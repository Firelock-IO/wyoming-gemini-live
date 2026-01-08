#!/usr/bin/env python3
"""
Google's OFFICIAL sample pattern - directly tests Gemini Live API.
If this works but our add-on doesn't, we have a bug.
If this also fails, it's an API/account issue.
"""
import os
import asyncio
import pyaudio
from google import genai
from google.genai import types

# Audio config
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"

# Get API key from env or hardcode for testing
API_KEY = os.environ.get("GEMINI_API_KEY", "REDACTED")

client = genai.Client(
    http_options={"api_version": "v1beta"},
    api_key=API_KEY,
)

CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
        )
    ),
)

pya = pyaudio.PyAudio()


class SimpleAudioTest:
    def __init__(self):
        self.audio_in_queue = None
        self.out_queue = None
        self.session = None
        self.audio_stream = None

    async def listen_audio(self):
        """Capture microphone audio."""
        mic_info = pya.get_default_input_device_info()
        self.audio_stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=SEND_SAMPLE_RATE,
            input=True,
            input_device_index=mic_info["index"],
            frames_per_buffer=CHUNK_SIZE,
        )
        print("🎤 Microphone active - SPEAK NOW!")
        while True:
            data = await asyncio.to_thread(
                self.audio_stream.read, CHUNK_SIZE, exception_on_overflow=False
            )
            await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})

    async def send_realtime(self):
        """Send audio to Gemini."""
        while True:
            msg = await self.out_queue.get()
            await self.session.send(input=msg)

    async def receive_audio(self):
        """Receive responses from Gemini."""
        print("👂 Listening for Gemini responses...")
        while True:
            turn = self.session.receive()
            async for response in turn:
                if data := response.data:
                    print(f"📢 Received audio: {len(data)} bytes")
                    self.audio_in_queue.put_nowait(data)
                if text := response.text:
                    print(f"💬 Text: {text}")
            # On turn complete, clear queue (for interruption support)
            while not self.audio_in_queue.empty():
                self.audio_in_queue.get_nowait()

    async def play_audio(self):
        """Play received audio."""
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
        )
        while True:
            bytestream = await self.audio_in_queue.get()
            await asyncio.to_thread(stream.write, bytestream)

    async def run(self):
        print(f"🔌 Connecting to Gemini Live: {MODEL}")
        try:
            async with (
                client.aio.live.connect(model=MODEL, config=CONFIG) as session,
                asyncio.TaskGroup() as tg,
            ):
                self.session = session
                self.audio_in_queue = asyncio.Queue()
                self.out_queue = asyncio.Queue(maxsize=5)
                
                print("✅ Connected! Speak into your microphone.")
                print("   (Press Ctrl+C to stop)")
                
                tg.create_task(self.send_realtime())
                tg.create_task(self.listen_audio())
                tg.create_task(self.receive_audio())
                tg.create_task(self.play_audio())
                
                # Keep running
                while True:
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            if self.audio_stream:
                self.audio_stream.close()
            pya.terminate()
            print("\n👋 Disconnected.")


if __name__ == "__main__":
    print("=" * 50)
    print("GOOGLE SAMPLE DIRECT TEST")
    print("This bypasses our add-on entirely.")
    print("=" * 50)
    try:
        asyncio.run(SimpleAudioTest().run())
    except KeyboardInterrupt:
        print("\nStopped by user.")
