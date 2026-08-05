# Changelog

## 0.4.0 - 2026-08-05

### Added

- `receive --source <url-or-path>` overrides the configured URL, for when the usual repository is unavailable
- `--config` on `repo-send` and `repo-apply`, matching `send` and `receive`

### Changed

- `repo-send` and `repo-apply` call `send`/`receive` in-process instead of shelling out; config and transport errors are now reported without a traceback
- `repo-apply` always receives its bundle over the transport, and takes the same `--source` override — a URL or a path to a copy of the encrypted payload

### Removed

- `repo-send --transfer-command`; the bundle always goes through `send`
- `repo-apply`'s BUNDLE argument, superseded by `--source`
- `receive --redownload` and the duplicate-download check; whether data should be applied is the receiving command's business, and `repo-apply` already refuses to apply a bundle twice

## 0.3.2 - 2026-08-04

### Changed

- Package version derived from git tags via hatch-vcs
- GitLab CI publish stage uses `uv build`/`uv publish`

### Added

- `.gitignore`

## 0.3.1 - 2026-08-04

### Added

- README with usage documentation
- GitLab CI publish stage to push Python package to GitLab registry on tagged releases

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
