"""Tests for Jinja template engine with security constraints."""

import itertools
import multiprocessing
import time

import pytest
from doc_template_service.core.templates.jinja_engine import (
    ALLOWED_FILTERS,
    MAX_AST_NODES,
    MAX_LOOP_DEPTH,
    MAX_TEMPLATE_SIZE,
    RENDER_TIMEOUT,
    EnvironmentConfig,
    SecureSandboxedEnvironment,
    TemplateComplexityError,
    TemplateLoopDepthError,
    TemplateRenderTimeoutError,
    TemplateSizeError,
    get_cached_environment,
    get_template_environment,
    render_template,
    validate_template,
)
from doc_template_service.schemas.models import ValidationReport


class TestTemplateSizeError:
    """Tests for TemplateSizeError exception."""

    def test_error_message(self) -> None:
        """Test error message format."""
        error = TemplateSizeError(150000, 100000)
        assert "150000 bytes" in str(error)
        assert "100000 bytes" in str(error)
        assert error.template_size == 150000
        assert error.max_size == 100000


class TestTemplateComplexityError:
    """Tests for TemplateComplexityError exception."""

    def test_error_message(self) -> None:
        """Test error message format."""
        error = TemplateComplexityError(6000, 5000)
        assert "6000 nodes" in str(error)
        assert "5000 nodes" in str(error)
        assert error.node_count == 6000
        assert error.max_nodes == 5000


class TestTemplateLoopDepthError:
    """Tests for TemplateLoopDepthError exception."""

    def test_error_message(self) -> None:
        """Test error message format."""
        error = TemplateLoopDepthError(10, 5)
        assert "10" in str(error)
        assert "5" in str(error)
        assert error.depth == 10
        assert error.max_depth == 5


class TestTemplateRenderTimeoutError:
    """Tests for TemplateRenderTimeoutError exception."""

    def test_error_message(self) -> None:
        """Test error message format."""
        error = TemplateRenderTimeoutError(0.2)
        assert "0.2 seconds" in str(error)
        assert error.timeout == pytest.approx(0.2)


class TestEnvironmentConfig:
    """Tests for EnvironmentConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = EnvironmentConfig()
        assert config.max_template_size == MAX_TEMPLATE_SIZE
        assert config.max_ast_nodes == MAX_AST_NODES
        assert config.max_loop_depth == MAX_LOOP_DEPTH
        assert config.render_timeout == RENDER_TIMEOUT
        assert config.allowed_filters is None

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = EnvironmentConfig(
            max_template_size=50000,
            max_ast_nodes=1000,
            max_loop_depth=3,
            render_timeout=1.0,
            allowed_filters={"upper", "lower"},
        )
        assert config.max_template_size == 50000
        assert config.max_ast_nodes == 1000
        assert config.max_loop_depth == 3
        assert config.render_timeout == pytest.approx(1.0)
        assert config.allowed_filters == {"upper", "lower"}


class TestSecureSandboxedEnvironment:
    """Tests for SecureSandboxedEnvironment class."""

    def test_init_with_default_config(self) -> None:
        """Test initialization with default config."""
        config = EnvironmentConfig()
        env = SecureSandboxedEnvironment(config)
        assert env.max_template_size == MAX_TEMPLATE_SIZE
        assert env.max_ast_nodes == MAX_AST_NODES
        assert env.max_loop_depth == MAX_LOOP_DEPTH
        assert env.render_timeout == RENDER_TIMEOUT

    def test_init_restricts_filters(self) -> None:
        """Test that filters are restricted to allowed set."""
        config = EnvironmentConfig(allowed_filters={"upper", "lower"})
        env = SecureSandboxedEnvironment(config)
        assert "upper" in env.filters
        assert "lower" in env.filters
        # Filters not in allowed set should be removed
        assert len(env.filters) == 2

    def test_validate_template_size_raises_error(self) -> None:
        """Test that oversized template raises TemplateSizeError."""
        config = EnvironmentConfig(max_template_size=100)
        env = SecureSandboxedEnvironment(config)

        with pytest.raises(TemplateSizeError):
            env._validate_template_size("x" * 200)

    def test_validate_template_size_passes(self) -> None:
        """Test that valid size template passes."""
        config = EnvironmentConfig(max_template_size=1000)
        env = SecureSandboxedEnvironment(config)
        env._validate_template_size("x" * 100)  # Should not raise

    def test_validate_ast_complexity_raises_error(self) -> None:
        """Test that complex template raises TemplateComplexityError."""
        config = EnvironmentConfig(max_ast_nodes=10)
        env = SecureSandboxedEnvironment(config)

        with pytest.raises(TemplateComplexityError):
            env._validate_ast_complexity(100)

    def test_validate_ast_complexity_passes(self) -> None:
        """Test that simple template passes."""
        config = EnvironmentConfig(max_ast_nodes=1000)
        env = SecureSandboxedEnvironment(config)
        env._validate_ast_complexity(10)  # Should not raise

    def test_validate_loop_depth_raises_error(self) -> None:
        """Test that deeply nested loops raise TemplateLoopDepthError."""
        config = EnvironmentConfig(max_loop_depth=2)
        env = SecureSandboxedEnvironment(config)

        # Create template with nested loops
        template = """
        {% for i in items %}
            {% for j in items %}
                {% for k in items %}
                    {{ k }}
                {% endfor %}
            {% endfor %}
        {% endfor %}
        """

        with pytest.raises(TemplateLoopDepthError):
            env._validate_loop_depth(template)

    def test_validate_template_valid(self) -> None:
        """Test validating a valid template."""
        config = EnvironmentConfig()
        env = SecureSandboxedEnvironment(config)
        template = "<html><body>{{ name }}</body></html>"

        report = env.validate_template(template)

        assert isinstance(report, ValidationReport)
        assert report.valid is True

    def test_validate_template_with_syntax_error(self) -> None:
        """Test validating template with syntax error."""
        config = EnvironmentConfig()
        env = SecureSandboxedEnvironment(config)
        template = "<html><body>{{ name }</body></html>"  # Missing closing brace

        report = env.validate_template(template)

        assert report.valid is False
        assert any("syntax" in issue.keyword.lower() for issue in report.issues)

    def test_validate_template_too_large(self) -> None:
        """Test validating oversized template."""
        config = EnvironmentConfig(max_template_size=100)
        env = SecureSandboxedEnvironment(config)
        template = "x" * 200

        report = env.validate_template(template)

        assert report.valid is False
        assert any("size" in issue.keyword.lower() for issue in report.issues)


class TestGetCachedEnvironment:
    """Tests for get_cached_environment function."""

    def test_returns_environment(self) -> None:
        """Test that function returns SecureSandboxedEnvironment."""
        config_hash = f"{MAX_TEMPLATE_SIZE},{MAX_AST_NODES},{MAX_LOOP_DEPTH},{RENDER_TIMEOUT}"
        env = get_cached_environment(config_hash)
        assert isinstance(env, SecureSandboxedEnvironment)

    def test_caches_environment(self) -> None:
        """Test that same config hash returns same environment."""
        config_hash = f"{MAX_TEMPLATE_SIZE},{MAX_AST_NODES},{MAX_LOOP_DEPTH},{RENDER_TIMEOUT}"
        env1 = get_cached_environment(config_hash)
        env2 = get_cached_environment(config_hash)
        assert env1 is env2


class TestGetTemplateEnvironment:
    """Tests for get_template_environment function."""

    def test_returns_environment_with_defaults(self) -> None:
        """Test that function returns environment with default values."""
        env = get_template_environment()
        assert isinstance(env, SecureSandboxedEnvironment)
        assert env.max_template_size == MAX_TEMPLATE_SIZE

    def test_returns_environment_with_custom_values(self) -> None:
        """Test that function returns environment with custom values."""
        env = get_template_environment(
            max_template_size=50000,
            max_ast_nodes=1000,
            max_loop_depth=3,
            render_timeout=1.0,
        )
        assert env.max_template_size == 50000
        assert env.max_ast_nodes == 1000
        assert env.max_loop_depth == 3
        assert env.render_timeout == pytest.approx(1.0)


class TestRenderTemplate:
    """Tests for render_template function."""

    @pytest.mark.asyncio
    async def test_render_simple_template(self) -> None:
        """Test rendering a simple template."""
        template = "<html><body>{{ name }}</body></html>"
        context = {"name": "Test"}

        result = await render_template(template, context)

        assert "<html><body>Test</body></html>" in result

    @pytest.mark.asyncio
    async def test_render_template_with_filters(self) -> None:
        """Test rendering template with allowed filters."""
        template = "<html><body>{{ name | upper }}</body></html>"
        context = {"name": "test"}

        result = await render_template(template, context)

        assert "TEST" in result

    @pytest.mark.asyncio
    async def test_render_template_with_loop(self) -> None:
        """Test rendering template with loop."""
        template = "<ul>{% for item in items %}<li>{{ item }}</li>{% endfor %}</ul>"
        context = {"items": ["a", "b", "c"]}

        result = await render_template(template, context)

        assert "<li>a</li>" in result
        assert "<li>b</li>" in result
        assert "<li>c</li>" in result

    @pytest.mark.asyncio
    async def test_render_template_with_conditional(self) -> None:
        """Test rendering template with conditional."""
        template = "{% if show %}Visible{% else %}Hidden{% endif %}"
        context_show = {"show": True}
        context_hide = {"show": False}

        result_show = await render_template(template, context_show)
        result_hide = await render_template(template, context_hide)

        assert "Visible" in result_show
        assert "Hidden" in result_hide

    @pytest.mark.asyncio
    async def test_render_rejects_recursive_ast_over_limit(self) -> None:
        template = "{% if a %}{% if b %}{{ value|upper }}{% endif %}{% endif %}"
        config = EnvironmentConfig(max_ast_nodes=5)

        with pytest.raises(TemplateComplexityError):
            await render_template(template, {"a": True, "b": True, "value": "ok"}, config)

    @pytest.mark.asyncio
    async def test_render_rejects_excessive_loop_depth(self) -> None:
        template = (
            "{% for a in values %}{% for b in values %}{% for c in values %}{{ c }}{% endfor %}{% endfor %}{% endfor %}"
        )
        config = EnvironmentConfig(max_loop_depth=2)

        with pytest.raises(TemplateLoopDepthError):
            await render_template(template, {"values": [1]}, config)

    @pytest.mark.asyncio
    async def test_timed_out_render_terminates_worker_process(self) -> None:
        children_before = {child.pid for child in multiprocessing.active_children()}
        started = time.monotonic()

        with pytest.raises(TemplateRenderTimeoutError):
            await render_template(
                "{% for value in values %}{{ value }}{% endfor %}",
                {"values": itertools.repeat("x")},
                EnvironmentConfig(render_timeout=0.05),
            )

        assert time.monotonic() - started < 1.0
        assert {child.pid for child in multiprocessing.active_children()} <= children_before


class TestValidateTemplate:
    """Tests for validate_template function."""

    def test_validate_valid_template(self) -> None:
        """Test validating a valid template."""
        template = "<html><body>{{ name }}</body></html>"

        report = validate_template(template)

        assert isinstance(report, ValidationReport)
        assert report.valid is True

    def test_validate_counts_descendant_ast_nodes(self) -> None:
        template = "{% if a %}{% if b %}{{ value|upper }}{% endif %}{% endif %}"

        report = validate_template(template, config=EnvironmentConfig(max_ast_nodes=5))

        assert report.valid is False
        assert any("complex" in issue.keyword.lower() for issue in report.issues)

    def test_validate_template_with_schema(self) -> None:
        """Test validating template against schema."""
        template = "<html><body>{{ name }}</body></html>"
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }

        report = validate_template(template, schema=schema)

        assert isinstance(report, ValidationReport)

    def test_validate_template_with_config(self) -> None:
        """Test validating template with custom config."""
        template = "<html><body>{{ name }}</body></html>"
        config = EnvironmentConfig(max_template_size=1000000)

        report = validate_template(template, config=config)

        assert isinstance(report, ValidationReport)


class TestAllowedFilters:
    """Tests for ALLOWED_FILTERS constant."""

    def test_contains_string_filters(self) -> None:
        """Test that string manipulation filters are allowed."""
        assert "upper" in ALLOWED_FILTERS
        assert "lower" in ALLOWED_FILTERS
        assert "capitalize" in ALLOWED_FILTERS
        assert "title" in ALLOWED_FILTERS
        assert "trim" in ALLOWED_FILTERS

    def test_contains_data_structure_filters(self) -> None:
        """Test that data structure filters are allowed."""
        assert "first" in ALLOWED_FILTERS
        assert "last" in ALLOWED_FILTERS
        assert "length" in ALLOWED_FILTERS
        assert "sort" in ALLOWED_FILTERS
        assert "join" in ALLOWED_FILTERS

    def test_contains_type_conversion_filters(self) -> None:
        """Test that type conversion filters are allowed."""
        assert "int" in ALLOWED_FILTERS
        assert "float" in ALLOWED_FILTERS
        assert "string" in ALLOWED_FILTERS
        assert "default" in ALLOWED_FILTERS
