from __future__ import annotations

import asyncio
import logging
import sys
from functools import partial

from wyoming.server import AsyncServer

from .config import Settings
from .wyoming_handler import GeminiLiveEventHandler


def _configure_logging(level: str) -> None:
    level = (level or "info").lower()
    numeric = {
        "trace": logging.DEBUG,  # wyoming doesn't define TRACE; map to DEBUG
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }.get(level, logging.INFO)

    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _async_main() -> None:
    settings = Settings.from_env_and_addon_options()
    _configure_logging(settings.log_level)

    if not settings.gemini_api_key:
        logging.getLogger(__name__).error("Missing GEMINI_API_KEY (or add-on option gemini_api_key).")
        sys.exit(2)

    server = AsyncServer.from_uri(f"tcp://{settings.host}:{settings.port}")
    logging.getLogger(__name__).info("Listening on %s:%s", settings.host, settings.port)

    await server.run(partial(GeminiLiveEventHandler, settings))


def main() -> None:
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
