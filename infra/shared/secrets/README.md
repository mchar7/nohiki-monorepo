# Local Development Secrets

This directory contains secrets for local Compose and k3s development.

## Directory Structure

Secrets are organized to match pydantic-settings nested models and the
`just k8s-secrets` recipe:

```text
secrets/
├── README.md
├── database/
│   ├── host
│   ├── port
│   ├── user
│   ├── password
│   ├── database
│   └── dsn
├── redis/
│   ├── password
│   ├── dsn
│   └── url
├── jwt/
│   ├── private_key
│   └── private_key.pem
├── oauth/
│   ├── github_client_id
│   ├── github_client_secret
│   ├── google_client_id
│   └── google_client_secret
├── email/
│   └── api_key
├── llm/provider/api_keys/
│   ├── openai
│   └── openrouter
├── jsearch/
│   └── api_key
├── kafka/
│   ├── bootstrap_servers
│   └── dsn
├── gcp/
│   └── vertex-key.json
├── qdrant/
│   └── grpc_host
├── s3/
│   ├── rustfs-root.env
│   ├── access_key
│   └── secret_key
├── s3-job-correlation/
│   ├── access_key
│   └── secret_key
├── s3-ml-compute/
│   ├── access_key
│   └── secret_key
└── s3-mlflow/
    ├── access_key
    └── secret_key
```

## Setup

Everything below is generated locally; no value is tracked. Run once:

```bash
cd infra/shared/secrets
umask 077
mkdir -p database redis jwt oauth email llm/provider/api_keys jsearch kafka \
  gcp qdrant s3 s3-job-correlation s3-ml-compute s3-mlflow

# Database (postgres reads the password file at first init)
echo -n "nohiki-infra-postgres" > database/host
echo -n "5432" > database/port
echo -n "postgres" > database/user
DB_PASSWORD="$(openssl rand -hex 24)"
echo -n "$DB_PASSWORD" > database/password
echo -n "nohiki_db" > database/database
echo -n "postgresql+asyncpg://postgres:${DB_PASSWORD}@nohiki-infra-postgres:5432/nohiki_db?sslmode=disable" > database/dsn

# Redis (unauthenticated inside the local compose network)
touch redis/password
echo -n "redis://nohiki-infra-valkey:6379" > redis/dsn
echo -n "redis://nohiki-infra-valkey:6379" > redis/url

# JWT
openssl genrsa -out jwt/private_key 4096
cp jwt/private_key jwt/private_key.pem

# Object store root credentials; compose loads the env file into the RustFS
# server and its init job, services read the file pair
S3_ACCESS_KEY="$(openssl rand -hex 8)"
S3_SECRET_KEY="$(openssl rand -hex 24)"
printf 'RUSTFS_ROOT_USER=%s\nRUSTFS_ROOT_PASSWORD=%s\n' "$S3_ACCESS_KEY" "$S3_SECRET_KEY" > s3/rustfs-root.env
for d in s3 s3-job-correlation s3-ml-compute s3-mlflow; do
  echo -n "$S3_ACCESS_KEY" > "$d/access_key"
  echo -n "$S3_SECRET_KEY" > "$d/secret_key"
done

# Kafka
echo -n "nohiki-cp-kafka:29092" > kafka/bootstrap_servers
echo -n "kafka://nohiki-cp-kafka:29092" > kafka/dsn

# Provider API keys: invalid placeholders keep services booting; paste real
# keys only to exercise those providers, and never commit them
echo -n "sk-placeholder" > llm/provider/api_keys/openai
echo -n "sk-or-placeholder" > llm/provider/api_keys/openrouter
echo -n "re_placeholder" > email/api_key
echo -n "placeholder" > jsearch/api_key

# OAuth, optional
echo -n "" > oauth/github_client_id
echo -n "" > oauth/github_client_secret
echo -n "" > oauth/google_client_id
echo -n "" > oauth/google_client_secret
```

For a local OpenAI-compatible proxy, write its token to `llm/provider/api_keys/openai` and configure its `/v1` endpoint
in `infra/compose/.env`. HTTPS remains the default. If the local proxy is HTTP-only, set
`NOHIKI_ALLOW_HTTP_LLM_LOCAL=1` in that `.env`; preflight accepts the exception only for endpoints whose resolved
addresses are all loopback or RFC1918.

MLflow and Phoenix (`dev` and `observability` profiles) read the database
password from the environment:

```bash
export POSTGRES_PASSWORD="$(cat infra/shared/secrets/database/password)"
```

## How It Works

Docker Compose mounts only the secret directories a service needs. The current
source of truth is `infra/compose/docker-compose.yml`.

```yaml
volumes:
  - ../shared/secrets/database:/run/secrets/database:ro
  - ../shared/secrets/redis:/run/secrets/redis:ro
  - ../shared/secrets/email:/run/secrets/email:ro
```

pydantic-settings reads these files directly:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(secrets_dir="/run/secrets/database")

    host: str
    port: int = 5432
    user: str
    password: str
    database: str
```

## Protected Mirror

The files remain real files in the primary worktree because the local secret
validator deliberately rejects symlinked path components. The pre-push gate
refreshes an owner-only mirror in
`$XDG_STATE_HOME/nohiki-secrets-mirror/`, outside every Git worktree and on the
Snapper-covered persistent home subvolume. When `XDG_STATE_HOME` is unset, it
uses the standard dot-local `state/` directory under `$HOME`. It refuses to
refresh from a sparse or incomplete primary worktree.

Restore the worktree copy from the mirror without replacing this README:

```bash
state_home="${XDG_STATE_HOME:-$(printf '%s/%s/%s' "$HOME" .local state)}"
rsync -a --delete --exclude=README.md --exclude=.last-refresh \
  "$state_home/nohiki-secrets-mirror/" infra/shared/secrets/
```

Run `scripts/dev/secrets-mirror.sh` to check the sparse-checkout tripwire and
refresh the mirror immediately. The command reports only a file count, never
secret filenames or contents.

## Security Notes

- Do not commit actual secret values. The `.gitignore` prevents this.
- Only this README is tracked; every other file in this directory is gitignored.
- Services mount secrets read-only.

## Troubleshooting

### Secrets not found

```bash
# from the repo root
ls -la infra/shared/secrets/database/

# verify permissions without reading secret contents
stat -c '%a %n' infra/shared/secrets/database/password

# validate the complete host-side secret contract
sh infra/compose/scripts/preflight.sh
```

### Permission denied

Keep secret directories private to the current user:

```bash
find infra/shared/secrets -type d -exec chmod 700 {} +
find infra/shared/secrets -type f ! -name README.md ! -name .gitkeep -exec chmod 600 {} +
```
