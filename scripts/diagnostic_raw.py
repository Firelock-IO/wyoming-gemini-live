
import asyncio
import logging
import time

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger("diagnostic")

async def main():
    host = "192.168.1.225"
    port = 10700
    
    _LOGGER.info(f"Connecting to {host}:{port}...")
    reader, writer = await asyncio.open_connection(host, port)
    _LOGGER.info("Connected!")

    # 1. Send AudioStart
    # Wyoming event format: {json_length}\n{json_content}
    content = '{"type": "audio-start", "data": {"rate": 16000, "width": 2, "channels": 1}}'
    writer.write(f"{len(content)}\n{content}".encode())
    await writer.drain()
    _LOGGER.info("Sent AudioStart")

    # 2. Send 1 second of silence
    # AudioChunk format: {header_len}\n{header_json}{payload_len}\n{payload_bytes}
    header = '{"type": "audio-chunk", "data": {"rate": 16000, "width": 2, "channels": 1}}'
    audio = b"\x00" * 32000 # 1 second
    writer.write(f"{len(header)}\n{header}".encode())
    writer.write(f"{len(audio)}\n".encode())
    writer.write(audio)
    await writer.drain()
    _LOGGER.info("Sent 1s of silence")

    # 3. Send AudioStop
    content = '{"type": "audio-stop", "data": {}}'
    writer.write(f"{len(content)}\n{content}".encode())
    await writer.drain()
    _LOGGER.info("Sent AudioStop")

    # 4. Listen for response
    _LOGGER.info("Listening for raw bytes for 10 seconds...")
    try:
        while True:
            data = await asyncio.wait_for(reader.read(4096), timeout=10)
            if not data:
                _LOGGER.info("Connection closed by server")
                break
            _LOGGER.info(f"RECEIVED {len(data)} BYTES: {data[:50]!r}...")
    except asyncio.TimeoutError:
        _LOGGER.info("Timed out waiting for data")
    finally:
        writer.close()
        await writer.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
