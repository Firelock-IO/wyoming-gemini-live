from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import aiohttp


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntityView:
    entity_id: str
    name: str
    state: str
    domain: str


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def _matches_any(patterns: Sequence[str], value: str) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(value, pat):
            return True
    return False


def filter_entities(
    states: Sequence[Mapping[str, Any]],
    allowed_domains: Sequence[str],
    allowlist: Sequence[str],
    blocklist: Sequence[str],
    max_entities: int,
) -> list[EntityView]:
    out: list[EntityView] = []
    for s in states:
        entity_id = str(s.get("entity_id", "")).strip()
        if not entity_id:
            continue

        dom = _domain(entity_id)
        if allowed_domains and dom not in allowed_domains:
            continue

        if allowlist and not _matches_any(allowlist, entity_id):
            continue
        if blocklist and _matches_any(blocklist, entity_id):
            continue

        attrs = s.get("attributes") or {}
        name = str(attrs.get("friendly_name") or entity_id)
        state = str(s.get("state", "unknown"))
        out.append(EntityView(entity_id=entity_id, name=name, state=state, domain=dom))

        if len(out) >= max_entities:
            break

    return out


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token.strip()

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url) and bool(self._token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def get_states(self) -> list[dict[str, Any]]:
        url = f"{self._base_url}/api/states"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    if resp.status == 401:
                        _LOGGER.warning("Home Assistant is not authorized (401). Check SUPERVISOR_TOKEN or 'ha_token' option.")
                        return []
                    raise RuntimeError(f"HA /api/states failed: {resp.status} {text}")
                data = await resp.json()
                if not isinstance(data, list):
                    raise RuntimeError("HA /api/states returned non-list JSON")
                return [dict(x) for x in data]

    async def call_service(
        self,
        domain: str,
        service: str,
        data: Mapping[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Call a Home Assistant service.

        Returns (ok, message).
        """
        if not self.is_configured:
            return (False, "Home Assistant token/URL not configured")

        domain = domain.strip()
        service = service.strip()
        if not domain or not service:
            return (False, "domain/service missing")

        url = f"{self._base_url}/api/services/{domain}/{service}"
        payload: dict[str, Any] = dict(data or {})

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self._headers(), json=payload) as resp:
                body = await resp.text()
                if resp.status == 200:
                    return (True, "ok")
                return (False, f"HTTP {resp.status}: {body[:500]}")

    async def build_entity_context_lines(
        self,
        allowed_domains: Sequence[str],
        allowlist: Sequence[str],
        blocklist: Sequence[str],
        max_entities: int,
    ) -> list[str]:
        """Create concise lines for prompt injection."""
        try:
            states = await self.get_states()
        except Exception as e:
            _LOGGER.warning("Failed to fetch HA states for context injection: %s", e)
            return ["(Could not fetch Home Assistant entity list.)"]

        entities = filter_entities(
            states=states,
            allowed_domains=allowed_domains,
            allowlist=allowlist,
            blocklist=blocklist,
            max_entities=max_entities,
        )

        lines: list[str] = []
        for ent in entities:
            # Keep it short: Name (entity_id) [state]
            lines.append(f"- {ent.name} ({ent.entity_id}) = {ent.state}")

        if not lines:
            lines.append("(No entities matched the current filters.)")

        return lines
