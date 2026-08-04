from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import click

from transfer.git import Failure, git, git_ok, rev_parse

FORMAT = 1

SENT_REF = "refs/diode/sent"

TAG_PATTERN = r"^v?\d+\.\d+\.\d+$"

WIRE_AUTHOR = "author <author>"

LINT_COMMAND = ["uv", "run", "--with", "black", "--no-project", "black", "--check", "."]

TRANSFER_COMMAND = "transfer send"


def lint(repo: Path) -> None:
    result = subprocess.run(LINT_COMMAND, cwd=repo)
    if result.returncode != 0:
        raise Failure("black --check failed; format before sending (or pass --no-lint)")


def decide_mode(repo: Path, resync: bool) -> tuple[str, str | None]:
    base = rev_parse(SENT_REF, repo=repo)
    if base is None:
        if resync:
            raise Failure(
                f"--resync given, but {SENT_REF} does not exist -- nothing has been\n"
                "sent yet, so there is nothing to resynchronise against."
            )
        return "full", None

    if git_ok("merge-base", "--is-ancestor", base, "HEAD", repo=repo):
        if resync:
            raise Failure(
                "--resync given, but history was not rewritten: "
                f"{base[:12]} is still an ancestor of HEAD.\n"
                "Send this as a normal incremental transfer."
            )
        return "incremental", base

    if not resync:
        raise Failure(
            f"History was rewritten. {base[:12]} was transferred previously but is no\n"
            "longer an ancestor of HEAD, so the patches after it no longer exist and\n"
            "the far side cannot be brought forward commit by commit.\n\n"
            "Re-run with --resync to send a single squashed commit carrying the\n"
            "difference instead. The far side keeps its existing history and gains\n"
            "one commit; the rewritten commits are not replayed."
        )
    return "resync", base


def commits_in_range(repo: Path, mode: str, base: str | None) -> list[str]:
    if mode == "full":
        return git("rev-list", "--reverse", "HEAD", repo=repo).splitlines()
    if mode == "incremental":
        assert base is not None
        return git("rev-list", "--reverse", f"{base}..HEAD", repo=repo).splitlines()
    return [git("rev-parse", "HEAD", repo=repo)]


def write_patches(repo: Path, patch_dir: Path, mode: str, base: str | None) -> int:
    patch_dir.mkdir(parents=True, exist_ok=True)

    if mode == "resync":
        assert base is not None
        write_resync_patch(repo, patch_dir, base)
    else:
        args = ["format-patch", "--binary", "-o", str(patch_dir)]
        if mode == "full":
            args += ["--root", "HEAD"]
        else:
            assert base is not None
            args += [f"{base}..HEAD"]
        git(*args, repo=repo)

    patches = sorted(patch_dir.glob("*.patch"))
    for patch in patches:
        scrub_author(patch)
    return len(patches)


def scrub_author(patch: Path) -> None:
    lines = patch.read_text(encoding="utf-8", errors="surrogateescape").split("\n")
    for i, line in enumerate(lines):
        if line.startswith("From: "):
            lines[i] = f"From: {WIRE_AUTHOR}"
            break
        if line == "":
            break
    patch.write_text("\n".join(lines), encoding="utf-8", errors="surrogateescape")


def write_resync_patch(repo: Path, patch_dir: Path, base: str) -> None:
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "--binary", "--full-index", base, "HEAD"],
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        raise Failure(f"git diff failed:\n{diff.stderr.strip()}")
    if not diff.stdout.strip():
        raise Failure(
            "Nothing to resynchronise: the rewritten history produces the same tree\n"
            "as what was already transferred (a reword or author change, most\n"
            f"likely). Move the marker forward without sending anything:\n"
            f"    git update-ref {SENT_REF} HEAD"
        )

    head = git("rev-parse", "HEAD", repo=repo)
    date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    body = (
        f"From {head} Mon Sep 17 00:00:00 2001\n"
        f"From: {WIRE_AUTHOR}\n"
        f"Date: {date}\n"
        f"Subject: [PATCH] resync to {head[:12]}\n"
        "\n"
        "History on the sending side was rewritten, so the individual commits\n"
        "could not be replayed. This commit carries the net difference from\n"
        f"{base[:12]}, the last state transferred, to {head[:12]}.\n"
        "---\n"
        f"{diff.stdout}"
        "-- \n"
        "diode\n"
    )
    (patch_dir / "0001-resync.patch").write_text(body, encoding="utf-8")


def write_tags(repo: Path, path: Path, commits: list[str], pattern: str) -> int:
    matcher = re.compile(pattern)
    index = {commit: i + 1 for i, commit in enumerate(commits)}

    lines: list[str] = []
    for tag in git("tag", "-l", repo=repo).splitlines():
        if not matcher.match(tag):
            continue
        target = rev_parse(f"{tag}^{{}}", repo=repo)
        number = index.get(target or "")
        if number is not None:
            lines.append(f"{tag} {number}")

    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return len(lines)


def write_manifest(
    path: Path, mode: str, patch_count: int, base: str | None, head: str
) -> None:
    path.write_text(
        f"FORMAT={FORMAT}\n"
        f"MODE={mode}\n"
        f"PATCH_COUNT={patch_count}\n"
        f"BASE={base or ''}\n"
        f"HEAD={head}\n",
        encoding="utf-8",
    )


def build_archive(export_dir: Path, archive: Path) -> None:
    with tarfile.open(archive, "w") as tar:
        tar.add(export_dir, arcname=export_dir.name)


def run_transfer(archive: Path, repo: Path, command: str) -> None:
    argv = shlex.split(command)
    result = subprocess.run([*argv, str(archive)], cwd=repo)
    if result.returncode != 0:
        raise Failure(
            f"{command} exited {result.returncode}. "
            f"{SENT_REF} has not been moved, so re-running will resend the same commits."
        )


def repo_send(
    *,
    repo: Path,
    export_dir: Path | None,
    resync: bool,
    tag_pattern: str,
    no_lint: bool,
    transfer_command: str,
    keep_export: bool,
    no_transfer: bool,
) -> None:
    repo = repo.resolve()
    resolved_export_dir = (export_dir or repo / "export").resolve()
    archive = resolved_export_dir.parent / "export.tar"

    if not git_ok("rev-parse", "--is-inside-work-tree", repo=repo):
        raise Failure(f"{repo} is not a git repository")
    if rev_parse("HEAD", repo=repo) is None:
        raise Failure("this repository has no commits")

    if not no_lint:
        lint(repo)

    mode, base = decide_mode(repo, resync)
    head = git("rev-parse", "HEAD", repo=repo)

    if mode == "incremental" and base == head:
        click.echo("No new commits to export")
        return

    if resolved_export_dir.exists():
        shutil.rmtree(resolved_export_dir)
    resolved_export_dir.mkdir(parents=True)

    commits = commits_in_range(repo, mode, base)
    patch_count = write_patches(repo, resolved_export_dir / "patches", mode, base)
    if patch_count == 0:
        shutil.rmtree(resolved_export_dir)
        click.echo("No new commits to export")
        return

    tag_count = write_tags(
        repo, resolved_export_dir / "tags.txt", commits, tag_pattern
    )
    write_manifest(resolved_export_dir / "manifest", mode, patch_count, base, head)

    click.echo(f"Mode: {mode}")
    click.echo(f"Exported {patch_count} patch(es), {tag_count} tag(s)")

    if no_transfer:
        click.echo(f"Bundle left at {resolved_export_dir}")
        return

    build_archive(resolved_export_dir, archive)
    run_transfer(archive, repo, transfer_command)

    git("update-ref", SENT_REF, head, repo=repo)
    click.echo(f"Sent. {SENT_REF} now at {head[:12]}")

    if not keep_export:
        shutil.rmtree(resolved_export_dir)
    archive.unlink(missing_ok=True)
