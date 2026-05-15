# Vitality Decay Baseline

**Measured at**: 2026-05-15
**Scope**: documents the existing behaviour of `SQLiteClient.apply_vitality_decay`,
`SQLiteClient.get_vitality_cleanup_candidates`, `SQLiteClient.get_vitality_stats`,
and the `/maintenance/vitality/*` review-token flow as currently implemented.
Nothing here is aspirational; the formulas, defaults, and field names below all
exist in source and can be cited verbatim.

## 1. Decay formula

Source: `backend/db/sqlite_client.py::SQLiteClient.apply_vitality_decay`
(lines 3990-4071).

For each non-deprecated memory:

1. Reference timestamp:
   `reference_dt = last_accessed_at or created_at or now`
2. Age in days:
   `age_days = max(0, (now - reference_dt).total_seconds() / 86400)`
3. Access-driven resistance (raises the effective half-life for frequently
   accessed memories):
   `resistance = 1 + min(2.0, log1p(access_count) * 0.35)`
4. Effective age:
   `effective_age_days = age_days / resistance`
5. Decay ratio (exponential — note the constant is named
   `half_life_days` historically but is used as a plain time constant
   `tau`, so at `effective_age_days == half_life_days` the ratio is `1/e
   (~0.368)`, NOT `0.5`):
   `decay_ratio = exp(-effective_age_days / half_life_days)`
6. Next score (floor-bounded):
   `next_score = max(min_score, current_score * decay_ratio)`
7. Persist only if `next_score < current_score - 1e-9`. A row is counted as
   "low-vitality" when `next_score <= cleanup_threshold`.

Daily idempotency is enforced via the `IndexMeta` key
`"vitality.last_decay_day.v1"`: if it equals the current UTC day key
(`YYYY-MM-DD`) and `force=False`, the method returns
`{"applied": False, "reason": "already_applied_today", ...}` without scanning.

### Decay return contract

```text
{
  "applied": bool,
  "day": "YYYY-MM-DD",
  "checked_memories": int,
  "updated_memories": int,
  "low_vitality_count": int,
  "half_life_days": float,
  "threshold": float
}
```

When skipped, the payload is `{"applied": False, "reason": "already_applied_today", "day": ..., "last_decay_day": ...}`.

## 2. Default parameters and environment variables

Source: `SQLiteClient.__init__` lines 660-675.

| Field                                  | Env var                          | Default | Effect                                                          |
| -------------------------------------- | -------------------------------- | ------- | --------------------------------------------------------------- |
| `_vitality_reinforce_delta`            | `VITALITY_REINFORCE_DELTA`       | `0.08`  | Per-access boost applied via `_reinforce_memory_access`.        |
| `_vitality_decay_half_life_days`       | `VITALITY_DECAY_HALF_LIFE_DAYS`  | `30.0`  | Half-life (days) for the exponential decay, min 1.0.            |
| `_vitality_decay_min_score`            | `VITALITY_DECAY_MIN_SCORE`       | `0.05`  | Lower floor for vitality score after decay.                     |
| `_vitality_cleanup_threshold`          | `VITALITY_CLEANUP_THRESHOLD`     | `0.35`  | Score `<=` this is eligible to surface as a cleanup candidate.  |
| `_vitality_cleanup_inactive_days`      | `VITALITY_CLEANUP_INACTIVE_DAYS` | `14.0`  | Memory must also have been inactive for at least this many days.|

The `VitalityDecayCoordinator` (in `backend/runtime_state.py` lines 1493-1560)
adds one further knob:

| Field                              | Env var                                              | Default | Effect                                                                   |
| ---------------------------------- | ---------------------------------------------------- | ------- | ------------------------------------------------------------------------ |
| `_check_interval_seconds`          | `RUNTIME_VITALITY_DECAY_CHECK_INTERVAL_SECONDS`      | `600`   | Minimum gap between runtime decay attempts (single-flight wrapper).      |

The `CleanupReviewCoordinator` adds the review-token TTL knobs:

| Field                  | Env var                                | Default | Effect                                       |
| ---------------------- | -------------------------------------- | ------- | -------------------------------------------- |
| `_default_ttl_seconds` | `RUNTIME_CLEANUP_REVIEW_TTL_SECONDS`   | `900`   | Default TTL for a pending cleanup review.    |
| `_max_pending`         | `RUNTIME_CLEANUP_REVIEW_MAX_PENDING`   | `64`    | Cap on concurrently pending reviews.         |

## 3. Cleanup-candidate query

`SQLiteClient.get_vitality_cleanup_candidates` (lines 4073-4347) selects
non-deprecated memories where:

- `vitality_score <= threshold`, and
- `inactive_cutoff = now - inactive_days`, with
  `last_accessed_at <= inactive_cutoff` OR
  (`last_accessed_at IS NULL` AND `created_at <= inactive_cutoff`).

Optional filters: `memory_ids`, `domain`, `path_prefix`. Results are ordered by
`(vitality_score ASC, COALESCE(last_accessed_at, created_at) ASC, id ASC)` and
capped at `limit` (1..500, default 50). Each item carries a `state_hash`
computed by `_build_vitality_state_hash` (lines 1984-1999):

```text
sha256("{memory_id}|{round(vitality_score, 6)}|{access_count}|{path_count}|{deprecated}")
```

The hash deliberately excludes wall-clock fields (e.g. `inactive_days`) so it
stays stable across the prepare/confirm round trip.

### Cleanup-candidate return contract

```text
{
  "items": [
    {
      "memory_id": int,
      "uri": "domain://path",
      "vitality_score": float,
      "access_count": int,
      "inactive_days": float,
      "state_hash": "<64-char hex>",
      "can_delete": bool,
      "reason_codes": [str, ...]
    },
    ...
  ],
  "summary": {
    "total_candidates": int,
    "threshold": float,
    "inactive_days": float,
    "query_profile": {
      "query_ms": float,
      "full_scan": bool,
      "degraded": bool,
      "index_usage": { "memory_cleanup_index": bool, "path_scope_index": bool }
    }
  }
}
```

## 4. Aggregate stats

`SQLiteClient.get_vitality_stats` (lines 4349-4409) returns a snapshot used by
the maintenance dashboard:

```text
{
  "total_memories": int,
  "avg_score": float,
  "min_score": float,
  "max_score": float,
  "low_vitality_count": int,    # vitality_score <= cleanup_threshold
  "threshold": float            # echoes _vitality_cleanup_threshold
}
```

All score fields are rounded to 6 decimals. `total_memories` and
`low_vitality_count` only count rows where `deprecated == False`.

## 5. Review-token + state-hash + write-lane confirmation flow

End-to-end this is a two-step prepare/confirm pattern documented in
`backend/api/maintenance.py`.

### Step A: list candidates (`POST /maintenance/vitality/candidates/query`)

Implementation: `query_vitality_cleanup_candidates` (lines 3808-3860).

Request body (`VitalityCleanupQueryRequest`, lines 224-229):

| Field           | Type    | Default | Notes                              |
| --------------- | ------- | ------- | ---------------------------------- |
| `threshold`     | float   | `0.35`  | `>= 0`.                            |
| `inactive_days` | float   | `14.0`  | `>= 0`.                            |
| `limit`         | int     | `50`    | `[1, 500]`.                        |
| `domain`        | str?    | `None`  | Optional scope.                    |
| `path_prefix`   | str?    | `None`  | Optional scope.                    |

The handler also opportunistically calls `runtime_state.vitality_decay.run_decay(force=False, reason="maintenance.vitality_candidates")` so the candidate list reflects a fresh decay pass.

### Step B: prepare review (`POST /maintenance/vitality/cleanup/prepare`)

Implementation: `prepare_vitality_cleanup` (lines 3863-3941).

Request body (`VitalityCleanupPrepareRequest`, lines 237-241):

```text
{
  "action": "delete" | "keep",      # default "delete"
  "selections": [
    { "memory_id": int >= 1, "state_hash": str (16..128 chars) }, ...
  ],                                # 1..100 items
  "reviewer": str?,
  "ttl_seconds": int                # 60..3600, default 900
}
```

The handler re-queries each selected memory_id with
`threshold=9999.0, inactive_days=0.0` and compares the freshly computed
`state_hash` against the caller-supplied one. Any drift returns HTTP 409
`{"error": "cleanup_candidates_changed", "missing_ids": [...], "stale_ids": [...]}`.
On match it creates a review record via
`runtime_state.cleanup_reviews.create_review`, returning:

```text
{
  "ok": True,
  "status": "pending_confirmation",
  "action": "delete" | "keep",
  "selected_count": int,
  "review": {
    "review_id": "cleanup-XXXXXXXXXX",
    "token": "<32-char hex>",
    "confirmation_phrase": "CONFIRM DELETE 3",
    "expires_at": <epoch seconds>
  },
  "preview": [ ...prepared selections... ]
}
```

`confirmation_phrase` is always `f"CONFIRM {ACTION.upper()} {len(selections)}"`.

### Step C: confirm and apply (`POST /maintenance/vitality/cleanup/confirm`)

Implementation: `confirm_vitality_cleanup` (lines 3944-4125).

Request body (`VitalityCleanupConfirmRequest`, lines 244-247):

```text
{
  "review_id": str (>= 8 chars),
  "token": str (>= 16 chars),
  "confirmation_phrase": str (>= 8 chars)
}
```

`runtime_state.cleanup_reviews.consume_review` validates id + token + phrase
and atomically removes the review record. If consumption fails it returns
HTTP 409 with the error reason. If consumption succeeds, the handler re-runs
`get_vitality_cleanup_candidates(memory_ids=...)` once more and compares each
item's `state_hash` to the value captured at prepare time
(`expected_hash_by_id`). Any mismatch aborts before write. Only after the
state hashes still match does the handler dispatch to the write lane:

- `action == "delete"`: calls `client.deprecate_memory(memory_id, expected_state_hash=...)`.
- `action == "keep"`: calls `client.bump_vitality_for_keep(memory_id, expected_state_hash=...)`.

Both write helpers take `expected_state_hash` so the write itself is also
hash-gated, providing the last line of defence against concurrent edits.

### Decay trigger endpoint

`POST /maintenance/vitality/decay` (lines 3792-3805) is a thin wrapper around
`runtime_state.vitality_decay.run_decay(force=bool, reason=str)`. The
coordinator serialises concurrent calls via an `asyncio.Lock` so only one
decay task can be in flight per process.

## 6. Tests of record

Existing coverage that this baseline must remain compatible with:

- `backend/tests/test_week6_vitality_cleanup.py` — daily idempotency, state
  hash stability, candidate ordering, domain/path-prefix filtering,
  prepare/confirm hash mismatch handling.

The new baseline test (`vitality_decay_baseline.py`) seeds memories with
known scores/ages, calls `apply_vitality_decay(force=True)`, and verifies
the per-row decay matches the formula above to within 1e-6. It also writes
the parameter snapshot into `vitality_decay_baseline.json` for future
comparison.
