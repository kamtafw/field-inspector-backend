# Scaling — Architectural Invariants

## What Invariant Does This Protect?

The system's capacity to handle more users, more requests, and more data grows through horizontal and structural means — not by making individual components stateful or tightly coupled.

## What Assumptions Must Never Change?

- The API layer holds no per-request or per-user in-memory state. Any instance can handle any request.
- The database is the system's consistency boundary. All locking and conflict detection happens there.
- Binary assets (photos) never pass through the application server. The Cloudinary signed upload flow is non-negotiable.

## Stateless API Scaling

The Django REST Framework API is stateless by design. Authentication uses JWT Bearer tokens. The token carries the user's identity and is validated on each request without a server-side session lookup. No request context is held in application memory between calls.

This means any number of API instances can run behind a load balancer and any instance can serve any request. Scaling out is a matter of adding instances — no coordination between them is required.

The one shared resource across instances is the database. PostgreSQL is the consistency boundary. Optimistic locking (`version` checks) and the `UNIQUE` constraint on `idempotency_key` are enforced at the database level, not the application level. This means correctness is preserved even when two instances process concurrent requests for the same inspection.

Redis is used for caching (ETag-based template responses). It is shared across instances. Losing Redis degrades cache hit rates but does not break correctness — template data is authoritative in PostgreSQL.

## Database Indexing Strategy

Indexes are defined explicitly on query patterns that are known at design time. The current set covers:

**`inspections` table**  

| Index                    | Query  Pattern                                                                 |
|--------------------------|--------------------------------------------------------------------------------|
| `(inspector_id, status)` | inspector's filtered inspection list                                           |
| `(template_id, status)`  | template-scoped inspection queries                                             |
| `(is_deleted, status)`   | soft-delete filtering combined with status (applied on every default queryset) |
| `(created_at)`           | chronological ordering                                                         |
| `(submitted_at)`         | approval workflow queries                                                      |

**`sync_operations` table**  

| Index                            | Query Pattern                           |
|----------------------------------|-----------------------------------------|
| `(idempotency_key)`              | fast idempotency lookup on every write  |
| `(entity_id)`                    | operation history by inspection         |
| `(user_id, processed_at)`        | user-scoped sync history                |
| `(operation_type, processed_at)` | operational monitoring                  |

The `(is_deleted, status)` index on `inspections` deserves specific attention. The `InspectionManager` appends `is_deleted=False` to every default query. Without an index on this combination, every list query becomes a full table scan filtered after the fact. As the table grows, this becomes the dominant query cost.

Adding indexes without corresponding query patterns wastes write performance and storage. Indexes should only be added in response to identified query patterns or measured slow queries — not speculatively.

## Media Offload Architecture

Photos implement a **signed-URL direct upload flow**. They are never processed or stored by the application. The flow is:

1. **Request:** Mobile client calls `/api/v1/photos/upload-params/`.
   - Returns: Pre-signed upload URL + required headers.
   - Server does NOT generate the binary.

2. **Upload:** Client uploads directly to cloud storage (Cloudinary).
   - Server is not in the request path.
   - Client manages retries, resumption, resumption.

3. **Verify:** Client calls `/api/v1/photos/confirm/` with the asset ID.
   - Server verifies the asset exists in cloud storage.
   - Server creates a Photo record linking to the asset.

The application server handles two small JSON requests per photo. It never receives, buffers, or streams binary data. This has several structural consequences:

 Django workers are not blocked waiting for large file uploads over slow mobile connections

- No local disk or object storage configuration is required on the server
- Photo delivery (CDN, transformations, format negotiation) is handled entirely by Cloudinary
- The server's memory footprint per request stays bounded and predictable

Removing this pattern and routing uploads through Django would require significantly more worker capacity to maintain the same throughput, particularly in field environments where mobile connections are slow and uploads take seconds to minutes.

## Why the Batch Endpoint Reduces Load?

Without a batch endpoint, a mobile client returning from offline would submit one HTTP request per queued operation. A user who created 20 inspections offline would generate 20 sequential (or concurrent) requests on reconnect.

With `POST /api/v1/sync/batch/`, those 20 operations arrive in a single request. The reduction is not just in request count — each HTTP request carries overhead: TLS handshake amortization, connection setup, authentication token validation, and DRF request/response serialization. Batching eliminates this overhead for all but one request per sync cycle.

The batch endpoint accepts up to **100 operations per request**. This ceiling prevents a single request from holding a worker thread indefinitely or exhausting per-request memory limits. It is not a hard limit on how many operations a client can sync — clients with more than 100 queued operations split them across multiple batch calls.

The combination of stateless API scaling, explicit indexing, media offload, and batch sync means the system's bottlenecks under load are predictable: database write throughput and connection pooling. Those are known, well-understood problems with established solutions (connection pooling via pgBouncer, read replicas for reporting queries) rather than novel architectural constraints.

## What Breaks If This Is Modified Incorrectly?

| Modification                         | Consequence                                                                                                | Severity     |
|--------------------------------------|------------------------------------------------------------------------------------------------------------|--------------|
| Add in-memory user caches            | Requires sticky sessions. Load balancer loses freedom. Horizontal scaling constrained. Cold starts hurt.   | **HIGH**     |
| Use Django sessions for API auth     | Sessions become per-instance. Sticky routing required. Horizontal scaling effectively blocked.             | **CRITICAL** |
| Proxy photo uploads through Django   | App tier becomes I/O-bound. CPU blocked. Bandwidth spikes. More instances required. CDN advantages lost.   | **HIGH**     |
| Generate thumbnails in request path  | Requests block on image processing. Latency spikes. Timeouts trigger retries. Retry storms possible.       | **HIGH**     |
| Batch-wide atomicity                 | One failure rolls back all operations. Entire batch retries. Queue stalls under reconnect storms.          | **CRITICAL** |
| Remove batch endpoint                | N operations → N requests. Reconnect storms exhaust connection pool. Cascading failures under normal load. | **CRITICAL** |
| Lazy-load relationships in responses | N+1 queries per batch. Query count explodes. Latency and timeouts cascade.                                 | **HIGH**     |
| Store device retry state server-side | Extra DB lookups per request. Cross-device contention. State ownership misplaced.                          | **MEDIUM**   |
