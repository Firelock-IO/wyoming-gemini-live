
import pytest
from wyoming_gemini_live.ha import filter_entities, EntityView

def test_filter_basic():
    states = [
        {"entity_id": "light.one", "state": "on", "attributes": {"friendly_name": "Light One"}},
        {"entity_id": "switch.two", "state": "off"},
        {"entity_id": "sensor.temp", "state": "20"},
    ]
    
    # Filter for lights only
    res = filter_entities(states, allowed_domains=["light"], allowlist=[], blocklist=[], max_entities=10)
    assert len(res) == 1
    assert res[0].entity_id == "light.one"

def test_allowlist():
    states = [
        {"entity_id": "light.one", "state": "on"},
        {"entity_id": "light.two", "state": "off"},
    ]
    # Allow only "light.one"
    res = filter_entities(states, allowed_domains=["light"], allowlist=["light.one"], blocklist=[], max_entities=10)
    assert len(res) == 1
    assert res[0].entity_id == "light.one"

def test_blocklist():
    states = [
        {"entity_id": "light.one", "state": "on"},
        {"entity_id": "light.two", "state": "off"},
    ]
    # Block "light.two"
    res = filter_entities(states, allowed_domains=["light"], allowlist=[], blocklist=["light.two"], max_entities=10)
    assert len(res) == 1
    assert res[0].entity_id == "light.one"

def test_max_entities():
    states = [{"entity_id": f"light.{i}", "state": "on"} for i in range(20)]
    res = filter_entities(states, allowed_domains=["light"], allowlist=[], blocklist=[], max_entities=5)
    assert len(res) == 5
