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

`receive` normally reads the URL from the receiver config. If that repository is
temporarily unavailable, `--source` overrides it with any other URL or a local
file path:

```
transfer receive <output> --source https://mirror.example.com/data
transfer receive <output> --source /media/usb/data
```

### Repository sync (diode)

Export commits from one git repository and apply them to another, designed for transferring code across network boundaries where direct git access is not available.

```
transfer repo-send --repo <path>
transfer repo-apply --repo <path>
```

`repo-send` creates a tar bundle of new commits (since the last send) along with matching version tags, then encrypts and pushes it through the same path as `send`. `repo-apply` receives that bundle exactly as `receive` would, decrypts it, and applies the patches to a tracking branch in the receiving repository.

Because it goes through `receive`, the same override applies when the usual repository is unavailable. `--source` names another copy of the encrypted payload — the file the transport would have served — either at a URL or on disk:

```
transfer repo-apply --source https://mirror.example.com/data --repo <path>
transfer repo-apply --source /media/usb/data --repo <path>
```

Applying is guarded rather than idempotent: a full bundle is refused if the tracking branch already exists, and an incremental one is refused unless the branch sits exactly where the bundle expects. Receiving the same payload twice therefore fails loudly instead of applying it twice.

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
