# RCT Slice 1 — Live runtime sign-off bundle (frozen)

This entry records the **versioned, checksum-pinned** closure artifact for Restricted Custody Transfer Slice 1 (2026-03-30 live matrix), as referenced in the Post-Closure Queue in `docs/development/current_next_steps.md`.

## Canonical location in this repository

| Item | Path |
| :--- | :--- |
| Frozen tree | `tests/fixtures/demo/rct_signoff_v1/` |
| Per-file manifest | `tests/fixtures/demo/rct_signoff_v1/manifest.json` |
| Sign-off report | `docs/development/restricted_custody_transfer_demo_signoff_report.md` |

**`bundle_version`:** `1.0.0` (see `manifest.json`)  
**Source capture id:** `20260330T061828Z` (original host path was `.local-runtime/rct_live_signoff/20260330T061828Z`, gitignored)

## Runtime audit identifiers (closure table)

| Case | `audit_id` |
| :--- | :--- |
| `allow_case` | `ba05655c-9351-4783-97f1-fc6774c4f38b` |
| `deny_missing_approval` | `a65bbee7-023a-44fa-9e9d-75e0164102e4` |
| `quarantine_stale_telemetry` | `21dcb295-644a-465b-a505-064e6908c99c` |
| `escalate_break_glass` | `28ac9873-3e8f-430f-9681-224fdad44286` |

## Verify the frozen bundle (machine check)

From the repo root (checks every artifact file against `manifest.json`):

```bash
python scripts/tools/verify_rct_signoff_bundle.py
```

**Pinned manifest digest:** see `MANIFEST.sha256` (path `rct_signoff_v1/manifest.json` is relative to the tarball extract root). After extracting the tarball into an empty directory, copy `MANIFEST.sha256` beside `rct_signoff_v1/` and run `shasum -a 256 -c MANIFEST.sha256`.

**Verify the release tarball file** (from this directory):

```bash
shasum -a 256 -c SHA256SUMS
```

## Build a distribution tarball (optional)

To regenerate the tarball and `SHA256SUMS` (for example before uploading a new GitHub Release asset):

```bash
bash scripts/tools/package_frozen_signoff_tarball.sh
```

If you change any file under `tests/fixtures/demo/rct_signoff_v1/`, bump `bundle_version` in `manifest.json`, re-run verification, then rebuild the tarball and update `MANIFEST.sha256` accordingly.

## Refreshing from a new host capture

When you capture a **new** matrix under `.local-runtime/rct_live_signoff/<stamp>Z`, use:

```bash
bash scripts/tools/package_signoff_bundle.sh
```

That overwrites `tests/fixtures/demo/rct_signoff_v1/` and regenerates `manifest.json`. A new freeze should bump `bundle_version`, update this README, and record a new `MANIFEST.sha256`.
