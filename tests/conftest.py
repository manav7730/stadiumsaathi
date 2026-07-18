"""
tests/conftest.py — Shared pytest fixtures for StadiumSaathi tests.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stadium_engine import StadiumEngine


@pytest.fixture
def mock_gemini():
    """Mock GeminiClient returning fixed text responses."""
    gemini = MagicMock()
    gemini.generate.return_value = "1. Do this. 2. Do that. 3. Escalate if needed."
    return gemini


@pytest.fixture
def engine(mock_gemini):
    """Fresh StadiumEngine instance backed by a mocked Gemini client."""
    return StadiumEngine(mock_gemini)


@pytest.fixture
def fan_session(engine):
    """A StadiumEngine with one active fan session."""
    session_id = "fan-session-0001"
    engine.create_fan_session(session_id, "Aditi", "en", "Zone A")
    return engine, session_id


@pytest.fixture
def volunteer_session(engine):
    """A StadiumEngine with one active volunteer session."""
    session_id = "vol-session-0001"
    engine.create_volunteer_session(session_id, "Rohan", "Medical", "Zone B")
    return engine, session_id
