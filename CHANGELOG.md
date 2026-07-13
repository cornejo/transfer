# Changelog

## 0.2.0 - 2026-07-13

### Added

- Duplicate download detection: `receive` tracks SHA-256 hash of downloaded data and errors if unchanged since last download
- `--redownload` flag on `receive` to explicitly re-download unchanged data
- Default config location at `~/.config/transfer/`
- Auto-create config directory on `init-receiver` and `init-sender`

### Fixed

- Base64-encode encrypted data in git transport to prevent `autocrlf` corruption

## 0.1.0 - 2026-06-04

### Added

- CLI with `init-receiver`, `init-sender`, `send`, `receive`, `destroy` commands
- Hybrid encryption: X25519 ECDH + HKDF-SHA256 + ChaCha20-Poly1305
- Git transport: push encrypted files without cloning (temp repo + force push)
- Receiver downloads via raw GitHub URL and decrypts locally
- TOML-based sender/receiver config files
- Pyright strict type checking
