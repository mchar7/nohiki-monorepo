"""Sandboxed Jinja template environment with security constraints.

A secure Jinja2 environment with strict security constraints:
- Whitelisted filters
- Maximum loop depth
- Render timeout
- Template size limits
- AST node count limits
- Compilation validation
"""

import asyncio
import multiprocessing
from dataclasses import dataclass
from functools import lru_cache
from multiprocessing.connection import Connection
from typing import Any

from jinja2 import TemplateSyntaxError, nodes
from jinja2.sandbox import SandboxedEnvironment

from doc_template_service.core.templates._jinja_inspect import (
    collect_template_variables,
    count_loop_depth,
    validate_variables_against_schema,
)
from doc_template_service.schemas.models import ValidationIssue, ValidationReport

# Security constants
MAX_TEMPLATE_SIZE: int = 100 * 1024  # 100KB
MAX_AST_NODES: int = 5000  # Maximum number of AST nodes
MAX_LOOP_DEPTH: int = 5  # Maximum allowed loop nesting depth
RENDER_TIMEOUT: float = 1.0  # 1s render timeout

# Whitelist of allowed filters
ALLOWED_FILTERS: set[str] = {
    # String manipulation
    "upper",
    "lower",
    "capitalize",
    "title",
    "trim",
    "striptags",
    "replace",
    "truncate",
    "wordwrap",
    # Formatting
    "format",
    "float",
    "int",
    "string",
    "list",
    "dict",
    # Data structure manipulation
    "first",
    "last",
    "length",
    "max",
    "min",
    "reverse",
    "sort",
    "unique",
    "join",
    "select",
    "reject",
    "map",
    "reduce",
    "sum",
    # Type conversion/testing
    "abs",
    "round",
    "default",
    # Output control
    "safe",
}


class TemplateSizeError(ValueError):
    """Exception raised when a template exceeds the maximum allowed size."""

    def __init__(self, template_size: int, max_size: int) -> None:
        """Initialize the exception with size details.

        Args:
            template_size: Size of the template in bytes
            max_size: Maximum allowed size in bytes

        """
        self.template_size = template_size
        self.max_size = max_size
        super().__init__(f"Template size ({template_size} bytes) exceeds the maximum allowed size ({max_size} bytes)")


class TemplateComplexityError(ValueError):
    """Exception raised when a template is too complex (too many AST nodes)."""

    def __init__(self, node_count: int, max_nodes: int) -> None:
        """Initialize the exception with complexity details.

        Args:
            node_count: Number of AST nodes in the template's AST
            max_nodes: Maximum allowed number of AST nodes

        """
        self.node_count = node_count
        self.max_nodes = max_nodes
        super().__init__(f"Template complexity ({node_count} nodes) exceeds the maximum allowed ({max_nodes} nodes)")


class TemplateLoopDepthError(ValueError):
    """Exception raised when a template has too deeply nested loops."""

    def __init__(self, depth: int, max_depth: int) -> None:
        """Initialize the exception with depth details.

        Args:
            depth: Loop nesting depth in the template
            max_depth: Maximum allowed loop nesting depth

        """
        self.depth = depth
        self.max_depth = max_depth
        super().__init__(f"Template loop depth ({depth}) exceeds the maximum allowed depth ({max_depth})")


class TemplateRenderTimeoutError(asyncio.TimeoutError):
    """Exception raised when template rendering exceeds the timeout."""

    def __init__(self, timeout: float) -> None:
        """Initialize the exception with timeout details.

        Args:
            timeout: Timeout in seconds

        """
        self.timeout = timeout
        super().__init__(f"Template rendering exceeded the timeout of {timeout} seconds")


@dataclass(slots=True)
class EnvironmentConfig:
    """Configuration for the sandboxed environment."""

    max_template_size: int = MAX_TEMPLATE_SIZE
    max_ast_nodes: int = MAX_AST_NODES
    max_loop_depth: int = MAX_LOOP_DEPTH
    render_timeout: float = RENDER_TIMEOUT
    allowed_filters: set[str] | None = None


class SecureSandboxedEnvironment(SandboxedEnvironment):
    """Secure Jinja2 environment with strict security constraints.

    This environment enforces:
    - A whitelist of allowed filters
    - Maximum template size
    - Maximum template complexity (AST node count)
    - Maximum loop nesting depth
    - Render timeout
    """

    def __init__(
        self,
        config: EnvironmentConfig,
        **kwargs: dict[str, Any],
    ) -> None:
        """Initialize a secure sandboxed Jinja2 environment.

        Args:
            config: Environment configuration with security constraints
            **kwargs: Additional arguments passed to SandboxedEnvironment

        """
        super().__init__(autoescape=True, **kwargs)
        # Legacy stored templates must compile; safe now escapes instead of bypassing autoescape.
        self.filters["safe"] = self.filters["escape"]

        self.max_template_size = config.max_template_size
        self.max_ast_nodes = config.max_ast_nodes
        self.max_loop_depth = config.max_loop_depth
        self.render_timeout = config.render_timeout
        self.allowed_filters = config.allowed_filters or ALLOWED_FILTERS

        # Restrict available filters to the allowed set
        self.filters = {name: filter_func for name, filter_func in self.filters.items() if name in self.allowed_filters}

    def _validate_template_size(self, template_source: str) -> None:
        """Validate that a template does not exceed the maximum allowed size.

        Args:
            template_source: The template source code

        Raises:
            TemplateSizeError: If the template exceeds the maximum allowed size

        """
        template_size = len(template_source.encode("utf-8"))
        if template_size > self.max_template_size:
            raise TemplateSizeError(template_size, self.max_template_size)

    def _validate_ast_complexity(self, ast_node_count: int) -> None:
        """Validate that a template's AST is not too complex.

        Args:
            ast_node_count: Number of nodes in the template's AST

        Raises:
            TemplateComplexityError: If the template has too many AST nodes

        """
        if ast_node_count > self.max_ast_nodes:
            raise TemplateComplexityError(ast_node_count, self.max_ast_nodes)

    def _validate_loop_depth(self, template_source: str) -> None:
        """Validate that a template's loop nesting does not exceed the maximum allowed depth.

        Args:
            template_source: The template source code

        Raises:
            TemplateLoopDepthError: If the template has too deeply nested loops

        """
        # Parse the template into an AST
        ast = self.parse(template_source)

        # Count the loop depth
        depth = count_loop_depth(ast)

        if depth > self.max_loop_depth:
            raise TemplateLoopDepthError(depth, self.max_loop_depth)

    def validate_render_source(self, template_source: str) -> None:
        """Reject oversized or complex templates before compilation."""
        self._validate_template_size(template_source)
        ast = self.parse(template_source)
        node_count = 1 + sum(1 for _ in ast.find_all(nodes.Node))
        self._validate_ast_complexity(node_count)
        depth = count_loop_depth(ast)
        if depth > self.max_loop_depth:
            raise TemplateLoopDepthError(depth, self.max_loop_depth)

    async def render_async(self, template_source: str, context: dict[str, Any]) -> str:
        """Render a template with an async timeout.

        Args:
            template_source: The template source code
            context: The context data for rendering

        Returns:
            The rendered template

        Raises:
            TemplateRenderTimeoutError: If rendering exceeds the timeout
            TemplateSyntaxError: If the template contains syntax errors

        """
        self.validate_render_source(template_source)
        return await _render_in_subprocess(template_source, context, self)

    def validate_template(self, template_source: str, schema: dict[str, Any] | None = None) -> ValidationReport:
        """Validate a template for security constraints and optionally against a schema.

        Args:
            template_source: The template source code
            schema: Optional JSON schema to validate template variables against

        Returns:
            ValidationReport with validation results

        """
        issues = []

        try:
            # Validate template size
            self._validate_template_size(template_source)

            # Parse the template into an AST
            ast = self.parse(template_source)

            # Count every descendant, including the root node.
            node_count = 1 + sum(1 for _ in ast.find_all(nodes.Node))
            self._validate_ast_complexity(node_count)

            # Validate loop depth
            depth = count_loop_depth(ast)
            if depth > self.max_loop_depth:
                issues.append(
                    ValidationIssue(
                        path="$",
                        keyword="loop_depth",
                        message=f"Template loop depth ({depth}) exceeds the maximum allowed ({self.max_loop_depth})",
                    )
                )

            # If a schema is provided, validate the template variables against it
            if schema is not None:
                # Collect variables used in the template (pass the source, not the AST)
                variables, _ = collect_template_variables(template_source)

                # Validate variables against the schema
                undefined_vars = validate_variables_against_schema(variables, schema)
                # Convert undefined variable names to ValidationIssue objects
                issues.extend(
                    ValidationIssue(
                        path=f"$.{var}",
                        keyword="undefined_variable",
                        message=f"Variable '{var}' is not defined in the schema",
                    )
                    for var in undefined_vars
                )

        except TemplateSizeError as e:
            issues.append(
                ValidationIssue(
                    path="$",
                    keyword="size",
                    message=str(e),
                )
            )
        except TemplateComplexityError as e:
            issues.append(
                ValidationIssue(
                    path="$",
                    keyword="complexity",
                    message=str(e),
                )
            )
        except TemplateSyntaxError as e:
            issues.append(
                ValidationIssue(
                    path=f"line {e.lineno}",
                    keyword="syntax",
                    message=f"Template syntax error: {e.message}",
                )
            )
        except ValueError as e:
            # Handle ValueError separately
            issues.append(
                ValidationIssue(
                    path="$",
                    keyword="value_error",
                    message=f"Value error during template validation: {e}",
                )
            )
        except TypeError as e:
            # Handle TypeError separately
            issues.append(
                ValidationIssue(
                    path="$",
                    keyword="type_error",
                    message=f"Type error during template validation: {e}",
                )
            )

        return ValidationReport(
            valid=len(issues) == 0,
            issues=issues,
        )


# Configuration indices for the config hash
CONFIG_IDX_TEMPLATE_SIZE = 0
CONFIG_IDX_AST_NODES = 1
CONFIG_IDX_LOOP_DEPTH = 2
CONFIG_IDX_RENDER_TIMEOUT = 3


@lru_cache(maxsize=128)
def get_cached_environment(config_hash: str) -> SecureSandboxedEnvironment:
    """Get a cached Jinja environment based on a configuration hash.

    Uses functools.lru_cache since environment objects cannot be serialized to Redis.
    The lru_cache decorator provides automatic caching with LRU eviction.

    Args:
        config_hash: Hash of the environment configuration for cache key

    Returns:
        Configured SecureSandboxedEnvironment instance

    """
    # Extract configuration values from the hash
    values = config_hash.split(",")
    max_template_size = (
        int(values[CONFIG_IDX_TEMPLATE_SIZE]) if len(values) > CONFIG_IDX_TEMPLATE_SIZE else MAX_TEMPLATE_SIZE
    )
    max_ast_nodes = int(values[CONFIG_IDX_AST_NODES]) if len(values) > CONFIG_IDX_AST_NODES else MAX_AST_NODES
    max_loop_depth = int(values[CONFIG_IDX_LOOP_DEPTH]) if len(values) > CONFIG_IDX_LOOP_DEPTH else MAX_LOOP_DEPTH
    render_timeout = (
        float(values[CONFIG_IDX_RENDER_TIMEOUT]) if len(values) > CONFIG_IDX_RENDER_TIMEOUT else RENDER_TIMEOUT
    )

    config = EnvironmentConfig(
        max_template_size=max_template_size,
        max_ast_nodes=max_ast_nodes,
        max_loop_depth=max_loop_depth,
        render_timeout=render_timeout,
    )

    return SecureSandboxedEnvironment(config=config)


def get_template_environment(
    max_template_size: int | None = None,
    max_ast_nodes: int | None = None,
    max_loop_depth: int | None = None,
    render_timeout: float | None = None,
) -> SecureSandboxedEnvironment:
    """Get a template environment with the specified configuration.

    Args:
        max_template_size: Maximum template size in bytes
        max_ast_nodes: Maximum number of AST nodes
        max_loop_depth: Maximum loop nesting depth
        render_timeout: Render timeout in seconds

    Returns:
        Configured SecureSandboxedEnvironment instance

    """
    # Use default values if not specified
    max_template_size = max_template_size if max_template_size is not None else MAX_TEMPLATE_SIZE
    max_ast_nodes = max_ast_nodes if max_ast_nodes is not None else MAX_AST_NODES
    max_loop_depth = max_loop_depth if max_loop_depth is not None else MAX_LOOP_DEPTH
    render_timeout = render_timeout if render_timeout is not None else RENDER_TIMEOUT

    # Create a hash of the configuration for caching
    config_hash = f"{max_template_size},{max_ast_nodes},{max_loop_depth},{render_timeout}"

    # Get a cached environment
    return get_cached_environment(config_hash)


def _render_worker(
    connection: Connection,
    template_source: str,
    context: dict[str, Any],
    config: EnvironmentConfig,
) -> None:
    """Compile and render in a process that the parent can terminate."""
    try:
        env = SecureSandboxedEnvironment(config=config)
        connection.send((True, env.from_string(template_source).render(**context)))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - relay arbitrary render failures; cancellation propagates
        connection.send((False, exc))
    finally:
        connection.close()


async def _render_in_subprocess(
    template_source: str,
    context: dict[str, Any],
    env: SecureSandboxedEnvironment,
) -> str:
    process_context = multiprocessing.get_context("fork")
    parent, child = process_context.Pipe(duplex=False)
    config = EnvironmentConfig(
        max_template_size=env.max_template_size,
        max_ast_nodes=env.max_ast_nodes,
        max_loop_depth=env.max_loop_depth,
        render_timeout=env.render_timeout,
        allowed_filters=set(env.allowed_filters),
    )
    process = process_context.Process(target=_render_worker, args=(child, template_source, context, config))
    process.start()
    child.close()
    try:
        try:
            succeeded, result = await asyncio.wait_for(
                asyncio.to_thread(parent.recv),
                timeout=env.render_timeout,
            )
        except TimeoutError as exc:
            raise TemplateRenderTimeoutError(env.render_timeout) from exc
        await asyncio.to_thread(process.join)
        if succeeded:
            return result
        raise result
    finally:
        if process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join)
        parent.close()


async def render_template(
    template_source: str,
    context: dict[str, Any],
    config: EnvironmentConfig | None = None,
) -> str:
    """Render a template with the specified context and configuration.

    Args:
        template_source: The template source code
        context: The context data for rendering
        config: Optional environment configuration

    Returns:
        The rendered template

    Raises:
        TemplateSizeError: If the template exceeds the maximum allowed size
        TemplateComplexityError: If the template has too many AST nodes
        TemplateLoopDepthError: If the template has too deeply nested loops
        TemplateRenderTimeoutError: If rendering exceeds the timeout
        TemplateSyntaxError: If the template contains syntax errors

    """
    env = get_template_environment(
        max_template_size=config.max_template_size if config else None,
        max_ast_nodes=config.max_ast_nodes if config else None,
        max_loop_depth=config.max_loop_depth if config else None,
        render_timeout=config.render_timeout if config else None,
    )
    env.validate_render_source(template_source)
    return await _render_in_subprocess(template_source, context, env)


def validate_template(
    template_source: str,
    schema: dict[str, Any] | None = None,
    config: EnvironmentConfig | None = None,
) -> ValidationReport:
    """Validate a template for security constraints and optionally against a schema.

    Args:
        template_source: The template source code
        schema: Optional JSON schema to validate template variables against
        config: Optional environment configuration

    Returns:
        ValidationReport with validation results

    """
    # Create a template environment with the specified configuration
    env = get_template_environment(
        max_template_size=config.max_template_size if config else None,
        max_ast_nodes=config.max_ast_nodes if config else None,
        max_loop_depth=config.max_loop_depth if config else None,
        render_timeout=config.render_timeout if config else None,
    )

    # Validate the template
    return env.validate_template(template_source, schema)
