from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


_ADDON_OPTIONS_PATH = Path("/data/options.json")


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _first(*values: str | None) -> str | None:
    for v in values:
        if v is not None and str(v).strip() != "":
            return v
    return None


def load_addon_options(path: Path = _ADDON_OPTIONS_PATH) -> dict[str, Any]:
    """Load Home Assistant add-on options (if running under HAOS).

    HA add-ons commonly expose configuration via /data/options.json.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@dataclass(frozen=True)
class Settings:
    # Network
    host: str = "0.0.0.0"
    port: int = 10700

    # Gemini
    gemini_api_key: str = ""
    model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    gemini_api_version: str = "v1beta"

    # Home Assistant
    ha_url: str = "http://homeassistant.local:8123"
    ha_token: str = ""

    # Context / tools
    allowed_domains: tuple[str, ...] = (
        "light",
        "switch",
        "cover",
        "climate",
        "lock",
        "scene",
        "script",
    )
    entity_allowlist: tuple[str, ...] = ()
    entity_blocklist: tuple[str, ...] = ()
    max_context_entities: int = 200

    # Audio
    input_sample_rate_hz: int = 16000
    output_sample_rate_hz: int = 16000
    gemini_output_sample_rate_hz: int = 24000

    # Voice / streaming behavior
    silence_tail_ms: int = 600  # send a small silence tail after AudioStop to trigger VAD
    audio_chunk_size: int = 1024  # PCM frames per chunk (samples)

    # Logging
    log_level: str = "info"

    @staticmethod
    def from_env_and_addon_options() -> "Settings":
        options = load_addon_options()

        gemini_api_key = _first(
            _env("GEMINI_API_KEY"),
            _env("GOOGLE_API_KEY"),
            options.get("gemini_api_key") if isinstance(options, Mapping) else None,
        )
        if not gemini_api_key:
            gemini_api_key = ""

        ha_token = _first(
            _env("HA_TOKEN"),
            options.get("ha_token") if isinstance(options, Mapping) else None,
        )
        if not ha_token:
            ha_token = ""

        ha_url = _first(
            _env("HA_URL"),
            options.get("ha_url") if isinstance(options, Mapping) else None,
            "http://homeassistant.local:8123",
        ) or "http://homeassistant.local:8123"

        model = _first(
            _env("MODEL"),
            options.get("model") if isinstance(options, Mapping) else None,
            "gemini-2.5-flash-native-audio-preview-12-2025",
        ) or "gemini-2.5-flash-native-audio-preview-12-2025"

        log_level = _first(
            _env("LOG_LEVEL"),
            options.get("log_level") if isinstance(options, Mapping) else None,
            "info",
        ) or "info"

        # Port
        port_str = _first(_env("PORT"), str(options.get("port")) if isinstance(options, Mapping) and "port" in options else None)
        try:
            port = int(port_str) if port_str else 10700
        except Exception:
            port = 10700

        # Allowed domains
        allowed_domains: Sequence[str] | None = None
        if isinstance(options, Mapping) and isinstance(options.get("allowed_domains"), list):
            allowed_domains = [str(x) for x in options["allowed_domains"]]
        else:
            allowed_domains = _split_csv(_env("ALLOWED_DOMAINS"))

        if not allowed_domains:
            allowed_domains = ["light", "switch", "cover", "climate", "lock", "scene", "script"]

        # Allow/block patterns
        if isinstance(options, Mapping) and isinstance(options.get("entity_allowlist"), list):
            entity_allowlist = tuple(str(x) for x in options["entity_allowlist"])
        else:
            entity_allowlist = tuple(_split_csv(_env("ENTITY_ALLOWLIST")))

        if isinstance(options, Mapping) and isinstance(options.get("entity_blocklist"), list):
            entity_blocklist = tuple(str(x) for x in options["entity_blocklist"])
        else:
            entity_blocklist = tuple(_split_csv(_env("ENTITY_BLOCKLIST")))

        # Max context entities
        max_ctx_str = _first(
            _env("MAX_CONTEXT_ENTITIES"),
            str(options.get("max_context_entities")) if isinstance(options, Mapping) and "max_context_entities" in options else None,
        )
        try:
            max_context_entities = int(max_ctx_str) if max_ctx_str else 200
        except Exception:
            max_context_entities = 200

        # Silence tail (ms)
        silence_tail_str = _first(_env("SILENCE_TAIL_MS"), str(options.get("silence_tail_ms")) if isinstance(options, Mapping) and "silence_tail_ms" in options else None)
        try:
            silence_tail_ms = int(silence_tail_str) if silence_tail_str else 600
        except Exception:
            silence_tail_ms = 600

        # Chunk size (samples)
        chunk_str = _first(_env("AUDIO_CHUNK_SIZE"), str(options.get("audio_chunk_size")) if isinstance(options, Mapping) and "audio_chunk_size" in options else None)
        try:
            audio_chunk_size = int(chunk_str) if chunk_str else 1024
        except Exception:
            audio_chunk_size = 1024

        # Audio rates
        in_rate_str = _first(_env("INPUT_SAMPLE_RATE_HZ"))
        out_rate_str = _first(_env("OUTPUT_SAMPLE_RATE_HZ"))

        try:
            input_rate = int(in_rate_str) if in_rate_str else 16000
        except Exception:
            input_rate = 16000

        try:
            output_rate = int(out_rate_str) if out_rate_str else 16000
        except Exception:
            output_rate = 16000

        return Settings(
            host="0.0.0.0",
            port=port,
            gemini_api_key=gemini_api_key,
            model=model,
            gemini_api_version="v1beta",
            ha_url=ha_url,
            ha_token=ha_token,
            allowed_domains=tuple(allowed_domains),
            entity_allowlist=entity_allowlist,
            entity_blocklist=entity_blocklist,
            max_context_entities=max_context_entities,
            input_sample_rate_hz=input_rate,
            output_sample_rate_hz=output_rate,
            silence_tail_ms=silence_tail_ms,
            audio_chunk_size=audio_chunk_size,
            log_level=log_level,
        )
