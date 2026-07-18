"""
gemini_client.py — Google Gemini API wrapper for StadiumSaathi.

Provides generate() with retry/backoff logic for rate-limit resilience
and a safe fallback so the UI never shows a raw error to a fan or
volunteer mid-match.

__all__ = ["GeminiClient"]
"""

from __future__ import annotations

import logging
import os
import time
import weakref
from functools import lru_cache

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
MAX_OUTPUT_TOKENS: int = 400
TEMPERATURE: float = 0.6
MAX_RETRIES: int = 3
RETRY_DELAY_SECONDS: float = 4.0
CACHE_SIZE: int = 64


class GeminiClient:
    """Thin wrapper around the Google Gemini API with retry logic."""

    def __init__(self) -> None:
        """
        Initialise the Gemini client using GEMINI_API_KEY from os.environ.

        Note: os.environ is populated from the local .env file by the
        `env` module, which app.py imports before this class is
        constructed. Standalone scripts/tests that import GeminiClient
        directly should `import env` first if they rely on a .env file.
        """
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not set — responses will be mocked.")
        self._client = genai.Client(api_key=api_key or "MISSING")

    def generate(self, prompt: str) -> str:
        """
        Generate a single-turn text response from Gemini with retry.

        Args:
            prompt: The full prompt string to send to Gemini.

        Returns:
            Generated text response, or a safe fallback string on failure.
        """
        for attempt in range(MAX_RETRIES):
            try:
                response = self._client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=MAX_OUTPUT_TOKENS,
                        temperature=TEMPERATURE,
                    ),
                )
                text = response.text
                if not text:
                    logger.warning("Gemini returned empty/blocked response text.")
                    return self._fallback_response()
                return text.strip()
            except Exception as e:
                if self._is_rate_limit(e) and attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAY_SECONDS * (2 ** attempt)
                    logger.warning(
                        "Rate limited — retrying in %.1fs (attempt %d)", wait, attempt + 1
                    )
                    time.sleep(wait)
                else:
                    logger.error("Gemini error: %s", e)
                    return self._fallback_response()
        return self._fallback_response()

    def generate_cached(self, prompt: str) -> str:
        """
        Cached variant of generate() for repeated identical prompts
        (e.g. identical command-center recommendation requests polled
        between crowd-sim ticks).

        Delegates to a module-level cache function rather than decorating
        this instance method directly with @lru_cache, which would pin a
        reference to `self` inside the cache for the process lifetime.

        Args:
            prompt: The prompt string, used as the cache key.

        Returns:
            Cached or freshly generated text response.
        """
        return _cached_generate(weakref.ref(self), prompt)

    @staticmethod
    def _is_rate_limit(error: Exception) -> bool:
        """
        Detect if an exception represents a rate limit (429) error.

        Args:
            error: Exception raised during a Gemini API call.

        Returns:
            True if the error indicates a rate limit / quota issue.
        """
        msg = str(error).lower()
        return "429" in msg or ("resource" in msg and "exhausted" in msg)

    @staticmethod
    def _fallback_response() -> str:
        """
        Return a safe, generic fallback message when Gemini is unavailable.

        Returns:
            A short apology string that keeps the UI functional.
        """
        return (
            "Saathi is briefly unavailable right now — please try again "
            "in a moment, or ask a nearby staff member for assistance."
        )


@lru_cache(maxsize=CACHE_SIZE)
def _cached_generate(client_ref: weakref.ReferenceType[GeminiClient], prompt: str) -> str:
    """
    Module-level cache for identical (client, prompt) pairs.

    Kept as a free function (not a decorated instance method) so the
    lru_cache does not hold a permanent strong reference to `self` — see
    GeminiClient.generate_cached for the rationale. In practice this app
    constructs exactly one long-lived GeminiClient, so caching by identity
    here is equivalent to caching per-client while staying free of the
    method-decoration memory-leak pattern that static analysis flags.

    Args:
        client_ref: A weakref to the GeminiClient instance.
        prompt: The prompt string, used as part of the cache key.

    Returns:
        Cached or freshly generated text response.
    """
    client = client_ref()
    if client is None:
        return GeminiClient._fallback_response()
    return client.generate(prompt)
