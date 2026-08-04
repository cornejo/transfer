from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return self.out + self.err


@dataclass
class Repo:
    path: Path

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            env=_env(),
        )
        assert result.returncode == 0, f"git {args}: {result.stderr}"
        return result.stdout.strip()

    def write(self, name: str, content: str) -> None:
        (self.path / name).write_text(content)

    def commit(self, name: str, content: str | None = None) -> str:
        (self.path / f"{name}.txt").write_text(f"{content or name}\n")
        self.git("add", "-A")
        self.git("commit", "-qm", name)
        return self.head

    def commit_binary(self, name: str, data: bytes) -> str:
        (self.path / name).write_bytes(data)
        self.git("add", "-A")
        self.git("commit", "-qm", f"add {name}")
        return self.head

    @property
    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def subjects(self, ref: str = "HEAD") -> list[str]:
        out = self.git("log", "--reverse", "--format=%s", ref)
        return out.splitlines() if out else []

    def tags(self) -> list[str]:
        out = self.git("tag", "-l")
        return out.splitlines() if out else []

    def ref(self, name: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(self.path), "rev-parse", "--verify", "--quiet", name],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None

    def send(self, *args: str) -> Result:
        return _run(
            [
                sys.executable,
                "-m",
                "transfer",
                "repo-send",
                "--repo",
                str(self.path),
                "--no-lint",
                "--transfer-command",
                "true",
                "--keep-export",
                *args,
            ]
        )

    def apply(self, bundle: Path, *args: str) -> Result:
        return _run(
            [
                sys.executable,
                "-m",
                "transfer",
                "repo-apply",
                str(bundle),
                "--repo",
                str(self.path),
                *args,
            ]
        )

    @property
    def bundle(self) -> Path:
        return self.path / "export"


def _env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_EDITOR": "true",
        "GIT_SEQUENCE_EDITOR": "true",
    }


def _run(argv: list[str]) -> Result:
    result = subprocess.run(argv, capture_output=True, text=True, env=_env())
    return Result(result.returncode, result.stdout, result.stderr)


def init_repo(path: Path) -> Repo:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(path)], check=True, env=_env()
    )
    repo = Repo(path)
    repo.git("config", "user.name", "Committer")
    repo.git("config", "user.email", "committer@example.com")
    return repo


@pytest.fixture
def source(tmp_path: Path) -> Repo:
    """The sending side, with three commits already on it."""
    repo = init_repo(tmp_path / "source")
    for name in ("one", "two", "three"):
        repo.commit(name)
    return repo


@pytest.fixture
def target(tmp_path: Path) -> Repo:
    """The receiving side: a real repository with no commits."""
    return init_repo(tmp_path / "target")
