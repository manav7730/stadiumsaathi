"""
stadium_engine.py — Core simulation and persona logic for StadiumSaathi.

Maintains one shared simulated live stadium state (zone crowd density,
gate status) consumed by all three personas: Fan, Volunteer, and
Command Center. Crowd data is a clearly-labelled simulated feed, not
live sensor data — see README for scope notes.

__all__ = ["StadiumEngine"]
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
SESSION_TTL_SECONDS: int = 86400          # 24 hours
CLEANUP_INTERVAL_SECONDS: int = 300        # lazy cleanup throttle: 5 minutes
CROWD_UPDATE_INTERVAL_SECONDS: int = 8
MAX_INCIDENT_LOG: int = 200
XP_NOT_APPLICABLE: int = 0                 # reserved constant, no gamification here

ZONES: list[str] = ["Zone A", "Zone B", "Zone C", "Zone D", "Zone E - Family", "Zone VIP"]
GATES: list[str] = ["Gate 1", "Gate 2", "Gate 3", "Gate 4", "Gate 5 (Accessible)"]

HIGH_DENSITY_THRESHOLD: float = 0.80
CRITICAL_DENSITY_THRESHOLD: float = 0.92


class IncidentType(StrEnum):
    """Known incident categories a volunteer can report."""
    MEDICAL = "medical"
    LOST_CHILD = "lost_child"
    OVERCROWDING = "overcrowding"
    SECURITY = "security"
    FACILITY = "facility"
    OTHER = "other"


class VolunteerRole(StrEnum):
    """Known volunteer role categories."""
    MEDICAL = "Medical"
    SECURITY = "Security"
    GUEST_SERVICES = "Guest Services"
    GENERAL = "General"


# ── Data models ────────────────────────────────────────────────────────────────
@dataclass
class ZoneState:
    """Live (simulated) state of a single stadium zone."""
    name: str
    density: float           # 0.0 - 1.0
    gate: str
    last_updated: float = field(default_factory=time.time)


@dataclass
class FanProfile:
    """A fan's session profile."""
    __slots__ = ("session_id", "name", "language", "seat_zone", "created_at", "last_active")
    session_id: str
    name: str
    language: str
    seat_zone: str
    created_at: float
    last_active: float

    def is_expired(self) -> bool:
        """Return True if this session has exceeded the TTL."""
        return time.time() - self.last_active > SESSION_TTL_SECONDS


@dataclass
class VolunteerProfile:
    """A volunteer's session profile."""
    __slots__ = ("session_id", "name", "role", "zone", "created_at", "last_active")
    session_id: str
    name: str
    role: str
    zone: str
    created_at: float
    last_active: float

    def is_expired(self) -> bool:
        """Return True if this session has exceeded the TTL."""
        return time.time() - self.last_active > SESSION_TTL_SECONDS


# ── Engine ────────────────────────────────────────────────────────────────────
class StadiumEngine:
    """
    Core engine simulating live stadium state and serving all three
    StadiumSaathi personas from that shared state.
    """

    def __init__(self, gemini: GeminiClient) -> None:
        """
        Initialise the engine with a Gemini client and seeded zone state.

        Args:
            gemini: Configured GeminiClient instance.
        """
        self._gemini = gemini
        self._lock = threading.Lock()
        self._fans: dict[str, FanProfile] = {}
        self._volunteers: dict[str, VolunteerProfile] = {}
        self._incidents: list[dict[str, Any]] = []
        self._zones: dict[str, ZoneState] = self._seed_zones()
        self._last_cleanup: float = time.time()
        self._last_crowd_tick: float = 0.0

    # ── Public API: shared state ──────────────────────────────────────────────

    def get_stadium_state(self) -> dict[str, Any]:
        """
        Return the current simulated stadium-wide state.

        Advances the simulated crowd density feed if enough time has
        passed since the last update, then returns a snapshot.

        Returns:
            dict with per-zone density, status label, and gate mapping.
        """
        self._maybe_advance_crowd_sim()
        self._maybe_cleanup_sessions()

        zones_payload = []
        for zone in self._zones.values():
            zones_payload.append({
                "name": zone.name,
                "gate": zone.gate,
                "density": round(zone.density, 2),
                "status": self._density_status(zone.density),
            })

        return {"zones": zones_payload, "updated_at": time.time()}

    # ── Public API: Fan persona ────────────────────────────────────────────────

    def create_fan_session(self, session_id: str, name: str,
                           language: str, seat_zone: str) -> dict[str, Any]:
        """
        Create a new fan session.

        Args:
            session_id: Unique UUID for this session.
            name: Fan's display name.
            language: ISO language code.
            seat_zone: Assigned seating zone label.

        Returns:
            dict summary of the created fan profile.
        """
        profile = FanProfile(
            session_id=session_id, name=name, language=language,
            seat_zone=seat_zone, created_at=time.time(), last_active=time.time(),
        )
        with self._lock:
            self._fans[session_id] = profile

        logger.info("New fan session: %s (%s)", name, session_id[:8])
        return {"name": name, "language": language, "seat_zone": seat_zone, "zones": ZONES}

    def fan_ask(self, session_id: str, message: str) -> dict[str, Any]:
        """
        Answer a fan's question using Gemini, grounded in live zone state.

        Args:
            session_id: Fan session UUID.
            message: The fan's free-text question.

        Returns:
            dict with the AI response text and an optional crowd warning.
        """
        fan = self._get_fan(session_id)
        state = self.get_stadium_state()
        zone_info = next((z for z in state["zones"] if z["name"] == fan.seat_zone), None)

        language_label = self._language_label(fan.language)
        prompt = (
            f"You are Saathi, a helpful multilingual stadium assistant during "
            f"a FIFA World Cup 2026 match. You are helping {fan.name}, seated in "
            f"{fan.seat_zone}. "
            f"Current zone status: {zone_info}. "
            f"Available zones: {', '.join(ZONES)}. Available gates: {', '.join(GATES)}. "
            f"Answer the fan's question in 2-4 short sentences. "
            f"If they ask about crowd/congestion, use the zone status data given. "
            f"Be practical — give directions, wait-time expectations, or "
            f"accessibility info as relevant. Respond in {language_label}.\n\n"
            f"Fan's question: {message}"
        )

        response_text = self._gemini.generate(prompt)
        warning = None
        if zone_info and zone_info["density"] >= HIGH_DENSITY_THRESHOLD:
            pct = int(zone_info["density"] * 100)
            warning = f"{fan.seat_zone} is currently at {pct}% capacity."

        with self._lock:
            fan.last_active = time.time()

        return {"response": response_text, "crowd_warning": warning}

    # ── Public API: Volunteer persona ─────────────────────────────────────────

    def create_volunteer_session(self, session_id: str, name: str,
                                 role: str, zone: str) -> dict[str, Any]:
        """
        Create a new volunteer session.

        Args:
            session_id: Unique UUID for this session.
            name: Volunteer's display name.
            role: Role category string.
            zone: Assigned stadium zone.

        Returns:
            dict summary of the created volunteer profile.
        """
        profile = VolunteerProfile(
            session_id=session_id, name=name, role=role, zone=zone,
            created_at=time.time(), last_active=time.time(),
        )
        with self._lock:
            self._volunteers[session_id] = profile

        logger.info("New volunteer session: %s (%s, %s)", name, role, session_id[:8])
        return {
            "name": name, "role": role, "zone": zone,
            "incident_types": [t.value for t in IncidentType],
        }

    def report_incident(self, session_id: str, incident_type: str,
                        description: str) -> dict[str, Any]:
        """
        Log an incident and generate AI triage guidance for the volunteer.

        Args:
            session_id: Volunteer session UUID.
            incident_type: Category string from IncidentType.
            description: Free-text description of the incident.

        Returns:
            dict with AI-generated triage steps and escalation suggestion.
        """
        volunteer = self._get_volunteer(session_id)

        desc_text = description or "No further details given."
        prompt = (
            f"You are Saathi, an AI incident-triage assistant for stadium "
            f"volunteers during FIFA World Cup 2026. "
            f"A volunteer ({volunteer.role}) in {volunteer.zone} is reporting: "
            f"Incident type: {incident_type}. Description: {desc_text} "
            f"Give exactly 3 short, numbered, practical next steps the volunteer "
            f"should take right now, plus one line stating whether this needs "
            f"escalation to Medical, Security, or can be handled locally. "
            f"Keep the whole response under 80 words. Be calm and clear."
        )

        guidance = self._gemini.generate(prompt)

        entry = {
            "incident_id": f"INC-{len(self._incidents) + 1:04d}",
            "incident_type": incident_type,
            "description": description,
            "zone": volunteer.zone,
            "reported_by": volunteer.name,
            "role": volunteer.role,
            "guidance": guidance,
            "timestamp": time.time(),
        }

        with self._lock:
            self._incidents.append(entry)
            if len(self._incidents) > MAX_INCIDENT_LOG:
                self._incidents.pop(0)
            volunteer.last_active = time.time()

        return {"incident": entry}

    # ── Public API: Command Center persona ────────────────────────────────────

    def get_command_recommendations(self) -> dict[str, Any]:
        """
        Generate AI operational recommendations based on current hotspots.

        Returns:
            dict with a list of recommendation strings and the hotspot zones
            that triggered them.
        """
        state = self.get_stadium_state()
        hotspots = [z for z in state["zones"] if z["density"] >= HIGH_DENSITY_THRESHOLD]

        if not hotspots:
            return {
                "recommendations": ["All zones currently operating within normal capacity."],
                "hotspots": [],
            }

        prompt = (
            f"You are Saathi, an AI operations advisor for a FIFA World Cup "
            f"2026 stadium command center. Current high-density zones: "
            f"{hotspots}. Gates available: {', '.join(GATES)}. "
            f"Give exactly 3 short, specific, actionable recommendations for "
            f"the organizer to reduce congestion right now (e.g. open specific "
            f"overflow gate, redirect flow, deploy staff). "
            f"One sentence each. Return as a numbered list."
        )

        raw = self._gemini.generate_cached(prompt)
        recommendations = self._parse_lines(raw)

        return {"recommendations": recommendations, "hotspots": hotspots}

    def get_all_incidents(self) -> list[dict[str, Any]]:
        """
        Return the full incident log, most recent first.

        Returns:
            List of incident dicts.
        """
        return list(reversed(self._incidents[-MAX_INCIDENT_LOG:]))

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_fan(self, session_id: str) -> FanProfile:
        """Retrieve a fan profile or raise ValueError if not found."""
        fan = self._fans.get(session_id)
        if not fan:
            raise ValueError(f"Fan session not found: {session_id}")
        return fan

    def _get_volunteer(self, session_id: str) -> VolunteerProfile:
        """Retrieve a volunteer profile or raise ValueError if not found."""
        volunteer = self._volunteers.get(session_id)
        if not volunteer:
            raise ValueError(f"Volunteer session not found: {session_id}")
        return volunteer

    def _seed_zones(self) -> dict[str, ZoneState]:
        """
        Create the initial simulated zone states with varied starting density.

        Returns:
            dict mapping zone name to its ZoneState.
        """
        zones: dict[str, ZoneState] = {}
        for i, name in enumerate(ZONES):
            base_density = random.uniform(0.3, 0.6)
            zones[name] = ZoneState(name=name, density=base_density, gate=GATES[i % len(GATES)])
        return zones

    def _maybe_advance_crowd_sim(self) -> None:
        """
        Advance the simulated crowd density feed via a bounded random walk,
        throttled to CROWD_UPDATE_INTERVAL_SECONDS to avoid excessive churn.
        """
        now = time.time()
        if now - self._last_crowd_tick < CROWD_UPDATE_INTERVAL_SECONDS:
            return

        with self._lock:
            for zone in self._zones.values():
                delta = random.uniform(-0.07, 0.09)
                zone.density = max(0.05, min(0.99, zone.density + delta))
                zone.last_updated = now
            self._last_crowd_tick = now

    def _maybe_cleanup_sessions(self) -> None:
        """
        Lazily remove expired fan/volunteer sessions, throttled to run
        at most once per CLEANUP_INTERVAL_SECONDS to avoid overhead on
        every request.
        """
        now = time.time()
        if now - self._last_cleanup < CLEANUP_INTERVAL_SECONDS:
            return

        with self._lock:
            expired_fans = [sid for sid, f in self._fans.items() if f.is_expired()]
            for sid in expired_fans:
                del self._fans[sid]

            expired_vols = [sid for sid, v in self._volunteers.items() if v.is_expired()]
            for sid in expired_vols:
                del self._volunteers[sid]

            self._last_cleanup = now

        if expired_fans or expired_vols:
            logger.info("Cleaned up %d fan and %d volunteer sessions",
                       len(expired_fans), len(expired_vols))

    @staticmethod
    def _density_status(density: float) -> str:
        """
        Map a density float to a human-readable status label.

        Args:
            density: Value between 0.0 and 1.0.

        Returns:
            One of 'normal', 'busy', or 'critical'.
        """
        if density >= CRITICAL_DENSITY_THRESHOLD:
            return "critical"
        if density >= HIGH_DENSITY_THRESHOLD:
            return "busy"
        return "normal"

    @staticmethod
    def _parse_lines(raw: str) -> list[str]:
        """
        Parse a numbered-list Gemini response into clean string items.

        Args:
            raw: Raw text response from Gemini.

        Returns:
            List of up to 3 cleaned recommendation strings.
        """
        lines = [
            line.strip("0123456789.-) ").strip()
            for line in raw.split("\n") if line.strip()
        ]
        return lines[:3] if lines else ["Monitor high-density zones closely."]

    @staticmethod
    def _language_label(code: str) -> str:
        """Map an ISO language code to its full display name."""
        mapping = {
            "en": "English", "hi": "Hindi", "es": "Spanish", "pt": "Portuguese",
            "fr": "French", "ar": "Arabic", "de": "German", "ja": "Japanese",
            "ko": "Korean", "zh": "Chinese",
        }
        return mapping.get(code, "English")
