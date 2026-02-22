# VANTAGE Field Inspector — System Overview

**Document scope:** This document sits above both the `field-inspector-mobile` and `field-inspector-backend` repositories. It describes the system as a single distributed architecture — what each node is responsible for, where the boundaries are, how the nodes coordinate, and what correctness guarantees the system makes as a whole.

Read this before making changes that cross the mobile/backend boundary.

## 1. What This System Is

VANTAGE Field Inspector is an **offline first distributed inspection platform** designed for a specific operational reality: inspectors work in low-connectivity environments where uninterrupted access to a server cannot be assumed, but the work they produce must eventually converge into a shared, authoritative record.

The system is composed of:

- **A mobile client** (React Native + WatermelonDB)
- **A stateless API** (Django REST Framework)
- **A PostgreSQL database** (consistency boundary)
- **Cloudinary** (media storage + delivery)

The mobile client is not a thin UI over an API.  
It is a fully capable offline node. It stores data locally, queues outgoing mutations, and synchronizes when connectivity permits.

The backend is not a real-time dependency.  
It is the **canonical authority** of the organization's data. It enforces integrity, validates idempotency, detects conflicts, and persists the authoritative version of every inspection.

**Clarification of “source of truth”:**

The mobile database is the operational source of truth for the user experience. It drives what the inspector sees and interacts with.

The backend database is the canonical source of truth for the organization. It determines the official, audit-relevant state of inspections.

Both statements are true within their respective scopes.

## 2. System Topology

```scss
┌─────────────────────────────────────────────────────────────────┐
│                        Field Device                             │
│                                                                 │
│   Inspector UI (React Native Screens)                           │
│          │                                                      │
│          ▼                                                      │
│   Local Database (WatermelonDB / SQLite)  ◄── UX Source         │
│          │                                                      │
│          ▼                                                      │
│   Sync Queue (sync_operations table)                            │
│          │                                                      │
│          ▼                                                      │
│   SyncEngine  ──── CircuitBreaker                               │
│          │         NetworkResilience                            │
│          │                                                      │
└──────────┼──────────────────────────────────────────────────────┘
           │
           │  HTTPS  (JWT Bearer Auth + Idempotency-Key)
           │
           │   POST /api/v1/inspections/
           │   POST /api/v1/sync/batch/
           │   POST /api/v1/photos/upload-params/
           │   POST /api/v1/photos/confirm/
           │
┌──────────┼──────────────────────────────────────────────────────┐
│          ▼                                                      │
│   Django REST API (Stateless, horizontally scalable)            │
│          │                                                      │
│          ▼                                                      │
│   Service Layer                                                 │
│   ├── InspectionService  (optimistic locking, versioning)       │
│   └── SyncService        (idempotency, batch processing)        │
│          │                                                      │
│          ▼                                                      │
│   PostgreSQL (Consistency Boundary)    Redis (ETag cache)       │
│   ├── inspections                                               │
│   ├── sync_operations (idempotency log)                         │
│   └── conflict_records                                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
           │
           │  Signed upload URL
           ▼
      Cloudinary (binary asset storage, CDN delivery)
```

The API layer is stateless. Any instance can serve any request.  
All cross-request guarantees terminate at the database.

## 3. The Core Design Decision

The mobile client does not depend on the server to function.

This is not a UX optimization. It is the structural constraint everything else is built around.

Because the client can operate offline indefinitely, the consequence of this is that the client and server may independently hold diverging versions of the same record. This is not an edge case. It is the normal condition when an inspector is offline. The system's job is not to prevent this divergence — it cannot — but to detect it when it resolves, surface it correctly, and require a human decision before any overwrite occurs.

This commitment drives the following invariants:

- The local database is not a cache. It is a persistent operational store.
- Every mutation is written locally before it is transmitted.
- Every queued operation carries an idempotency key generated at queue time.
- Every update carries the client's last known version
- The server rejects stale versions with `409 Conflict`.
- A stale write is never retried by incrementing versions locally.
- Conflicts require deliberate user resolution.

Correctness is enforced by protocol and database constraints — not by timing assumptions.

## 4. Consistency Model

This system is **locally consistent per node and converges through explicit reconciliation**.

It is not globally consistent at all times.

Temporary divergence between mobile and backend is allowed. Convergence occurs when:

- The client transmits queued mutations.
- The server enforces optimistic locking.
- Conflicts are resolved explicitly by the user.

The model uses:

- **Optimistic concurrency control** (version integers)
- **At-least-once transmission**
- **At-most-once effect** (via idempotency keys)
- **Mandatory conflict surfacing**

Guarantees:

- A write that passes version validation is applied exactly once.
- A write that fails version validation is never applied silently.
- A duplicate write (same idempotency key) never produces duplicate effect.
- No inspection is hard-deleted.
- No version is incremented silently.

Non-guarantees:

- Automatic merge of concurrent offline edits.
- Client's local state at any moment reflects the server's current state
- Operations submitted in same batch are applied atomically across the batch

The consistency boundary is PostgreSQL.  
The `UNIQUE` constraint on `idempotency_key` and strict version comparison enforce correctness.

## 5. Device Model

The current product policy assumes **one active device per inspector account**.

However:

- The architecture does not rely on this assumption for correctness.
- If multiple devices are used concurrently, optimistic locking still prevents silent overwrites.
- Additional UX considerations (e.g, cross-device awareness) would be required to formally support multi-device workflows.

This distinction is intentional: the system is safe under multi-device concurrency, even if the product does not officially support it yet.

## 6. Data Lifecycle

### 6.1 Inspection Creation (Offline Path)

1. The inspector fills out a form on-device. On submission, the `InspectionRepository` writes a new `Inspection` record to the local SQLite database with `status: submitted`, `version: 1`, `is_synced: false`.
2. A `SyncOperation` record is written to the local `sync_operations` table in the same database write transaction. It carries a UUID idempotency key, `operation_type: CREATE_INSPECTION`, and a serialized payload.
3. The UI immediately reflects the inspection from local state. No network call has occurred.
4. When the `SyncEngine` detects connectivity (or is already online), it fetches pending operations and processes them. For a CREATE, it calls `POST /api/v1/inspections/` with the idempotency key as a header.
5. The server creates the inspection, stores a `SyncOperation` record keyed on the idempotency key, and returns the server-assigned UUID and version.
6. The client updates its local record with `remote_id` and `is_synced: true`.

### 6.2 Inspection Update (With Concurrent Edit Risk)

1. The inspector edits a previously synced inspection. The local record is updated immediately. A `SyncOperation` with `operation_type: UPDATE_INSPECTION` is queued, carrying the current local `version`.
2. The `SyncEngine` sends `PATCH /api/v1/inspections/{remote_id}/` with the version in the payload.
3. The server compares the submitted version against `inspection.version` in PostgreSQL.
   - **Match** → write succeeds, `inspection.version` increments, response returned, local record updated.
   - **Mismatch** → `409 Conflict` returned with both version numbers and a full snapshot of the server's current state.
4. On a 409, the client creates a `ConflictRecord` locally with both data snapshots. The inspection status transitions to `conflict`. The sync operation is marked completed — the conflict has been handled, not failed.
5. The inspector navigates to conflict resolution, chooses a strategy (`keep_mine`, `keep_theirs`, or `merge`), and confirms. The local record is updated with the resolved data and `version = serverVersion`. A new sync operation is queued.

### 6.3 Photo Upload

Photos are decoupled from inspection sync. The sequence is:

1. After inspection operations complete, the `PhotoUploadService` processes queued photos.
2. The client requests signed upload parameters from the backend (`POST /api/v1/photos/upload-params/`). The backend generates a Cloudinary signature.
3. The client uploads directly to Cloudinary using those parameters. The backend is not in this path.
4. The client confirms the upload to the backend (`POST /api/v1/photos/confirm/`). The backend verifies the asset exists in Cloudinary and records the URL and metadata.

The backend never receives photo bytes. This is load-structural, not incidental.

### 6.4 Approval Workflow

```toml
draft → submitted → approved
                  ↘ rejected
```

Managers approve or reject submitted inspections via the backend API. Each approval or rejection calls `increment_version()` on the inspection, which means a manager action on a submitted inspection can cause a version conflict if the inspector has meanwhile made offline edits. The system handles this identically to any other conflict.

## 7. The Sync Protocol

The protocol between the two sync engines is deliberately asymmetric. The mobile client drives synchronization; the backend responds. The backend does not push changes.

### Client Responsibilities

- Generate idempotency keys before first transmit.
- Preserve operation ordering (ascending `created_ts`)
- Route to batch or individual endpoint based on queue depth (threshold: 3+)
- Handle 409 as a conflict signal, not an error
- Implement exponential backoff and circuit breaker
- Never reuse idempotency keys for new logical mutations

### Server Responsibilities

- Check idempotency before mutation
- Return cached results for duplicate key
- Enforce version check before update
- Return per-operation results in request order
- Persist `ConflictRecord` snapshot at conflict time
- Never increment version silently

### Explicit Non-Goals

- The server does not push state changes to the client. There is no WebSocket, no polling, no push-triggered sync.
- The client does not pull a full server state on sync. It only pushes its queued operations.
- There is no operational transform, no CRDT, no merge algorithm at the protocol level. Merging is a user-assisted, field-by-field action, not an automated one.

This is intentional. The system trades automatic convergence for explicit, auditable human decisions on conflicting data.

## 8. Failure Modes and System Behavior

**Network unavailable:**  
The mobile client continues normal operation. Mutations accumulate in the local sync queue. When connectivity returns, `NetInfo` fires a state change event and the `SyncEngine` processes the queue. No user action required.

**Server returns 5xx:**  
The operation is marked failed. Exponential backoff is applied (`min(2^retryCount, 64)` seconds). After 5 failures the inspection is quarantined and removed from automatic processing.

**Server returns 409:**  
Not treated as a failure. The conflict flow is initiated. The sync operation is marked completed. A local `ConflictRecord` is created. The inspector resolves manually.

**App crash mid-sync:**  
`BootManager` re-runs all initialization steps on the next launch. The sync queue is re-fetched from the database. Operations marked `in_progress` at crash time are not automatically retried — they remain in that status until the engine evaluates them. The `DataIntegrityService` scans for stuck states on every boot.

**Batch request network failure (before server processes):**  
The `SyncEngine` captured rollback points for all operations in the batch before sending. On a network-level failure, local state is restored from those snapshots. Operations return to `failed` status and re-enter the retry cycle.

**Duplicate request (client retries a completed operation):**  
The server finds the `idempotency_key` in `sync_operations` and returns the cached result immediately. No write occurs. The client receives a success response indistinguishable from the original.

## 9. Node Boundaries and Ownership

Understanding which node owns which responsibility prevents the most common class of architectural rot: logic that should live in one node drifting into the other.

| Concern                    | Owner                   | Rationale                                                |
|----------------------------|-------------------------|----------------------------------------------------------|
| UX state                   | Mobile                  | UI must work offline                                     |
| Canonical record           | Backend                 | Organizational authority                                 |
| Idempotency key generation | Mobile                  | Must exist pre-transmission                              |
| Idempotency enforcement    | Backend (DB constraint) | Cannot trust client retries                              |
| Version increment          | Backend only            | Client cannot predict post-write version                 |
| Conflict detection         | Backend                 | Only server sees concurrent writes                       |
| Conflict record creation   | Both                    | Server returns conflict data; client persists it locally |
| Conflict resolution        | Mobile (user-facing)    | Human judgment required                                  |
| Media storage              | Cloudinary              | Binary assets must not pass through app server           |
| Auth token validation      | Backend                 | Client stores tokens; backend validates them             |
| Retry scheduling           | Mobile                  | Client owns its own queue pacing                         |
| Circuit breaker            | Mobile                  | Protects client from hammering a degraded server         |

## 10. Architectural Guardrails

Changes that cross the node boundary — anything that touches how the client and server communicate — should be evaluated against these questions:

**Changing the sync protocol (endpoints, payloads, response structure)**  
Client and server sync engines must remain in agreement on idempotency key handling, version field semantics, and 409 response structure. Misalignment causes silent data loss or permanent sync failures.

**Changing version logic or conflict detection**  
Altering when or how versions increment can allow silent overwrites to pass undetected.

**Changing the boot sequence**  
Reordering or parallelizing boot steps can cause the sync engine to start before auth is restored, or repositories to be accessed before the database is initialized.

**Changing data models (adding fields, altering constraints)**  
The `UNIQUE` constraint on `idempotency_key` and the `version` field are enforced at the database level. Removing or weakening them removes correctness guarantees the rest of the system depends on.

**Scaling the backend**  
The API is stateless by design. Introducing any per-instance in-memory state (session storage, local queues) breaks horizontal scalability and makes correctness routing-dependent.

## 11. Technology Reference

| Component           | Technology                      | Purpose                           |
|---------------------|---------------------------------|-----------------------------------|
| Mobile runtime      | React Native 0.81, Expo SDK 54  | iOS and Android client            |
| Mobile local DB     | WatermelonDB (SQLite)           | Offline-first local persistence   |
| Mobile auth storage | Expo SecureStore                | JWT token storage                 |
| Mobile connectivity | NetInfo                         | Online/offline detection          |
| Backend framework   | Django 5 + DRF                  | REST API, business logic          |
| Backend database    | PostgreSQL (prod), SQLite (dev) | Authoritative data store          |
| Backend cache       | Redis                           | ETag cache for template responses |
| Backend auth        | djangorestframework-simplejwt   | JWT issuance and rotation         |
| Media storage       | Cloudinary                      | Binary asset storage and CDN      |
