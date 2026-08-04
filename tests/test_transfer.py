"""End-to-end: build a bundle from one repository, apply it to another."""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import Repo, init_repo


def transfer(source: Repo, target: Repo, *send_args: str) -> None:
    """The happy path, asserted, so tests can use it as a setup step."""
    sent = source.send(*send_args)
    assert sent.code == 0, sent.text
    applied = target.apply(source.bundle)
    assert applied.code == 0, applied.text


class TestFullHistory:
    def test_it_creates_the_branch_from_the_root_commit(
        self, source: Repo, target: Repo
    ) -> None:
        transfer(source, target)

        assert target.subjects("upstream") == ["one", "two", "three"]
        # The branch carries the root commit; nothing precedes it.
        assert len(target.git("rev-list", "--max-parents=0", "upstream").split()) == 1

    def test_it_refuses_a_branch_that_already_exists(
        self, source: Repo, target: Repo
    ) -> None:
        transfer(source, target)
        source.commit("four")

        # A second full bundle, as if the sender had lost its state.
        source.git("update-ref", "-d", "refs/diode/sent")
        assert source.send().code == 0
        result = target.apply(source.bundle)

        assert result.code == 1
        assert "already exists" in result.text
        assert target.subjects("upstream") == ["one", "two", "three"]

    def test_it_leaves_the_original_branch_checked_out(
        self, source: Repo, target: Repo
    ) -> None:
        target.commit("local")
        transfer(source, target)

        assert target.git("symbolic-ref", "--short", "HEAD") == "main"
        assert target.subjects("main") == ["local"]
        assert target.subjects("upstream") == ["one", "two", "three"]

    def test_it_carries_binary_files(self, source: Repo, target: Repo) -> None:
        data = bytes(range(256)) * 40
        source.commit_binary("blob.bin", data)
        transfer(source, target)

        target.git("checkout", "-q", "upstream")
        assert (target.path / "blob.bin").read_bytes() == data


class TestIncremental:
    def test_it_extends_the_branch(self, source: Repo, target: Repo) -> None:
        transfer(source, target)
        source.commit("four")
        source.commit("five")
        transfer(source, target)

        assert target.subjects("upstream") == ["one", "two", "three", "four", "five"]

    def test_it_refuses_a_repository_that_has_never_been_seeded(
        self, source: Repo, target: Repo
    ) -> None:
        # The full bundle is built but never applied; the next one continues
        # from history the target has never had.
        assert source.send().code == 0
        source.commit("four")
        assert source.send().code == 0

        result = target.apply(source.bundle)

        assert result.code == 1
        assert "does not exist" in result.text

    def test_it_refuses_a_bundle_whose_base_was_never_applied(
        self, source: Repo, target: Repo
    ) -> None:
        transfer(source, target)

        source.commit("four")
        assert source.send().code == 0
        skipped = Path(str(source.bundle) + ".skipped")
        source.bundle.rename(skipped)

        source.commit("five")
        assert source.send().code == 0
        result = target.apply(source.bundle)

        assert result.code == 1
        assert "never seen" in result.text
        assert target.subjects("upstream") == ["one", "two", "three"]

        # And it applies once the skipped bundle is put back in order.
        assert target.apply(skipped).code == 0
        assert target.apply(source.bundle).code == 0
        assert target.subjects("upstream")[-2:] == ["four", "five"]

    def test_it_refuses_when_the_branch_has_moved_underneath_it(
        self, source: Repo, target: Repo
    ) -> None:
        target.commit("local")
        transfer(source, target)
        target.git("checkout", "-q", "upstream")
        target.commit("local meddling")
        target.git("checkout", "-q", "main")

        source.commit("four")
        assert source.send().code == 0
        result = target.apply(source.bundle)

        assert result.code == 1
        assert "reserved for transferred commits" in result.text

    def test_it_reports_nothing_to_do(self, source: Repo, target: Repo) -> None:
        transfer(source, target)
        result = source.send()

        assert result.code == 0
        assert "No new commits" in result.text


class TestAuthorship:
    def test_the_wire_carries_a_fixed_identity(self, source: Repo) -> None:
        assert source.send().code == 0
        text = (source.bundle / "patches" / "0001-one.patch").read_text()

        assert "From: author <author>" in text
        assert "committer@example.com" not in text

    def test_the_applied_commits_belong_to_whoever_applied_them(
        self, source: Repo, target: Repo
    ) -> None:
        target.git("config", "user.name", "Receiver")
        target.git("config", "user.email", "receiver@example.com")
        transfer(source, target)

        people = target.git("log", "--format=%an <%ae>|%cn <%ce>", "upstream")
        for line in people.splitlines():
            assert (
                line
                == "Receiver <receiver@example.com>|Receiver <receiver@example.com>"
            )

    def test_the_upstream_sha_survives_scrubbing(self, source: Repo) -> None:
        # Not used by anything today, but it is the only cross-diode identity
        # available if a future version needs one.
        assert source.send().code == 0
        first = (
            (source.bundle / "patches" / "0001-one.patch").read_text().split("\n")[0]
        )

        assert (
            first.split()[1] == source.git("rev-list", "--reverse", "HEAD").split()[0]
        )


class TestTags:
    def test_only_version_tags_cross(self, source: Repo, target: Repo) -> None:
        source.git("tag", "v1.0.0", "HEAD~2")
        source.git("tag", "2.0.0", "HEAD~1")
        source.git("tag", "nightly", "HEAD")
        source.git("tag", "v1.0.0-rc1", "HEAD")
        source.git("tag", "release/final", "HEAD")
        transfer(source, target)

        assert sorted(target.tags()) == sorted(
            ["upstream/v1.0.0", "upstream/2.0.0", f"diode/base/{source.head}"]
        )

    def test_a_tag_lands_on_the_right_commit(self, source: Repo, target: Repo) -> None:
        source.git("tag", "v1.0.0", "HEAD~1")
        transfer(source, target)

        tagged = target.git("log", "-1", "--format=%s", "upstream/v1.0.0")
        assert tagged == "two"

    def test_an_annotated_tag_is_peeled_to_its_commit(
        self, source: Repo, target: Repo
    ) -> None:
        source.git("tag", "-a", "-m", "release", "v1.0.0", "HEAD~1")
        transfer(source, target)

        assert target.git("log", "-1", "--format=%s", "upstream/v1.0.0") == "two"

    def test_a_reused_tag_name_moves_instead_of_failing(
        self, source: Repo, target: Repo
    ) -> None:
        source.git("tag", "v1.0.0", "HEAD~1")
        transfer(source, target)
        assert target.git("log", "-1", "--format=%s", "upstream/v1.0.0") == "two"

        # Same name, re-pointed upstream at a commit in the next bundle.
        source.commit("four")
        source.git("tag", "-f", "v1.0.0", "HEAD")
        transfer(source, target)

        assert target.git("log", "-1", "--format=%s", "upstream/v1.0.0") == "four"

    def test_a_tag_that_cannot_be_placed_does_not_abort_the_apply(
        self, source: Repo, target: Repo
    ) -> None:
        # Tag names cannot nest: with `upstream/1.0.0` present, git refuses to
        # create `upstream/1.0.0/9`. Nothing produces that from the version
        # pattern, so it is forced here to exercise the failure path.
        transfer(source, target)
        target.git("tag", "upstream/9.9.9", "upstream")
        source.commit("four")
        assert source.send().code == 0
        (source.bundle / "tags.txt").write_text("9.9.9/1 1\n")

        result = target.apply(source.bundle)

        assert result.code == 0
        assert "could not place tag" in result.text
        assert target.subjects("upstream")[-1] == "four"


class TestBaseMarker:
    def test_it_names_the_upstream_commit_and_moves_each_transfer(
        self, source: Repo, target: Repo
    ) -> None:
        first = source.head
        transfer(source, target)
        assert target.ref(f"refs/tags/diode/base/{first}") == target.ref("upstream")

        source.commit("four")
        second = source.head
        transfer(source, target)

        assert target.ref(f"refs/tags/diode/base/{second}") == target.ref("upstream")
        # Exactly one marker: the old one is dropped once the new one is written.
        assert [t for t in target.tags() if t.startswith("diode/base/")] == [
            f"diode/base/{second}"
        ]


class TestRewrittenHistory:
    def test_send_detects_a_rewrite_and_refuses(
        self, source: Repo, target: Repo
    ) -> None:
        transfer(source, target)
        source.git("commit", "-q", "--amend", "-m", "three reworded")

        result = source.send()

        assert result.code == 1
        assert "History was rewritten" in result.text
        assert "--resync" in result.text

    def test_the_marker_survives_gc(self, source: Repo, target: Repo) -> None:
        # A plain .last_commit file names a commit that gc will happily delete
        # once a rewrite orphans it. A ref keeps it reachable.
        transfer(source, target)
        sent = source.ref("refs/diode/sent")
        source.git("commit", "-q", "--amend", "-m", "three reworded")
        source.git("reflog", "expire", "--expire=now", "--all")
        source.git("gc", "--prune=now", "-q")

        assert source.ref("refs/diode/sent") == sent
        assert source.git("cat-file", "-t", str(sent)) == "commit"

    def test_resync_sends_one_commit_carrying_the_difference(
        self, source: Repo, target: Repo
    ) -> None:
        transfer(source, target)
        source.git("reset", "-q", "--hard", "HEAD~2")
        source.commit("rebuilt")

        result = source.send("--resync")
        assert result.code == 0, result.text
        assert result.text.count("Mode: resync") == 1
        assert len(list((source.bundle / "patches").glob("*.patch"))) == 1

        assert target.apply(source.bundle).code == 0
        # The far side keeps its history and gains one commit whose tree
        # matches the rewritten source exactly.
        assert target.subjects("upstream")[:3] == ["one", "two", "three"]
        assert len(target.subjects("upstream")) == 4
        assert target.git("rev-parse", "upstream^{tree}") == source.git(
            "rev-parse", "HEAD^{tree}"
        )

    def test_resync_refuses_when_nothing_was_rewritten(
        self, source: Repo, target: Repo
    ) -> None:
        transfer(source, target)
        source.commit("four")

        result = source.send("--resync")

        assert result.code == 1
        assert "was not rewritten" in result.text

    def test_resync_refuses_a_rewrite_that_changed_no_content(
        self, source: Repo, target: Repo
    ) -> None:
        transfer(source, target)
        source.git("commit", "-q", "--amend", "-m", "three reworded")

        result = source.send("--resync")

        assert result.code == 1
        assert "same tree" in result.text
        assert "update-ref" in result.text

    def test_incremental_continues_after_a_resync(
        self, source: Repo, target: Repo
    ) -> None:
        transfer(source, target)
        source.git("reset", "-q", "--hard", "HEAD~2")
        source.commit("rebuilt")
        transfer(source, target, "--resync")

        source.commit("after")
        transfer(source, target)

        assert target.subjects("upstream")[-1] == "after"


class TestAtomicity:
    def test_a_conflicting_series_leaves_the_repository_untouched(
        self, source: Repo, target: Repo, tmp_path: Path
    ) -> None:
        target.commit("local")
        transfer(source, target)
        source.commit("four")
        source.write("one.txt", "rewritten\n")
        source.git("add", "-A")
        source.git("commit", "-qm", "five")
        assert source.send().code == 0

        # Patch 1 of 2 still applies; patch 2 now expects content that is not
        # there, so the series must stop with nothing committed.
        patches = sorted((source.bundle / "patches").glob("*.patch"))
        lines = patches[-1].read_text().split("\n")
        patches[-1].write_text(
            "\n".join("-never was this" if line == "-one" else line for line in lines)
        )

        before = target.ref("upstream")
        result = target.apply(source.bundle)

        assert result.code == 1
        assert target.ref("upstream") == before
        assert target.subjects("upstream") == ["one", "two", "three"]
        assert target.git("status", "--porcelain") == ""

    def test_a_failed_full_apply_leaves_no_branch_behind(
        self, source: Repo, target: Repo
    ) -> None:
        assert source.send().code == 0
        patches = sorted((source.bundle / "patches").glob("*.patch"))
        patches[-1].write_text(
            "From x\nFrom: a <a>\nSubject: [PATCH] junk\n\nnot a patch\n"
        )

        result = target.apply(source.bundle)

        assert result.code == 1
        assert target.ref("refs/heads/upstream") is None
        assert target.git("symbolic-ref", "--short", "HEAD") == "main"
        assert target.git("status", "--porcelain") == ""

    def test_it_refuses_to_run_with_a_dirty_tree(
        self, source: Repo, target: Repo
    ) -> None:
        assert source.send().code == 0
        (target.path / "scratch.txt").write_text("work in progress")

        result = target.apply(source.bundle)

        assert result.code == 1
        assert "uncommitted changes" in result.text
        assert (target.path / "scratch.txt").exists()


class TestBundleHandling:
    def test_it_accepts_a_tar_archive(
        self, source: Repo, target: Repo, tmp_path: Path
    ) -> None:
        assert source.send().code == 0
        archive = tmp_path / "export.tar"
        subprocess.run(
            ["tar", "cf", str(archive), "-C", str(source.path), "export"], check=True
        )

        assert target.apply(archive).code == 0
        assert target.subjects("upstream") == ["one", "two", "three"]

    def test_it_refuses_a_bundle_from_a_newer_sender(
        self, source: Repo, target: Repo
    ) -> None:
        assert source.send().code == 0
        manifest = source.bundle / "manifest"
        manifest.write_text(manifest.read_text().replace("FORMAT=1", "FORMAT=99"))

        result = target.apply(source.bundle)

        assert result.code == 1
        assert "not supported" in result.text
        assert target.ref("refs/heads/upstream") is None

    def test_it_refuses_something_that_is_not_a_bundle(
        self, target: Repo, tmp_path: Path
    ) -> None:
        empty = tmp_path / "nothing"
        empty.mkdir()

        result = target.apply(empty)

        assert result.code == 1
        assert "no manifest" in result.text


class TestSendPreconditions:
    def test_it_refuses_a_repository_with_no_commits(self, tmp_path: Path) -> None:
        repo = init_repo(tmp_path / "empty")

        result = repo.send()

        assert result.code == 1
        assert "no commits" in result.text

    def test_the_marker_only_moves_once_the_bytes_are_away(self, source: Repo) -> None:
        # A failed transfer must leave the marker alone, so the next run
        # resends these commits rather than skipping past them.
        result = source.send("--transfer-command", "false")

        assert result.code == 1
        assert "resend the same commits" in result.text
        assert source.ref("refs/diode/sent") is None

    def test_the_marker_moves_after_a_successful_transfer(self, source: Repo) -> None:
        assert source.send().code == 0
        assert source.ref("refs/diode/sent") == source.head
