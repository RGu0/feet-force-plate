\set ON_ERROR_STOP on

REVOKE CONNECT ON DATABASE :"database_name" FROM PUBLIC;
ALTER SYSTEM SET listen_addresses = '127.0.0.1,::1';

CREATE ROLE ffp_seed_tenant LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    INHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'tenant_password';
CREATE ROLE ffp_seed_activation LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    INHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'activation_password';
CREATE ROLE ffp_seed_platform LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    INHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'platform_password';

GRANT ffp_tenant_app TO ffp_seed_tenant;
GRANT ffp_activation_app TO ffp_seed_activation;
GRANT ffp_platform_app TO ffp_seed_platform;
GRANT CONNECT ON DATABASE :"database_name"
    TO ffp_seed_tenant, ffp_seed_activation, ffp_seed_platform;

ALTER ROLE ffp_seed_tenant SET statement_timeout = '60s';
ALTER ROLE ffp_seed_activation SET statement_timeout = '30s';
ALTER ROLE ffp_seed_platform SET statement_timeout = '60s';
ALTER ROLE ffp_seed_tenant SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE ffp_seed_activation SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE ffp_seed_platform SET idle_in_transaction_session_timeout = '30s';
