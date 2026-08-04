from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from transfer.cli import main
from transfer.crypto import encode_key, generate_keypair, encrypt


class TestInitReceiver:
    def test_creates_config_and_prints_public_key(self, tmp_path: Path) -> None:
        config_path = tmp_path / "receiver.toml"
        runner = CliRunner()
        result = runner.invoke(
            main, ["init-receiver", "--url", "https://example.com/data", "--config", str(config_path)]
        )
        assert result.exit_code == 0
        assert "Public key" in result.output
        assert config_path.exists()
        text = config_path.read_text()
        assert "https://example.com/data" in text
        assert "private_key" in text


class TestInitSender:
    def test_creates_config(self, tmp_path: Path) -> None:
        _, public = generate_keypair()
        config_path = tmp_path / "sender.toml"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init-sender",
                "--public-key", encode_key(public),
                "--repo", "git@host:repo.git",
                "--branch", "data",
                "--config", str(config_path),
            ],
        )
        assert result.exit_code == 0
        assert config_path.exists()
        text = config_path.read_text()
        assert "git@host:repo.git" in text
        assert "data" in text

    def test_saves_valid_key(self, tmp_path: Path) -> None:
        _, public = generate_keypair()
        config_path = tmp_path / "sender.toml"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init-sender",
                "--public-key", encode_key(public),
                "--repo", "git@other:repo.git",
                "--branch", "xfer",
                "--config", str(config_path),
            ],
        )
        assert result.exit_code == 0
        assert encode_key(public) in config_path.read_text()


class TestSend:
    def test_file_not_found(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["send", "/nonexistent/file"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_encrypts_and_pushes(self, tmp_path: Path) -> None:
        _, public = generate_keypair()
        config_path = tmp_path / "sender.toml"
        config_path.write_text(
            f'public_key = "{encode_key(public)}"\n'
            f'repo = "git@host:repo.git"\n'
            f'branch = "data"\n'
        )
        file_path = tmp_path / "payload.txt"
        file_path.write_text("secret data")

        runner = CliRunner()
        with patch("transfer.cli.push_data") as mock_push:
            result = runner.invoke(
                main, ["send", str(file_path), "--config", str(config_path)]
            )
        assert result.exit_code == 0
        assert "Encrypted" in result.output
        assert "Pushed" in result.output
        mock_push.assert_called_once()


class TestReceive:
    def test_decrypts_and_writes_output(self, tmp_path: Path) -> None:
        private, public = generate_keypair()
        plaintext = b"the secret"
        encrypted = encrypt(plaintext, public)

        config_path = tmp_path / "receiver.toml"
        config_path.write_text(
            f'private_key = "{encode_key(private)}"\n'
            f'url = "https://example.com/data"\n'
        )
        output_path = tmp_path / "output.txt"

        runner = CliRunner()
        with patch("transfer.cli.download_data", return_value=encrypted):
            result = runner.invoke(
                main,
                ["receive", str(output_path), "--config", str(config_path)],
            )
        assert result.exit_code == 0
        assert output_path.read_bytes() == plaintext

    def test_detects_duplicate_download(self, tmp_path: Path) -> None:
        private, public = generate_keypair()
        encrypted = encrypt(b"data", public)

        config_path = tmp_path / "receiver.toml"
        config_path.write_text(
            f'private_key = "{encode_key(private)}"\n'
            f'url = "https://example.com/data"\n'
        )
        output_path = tmp_path / "output.txt"

        runner = CliRunner()
        with patch("transfer.cli.download_data", return_value=encrypted):
            result = runner.invoke(
                main,
                ["receive", str(output_path), "--config", str(config_path)],
            )
            assert result.exit_code == 0

            result2 = runner.invoke(
                main,
                ["receive", str(output_path), "--config", str(config_path)],
            )
            assert result2.exit_code != 0
            assert "not changed" in result2.output

    def test_redownload_flag(self, tmp_path: Path) -> None:
        private, public = generate_keypair()
        encrypted = encrypt(b"data", public)

        config_path = tmp_path / "receiver.toml"
        config_path.write_text(
            f'private_key = "{encode_key(private)}"\n'
            f'url = "https://example.com/data"\n'
        )
        output_path = tmp_path / "output.txt"

        runner = CliRunner()
        with patch("transfer.cli.download_data", return_value=encrypted):
            runner.invoke(
                main,
                ["receive", str(output_path), "--config", str(config_path)],
            )
            result = runner.invoke(
                main,
                ["receive", str(output_path), "--config", str(config_path), "--redownload"],
            )
            assert result.exit_code == 0

    def test_redownload_rejects_changed_data(self, tmp_path: Path) -> None:
        private, public = generate_keypair()
        encrypted1 = encrypt(b"data1", public)
        encrypted2 = encrypt(b"data2", public)

        config_path = tmp_path / "receiver.toml"
        config_path.write_text(
            f'private_key = "{encode_key(private)}"\n'
            f'url = "https://example.com/data"\n'
        )
        output_path = tmp_path / "output.txt"

        runner = CliRunner()
        with patch("transfer.cli.download_data", return_value=encrypted1):
            runner.invoke(
                main,
                ["receive", str(output_path), "--config", str(config_path)],
            )

        with patch("transfer.cli.download_data", return_value=encrypted2):
            result = runner.invoke(
                main,
                ["receive", str(output_path), "--config", str(config_path), "--redownload"],
            )
            assert result.exit_code != 0
            assert "changed" in result.output


class TestDestroy:
    def test_calls_delete_branch(self, tmp_path: Path) -> None:
        _, public = generate_keypair()
        config_path = tmp_path / "sender.toml"
        config_path.write_text(
            f'public_key = "{encode_key(public)}"\n'
            f'repo = "git@host:repo.git"\n'
            f'branch = "data"\n'
        )

        runner = CliRunner()
        with patch("transfer.cli.delete_branch") as mock_delete:
            result = runner.invoke(
                main, ["destroy", "--config", str(config_path)]
            )
        assert result.exit_code == 0
        mock_delete.assert_called_once_with("git@host:repo.git", "data")


class TestRepoSendHelp:
    def test_command_is_registered(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["repo-send", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--resync" in result.output


class TestRepoApplyHelp:
    def test_command_is_registered(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["repo-apply", "--help"])
        assert result.exit_code == 0
        assert "BUNDLE" in result.output
        assert "--branch" in result.output
