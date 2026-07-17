# GitOps deployment

Per-cluster, pull-based delivery of the Nohiki platform. A GitOps engine runs in
the cluster, watches this repository, and reconciles three stacks in dependency
order. Continuous delivery never holds write credentials to a cluster; promotion
is a reviewed Git change.

The engine is [Flux v2](https://fluxcd.io). Installation and cluster
self-management use the upstream, idempotent `flux bootstrap github` command, so
the engine install, the deploy key, and the per-cluster sync configuration are
owned by Flux rather than by vendored manifests. The user-facing recipes stay
`gitops-*`.

## Layout

```text
gitops/
  install/
    bootstrap.sh           Wraps `flux bootstrap github`: creates the read-only
                           deploy key, installs the controllers, and reconciles
                           the selected cluster; also seeds the runtime ConfigMap
  clusters/
    local/                 In-cluster k3s (namespace nohiki)
    dev-aks/               GPU-less AKS (namespace nohiki-dev)
    staging-aks/           AKS (namespace nohiki-staging)
    prod-aks/              AKS (namespace nohiki-prod): release-source.yaml plus
                           commit-pinned, suspended stacks
  infrastructure/          Foundation HelmRelease (Gateway API CRDs, kgateway, CloudNativePG)
    base/ local/ dev/ staging/ prod/
  platform/                Umbrella HelmRelease (operators, data stores, services, jobs)
    base/ local/ dev/ staging/ prod/
```

Each `clusters/<cluster>` directory holds the three stack Kustomizations as flat
manifests (plus, for production, the commit-pinned `gitops-release` source).
`flux bootstrap` generates and commits the `clusters/<cluster>/flux-system`
sync manifests (`gotk-components.yaml`, `gotk-sync.yaml`, `kustomization.yaml`)
into the repository at first bootstrap; those files are Flux-owned and are not
committed by hand. The `observability` stack points directly at the existing
`infra/k8s/observability/overlays/<env>` Kustomize overlays; no manifests are
duplicated here.

## Stacks and dependency order

```text
infrastructure  ->  platform  ->  observability
```

- `infrastructure` reconciles the `nohiki-foundation` HelmRelease from
  `infra/k8s/helm-foundation`: the pinned Gateway API standard CRDs, kgateway,
  and the CloudNativePG operator. It waits for the release to be ready.
- `platform` (depends on `infrastructure`) reconciles the `nohiki` HelmRelease
  from `infra/k8s/helm`: the CloudNativePG cluster, Kafka, the application
  services, and their jobs.
- `observability` (depends on `platform`) reconciles Grafana, OpenTelemetry,
  and External Secrets custom resources; External Secrets Operator and its CRDs
  are installed by the foundation chart, before these resources reconcile.

Both HelmReleases build the chart from the Git source path with
`reconcileStrategy: Revision`, so every repository revision rebuilds the chart
even when the chart version is unchanged. They enable drift detection and retry
remediation. The platform install does not wait (`install.disableWait: true`)
because a fresh install converges through database migration hooks; upgrades do
wait so migrations gate the rollout.

Helm `valuesFiles` are resolved from the GitRepository root, so every entry is
written repo-root-relative (for example `infra/k8s/helm/values.yaml`), not
relative to the chart path.

## Environments

| Cluster       | Control source | Stacks source    | Revision          | Namespace        | Chart values |
|---------------|----------------|------------------|-------------------|------------------|--------------|
| `local`       | `flux-system`  | `flux-system`    | branch `main`     | `nohiki`         | `infra/k8s/helm/values.yaml`, `values.local.yaml` |
| `dev-aks`     | `flux-system`  | `flux-system`    | branch `main`     | `nohiki-dev`     | `infra/k8s/helm/values.yaml`, `values.dev.yaml` |
| `staging-aks` | `flux-system`  | `flux-system`    | branch `main`     | `nohiki-staging` | `infra/k8s/helm/values.yaml`, `values.staging.yaml` |
| `prod-aks`    | `flux-system`  | `gitops-release` | commit (pinned)   | `nohiki-prod`    | `infra/k8s/helm/values.yaml`, `values.prod.yaml`, `values.prod.identity.yaml`, `values.prod.network.yaml`, `values.prod.digests.yaml` |

`flux-system` is the branch-tracking GitRepository and Kustomization that
`flux bootstrap` creates. It is the self-managing control root: a merged change
under `clusters/<cluster>` reconciles into the cluster on the next interval, so
source and stack fields update without a re-bootstrap.

Local uses the contributor registry from `values.local.yaml` and the stable
`dev` image tag (a fixed tag name that is repushed in place, not an immutable
digest), with pre-created local secrets. Dev and staging track the default
branch through `flux-system`.

Production keeps the branch-tracking `flux-system` control root but sources its
stacks from a distinct, commit-pinned `gitops-release` GitRepository. The
committed `gitops-release` carries `ref.commit: PROMOTION_REQUIRED` and every
production stack is `suspend: true`. The activation change stamps the commit to
the reviewed release SHA and flips the stacks to `suspend: false`; the control
root observes that merged change and applies it, so the release source and
suspend fields converge automatically. Until then the placeholder keeps
`gitops-release` NotReady and the stacks suspended.

## Runtime coordinates

Non-secret runtime coordinates that vary per fork or per environment enter Flux
through the `gitops-runtime` ConfigMap in `flux-system`, which `bootstrap.sh`
creates or updates, and through native `postBuild.substituteFrom` on the
dev and staging platform Kustomizations. Dev and staging override the global
image coordinates (`registry`, `owner`, `repositoryName`, `imageTag`) and the
`global.eso.azure` values (`clientId`, `tenantId`, `keyVaultUrl`) this way, so a
runtime override survives every self-reconcile instead of being replaced by a
committed default. Local uses the committed `values.local.yaml` registry and the
chart defaults; production uses the committed identity, network, and digest
overlays. None of these coordinates is a secret.

## Local prerequisites

The local cluster pulls first-party images from the contributor registry at
`localhost:5000` declared in `values.local.yaml`. k3s must run directly on the
native host, not inside a VM or a nested container, so the cluster nodes and
pods resolve `localhost:5000` as the host loopback and pull the pushed images. A
nested or VM-hosted k3s cannot reach the host loopback registry without extra
network plumbing, and image pulls fail.

## Runbook

Bring up the local stack in one step:

```bash
just k8s-reconcile-local
```

Individual recipes:

```bash
just gitops-bootstrap       # flux bootstrap github for the selected cluster
just gitops-wait            # wait for the source, stacks, and platform workloads
just gitops-rollout-local   # restart first-party Deployments to pull the repushed local tag
just gitops-status          # source, stacks, and releases at a glance
just gitops-logs            # follow the reconciler logs
just gitops-full            # bootstrap + wait + status
```

Bootstrap uses the upstream `flux bootstrap github`, so it is idempotent: re-run
it to upgrade the controllers or reconcile drift. The command creates or updates
the read-only cluster deploy key, commits the generated `flux-system` sync files
to the selected branch, installs the controllers, and waits for reconciliation.
Its `GITHUB_TOKEN` is used for those GitHub operations only and is never written
to Git, a manifest, or the cluster.

For the dev deployment workflow, create a fine-grained personal access token in
GitHub under **Settings → Developer settings → Personal access tokens →
Fine-grained tokens** and save it as the repository Actions secret
`FLUX_GITHUB_TOKEN`. Scope the token to **only this repository**. Its minimal
repository permissions are **Administration: Read and write** (manage the
read-only deploy key) and **Contents: Read and write** (read the repository and
commit the generated sync files); GitHub adds **Metadata: Read-only**
automatically. Do not grant organization-wide repository access or unrelated
permissions. Choose the shortest practical expiration, rotate the Actions secret
before expiry, and revoke superseded tokens immediately. If bootstrap is not run
continuously, revoke the token after bootstrap and create a new short-lived token
for the next controller upgrade or drift reconciliation. A missing secret fails
the workflow before Flux runs.

```bash
GITHUB_TOKEN=<short-lived-pat> \
  NOHIKI_CLUSTER=local \
  GITOPS_GITHUB_OWNER=<owner> \
  GITOPS_GITHUB_REPOSITORY=nohiki-monorepo \
  GITOPS_GITHUB_BRANCH=main \
  GITOPS_GITHUB_PERSONAL=true \
  just gitops-bootstrap
```

`GITOPS_GITHUB_PERSONAL` is required and explicit: `true` for a personal account,
`false` for an organization. Dev and staging additionally require the non-secret
image and ESO runtime coordinates (`NOHIKI_IMAGE_REGISTRY`, `NOHIKI_IMAGE_OWNER`,
`NOHIKI_IMAGE_REPOSITORY`, `NOHIKI_IMAGE_TAG`, `NOHIKI_ESO_CLIENT_ID`,
`NOHIKI_ESO_TENANT_ID`, `NOHIKI_ESO_VAULT_URL`); a missing value fails the
bootstrap closed.

A fork bootstraps against its own repository by passing its own
`GITOPS_GITHUB_OWNER`, `GITOPS_GITHUB_REPOSITORY`, and `GITOPS_GITHUB_BRANCH`.
Flux commits the sync configuration to that fork and branch, so self-reconcile
stays consistent with wherever the cluster was bootstrapped, with no tracked-file
edit.

Reset the local stack (the Flux engine in `flux-system` is preserved):

```bash
just k8s-reset-local --confirm
```

The reset suspends the self-managing `flux-system` Kustomization first so it
cannot re-apply the stacks, then deletes the stacks in reverse dependency order
so each Kustomization's finalizer prunes its managed workloads, then deletes the
application namespaces. It requires the current context to equal
`K8S_LOCAL_CONTEXT` and never deletes the `flux-system` namespace, so a
re-bootstrap resumes the suspended control root.

## Ownership boundary

OpenTofu owns the cloud account and cluster add-ons; the GitOps engine owns
application, foundation, and observability reconciliation. The engine itself is
installed and kept current by `flux bootstrap`, which pins the controllers to the
flake-pinned Flux CLI version and is idempotent and self-updating on re-run.
