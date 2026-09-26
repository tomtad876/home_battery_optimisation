"""Deployed-build identification.

A failed Render/Vercel build silently keeps the previous instance serving, so
"the API responds" does NOT prove the latest commit is live. Exposing the commit
here makes a stale build detectable — see the 2026-09-26 incident where Render
served pre-optimiser code for a day behind a healthy ``/health``.
"""
import os
from datetime import datetime, timezone

# Render sets RENDER_GIT_COMMIT; accept fallbacks for other hosts / local.
COMMIT = (
    os.environ.get("RENDER_GIT_COMMIT")
    or os.environ.get("VERCEL_GIT_COMMIT_SHA")
    or os.environ.get("GIT_COMMIT")
    or "unknown"
)
BRANCH = (
    os.environ.get("RENDER_GIT_BRANCH")
    or os.environ.get("VERCEL_GIT_COMMIT_REF")
    or os.environ.get("GIT_BRANCH")
    or "unknown"
)

# Captured at import time, i.e. when the process booted. A long-running old
# instance and a fresh redeploy can be told apart by this.
BOOT_TIME = datetime.now(timezone.utc).isoformat()


def build_info() -> dict:
    """Commit, branch and boot time of the running process."""
    return {"commit": COMMIT, "branch": BRANCH, "boot_time": BOOT_TIME}
