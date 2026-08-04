# transfer

A CLI tool for encrypted file transfer over git and for syncing repositories across network boundaries.

## Features

### Encrypted file transfer

Send and receive files encrypted with X25519 ECDH + HKDF-SHA256 + ChaCha20-Poly1305, using a git repository as the transport layer. The sender pushes encrypted data to a branch; the receiver downloads and decrypts it via a raw URL.

```
transfer init-receiver --url <raw-url>
transfer init-sender --public-key <key> --repo <ssh-url> --branch <branch>
transfer send <file>
transfer receive <output>
transfer destroy
```

### Repository sync (diode)

Export commits from one git repository and apply them to another, designed for transferring code across network boundaries where direct git access is not available.

```
transfer repo-send --repo <path>
transfer repo-apply <bundle> --repo <path>
```

`repo-send` creates a tar bundle of new commits (since the last send) along with matching version tags, then hands it off via `transfer send`. `repo-apply` unpacks the bundle and applies the patches to a tracking branch in the receiving repository.

## Installation

Requires Python 3.12+.

```
pip install transfer
```

Or with uv:

```
uv pip install transfer
```

## Configuration

Config files are stored in `~/.config/transfer/` by default. Running `init-receiver` or `init-sender` creates the config file and generates keys as needed.

## Development

```
uv sync --group dev
uv run pytest
uv run pyright
```
