# VANTAGE Field Inspector — Backend API

Backend API for the VANTAGE Field Inspector platform — an offline-first field inspection system designed for low-connectivity environments.
Built with Django REST Framework, this service manages inspection lifecycle, batch synchronization from mobile-clients, conflict detection, and secure media handling.

## Overview

The backend is designed around three core principles:

- **Offline resilience** — mobile clients can queue operations and sync later.
- **Data integrity** — optimistic locking and idempotency prevent accidental overwrites and duplicate writes.
- **Clear separation of concerns** — views handle HTTP, services handle business logic, models handle persistence.

## Architecture Summary

```stl
Mobile Clients (React Native)
              │
              ▼
Django REST API (DRF)
    ├── Auth
    ├── Inspections
    ├── Photos
    ├── Sync Engine
    └── Service Layer
              │
              ▼
PostgreSQL + Redis + Cloudinary
```

### Layered Design

- **Views** — request validation, authentication, serialization.
- **Services** — business logic (optimistic locking, idempotency, conflict handling).
- **Models** — persistence, versioning, soft deletes, indexing.

This structure keeps domain logic out of views and supports long-term maintainability.

## Core Features

### Optimistic Locking

Each `Inspection` carries `version` field. Updates must include the last known version. If this differs from the server's version, a `409 Conflict` is returned.

### Idempotent Sync Operations

All mutating operations accept an `Idempotency-Key`. Duplicate submissions return cached results, preventing double writes during network retries.

### Batch Sync Engine

`POST /api/v1/sync/batch/` processes up to 100 operations per request. Partial failures return HTTP `207 Multi-Status` with per-operation results.

### Conflict Tracking

Version conflicts create `ConflictRecord` entries containing both client and server snapshots. Clients can resolve via `keep_mine`, `keep_theirs`, or `merge` resolution strategies.

### Soft Deletes

`Inspection` records are never hard-deleted. Queries automatically exclude soft_deleted entries.

### Secure Media Flow

Photo uploads use a signed Cloudinary workflow:

1. Clients requests upload parameters.
2. Client uploads directly to Cloudinary.
3. Backend verifies and registers the asset.

### Template Caching

Inspection templates use ETag-based caching to avoid redundant payloads transfers.

## Tech Stack

- Python 3.11+
- Django + Django REST Framework
- PostgreSQL (production), SQLite (local development)
- Redis (caching / background tasks)
- JWT Authentication (`djangorestframework-simplejwt`)
- Cloudinary (media storage)

## Installation

```bash
git clone https://github.com/kamtafw/field-inspector-backend.git
cd field-inspector-backend

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Create a `.env` file and configure required variables:

```makefile
SECRET_KEY=
DEBUG=
DATABASE_URL=
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
```

Run migrations:

```bash
python manage.py migrate
```

Start the development server:

```bash
python manage.py runserver
```

API base URL:

```bash
http://localhost:8000
```

## API Overview

All endpoints are prefixed with:

```bash
/api/v1/
```

Authentication uses JWT Bearer tokens.

### Major Endpoint Groups

- `/auth/` — signup, login, refresh, logout
- `/inspections/` — inspection lifecycle management
- `/templates/` — read-only inspection templates
- `/photos/` — media handling
- `/sync/` — batch synchronization engine

Full request/response examples are available in /docs/api-reference.md.

## Data Model Highlights

### Inspection

- UUID primary key
- JSON-based checklist responses
- Status workflow (`draft → submitted → approved/rejected`)
- Integer `version` field for optimistic locking
- Soft delete support

### SyncOperation

Stores idempotency keys and cached responses for replay safety.

### ConflictRecord

Captures both client and server states when version mismatches occur

Full schema details: `/docs/data-models.md`

## Security

- JWT access tokens required for protected endpoints
- Refresh token rotation enabled
- Role-based access (inspector/manager)
- Rate limiting on sync and write operations
- CORS restricted to configured origins

## Deployment Summary

Production checklist:

- Set `DEBUG=False`
- Configure `ALLOWED_HOSTS`
- Use secure `SECRET_KEY`
- Configure PostgreSQL
- Configure Cloudinary credentials
- Run `collectstatic`
- Run `migrate`
- Use Gunicorn + Nginx
- Enable database connection pooling

Detailed deployment guide: `/docs/deployment.md`.

## Design Philosophy

This backend is structured to support:

- Offline-first mobile clients
- Concurrent editing without silent overwrites
- Safe retries under unstable networks
- Clear separation between HTTP concerns and domain logic

The goal is predictable behaviour under unreliable connectivity, and not just CRUD endpoints.
