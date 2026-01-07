from __future__ import annotations

from google.genai import types


def build_tools() -> list[types.Tool]:
    """Tools exposed to Gemini.

    We keep a single, generic Home Assistant tool for reliability.
    """
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="control_home_assistant",
                    description=(
                        "Call a Home Assistant service to control devices. "
                        "Prefer entity_id from the provided device list."
                    ),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "domain": types.Schema(
                                type="STRING",
                                description="Home Assistant domain, e.g. light, switch, cover, climate, lock, scene, script",
                            ),
                            "service": types.Schema(
                                type="STRING",
                                description="Service name, e.g. turn_on, turn_off, toggle, set_temperature, open_cover",
                            ),
                            "entity_id": types.Schema(
                                type="STRING",
                                description="Exact entity_id for the target device (preferred).",
                            ),
                            "service_data_json": types.Schema(
                                type="STRING",
                                description=(
                                    "Optional JSON object (as a string) with extra service fields, "
                                    "e.g. {\"brightness\": 128} or {\"temperature\": 72}."
                                ),
                            ),
                        },
                        required=["domain", "service"],
                    ),
                )
            ]
        )
    ]
