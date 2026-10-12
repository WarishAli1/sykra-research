# Production checklist

The following steps require accounts, production credentials, or an explicit
launch decision and are intentionally not automated in this repository.

- [ ] Create an email provider account, generate an API key, set
  `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, and `EMAIL_FROM`.
- [ ] Create a Google Cloud OAuth client, configure the exact HTTPS callback
  URL `/api/auth/google/callback`, and set the Google client variables.
- [ ] Create a private production S3/R2 bucket and access keys, then configure
  the production storage adapter and lifecycle policy.
- [ ] Create managed production PostgreSQL, enable backups and point-in-time
  recovery, perform and document a test restore, and configure separate app
  and migration role URLs.
- [ ] Create hosting accounts, connect the production domains, and provision
  HTTPS certificates.
- [ ] Put all production secrets in the hosting provider's secret manager;
  never upload `.env`.
- [ ] Run `alembic upgrade head` against production using
  `MIGRATION_DATABASE_URL` after reviewing the migration plan.
- [ ] Enable GitHub secret scanning and push protection for the repository.
- [ ] Complete a staging test covering signup, verification, reset, OAuth,
  multi-device sessions, ownership isolation, uploads, export, deletion, and
  rate limits; then record the launch decision.

Before launch, also configure Redis, ClamAV or an approved malware-scanning
replacement, monitoring, alerting, backups, and an incident-response owner.
