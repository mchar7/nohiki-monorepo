"""LlamaCppProvider for llama.cpp OpenAI-compatible server.

llama.cpp server exposes an OpenAI-compatible Chat Completions API at `/v1/chat/completions`.
It returns reasoning content in the `reasoning_content` field of the message object.

This provider configures PydanticAI's `OpenAIChatModel` to correctly parse this field
into `ThinkingPart` objects for reasoning-aware models.
"""

import httpx
from openai import AsyncOpenAI
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer, OpenAIModelProfile
from pydantic_ai.providers import Provider

from nohiki_llm_client.transport import (
    LLAMACPP_API_KEY_PLACEHOLDER,
    resolve_local_api_key,
    validate_http_base_url,
)


class LlamaCppProvider(Provider[AsyncOpenAI]):
    """Provider for llama.cpp server OpenAI-compatible API.

    llama.cpp server provides an OpenAI-compatible Chat Completions API that:
    - Returns reasoning in the `reasoning_content` message field (not `usage`)
    - Does NOT support OpenAI's Responses API
    - Does NOT provide separate reasoning token counts

    Usage:
        model = OpenAIChatModel(
            'Qwen3.5-35B-A3B-UD-Q4_K_M.gguf',
            provider=LlamaCppProvider(base_url='http://localhost:8888/v1'),
        )
        agent = Agent(model)

    Endpoint and credential selection are explicit so ambient environment
    variables cannot redirect local inference.
    """

    @property
    def name(self) -> str:
        """Return the provider name."""
        return "llamacpp"

    @property
    def base_url(self) -> str:
        """Return the base URL."""
        return self._base_url

    @property
    def client(self) -> AsyncOpenAI:
        """Return the AsyncOpenAI client."""
        return self._client

    def model_profile(self, model_name: str) -> ModelProfile | None:
        """Get model profile for llama.cpp models.

        All llama.cpp models share the same OpenAI-compatible profile: the
        model name is accepted per the ``Provider`` interface contract but unused.

        Returns:
            OpenAI model profile configured for llama.cpp compatibility:
            ``openai_chat_thinking_field='reasoning_content'`` to parse reasoning
            from the message field; ``openai_chat_send_back_thinking_parts='field'``
            to send reasoning back in the same format;
            ``openai_supports_strict_tool_definition=False`` for llama.cpp
            partial strict-mode support.
        """
        del model_name  # Required by Provider interface; all llama.cpp models share the same profile.
        return OpenAIModelProfile(
            json_schema_transformer=OpenAIJsonSchemaTransformer,
            supports_json_object_output=True,
            openai_chat_thinking_field="reasoning_content",
            openai_chat_send_back_thinking_parts="field",
            openai_supports_strict_tool_definition=False,
        )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        openai_client: AsyncOpenAI | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize llama.cpp provider.

        Args:
            base_url: Explicit llama.cpp server URL (e.g.,
                ``http://localhost:8888/v1``).
            api_key: Explicit API key, or a harmless nonempty placeholder when
                the local server does not require authentication.
            openai_client: Optional pre-configured AsyncOpenAI client.
            http_client: Optional custom httpx.AsyncClient.

        Raises:
            ValueError: If ``base_url`` is not a credential-free absolute HTTP(S) URL.
        """
        validate_http_base_url(base_url)

        if openai_client is not None:
            client_base_url = str(openai_client.base_url)
            validate_http_base_url(client_base_url, field_name="openai_client.base_url")
            if client_base_url.rstrip("/") != base_url.rstrip("/"):
                msg = "openai_client.base_url must match the explicit base_url"
                raise ValueError(msg)
            self._client = openai_client
            self._base_url = client_base_url
        else:
            api_key = resolve_local_api_key(
                api_key,
                placeholder=LLAMACPP_API_KEY_PLACEHOLDER,
            )

            self._base_url = base_url

            # Create http client if not provided
            if http_client is None:
                http_client = httpx.AsyncClient(timeout=300.0)

            self._client = AsyncOpenAI(
                base_url=self._base_url,
                api_key=api_key,
                http_client=http_client,
            )
