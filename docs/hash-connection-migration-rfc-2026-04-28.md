# RFC — `vector_db._hash_connection` URL normalization migration

**Status**: DRAFT (pre-implementation review)
**Date**: 2026-04-28
**Wave bucket**: 2D (deferred from Wave 2)
**Related risks**: R3, R10 (from `docs/wave-2-mitigation-plan-2026-04-28.md` line item review)

---

## Problem

`vector_db._hash_connection(connection_url)` at `backend/app/services/vector_db.py:170-175` produces the connection-scoped key under which schema, business terms, query patterns, and column descriptions are stored. The current implementation:

```python
def _hash_connection(self, connection_url: str) -> str:
    """Create stable hash for connection URL (excluding credentials)"""
    sanitized = (
        connection_url.split("@")[-1] if "@" in connection_url else connection_url
    )
    return hashlib.sha256(sanitized.encode()).hexdigest()[:16]
```

Strips credentials (correctly — `user:pass@host` → `host`). **Does not normalize**:

1. **Scheme**: `postgresql://` and `postgres://` are equivalent for psycopg but produce different hashes.
2. **SQLAlchemy driver suffix**: `postgresql+asyncpg://` vs `postgresql://` produce different hashes.
3. **Query parameters**: `?sslmode=require` vs `?sslmode=disable` vs no query string produce three different hashes for the same logical database.
4. **Trailing slashes**: `host/db` vs `host/db/` produce different hashes.

**Symptom in the wild**: a user enters `postgresql://...?sslmode=require`, sets up Context Studio with column descriptions, then later reconnects with `postgresql://...?sslmode=disable`. Their dictionary disappears silently — not deleted, just unreachable behind a different hash.

**Discovered**: Wave 1 multi-agent review (`docs/analyst-mode-deep-audit-2026-04-22.md`).

**Why this is a Wave 2D blocker, not a Wave 1/2 fix**: every existing `ColumnDescription`, `BusinessTerm`, and indexed schema row in production is keyed to the current (unnormalized) hash. Changing the function naively orphans all of that data. We need a migration plan, not just a code fix.

---

## Goals

1. Lookups succeed regardless of cosmetic URL variation (sslmode, scheme alias, trailing slash, driver suffix).
2. Existing data is not lost during the transition.
3. Rollback is feasible if the migration introduces a regression.
4. No degradation of read latency on the happy path.

## Non-goals

- Reworking the underlying `ColumnDescription` schema — purely the hash function.
- Cross-connection deduplication (different `host/db` pairs intentionally produce different hashes; that stays).
- Hashing performance beyond "still cheap" — we don't need to switch from sha256.

---

## Options

### Option A — One-shot rehash + downtime window

**Approach**: ship the new normalized hash; ship a one-shot SQL migration script that rewrites every existing `ColumnDescription.connection_hash`, `BusinessTerm.connection_hash`, and vector-DB key to the new value; deploy with a brief read-write freeze to prevent in-flight writes from missing the migration.

**Pros**: simplest end-state; no transition code carries forward.

**Cons**:
- Requires a maintenance window (ColumnDescription has indexed `connection_hash` columns; SQL migration needs `ALTER TABLE`-equivalent DDL plus row updates plus reindex).
- Vector DB (ChromaDB / Qdrant) rewrite is not transactional with the SQL rewrite — risk of partial migration if either side fails.
- Operator can't roll back without restoring from backup.

**Effort**: M (script + window planning).

### Option B — Dual-lookup transition (recommended)

**Approach**:
1. Add a new `_hash_connection_normalized(url)` that strips credentials, normalizes scheme aliases, drops query strings, and trims trailing slashes.
2. New writes use only the normalized hash.
3. Reads compute BOTH hashes and look up under the normalized hash first; on miss, fall back to the legacy hash. If the fallback hits, opportunistically rewrite that row's `connection_hash` to the normalized value (single-row update) so subsequent reads hit the fast path.
4. Add a metric counter for "fallback hits" so we can see when the legacy data has been migrated.
5. After a release window with metric showing zero fallback hits, drop the legacy fallback in a follow-up PR.

**Pros**:
- Zero downtime.
- Self-migrating — no operator action.
- Trivial rollback (revert PR; both hashes still work for reads written before the rollback).

**Cons**:
- Two hashes computed per read for the transition window — small overhead (~microseconds), but real.
- "Zero fallback hits" criterion needs a clear horizon (e.g., 30 days production traffic) before we can prune the legacy code.
- Code carries the transition state for that window.

**Effort**: M-L (write the new hash function + dual-lookup wrapper + opportunistic rewrite + metric + cleanup PR).

### Option C — Canonicalize input URL, keep hash function

**Approach**: don't change the hash function at all; normalize the URL **before** it reaches `_hash_connection`. Wrap the function with a `_canonicalize_url_for_hash(url)` step that applies the same normalizations.

**Pros**: smallest code change.

**Cons**:
- Identical migration cost to Option A — existing data still keyed to the old hash because it was computed pre-canonicalization.
- "Canonicalization" can have edge cases (e.g., when does `?sslmode=require` actually change the data we care about?). The hash function staying the same doesn't help if the inputs change.

**Effort**: S, but only for the new-data path. Migration is still required for old data.

**Not recommended.**

---

## Recommended path: Option B

Specifically:

```python
def _hash_connection_normalized(self, connection_url: str) -> str:
    """
    Normalize the connection URL to a canonical form before hashing,
    so cosmetic variation (sslmode, scheme alias, trailing slash) all
    map to the same hash for the same logical database.
    """
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(connection_url)
    # 1. Normalize scheme aliases.
    scheme = parsed.scheme.split("+")[0]  # postgresql+asyncpg → postgresql
    if scheme == "postgres":
        scheme = "postgresql"
    if scheme == "mysql+pymysql":
        scheme = "mysql"
    # 2. Strip credentials (already done in _hash_connection).
    netloc = parsed.netloc.split("@")[-1] if "@" in parsed.netloc else parsed.netloc
    # 3. Trim trailing slashes from path.
    path = parsed.path.rstrip("/")
    # 4. Drop query string entirely.
    canonical = urlunparse((scheme, netloc, path, "", "", ""))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

```python
# In every consumer of _hash_connection:
def lookup_with_legacy_fallback(self, connection_url, query):
    new_hash = self._hash_connection_normalized(connection_url)
    result = primary_lookup(new_hash, query)
    if result is not None:
        return result
    legacy_hash = self._hash_connection(connection_url)
    if legacy_hash != new_hash:
        result = primary_lookup(legacy_hash, query)
        if result is not None:
            # Opportunistic single-row migration.
            opportunistic_rehash(legacy_hash, new_hash, row_id)
            metrics.increment("vector_db.legacy_hash_fallback_hit")
            return result
    return None
```

---

## Decision criteria

Before implementing:

1. **Production data volume** — how many `ColumnDescription` + `BusinessTerm` rows exist? If small (<10K), Option A's downtime cost may be acceptable. Pull a count from prod or a staging snapshot.
2. **Maintenance window tolerance** — what's the expected DAU during the chosen migration window? If we can hit a quiet hour (early morning UTC for US workloads), Option A becomes more palatable.
3. **Observed incidence rate** — how often does the bug actually fire? Add a debug log when `connection_url` differs only in cosmetic ways across two sequential lookups; collect for one week before deciding.

If incidence is low (<1% of users, no compliance-driven urgency), defer further. If high (>5% of new users hit the dictionary-disappear case), escalate priority.

---

## Open questions for stakeholder review

1. Is there ever a legitimate case where two URLs that differ only in `sslmode` should produce *different* dictionary entries? (Theoretically: a "secured" vs "unsecured" view of the same database with different access controls. But that would be a Postgres permissions thing, not a URL difference. Likely no.)
2. Should we extend the normalization to handle case-insensitivity of host/database name? Postgres treats `MyHost` and `myhost` as the same; MySQL is case-sensitive on path.
3. The opportunistic rehash on fallback-hit modifies rows on read paths. Acceptable, or do we prefer a background job that walks the table?

---

## Implementation plan (when this RFC is approved)

1. **Phase 1** — observe (1 week, no code changes):
   - Add a debug log in `_hash_connection` that captures the URL shape (scheme, has-query-string, trailing-slash) per call.
   - Aggregate logs to estimate fallback-rate if we shipped Option B today.
   - Make the go/no-go call.

2. **Phase 2** — implement Option B:
   - New `_hash_connection_normalized` function + tests (unit-test 8+ shape-variation cases).
   - Update every consumer of `_hash_connection` to use the dual-lookup wrapper (~5 sites; need to grep).
   - Add `vector_db.legacy_hash_fallback_hit` counter to `LLMMetricsTracker` or equivalent.
   - Smoke test in dev: insert a row keyed to legacy hash; query via normalized hash; assert opportunistic rewrite happened.
   - Ship behind feature flag `ENABLE_NORMALIZED_HASH=False` for canary.

3. **Phase 3** — flip flag to True for 100% traffic. Monitor `legacy_hash_fallback_hit` for 30 days.

4. **Phase 4** — when counter reads zero for 7 consecutive days: drop the legacy fallback in a follow-up PR. Done.

---

## Effort estimate

- Phase 1: S (1 day, observation only).
- Phase 2: M (3-4 days, implementation + tests + canary).
- Phase 3: 30 days elapsed, near-zero engineering time.
- Phase 4: S (cleanup PR).

Total: ~1 month elapsed, ~5 days engineering time.

---

## Status checklist

- [ ] RFC reviewed
- [ ] Decision made: A / B / C
- [ ] If B: Phase 1 (observation) started
- [ ] Phase 1 → Phase 2 transition criteria met
- [ ] Phase 2 implemented and merged behind flag
- [ ] Flag flipped to 100%
- [ ] 30-day clean window validated
- [ ] Phase 4 cleanup merged

When the last box is checked: archive this RFC under `docs/archive/`.
