"""
env.py — Single source of truth for environment variable loading.

Loads the local .env file into os.environ exactly once, at import time,
before any other module reads configuration. Importing this module first
(from app.py) guarantees GEMINI_API_KEY, FLASK_SECRET_KEY, PORT, etc. are
all present in os.environ for every subsequent os.environ.get() call
across the codebase — including inside gemini_client.py.

__all__ = ["ENV_PATH"]
"""

from __future__ import annotations

import pathlib

from dotenv import load_dotenv

ENV_PATH: pathlib.Path = pathlib.Path(__file__).resolve().parent / ".env"

# override=False: real deployment env vars (e.g. Cloud Run --set-env-vars)
# must always win over a stray local .env file if one happens to be present.
load_dotenv(dotenv_path=ENV_PATH, override=False)
