# Tailor: Nohiki Document Tailoring CLI

A SOLID-compliant CLI tool for manual document tailoring that maximally reuses existing Nohiki modules
(`nohiki-llm-client`, `doc-template-service`) while providing a beautiful interactive wizard TUI.

## Features

- **Interactive Wizard**: Guided step-by-step document generation
- **CLI Args Mode**: Direct command-line interface for scripting
- **Template Discovery**: Automatically finds templates from `doc-template-service`
- **Schema Validation**: Uses JSON schemas for structured LLM output
- **Multiple Output Formats**: PDF, HTML, PNG, WebP, Text
- **Rich TUI**: Beautiful progress indicators, cost estimates, and status display
- **OpenRouter Integration**: Custom app attribution for analytics

## Prerequisites

1. **Gotenberg**: Required for PDF/image generation

   ```bash
   sh infra/compose/scripts/preflight.sh up -d nohiki-infra-gotenberg
   ```

2. **LLM API Keys**: Store provider keys in the canonical secrets directory:

   ```bash
   mkdir -p infra/shared/secrets/llm/provider/api_keys
   printf '%s' 'sk-or-...' > infra/shared/secrets/llm/provider/api_keys/openrouter
   printf '%s' 'sk-...' > infra/shared/secrets/llm/provider/api_keys/openai
   ```

## Installation

```bash
# From monorepo root
cd scripts/util/tailor
uv sync
```

## Usage

### Interactive Wizard (Default)

```bash
uv run tailor
```

This launches a guided wizard that walks you through:

1. Selecting personal context files
2. Selecting job listing files
3. Choosing a template
4. Configuring output options
5. Confirming and generating

### CLI Args Mode

```bash
# Generate a resume
uv run tailor generate \
  --context resume_context.txt \
  --context cover_letter_example.md \
  --job job_posting.txt \
  --template resume \
  --format pdf \
  --output ./output/resume.pdf

# Short form
uv run tailor generate \
  -c resume.txt \
  -j posting.txt \
  -t resume \
  -f pdf
```

### Manual Data Mode

Skip LLM generation entirely by providing a pre-written JSON data file. The
data is validated against the template's schema, then rendered directly.

```bash
uv run --python python3.14 tailor generate \
  --data /path/to/cover_letter_data.json \
  --template cover_letter \
  --format pdf \
  --output ./output/cover_letter.pdf
```

The `--data` flag replaces `--context` and `--job` (those are for LLM-generated
content). Schema validation still runs, so the JSON must conform to the
template's matched schema.

**Note:** `pyproject.toml` specifies `requires-python = ">=3.14"`, so bare
`uv run` should work. Use `--python python3.14` to pin a specific version if
your system defaults to an older Python.

### Other Commands

```bash
# List available templates
uv run tailor templates
uv run tailor templates --verbose

# List available schemas
uv run tailor schemas
uv run tailor schemas --verbose

# Preview a template's schema requirements
uv run tailor preview resume

# Show version
uv run tailor --version
```

## Configuration

Settings are loaded in order of precedence:

1. Environment variables with the `TAILOR_` prefix
2. Provider key files under `infra/shared/secrets/llm/provider/api_keys/`
3. Defaults

### Key Settings

| Setting | Environment Variable | Default |
|---------|---------------------|---------|
| Model | `TAILOR_LLM_MODEL` | `openrouter:google/gemini-3-flash-preview` |
| Gotenberg URL | `TAILOR_GOTENBERG_URL` | `http://localhost:3000` |
| Templates Dir | `TAILOR_TEMPLATES_DIR` | `backend/services/doc-template-service/seed_templates` |
| Schemas Dir | `TAILOR_SCHEMAS_DIR` | `backend/services/doc-template-service/seed_schemas` |
| Output Dir | `TAILOR_OUTPUT_DIR` | `./output` |

## Architecture

```text
tailor/
├── cli/           # Typer CLI commands
├── core/          # Business logic orchestration
├── adapters/      # Nohiki module integration
├── display/       # Rich TUI components
├── models/        # Data models
└── exceptions.py  # Custom exceptions
```

### Code Reuse

This CLI **maximally reuses** existing Nohiki modules:

- **`nohiki-llm-client`**: LLM client with PydanticAI, metrics, retry logic
- **`nohiki-core-settings`**: Settings with secrets loading
- **`doc-template-service`**: Template rendering, Gotenberg integration, metadata parsing

### SOLID Principles

- **SRP**: Each module has a single responsibility
- **OCP**: New templates/schemas extend without code changes
- **LSP**: Both wizard and CLI use same `TailorOrchestrator`
- **ISP**: Small focused protocols for adapters
- **DIP**: Core depends on abstractions, not implementations

## Output Formats

| Format | Description | Requires |
|--------|-------------|----------|
| `pdf` | PDF document | Gotenberg |
| `html` | Raw HTML | - |
| `text` | Plain text | - |
| `png` | PNG image | Gotenberg |
| `webp` | WebP image | Gotenberg |
| `json` | Raw data | - |

## Troubleshooting

### "Gotenberg service not available"

Ensure Gotenberg is running:

```bash
just compose-up
```

### "No LLM API key configured"

Store the provider key in the canonical secrets directory:

```bash
mkdir -p infra/shared/secrets/llm/provider/api_keys
printf '%s' 'sk-or-...' > infra/shared/secrets/llm/provider/api_keys/openrouter
```

### "Template not found"

Check available templates:

```bash
uv run tailor templates
```

## Known Issues

### Seed file reversion

Template and schema files in `seed_templates/` and `seed_schemas/` may revert
to their git-tracked state after being modified. The cause is likely a file
watcher or build process in the monorepo.

**Workaround:** Commit changes after editing, or write via shell redirect
(`cat > file << 'EOF'`) for temporary changes that only need to survive a
render cycle.

**Symptom:** Schema validation errors mentioning `personalInfo`, `recipient`,
or `letter_content` indicate the old cover letter schema has been restored.
Template errors mentioning `'personalInfo' is undefined` indicate the old
cover letter template has been restored.

### Gotenberg PNG rendering quirks

- `position: fixed` elements do **not** render in PNG captures. Elements
  must be in the normal document flow to appear in screenshots.
- `100vh` resolves to Gotenberg's default image viewport size (800x600),
  **not** the page size from `@page`. Use fixed dimensions matching the
  page size instead (e.g., `width: 8.5in; height: 11in` for US Letter).

### Unit precision in PDF/PNG output

mm-based CSS dimensions can produce sub-pixel rounding gaps in Chromium's
renderer, visible as thin white lines between elements or at page edges.
Prefer inches for standard page sizes (US Letter = `8.5in x 11in`) to
avoid this.

### Template architecture reference

For details on template internals (design system, layout engines, schema
conventions), see `seed_templates/TEMPLATES.md`.
