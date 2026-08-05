from __future__ import annotations

import os
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from transfer.crypto import encode_key, generate_keypair

BRANCH = "data"


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return self.out + self.err


@dataclass
class Hub:
    """The transport both sides share: a bare repo, and a config pair to reach it."""

    remote: Path
    sender_config: Path
    receiver_config: Path
    published: Path

    def serve(self) -> Path:
        """Serve what was last pushed, as a raw URL would.

        The payload lives in a branch on the remote; this is the step a hosting
        service does for real, extracting it to somewhere a receiver can read.
        """
        result = subprocess.run(
            ["git", "-C", str(self.remote), "show", f"{BRANCH}:data"],
            capture_output=True,
            text=True,
            env=_env(),
        )
        assert result.returncode == 0, f"nothing pushed to {BRANCH}: {result.stderr}"
        self.published.write_text(result.stdout)
        return self.published

    def break_remote(self) -> None:
        """Point the sender at a remote that is not there, so pushing fails."""
        text = self.sender_config.read_text()
        self.sender_config.write_text(
            text.replace(str(self.remote), str(self.remote) + "-gone")
        )


@dataclass
class Repo:
    path: Path
    hub: Hub | None = None

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
        config = ["--config", str(self.hub.sender_config)] if self.hub else []
        return _run(
            [
                sys.executable,
                "-m",
                "transfer",
                "repo-send",
                "--repo",
                str(self.path),
                "--no-lint",
                "--keep-export",
                *config,
                *args,
            ]
        )

    def apply(self, *args: str) -> Result:
        """Receive whatever the transport is serving and apply it."""
        config = ["--config", str(self.hub.receiver_config)] if self.hub else []
        return _run(
            [
                sys.executable,
                "-m",
                "transfer",
                "repo-apply",
                "--repo",
                str(self.path),
                *config,
                *args,
            ]
        )

    def resend(self, bundle: Path | None = None) -> None:
        """Put `bundle` on the transport by hand, as the end of repo-send does.

        Tests that doctor a bundle before it is applied need this: repo-send has
        already sent the pristine one, and there is no other way in.
        """
        assert self.hub is not None
        target = bundle if bundle is not None else self.bundle
        if target.is_dir():
            archive = target.parent / f"{target.name}.tar"
            with tarfile.open(archive, "w") as tar:
                tar.add(target, arcname=target.name)
        else:
            archive = target
        result = _run(
            [
                sys.executable,
                "-m",
                "transfer",
                "send",
                str(archive),
                "--config",
                str(self.hub.sender_config),
            ]
        )
        assert result.code == 0, result.text
        self.hub.serve()

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


def init_repo(path: Path, hub: Hub | None = None) -> Repo:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(path)], check=True, env=_env()
    )
    repo = Repo(path, hub)
    repo.git("config", "user.name", "Committer")
    repo.git("config", "user.email", "committer@example.com")
    return repo


@pytest.fixture
def hub(tmp_path: Path) -> Hub:
    """A working transport: real keys, and a bare repo standing in for the host."""
    remote = tmp_path / "hub.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=_env())

    private, public = generate_keypair()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    sender_config = config_dir / "sender.toml"
    sender_config.write_text(
        f'public_key = "{encode_key(public)}"\n'
        f'repo = "{remote}"\n'
        f'branch = "{BRANCH}"\n'
    )
    published = tmp_path / "published-data"
    receiver_config = config_dir / "receiver.toml"
    receiver_config.write_text(
        f'private_key = "{encode_key(private)}"\n'
        f'url = "{published.as_uri()}"\n'
    )
    return Hub(remote, sender_config, receiver_config, published)


@pytest.fixture
def source(tmp_path: Path, hub: Hub) -> Repo:
    """The sending side, with three commits already on it."""
    repo = init_repo(tmp_path / "source", hub)
    for name in ("one", "two", "three"):
        repo.commit(name)
    return repo


@pytest.fixture
def target(tmp_path: Path, hub: Hub) -> Repo:
    """The receiving side: a real repository with no commits."""
    return init_repo(tmp_path / "target", hub)
