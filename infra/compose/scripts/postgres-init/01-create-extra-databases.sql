-- Idempotent ownership and access contract for third-party service databases.
-- Passwords arrive through psql variables populated from ephemeral environment
-- variables by the bootstrap job; they are never printed or embedded in Compose.
\getenv mlflow_password MLFLOW_DB_PASSWORD
\getenv phoenix_password PHOENIX_DB_PASSWORD

SELECT format('CREATE ROLE mlflow LOGIN PASSWORD %L', :'mlflow_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mlflow')\gexec
ALTER ROLE mlflow WITH LOGIN PASSWORD :'mlflow_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

SELECT format('CREATE ROLE phoenix LOGIN PASSWORD %L', :'phoenix_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'phoenix')\gexec
ALTER ROLE phoenix WITH LOGIN PASSWORD :'phoenix_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

SELECT 'CREATE DATABASE mlflow OWNER mlflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflow')\gexec
SELECT 'CREATE DATABASE phoenix OWNER phoenix'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'phoenix')\gexec

ALTER DATABASE mlflow OWNER TO mlflow;
ALTER DATABASE phoenix OWNER TO phoenix;
REVOKE ALL ON DATABASE mlflow FROM PUBLIC;
REVOKE ALL ON DATABASE phoenix FROM PUBLIC;
