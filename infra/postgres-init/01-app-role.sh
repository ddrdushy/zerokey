#!/usr/bin/env bash
# Provisions the non-superuser application role used by Django at runtime.
# Per ARCHITECTURE.md and DATA_MODEL.md, the app must NOT connect as a
# superuser — superusers bypass Row-Level Security policies, which is the
# entire mechanism enforcing multi-tenancy isolation.
set -euo pipefail

APP_USER="${POSTGRES_APP_USER:-zerokey_app}"
APP_PASSWORD="${POSTGRES_APP_PASSWORD:-zerokey_app_dev}"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_USER') THEN
            CREATE ROLE $APP_USER LOGIN PASSWORD '$APP_PASSWORD';
        END IF;
    END
    \$\$;

    GRANT CONNECT ON DATABASE $POSTGRES_DB TO $APP_USER;
    GRANT USAGE, CREATE ON SCHEMA public TO $APP_USER;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $APP_USER;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO $APP_USER;

    -- Required for ``manage.py test`` / pytest-django, which spin up a
    -- throwaway ``test_<dbname>`` database. Granting CREATEDB to a
    -- non-superuser is the standard Django dev-env pattern; it does
    -- NOT bypass Row-Level Security (only superusers do that), so the
    -- multi-tenant isolation contract is preserved.
    ALTER ROLE $APP_USER CREATEDB;
SQL
