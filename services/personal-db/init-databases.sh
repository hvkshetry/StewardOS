#!/bin/bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE ghostfolio;
    CREATE DATABASE paperless;
    CREATE DATABASE wger;
    CREATE DATABASE n8n;
    CREATE DATABASE estate_planning;
    CREATE DATABASE finance_graph;

    -- Estate-planning schema user
    CREATE USER estate WITH PASSWORD '${ESTATE_DB_PASSWORD}';
    -- Finance graph schema user (default to estate password if FINANCE_DB_PASSWORD is not set)
    CREATE USER finance WITH PASSWORD '${FINANCE_DB_PASSWORD:-${ESTATE_DB_PASSWORD}}';

    \connect estate_planning
    CREATE SCHEMA IF NOT EXISTS estate AUTHORIZATION estate;
    GRANT USAGE ON SCHEMA estate TO estate;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA estate TO estate;
    ALTER DEFAULT PRIVILEGES IN SCHEMA estate GRANT ALL ON TABLES TO estate;
    ALTER DEFAULT PRIVILEGES IN SCHEMA estate GRANT ALL ON SEQUENCES TO estate;

    \connect finance_graph
    CREATE SCHEMA IF NOT EXISTS finance AUTHORIZATION finance;
    GRANT USAGE ON SCHEMA finance TO finance;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA finance TO finance;
    ALTER DEFAULT PRIVILEGES IN SCHEMA finance GRANT ALL ON TABLES TO finance;
    ALTER DEFAULT PRIVILEGES IN SCHEMA finance GRANT ALL ON SEQUENCES TO finance;

    -- n8n user (OWNER required for PG 15+ public schema access)
    CREATE USER n8n WITH PASSWORD '${N8N_DB_PASSWORD}';
    ALTER DATABASE n8n OWNER TO n8n;
EOSQL
