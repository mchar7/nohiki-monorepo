# Bootstrap: remote state and GitHub Actions identity

This root owns the objects that must exist before any environment stack can run:

- The remote-state resource group, storage account, and blob container.
- The Entra application and service principal GitHub Actions authenticates as.
- The federated identity credentials for the default branch and each GitHub
  environment.
- The Contributor role assignment at the deployment scope and the Storage Blob
  Data Contributor grant on the state container.

It replaces the former imperative OIDC setup shell script. The
environment stacks in `infra/terraform` consume the outputs of this root as
GitHub Actions secrets and variables; this root never manages any environment
resource, and no environment state manages any resource here.

## First apply is human authenticated

The service principal this root creates cannot authenticate its own creation,
and no workflow runs bootstrap. A human with Owner or User Access Administrator
on the subscription runs `az login` and drives every step below. This boundary
is unavoidable and by design.

Do not commit `bootstrap.tfvars`, `bootstrap.backend.tfvars`, or any object GUID
or credential. Populate GitHub secrets and variables with the `gh` CLI from
`tofu output`, never by pasting values into tracked files.

## Greenfield pre-init: create the state storage

Skip this section when the state storage already exists; import it instead (see
below). For a brand new subscription, create the three objects by hand once,
because the backend cannot initialize without a container to hold its state:

```bash
TF_STATE_RG="nohiki-tfstate-rg"
TF_STATE_LOCATION="eastus"
TF_STATE_STORAGE_ACCOUNT="nohikitfstate$(openssl rand -hex 4)"
TF_STATE_CONTAINER="tfstate"

az group create --name "$TF_STATE_RG" --location "$TF_STATE_LOCATION"
az storage account create \
  --name "$TF_STATE_STORAGE_ACCOUNT" \
  --resource-group "$TF_STATE_RG" \
  --location "$TF_STATE_LOCATION" \
  --sku Standard_GRS \
  --kind StorageV2 \
  --https-only true \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --allow-shared-key-access false
az storage container create \
  --account-name "$TF_STATE_STORAGE_ACCOUNT" \
  --name "$TF_STATE_CONTAINER" \
  --auth-mode login
az storage account blob-service-properties update \
  --account-name "$TF_STATE_STORAGE_ACCOUNT" \
  --enable-versioning true \
  --enable-delete-retention true \
  --delete-retention-days 14 \
  --enable-container-delete-retention true \
  --enable-container-delete-retention true \
  --container-delete-retention-days 14 \
  --auth-mode login
```

## Initialize the backend

`backend.tf` is a partial configuration. Write `bootstrap.backend.tfvars` with
the state location and the key `nohiki/bootstrap.tfstate`, which keeps this root
separate from every environment state in the same account and container:

```hcl
subscription_id      = "<your-azure-subscription-id>"
resource_group_name  = "<your-state-resource-group>"
storage_account_name = "<your-state-storage-account>"
container_name       = "tfstate"
key                  = "nohiki/bootstrap.tfstate"
use_azuread_auth     = true
```

```bash
tofu init -backend-config=bootstrap.backend.tfvars
```

Set the module inputs in `bootstrap.tfvars`, using values that match the live
objects exactly so they import cleanly:

```hcl
az_subscription_id         = "<subscription-guid>"
az_location                = "eastus"
github_repository          = "<owner>/<repo>"
github_default_branch      = "main"
github_environments        = ["dev", "staging", "prod"]
app_display_name           = "<live-entra-application-display-name>"
deployment_scope           = "<live-contributor-scope>"
state_resource_group_name  = "nohiki-tfstate-rg"
state_storage_account_name = "<live-state-storage-account>"
state_container_name       = "tfstate"
```

## Import existing resources

When migrating an existing subscription, import every resource before the first
apply so nothing is duplicated. Entra display names are not unique, so a second
apply without imports would create a parallel application. Discover the live ids
first (read only):

```bash
APP_ID=$(az ad app list --display-name "$APP_NAME" --query '[0].appId' -o tsv)
APP_OBJ=$(az ad app show --id "$APP_ID" --query id -o tsv)
SP_OBJ=$(az ad sp show --id "$APP_ID" --query id -o tsv)
SUB="$AZURE_SUBSCRIPTION_ID"
```

Import the identity objects:

```bash
tofu import azuread_application.github_actions "/applications/$APP_OBJ"
tofu import azuread_service_principal.github_actions "/servicePrincipals/$SP_OBJ"

for N in main-branch dev-environment staging-environment prod-environment; do
  FIC_ID=$(az ad app federated-credential list --id "$APP_ID" \
    --query "[?name=='$N'].id | [0]" -o tsv)
  tofu import "azuread_application_federated_identity_credential.github[\"$N\"]" \
    "/applications/$APP_OBJ/federatedIdentityCredentials/$FIC_ID"
done
```

Import the state storage:

```bash
tofu import azurerm_resource_group.state \
  "/subscriptions/$SUB/resourceGroups/$TF_STATE_RESOURCE_GROUP"
tofu import azurerm_storage_account.state \
  "/subscriptions/$SUB/resourceGroups/$TF_STATE_RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$TF_STATE_STORAGE_ACCOUNT"
tofu import azurerm_storage_container.state \
  "/subscriptions/$SUB/resourceGroups/$TF_STATE_RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$TF_STATE_STORAGE_ACCOUNT/blobServices/default/containers/$TF_STATE_CONTAINER"
```

Import the role assignments by their own assignment ids:

```bash
RA_ID=$(az role assignment list --assignee "$SP_OBJ" --role Contributor \
  --scope "$ROLE_SCOPE" --query '[0].id' -o tsv)
tofu import azurerm_role_assignment.deploy_contributor "$RA_ID"

BLOB_RA=$(az role assignment list --assignee "$SP_OBJ" \
  --role 'Storage Blob Data Contributor' --query '[0].id' -o tsv)
```

Import the blob grant only when a live grant exists at the container scope this
root models. If the live grant sits at a broader scope, let the apply create the
narrow container-scoped grant, then remove the broad one by hand afterward:

```bash
tofu import azurerm_role_assignment.state_blob_contributor "$BLOB_RA"
```

## Plan gate

After importing, run the plan and confirm it does not create or destroy any
imported resource:

```bash
tofu plan -var-file=bootstrap.tfvars
```

For a migration the plan must report `0 to add, 0 to destroy` for the imported
resources. The only permitted create is `state_blob_contributor` when no live
grant existed at the container scope. Reviewable in-place attribute diffs on the
imported storage account are expected; align the configuration to reality rather
than letting an apply mutate the state account. Never proceed past a plan that
would destroy or recreate an identity or state resource.

## Apply and populate GitHub

```bash
tofu apply -var-file=bootstrap.tfvars
tofu output github_actions_secrets
tofu output github_actions_variables
```

Create the GitHub environments and set the repository secrets and variables from
the outputs. These commands read values at runtime; no GUID or credential is
written to a tracked file:

```bash
for ENV in dev staging prod; do
  gh api -X PUT "repos/<owner>/<repo>/environments/$ENV" >/dev/null
done

gh secret set AZURE_CLIENT_ID       --body "$(tofu output -raw -json github_actions_secrets | jq -r .AZURE_CLIENT_ID)"
gh secret set AZURE_TENANT_ID       --body "$(tofu output -raw -json github_actions_secrets | jq -r .AZURE_TENANT_ID)"
gh secret set AZURE_SUBSCRIPTION_ID --body "$(tofu output -raw -json github_actions_secrets | jq -r .AZURE_SUBSCRIPTION_ID)"

gh variable set TF_STATE_RESOURCE_GROUP --body "$(tofu output -json github_actions_variables | jq -r .TF_STATE_RESOURCE_GROUP)"
gh variable set TF_STATE_STORAGE_ACCOUNT --body "$(tofu output -json github_actions_variables | jq -r .TF_STATE_STORAGE_ACCOUNT)"
gh variable set TF_STATE_CONTAINER       --body "$(tofu output -json github_actions_variables | jq -r .TF_STATE_CONTAINER)"
```

`AZURE_CONTAINER_REGISTRY` and `ACR_RESOURCE_GROUP_NAME` reference the externally
managed registry and remain operator set. GitHub population stays a `gh` CLI
step on purpose: no GitHub provider is added, so no state holds a GitHub token.

## Verify workflow OIDC

Dispatch a dev plan run of a CD workflow. The `azure/login` step, `tofu init`
with `use_azuread_auth`, and the plan must all succeed under the identity this
root owns. That proves the federated subjects, the Contributor scope, and state
blob access before the old script is removed.

## Rollback

Every resource here is imported or a single narrow role assignment. To roll
back, run `tofu state rm` for each address; the live objects are untouched.
Reverting the commit that added this root leaves the imported objects in place.

## Break glass

This root is the replacement for the removed shell bootstrap. If GitHub Actions
loses Azure access, a human runs `az login` and reruns the plan gate and apply
here to reconcile the identity and role assignments. Broader subscription and
role-administration grants are deliberately absent: the GitHub principal can
deploy at the deployment scope and read and write state blobs, but can never
mutate the identity objects this root owns.
