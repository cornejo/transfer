from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from transfer.git import Failure, git, git_ok, rev_parse


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(tmp_path)], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True
    )
    (tmp_path / "file.txt").write_text("content\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True
    )
    return tmp_path


class TestGit:
    def test_returns_stdout(self, repo: Path) -> None:
        result = git("rev-parse", "HEAD", repo=repo)
        assert len(result) == 40

    def test_raises_on_failure(self, repo: Path) -> None:
        with pytest.raises(Failure, match="git .* failed"):
            git("checkout", "nonexistent", repo=repo)

    def test_check_false_suppresses_error(self, repo: Path) -> None:
        result = git("checkout", "nonexistent", repo=repo, check=False)
        assert isinstance(result, str)

    def test_custom_env(self, repo: Path) -> None:
        import os

        env = {**os.environ, "GIT_EDITOR": "true"}
        result = git("rev-parse", "HEAD", repo=repo, env=env)
        assert len(result) == 40


class TestGitOk:
    def test_returns_true_on_success(self, repo: Path) -> None:
        assert git_ok("rev-parse", "--is-inside-work-tree", repo=repo) is True

    def test_returns_false_on_failure(self, repo: Path) -> None:
        assert git_ok("rev-parse", "--verify", "nonexistent", repo=repo) is False


class TestRevParse:
    def test_resolves_existing_ref(self, repo: Path) -> None:
        sha = rev_parse("HEAD", repo=repo)
        assert sha is not None
        assert len(sha) == 40

    def test_returns_none_for_missing_ref(self, repo: Path) -> None:
        assert rev_parse("refs/heads/nonexistent", repo=repo) is None
