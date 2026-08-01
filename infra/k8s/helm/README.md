# Nohiki Umbrella Helm Chart

This chart deploys the Nohiki application and in-cluster dependencies to
Kubernetes.

## Prerequisites

- Kubernetes cluster with Gateway API support.
- Helm installed and configured.
- Container images for first-party services in a reachable registry.
- External Secrets Operator and CRDs, installed by the foundation chart
  (`infra/k8s/helm-foundation`), when `global.eso.externalSecretsEnabled` is true.
- Strimzi when Kafka resources are enabled.

OpenTofu provisions the AKS cluster and cloud add-ons; Flux reconciles this
chart onto it. Local k3s uses the `just k8s-*` recipes from the repo root.

## Chart Structure

First-party service charts live in `charts/`:

- `user-auth-service`
- `user-pref-service`
- `user-upload-service`
- `user-entitlement-service`
- `job-ingest-discovery-service`
- `job-ingest-schedule-service`
- `job-query-composition-service`
- `job-ingest-enrichment-service`
- `job-storage-service`
- `job-correlation-evaluation-service`
- `doc-template-service`
- `doc-content-service`
- `doc-process-service`
- `ml-gateway-service`
- `ml-compute-service`
- `skill-graph-service`
- `bff-service`
- `notification-service`

Shared and infrastructure charts include `nohiki-common`, `docling-serve`,
`rustfs`, Strimzi, Valkey, Qdrant, Gotenberg, and the observability stack. The
External Secrets Operator and its CRDs are owned by the foundation chart, not
this umbrella.

Top-level templates create the Gateway API resources, Kafka resources,
CloudNativePG resources, migration jobs, ExternalSecrets, Kafka Connect
resources, and bootstrap jobs.

## Local Deployment

Deployment is **declarative via Flux**. The platform chart is rendered and
reconciled by the platform stack; the cluster foundation (Gateway API,
kgateway, the CloudNativePG operator) by the infrastructure stack. From the
repo root:

```bash
just k8s-reconcile-local   # check context, build + push images, then Flux owns the rest
# or, against a running cluster with images already pushed:
just gitops-full
```

The workstation public origins are `http://nohiki.localhost:8080` for the UI
and API and `http://s3.nohiki.localhost:8080` for browser-facing S3 requests.
Both hosts traverse the Gateway; application services continue to use
in-cluster Service DNS.

An engineer authors local Secret ciphertext before bootstrap. The application
provisioner reads the external source directory once, generates the per-service
database and local-only credentials in a private temporary directory, and
encrypts the result to the public Age recipient in `.sops.yaml`. It never needs
the private Age identity:

```bash
: "${NOHIKI_LOCAL_SECRETS_DIR:?set an absolute private source directory}"
case "$NOHIKI_LOCAL_SECRETS_DIR" in
  /*) ;;
  *) printf '%s\n' 'NOHIKI_LOCAL_SECRETS_DIR must be absolute' >&2; exit 2 ;;
esac
uv run python scripts/infra/provision_local_app_secrets.py \
  --source-dir "$NOHIKI_LOCAL_SECRETS_DIR" \
  --output infra/k8s/gitops/secrets/local/nohiki-app-secrets.sops.yaml \
  --sops-config .sops.yaml
uv run python scripts/infra/provision_local_runtime_secrets.py \
  --source-dir "$NOHIKI_LOCAL_SECRETS_DIR" \
  --output infra/k8s/gitops/secrets/local/nohiki-llm-runtime.sops.yaml \
  --sops-config .sops.yaml
uv run python scripts/infra/provision_local_tls_source.py \
  --output infra/k8s/gitops/secrets/local/nohiki-model-egress-tls-source.sops.yaml
```

Review only manifest metadata, Secret names, key names, and SOPS status. Do not
decrypt or print values. Commit all three freshly authored ciphertext files.
Before a pristine bootstrap, validate the source permissions, all three
encrypted inventories, the Age identity, and the Flux owner graph without
changing the cluster:

```bash
uv run python scripts/infra/validate_local_secret_sources.py \
  --secrets-dir "$NOHIKI_LOCAL_SECRETS_DIR" \
  --age-key-file "$SOPS_AGE_KEY_FILE"
sops filestatus infra/k8s/gitops/secrets/local/nohiki-app-secrets.sops.yaml
sops filestatus infra/k8s/gitops/secrets/local/nohiki-model-egress-tls-source.sops.yaml
sops filestatus infra/k8s/gitops/secrets/local/nohiki-llm-runtime.sops.yaml
kubectl kustomize infra/k8s/gitops/secrets/local >/dev/null
```

Bootstrap applies only the `flux-system/flux-sops` trust root. Flux decrypts the
tracked sources and owns every local application Secret; Helm inline Secrets and
local ESO duplicates remain disabled.

To render the chart locally for inspection (never as an install path):

```bash
helm dependency build infra/k8s/helm
helm template nohiki infra/k8s/helm -f infra/k8s/helm/values.local.yaml
```

Platform ExternalSecret targets in dev/staging/prod are every enabled
`<service>-db-credentials`, the shared application targets
`nohiki-redis-credentials`, `nohiki-jwt-keys`, `nohiki-oauth-credentials`,
`nohiki-email-api-keys`, `nohiki-jsearch-api-keys`, `nohiki-s3-credentials`,
`qdrant-api-key`, `auth-listings-secret`, and `kafka-sasl-credentials`, plus TLS,
CA, and only the model-provider targets declared by
`global.modelEgress.providerCredentials`. Local values emit OpenAI and
OpenRouter targets; the disabled local `messages` backend emits no Anthropic
route, runtime key, ExternalSecret, or health gate. Managed environments retain
Anthropic while that backend and its source remain enabled. Per-purpose client
credentials are generated in-cluster and authorize only their declared gateway
routes; Kubernetes workloads never receive provider credentials directly.

The generated client credentials are limited to the routes declared in
`global.modelEgress.clients[].allowedRoutes`. `doc-content-service` and
`job-ingest-enrichment-service` may call only `responses`; no workload credential
matches the strict `completions` selector, and local values disable the unused
`messages` backend. The `responses` route dispatches only to the native OpenAI
backend at `api.openai.com:443`; its
OpenRouter provider entry is disabled, so these model identifiers cannot drift
to a different upstream or fallback provider. The deployed model policy is
`openai:gpt-5.6-luna` for enrichment, extraction, and skill
clarification, and `openai:gpt-5.6-sol` for document tailoring. Correlation uses
the stage-3 reranker directly and has no LLM client credential or model-egress
CA mount.

Key Vault secret names are: `database-host`, `database-port`, `database-user`,
`database-password`, service database and DSN names, `redis-dsn`,
`jwt-private-key`, `oauth-github-client-id`, `oauth-github-client-secret`,
`oauth-google-client-id`, `oauth-google-client-secret`, the five
`model-egress-*` credential/TLS keys declared in `values.<env>.yaml`,
`resend-api-key`, `jsearch-api-key`, `s3-access-key`, `s3-secret-key`,
`s3-region`, `qdrant-api-key`, `auth-listings-secret`,
`kafka-sasl-username`, `kafka-sasl-password`, and `kafka-sasl-mechanism`.
This inventory contains names only; never record values in Git.

The `nohiki-observability` overlays own managed-environment storage and Grafana
ExternalSecrets. Local Flux instead owns `observability-storage-credentials` in
`nohiki-app-secrets.sops.yaml`; the provisioner copies the same external S3
access and secret values used by `nohiki-s3-credentials` and
`nohiki-rustfs-credentials`, with the exact `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, and `AWS_REGION` keys consumed by Loki, Mimir, Tempo,
and Pyroscope. Local Grafana uses anonymous Viewer access, so the local overlay
does not emit or consume a Grafana administrator credential.

## Configuration

The base file is `values.yaml`. Environment overlays are
`values.local.yaml`, `values.staging.yaml`, and `values.prod.yaml`.

Key global values:

| Parameter | Purpose | Default |
| --- | --- | --- |
| `global.nohikiImage.registry` | First-party container registry hostname. | empty |
| `global.nohikiImage.owner` | First-party registry owner or organization. | empty |
| `global.nohikiImage.repositoryName` | First-party registry repository name. | empty |
| `global.imageTag` | Shared image tag for first-party services. | `latest` |
| `global.environment` | Deployment environment. | `dev` |
| `global.ingress.enabled` | Create Gateway API entrypoint. | `true` |
| `global.ingress.gatewayClass` | GatewayClass name. | `kgateway` |
| `global.ingress.host` | Public hostname. | `nohiki.localhost` |

Each service has a top-level values section with `enabled`, database, scaling,
resources, and service-specific overrides.

## Upgrade

Upgrades are declarative and promoted through Git. The CD pipeline commits the
built image reference (a `sha-<commit>` tag) for the target environment and Flux
reconciles the platform HelmRelease to it; there is no imperative retag or
`helm upgrade`. Non-secret cloud and registry coordinates reach the cluster
through the Flux bootstrap ConfigMap and Kustomization postBuild substitution,
not through tracked defaults in these values files. For a local cluster, re-run
`just k8s-reconcile-local` to rebuild, push, and reconcile.
