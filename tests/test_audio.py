
import pytest
import numpy as np
from wyoming_gemini_live.audio import resample_pcm16, iter_silence_chunks, PCM16_DTYPE

def test_resample_simple():
    # 16kHz -> 16kHz (no change)
    data = np.zeros(100, dtype=PCM16_DTYPE).tobytes()
    out = resample_pcm16(data, 16000, 16000)
    assert out == data

def test_resample_upsample():
    # 16kHz -> 24kHz
    # 16 samples input -> 24 samples output
    data = np.zeros(16, dtype=PCM16_DTYPE).tobytes()
    out = resample_pcm16(data, 16000, 24000)
    assert len(out) == 24 * 2  # 2 bytes per sample

def test_resample_downsample():
    # 24kHz -> 16kHz
    # 24 samples input -> 16 samples output
    data = np.zeros(24, dtype=PCM16_DTYPE).tobytes()
    out = resample_pcm16(data, 24000, 16000)
    assert len(out) == 16 * 2

def test_iter_silence():
    # 100ms at 16kHz = 1600 samples
    chunks = list(iter_silence_chunks(100, 16000, 160))
    # 1600 / 160 = 10 chunks
    assert len(chunks) == 10
    assert len(chunks[0]) == 160 * 2
    assert all(c == b'\x00' * 320 for c in chunks)
