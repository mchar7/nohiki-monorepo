# Proto Generator

Generates Python domain models from protobuf files using betterproto2.

## Purpose

- Generates Python dataclasses from `.proto` definitions
- Enforces `buf.validate` required field constraints
- Fixes imports and performs post-processing
- Validates generated types can be imported

## Usage

```bash
# Full generation pipeline
uv run python -m proto_gen generate

# Fix required fields only (after manual protoc run)
uv run python -m proto_gen fix-required

# Validate generated types can be imported
uv run python -m proto_gen validate
```

## Commands

| Command | Description |
|---------|-------------|
| `generate` | Full generation pipeline (fetch deps → generate → post-process) |
| `fix-required` | Fix required field defaults in generated code |
| `validate` | Validate all generated modules can be imported |

## Architecture

```text
proto_gen/
├── cli.py           # Typer CLI entry point
├── console.py       # Rich console utilities
├── dependencies.py  # Proto dependency fetching
├── generator.py     # Protoc invocation
├── paths.py         # Path constants
├── post_processor.py # Import fixing and cleanup
└── required_fields.py # buf.validate required field handling
```

## Output

Generated Python code is placed in:

```text
backend/libs/nohiki-domain-models/src/nohiki/
├── common/v1/
├── doc/v1/
├── job/listing/v1/
├── user/pref/v1/
└── ...
```

## Import Pattern

```python
from nohiki.job.listing.v1 import ListingCreated, ListingSnapshot
from nohiki.common.v1 import EventMetadata, Location
```
