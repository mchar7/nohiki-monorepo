# Traefik Configuration

This directory contains the Traefik configuration for the Nohiki application,
following best practices by separating static and dynamic configuration.

## Configuration Structure

### Static Configuration (`traefik.yml`)

- **Purpose**: Contains configuration that requires a restart to change
- **Includes**: Entry points, providers, logging, metrics, and basic settings
- **Location**: `/etc/traefik/traefik.yml` in the container

### Dynamic Configuration Files

These files are automatically reloaded when changed (no restart required):

#### `middlewares.yml`

- **Purpose**: Defines reusable middleware components
- **Includes**:
  - `jwt-auth`: JWT authentication via user-auth-service
  - `internal-auth`: Internal service authentication
  - `cors-headers`: CORS configuration for frontend
  - `rate-limit`: Rate limiting for API protection
  - `security-headers`: Security headers for production

#### `routes.yml`

- **Purpose**: Defines all routing rules and service configurations
- **Includes**:
  - Router definitions with rules, priorities, and middleware assignments
  - Service definitions with load balancer and health check configuration
  - All previously embedded docker-compose.yml labels

## Routing Strategy

### Priority System

- **1000+**: Health checks and critical endpoints
- **950**: High-priority API routes (auth, specific user endpoints)
- **900**: Standard API routes
- **800**: Lower-priority API routes

### Service Routing

#### BFF Service (Main API Gateway)

- **Base URL**: `http://bff-service:8000`
- **Routes**: `/api/*` (all frontend-facing APIs)
- **Auth**: JWT required for most endpoints

#### User Auth Service

- **Base URL**: `http://user-auth-service:8000`
- **Routes**: `/api/v1/auth/*`
- **Auth**: Public access for login/signup, JWT for other endpoints

**Note:** All other services are Kafka-only and not exposed via Traefik.

#### Frontend development

The frontend is not a Compose service. Run `pnpm --filter nohiki-frontend dev` on port `5173`.
Vite proxies `/api` to Traefik; Traefik has no frontend catch-all route.

## Note on Service Architecture

Most backend services are Kafka-only (no HTTP endpoints). Only `bff-service` and
`user-auth-service` are exposed via Traefik. All API traffic flows through the BFF.

## Health Checks

Health checks are configured at the service level in the load balancer
configuration rather than as separate routes. This provides better service
discovery and health monitoring.

## Making Changes

1. **Static Configuration**: Edit `traefik.yml` and restart the Traefik container
2. **Dynamic Configuration**: Edit `middlewares.yml` or `routes.yml` - changes are applied automatically
3. **Testing**: Use the Traefik dashboard at `http://localhost:8080` to verify configuration

```bash
# View routing configuration
curl http://traefik.localhost:8080/api/rawdata | jq '.routers'

# Check service health
curl http://traefik.localhost:8080/api/rawdata | jq '.services'
```
