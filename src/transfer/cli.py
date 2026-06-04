from __future__ import annotations

from pathlib import Path

import click

from transfer.config import (
    CONFIG_DIR,
    ReceiverConfig,
    SenderConfig,
    load_receiver_config,
    load_sender_config,
    save_receiver_config,
    save_sender_config,
)
from transfer.crypto import decode_key, encode_key, encrypt, decrypt, generate_keypair
from transfer.transport import delete_branch, download_data, push_data

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
    config = load_sender_config(Path(config_path))
    plaintext = file_path.read_bytes()
    recipient_key = decode_key(config.public_key)
    encrypted = encrypt(plaintext, recipient_key)
    click.echo(f"Encrypted {len(plaintext)} bytes -> {len(encrypted)} bytes")
    push_data(encrypted, config.repo, config.branch)
    click.echo("Pushed to remote.")


@main.command()
@click.argument("output")
@click.option("--config", "config_path", default=_DEFAULT_RECEIVER_CONFIG)
def receive(output: str, config_path: str) -> None:
    config = load_receiver_config(Path(config_path))
    click.echo("Downloading...")
    encrypted = download_data(config.url)
    private_key = decode_key(config.private_key)
    plaintext = decrypt(encrypted, private_key)
    Path(output).write_bytes(plaintext)
    click.echo(f"Decrypted {len(plaintext)} bytes -> {output}")


@main.command()
@click.option("--config", "config_path", default=_DEFAULT_SENDER_CONFIG)
def destroy(config_path: str) -> None:
    config = load_sender_config(Path(config_path))
    delete_branch(config.repo, config.branch)
    click.echo(f"Deleted remote branch '{config.branch}'.")
