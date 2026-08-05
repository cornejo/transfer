from __future__ import annotations

import base64
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_DATA_FILENAME = "data"

_URL_SCHEMES = {"http", "https", "file", "ftp"}


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


def is_url(source: str) -> bool:
    """True if `source` names a URL rather than a filesystem path."""
    return urllib.parse.urlsplit(source).scheme in _URL_SCHEMES


def read_source(source: str) -> bytes:
    """Read the raw bytes of `source`, which may be a URL or a local path."""
    if is_url(source):
        try:
            with urllib.request.urlopen(source) as resp:
                raw: bytes = resp.read()
                return raw
        except urllib.error.HTTPError as e:
            if e.code == 404:
                msg = f"no data found at {source} (404)"
                raise FileNotFoundError(msg) from e
            raise

    path = Path(source).expanduser()
    if not path.is_file():
        msg = f"no data found at {source}"
        raise FileNotFoundError(msg)
    return path.read_bytes()


def download_data(source: str) -> bytes:
    return base64.b64decode(read_source(source).strip())


def _git(cwd: str, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )
