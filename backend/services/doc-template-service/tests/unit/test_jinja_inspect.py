"""Tests for Jinja template AST inspection and variable collection."""

from doc_template_service.core.templates._jinja_inspect import (
    VariableCollector,
    collect_template_variables,
    count_loop_depth,
    flatten_variables,
    inspect_template,
    validate_variables_against_schema,
)
from jinja2 import Environment


class TestVariableCollector:
    """Tests for VariableCollector class."""

    def test_init_defaults(self) -> None:
        """Test that collector initializes with empty collections."""
        collector = VariableCollector()
        assert collector.variables == {}
        assert collector.visited_nodes == []
        assert collector.node_count == 0
        assert collector.current_iteration_vars == set()

    def test_add_variable(self) -> None:
        """Test adding variables to collector."""
        collector = VariableCollector()
        collector._add_variable("user", "user")
        collector._add_variable("user", "user.name")

        assert "user" in collector.variables
        assert "user" in collector.variables["user"]
        assert "user.name" in collector.variables["user"]


class TestCollectTemplateVariables:
    """Tests for collect_template_variables function."""

    def test_simple_variable(self) -> None:
        """Test collecting simple variable."""
        template = "{{ name }}"
        variables, node_count = collect_template_variables(template)

        assert "name" in variables
        assert node_count > 0

    def test_nested_attribute_access(self) -> None:
        """Test collecting nested attribute access."""
        template = "{{ user.name }}"
        variables, _ = collect_template_variables(template)

        assert "user" in variables
        assert any("user.name" in path for path in variables.get("user", set()))

    def test_nested_deep_attribute_access(self) -> None:
        """Test collecting deeply nested attribute access."""
        template = "{{ user.address.city }}"
        variables, _ = collect_template_variables(template)

        assert "user" in variables

    def test_getitem_access_with_constant(self) -> None:
        """Test collecting item access with constant index."""
        template = "{{ items[0] }}"
        variables, _ = collect_template_variables(template)

        assert "items" in variables

    def test_getitem_access_with_variable(self) -> None:
        """Test collecting item access with variable index."""
        template = "{{ items[i] }}"
        variables, _ = collect_template_variables(template)

        assert "items" in variables
        assert "i" in variables

    def test_getitem_access_with_string_key(self) -> None:
        """Test collecting item access with string key."""
        template = "{{ data['key'] }}"
        variables, _ = collect_template_variables(template)

        assert "data" in variables

    def test_for_loop_variable(self) -> None:
        """Test collecting for loop iteration variable."""
        template = "{% for item in items %}{{ item }}{% endfor %}"
        variables, _ = collect_template_variables(template)

        assert "items" in variables
        assert "item" in variables

    def test_for_loop_with_else(self) -> None:
        """Test collecting variables in for loop with else clause."""
        template = "{% for item in items %}{{ item }}{% else %}{{ default }}{% endfor %}"
        variables, _ = collect_template_variables(template)

        assert "items" in variables
        assert "default" in variables

    def test_if_statement(self) -> None:
        """Test collecting variables in if statement."""
        template = "{% if condition %}{{ value }}{% endif %}"
        variables, _ = collect_template_variables(template)

        assert "condition" in variables
        assert "value" in variables

    def test_if_else_statement(self) -> None:
        """Test collecting variables in if-else statement."""
        template = "{% if condition %}{{ value1 }}{% else %}{{ value2 }}{% endif %}"
        variables, _ = collect_template_variables(template)

        assert "condition" in variables
        assert "value1" in variables
        assert "value2" in variables

    def test_macro_definition(self) -> None:
        """Test collecting macro names."""
        template = "{% macro render_item(item) %}{{ item }}{% endmacro %}"
        variables, _ = collect_template_variables(template)

        assert "render_item" in variables

    def test_function_call(self) -> None:
        """Test collecting variables in function calls."""
        template = "{{ format(value, precision) }}"
        variables, _ = collect_template_variables(template)

        assert "format" in variables
        assert "value" in variables
        assert "precision" in variables

    def test_multiple_variables(self) -> None:
        """Test collecting multiple variables."""
        template = "{{ first }} {{ second }} {{ third }}"
        variables, _ = collect_template_variables(template)

        assert "first" in variables
        assert "second" in variables
        assert "third" in variables

    def test_with_custom_environment(self) -> None:
        """Test collecting variables with custom environment."""
        env = Environment(autoescape=True)
        template = "{{ name }}"
        variables, _ = collect_template_variables(template, env)

        assert "name" in variables

    def test_empty_template(self) -> None:
        """Test collecting variables from empty template."""
        template = "Hello, World!"
        variables, _ = collect_template_variables(template)

        assert variables == {}

    def test_filter_usage(self) -> None:
        """Test that filters don't add spurious variables."""
        template = "{{ name | upper }}"
        variables, _ = collect_template_variables(template)

        assert "name" in variables
        # 'upper' is a filter, not a variable
        assert "upper" not in variables


class TestFlattenVariables:
    """Tests for flatten_variables function."""

    def test_flatten_single_variable(self) -> None:
        """Test flattening single variable."""
        variables = {"name": {"name"}}
        result = flatten_variables(variables)

        assert "name" in result

    def test_flatten_multiple_paths(self) -> None:
        """Test flattening multiple paths."""
        variables = {"user": {"user", "user.name", "user.email"}}
        result = flatten_variables(variables)

        assert "user" in result
        assert "user.name" in result
        assert "user.email" in result

    def test_flatten_empty(self) -> None:
        """Test flattening empty variables."""
        variables: dict[str, set[str]] = {}
        result = flatten_variables(variables)

        assert result == set()


class TestValidateVariablesAgainstSchema:
    """Tests for validate_variables_against_schema function."""

    def test_valid_variables(self) -> None:
        """Test validating variables that exist in schema."""
        variables = {"name": {"name"}}
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }

        undefined = validate_variables_against_schema(variables, schema)

        assert len(undefined) == 0

    def test_undefined_variables(self) -> None:
        """Test detecting undefined variables."""
        variables = {"unknown": {"unknown"}}
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }

        undefined = validate_variables_against_schema(variables, schema)

        assert len(undefined) > 0
        assert "unknown" in undefined

    def test_nested_property_valid(self) -> None:
        """Test validating nested property that exists."""
        variables = {"user": {"user", "user.name"}}
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        }

        undefined = validate_variables_against_schema(variables, schema)

        # user and user.name should be valid
        assert "user" not in undefined

    def test_array_items_valid(self) -> None:
        """Test validating array item access."""
        variables = {"items": {"items", "items[*]"}}
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }

        undefined = validate_variables_against_schema(variables, schema)

        # items should be valid
        assert "items" not in undefined

    def test_empty_schema(self) -> None:
        """Test with empty schema."""
        variables = {"name": {"name"}}
        schema: dict[str, object] = {"type": "object"}

        undefined = validate_variables_against_schema(variables, schema)

        # All variables should be undefined
        assert len(undefined) > 0


class TestCountLoopDepth:
    """Tests for count_loop_depth function."""

    def test_no_loops(self) -> None:
        """Test template with no loops."""
        env = Environment(autoescape=True)
        ast = env.parse("{{ name }}")

        depth = count_loop_depth(ast)

        assert depth == 0

    def test_single_loop(self) -> None:
        """Test template with single loop."""
        env = Environment(autoescape=True)
        ast = env.parse("{% for item in items %}{{ item }}{% endfor %}")

        depth = count_loop_depth(ast)

        assert depth == 1

    def test_nested_loops(self) -> None:
        """Test template with nested loops."""
        env = Environment(autoescape=True)
        template = """
        {% for row in rows %}
            {% for cell in row %}
                {{ cell }}
            {% endfor %}
        {% endfor %}
        """
        ast = env.parse(template)

        depth = count_loop_depth(ast)

        assert depth == 2

    def test_deeply_nested_loops(self) -> None:
        """Test template with deeply nested loops."""
        env = Environment(autoescape=True)
        template = """
        {% for a in items_a %}
            {% for b in items_b %}
                {% for c in items_c %}
                    {{ c }}
                {% endfor %}
            {% endfor %}
        {% endfor %}
        """
        ast = env.parse(template)

        depth = count_loop_depth(ast)

        assert depth == 3

    def test_sequential_loops(self) -> None:
        """Test template with sequential (not nested) loops."""
        env = Environment(autoescape=True)
        template = """
        {% for a in items_a %}{{ a }}{% endfor %}
        {% for b in items_b %}{{ b }}{% endfor %}
        """
        ast = env.parse(template)

        depth = count_loop_depth(ast)

        assert depth == 1

    def test_loop_with_else(self) -> None:
        """Test loop depth with else clause containing loop."""
        env = Environment(autoescape=True)
        template = """
        {% for item in items %}
            {{ item }}
        {% else %}
            {% for alt in alternatives %}{{ alt }}{% endfor %}
        {% endfor %}
        """
        ast = env.parse(template)

        depth = count_loop_depth(ast)

        assert depth >= 1


class TestInspectTemplate:
    """Tests for inspect_template function."""

    def test_valid_template(self) -> None:
        """Test inspecting valid template."""
        template = "<html><body>{{ name }}</body></html>"
        issues = inspect_template(template)

        assert len(issues) == 0

    def test_syntax_error(self) -> None:
        """Test inspecting template with syntax error."""
        template = "<html><body>{{ name }</body></html>"  # Missing closing brace
        issues = inspect_template(template)

        assert len(issues) > 0
        assert any("syntax" in issue.keyword.lower() for issue in issues)

    def test_with_environment_config(self) -> None:
        """Test inspecting template with custom environment config."""
        template = "{{ name }}"
        config: dict[str, object] = {"trim_blocks": True}
        issues = inspect_template(template, config)

        assert len(issues) == 0

    def test_invalid_jinja_expression(self) -> None:
        """Test inspecting template with invalid Jinja expression."""
        template = "{% invalid_keyword %}"
        issues = inspect_template(template)

        assert len(issues) > 0

    def test_unclosed_block(self) -> None:
        """Test inspecting template with unclosed block."""
        template = "{% for item in items %}{{ item }}"  # Missing endfor
        issues = inspect_template(template)

        assert len(issues) > 0
        assert any("syntax" in issue.keyword.lower() for issue in issues)
