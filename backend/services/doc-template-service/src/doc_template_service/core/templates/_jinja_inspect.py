"""Jinja template AST inspection and variable collection.

Functionality to analyze Jinja templates using Abstract Syntax Tree (AST)
inspection to collect all variable references, validate template complexity, and ensure
templates follow required security constraints.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, cast

import jinja2
from jinja2 import Environment, nodes
from jinja2.utils import select_autoescape
from jinja2.visitor import NodeVisitor

if TYPE_CHECKING:
    from jinja2.nodes import Node

from doc_template_service.schemas.models import ValidationIssue

logger = logging.getLogger(__name__)

type SchemaDict = dict[str, object]

# Pre-compiled regex for normalizing indexed paths (matches [0], [*], [key], etc.)
_INDEX_PATTERN = re.compile(r"\[[^\]]*\]")
# Pre-compiled regex for collapsing multiple consecutive dots into a single dot
_MULTI_DOT_PATTERN = re.compile(r"\.{2,}")


def _normalize_indexed_path(path: str) -> str:
    """Normalize an indexed path by removing array indices and brackets.

    Uses single-pass regex substitution for O(N) complexity instead of
    repeated string replacement which could be O(N²) in the worst case.
    """
    normalized = _INDEX_PATTERN.sub(".", path)
    normalized = _MULTI_DOT_PATTERN.sub(".", normalized)
    return normalized.strip(".")


class VariableCollector(NodeVisitor):
    """Node visitor that collects all variable references in a Jinja2 template AST.

    This visitor traverses the Jinja2 template's AST (Abstract Syntax Tree) and
    collects all variable names, tracking their usage locations and parent nodes.
    It handles nested variables including dictionary access and attribute access.
    """

    def __init__(self) -> None:
        """Initialize the variable collector with empty collections."""
        # Dictionary of variable names to their paths (e.g., {'user': {'user', 'user.name', 'user.address.city'}})
        self.variables: dict[str, set[str]] = {}

        # Track all visited nodes for analysis
        self.visited_nodes: list[Node] = []

        # Track the current traversal path
        self._current_path: list[str] = []

        # Track the total number of AST nodes
        self.node_count: int = 0

        # Track iteration variables to avoid treating them as regular variables
        self.current_iteration_vars: set[str] = set()

    def visit(self, node: Node, *args: object, **kwargs: object) -> object:
        """Visit a node in the AST and track its existence.

        Args:
            node: The AST node to visit
            *args: Additional positional arguments passed to parent
            **kwargs: Additional keyword arguments passed to parent

        Returns:
            Result from parent visit method

        """
        self.node_count += 1
        self.visited_nodes.append(node)
        return super().visit(node, *args, **kwargs)

    def _add_variable(self, name: str, full_path: str) -> None:
        """Add a variable reference to the collected variables.

        Args:
            name: The base variable name
            full_path: The full path of the variable (e.g., 'user.name')

        """
        if name not in self.variables:
            self.variables[name] = set()

        self.variables[name].add(full_path)

    def visit_Name(self, node: nodes.Name) -> None:
        """Visit a name node which represents a variable reference.

        Args:
            node: The name node to visit

        """
        if node.ctx == "load":  # Only consider variables being loaded/read
            name = node.name
            if self._current_path:
                # Build path in correct order (outermost attribute first)
                segments_rev = list(reversed(self._current_path))
                parts: list[str] = []
                for part in segments_rev:
                    if part.startswith("["):
                        parts.append(part)
                    else:
                        parts.append("." + part)
                full_path = name + "".join(parts)
            else:
                full_path = name

            # Store the base name and the full path
            self._add_variable(name, full_path)

        # Visit child nodes if any
        self.generic_visit(node)

    def visit_Getattr(self, node: nodes.Getattr) -> None:
        """Visit an attribute access node (e.g., user.name).

        Args:
            node: The attribute access node

        """
        # Save attribute name to path
        self._current_path.append(node.attr)

        # Visit the node being accessed (e.g., the 'user' in 'user.name')
        self.visit(node.node)

        # If the object is a simple Name, capture two-level parent path (e.g., user.address)
        if isinstance(node.node, nodes.Name):
            parent_path = f"{node.node.name}.{node.attr}"
            self._add_variable(node.node.name, parent_path)

        # Remove attribute from path after traversal
        self._current_path.pop()

    def visit_Getitem(self, node: nodes.Getitem) -> None:
        """Visit an item access node (e.g., user['name'] or items[0]).

        Args:
            node: The item access node

        """
        # Save the current path for later use
        original_path = list(self._current_path)

        # Try to determine the key if it's a constant
        if isinstance(node.arg, nodes.Const):
            key = str(node.arg.value)
            self._current_path.append(f"[{key}]")
        else:
            # For dynamic keys, use a placeholder and track the variable used as index
            self._current_path.append("[*]")
            if isinstance(node.arg, nodes.Name):
                self._add_variable(node.arg.name, node.arg.name)

        # Visit the node being accessed
        self.visit(node.node)

        # Special handling for array access
        if isinstance(node.node, nodes.Name):
            array_name = node.node.name
            array_path = f"{array_name}"
            if original_path:
                array_path = ".".join([*original_path, array_name])

            # Create array access notation (e.g., "items[0]")
            if isinstance(node.arg, nodes.Const):
                index_notation = f"{array_path}[{node.arg.value}]"
            else:
                index_notation = f"{array_path}[*]"

            # Add the array name and indexed access to variables
            if array_name not in self.variables:
                self.variables[array_name] = set()
            self.variables[array_name].add(array_name)
            self.variables[array_name].add(index_notation)

            # Add the indexed variable itself as a top-level key (e.g., items[0])
            if isinstance(node.arg, nodes.Const):
                idx_key = f"{array_name}[{node.arg.value}]"
                self._add_variable(idx_key, idx_key)

        # Remove key from path after traversal
        self._current_path.pop()

    def visit_For(self, node: nodes.For) -> None:
        """Visit a for-loop node and track iteration variables.

        Args:
            node: The for-loop node

        """
        # Save the target name (iteration variable)
        target_name = node.target.name if isinstance(node.target, nodes.Name) else "[complex-target]"

        # Add the iteration variable to our variables
        self._add_variable(target_name, target_name)

        # Track the iteration variable
        if isinstance(node.target, nodes.Name):
            self.current_iteration_vars.add(target_name)

        # Visit the iterable
        self.visit(node.iter)

        # Visit the body with the iteration variable in scope
        for child in node.body:
            self.visit(child)

        # Visit the else body if it exists
        if node.else_:
            for child in node.else_:
                self.visit(child)

        # Remove the iteration variable from tracking
        if isinstance(node.target, nodes.Name):
            self.current_iteration_vars.remove(target_name)

    def visit_If(self, node: nodes.If) -> None:
        """Visit an if-statement node.

        Args:
            node: The if-statement node

        """
        # Visit the test condition
        self.visit(node.test)

        # Visit the body
        for child in node.body:
            self.visit(child)

        # Visit the else body if it exists
        if node.else_:
            for child in node.else_:
                self.visit(child)

    def visit_Macro(self, node: nodes.Macro) -> None:
        """Visit a macro definition.

        Args:
            node: The macro definition node

        """
        # Add macro name as a defined variable
        self._add_variable(node.name, node.name)

        # Visit the macro body
        for child in node.body:
            self.visit(child)

    def visit_Call(self, node: nodes.Call) -> None:
        """Visit a function call node.

        Args:
            node: The function call node

        """
        # Visit the function being called
        self.visit(node.node)

        # Visit all arguments
        for arg in node.args:
            self.visit(arg)

        # Visit all keyword arguments
        for kwarg in node.kwargs:
            self.visit(kwarg)


def collect_template_variables(template_source: str, env: Environment | None = None) -> tuple[dict[str, set[str]], int]:
    """Collect all variables used in a Jinja2 template.

    Args:
        template_source: The source code of the template
        env: Optional Jinja2 environment to use for parsing

    Returns:
        Tuple containing:
            - Dictionary mapping base variable names to sets of full variable paths
            - Total number of AST nodes in the template

    Raises:
        jinja2.exceptions.TemplateSyntaxError: If the template contains syntax errors

    """
    # Create a default environment if none provided
    if env is None:
        # Set autoescape to True by default for better security
        # Set autoescape=True directly in the constructor to satisfy S701
        env = Environment(autoescape=True)

    # Parse the template into an AST
    ast = env.parse(template_source)

    # Create and use our visitor
    collector = VariableCollector()
    collector.visit(ast)

    # Ensure variables are properly initialized even if none are found
    if not collector.variables:
        collector.variables = {}

    # Process the variables to ensure they're properly structured
    result: dict[str, set[str]] = {}
    for name, paths in collector.variables.items():
        if name not in result:
            result[name] = set()
        result[name].update(paths)

        # Add the base name itself if it's not already there
        result[name].add(name)

    # Add generic versions of indexed paths (e.g., items[0].name -> items.name)
    for paths in result.values():
        extra = {_normalize_indexed_path(p) for p in paths if "[" in p}
        paths.update(extra)

    return result, collector.node_count


def flatten_variables(variables: dict[str, set[str]]) -> set[str]:
    """Flatten the nested structure of collected variables into a simple set.

    Args:
        variables: Dictionary mapping base variable names to sets of full paths

    Returns:
        Set of all variable paths

    """
    result: set[str] = set()

    for paths in variables.values():
        result.update(paths)

    return result


def _descend_into_array_items(current_schema: SchemaDict) -> SchemaDict:
    """If schema is an array type, descend into its items schema."""
    if "type" in current_schema and current_schema["type"] == "array" and "items" in current_schema:
        return cast("SchemaDict", current_schema["items"])
    return current_schema


def _navigate_to_property(current_schema: SchemaDict, part: str) -> SchemaDict | None:
    """Navigate to a nested property in the schema, returning None if not found."""
    properties = current_schema.get("properties")
    if isinstance(properties, dict):
        prop_dict = cast("dict[str, object]", properties)
        prop_value = prop_dict.get(part)
        if isinstance(prop_value, dict):
            return cast("SchemaDict", prop_value)
    return None


def _validate_path_against_schema(path: str, base_var: str, base_path: str, schema: dict[str, object]) -> bool:
    """Validate a single variable path against a JSON schema."""
    if path == base_var:
        return True

    parts = path.split(".")[1:]  # Skip the first part (base_var)
    properties = cast("dict[str, object]", schema.get("properties", {}))
    current_schema = cast("SchemaDict", properties[base_path])

    for part in parts:
        if part == "[*]":
            if "items" in current_schema:
                current_schema = cast("SchemaDict", current_schema["items"])
                continue
            return False

        current_schema = _descend_into_array_items(current_schema)
        next_schema = _navigate_to_property(current_schema, part)
        if next_schema is None:
            return False
        current_schema = next_schema

    return True


def validate_variables_against_schema(
    variables: dict[str, set[str]], schema: dict[str, object], prefix: str = ""
) -> list[str]:
    """Compare collected template variables against a JSON schema to find undefined variables.

    Args:
        variables: Dictionary of collected variables
        schema: JSON schema to validate against
        prefix: Current prefix for nested property path

    Returns:
        List of undefined variables that are not in the schema

    """
    undefined_vars: list[str] = []

    # Process each base variable
    for base_var, paths in variables.items():
        # The base path is usually the top-level key
        base_path = prefix + base_var if prefix else base_var

        # Check if the base variable exists in the schema
        schema_properties = cast("dict[str, object]", schema.get("properties", {}))
        if not schema_properties or base_path not in schema_properties:
            # Base variable doesn't exist in schema
            undefined_vars.extend(paths)  # Add all paths using this base
            continue

        # Use list extension for better performance
        undefined_vars.extend(
            [path for path in paths if not _validate_path_against_schema(path, base_var, base_path, schema)]
        )

    return undefined_vars


def count_loop_depth(ast: Node) -> int:
    """Count the maximum nesting level of loops in a template AST.

    Args:
        ast: The template AST to analyze

    Returns:
        Maximum loop nesting depth

    """
    max_depth = [0]  # Use a list to allow modification from inner scope
    current_depth = [0]

    # Define a visitor class that tracks loop depth
    class LoopDepthVisitor(NodeVisitor):
        def visit_For(self, node: nodes.For) -> None:
            current_depth[0] += 1
            max_depth[0] = max(max_depth[0], current_depth[0])

            # Visit the body with increased depth
            for child in node.body:
                self.visit(child)

            # Visit the else clause if it exists
            if node.else_:
                for child in node.else_:
                    self.visit(child)

            current_depth[0] -= 1

    # Run the visitor
    visitor = LoopDepthVisitor()
    visitor.visit(ast)

    return max_depth[0]


def inspect_template(template_source: str, environment_config: dict[str, Any] | None = None) -> list[ValidationIssue]:
    """Inspect a Jinja template for syntax errors and other issues.

    Args:
        template_source: The source code of the template to inspect
        environment_config: Optional configuration for the Jinja environment

    Returns:
        List of validation issues found in the template

    """
    issues = []

    # Create a Jinja environment with the provided configuration
    env_kwargs = environment_config or {}

    # Use select_autoescape to ensure autoescaping is enabled for HTML and XML
    if "autoescape" not in env_kwargs:
        env_kwargs["autoescape"] = select_autoescape(["html", "xml"])

    # Set autoescape=True directly in the constructor to satisfy S701
    env = Environment(autoescape=True, **{k: v for k, v in env_kwargs.items() if k != "autoescape"})

    try:
        # Try to parse the template
        env.parse(template_source)
    except jinja2.exceptions.TemplateSyntaxError as e:
        # Handle syntax errors
        issues.append(
            ValidationIssue(
                path=f"line {e.lineno}",
                keyword="template_syntax",
                message=f"Template syntax error: {e.message} at line {e.lineno}",
            )
        )
    except (jinja2.exceptions.TemplateError, ValueError, TypeError) as e:
        # Handle specific template parsing errors
        issues.append(
            ValidationIssue(
                path="$",
                keyword="template_error",
                message=f"Template error: {e!s}",
            )
        )

    return issues
