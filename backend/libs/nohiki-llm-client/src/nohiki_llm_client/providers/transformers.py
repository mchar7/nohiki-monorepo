"""JSON schema transformers for provider-specific schema compatibility.

Custom ``JsonSchemaTransformer`` subclasses that handle provider quirks:

- **OllamaJsonSchemaTransformer**: Forces strict mode to avoid Ollama's GBNF
  grammar parser issues with large ``maxLength`` constraints.
- **InlinedRefsJsonSchemaTransformer**: Eliminates ``$defs``/``$ref`` pointers
  to fix serialisation bugs in certain OpenRouter backends.
"""

from __future__ import annotations

from pydantic_ai._json_schema import JsonSchema, JsonSchemaTransformer
from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer


class OllamaJsonSchemaTransformer(OpenAIJsonSchemaTransformer):
    """JSON schema transformer for Ollama that forces strict mode.

    Ollama's GBNF grammar parser cannot handle large ``maxLength`` constraints
    (e.g., maxLength=15000) because they generate enormous grammar rules.
    Strict mode strips these constraints, making schemas compatible with
    Ollama's structured output while preserving semantic correctness.
    """

    def __init__(
        self,
        schema: JsonSchema,
        **_kwargs: object,
    ) -> None:
        """Initialize transformer with forced strict mode.

        Args:
            schema: JSON schema to transform.
            **_kwargs: Absorbed to satisfy the superclass interface: always
                uses ``strict=True`` regardless of what callers pass.
        """
        super().__init__(schema, strict=True)


class InlinedRefsJsonSchemaTransformer(OpenAIJsonSchemaTransformer):
    """JSON schema transformer that eliminates all ``$defs``/``$ref`` pointers.

    Some model backends on OpenRouter serialise ``$ref``-referenced nested
    objects as escaped JSON strings in tool-call arguments rather than inline
    JSON objects.  The bug is triggered by the ``$defs``/``$ref`` structure
    that ``OpenAIJsonSchemaTransformer`` produces by default.  Confirmed
    affected backends: ``xiaomi/*`` and ``openai/gpt-oss-120b:exacto``
    (DeepInfra).

    ``prefer_inlined_defs=True`` instructs the walker to resolve every
    ``$ref`` inline.  The resulting schema has no ``$defs`` section and no
    ``$ref`` pointers, which eliminates the serialisation bug.

    ``strict=None`` preserves schema constraints (``minLength``,
    ``maxLength``, ``minimum``, ``maximum``, etc.) in the emitted schema.
    These constraints guide the model; stripping them causes models to
    violate length/range limits that Pydantic then rejects locally.
    """

    def __init__(
        self,
        schema: JsonSchema,
        **_kwargs: object,
    ) -> None:
        """Initialize with inlined ``$ref`` expansion and auto strict-detect.

        Bypasses ``OpenAIJsonSchemaTransformer.__init__`` to pass
        ``prefer_inlined_defs=True`` to the grandparent, then sets
        ``self.root_ref`` to preserve recursive-model handling from the parent.

        Args:
            schema: JSON schema to transform.
            **_kwargs: Absorbed to satisfy the superclass interface.
        """
        JsonSchemaTransformer.__init__(self, schema, strict=None, prefer_inlined_defs=True)
        self.root_ref = schema.get("$ref")
