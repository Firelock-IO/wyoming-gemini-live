#!/usr/bin/env python3
"""
Direct Gemini Live test - TRUE real-time streaming.
Buffers responses and plays them only after you stop talking.
"""
import os
import asyncio
import sounddevice as sd
import numpy as np
from google import genai
from google.genai import types

SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
RECORD_SECONDS = 5

MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("ERROR: Set GEMINI_API_KEY environment variable")
    exit(1)

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


class GeminiTest:
    def __init__(self):
        self.out_queue = asyncio.Queue(maxsize=5)
        self.audio_in_queue = asyncio.Queue()
        self.session = None
        self.done_recording = False
        self.done_receiving = False

    async def listen_mic(self):
        """Capture mic and queue for sending."""
        loop = asyncio.get_running_loop()
        stream = sd.InputStream(
            samplerate=SEND_SAMPLE_RATE,
            channels=1,
            dtype='int16',
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        print(f"🎤 Recording for {RECORD_SECONDS} seconds... SPEAK NOW!")
        
        count = 0
        target = int(RECORD_SECONDS * SEND_SAMPLE_RATE / CHUNK_SIZE)
        while count < target:
            data, _ = await loop.run_in_executor(None, stream.read, CHUNK_SIZE)
            await self.out_queue.put({"data": bytes(data), "mime_type": "audio/pcm"})
            count += 1
            if count % 20 == 0:
                print(f"  📤 {count * CHUNK_SIZE / SEND_SAMPLE_RATE:.1f}s...")
        
        stream.stop()
        print("✅ Done recording")
        self.done_recording = True

    async def send_audio(self):
        """Send queued audio to Gemini."""
        while not (self.done_recording and self.out_queue.empty()):
            try:
                msg = await asyncio.wait_for(self.out_queue.get(), timeout=0.1)
                await self.session.send(input=msg)
            except asyncio.TimeoutError:
                continue
        print("✅ All audio sent to Gemini")

    async def receive_audio(self):
        """Receive from Gemini and queue audio for playback."""
        print("👂 Listening for Gemini...")
        response_count = 0
        
        while not self.done_receiving:
            try:
                turn = self.session.receive()
                async for response in turn:
                    if data := response.data:
                        self.audio_in_queue.put_nowait(data)
                        response_count += 1
                        if response_count % 20 == 0:
                            print(f"  📥 Received {response_count} chunks...")
                    if text := response.text:
                        print(f"  💬 {text}")
                
                print(f"🔄 Turn complete ({response_count} chunks)")
                if response_count > 0:
                    self.done_receiving = True
            except asyncio.CancelledError:
                break
            except Exception as e:
                if "close" in str(e).lower():
                    break
                print(f"  Error: {e}")
                break

    async def play_buffered_audio(self):
        """Play all buffered audio after receiving is done."""
        # Wait for responses to come in
        await asyncio.sleep(1)
        while not self.done_receiving:
            await asyncio.sleep(0.5)
        
        if self.audio_in_queue.empty():
            print("❌ No audio received from Gemini")
            return
        
        print("🔊 Playing response...")
        chunks = []
        while not self.audio_in_queue.empty():
            chunks.append(self.audio_in_queue.get_nowait())
        
        all_audio = b"".join(chunks)
        audio_array = np.frombuffer(all_audio, dtype=np.int16)
        
        sd.play(audio_array, samplerate=RECEIVE_SAMPLE_RATE)
        sd.wait()
        print("✅ Playback done!")

    async def run(self):
        print("=" * 60)
        print("GEMINI LIVE - REAL-TIME STREAMING TEST")
        print("=" * 60)
        print("⚠️  Use headphones to prevent feedback!")
        print("")
        
        async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:
            self.session = session
            print("✅ Connected!\n")
            
            # Run all tasks
            await asyncio.gather(
                self.listen_mic(),
                self.send_audio(),
                self.receive_audio(),
                self.play_buffered_audio(),
                return_exceptions=True
            )
        
        print("\n👋 Done!")


if __name__ == "__main__":
    try:
        asyncio.run(GeminiTest().run())
    except KeyboardInterrupt:
        print("\nStopped.")
