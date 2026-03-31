# Owner Context Hash Contract

This contract defines how `owner_context_hash` is computed across SeedCore surfaces
(`trust/*`, `verify`, replay projections, and `seedcore.owner_context.get`).

## Input

- Input object: `owner_context_ref` (or `owner_context`) map.
- Expected top-level keys:
  - `owner_id`
  - `creator_profile_ref`
  - `trust_preferences_ref`

## Canonicalization

1. Serialize the input map with deterministic JSON:
   - sorted keys
   - separators `(",", ":")`
   - default string conversion for non-JSON-native values
2. Compute SHA-256 over UTF-8 bytes of the canonical JSON.
3. Prefix hex digest with `sha256:`.

Formula:

`owner_context_hash = "sha256:" + sha256_hex(canonical_json(owner_context_ref))`

## Shared Implementation

- Runtime helper: [owner_context.py](/Users/ningli/project/seedcore/src/seedcore/ops/evidence/owner_context.py)
- Golden vectors: [golden.json](/Users/ningli/project/seedcore/tests/fixtures/owner_context_hash/golden.json)
- Contract test: [test_owner_context_hash_contract.py](/Users/ningli/project/seedcore/tests/test_owner_context_hash_contract.py)

## Compatibility

- The hash is additive metadata and does not replace existing authority/trust checks.
- New fields added to `owner_context_ref` change the hash by design.
