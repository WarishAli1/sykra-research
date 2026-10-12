# Sykra Research

## Local development

Copy `.env.example` to `.env`, set a long random `POSTGRES_PASSWORD`, and make
the same `DATABASE_URL` available to the backend.

```bash
docker compose up -d postgres redis
cd backend
alembic upgrade head
cd ../frontend
npm run dev
```

The backend uses PostgreSQL for users, sessions, chats, messages, and library
metadata. Run `alembic upgrade head` after pulling migrations. The frontend
protects `/app` and sends requests with credentials so the backend can enforce
ownership from the HttpOnly session cookie.

For local HTTP use `SECURE_COOKIES=false`; production must use HTTPS and
`SECURE_COOKIES=true`. Configure `TRUSTED_ORIGINS` as a comma-separated
allowlist. Never commit `.env` or production secrets.

### Migrations and database roles

Alembic reads `MIGRATION_DATABASE_URL` when it is set and otherwise uses
`DATABASE_URL`. In production, point the application at the restricted role
and Alembic at the separate migration role. The role grants are documented in
[`ops/postgres_roles.sql`](./ops/postgres_roles.sql). Run migrations only with
the migration connection:

```bash
cd backend
alembic upgrade head
```

### Optional services

- `CLAMAV_ENABLED=true` enables fail-closed PDF malware scanning through the
  Compose `clamav` service.
- `EMAIL_PROVIDER=resend` enables verification and password-reset delivery;
  `console` is the development default.
- `REDIS_URL` enables distributed rate limiting. Development may use the
  in-memory fallback when it is unset; production requires Redis.
- Google OAuth is disabled until its client variables are configured.

### Tests and checks

```bash
PYTHONPATH=backend pytest -q backend/tests
cd frontend && npm run build
```

Database integration tests are enabled by setting `TEST_DATABASE_URL` to a
separate test database. Do not point tests at production.

## Authentication endpoints

- `POST /api/auth/signup`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `POST /api/auth/logout-all`
- `GET /api/auth/me`
- `GET /api/chats`
- `GET /api/chats/{chatId}`
- `GET /api/account/export`
- `DELETE /api/account`

## Deployment documentation

- [Security controls](./SECURITY.md)
- [Production checklist](./docs/PRODUCTION_CHECKLIST.md)
- [Ownership audit](./docs/OWNERSHIP_AUDIT.md)
- [Architecture decisions](./docs/DECISIONS.md)
