# Data Models — Architectural Invariants

## What Invariant Does This Protect?

Every record in the system has a stable identity, a traceable history, and a version that can be used to detect concurrent modification. Data is never silently lost, silently overwritten, or ambiguously duplicated.

**The fundamental constraint:** Every mutation is **versioned, tracked, and auditable**. The server is the authority; clients propose changes based on a known version.

## What Assumptions Must Never Change?

- `Inspection.version` is the basis for all optimistic locking. It must be checked on every write and incremented on every successful write.
- `SyncOperation.idempotency_key` must be unique across all users and all time. It is the sole mechanism preventing duplicate processing of retried requests.
- Inspections are never hard-deleted. The soft delete flag is enforced at the query manager level, not at the call site.

## What Breaks if This Is Modified Incorrectly?

- Removing the version check allows concurrent writes to silently clobber each other.
- Making idempotency keys non-unique allows a network retry to create a duplicate inspection.
- Introducing hard deletes breaks audit trails and causes dangling references in `ConflictRecord`.

## Versioning Strategy

`Inspection` uses integer optimistic locking. The `version` field which is the sole concurrency control mechanism starts at 1 on record creation. Every successful update increments it by exactly 1 using Django's `F()` expression to avoid race conditions at the application layer:

```python
self.version = models.F("version") + 1
self.save(update_fields=["version"])
self.refresh_from_db()
```

`refresh_from_db()` is called immediately after save to return the resolved integer to the caller. Code that reads `inspection.version` after an update will always see the confirmed server value, not a stale in-memory copy.

Every client update request must include the last known `version`. If the submitted version does not match the server's current version, the write is rejected with `409 Conflict`. This is enforced in `InspectionService.update_inspection()` before any field mutations occur.

## Unique Constraints

`SyncOperation.idempotency_key` has a `UNIQUE` database constraint and a `db_index=True` declaration. Attempting to insert a duplicate key raises an `IntegrityError` at the database level. The service layer catches this and returns the cached `result` JSON from the existing record — the same response the client would have received on the original request.

This means the idempotency guarantee is enforced by the database, not by application-level logic. It holds even under concurrent requests.

`Inspection.id` is a UUID primary key, generated server-side on creation. UUIDs eliminate the risk of ID collisions when multiple clients create records offline and sync simultaneously.

## Idempotency Table

The `SyncOperation` model (`db_table = "sync_operations"`) stores one record per processed operation:

| Field             | Purpose                                               |
|-------------------|-------------------------------------------------------|
| `idempotency_key` | Client-generated UUID. Unique. Indexed.               |
| `operation_type`  | `CREATE_INSPECTION`, `UPDATE_INSPECTION`, etc.        |
| `entity_id`       | UUID of the affected `Inspection`.                    |
| `user`            | FK to the user who submitted the operation.           |
| `processed_at`    | Timestamp of first processing. Auto-set.              |
| `result`          | Cached JSON response. Returned verbatim on replay.    |

Records in this table are permanent for the lifetime of the operation's relevance. They are not cleaned up automatically. They exist to answer the question: "Has this operation been processed before, and if so, what did we return?"

Indexed on: `idempotency_key` (lookup), `entity_id` (entity history), `(user, processed_at)` (user-scoped queries), `(operation_type, processed_at)` (operational analytics).

## Conflict Metadata Fields

The `ConflictRecord` model (`db_table = "conflict_records"`) captures a point-in-time snapshot of both versions at the moment of conflict:

| Field                     | Purpose                                                   |
|---------------------------|-----------------------------------------------------------|
| `inspection`              | FK to the affected `Inspection`.                          |
| `client_version_number`   | Version the client submitted.                             |
| `server_version_number`   | Version the server held at conflict time.                 |
| `client_data`             | Full JSON snapshot of the client's payload.               |
| `server_data`             | Full JSON snapshot of the server's current state.         |
| `resolved`                | Boolean. False until a resolution strategy is applied.    |
| `resolved_at`             | Timestamp of resolution.                                  |
| `resolved_by`             | FK to the user who resolved it. Nullable.                 |
| `resolution_strategy`     | `keep_mine`, `keep_theirs`, or `merge`.                   |

Both data snapshots are stored at conflict time, not lazily. If an inspection is subsequently updated again, the snapshots still reflect what the client and server held at the moment the conflict was detected. This is important for audit: the record is a factual account of a specific divergence event.

Indexed on: `inspection` (lookup by entity), `resolved` (filtering unresolved), `(resolved, created_at)` (ordered unresolved queue).

## Soft Delete Rules

`Inspection` records set `is_deleted = True` via `soft_delete(user)`. The `deleted_at` timestamp and `deleted_by` FK are recorded. Hard deletion is not available through the application layer.

The default query manager (`InspectionManager`) filters `is_deleted=False` on every query. Code that uses `Inspection.objects` will never see deleted records unless it explicitly switches to `Inspection.all_objects`, which bypasses the filter.

This is a deliberate two-manager pattern. `all_objects` exists for administrative and audit access only. It must not be used in any path that processes user-facing data or sync operations.

`InspectionTemplate` uses a different soft delete pattern: `is_active = False` with a `deleted_at` timestamp. Templates are not filterable by a custom manager — their inactive state is checked explicitly where relevant. Templates cannot be hard-deleted because existing `Inspection` records reference them via a `PROTECT` foreign key constraint.
