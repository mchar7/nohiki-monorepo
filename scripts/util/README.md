# Utility Scripts

Miscellaneous utility scripts for development.

## Scripts

### export-openapi.py

Exports combined OpenAPI spec from backend services.

```bash
# Export to default location (docs/api/nohiki.openapi.json)
uv run python scripts/util/export-openapi.py

# Export to custom location
uv run python scripts/util/export-openapi.py --output /path/to/spec.json
```

**Merges specs from:**

- `user-auth-service` - Authentication endpoints
- `bff-service` - Backend-for-frontend endpoints

**Output:**

- Combined OpenAPI 3.1.0 specification
- Structurally identical shared schemas, retaining the BFF version
- Unified tags and security schemes
