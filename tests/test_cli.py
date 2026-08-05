from __future__ import annotations

import base64
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
        with patch("transfer.exchange.push_data") as mock_push:
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
        with patch("transfer.exchange.download_data", return_value=encrypted):
            result = runner.invoke(
                main,
                ["receive", str(output_path), "--config", str(config_path)],
            )
        assert result.exit_code == 0
        assert output_path.read_bytes() == plaintext


class TestReceiveSourceOverride:
    def _config(self, tmp_path: Path, private: bytes) -> Path:
        config_path = tmp_path / "receiver.toml"
        config_path.write_text(
            f'private_key = "{encode_key(private)}"\n'
            f'url = "https://unavailable.example.com/data"\n'
        )
        return config_path

    def test_reads_from_a_local_file(self, tmp_path: Path) -> None:
        private, public = generate_keypair()
        plaintext = b"the secret"
        source_path = tmp_path / "data"
        source_path.write_text(base64.b64encode(encrypt(plaintext, public)).decode("ascii"))
        output_path = tmp_path / "output.txt"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "receive", str(output_path),
                "--config", str(self._config(tmp_path, private)),
                "--source", str(source_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert output_path.read_bytes() == plaintext

    def test_reads_from_an_alternative_url(self, tmp_path: Path) -> None:
        private, public = generate_keypair()
        encrypted = encrypt(b"the secret", public)
        output_path = tmp_path / "output.txt"

        runner = CliRunner()
        with patch("transfer.exchange.download_data", return_value=encrypted) as mock_download:
            result = runner.invoke(
                main,
                [
                    "receive", str(output_path),
                    "--config", str(self._config(tmp_path, private)),
                    "--source", "https://mirror.example.com/data",
                ],
            )
        assert result.exit_code == 0, result.output
        mock_download.assert_called_once_with("https://mirror.example.com/data")

    def test_reports_a_missing_source(self, tmp_path: Path) -> None:
        private, _ = generate_keypair()
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "receive", str(tmp_path / "output.txt"),
                "--config", str(self._config(tmp_path, private)),
                "--source", str(tmp_path / "nope"),
            ],
        )
        assert result.exit_code != 0
        assert "could not read" in result.output


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
        assert "--source" in result.output
        assert "--branch" in result.output
