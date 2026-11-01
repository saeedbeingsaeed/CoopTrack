import os

import pytest

# Playwright's sync API runs an event loop, so Django would block DB calls. We only read results.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Optional: point at an already-installed Chromium instead of `playwright install`.
    path = os.environ.get("CHROMIUM_EXECUTABLE")
    return {**browser_type_launch_args, **({"executable_path": path} if path else {})}


@pytest.fixture(autouse=True)
def _timeouts(page):
    page.set_default_timeout(10_000)
