
import argparse
import asyncio
import logging
import sys
from typing import Optional

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.event import Event

# You may need: pip install sounddevice numpy
try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    print("Missing dependencies. Please run: pip install sounddevice numpy")
    sys.exit(1)

_LOGGER = logging.getLogger("client")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", help="Host IP (optional, defaults to auto-discovery)")
    parser.add_argument("--port", type=int, default=10700)
    parser.add_argument("--rate", type=int, default=16000)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    
    if args.host:
        # User specified host
        print(f"Connecting to {args.host}:{args.port}...")
        client = AsyncTcpClient(args.host, args.port)
        try:
            await client.connect()
            print("Connected! Speak into your microphone.")
        except ConnectionRefusedError:
            print(f"Error: Could not connect to {args.host}:{args.port}. Is the server running?")
            return
    else:
        # Auto-discovery
        from zeroconf import Zeroconf, ServiceBrowser
        import time
        
        print("Scanning for Wyoming servers (mDNS)...")
        zeroconf = Zeroconf()
        discovered = []

        class Listener:
            def remove_service(self, zeroconf, type, name):
                pass
            def add_service(self, zeroconf, type, name):
                info = zeroconf.get_service_info(type, name)
                if info and info.addresses:
                    # Convert bytes IP to string
                    import socket
                    ip = socket.inet_ntoa(info.addresses[0])
                    discovered.append((ip, info.port, name))
                    
        browser = ServiceBrowser(zeroconf, "_wyoming._tcp.local.", Listener())
        
        # Scan for 3 seconds
        end_time = time.time() + 3
        while time.time() < end_time and not discovered:
            await asyncio.sleep(0.5)
            
        zeroconf.close()
        
        if not discovered:
            print("No Wyoming services found via discovery. Try specifying --host.")
            return
            
        # Pick first
        host, port, name = discovered[0]
        print(f"Discovered {name} at {host}:{port}")
        
        client = AsyncTcpClient(host, port)
        try:
            await client.connect()
            print("Connected! Speak into your microphone.")
        except ConnectionRefusedError:
            print(f"Error: Could not connect to {host}:{port}.")
            return

    reader, writer = client.get_reader_writer()
    
    # Send AudioStart
    await client.write_event(AudioStart(rate=args.rate, width=2, channels=1).event())
    
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    # Queue for outgoing audio
    audio_queue = asyncio.Queue()

    def audio_callback(indata, outdata, frames, time, status):
        """Callback for sounddevice."""
        if status:
            print(status, file=sys.stderr)
        
        # Put microphone data into queue
        loop.call_soon_threadsafe(audio_queue.put_nowait, bytes(indata))
        
        # We don't play audio here; we play it when we receive it from network
        # But sounddevice stream is duplex. We need a way to feed 'outdata'.
        # For simplicity, we'll use a globally managed buffer or queue for playback
        # if using a full duplex stream.
        # However, to keep it simple, let's just record/send.
        # Playback is tricky in callback if we don't have the data ready.
        outdata.fill(0)

    # Simplified approach: Separate streams for read/write might be easier, 
    # but duplex ensures sync.
    # To handle playback, we'll use a separate output stream or queue.
    # Let's try to just send audio for now and print received events.
    
    # Better demo: Just use raw input/output streams with sounddevice in blocking mode
    # inside async executor? No.
    
    # Real "chat" feel needs simultaneous mic and speaker.
    # Let's use two streams.
    
    # Output Stream (Speaker)
    output_stream = sd.OutputStream(
        samplerate=args.rate,
        channels=1,
        dtype='int16',
    )
    output_stream.start()
    
    async def receive_loop():
        """Receive audio from server and play it."""
        print("Listening for audio response...")
        while True:
            event = await client.read_event()
            if event is None:
                print("Connection closed by server")
                stop_event.set()
                break
            
            if AudioChunk.is_type(event.type):
                chunk = AudioChunk.from_event(event)
                # Play audio
                output_stream.write(np.frombuffer(chunk.data, dtype=np.int16))
            elif AudioStop.is_type(event.type):
                print("Audio Stop received")
            else:
                print(f"Received: {event.type}")

    # Input Stream (Mic)
    # We will read from mic in chunks and send to server
    
    async def mic_loop():
        print("Microphone active. Speak now! (Ctrl+C to stop)")
        input_stream = sd.InputStream(
            samplerate=args.rate,
            channels=1,
            dtype='int16',
            blocksize=1024
        )
        input_stream.start()
        
        while not stop_event.is_set():
            # Blocking read, run in executor
            data, overflow = await loop.run_in_executor(None, input_stream.read, 1024)
            if overflow:
                print("Audio overflow")
                
            chunk = AudioChunk(rate=args.rate, data=bytes(data), timestamp=0)
            await client.write_event(chunk.event())
            
    # Run both
    tasks = [
        asyncio.create_task(receive_loop()),
        asyncio.create_task(mic_loop())
    ]
    
    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("Closing...")
        output_stream.stop()
        output_stream.close()
        # client close...
        
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
