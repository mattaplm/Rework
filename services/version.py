"""Which build is running, shown on the Admin page.

`REWORK_REVISION` (set by the deployment, same value /health reports) wins;
otherwise reads the git commit straight out of `.git` for local dev (no `git`
binary needed).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _read_git_commit() -> str | None:
    git = _ROOT / ".git"
    try:
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return head  # detached HEAD
        ref = head.split(" ", 1)[1]
        ref_file = git / ref
        if ref_file.exists():
            return ref_file.read_text().strip()
        for line in (git / "packed-refs").read_text().splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except OSError:
        pass
    return None


@lru_cache(maxsize=1)
def get_version() -> str:
    explicit = os.environ.get("REWORK_REVISION", "").strip()
    if explicit:
        return explicit[:7]
    commit = _read_git_commit()
    return commit[:7] if commit else "unknown"
