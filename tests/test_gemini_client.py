"""
tests/test_gemini_client.py — Unit tests for GeminiClient retry/fallback logic.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("gemini_client.genai.Client"):
    from gemini_client import GeminiClient


@pytest.fixture
def client():
    with patch("gemini_client.genai.Client"):
        return GeminiClient()


def test_generate_returns_text_on_success(client):
    mock_response = MagicMock()
    mock_response.text = "  Turn left at Gate 3.  "
    client._client.models.generate_content.return_value = mock_response

    result = client.generate("test prompt")
    assert result == "Turn left at Gate 3."

def test_generate_retries_on_rate_limit(client):
    mock_response = MagicMock()
    mock_response.text = "Recovered response"
    client._client.models.generate_content.side_effect = [
        Exception("429 rate limit exceeded"),
        mock_response,
    ]
    with patch("gemini_client.time.sleep"):
        result = client.generate("test prompt")
    assert result == "Recovered response"

def test_generate_falls_back_after_max_retries(client):
    client._client.models.generate_content.side_effect = Exception("429 rate limit")
    with patch("gemini_client.time.sleep"):
        result = client.generate("test prompt")
    assert "saathi" in result.lower() or "unavailable" in result.lower()

def test_generate_falls_back_on_non_rate_limit_error(client):
    client._client.models.generate_content.side_effect = Exception("Some other error")
    result = client.generate("test prompt")
    assert "unavailable" in result.lower()

def test_is_rate_limit_detects_429():
    assert GeminiClient._is_rate_limit(Exception("Error 429: too many requests"))

def test_is_rate_limit_detects_resource_exhausted():
    assert GeminiClient._is_rate_limit(Exception("RESOURCE_EXHAUSTED quota"))

def test_is_rate_limit_false_for_other_errors():
    assert not GeminiClient._is_rate_limit(Exception("API key not valid"))

def test_fallback_response_is_non_empty():
    assert len(GeminiClient._fallback_response()) > 0
