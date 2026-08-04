from __future__ import annotations

import hashlib
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
from transfer.git import Failure
from transfer.repo_apply import DEFAULT_BRANCH, repo_apply
from transfer.repo_send import TAG_PATTERN, TRANSFER_COMMAND, repo_send
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


def _hash_file_for_config(config_path: Path) -> Path:
    return config_path.with_suffix(".sha256")


@main.command()
@click.argument("output")
@click.option("--config", "config_path", default=_DEFAULT_RECEIVER_CONFIG)
@click.option("--redownload", is_flag=True, help="Re-download a previously seen file.")
def receive(output: str, config_path: str, *, redownload: bool) -> None:
    cfg_path = Path(config_path)
    config = load_receiver_config(cfg_path)
    click.echo("Downloading...")
    encrypted = download_data(config.url)
    new_hash = hashlib.sha256(encrypted).hexdigest()
    hash_path = _hash_file_for_config(cfg_path)
    prev_hash = hash_path.read_text().strip() if hash_path.exists() else None

    if redownload:
        if prev_hash is not None and new_hash != prev_hash:
            raise click.ClickException(
                "remote data has changed since last download; "
                "run without --redownload to receive the new file"
            )
    else:
        if prev_hash is not None and new_hash == prev_hash:
            raise click.ClickException(
                "remote data has not changed since last download; "
                "use --redownload to download it again"
            )

    private_key = decode_key(config.private_key)
    plaintext = decrypt(encrypted, private_key)
    Path(output).write_bytes(plaintext)
    hash_path.write_text(new_hash + "\n")
    click.echo(f"Decrypted {len(plaintext)} bytes -> {output}")


@main.command()
@click.option("--config", "config_path", default=_DEFAULT_SENDER_CONFIG)
def destroy(config_path: str) -> None:
    config = load_sender_config(Path(config_path))
    delete_branch(config.repo, config.branch)
    click.echo(f"Deleted remote branch '{config.branch}'.")


@main.command("repo-send")
@click.option("--repo", type=click.Path(path_type=Path), default=Path("."), help="Path to the git repository.")
@click.option("--export-dir", type=click.Path(path_type=Path), default=None, help="Directory for the exported bundle.")
@click.option("--resync", is_flag=True, help="Send one squashed commit after a history rewrite.")
@click.option("--tag-pattern", default=TAG_PATTERN, help="Regex for version tags to include.")
@click.option("--no-lint", is_flag=True, help="Skip the black --check lint gate.")
@click.option("--transfer-command", default=TRANSFER_COMMAND, help="Command to hand the archive to.")
@click.option("--keep-export", is_flag=True, help="Leave the export directory after sending.")
@click.option("--no-transfer", is_flag=True, help="Build the bundle without sending or moving the marker.")
def repo_send_cmd(
    repo: Path,
    export_dir: Path | None,
    resync: bool,
    tag_pattern: str,
    no_lint: bool,
    transfer_command: str,
    keep_export: bool,
    no_transfer: bool,
) -> None:
    try:
        repo_send(
            repo=repo,
            export_dir=export_dir,
            resync=resync,
            tag_pattern=tag_pattern,
            no_lint=no_lint,
            transfer_command=transfer_command,
            keep_export=keep_export,
            no_transfer=no_transfer,
        )
    except Failure as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("repo-apply")
@click.argument("bundle", type=click.Path(path_type=Path))
@click.option("--repo", type=click.Path(path_type=Path), default=Path("."), help="Path to the receiving git repository.")
@click.option("--branch", default=DEFAULT_BRANCH, help="Branch to apply patches to.")
def repo_apply_cmd(bundle: Path, repo: Path, branch: str) -> None:
    try:
        repo_apply(bundle=bundle, repo=repo, branch=branch)
    except Failure as exc:
        raise click.ClickException(str(exc)) from exc
