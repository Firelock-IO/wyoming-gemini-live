#!/usr/bin/env python3
"""
Minimal diagnostic client for Wyoming Gemini Live.
Tests if audio can be sent and received.
"""
import argparse
import asyncio
import logging

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger("diag")

try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    print("pip install sounddevice numpy")
    exit(1)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=10700)
    args = parser.parse_args()

    RATE = 16000
    CHUNK = 1024

    _LOGGER.info("Connecting to %s:%s...", args.host, args.port)
    client = AsyncTcpClient(args.host, args.port)
    await client.connect()
    _LOGGER.info("Connected!")

    # Output stream for playing received audio
    output_stream = sd.OutputStream(samplerate=RATE, channels=1, dtype='int16', latency='low')
    output_stream.start()

    # Input stream for mic
    input_stream = sd.InputStream(samplerate=RATE, channels=1, dtype='int16', blocksize=CHUNK)
    input_stream.start()

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    recording = True

    async def receive_loop():
        """Just read events from server and print/play them."""
        _LOGGER.info("Starting receive loop...")
        while not stop.is_set():
            try:
                event = await asyncio.wait_for(client.read_event(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                _LOGGER.error("Read error: %s", e)
                break

            if event is None:
                _LOGGER.warning("Server closed connection")
                stop.set()
                break

            _LOGGER.info("EVENT: type=%s", event.type)

            if AudioChunk.is_type(event.type):
                chunk = AudioChunk.from_event(event)
                _LOGGER.info("  -> AudioChunk: %d bytes", len(chunk.audio))
                output_stream.write(np.frombuffer(chunk.audio, dtype=np.int16))
            elif AudioStart.is_type(event.type):
                _LOGGER.info("  -> AudioStart")
            elif AudioStop.is_type(event.type):
                _LOGGER.info("  -> AudioStop")

    async def send_loop():
        """Record 3 seconds of mic audio, send it, then wait for response."""
        nonlocal recording
        
        _LOGGER.info("Sending AudioStart...")
        await client.write_event(AudioStart(rate=RATE, width=2, channels=1).event())

        _LOGGER.info("Recording 3 seconds of audio... SPEAK NOW!")
        for i in range(int(3 * RATE / CHUNK)):
            data, _ = await loop.run_in_executor(None, input_stream.read, CHUNK)
            chunk = AudioChunk(rate=RATE, width=2, channels=1, audio=bytes(data), timestamp=0)
            await client.write_event(chunk.event())
            if i % 15 == 0:
                _LOGGER.debug("Sent chunk %d", i)

        _LOGGER.info("Sending AudioStop...")
        await client.write_event(AudioStop().event())

        _LOGGER.info("Waiting 10 seconds for response...")
        await asyncio.sleep(10)
        stop.set()

    try:
        await asyncio.gather(receive_loop(), send_loop())
    except KeyboardInterrupt:
        pass
    finally:
        input_stream.stop()
        output_stream.stop()
        _LOGGER.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
