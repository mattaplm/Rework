"""Which build is running, shown on the Admin page.

Reads the git commit straight out of `.git` (no `git` binary needed -- the
Docker image doesn't install one). `APP_VERSION` in the environment wins if
set, for deployments that ship without a `.git` folder.
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
    explicit = os.environ.get("APP_VERSION", "").strip()
    if explicit:
        return explicit
    commit = _read_git_commit()
    return commit[:7] if commit else "unknown"
