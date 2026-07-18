"""
StadiumSaathi — GenAI Smart Stadium & Tournament Operations Platform.

Flask application entry point serving three personas from one shared
live stadium-state feed: Fan, Volunteer, and Command Center (organizer).

__all__ = ["app"]
"""

from __future__ import annotations

# `env` must be imported before any other project module that reads
# os.environ at import time (e.g. gemini_client.GEMINI_MODEL). It is kept
# in its own import group, deliberately out of alphabetical order — see
# the app.py entry under [tool.ruff.lint.per-file-ignores] in
# pyproject.toml for why this is intentional rather than an oversight.
import env  # noqa: F401  (side-effect import: populates os.environ from .env)

import logging
import os
import uuid
from typing import Any

from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from gemini_client import GeminiClient
from stadium_engine import StadiumEngine

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_NAME_LENGTH: int = 60
MAX_MESSAGE_LENGTH: int = 500
ALLOWED_LANGUAGES: set[str] = {
    "en", "hi", "es", "pt", "fr", "ar", "de", "ja", "ko", "zh"
}
RATE_LIMIT_DEFAULT: str = "60 per minute"
RATE_LIMIT_AI: str = "15 per minute"

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "stadiumsaathi-dev-key")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,  # 1 MB request body cap
)

CORS(app, origins=["https://stadiumsaathi-*.run.app", "http://localhost:*"])

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[RATE_LIMIT_DEFAULT],
    storage_uri="memory://",
)
# NOTE: storage_uri="memory://" keeps rate-limit counters in this single
# process's memory. It is only correct with exactly ONE Gunicorn worker
# (see Dockerfile: --workers 1) — with multiple workers or Cloud Run
# instances, each would keep its own counter and the effective limit would
# silently multiply. A production deployment serving real traffic should
# swap this for a shared backend (e.g. storage_uri="redis://...").

gemini = GeminiClient()
engine = StadiumEngine(gemini)

# ── Security headers ──────────────────────────────────────────────────────────
@app.after_request
def add_security_headers(response: Response) -> Response:
    """Attach standard security headers to every response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    return response

# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e: Any) -> tuple[Response, int]:
    """Return JSON for unmatched routes instead of Flask's default HTML."""
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(429)
def rate_limited(e: Any) -> tuple[Response, int]:
    """Return JSON when a client exceeds the rate limit."""
    return jsonify({"error": "Too many requests. Please slow down."}), 429

@app.errorhandler(ValueError)
def handle_value_error(e: ValueError) -> tuple[Response, int]:
    """Map invalid session/session-lookup errors to HTTP 404."""
    logger.info("ValueError mapped to 404: %s", e)
    return jsonify({"error": str(e)}), 404

@app.errorhandler(Exception)
def handle_exception(e: Exception) -> tuple[Response, int]:
    """Catch-all handler returning structured JSON instead of a raw 500 page."""
    logger.error("Unhandled exception: %s", e, exc_info=True)
    return jsonify({"error": "An unexpected error occurred."}), 500

# ── Content-Type guard ────────────────────────────────────────────────────────
def _require_json() -> dict:
    """
    Validate the request has a JSON content type and body.

    Returns:
        Parsed JSON body as a dict (empty dict if body absent).

    Raises:
        ValueError: If Content-Type is not application/json.
    """
    if not request.is_json:
        raise ValueError("Content-Type must be application/json")
    return request.get_json(silent=True) or {}

def _validate_session_id(value: str) -> str:
    """
    Validate a string is a well-formed UUID.

    Args:
        value: Candidate session id string.

    Returns:
        The validated UUID string.

    Raises:
        ValueError: If value is not a valid UUID.
    """
    try:
        uuid.UUID(str(value))
        return str(value)
    except (ValueError, AttributeError, TypeError) as err:
        raise ValueError("Valid session_id (UUID) required") from err

# ── Routes: pages ─────────────────────────────────────────────────────────────
@app.route("/")
def index() -> str:
    """Render the persona picker / landing page."""
    return render_template("index.html")

# ── Routes: shared stadium state ──────────────────────────────────────────────
@app.route("/api/stadium_state", methods=["GET"])
@limiter.limit("60 per minute")
def stadium_state() -> tuple[Response, int]:
    """
    Return the current simulated live stadium state.

    Returns:
        JSON with zone-by-zone crowd density, gate status, and timestamp.
    """
    return jsonify(engine.get_stadium_state()), 200

# ── Routes: Fan persona ────────────────────────────────────────────────────────
@app.route("/api/fan/session", methods=["POST"])
@limiter.limit("30 per minute")
def fan_create_session() -> tuple[Response, int]:
    """
    Create a fan session with seat/gate info and preferred language.

    Request JSON:
        name (str): Fan's display name.
        language (str): ISO language code.
        seat_zone (str): Assigned seating zone (e.g. 'Zone C').

    Returns:
        JSON with session_id and initial fan profile.
    """
    data = _require_json()
    name = str(data.get("name", "Fan"))[:MAX_NAME_LENGTH].strip()
    language = data.get("language", "en")
    seat_zone = str(data.get("seat_zone", "Zone A")).strip()

    if language not in ALLOWED_LANGUAGES:
        language = "en"

    session_id = str(uuid.uuid4())
    profile = engine.create_fan_session(session_id, name, language, seat_zone)
    return jsonify({"session_id": session_id, "profile": profile}), 201

@app.route("/api/fan/ask", methods=["POST"])
@limiter.limit(RATE_LIMIT_AI)
def fan_ask() -> tuple[Response, int]:
    """
    Ask the multilingual fan assistant a question.

    Request JSON:
        session_id (str): Valid fan session UUID.
        message (str): Fan's question (max 500 chars).

    Returns:
        JSON with AI response and any relevant crowd warning.
    """
    data = _require_json()
    session_id = _validate_session_id(data.get("session_id", ""))
    message = str(data.get("message", ""))[:MAX_MESSAGE_LENGTH].strip()

    if not message:
        return jsonify({"error": "message is required"}), 400

    result = engine.fan_ask(session_id, message)
    return jsonify(result), 200

# ── Routes: Volunteer persona ──────────────────────────────────────────────────
@app.route("/api/volunteer/session", methods=["POST"])
@limiter.limit("30 per minute")
def volunteer_create_session() -> tuple[Response, int]:
    """
    Create a volunteer/staff session.

    Request JSON:
        name (str): Volunteer's display name.
        role (str): Role identifier (e.g. 'Medical', 'Security', 'General').
        zone (str): Assigned stadium zone.

    Returns:
        JSON with session_id and initial volunteer profile.
    """
    data = _require_json()
    name = str(data.get("name", "Volunteer"))[:MAX_NAME_LENGTH].strip()
    role = str(data.get("role", "General")).strip()
    zone = str(data.get("zone", "Zone A")).strip()

    session_id = str(uuid.uuid4())
    profile = engine.create_volunteer_session(session_id, name, role, zone)
    return jsonify({"session_id": session_id, "profile": profile}), 201

@app.route("/api/volunteer/incident", methods=["POST"])
@limiter.limit(RATE_LIMIT_AI)
def volunteer_report_incident() -> tuple[Response, int]:
    """
    Report an incident and receive AI-generated triage guidance.

    Request JSON:
        session_id (str): Valid volunteer session UUID.
        incident_type (str): One of the known incident categories.
        description (str): Free-text incident description.

    Returns:
        JSON with AI triage steps and suggested escalation.
    """
    data = _require_json()
    session_id = _validate_session_id(data.get("session_id", ""))
    incident_type = str(data.get("incident_type", "")).strip()
    description = str(data.get("description", ""))[:MAX_MESSAGE_LENGTH].strip()

    if not incident_type:
        return jsonify({"error": "incident_type is required"}), 400

    result = engine.report_incident(session_id, incident_type, description)
    return jsonify(result), 200

# ── Routes: Command Center persona ────────────────────────────────────────────
@app.route("/api/command/recommendations", methods=["GET"])
@limiter.limit(RATE_LIMIT_AI)
def command_recommendations() -> tuple[Response, int]:
    """
    Return AI-generated operational recommendations based on live state.

    Returns:
        JSON with a list of recommendation strings tied to current hotspots.
    """
    result = engine.get_command_recommendations()
    return jsonify(result), 200

@app.route("/api/command/incidents", methods=["GET"])
@limiter.limit("60 per minute")
def command_incidents() -> tuple[Response, int]:
    """
    Return the live incident log for the command center view.

    Returns:
        JSON list of all reported incidents across volunteers.
    """
    return jsonify({"incidents": engine.get_all_incidents()}), 200

@app.route("/health")
@limiter.exempt
def health() -> tuple[Response, int]:
    """Health check endpoint for Cloud Run."""
    return jsonify({"status": "ok", "service": "StadiumSaathi"}), 200

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
