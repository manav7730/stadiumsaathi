"""
tests/test_stadium_engine.py — Unit tests for the StadiumEngine.
"""

import time
from unittest.mock import MagicMock

import pytest

from gemini_client import GeminiClient
from stadium_engine import ZONES, IncidentType, StadiumEngine

# ── Zone state ────────────────────────────────────────────────────────────────

def test_stadium_state_returns_all_zones(engine):
    state = engine.get_stadium_state()
    assert len(state["zones"]) == len(ZONES)

def test_stadium_state_zone_fields(engine):
    state = engine.get_stadium_state()
    zone = state["zones"][0]
    assert "name" in zone and "density" in zone and "status" in zone and "gate" in zone

def test_stadium_state_density_bounds(engine):
    state = engine.get_stadium_state()
    for zone in state["zones"]:
        assert 0.0 <= zone["density"] <= 1.0

def test_density_status_mapping(engine):
    assert engine._density_status(0.5) == "normal"
    assert engine._density_status(0.85) == "busy"
    assert engine._density_status(0.95) == "critical"


# ── Fan persona ───────────────────────────────────────────────────────────────

def test_create_fan_session_returns_profile(engine):
    profile = engine.create_fan_session("s1", "Meera", "hi", "Zone C")
    assert profile["name"] == "Meera"
    assert profile["language"] == "hi"
    assert profile["seat_zone"] == "Zone C"
    assert profile["zones"] == ZONES

def test_fan_ask_returns_response(fan_session):
    engine, sid = fan_session
    result = engine.fan_ask(sid, "Where is my seat?")
    assert "response" in result

def test_fan_ask_calls_gemini(fan_session):
    engine, sid = fan_session
    engine.fan_ask(sid, "Where is the restroom?")
    engine._gemini.generate.assert_called_once()

def test_fan_ask_invalid_session_raises(engine):
    with pytest.raises(ValueError):
        engine.fan_ask("nonexistent", "hello")

def test_fan_ask_high_density_triggers_warning(fan_session):
    engine, sid = fan_session
    with engine._lock:
        engine._zones["Zone A"].density = 0.95
    result = engine.fan_ask(sid, "Is it crowded?")
    assert result["crowd_warning"] is not None
    assert "Zone A" in result["crowd_warning"]

def test_fan_ask_low_density_no_warning(fan_session):
    engine, sid = fan_session
    with engine._lock:
        engine._zones["Zone A"].density = 0.3
    result = engine.fan_ask(sid, "Is it crowded?")
    assert result["crowd_warning"] is None


# ── Volunteer persona ─────────────────────────────────────────────────────────

def test_create_volunteer_session_returns_profile(engine):
    profile = engine.create_volunteer_session("v1", "Sam", "Security", "Zone D")
    assert profile["name"] == "Sam"
    assert profile["role"] == "Security"
    assert set(profile["incident_types"]) == {t.value for t in IncidentType}

def test_report_incident_returns_guidance(volunteer_session):
    engine, sid = volunteer_session
    result = engine.report_incident(sid, "medical", "Person fainted near Gate 2")
    assert "guidance" in result["incident"]
    assert result["incident"]["incident_type"] == "medical"

def test_report_incident_invalid_session_raises(engine):
    with pytest.raises(ValueError):
        engine.report_incident("nonexistent", "medical", "test")

def test_report_incident_assigns_sequential_ids(volunteer_session):
    engine, sid = volunteer_session
    r1 = engine.report_incident(sid, "medical", "First")
    r2 = engine.report_incident(sid, "security", "Second")
    assert r1["incident"]["incident_id"] != r2["incident"]["incident_id"]

def test_report_incident_appears_in_log(volunteer_session):
    engine, sid = volunteer_session
    engine.report_incident(sid, "lost_child", "Child missing near Zone C")
    incidents = engine.get_all_incidents()
    assert len(incidents) == 1
    assert incidents[0]["incident_type"] == "lost_child"


# ── Command center persona ────────────────────────────────────────────────────

def test_recommendations_no_hotspots(engine):
    with engine._lock:
        for zone in engine._zones.values():
            zone.density = 0.4
    result = engine.get_command_recommendations()
    assert result["hotspots"] == []
    assert len(result["recommendations"]) >= 1

def test_recommendations_with_hotspots_calls_gemini(engine):
    with engine._lock:
        engine._zones["Zone A"].density = 0.95
    result = engine.get_command_recommendations()
    assert len(result["hotspots"]) >= 1
    engine._gemini.generate_cached.assert_called_once()

def test_recommendations_cache_hits_on_identical_hotspot_state(mock_gemini):
    """Repeated calls with an unchanged hotspot snapshot should reuse the
    cached Gemini response rather than issuing a fresh API call each time."""
    real_gemini = GeminiClient.__new__(GeminiClient)
    real_gemini._client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "1. Open overflow gate. 2. Redirect flow. 3. Deploy staff."
    real_gemini._client.models.generate_content.return_value = mock_response

    test_engine = StadiumEngine(real_gemini)
    with test_engine._lock:
        test_engine._zones["Zone A"].density = 0.95
        # Freeze the sim so the prompt (and hence cache key) stays identical
        test_engine._last_crowd_tick = time.time()

    test_engine.get_command_recommendations()
    test_engine.get_command_recommendations()

    assert real_gemini._client.models.generate_content.call_count == 1

def test_get_all_incidents_empty_initially(engine):
    assert engine.get_all_incidents() == []

def test_get_all_incidents_most_recent_first(volunteer_session):
    engine, sid = volunteer_session
    engine.report_incident(sid, "medical", "First incident")
    engine.report_incident(sid, "security", "Second incident")
    incidents = engine.get_all_incidents()
    assert incidents[0]["description"] == "Second incident"


# ── Line parsing helper ───────────────────────────────────────────────────────

def test_parse_lines_numbered_list():
    raw = "1. First rec\n2. Second rec\n3. Third rec"
    result = StadiumEngineTestHelper.parse(raw)
    assert result == ["First rec", "Second rec", "Third rec"]

def test_parse_lines_empty_fallback():
    result = StadiumEngineTestHelper.parse("")
    assert len(result) >= 1


class StadiumEngineTestHelper:
    """Thin test helper exposing the static parser without instantiating the engine."""
    @staticmethod
    def parse(raw: str) -> list[str]:
        from stadium_engine import StadiumEngine
        return StadiumEngine._parse_lines(raw)
