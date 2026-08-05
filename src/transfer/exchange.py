"""What `send` and `receive` do, with no CLI attached.

The repository commands transfer bundles the same way single files travel, so
they call in here rather than reimplementing -- or reinvoking -- the pair.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import NamedTuple

from transfer.config import (
    CONFIG_DIR,
    ReceiverConfig,
    SenderConfig,
    load_receiver_config,
    load_sender_config,
)
from transfer.crypto import decode_key, decrypt, encrypt
from transfer.git import Failure
from transfer.transport import download_data, push_data

DEFAULT_SENDER_CONFIG = CONFIG_DIR / "sender.toml"
DEFAULT_RECEIVER_CONFIG = CONFIG_DIR / "receiver.toml"

_CONFIG_ERRORS = (OSError, TypeError, tomllib.TOMLDecodeError)


class Payload(NamedTuple):
    encrypted: bytes
    plaintext: bytes


def _missing(path: Path, side: str) -> Failure:
    return Failure(f"no {side} config at {path}; run 'transfer init-{side}' first")


def _unusable(path: Path, side: str, exc: Exception) -> Failure:
    return Failure(f"{path} is not a usable {side} config: {exc}")


def sender_config(path: Path = DEFAULT_SENDER_CONFIG) -> SenderConfig:
    """Load the sender config, reporting its problems as Failure."""
    try:
        return load_sender_config(path)
    except FileNotFoundError as exc:
        raise _missing(path, "sender") from exc
    except _CONFIG_ERRORS as exc:
        raise _unusable(path, "sender", exc) from exc


def receiver_config(path: Path = DEFAULT_RECEIVER_CONFIG) -> ReceiverConfig:
    """Load the receiver config, reporting its problems as Failure."""
    try:
        return load_receiver_config(path)
    except FileNotFoundError as exc:
        raise _missing(path, "receiver") from exc
    except _CONFIG_ERRORS as exc:
        raise _unusable(path, "receiver", exc) from exc


def send_payload(plaintext: bytes, config_path: Path = DEFAULT_SENDER_CONFIG) -> Payload:
    """Encrypt for the configured recipient and push to the configured branch."""
    config = sender_config(config_path)
    encrypted = encrypt(plaintext, decode_key(config.public_key))
    try:
        push_data(encrypted, config.repo, config.branch)
    except subprocess.CalledProcessError as exc:
        raise Failure(f"pushing to {config.repo} failed (exit {exc.returncode})") from exc
    return Payload(encrypted, plaintext)


def receive_payload(
    config_path: Path = DEFAULT_RECEIVER_CONFIG, source: str | None = None
) -> Payload:
    """Read the encrypted data -- from `source` if given, else the configured URL.

    Deliberately dumb: it fetches and decrypts, and leaves every judgement about
    whether this data should be used to the caller.
    """
    config = receiver_config(config_path)
    location = source or config.url
    try:
        encrypted = download_data(location)
    except OSError as exc:
        raise Failure(f"could not read {location}: {exc}") from exc
    return Payload(encrypted, decrypt(encrypted, decode_key(config.private_key)))
