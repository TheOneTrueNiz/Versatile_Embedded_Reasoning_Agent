# Offline Bootstrap

VERA supports offline dependency/bootstrap workflows via a local wheelhouse plus `.venv` seed fallback.

## 1) Prepare Assets While Online (Optional)

```bash
./scripts/build_wheelhouse.sh
```

This script attempts to download wheels for `requirements.txt` and writes:
- `WHEELHOUSE_STAMP.txt`
- `venv_seed.tar.gz` (snapshot of current `.venv`, when available)

Recommended external location: `/mnt/storage/vera_wheelhouse` (or another durable mounted path).

`venv_seed.tar.gz` is machine/Python specific and intended as last-resort fallback.

## 2) Bootstrap Offline

```bash
export VERA_WHEELHOUSE_DIR=/mnt/storage/vera_wheelhouse
VERA_NO_RUN=1 ./scripts/run_vera.sh
```

`scripts/run_vera.sh` behavior:

1. Calculates hash of `requirements.txt`.
2. Decides whether core deps must be installed (`.venv/.deps_core` + `.venv/.deps_core_sha256`).
3. If install is required:
   - If wheelhouse has at least one `*.whl`, install from local wheels in no-index mode.
   - If no usable wheels but `venv_seed.tar.gz` exists, restore `.venv` from seed.
   - If wheel install fails and seed exists, restore `.venv` from seed.
   - Otherwise, falls back to online pip install path.

## 3) Safe Seed Restore Semantics

Seed restore in `run_vera.sh` is rollback-safe:
- Existing `.venv` is first renamed to `.venv__pre_seed_<timestamp>`.
- Seed archive is extracted.
- If extraction fails, original `.venv` is restored automatically.

Backup retention after successful restore:
- `VERA_PRESEED_BACKUPS_TO_KEEP` (default: `1`)
- `VERA_KEEP_ALL_PRESEED_BACKUPS=1` disables pruning
- The backup created in the current restore run is always preserved for that run.

## 4) Practical Notes

- If `requirements.txt` changes, core dependency install is re-triggered automatically via hash mismatch.
- If wheelhouse is seed-only (no `*.whl`), bootstrap can still succeed via `.venv` seed restore.
- Keep `VERA_WHEELHOUSE_DIR` on durable storage if you want repeatable offline bring-up.
