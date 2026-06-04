# Changelog

## 0.1.0 - 2026-06-04

### Added

- CLI with `init-receiver`, `init-sender`, `send`, `receive`, `destroy` commands
- Hybrid encryption: X25519 ECDH + HKDF-SHA256 + ChaCha20-Poly1305
- Git transport: push encrypted files without cloning (temp repo + force push)
- Receiver downloads via raw GitHub URL and decrypts locally
- TOML-based sender/receiver config files
- Pyright strict type checking
