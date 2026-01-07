from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Iterator

import numpy as np
from scipy import signal


PCM16_DTYPE = np.int16
PCM16_MAX = np.iinfo(PCM16_DTYPE).max
PCM16_MIN = np.iinfo(PCM16_DTYPE).min


def resample_pcm16(
    pcm: bytes,
    src_rate_hz: int,
    dst_rate_hz: int,
) -> bytes:
    """Resample 16-bit PCM mono audio.

    Uses polyphase resampling for better streaming quality than naive FFT resample.
    """
    if src_rate_hz == dst_rate_hz:
        return pcm
    if not pcm:
        return b""

    x = np.frombuffer(pcm, dtype=PCM16_DTYPE).astype(np.float32)

    g = math.gcd(src_rate_hz, dst_rate_hz)
    up = dst_rate_hz // g
    down = src_rate_hz // g

    # Polyphase resampling. Returns float64 by default; keep float32.
    y = signal.resample_poly(x, up=up, down=down).astype(np.float32)

    # Clip to int16 range
    y = np.clip(y, PCM16_MIN, PCM16_MAX)
    return y.astype(PCM16_DTYPE).tobytes()


def iter_silence_chunks(
    duration_ms: int,
    sample_rate_hz: int,
    chunk_size_samples: int,
) -> Iterator[bytes]:
    """Yield PCM16 silence chunks covering duration_ms."""
    if duration_ms <= 0:
        return
    total_samples = int((duration_ms / 1000.0) * sample_rate_hz)
    silence = np.zeros(chunk_size_samples, dtype=PCM16_DTYPE).tobytes()
    full_chunks = total_samples // chunk_size_samples
    remainder = total_samples % chunk_size_samples

    for _ in range(full_chunks):
        yield silence
    if remainder:
        yield np.zeros(remainder, dtype=PCM16_DTYPE).tobytes()
