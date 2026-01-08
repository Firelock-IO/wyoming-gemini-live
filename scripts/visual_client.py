
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
    "is_talking": False,
    "logs": []
}

websockets = set()
mic_event = asyncio.Event()

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
    samples = np.frombuffer(data, dtype=np.int16)
    if len(samples) == 0:
        return 0.0
    floats = samples.astype(np.float32) / 32768.0
    rms = np.sqrt(np.mean(floats**2))
    return float(rms)

async def web_handler(request):
    with open("scripts/web/index.html", "r") as f:
        return web.Response(text=f.read(), content_type="text/html")

async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    websockets.add(ws)
    await broadcast_state()
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("command") == "toggle_mic":
                    if state["is_talking"]:
                        state["is_talking"] = False
                        mic_event.clear()
                    else:
                        state["is_talking"] = True
                        mic_event.set()
                    await broadcast_state()
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
        while True: await asyncio.sleep(1)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    # Output Audio Stream
    output_stream = sd.OutputStream(
        samplerate=args.rate, channels=1, dtype='int16', latency='low'
    )
    output_stream.start()

    async def receive_loop():
        add_log("Listening for audio response...")
        while True:
            event = await client.read_event()
            if event is None:
                add_log("Server disconnected")
                state["status"] = "Disconnected"
                stop_event.set()
                break
            
            _LOGGER.info(f"Received event: {event.type}") 

            if AudioChunk.is_type(event.type):
                chunk = AudioChunk.from_event(event) 
                audio_data = chunk.audio
                _LOGGER.info(f"Received AudioChunk: {len(audio_data)} bytes")
                
                rms = calculate_rms(audio_data)
                state["gemini_level"] = min(rms * 5, 1.0)
                
                output_stream.write(np.frombuffer(audio_data, dtype=np.int16))
            elif AudioStop.is_type(event.type):
                add_log("Audio Stop received")
                state["gemini_level"] = 0.0
            else:
                 _LOGGER.info(f"Ignored event: {event.type}")

            await broadcast_state()

    async def mic_loop():
        input_stream = sd.InputStream(
            samplerate=args.rate, channels=1, dtype='int16', blocksize=1024
        )
        input_stream.start()
        
        chunk_info = AudioChunk(rate=args.rate, width=2, channels=1, audio=b"", timestamp=0)

        while not stop_event.is_set():
            # Wait for "Talking" state
            if not state["is_talking"]:
                state["mic_level"] = 0.0
                await broadcast_state()
                await mic_event.wait()
                # Once activated, send Start
                add_log("Mic Started (Sending AudioStart)")
                await client.write_event(AudioStart(rate=args.rate, width=2, channels=1).event())

            # Read audio
            data, overflow = await loop.run_in_executor(None, input_stream.read, 1024)
            if overflow: pass
            
            rms = calculate_rms(bytes(data))
            state["mic_level"] = min(rms * 5, 1.0)
            
            # Send chunk if talking
            if state["is_talking"]:
                chunk_info.audio = bytes(data)
                await client.write_event(chunk_info.event())
            else:
                # Just stopped talking
                add_log("Mic Stopped (Sending AudioStop)")
                await client.write_event(AudioStop().event())
                # prevent spamming STOP
                mic_event.clear()

            await broadcast_state()

    await asyncio.gather(receive_loop(), mic_loop())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
