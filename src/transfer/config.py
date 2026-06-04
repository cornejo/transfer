from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SenderConfig:
    public_key: str
    repo: str
    branch: str


@dataclass(frozen=True)
class ReceiverConfig:
    private_key: str
    url: str


def _require_str(data: dict[str, object], key: str) -> str:
    val = data.get(key)
    if not isinstance(val, str):
        msg = f"config field '{key}' must be a string"
        raise TypeError(msg)
    return val


def load_sender_config(path: Path) -> SenderConfig:
    with open(path, "rb") as f:
        data: dict[str, object] = tomllib.load(f)
    return SenderConfig(
        public_key=_require_str(data, "public_key"),
        repo=_require_str(data, "repo"),
        branch=_require_str(data, "branch"),
    )


def load_receiver_config(path: Path) -> ReceiverConfig:
    with open(path, "rb") as f:
        data: dict[str, object] = tomllib.load(f)
    return ReceiverConfig(
        private_key=_require_str(data, "private_key"),
        url=_require_str(data, "url"),
    )


def save_sender_config(config: SenderConfig, path: Path) -> None:
    lines = [
        f'public_key = "{config.public_key}"',
        f'repo = "{config.repo}"',
        f'branch = "{config.branch}"',
        "",
    ]
    path.write_text("\n".join(lines))


def save_receiver_config(config: ReceiverConfig, path: Path) -> None:
    lines = [
        f'private_key = "{config.private_key}"',
        f'url = "{config.url}"',
        "",
    ]
    path.write_text("\n".join(lines))
