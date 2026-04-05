"""Model profiles and provider quirks registry for OpenRouter/Ollama.

Contains:

- **Model profiles**: Pre-configured ``OpenAIModelProfile`` instances for
  providers with special requirements (Ollama, Xiaomi, Meta-Llama, Qwen).
- **Quirks registry**: Per-provider behavioural overrides for OpenRouter
  model routing, with longest-prefix matching.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer, OpenAIModelProfile

from nohiki_llm_client.providers.transformers import (
    InlinedRefsJsonSchemaTransformer,
    OllamaJsonSchemaTransformer,
)

OLLAMA_PROFILE: OpenAIModelProfile = OpenAIModelProfile(
    json_schema_transformer=OllamaJsonSchemaTransformer,
    supports_json_schema_output=True,
    supports_json_object_output=True,
    default_structured_output_mode="native",
    native_output_requires_schema_in_instructions=True,
    openai_chat_thinking_field="reasoning",
)
"""Profile for Ollama models using the OpenAI-compatible chat API.

Forces strict mode via ``OllamaJsonSchemaTransformer`` to avoid GBNF grammar
parser issues with large ``maxLength`` constraints.
"""

INLINED_REFS_OPENROUTER_PROFILE: OpenAIModelProfile = OpenAIModelProfile(
    json_schema_transformer=InlinedRefsJsonSchemaTransformer,
)
"""Profile for OpenRouter-hosted models that exhibit the ``$ref`` serialisation bug.

Confirmed affected backends: **Xiaomi** (``xiaomi/*``) and **DeepInfra**
(``openai/gpt-oss-120b:exacto``).  Both serialise ``$ref``-referenced nested
objects as escaped JSON strings in tool-call arguments instead of inline
objects, causing PydanticAI validation to fail with ``input_type=str`` errors.

``json_schema_transformer=InlinedRefsJsonSchemaTransformer`` eliminates all
``$defs``/``$ref`` pointers before the request is sent, resolving the bug.
The transformer uses ``strict=None`` so schema constraints (``minLength``,
``maxLength``, etc.) are preserved as model guidance.

All other profile fields -- including ``openai_chat_send_back_thinking_parts``,
``openai_chat_thinking_field``, and ``openai_chat_supports_file_urls`` -- are
merged in from the OpenRouter provider's resolved profile via
``resolve_effective_profile``.
"""

QWEN_NEXT_OPENROUTER_PROFILE: OpenAIModelProfile = OpenAIModelProfile(
    default_structured_output_mode="native",
    supports_json_schema_output=True,
)
"""Profile for ``qwen/qwen3-next`` family models on OpenRouter.

These models respond to tool calls using the Hermes XML format --
``<tool_call>{"name": ..., "arguments": ...}</tool_call>`` -- which OpenRouter
does not normalise to the OpenAI schema.  Setting
``default_structured_output_mode='native'`` bypasses tool-calling entirely:
PydanticAI sends a ``response_format: json_schema`` request and the model
returns structured output directly in the ``content`` field, eliminating the
Hermes wrapper at the profile level with no custom model code.

The ``OpenRouterProvider`` already applies ``qwen_model_profile`` for all
``qwen/*`` slugs, which sets ``json_schema_transformer=InlineDefsJsonSchemaTransformer``.
The native-mode JSON schema is therefore also ``$ref``-free without any
additional transformer.
"""

META_LLAMA_OPENROUTER_PROFILE: OpenAIModelProfile = OpenAIModelProfile(
    openai_supports_tool_choice_required=False,
)
"""Profile for Meta Llama models on OpenRouter.

Meta Llama backends reject forced function calling (``tool_choice='required'``,
OpenRouter mode=ANY).  Setting ``openai_supports_tool_choice_required=False``
causes PydanticAI to send ``tool_choice='auto'`` instead; instruction-tuned
Llama models reliably call the provided extraction tool without the
forced-calling constraint.
"""


@dataclass(frozen=True, slots=True)
class OpenRouterModelQuirks:
    """Per-provider behavioural overrides for OpenRouter model routing.

    Attributes:
        profile: Custom model profile for schema or capability quirks.
            ``None`` defers to the OpenRouter provider's default profile.
        supports_openrouter_reasoning: Whether this model/provider accepts
            the ``reasoning`` request parameter (``effort``/``max_tokens``).
            Set to ``False`` for providers that reject it with HTTP 400.
    """

    profile: OpenAIModelProfile | None = None
    supports_openrouter_reasoning: bool = True


OPENROUTER_QUIRKS: dict[str, OpenRouterModelQuirks] = {
    "openai/gpt-oss-120b:exacto": OpenRouterModelQuirks(profile=INLINED_REFS_OPENROUTER_PROFILE),
    "qwen/qwen3-next": OpenRouterModelQuirks(
        profile=QWEN_NEXT_OPENROUTER_PROFILE,
        supports_openrouter_reasoning=False,
    ),
    "qwen/qwen3.5": OpenRouterModelQuirks(
        profile=OpenAIModelProfile(json_schema_transformer=OpenAIJsonSchemaTransformer),
    ),
    "qwen/qwen3-vl": OpenRouterModelQuirks(supports_openrouter_reasoning=False),
    "meta-llama": OpenRouterModelQuirks(
        profile=META_LLAMA_OPENROUTER_PROFILE,
        supports_openrouter_reasoning=False,
    ),
    "xiaomi": OpenRouterModelQuirks(profile=INLINED_REFS_OPENROUTER_PROFILE),
}
"""Registry of per-provider behavioural quirks for OpenRouter model routing.

Keys are model-slug prefixes.  Longer prefixes take precedence over shorter
ones (e.g. ``"qwen/qwen3-vl"`` overrides a hypothetical ``"qwen"`` entry for
all ``qwen/qwen3-vl-*`` models).  For providers where *all* models share the
same quirk, use the vendor prefix (e.g. ``"meta-llama"``).  For per-series
overrides, use a more specific prefix (e.g. ``"qwen/qwen3-next"``).  Lookup
uses longest-prefix matching -- see ``select_openrouter_quirks``.
"""

OPENROUTER_QUIRKS_BY_SPECIFICITY: tuple[tuple[str, OpenRouterModelQuirks], ...] = tuple(
    sorted(OPENROUTER_QUIRKS.items(), key=lambda item: len(item[0]), reverse=True)
)
"""``OPENROUTER_QUIRKS`` entries pre-sorted longest-prefix-first.

Pre-computed once at module load so ``select_openrouter_quirks`` iterates a
constant sequence rather than re-sorting on every call.
"""


def select_openrouter_quirks(model_name: str) -> OpenRouterModelQuirks:
    """Return behavioural quirks for the given OpenRouter model slug.

    Performs a longest-prefix match against ``OPENROUTER_QUIRKS`` keys so
    that finer-grained series overrides (e.g. ``"qwen/qwen3-vl"``) take
    precedence over vendor-level entries (e.g. a hypothetical ``"qwen"``
    entry).  The match is a plain ``str.startswith`` check on the full slug,
    including any colon routing suffix (e.g. ``"openai/gpt-oss-120b:exacto``").

    Args:
        model_name: Full OpenRouter model slug, optionally with a colon
            routing suffix (e.g. ``"openai/gpt-oss-120b:exacto"``).

    Returns:
        The first matching ``OpenRouterModelQuirks`` (longest prefix wins),
        or a default instance when no prefix matches.
    """
    for prefix, quirks in OPENROUTER_QUIRKS_BY_SPECIFICITY:
        if model_name.startswith(prefix):
            return quirks
    return OpenRouterModelQuirks()
