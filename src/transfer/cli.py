from __future__ import annotations

from pathlib import Path

import click

from transfer.config import (
    CONFIG_DIR,
    ReceiverConfig,
    SenderConfig,
    save_receiver_config,
    save_sender_config,
)
from transfer.crypto import decode_key, encode_key, generate_keypair
from transfer.exchange import receive_payload, send_payload, sender_config
from transfer.git import Failure
from transfer.repo_apply import DEFAULT_BRANCH, repo_apply
from transfer.repo_send import TAG_PATTERN, repo_send
from transfer.transport import delete_branch

_DEFAULT_SENDER_CONFIG = str(CONFIG_DIR / "sender.toml")
_DEFAULT_RECEIVER_CONFIG = str(CONFIG_DIR / "receiver.toml")


@click.group()
def main() -> None:
    pass


@main.command("init-receiver")
@click.option("--url", required=True, help="Raw GitHub URL for the data file.")
@click.option("--config", "config_path", default=_DEFAULT_RECEIVER_CONFIG)
def init_receiver(url: str, config_path: str) -> None:
    private_bytes, public_bytes = generate_keypair()
    config = ReceiverConfig(
        private_key=encode_key(private_bytes),
        url=url,
    )
    save_receiver_config(config, Path(config_path))
    click.echo(f"Receiver config written to {config_path}")
    click.echo(f"Public key (share with sender): {encode_key(public_bytes)}")


@main.command("init-sender")
@click.option("--public-key", required=True, help="Recipient's public key.")
@click.option("--repo", required=True, help="SSH URL of the GitHub repo.")
@click.option("--branch", required=True, help="Branch name to use for transfers.")
@click.option("--config", "config_path", default=_DEFAULT_SENDER_CONFIG)
def init_sender(public_key: str, repo: str, branch: str, config_path: str) -> None:
    decode_key(public_key)
    config = SenderConfig(public_key=public_key, repo=repo, branch=branch)
    save_sender_config(config, Path(config_path))
    click.echo(f"Sender config written to {config_path}")


@main.command()
@click.argument("file")
@click.option("--config", "config_path", default=_DEFAULT_SENDER_CONFIG)
def send(file: str, config_path: str) -> None:
    file_path = Path(file)
    if not file_path.is_file():
        raise click.ClickException(f"file not found: {file}")
    plaintext = file_path.read_bytes()
    try:
        payload = send_payload(plaintext, Path(config_path))
    except Failure as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Encrypted {len(plaintext)} bytes -> {len(payload.encrypted)} bytes")
    click.echo("Pushed to remote.")


@main.command()
@click.argument("output")
@click.option("--config", "config_path", default=_DEFAULT_RECEIVER_CONFIG)
@click.option(
    "--source",
    default=None,
    help="URL or file path to read the data from, instead of the configured URL.",
)
def receive(output: str, config_path: str, source: str | None) -> None:
    click.echo(f"Reading from {source}..." if source else "Downloading...")
    try:
        payload = receive_payload(Path(config_path), source)
    except Failure as exc:
        raise click.ClickException(str(exc)) from exc
    Path(output).write_bytes(payload.plaintext)
    click.echo(f"Decrypted {len(payload.plaintext)} bytes -> {output}")


@main.command()
@click.option("--config", "config_path", default=_DEFAULT_SENDER_CONFIG)
def destroy(config_path: str) -> None:
    try:
        config = sender_config(Path(config_path))
    except Failure as exc:
        raise click.ClickException(str(exc)) from exc
    delete_branch(config.repo, config.branch)
    click.echo(f"Deleted remote branch '{config.branch}'.")


@main.command("repo-send")
@click.option("--repo", type=click.Path(path_type=Path), default=Path("."), help="Path to the git repository.")
@click.option("--export-dir", type=click.Path(path_type=Path), default=None, help="Directory for the exported bundle.")
@click.option("--resync", is_flag=True, help="Send one squashed commit after a history rewrite.")
@click.option("--tag-pattern", default=TAG_PATTERN, help="Regex for version tags to include.")
@click.option("--no-lint", is_flag=True, help="Skip the black --check lint gate.")
@click.option("--config", "config_path", default=_DEFAULT_SENDER_CONFIG)
@click.option("--keep-export", is_flag=True, help="Leave the export directory after sending.")
@click.option("--no-transfer", is_flag=True, help="Build the bundle without sending or moving the marker.")
def repo_send_cmd(
    repo: Path,
    export_dir: Path | None,
    resync: bool,
    tag_pattern: str,
    no_lint: bool,
    config_path: str,
    keep_export: bool,
    no_transfer: bool,
) -> None:
    """Export new commits and send them with `send`."""
    try:
        repo_send(
            repo=repo,
            export_dir=export_dir,
            resync=resync,
            tag_pattern=tag_pattern,
            no_lint=no_lint,
            config_path=Path(config_path),
            keep_export=keep_export,
            no_transfer=no_transfer,
        )
    except Failure as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("repo-apply")
@click.option("--repo", type=click.Path(path_type=Path), default=Path("."), help="Path to the receiving git repository.")
@click.option("--branch", default=DEFAULT_BRANCH, help="Branch to apply patches to.")
@click.option("--config", "config_path", default=_DEFAULT_RECEIVER_CONFIG)
@click.option(
    "--source",
    default=None,
    help="URL or file path to receive from, instead of the configured URL.",
)
def repo_apply_cmd(repo: Path, branch: str, config_path: str, source: str | None) -> None:
    """Receive a diode bundle with `receive` and apply it."""
    try:
        repo_apply(
            repo=repo,
            branch=branch,
            config_path=Path(config_path),
            source=source,
        )
    except Failure as exc:
        raise click.ClickException(str(exc)) from exc
