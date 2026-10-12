-- Run manually by a database administrator in the target PostgreSQL database.
-- Do not use the migration role for application traffic.

CREATE ROLE sykra_app LOGIN PASSWORD '<set-in-secret-manager>';
CREATE ROLE sykra_migrator LOGIN PASSWORD '<set-in-secret-manager>';

GRANT CONNECT ON DATABASE sykra TO sykra_app, sykra_migrator;
GRANT USAGE ON SCHEMA public TO sykra_app, sykra_migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sykra_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sykra_app;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sykra_migrator;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sykra_migrator;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sykra_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO sykra_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL PRIVILEGES ON TABLES TO sykra_migrator;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL PRIVILEGES ON SEQUENCES TO sykra_migrator;
