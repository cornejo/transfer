from __future__ import annotations

import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

import click

from transfer.exchange import DEFAULT_RECEIVER_CONFIG, receive_payload
from transfer.git import Failure, git, git_ok, rev_parse

SUPPORTED_FORMATS = {1}

DEFAULT_BRANCH = "upstream"

TAG_PREFIX = "upstream/"

BASE_PREFIX = "diode/base/"

AMEND = "git commit --amend --reset-author --no-edit"


def _env() -> dict[str, str]:
    return {**os.environ, "GIT_EDITOR": "true", "GIT_SEQUENCE_EDITOR": "true"}


def read_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        raise Failure(f"no manifest in the bundle at {path.parent}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise Failure(f"malformed manifest line: {line!r}")
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()

    try:
        version = int(values.get("FORMAT", ""))
    except ValueError:
        raise Failure("manifest has no usable FORMAT; this is not a diode bundle")
    if version not in SUPPORTED_FORMATS:
        raise Failure(
            f"bundle format {version} is not supported by this apply "
            f"(understands {sorted(SUPPORTED_FORMATS)}).\n"
            "The sending side has been updated; update this repository's copy."
        )
    if values.get("MODE") not in {"full", "incremental", "resync"}:
        raise Failure(f"manifest has an unknown MODE: {values.get('MODE')!r}")
    return values


def read_tags(path: Path) -> list[tuple[str, int]]:
    if not path.exists():
        return []
    tags: list[tuple[str, int]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        tags.append((parts[0], int(parts[1])))
    return tags


def check_clean(repo: Path) -> None:
    if git("status", "--porcelain", repo=repo, env=_env()):
        raise Failure(
            "the working tree has uncommitted changes.\n"
            "Applying rewrites the checkout, so commit or stash them first."
        )


def check_preconditions(repo: Path, branch: str, mode: str, base: str) -> str | None:
    head = rev_parse(f"refs/heads/{branch}", repo=repo)

    if mode == "full":
        if head is not None:
            raise Failure(
                f"this is a full-history bundle, but branch '{branch}' already exists.\n"
                "It replays the repository from its root commit and can only create a\n"
                "branch, never extend one. If you meant to start over, delete the\n"
                f"branch first; if this repository is already tracking upstream, ask\n"
                "the sending side for an incremental bundle instead."
            )
        return None

    if head is None:
        raise Failure(
            f"this is a {mode} bundle, but branch '{branch}' does not exist.\n"
            "It continues from history that is not here. Apply the full-history\n"
            f"bundle first -- on the sending side, delete refs/diode/sent and re-send."
        )

    if not base:
        raise Failure(f"a {mode} bundle must name a BASE in its manifest")

    expected = rev_parse(f"refs/tags/{BASE_PREFIX}{base}", repo=repo)
    if expected is None:
        current = current_base(repo)
        raise Failure(
            f"this bundle continues from upstream commit {base[:12]}, which this\n"
            f"repository has never seen (no tag {BASE_PREFIX}{base}).\n"
            + (
                f"It is currently at {current[:12]}.\n"
                if current
                else "It has no recorded upstream position.\n"
            )
            + "A bundle has been skipped, or these bundles are being applied out of\n"
            "order. Apply the missing one first."
        )

    if expected != head:
        raise Failure(
            f"branch '{branch}' is at {head[:12]}, but the bundle expects it to be at\n"
            f"{expected[:12]} (upstream {base[:12]}).\n"
            "Something has committed to the branch since the last apply. It is\n"
            "reserved for transferred commits; move local work onto its own branch."
        )
    return head


def current_base(repo: Path) -> str | None:
    for ref in git("tag", "-l", f"{BASE_PREFIX}*", repo=repo, env=_env()).splitlines():
        return ref[len(BASE_PREFIX) :]
    return None


def apply_patches(repo: Path, patches: list[Path], start: str | None) -> None:
    result = subprocess.run(
        ["git", "-C", str(repo), "am", *[str(p) for p in patches]],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Failure(
            "the patches did not apply:\n"
            + (result.stdout.strip() or result.stderr.strip())
        )

    args = ["rebase", "--exec", AMEND]
    args += ["--root"] if start is None else [start]
    git(*args, repo=repo, env=_env())


def rollback(
    repo: Path,
    branch: str,
    original_branch: str | None,
    original_commit: str | None,
    branch_existed: bool,
) -> None:
    env = _env()
    git_ok("am", "--abort", repo=repo, env=env)
    git_ok("rebase", "--abort", repo=repo, env=env)

    if original_commit is not None:
        target = original_branch or original_commit
        git_ok("checkout", "-q", "--force", target, repo=repo, env=env)
        git_ok("reset", "--hard", original_commit, repo=repo, env=env)
    else:
        if original_branch:
            git_ok(
                "symbolic-ref", "HEAD", f"refs/heads/{original_branch}", repo=repo, env=env
            )
        git_ok("reset", "-q", repo=repo, env=env)
        git_ok("clean", "-qfd", repo=repo, env=env)

    if not branch_existed and rev_parse(f"refs/heads/{branch}", repo=repo) is not None:
        git_ok("branch", "-D", branch, repo=repo, env=env)


def place_tags(
    repo: Path, tags: list[tuple[str, int]], commits: list[str]
) -> tuple[int, list[str]]:
    placed = 0
    problems: list[str] = []
    for name, number in tags:
        index = number - 1
        if not 0 <= index < len(commits):
            problems.append(f"{name}: patch {number} is not in this bundle")
            continue
        target = f"{TAG_PREFIX}{name}"
        result = subprocess.run(
            ["git", "-C", str(repo), "tag", "-f", target, commits[index]],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            problems.append(f"{target}: {result.stderr.strip()}")
            continue
        placed += 1
    return placed, problems


def move_base(repo: Path, head_upstream: str, previous: str, commit: str) -> None:
    env = _env()
    git("tag", "-f", f"{BASE_PREFIX}{head_upstream}", commit, repo=repo, env=env)
    if previous and previous != head_upstream:
        git_ok("tag", "-d", f"{BASE_PREFIX}{previous}", repo=repo, env=env)


def receive_bundle(
    config_path: Path, source: str | None, stack: list[tempfile.TemporaryDirectory[str]]
) -> Path:
    """Receive the bundle over the encrypted transport, as `transfer receive` would."""
    click.echo(f"Receiving from {source}..." if source else "Receiving...")
    payload = receive_payload(config_path, source)
    holder = tempfile.TemporaryDirectory()
    stack.append(holder)
    dest = Path(holder.name) / "bundle.tar"
    dest.write_bytes(payload.plaintext)
    click.echo(f"Received {len(payload.plaintext)} bytes")
    return dest


def resolve_bundle(path: Path, stack: list[tempfile.TemporaryDirectory[str]]) -> Path:
    if path.is_dir():
        return path
    if not path.exists():
        raise Failure(f"no such bundle: {path}")
    holder = tempfile.TemporaryDirectory()
    stack.append(holder)
    with tarfile.open(path) as tar:
        tar.extractall(holder.name, filter="data")
    root = Path(holder.name)
    if (root / "manifest").exists():
        return root
    entries = [p for p in root.iterdir() if p.is_dir()]
    if len(entries) == 1 and (entries[0] / "manifest").exists():
        return entries[0]
    raise Failure(f"{path} does not look like a diode bundle")


def repo_apply(
    *,
    repo: Path,
    branch: str,
    config_path: Path = DEFAULT_RECEIVER_CONFIG,
    source: str | None = None,
) -> None:
    repo = repo.resolve()
    holders: list[tempfile.TemporaryDirectory[str]] = []
    env = _env()

    try:
        if not git_ok("rev-parse", "--is-inside-work-tree", repo=repo, env=env):
            raise Failure(f"{repo} is not a git repository")

        received = receive_bundle(config_path, source, holders)
        resolved_bundle = resolve_bundle(received, holders)
        manifest = read_manifest(resolved_bundle / "manifest")
        mode = manifest["MODE"]
        base = manifest.get("BASE", "")
        head_upstream = manifest.get("HEAD", "")
        if not head_upstream:
            raise Failure("manifest does not name the upstream HEAD it carries")

        patches = sorted((resolved_bundle / "patches").glob("*.patch"))
        if not patches:
            click.echo("Bundle contains no patches")
            return

        check_clean(repo)
        start = check_preconditions(repo, branch, mode, base)

        original_branch = (
            git("symbolic-ref", "--quiet", "--short", "HEAD", repo=repo, check=False, env=env)
            or None
        )
        original_commit = rev_parse("HEAD", repo=repo)
        branch_existed = start is not None

        if branch_existed:
            git("checkout", "-q", branch, repo=repo, env=env)
        else:
            git("checkout", "-q", "--orphan", branch, repo=repo, env=env)
            git_ok("rm", "-rq", "--cached", ".", repo=repo, env=env)
            git_ok("clean", "-qfd", repo=repo, env=env)

        click.echo(f"Applying {len(patches)} patch(es) to '{branch}' ({mode})...")
        try:
            apply_patches(repo, patches, start)
        except Failure:
            rollback(repo, branch, original_branch, original_commit, branch_existed)
            click.echo(
                "Nothing was applied; the repository is as it was.", err=True
            )
            raise

        span = "HEAD" if start is None else f"{start}..HEAD"
        commits = git("rev-list", "--reverse", span, repo=repo, env=env).splitlines()

        placed, problems = place_tags(
            repo, read_tags(resolved_bundle / "tags.txt"), commits
        )
        move_base(repo, head_upstream, base, commits[-1])

        if original_commit is not None and original_branch:
            git("checkout", "-q", original_branch, repo=repo, env=env)
            landed = f"'{branch}'"
        else:
            landed = f"'{branch}' (now checked out)"

        click.echo(f"Applied {len(commits)} commit(s) to {landed}")
        if placed:
            click.echo(f"Placed {placed} tag(s) under {TAG_PREFIX}")
        for problem in problems:
            click.echo(f"Warning: could not place tag {problem}", err=True)
        click.echo(f"Upstream position: {head_upstream[:12]} ({BASE_PREFIX}{head_upstream})")
    finally:
        for holder in holders:
            holder.cleanup()
