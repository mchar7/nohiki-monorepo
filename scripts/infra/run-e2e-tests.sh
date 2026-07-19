#!/bin/bash
# =============================================================================
# Nohiki E2E Test Runner
# =============================================================================
#
# Runs end-to-end tests against the deployed Nohiki stack.
# Can be run against local Docker Compose or a remote environment.
#
# Usage:
#   ./scripts/run-e2e-tests.sh              # Run all E2E tests
#   ./scripts/run-e2e-tests.sh --quick      # Run only quick smoke tests
#   ./scripts/run-e2e-tests.sh --verbose    # Run with verbose output
#
# Environment Variables:
#   E2E_BASE_URL           - Base URL for services (default: http://localhost:8000)
#   E2E_DEPLOYMENT_TIMEOUT - Timeout waiting for services (default: 300)
#   E2E_WORKFLOW_TIMEOUT   - Timeout for workflow completion (default: 180)
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
E2E_BASE_URL="${E2E_BASE_URL:-http://localhost:8000}"
E2E_DEPLOYMENT_TIMEOUT="${E2E_DEPLOYMENT_TIMEOUT:-300}"
E2E_WORKFLOW_TIMEOUT="${E2E_WORKFLOW_TIMEOUT:-180}"

# Parse arguments
QUICK_MODE=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            QUICK_MODE=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--quick] [--verbose]"
            echo ""
            echo "Options:"
            echo "  --quick    Run only quick smoke tests"
            echo "  --verbose  Enable verbose output"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}=== NOHIKI E2E TEST RUNNER ===${NC}"
echo ""
echo "Configuration:"
echo "  Base URL: $E2E_BASE_URL"
echo "  Deployment Timeout: ${E2E_DEPLOYMENT_TIMEOUT}s"
echo "  Workflow Timeout: ${E2E_WORKFLOW_TIMEOUT}s"
echo ""

# Step 1: Verify services are reachable
echo -e "${YELLOW}Step 1: Checking service health...${NC}"

check_service() {
    local service=$1
    local url=$2
    if curl -sf "$url" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $service"
        return 0
    else
        echo -e "  ${RED}✗${NC} $service (unreachable)"
        return 1
    fi
}

SERVICES_HEALTHY=true

# Check Traefik (gateway)
if ! check_service "Traefik Gateway" "$E2E_BASE_URL/"; then
    SERVICES_HEALTHY=false
fi

# Check identity service health
if ! check_service "Identity Service" "$E2E_BASE_URL/api/v1/health" 2>/dev/null; then
    # Try direct container check
    check_service "Identity Service" "http://nohiki-svc-identity:8000/readyz" 2>/dev/null || true
fi

if [ "$SERVICES_HEALTHY" = false ]; then
    echo ""
    echo -e "${RED}ERROR: Some services are not healthy${NC}"
    echo "Please ensure the Docker Compose stack is running:"
    echo "  just compose-up"
    exit 1
fi

echo ""

# Step 2: Run E2E tests
echo -e "${YELLOW}Step 2: Running E2E tests...${NC}"
echo ""

cd "$REPO_ROOT"

# Build pytest arguments
PYTEST_ARGS="-v --tb=short"

if [ "$QUICK_MODE" = true ]; then
    PYTEST_ARGS="$PYTEST_ARGS -m 'e2e and not slow'"
fi

if [ "$VERBOSE" = true ]; then
    PYTEST_ARGS="$PYTEST_ARGS --capture=no"
fi

# Export environment for tests
export E2E_BASE_URL
export E2E_DEPLOYMENT_TIMEOUT
export E2E_WORKFLOW_TIMEOUT

# Run tests
echo "Running: uv run pytest tests/e2e/ $PYTEST_ARGS"
echo ""

if uv run pytest tests/e2e/ $PYTEST_ARGS; then
    echo ""
    echo -e "${GREEN}=== E2E TESTS PASSED ===${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}=== E2E TESTS FAILED ===${NC}"
    exit 1
fi
