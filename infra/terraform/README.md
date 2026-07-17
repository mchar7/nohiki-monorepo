# OpenTofu Deployment Instructions for Nohiki

This directory contains the OpenTofu configuration for the Azure AKS deployment
path. It provisions Azure infrastructure and installs cluster dependencies.
Application charts are deployed by a GitOps controller, not by this module.

This module supports the AKS deployment path only; `deployment_type` is
validated as `aks`.

## Prerequisites

- Azure account and active subscription.
- Azure CLI installed and logged in with `az login`.
- OpenTofu CLI matching `provider.tf`.
- A domain managed by Azure DNS.
- Container images in a registry that the cluster can pull.
- `bash` or a compatible shell.

## Azure Setup

### Remote State Backend

The remote-state storage account and container, and the GitHub Actions
identity, are created and owned by the bootstrap root at
`infra/terraform/bootstrap`. See its `README.md` for the one-time,
human-authenticated setup and import runbook. Do not create the state storage
from here.

Copy `backend.tfvars.example` to `backend.tfvars`, then set every backend
value. The example enables Microsoft Entra ID authentication so storage account
keys are not written to local configuration. Use a distinct `key` per
environment:

```bash
cp backend.tfvars.example backend.tfvars
tofu init -backend-config=backend.tfvars
```

### Azure DNS Zone

Create or reuse the DNS zone named by `dns_zone_name` in the resource group
named by `dns_zone_resource_group`:

```bash
az group create --name "nohiki-dns-rg" --location "eastus"
az network dns zone create \
  --resource-group "nohiki-dns-rg" \
  --name "nohiki.yourdomain.com"
```

Delegate the zone at your registrar to the Azure DNS name servers.

### Azure Key Vault

Create or reuse the Key Vault named by `kv_name` in the resource group named by
`kv_rg_name`:

```bash
KV_NAME="nohiki-kv"
KV_RG="nohiki-keyvault-rg"
KV_LOCATION="eastus"

az group create --name "$KV_RG" --location "$KV_LOCATION"
az keyvault create \
  --name "$KV_NAME" \
  --resource-group "$KV_RG" \
  --location "$KV_LOCATION" \
  --enable-rbac-authorization
```

Grant your user the Key Vault Secrets Officer role:

```bash
CURRENT_USER_OBJECT_ID="$(az ad signed-in-user show --query id -o tsv)"
KEYVAULT_ID="$(az keyvault show --name "$KV_NAME" --resource-group "$KV_RG" --query id -o tsv)"
az role assignment create \
  --assignee "$CURRENT_USER_OBJECT_ID" \
  --role "Key Vault Secrets Officer" \
  --scope "$KEYVAULT_ID"
```

Set only externally managed secrets before `tofu apply`. OpenTofu generates the
PostgreSQL administrator password and writes it to the Key Vault;
do not create or rotate that secret separately:

```bash
az keyvault secret set \
  --vault-name "$KV_NAME" \
  --name "acme-email" \
  --value "you@example.com"
az keyvault secret set \
  --vault-name "$KV_NAME" \
  --name "jwt-private-key" \
  --value "$(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048)"
az keyvault secret set \
  --vault-name "$KV_NAME" \
  --name "openai-api-key" \
  --value "replace-me"
```

Every AKS environment (dev, staging, prod) syncs its Kubernetes Secrets from
this Key Vault through the External Secrets Operator (owned by the foundation
chart) and the chart-managed `nohiki-secret-store` ClusterSecretStore. Populate
the required Key Vault secrets before the first reconcile; values are never
stored in Git. The full application inventory (name only) is in
`infra/k8s/helm/README.md`. The JWT signing key is `jwt-private-key`, the exact
name every ExternalSecret reads; the older `internal-jwt-secret` name is not
consumed by any workload.

Observability additionally requires `grafana-admin-user`,
`grafana-admin-password`, `grafana-oauth-client-id`,
`grafana-oauth-client-secret`, and `azure-tenant-id`. Its sole
`observability-storage-credentials` ExternalSecret owner reads the
OpenTofu-managed `s3-access-key`, `s3-secret-key`, and `s3-region` objects and
projects the AWS-compatible schema consumed by Mimir, Tempo, Loki, and
Pyroscope. The Azure Blob storage account and the containers named in
`infra/k8s/helm/values.<env>.yaml` must exist before the observability stack
reconciles.

The backend and OpenTofu-managed Key Vault secrets are present in OpenTofu
state. Restrict the state account firewall to trusted deployment runners (or a
private endpoint), grant them only `Storage Blob Data Contributor` on the state
container, and keep blob versioning and soft-delete retention enabled.

## Deploy

From `infra/terraform`, create an environment file:

```bash
cp example.tfvars dev.tfvars
```

Set these values in the file:

- `az_subscription_id`
- `dns_zone_resource_group`
- `dns_zone_name`
- `kv_rg_name`
- `kv_name`
- `app_environment`
- `deployment_type = "aks"`
- `container_registry`

Then run:

```bash
tofu plan -var-file="dev.tfvars" -out=iac-plan-dev
tofu apply "iac-plan-dev"
```

For production, the deploy workflow authenticates to Azure with GitHub OIDC and
passes the externally managed Event Hubs namespace name and resource group from
the production environment variables `PROD_EVENT_HUBS_NAMESPACE_NAME` and
`PROD_EVENT_HUBS_RESOURCE_GROUP_NAME`. It explicitly selects Standard/C/0 Redis.
After apply it exports only OpenTofu's three non-sensitive External Secrets
identity outputs and the non-sensitive `production_network` object, validates
them, and generates `infra/k8s/helm/values.prod.identity.yaml` and
`infra/k8s/helm/values.prod.network.yaml`. One scoped PR promotes both overlays
atomically; do not hand-write or separately promote them. The GitOps controller
(Flux) loads production values in this order: `values.yaml`, `values.prod.yaml`,
`values.prod.identity.yaml`, `values.prod.network.yaml`, then
`values.prod.digests.yaml`; a missing runtime overlay fails rendering.

OpenTofu provisions:

- An Azure resource group for the environment.
- An AKS cluster.
- A public IP and DNS record for the Gateway API entrypoint.
- Cert-Manager and a Let's Encrypt ClusterIssuer via Helm; the existing
  kgateway installation supplies the Gateway API controller.
- KEDA.
- Azure Database for PostgreSQL Flexible Server.
- Azure Cache for Redis or Upstash Redis, depending on variables.
- Azure Blob Storage.
- Identities, role assignments, and Key Vault secret wiring.

The AKS application hostname is
`https://<app_environment>.<dns_zone_name>`.

Application deployment is owned by a GitOps controller (Flux v2) in every
environment. This module provisions cloud infrastructure and cluster add-on
operators only; it does not install or upgrade the Nohiki application chart.

## Manage Environments

Use one `.tfvars` file and one remote-state key per environment. Keep `.tfvars`
files containing environment identifiers or sensitive values out of version control.

For `app_environment = "prod"`, the module rejects fewer than 14 days of
PostgreSQL backup retention, disabled geo-redundant PostgreSQL backups,
non-geo-redundant blob storage, and the Basic Azure Cache for Redis SKU.

GitHub deployment workflows pass the environment file during deployment.

## Destroy

From `infra/terraform`, run:

```bash
tofu destroy -var-file="dev.tfvars"
```

Confirm only after checking that the backend state key and `.tfvars` file both
identify the environment you intend to delete. Resource groups containing
unmanaged resources and soft-deleted Key Vaults are intentionally not purged.

## Troubleshooting

- Azure permissions: the identity running OpenTofu needs rights on the
  subscription or target resource groups.
- Unique names: storage accounts and public DNS names must be globally unique.
- Service quotas: new subscriptions may need quota increases for compute or
  public IPs.
- DNS propagation: DNS records may take time to resolve globally.
- State locks: use `tofu force-unlock <LOCK_ID>` only after confirming no apply
  is still running.
- Helm chart issues: inspect pods with `kubectl get pods -n <namespace>` and
  `kubectl logs <pod-name> -n <namespace>`.
