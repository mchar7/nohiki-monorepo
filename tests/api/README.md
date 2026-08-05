# API Contract Tests

This directory contains **API contract tests** that verify the BFF REST API
behaves correctly. These are NOT browser-based E2E tests.

For browser E2E tests, see `typescript/apps/frontend/e2e/`.

## Test Categories

- **Auth API** (`test_user_flows.py`) - Registration, login, logout, session
- **Profile API** (`test_user_flows.py`) - Profile CRUD operations
- **Listing API** (`test_listings_flows.py`) - Job listing queries

## Running Tests

```bash
# All API tests
just test-api

# Specific test file
uv run --package nohiki-integration-tests pytest tests/api/test_user_flows.py --tb=short

# Kubernetes API tests through the deployed Gateway (required values shown)
K8S_GATEWAY_URL="https://gateway.example" K8S_NAMESPACE="nohiki" just k8s-test

# With coverage
just test-api-cov
```

## Fixture Strategy

Tests use **session-scoped fixtures** to minimize redundant operations:

- **`session_client`** - Authenticated client, one user per test session
- **`session_profile`** - Test profile, created once per session
- **`fresh_client`** - Unauthenticated client for auth flow tests
- **`authenticated_client`** - Alias for session_client (backward compatibility)

The session user credentials are fixed:

- Email: `e2e-session-user@example.com`
- Password: `SessionUserP@ss123!`

This user is created once and reused. If it already exists from a previous
run, the fixture logs in instead of registering.

## Environment Variables

### Optional Configuration

```bash
export E2E_BASE_URL="http://localhost:8000"
export E2E_ORIGIN="http://localhost:5173"
export E2E_DEPLOYMENT_TIMEOUT="300"
export E2E_WORKFLOW_TIMEOUT="180"
```

`E2E_ORIGIN` is the browser origin sent on cookie-authenticated mutations. It must match an origin
allowed by the deployed BFF and auth services.

For `just k8s-test`, `K8S_GATEWAY_URL` and `K8S_NAMESPACE` identify the deployed public Gateway
and namespace. `K8S_RELEASE` defaults to `nohiki`. The Gateway hostname must resolve through
system DNS or `/etc/hosts` to an address reported in Gateway status. The recipe sets
`NOHIKI_GATEWAY_URL` and `E2E_BASE_URL` to the required Gateway URL.

### For Full LLM Testing

```bash
export OPENAI_API_KEY_E2E="your-e2e-openai-key"
export OPENROUTER_API_KEY_E2E="your-e2e-openrouter-key"
```

## Prerequisites

Local Compose API tests require the Docker Compose stack. Kubernetes Gateway tests require a fresh,
converged cluster deployment and its public origin:

```bash
# Local Compose tests (run from the repository root)
just compose-up

# Fresh Kubernetes Gateway tests
K8S_GATEWAY_URL="https://gateway.example" K8S_NAMESPACE="nohiki" just k8s-test
```

## Cost Optimization

The session-scoped fixtures significantly reduce test costs:

| Metric | Before | After |
| -------- | -------- | ------- |
| Users created per run | 50+ | 1-2 |
| Kafka events triggered | 250-500 | ~20 |
| Test duration | 25-40 min | 5-15 min |

## Architecture Notes

- Tests hit real deployed services via HTTP
- Cookie-based authentication through BFF service
- CQRS patterns require polling for projection updates
- Use `@pytest.mark.timeout(N)` for tests with async operations
