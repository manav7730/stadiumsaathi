"""
tests/test_app.py — Integration tests for Flask routes using test_client.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("gemini_client.genai.Client"):
    import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    # Stub the real GeminiClient.generate so routes get a plain string,
    # not an unconfigured MagicMock (which fails JSON serialization).
    fallback_text = "1. Step one. 2. Step two. 3. Step three."
    with patch.object(app_module.gemini, "generate", return_value=fallback_text):
        with app_module.app.test_client() as client:
            yield client


def _create_fan(client) -> str:
    payload = {"name": "Test Fan", "seat_zone": "Zone A", "language": "en"}
    res = client.post("/api/fan/session", json=payload)
    return res.get_json()["session_id"]

def _create_volunteer(client) -> str:
    payload = {"name": "Test Vol", "role": "Medical", "zone": "Zone B"}
    res = client.post("/api/volunteer/session", json=payload)
    return res.get_json()["session_id"]


# ── Basic routes ──────────────────────────────────────────────────────────────

def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"

def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200

def test_security_headers_present(client):
    res = client.get("/health")
    assert "X-Content-Type-Options" in res.headers
    assert "X-Frame-Options" in res.headers
    assert "Content-Security-Policy" in res.headers

def test_stadium_state_endpoint(client):
    res = client.get("/api/stadium_state")
    assert res.status_code == 200
    assert "zones" in res.get_json()


# ── Fan routes ────────────────────────────────────────────────────────────────

def test_fan_session_creation(client):
    payload = {"name": "Priya", "seat_zone": "Zone C", "language": "hi"}
    res = client.post("/api/fan/session", json=payload)
    assert res.status_code == 201
    assert "session_id" in res.get_json()

def test_fan_session_invalid_language_defaults(client):
    res = client.post("/api/fan/session", json={"name": "Priya", "language": "xx"})
    assert res.status_code == 201

def test_fan_ask_success(client):
    sid = _create_fan(client)
    res = client.post("/api/fan/ask", json={"session_id": sid, "message": "Where is my seat?"})
    assert res.status_code == 200
    assert "response" in res.get_json()

def test_fan_ask_missing_message(client):
    sid = _create_fan(client)
    res = client.post("/api/fan/ask", json={"session_id": sid, "message": ""})
    assert res.status_code == 400

def test_fan_ask_missing_session_id(client):
    res = client.post("/api/fan/ask", json={"message": "hello"})
    assert res.status_code == 404

def test_fan_ask_invalid_session_uuid(client):
    res = client.post("/api/fan/ask", json={"session_id": "not-a-uuid", "message": "hi"})
    assert res.status_code == 404

def test_fan_ask_nonexistent_valid_uuid(client):
    res = client.post("/api/fan/ask", json={
        "session_id": "00000000-0000-0000-0000-000000000000", "message": "hi",
    })
    assert res.status_code == 404


# ── Volunteer routes ──────────────────────────────────────────────────────────

def test_volunteer_session_creation(client):
    payload = {"name": "Sam", "role": "Security", "zone": "Zone D"}
    res = client.post("/api/volunteer/session", json=payload)
    assert res.status_code == 201
    assert "session_id" in res.get_json()

def test_volunteer_incident_success(client):
    sid = _create_volunteer(client)
    res = client.post("/api/volunteer/incident", json={
        "session_id": sid, "incident_type": "medical", "description": "Fainting near gate",
    })
    assert res.status_code == 200
    assert "incident" in res.get_json()

def test_volunteer_incident_missing_type(client):
    sid = _create_volunteer(client)
    res = client.post("/api/volunteer/incident", json={"session_id": sid, "incident_type": ""})
    assert res.status_code == 400

def test_volunteer_incident_invalid_session(client):
    payload = {"session_id": "bad-uuid", "incident_type": "medical"}
    res = client.post("/api/volunteer/incident", json=payload)
    assert res.status_code == 404


# ── Command center routes ─────────────────────────────────────────────────────

def test_command_recommendations(client):
    res = client.get("/api/command/recommendations")
    assert res.status_code == 200
    assert "recommendations" in res.get_json()

def test_command_incidents_empty_initially(client):
    res = client.get("/api/command/incidents")
    assert res.status_code == 200
    assert "incidents" in res.get_json()

def test_command_incidents_lists_reported(client):
    sid = _create_volunteer(client)
    client.post("/api/volunteer/incident", json={
        "session_id": sid, "incident_type": "security", "description": "Suspicious activity",
    })
    res = client.get("/api/command/incidents")
    incidents = res.get_json()["incidents"]
    assert len(incidents) >= 1


# ── Content-Type validation ────────────────────────────────────────────────────

def test_non_json_request_rejected(client):
    res = client.post("/api/fan/session", data="not json", content_type="text/plain")
    assert res.status_code == 404  # ValueError mapped to 404


# ── 404 handling ──────────────────────────────────────────────────────────────

def test_unknown_route_returns_404_json(client):
    res = client.get("/api/does-not-exist")
    assert res.status_code == 404
    assert "error" in res.get_json()
