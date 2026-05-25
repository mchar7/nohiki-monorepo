# AST Explorer

Tree-sitter based codebase AST generation tool for AI-assisted code navigation and refactoring.

## Purpose

Generates a queryable structural map of Python codebases using tree-sitter for parsing.
The output is optimized for LLM context consumption, enabling AI assistants like Claude to
understand codebase structure without reading entire files.

## Features

- **Fast parsing** using tree-sitter for accurate AST generation
- **Multiple export formats**: JSON, YAML, Markdown (optimized for LLM context)
- **Queryable symbols**: Filter by kind, name pattern, visibility, file location
- **Rich CLI**: Progress bars, tables, trees, and panels via Rich + Typer
- **Extensible**: Language parser registry supports adding new languages

## Installation

```bash
cd scripts/util/ast_explorer
uv sync
```

## Usage

### Scan a directory

```bash
# Basic scan with summary
ast-explorer scan ./src

# Export to markdown (best for Claude)
ast-explorer scan ./src -o codebase.md -f markdown

# Show file tree with symbols
ast-explorer scan ./src --tree --symbols
```

### Query symbols

```bash
# Find all classes
ast-explorer query ./src --kind class

# Find functions matching pattern
ast-explorer query ./src --kind function --name "test_*"

# Show public API only
ast-explorer query ./src --public
```

### Inspect a symbol

```bash
ast-explorer inspect MyClassName --path ./src
```

### Export for LLM context

```bash
# Markdown format is optimized for LLM consumption
ast-explorer export ./src -o context.md -f markdown
```

## Output Formats

### Markdown (Recommended for LLMs)

Produces a hierarchical view with signatures, docstring previews, and line numbers:

```markdown
## Files

### `src/models.py`

- 📦 `class UserProfile` -- *Represents a user profile...* (L15)
  - 🔧 `def __init__(self, name: str)` (L20)
  - 🏷️ `@property email` (L35)
- ⚡ `def create_user(name: str) -> UserProfile` (L50)
```

### JSON

Full structured data for programmatic access.

### YAML

Human-readable structured data.

## Supported Languages

- **Python** (`.py`, `.pyi`): Full support
- TypeScript/JavaScript: Planned

## Architecture

```text
ast_explorer/
├── models/          # Domain models (SymbolNode, FileAST, CodebaseAST)
├── parsers/         # Language-specific tree-sitter parsers
├── analysis/        # File scanning and AST extraction
├── export/          # Output formatters (JSON, YAML, Markdown)
└── cli/             # Typer CLI with Rich TUI
```
