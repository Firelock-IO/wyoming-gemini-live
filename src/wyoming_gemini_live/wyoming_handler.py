from __future__ import annotations

import asyncio
import logging
from typing import Any

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Describe
from wyoming.server import AsyncEventHandler

from .config import Settings
from .gemini import GeminiLiveController, OutputAudioCallbacks
from .ha import HomeAssistantClient


_LOGGER = logging.getLogger(__name__)


class GeminiLiveEventHandler(AsyncEventHandler):
    """Wyoming TCP event handler.

    This handler expects a client that streams raw PCM16 audio via:
      audio-start -> audio-chunk* -> audio-stop

    The handler streams audio to Gemini Live, then streams Gemini's audio back to
    the client using the same audio-start/chunk/stop event types.

    NOTE: This is a *voice-assistant gateway*, not a classic Wyoming STT/TTS service.
    """

    def __init__(self, settings: Settings, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._settings = settings
        self._ha = HomeAssistantClient(settings.ha_url, settings.ha_token)

        self._input_rate_hz = settings.input_sample_rate_hz

        self._gemini = GeminiLiveController(
            settings=settings,
            ha=self._ha,
            output_callbacks=OutputAudioCallbacks(
                on_start=self._send_audio_start,
                on_chunk=self._send_audio_chunk,
                on_stop=self._send_audio_stop,
            ),
        )

    async def run(self) -> None:
        try:
            await super().run()
        finally:
            await self._gemini.stop()

    async def handle_event(self, event: Event) -> bool:
        # Some clients will start with Describe; we just ack (no Info yet).
        if Describe.is_type(event.type):
            _LOGGER.debug("Received Describe (no Info response implemented yet).")
            return True

        if AudioStart.is_type(event.type):
            start = AudioStart.from_event(event)
            self._input_rate_hz = int(getattr(start, "rate", self._settings.input_sample_rate_hz))
            _LOGGER.debug("AudioStart: rate=%s", self._input_rate_hz)

            # Barge-in: if the model is talking, stop forwarding its audio immediately.
            self._gemini.notify_barge_in()

            await self._gemini.ensure_running()
            return True

        if AudioChunk.is_type(event.type):
            chunk = AudioChunk.from_event(event)
            rate = int(getattr(chunk, "rate", self._input_rate_hz))
            await self._gemini.enqueue_audio(chunk.audio, src_rate_hz=rate)
            return True

        if AudioStop.is_type(event.type):
            _LOGGER.debug("AudioStop")
            await self._gemini.end_user_turn()
            return True

        # Unknown event type → close connection
        _LOGGER.debug("Unhandled event type: %s", event.type)
        return False

    # ---------------------------------------------------------------------
    # Output (Gemini -> Client)
    # ---------------------------------------------------------------------

    async def _send_audio_start(self, rate_hz: int) -> None:
        # PCM16 mono
        await self.write_event(AudioStart(rate=rate_hz, width=2, channels=1).event())

    async def _send_audio_chunk(self, pcm16: bytes, rate_hz: int) -> None:
    async def _send_audio_chunk(self, pcm16: bytes, rate_hz: int) -> None:
        _LOGGER.debug("Sending AudioChunk (%d bytes) to client", len(pcm16))
        await self.write_event(AudioChunk(rate=rate_hz, audio=pcm16, timestamp=0).event())
        _LOGGER.debug("AudioChunk sent.")

    async def _send_audio_stop(self) -> None:
        await self.write_event(AudioStop().event())
