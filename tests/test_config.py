from __future__ import annotations

from pathlib import Path

import pytest

from transfer.config import (
    ReceiverConfig,
    SenderConfig,
    load_receiver_config,
    load_sender_config,
    save_receiver_config,
    save_sender_config,
)


class TestSenderConfig:
    def test_roundtrip(self, tmp_path: Path) -> None:
        config = SenderConfig(
            public_key="abc123", repo="git@host:repo.git", branch="data"
        )
        path = tmp_path / "sender.toml"
        save_sender_config(config, path)
        loaded = load_sender_config(path)
        assert loaded == config

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "a" / "b" / "sender.toml"
        config = SenderConfig(public_key="k", repo="r", branch="b")
        save_sender_config(config, path)
        assert path.exists()

    def test_missing_field_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text('public_key = "k"\nrepo = "r"\n')
        with pytest.raises(TypeError, match="branch"):
            load_sender_config(path)

    def test_non_string_field_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text('public_key = "k"\nrepo = "r"\nbranch = 123\n')
        with pytest.raises(TypeError, match="branch"):
            load_sender_config(path)

    def test_is_frozen(self) -> None:
        config = SenderConfig(public_key="k", repo="r", branch="b")
        with pytest.raises(AttributeError):
            config.branch = "other"  # type: ignore[misc]


class TestReceiverConfig:
    def test_roundtrip(self, tmp_path: Path) -> None:
        config = ReceiverConfig(private_key="secret", url="https://example.com/data")
        path = tmp_path / "receiver.toml"
        save_receiver_config(config, path)
        loaded = load_receiver_config(path)
        assert loaded == config

    def test_missing_field_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text('private_key = "k"\n')
        with pytest.raises(TypeError, match="url"):
            load_receiver_config(path)
