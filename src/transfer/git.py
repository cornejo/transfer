from __future__ import annotations

import subprocess
from pathlib import Path


class Failure(Exception):
    """Something the user needs to fix. Reported without a traceback."""


def git(
    *args: str,
    repo: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    if check and result.returncode != 0:
        raise Failure(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def git_ok(
    *args: str,
    repo: Path,
    env: dict[str, str] | None = None,
) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode == 0


def rev_parse(ref: str, repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", ref],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None
