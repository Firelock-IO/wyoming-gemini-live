
import argparse
import asyncio
import logging
import sys
import json
import time
import math
from aiohttp import web
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient

# Configure logging
logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger("visual_client")

try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    print("Missing dependencies: pip install sounddevice numpy aiohttp")
    sys.exit(1)

# Global State
state = {
    "mic_level": 0.0,
    "gemini_level": 0.0,
    "status": "Disconnected",
    "logs": []
}

websockets = set()

def add_log(msg):
    _LOGGER.info(msg)
    state["logs"].append(f"{time.strftime('%H:%M:%S')} {msg}")
    if len(state["logs"]) > 20:
        state["logs"].pop(0)

async def broadcast_state():
    if not websockets:
        return
    data = json.dumps({"type": "state", "data": state})
    for ws in list(websockets):
        try:
            await ws.send_str(data)
        except Exception:
            websockets.discard(ws)

def calculate_rms(data):
    """Calculate RMS amplitude from bytes."""
    # Convert bytes to int16 numpy array
    samples = np.frombuffer(data, dtype=np.int16)
    if len(samples) == 0:
        return 0.0
    # Normalize to 0.0 - 1.0 (float)
    floats = samples.astype(np.float32) / 32768.0
    rms = np.sqrt(np.mean(floats**2))
    return float(rms)

async def web_handler(request):
    """Serve the index.html."""
    with open("scripts/web/index.html", "r") as f:
        return web.Response(text=f.read(), content_type="text/html")

async def ws_handler(request):
    """Handle WebSocket connections."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    websockets.add(ws)
    await broadcast_state() # Send initial
    try:
        async for msg in ws:
            pass 
    finally:
        websockets.discard(ws)
    return ws

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="Host IP of the Add-on")
    parser.add_argument("--port", type=int, default=10700)
    parser.add_argument("--rate", type=int, default=16000)
    args = parser.parse_args()

    # Web Server Setup
    app = web.Application()
    app.router.add_get('/', web_handler)
    app.router.add_get('/ws', ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    add_log("Web UI started at http://localhost:8000")

    # Wyoming Client Setup
    state["status"] = "Connecting..."
    client = AsyncTcpClient(args.host, args.port)
    try:
        await client.connect()
        state["status"] = "Connected"
        add_log("Connected to Wyoming Server")
    except Exception as e:
        state["status"] = f"Error: {e}"
        add_log(f"Connection failed: {e}")
        # Keep web server running to show error
        while True: await asyncio.sleep(1)

    await client.write_event(AudioStart(rate=args.rate, width=2, channels=1).event())

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    # Output Audio Stream (Speaker)
    output_stream = sd.OutputStream(
        samplerate=args.rate, channels=1, dtype='int16'
    )
    output_stream.start()

    # Tasks
    async def receive_loop():
        add_log("Listening for audio response...")
        while True:
            event = await client.read_event()
            if event is None:
                add_log("Server disconnected")
                state["status"] = "Disconnected"
                stop_event.set()
                break
            
            if AudioChunk.is_type(event.type):
                chunk = AudioChunk.from_event(event) # audio attribute fixed in library usage?
                # Library uses .audio actually, checking my previous fix...
                # wait, library might use .audio or .data depending on version?
                # The User log showed 'AudioChunk' object has no attribute 'data'.
                # So it MUST be .audio.
                # In client connection we construct it. Here we read it.
                # AudioChunk definition in library uses 'audio' field.
                
                audio_data = chunk.audio
                rms = calculate_rms(audio_data)
                state["gemini_level"] = min(rms * 5, 1.0) # Boost visual level
                
                output_stream.write(np.frombuffer(audio_data, dtype=np.int16))
            elif AudioStop.is_type(event.type):
                add_log("Audio Stop received")
                state["gemini_level"] = 0.0

            await broadcast_state()

    async def mic_loop():
        add_log("Microphone active.")
        input_stream = sd.InputStream(
            samplerate=args.rate, channels=1, dtype='int16', blocksize=1024
        )
        input_stream.start()
        
        while not stop_event.is_set():
            data, overflow = await loop.run_in_executor(None, input_stream.read, 1024)
            if overflow:
                # ignore
                pass
            
            # Calculate RMS for visual
            rms = calculate_rms(bytes(data))
            state["mic_level"] = min(rms * 5, 1.0)
            
            # Send to server
            # FIX: Use 'audio' not 'data'
            chunk = AudioChunk(rate=args.rate, width=2, channels=1, audio=bytes(data), timestamp=0)
            await client.write_event(chunk.event())
            
            # Broadcast update periodically to avoid spamming? 
            # 16000hz / 1024 = 15 updates/sec. OK.
            await broadcast_state()

    await asyncio.gather(receive_loop(), mic_loop())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
