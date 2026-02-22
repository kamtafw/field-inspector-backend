# Sync Engine — Architectural Invariants

## What Invariant Does This Protect?

The batch endpoint processes multiple client operations in a single request and returns a per-operation result for each one. No operation silently disappears. Idempotency is enforced before any mutation occurs. Partial batch failure does not contaminate the results of successful operations.

## What Assumptions Must Never Change?

1. **Idempotency is checked before mutation logic.** The check-then-write sequence must not be inverted or made concurrent. Permission checks come after. This order is mandatory.
2. **Results are returned in request order.** Never return unordered results; clients rely on positional correspondence to correlate results with their submitted operations.
3. **Per-operation atomicity, not batch-wide atomicity.** A failure in operation N must not prevent operations N+1 through M from being attempted.
4. **Conflict metadata is always returned on conflict.** The client needs both versions to resolve intelligently.

## What Breaks If This Is Modified Incorrectly?

Checking idempotency after the write creates a race window where two concurrent requests with the same key both succeed. Processing operations dependently means a single bad operation (e.g., a validation error) could block an entire batch. Reordering results breaks the client's ability to map outcomes back to local queue entries.

## Batch Processor Flow

The batch endpoint (`POST /api/v1/sync/batch/`) accepts a list of operations, each containing an `operation_type`, `idempotency_key`, and `data` payload. Processing follows this sequence for each operation:

```toml
1. Extract idempotency_key and operation_type from operation
2. Check SyncOperation table for existing key
   ├── Found → return cached result immediately (no write)
   └── Not found → proceed to step 3
3. Delegate to process_operation(operation_type, idempotency_key, data, user)
4. On success → persist SyncOperation record with cached result
5. On ConflictError → return 409 payload (no SyncOperation record created)
6. On any other exception → return error payload for this operation, continue to next
```

The outer loop does not short-circuit. Every operation is attempted and every result is appended, regardless of how prior operations resolved. The response is HTTP `207 Multi-Status` with a JSON array of per-operation results.

**Why per-operation, not batch-wide?**

- Batch-wide atomicity would block pending operations if one operation is invalid.
- Example: If operation #50 has a bad template ID, all 49 prior successful operations would roll back. Unacceptable.
- Mobile queue is already granular; per-operation semantics match client expectations.

## Atomicity Boundaries

Each operation in a batch is processed within its own implicit database transaction boundary via Django's ORM. Operations are not grouped into a single transaction spanning the entire batch.

This is intentional. A single transaction across 100 operations would hold locks for the duration of the entire batch. Any failure — including a `ConflictError` on operation 50 — would roll back all 100 operations, including the 49 that succeeded.

The trade-off is that a batch is not all-or-nothing. Partial success is possible and expected. The `207 Multi-Status` response communicates this explicitly. Clients are responsible for reading per-operation results and re-queuing or handling any that did not succeed.

The client-side batch implementation captures local rollback points before sending the request. If the entire batch request fails at the network level (before any server processing occurs), the client restores local state from those snapshots. This is distinct from partial server-side failure, which is handled per-operation.

## Per-Operation Result Structure

Each entry in the response array corresponds to the input operation at the same index.

**A successful result:**

```json
{
  "index": 0,
  "success": true,
  "idempotency_key": "...",
  "operation_type": "CREATE_INSPECTION",
  "data": {"id": "...", "version": 1}
}
```

**A conflict result:**

```json
{
  "index": 1,
  "success": false,
  "error": "conflict",
  "idempotency_key": "...",
  "operation_type": "UPDATE_INSPECTION",
  "conflict_data": {
    "client_version": 2,
    "server_version": 3,
    "server_data": {...}
  }
}
```

**A general failure result:**

```json
{
  "index": 2,
  "success": false,
  "error": "...",
  "idempotency_key": "...",
  "operation_type": "UPDATE_INSPECTION"
}
```

The `index` field is redundant with array position but is included explicitly. Clients that parse results out of order or log them individually can use it without re-deriving position.

Rules:

- Array length equals operations length.
- Order is preserved.
- `version` populated on success and conflict.
- `server_data` populated only on conflict.
- `error_code` is stable vocabulary.
- `error_message` is not parseable contract.

If an operation is skipped, it must still emit a `status: error` result.

This preserves deterministic client mapping.

## Idempotency Validation Order

Idempotency is validated as the first action inside the batch loop, before any model is touched:

```py
existing = SyncOperation.objects.filter(idempotency_key=idempotency_key).first()
if existing:
    return cached_result(existing)
```

This placement is not an optimization — it is the correctness guarantee. The idempotency check must happen before any read of mutable state and before any write. If it were placed after the business logic, a concurrent retry could pass the check while the first request is mid-write, resulting in two successful executions of the same operation.

After a successful operation, a `SyncOperation` record is written with the serialized response as `result`. Future duplicate requests return this value directly, without re-running any service logic.

Conflicts (`ConflictError`) do not create a `SyncOperation` record. A conflict is not a successful completion — the operation was not applied. If the client retries after resolving the conflict with a new version number, it will also submit a new idempotency key (because the underlying mutation changed). The old key will never match a new request.

## Conflict Detection

Conflict detection occurs inside UPDATE handler.

Rule:

```py
if current.version != operation.base_version:
    return ConflictResult(...)
```

The comparison is strict inequality.

**Why not `<`?**  
A client sending a version higher than server indicates corruption or a logic bug. That must also produce a conflict.

On conflict:

- No mutation occurs.
- A ConflictLog entry is written.
- Full server snapshot is returned.
- Server version is returned.
