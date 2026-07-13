from __future__ import annotations

import base64
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

_DATA_FILENAME = "data"


def push_data(encrypted: bytes, repo: str, branch: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / _DATA_FILENAME).write_text(base64.b64encode(encrypted).decode("ascii"))
        _git(tmp, "init", "-b", "main")
        _git(tmp, "add", _DATA_FILENAME)
        _git(
            tmp,
            "-c", "user.name=transfer",
            "-c", "user.email=noreply",
            "commit", "-m", _DATA_FILENAME,
        )
        subprocess.run(
            ["git", "push", "-f", repo, f"HEAD:{branch}"],
            cwd=tmp,
            check=True,
        )


def delete_branch(repo: str, branch: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _git(tmp, "init", "-b", "main")
        subprocess.run(
            ["git", "push", repo, "--delete", branch],
            cwd=tmp,
            check=True,
        )


def download_data(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url) as resp:
            raw: bytes = resp.read()
            return base64.b64decode(raw.strip())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            msg = "no data found at remote (404)"
            raise FileNotFoundError(msg) from e
        raise


def _git(cwd: str, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )
