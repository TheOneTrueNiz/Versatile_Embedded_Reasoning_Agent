# VERA Secret Handling

## Goal

Keep secrets out of repo files while preserving simple startup UX.

## Recommended Dev Flow

1. Store/update secrets in OS keychain:

```bash
./scripts/vera_secret_store.sh set XAI_API_KEY "<your_key>"
```

2. Optional migration from a legacy file-based credentials directory:

```bash
./scripts/vera_secret_store.sh migrate-creds "/path/to/legacy-creds"
```

3. Check secret presence (values are never printed):

```bash
./scripts/vera_secret_store.sh status
```

## Runtime Behavior

- `scripts/run_vera.sh` and `scripts/run_vera_full.sh` auto-load keychain secrets by default.
- Python entrypoints also prime env from keychain:
  - `run_vera.py`
  - `run_vera_api.py`
  - `run_vera_monolithic.py`
- Compatibility fallback to the legacy `CREDS_DIR` location is still present.

Disable keychain autoload:

```bash
VERA_KEYCHAIN_LOAD=0 ./scripts/run_vera.sh
```

## Backends

- Linux: `secret-tool` (libsecret)
- macOS: `security`

Backend/service controls:

- `VERA_KEYCHAIN_BACKEND=auto|secret-tool|security|none`
- `VERA_KEYCHAIN_SERVICE=vera.dev` (default)

## Production Guidance

- Inject secrets via environment variables or a secret manager.
- Do not commit runtime secrets.
- Keep browser UI key handling disabled where backend proxy routes are available.
