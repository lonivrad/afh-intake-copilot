"""Pytest configuration shared across the suite.

Tests marked `@pytest.mark.api` make live Anthropic API calls (they cost
money). They are skipped by default and run ONLY when AFH_RUN_API_TESTS is set
to a truthy value in the environment.

Why an explicit opt-in rather than "run if a key is present": every pipeline
module calls dotenv.load_dotenv() at import time, so simply importing the code
under test pulls ANTHROPIC_API_KEY out of a local .env file. Keying the gate on
"is a key present" would therefore let a bare `pytest` spend money whenever a
.env exists. The dedicated flag makes running the paid tests a deliberate act.

CI wiring:
- The keyless PR/push job runs `pytest -m "not api"` — the api tests are never
  even collected for execution.
- The opt-in nightly/dispatch job sets AFH_RUN_API_TESTS=1 and provides
  ANTHROPIC_API_KEY from a secret.
"""

from __future__ import annotations

import os

import pytest

_TRUTHY = {"1", "true", "yes", "on"}


def _api_opt_in() -> bool:
    return os.getenv("AFH_RUN_API_TESTS", "").strip().lower() in _TRUTHY


def _api_skip_reason() -> str | None:
    """Return why the api tests should be skipped, or None if they should run.

    Two gates, checked in order so the failure mode stays legible:
    - the AFH_RUN_API_TESTS opt-in flag is the money-safety gate;
    - a present ANTHROPIC_API_KEY is required to actually call the API, so a
      misconfigured run (flag set, secret missing — e.g. a nightly job without
      its secret) SKIPS cleanly rather than erroring with a wall of auth
      failures that reads like a real test regression.
    """
    if not _api_opt_in():
        return "live API test: set AFH_RUN_API_TESTS=1 (with ANTHROPIC_API_KEY) to run"
    if not os.getenv("ANTHROPIC_API_KEY"):
        return "live API test: AFH_RUN_API_TESTS is set but ANTHROPIC_API_KEY is missing"
    return None


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    reason = _api_skip_reason()
    if reason is None:
        return
    skip_api = pytest.mark.skip(reason=reason)
    for item in items:
        if "api" in item.keywords:
            item.add_marker(skip_api)
