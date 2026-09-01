"""Shared fixtures for the backend test suite.

Everything here that touches ESCO data goes through the `_require_store`
autouse fixture first, so the whole suite skips cleanly (rather than erroring)
on a checkout that doesn't have the 1.2 GB backend/esco.sqlite3 -- e.g. CI.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

# backend/ has no __init__.py and is not installed as a package -- main.py,
# esco_store.py etc. are flat modules meant to be imported with backend/ on
# sys.path. pytest.ini's `pythonpath = .` already arranges this when pytest
# is run from backend/; this is a belt-and-braces fallback for any other
# invocation (e.g. `pytest tests/` from elsewhere, or an IDE runner).
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

STORE_PATH = Path(os.environ.get("ESCO_STORE", BACKEND_DIR / "esco.sqlite3"))


def _skip_if_store_missing():
    if not STORE_PATH.exists():
        pytest.skip(
            f"ESCO quadstore not found at {STORE_PATH} -- it's a 1.2 GB "
            f"prebuilt sqlite3 file that isn't checked in and isn't shipped "
            f"to CI. Build it locally with `python ingest.py`, or point "
            f"ESCO_STORE at an existing one, to run this test.",
        )


@pytest.fixture(scope="session", autouse=True)
def _require_store():
    """Autouse session guard: skip every test in this suite if the store
    isn't on disk, instead of letting each one fail on FileNotFoundError."""
    _skip_if_store_missing()


@pytest.fixture(scope="session")
def store_module():
    """The opened, read-only esco_store module (attaches the sqlite backend
    once for the whole session -- opening is cheap and idempotent, but
    there's no reason to repeat it per test)."""
    import esco_store as store
    store.open_store()
    return store


@pytest.fixture(scope="session")
def app(store_module):
    """The FastAPI app, built with whatever CORS_ORIGINS is in the real
    environment at import time. Tests that need a *specific* CORS config use
    the `cors_app` factory fixture instead, which rebuilds the app."""
    import main
    return main.app


@pytest.fixture(scope="session")
def client(app):
    """A TestClient run through the app's lifespan (opens the store, builds
    the skill index), shared by every test that doesn't need a bespoke app."""
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cors_app(monkeypatch, store_module):
    """Factory fixture: rebuild the `main` module (and so its FastAPI app)
    with a chosen CORS_ORIGINS / CORS_ORIGIN_REGEX.

    CORS_ORIGINS is read once, at module import time, into the
    CORSMiddleware the app is constructed with -- so exercising a different
    value means re-importing main, not just tweaking os.environ. monkeypatch
    guarantees the env var is restored after the test regardless of outcome.
    """
    def _build(cors_origins: str | None = None, cors_origin_regex: str | None = None):
        if cors_origins is not None:
            monkeypatch.setenv("CORS_ORIGINS", cors_origins)
        else:
            monkeypatch.delenv("CORS_ORIGINS", raising=False)
        if cors_origin_regex is not None:
            monkeypatch.setenv("CORS_ORIGIN_REGEX", cors_origin_regex)
        else:
            monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)

        import main
        importlib.reload(main)
        return main.app

    yield _build

    # Leave `main` back in its default-env state for any later fixture in the
    # session that imports it fresh (e.g. another test's `import main`).
    monkeypatch.undo()
    import main
    importlib.reload(main)
