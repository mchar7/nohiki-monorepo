# Auth Listings Worker Operations

Operational notes for `typescript/edge/auth-listings-worker/` and the BFF route
`/api/v1/auth-listings`.

The Worker serves the public auth-page listings request. It applies CORS and edge behavior, then
sends the request to the BFF with `X-Auth-Listings-Secret`. The BFF validates that header before
running the auth-listings pipeline.

```text
Browser -> Cloudflare Worker -> BFF /api/v1/auth-listings
             |                    |
             | adds secret header | validates secret header
             | sends OTLP traces  | owns route rate limit
```

## Secret source

Secret name: `auth-listings-secret`

- Azure Key Vault key: `auth-listings-secret`
- Kubernetes Secret: `auth-listings-secret`, key `secret`
- BFF env var: `BFF_AUTH_LISTINGS__SECRET`
- Worker secret: `AUTH_LISTINGS_SECRET`

The Kubernetes Secret is reconciled by
`infra/k8s/helm/templates/auth-listings-external-secret.yaml`. The Worker secret must be pushed
with Wrangler from the same Key Vault value.

## Rotate the secret

Rotate the BFF and Worker copies together.

```bash
NEW_SECRET=$(openssl rand -hex 32)
az keyvault secret set \
  --vault-name <vault> \
  --name auth-listings-secret \
  --value "$NEW_SECRET"
```

Push the same value to each Worker environment:

```bash
printf '%s' "$NEW_SECRET" | wrangler secret put AUTH_LISTINGS_SECRET --env staging
printf '%s' "$NEW_SECRET" | wrangler secret put AUTH_LISTINGS_SECRET --env production
```

Wait for External Secrets to refresh, or force a sync:

```bash
kubectl annotate externalsecret auth-listings-secret \
  force-sync=$(date +%s) --overwrite -n <namespace>
```

Restart the BFF so it reads the new Kubernetes Secret:

```bash
kubectl rollout restart deploy/<release>-bff-service -n <namespace>
```

Run the Worker secret update and BFF restart back-to-back. Requests return `403` while the two
copies disagree.

## Local development

The Worker config lives in `wrangler.toml`.

Default `wrangler dev` values:

- `BFF_ORIGIN=http://localhost:8000`
- `ALLOWED_ORIGINS=http://localhost:5173`
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces`

Set local secrets in `.dev.vars`. Use `.dev.vars.example` as the template.

Docker Compose sets the BFF default secret with
`BFF_AUTH_LISTINGS__SECRET=${BFF_AUTH_LISTINGS__SECRET:-dev-test-secret-qa-only}`. Override it in
your shell before starting compose when you need a different local value.

For k3s local runs, use the `k3s` Wrangler environment:

```bash
wrangler dev --env k3s
```

That environment points the Worker at `http://nohiki.localhost:8080` and sends OTLP traces to
`http://nohiki.localhost:8080/v1/traces`.

## Deploy

Deploy the platform first (the GitOps engine reconciles the BFF and its ExternalSecret), then
deploy the Worker.

```bash
just gitops-full
wrangler deploy --env staging
```

Production uses the `production` Wrangler environment:

```bash
wrangler deploy --env production
```

## Observability

Dashboard source:

- JSON: `infra/shared/dashboards/auth-listings-worker.json`
- Rendered CRD:
  `infra/k8s/observability/base/grafana/dashboards/auth-listings-worker.yaml`

Regenerate rendered dashboard manifests with:

```bash
just generate-dashboard-crds
```

Worker trace export endpoints:

- Compose: `http://localhost:4318/v1/traces`
- k3s local: `http://nohiki.localhost:8080/v1/traces`

The local stack does not require `OTEL_EXPORTER_AUTH_TOKEN`. Leave it unset unless the target
collector requires it.

Dashboard panels that split by `cache_status` or `country` need those span attributes promoted in
Tempo span metrics. Add the dimensions under `tempo-distributed` in the Helm values for the target
environment:

```yaml
tempo-distributed:
  tempo:
    structuredConfig:
      metrics_generator:
        processor:
          span_metrics:
            dimensions:
              - cache_status
              - country
```

The BFF rate-limit panel reads `nohiki_http_server_request_count_total` filtered to
`http_response_status_code="429"` on `/api/v1/auth-listings`.

## Failure modes

### BFF returns 403

Worker and BFF secrets differ, or one side has no secret. Push the Worker secret and restart the
BFF from the same Key Vault value.

### Worker returns 500 with `fetch failed`

`BFF_ORIGIN` is wrong or unreachable. Check the active Wrangler environment and the gateway route.

### Dashboard panels are empty

Check that the Worker emits traces, Tempo span metrics are enabled, and `cache_status` plus
`country` are promoted as span-metric dimensions.

### BFF 429 panel is empty

No recent request hit the route limit, or the route label differs. Check
`nohiki_http_server_request_count_total` labels in Mimir.

### ExternalSecret is `NotReady`

The Key Vault key is missing or workload identity cannot read it.

```bash
kubectl describe externalsecret auth-listings-secret -n <namespace>
```
