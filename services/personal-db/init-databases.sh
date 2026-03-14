#!/bin/bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE ghostfolio;
    CREATE DATABASE paperless;
    CREATE DATABASE wger;
    CREATE DATABASE plane;
    CREATE DATABASE estate_planning;
    CREATE DATABASE finance_graph;
    CREATE DATABASE household_tax;
    CREATE DATABASE family_edu;
    CREATE DATABASE health_graph;
    CREATE DATABASE orchestration;

    -- Estate-planning schema user
    CREATE USER estate WITH PASSWORD '${ESTATE_DB_PASSWORD}';
    -- Finance graph schema user (default to estate password if FINANCE_DB_PASSWORD is not set)
    CREATE USER finance WITH PASSWORD '${FINANCE_DB_PASSWORD:-${ESTATE_DB_PASSWORD}}';
    -- Household tax schema user (default to finance password if HOUSEHOLD_TAX_DB_PASSWORD is not set)
    CREATE USER household_tax WITH PASSWORD '${HOUSEHOLD_TAX_DB_PASSWORD:-${FINANCE_DB_PASSWORD:-${ESTATE_DB_PASSWORD}}}';
    -- Family education schema user (default to estate password if FAMILY_EDU_DB_PASSWORD is not set)
    CREATE USER family_edu WITH PASSWORD '${FAMILY_EDU_DB_PASSWORD:-${ESTATE_DB_PASSWORD:-changeme}}';
    -- Health graph schema user (default to estate password if HEALTH_DB_PASSWORD is not set)
    CREATE USER health WITH PASSWORD '${HEALTH_DB_PASSWORD:-${ESTATE_DB_PASSWORD:-changeme}}';
    -- Orchestration schema user (mail worker, delegation state)
    CREATE USER orchestration WITH PASSWORD '${ORCHESTRATION_DB_PASSWORD:-${ESTATE_DB_PASSWORD:-changeme}}';

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

    \connect household_tax
    CREATE SCHEMA IF NOT EXISTS tax AUTHORIZATION household_tax;
    GRANT USAGE ON SCHEMA tax TO household_tax;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA tax TO household_tax;
    ALTER DEFAULT PRIVILEGES IN SCHEMA tax GRANT ALL ON TABLES TO household_tax;
    ALTER DEFAULT PRIVILEGES IN SCHEMA tax GRANT ALL ON SEQUENCES TO household_tax;


    \connect health_graph
    CREATE SCHEMA IF NOT EXISTS health AUTHORIZATION health;
    GRANT USAGE ON SCHEMA health TO health;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA health TO health;
    ALTER DEFAULT PRIVILEGES IN SCHEMA health GRANT ALL ON TABLES TO health;
    ALTER DEFAULT PRIVILEGES IN SCHEMA health GRANT ALL ON SEQUENCES TO health;

    \connect family_edu
    CREATE SCHEMA IF NOT EXISTS family_edu AUTHORIZATION family_edu;
    GRANT USAGE ON SCHEMA family_edu TO family_edu;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA family_edu TO family_edu;
    ALTER DEFAULT PRIVILEGES IN SCHEMA family_edu GRANT ALL ON TABLES TO family_edu;
    ALTER DEFAULT PRIVILEGES IN SCHEMA family_edu GRANT ALL ON SEQUENCES TO family_edu;

    \connect orchestration
    CREATE SCHEMA IF NOT EXISTS orchestration AUTHORIZATION orchestration;
    GRANT USAGE ON SCHEMA orchestration TO orchestration;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA orchestration TO orchestration;
    ALTER DEFAULT PRIVILEGES IN SCHEMA orchestration GRANT ALL ON TABLES TO orchestration;
    ALTER DEFAULT PRIVILEGES IN SCHEMA orchestration GRANT ALL ON SEQUENCES TO orchestration;

EOSQL
