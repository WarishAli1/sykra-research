# Architecture decisions

## Separate application and migration database roles

The runtime uses `DATABASE_URL` and should receive only data CRUD privileges.
Alembic uses `MIGRATION_DATABASE_URL` when configured so schema privileges are
not required by the application process. This is safer for production and
keeps local development simple when both variables point to the same database.

## Production HTTPS defaults

Secure cookies default to enabled in application settings. Local HTTP
development explicitly sets `SECURE_COOKIES=false` in `.env`. Production
requests sent over HTTP are redirected to HTTPS and HSTS is emitted only in
production.

## Legacy ownership boundary

Legacy research identifiers are claimed once by the first authenticated owner.
Unknown identifiers and identifiers owned by another user return 404. This
preserves the IDOR boundary without inventing ownership for anonymous legacy
data; old anonymous sessions may therefore need to be re-created.

## Dependency audit policy

CI runs audits without automatically applying breaking upgrades. Existing
frontend advisories and lint failures remain visible until their upstream
compatibility and code-level fixes can be reviewed separately.
