from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

from google import genai
from google.genai import types

from .audio import iter_silence_chunks, resample_pcm16
from .config import Settings
from .ha import HomeAssistantClient
from .prompts import build_system_prompt
from .tools import build_tools


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutputAudioCallbacks:
    on_start: Callable[[int], Awaitable[None]]
    on_chunk: Callable[[bytes, int], Awaitable[None]]
    on_stop: Callable[[], Awaitable[None]]


class GeminiLiveController:
    """Maintains a Gemini Live session and streams audio in/out."""

    def __init__(
        self,
        settings: Settings,
        ha: HomeAssistantClient,
        output_callbacks: OutputAudioCallbacks,
    ) -> None:
        self._settings = settings
        self._ha = ha
        self._out = output_callbacks

        self._client = genai.Client(
            http_options={"api_version": settings.gemini_api_version},
            api_key=settings.gemini_api_key,
        )

        self._input_audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)
        self._stop_evt = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

        self._output_stream_open = False
        self._last_input_ts = time.monotonic()

        # If the user starts speaking while the model is speaking,
        # we stop forwarding audio output immediately.
        self._barge_in = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def ensure_running(self) -> None:
        if self.running:
            return
        self._stop_evt.clear()
        self._task = asyncio.create_task(self._run(), name="gemini-live-session")

    async def stop(self) -> None:
        self._stop_evt.set()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    def notify_barge_in(self) -> None:
        # Called when the user starts talking.
        self._barge_in = True

    async def enqueue_audio(self, pcm16: bytes, src_rate_hz: int) -> None:
        """Queue audio to send to Gemini (resampling to 16k if needed)."""
        await self.ensure_running()
        self._last_input_ts = time.monotonic()
        self._barge_in = False  # user is speaking; allow the model to interrupt itself

        if src_rate_hz != self._settings.input_sample_rate_hz:
            pcm16 = resample_pcm16(pcm16, src_rate_hz=src_rate_hz, dst_rate_hz=self._settings.input_sample_rate_hz)

        # If the queue is full, drop oldest to keep latency low.
        if self._input_audio_queue.full():
            try:
                _ = self._input_audio_queue.get_nowait()
            except Exception:
                pass

        await self._input_audio_queue.put(pcm16)

    async def end_user_turn(self) -> None:
        """Send a short silence tail so the Live API VAD can close the turn."""
        await self.ensure_running()
        for chunk in iter_silence_chunks(
            duration_ms=self._settings.silence_tail_ms,
            sample_rate_hz=self._settings.input_sample_rate_hz,
            chunk_size_samples=self._settings.audio_chunk_size,
        ):
            # silence is already at 16k
            if self._input_audio_queue.full():
                try:
                    _ = self._input_audio_queue.get_nowait()
                except Exception:
                    pass
            await self._input_audio_queue.put(chunk)

    async def _run(self) -> None:
        if not self._settings.gemini_api_key:
            _LOGGER.error("GEMINI_API_KEY is not set; cannot start Live session.")
            return

        # Build system prompt with HA context injection.
        entity_lines = await self._ha.build_entity_context_lines(
            allowed_domains=self._settings.allowed_domains,
            allowlist=self._settings.entity_allowlist,
            blocklist=self._settings.entity_blocklist,
            max_entities=self._settings.max_context_entities,
        )
        system_prompt = build_system_prompt(entity_lines)

        tools = build_tools()

        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            tools=tools,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Zephyr")
                )
            ),
            system_instruction=types.Content(
                role="user",
                parts=[types.Part.from_text(text=system_prompt)],
            ),
        )

        model = self._settings.model
        # Accept both "gemini-..." and "models/gemini-..."
        if not model.startswith("models/"):
            model = f"models/{model}"

        _LOGGER.info("Connecting to Gemini Live: %s", model)

        try:
            async with self._client.aio.live.connect(model=model, config=live_config) as session:
                send_task = asyncio.create_task(self._send_loop(session), name="gemini-send-loop")
                recv_task = asyncio.create_task(self._recv_loop(session), name="gemini-recv-loop")

                await self._stop_evt.wait()

                send_task.cancel()
                recv_task.cancel()
                await asyncio.gather(send_task, recv_task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Gemini Live session crashed")
        finally:
            # Ensure we close any open output audio stream
            if self._output_stream_open:
                try:
                    await self._out.on_stop()
                except Exception:
                    pass
                self._output_stream_open = False

    async def _send_loop(self, session: Any) -> None:
        """Drain input audio queue and send to Gemini."""
        rate = self._settings.input_sample_rate_hz
        while True:
            pcm16 = await self._input_audio_queue.get()

            # Use send_realtime_input with audio dict - this produces the correct wire format
            # that worked at 16:16 with {"realtime_input": {"audio": {...}}}
            await session.send_realtime_input(audio={"data": pcm16, "mime_type": "audio/pcm"})

    async def _recv_loop(self, session: Any) -> None:
        """Receive turns from Gemini and forward audio + tool calls."""
        while True:
            turn = session.receive()
            # Reset barge-in flag at the start of a model turn.
            # If the user starts speaking, the wyoming handler sets it again.
            self._barge_in = False

            saw_audio = False

            try:
                async for msg in turn:
                    # Fast-path: audio bytes show up as msg.data in many samples.
                    audio_bytes: bytes | None = None
                    if getattr(msg, "data", None):
                        if isinstance(msg.data, (bytes, bytearray)):
                            audio_bytes = bytes(msg.data)

                    # Slow-path: structured server content (model_turn parts)
                    if audio_bytes is None:
                        server_content = getattr(msg, "server_content", None)
                        model_turn = getattr(server_content, "model_turn", None) if server_content else None
                        if model_turn and getattr(model_turn, "parts", None):
                            for part in model_turn.parts:
                                inline = getattr(part, "inline_data", None)
                                if inline and isinstance(getattr(inline, "data", None), (bytes, bytearray)):
                                    audio_bytes = bytes(inline.data)
                                    break

                    if audio_bytes:
                        saw_audio = True
                        if self._barge_in:
                            # User started talking; stop forwarding model speech.
                            continue

                        # Open an output stream on first audio chunk
                        if not self._output_stream_open:
                            await self._out.on_start(self._settings.output_sample_rate_hz)
                            self._output_stream_open = True

                            # Gemini audio is 24kHz PCM16 mono; resample to configured output rate.
                            _LOGGER.debug("Resampling %d bytes of audio...", len(audio_bytes))
                            pcm_out = resample_pcm16(
                                audio_bytes,
                                src_rate_hz=self._settings.gemini_output_sample_rate_hz,
                                dst_rate_hz=self._settings.output_sample_rate_hz,
                            )
                            _LOGGER.debug("Resampled to %d bytes. Sending to client...", len(pcm_out))
                            await self._out.on_chunk(pcm_out, self._settings.output_sample_rate_hz)
                        else:
                            # Gemini audio is 24kHz PCM16 mono; resample to configured output rate.
                            pcm_out = resample_pcm16(
                                audio_bytes,
                                src_rate_hz=self._settings.gemini_output_sample_rate_hz,
                                dst_rate_hz=self._settings.output_sample_rate_hz,
                            )
                            await self._out.on_chunk(pcm_out, self._settings.output_sample_rate_hz)

                    # Text can show up too (debug)
                    if getattr(msg, "text", None):
                        _LOGGER.debug("Gemini text: %s", msg.text)

                    # Tool calls
                    tool_call = getattr(msg, "tool_call", None)
                    if tool_call and getattr(tool_call, "function_calls", None):
                        await self._handle_tool_calls(session, tool_call.function_calls)

            except Exception as e:
                # Check for ConnectionClosedOK (generic check to avoid importing websockets)
                if "ConnectionClosedOK" in type(e).__name__:
                    _LOGGER.info("Gemini connection closed gracefully.")
                    break
                raise

            # Turn complete.
            if self._output_stream_open:
                await self._out.on_stop()
                self._output_stream_open = False

            # If Gemini produced no audio but did tool calls/text, we do nothing.
            # The model typically speaks after tool responses; if not, that's fine.

    async def _handle_tool_calls(self, session: Any, function_calls: Any) -> None:
        responses: list[types.FunctionResponse] = []

        for fc in function_calls:
            fc_id = getattr(fc, "id", None)
            fc_name = getattr(fc, "name", None)
            fc_args = getattr(fc, "args", None)

            if fc_name != "control_home_assistant":
                # Unknown tool (future-proofing)
                responses.append(
                    types.FunctionResponse(
                        id=fc_id,
                        name=str(fc_name or "unknown"),
                        response={"ok": False, "error": "Unknown tool"},
                    )
                )
                continue

            ok, result = await self._execute_control_home_assistant(fc_args)
            responses.append(
                types.FunctionResponse(
                    id=fc_id,
                    name="control_home_assistant",
                    response={"ok": ok, "result": result},
                )
            )

        if responses:
            # SDK compatibility: prefer `send_tool_response`, fall back to generic `send`.
            if hasattr(session, "send_tool_response"):
                await session.send_tool_response(function_responses=responses)
            else:
                await session.send(input=types.LiveClientToolResponse(function_responses=responses))

    async def _execute_control_home_assistant(self, args: Any) -> tuple[bool, str]:
        if not isinstance(args, Mapping):
            return (False, "Invalid tool args (expected object)")

        domain = str(args.get("domain", "")).strip()
        service = str(args.get("service", "")).strip()
        entity_id = str(args.get("entity_id", "")).strip()
        service_data_json = args.get("service_data_json")

        data: dict[str, Any] = {}
        if entity_id:
            data["entity_id"] = entity_id

        if isinstance(service_data_json, str) and service_data_json.strip():
            try:
                extra = json.loads(service_data_json)
                if isinstance(extra, Mapping):
                    data.update(dict(extra))
            except Exception:
                # Don't fail the call; just ignore malformed JSON.
                pass

        ok, msg = await self._ha.call_service(domain=domain, service=service, data=data)
        return (ok, msg)
