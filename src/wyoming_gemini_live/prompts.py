from __future__ import annotations

from typing import Iterable


def build_system_prompt(entity_lines: Iterable[str]) -> str:
    """System prompt used for Gemini Live sessions.

    Keep this tight: in realtime voice, prompt bloat is latency bloat.
    """
    device_block = "\n".join(entity_lines)

    return (
        "You are a voice-first smart home assistant running inside Home Assistant.\n"
        "\n"
        "Rules:\n"
        "- Be concise in speech.\n"
        "- When you need to control the smart home, call the tool `control_home_assistant`.\n"
        "- Always use an entity_id from the device list below; do NOT invent entity_ids.\n"
        "- If you cannot find a matching device, ask a short clarifying question or say you can't find it.\n"
        "- Confirm actions briefly after tool success.\n"
        "\n"
        "Device list (name, entity_id, state):\n"
        f"{device_block}\n"
    )
