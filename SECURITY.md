# Security controls

Sykra uses a server-side PostgreSQL session model. The browser receives only an
HttpOnly, SameSite=Lax cookie; the raw session token is never stored in the
database, logs, URL, or local storage.

## Controls mapped to OWASP Top 10:2025

- **Broken Access Control (A01):** chat list, read, rename, delete,
  and message persistence queries require the authenticated `user_id`. A chat
  belonging to another account returns 404.
- **Cryptographic Failures (A04) and Authentication Failures (A07):** passwords require 12+ characters and are
  hashed with Argon2id through `pwdlib`. Sessions are random, hashed at rest,
  expiring, revocable individually, and revocable across all devices.
- **Injection (A05):** database access uses SQLAlchemy parameters and Pydantic
  validation; no user-controlled SQL is interpolated.
- **Security Misconfiguration (A02):** CORS is allowlisted, CSP,
  `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, and
  production HSTS are set.
- **Logging and Alerting Failures (A09):** authentication errors are generic.
  Do not log passwords, cookies, tokens, or full message content.
- **SSRF / unsafe content:** paper URLs must remain validated before rendering;
  model output is treated as data, not executable HTML.
- **LLM application risks:** uploaded papers and retrieved text are untrusted
  evidence, never instructions. The model receives only the current user's
  request context and server-side system instructions.

- **Software Supply Chain Failures (A03):** versions are pinned where practical;
  Dependabot and CI dependency audits cover Python, npm, Docker, and Actions.
- **Software or Data Integrity Failures (A08):** migration files are versioned,
  uploads use opaque private names, and ClamAV scanning can be enabled.
- **Mishandling of Exceptional Conditions (A10):** invalid ownership, expired
  tokens, scanner failures, and production Redis misconfiguration fail with
  explicit errors rather than success-shaped fallbacks.

## Implemented account and platform controls

- Email verification and single-use password reset tokens are hashed at rest
  and expire after 24 hours and 30 minutes respectively.
- HIBP k-anonymity checks send only a five-character SHA-1 prefix.
- Google OAuth is optional and uses a validated, HttpOnly state cookie before
  creating the normal Sykra session.
- PDF uploads validate magic bytes, size, ownership, private storage, and
  optional fail-closed ClamAV scanning.
- Redis fixed-window rate limits return `429` with `Retry-After`; development
  fallback is not available in production.
- Account export and password-confirmed deletion are available from Settings.
- Production redirects HTTP to HTTPS and emits HSTS.

## Known limitations

- Legacy graph/vector stores are not fully migrated into PostgreSQL; the
  authenticated research-session ownership boundary protects the exposed
  routes, but a full durable per-user migration remains future work.
- Streaming cancellation is process-local and does not survive a backend
  restart.
- Full integration tests for PostgreSQL, Redis, ClamAV, OAuth, and email
  providers require separately configured services.
- Current frontend lint and npm audit report pre-existing issues; CI exposes
  them and no breaking forced audit upgrade was applied.
- The backend dependency audit currently reports ChromaDB advisories without a
  published fixed version. The Cerebras adapter also constrains
  `langchain-openai` to the vulnerable 0.3.x line; removing that provider
  would be a functional change, so it remains an explicitly tracked upstream
  blocker.

See [`docs/PRODUCTION_CHECKLIST.md`](./docs/PRODUCTION_CHECKLIST.md) for the
remaining human-only deployment steps.
