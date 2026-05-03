"""Benchmarks for Jinja2 template operations (doc-template-service).

Measures template compilation, validation, rendering, cache key
generation, variable collection, and security checks -- the hot-path
operations for every document generation request.
"""

from __future__ import annotations

import hashlib

import pytest
from jinja2 import Environment
from jinja2.sandbox import SandboxedEnvironment

# Fixtures: realistic templates of varying complexity

_SIMPLE_TEMPLATE = "<h1>{{ name }}</h1><p>{{ title }}</p>"

_RESUME_TEMPLATE = """<!DOCTYPE html>
<html>
<head><title>{{ name }} - Resume</title></head>
<body>
<h1>{{ name }}</h1>
<h2>{{ title }}</h2>
<p>{{ summary }}</p>
<h3>Experience</h3>
{% for job in experience %}
<div class="job">
  <h4>{{ job.company }} -- {{ job.role }}</h4>
  <p>{{ job.start_date }} - {{ job.end_date }}</p>
  <ul>
  {% for bullet in job.bullets %}
    <li>{{ bullet }}</li>
  {% endfor %}
  </ul>
</div>
{% endfor %}
<h3>Skills</h3>
<ul>
{% for skill in skills %}
  <li>{{ skill.name }} ({{ skill.proficiency }})</li>
{% endfor %}
</ul>
<h3>Education</h3>
{% for edu in education %}
<div>{{ edu.institution }} -- {{ edu.degree }} ({{ edu.year }})</div>
{% endfor %}
</body>
</html>"""

_RESUME_CONTEXT: dict[str, object] = {
    "name": "Jane Doe",
    "title": "Senior Software Engineer",
    "summary": "10+ years of experience in distributed systems.",
    "experience": [
        {
            "company": f"Company {i}",
            "role": f"Role {i}",
            "start_date": "2020-01",
            "end_date": "2023-06",
            "bullets": [f"Achievement {j}" for j in range(5)],
        }
        for i in range(4)
    ],
    "skills": [{"name": f"Skill {i}", "proficiency": "Advanced"} for i in range(12)],
    "education": [
        {"institution": "MIT", "degree": "BS Computer Science", "year": 2013},
    ],
}

_SIMPLE_CONTEXT: dict[str, str] = {"name": "Jane Doe", "title": "Engineer"}

# Environment creation (once per config)

_ALLOWED_FILTERS: set[str] = {
    "upper",
    "lower",
    "capitalize",
    "title",
    "trim",
    "replace",
    "truncate",
    "format",
    "float",
    "int",
    "string",
    "list",
    "dict",
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
    "sum",
    "abs",
    "round",
    "default",
}


def _create_sandboxed_env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(autoescape=True)
    env.filters = {name: func for name, func in env.filters.items() if name in _ALLOWED_FILTERS}
    return env


def test_bench_create_sandboxed_env(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating a sandboxed Jinja2 environment."""
    benchmark(_create_sandboxed_env)


def test_bench_create_plain_env(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating a plain Jinja2 environment (baseline)."""
    benchmark(Environment, autoescape=True)


# Template compilation (critical for cold starts and cache misses)


def test_bench_compile_simple(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark compiling a simple 2-variable template."""
    env = _create_sandboxed_env()
    benchmark(env.from_string, _SIMPLE_TEMPLATE)


def test_bench_compile_resume(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark compiling a full resume template with loops."""
    env = _create_sandboxed_env()
    benchmark(env.from_string, _RESUME_TEMPLATE)


# Template rendering (every document generation request)


def test_bench_render_simple(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark rendering a simple template."""
    env = _create_sandboxed_env()
    template = env.from_string(_SIMPLE_TEMPLATE)
    benchmark(template.render, **_SIMPLE_CONTEXT)


def test_bench_render_resume(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark rendering a full resume template."""
    env = _create_sandboxed_env()
    template = env.from_string(_RESUME_TEMPLATE)
    benchmark(template.render, **_RESUME_CONTEXT)


# Cache key generation (every template lookup)


def _make_cache_key(template_source: str, env_id: int) -> str:
    content = f"{template_source}:{env_id}"
    return hashlib.sha256(content.encode()).hexdigest()


def test_bench_cache_key_simple(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark cache key generation for simple template."""
    env = _create_sandboxed_env()
    benchmark(_make_cache_key, _SIMPLE_TEMPLATE, id(env))


def test_bench_cache_key_resume(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark cache key generation for full resume template (~1KB)."""
    env = _create_sandboxed_env()
    benchmark(_make_cache_key, _RESUME_TEMPLATE, id(env))


# Template AST analysis (validation pipeline)


def test_bench_parse_ast_simple(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark parsing template into AST (simple)."""
    env = _create_sandboxed_env()
    benchmark(env.parse, _SIMPLE_TEMPLATE)


def test_bench_parse_ast_resume(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark parsing template into AST (resume with loops)."""
    env = _create_sandboxed_env()
    benchmark(env.parse, _RESUME_TEMPLATE)


def test_bench_count_ast_nodes(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark counting AST nodes (complexity check)."""
    env = _create_sandboxed_env()
    ast = env.parse(_RESUME_TEMPLATE)
    benchmark(lambda: sum(1 for _ in ast.iter_child_nodes()))


# Template size validation (security check)

_MAX_TEMPLATE_SIZE = 100 * 1024


def test_bench_size_check(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark template size validation (len check)."""
    benchmark(lambda: len(_RESUME_TEMPLATE) > _MAX_TEMPLATE_SIZE)


def test_bench_filter_whitelist_check(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark filter whitelist membership test."""
    benchmark(lambda: "upper" in _ALLOWED_FILTERS)


# Full compile+render pipeline (end-to-end hot path)


def test_bench_full_pipeline_simple(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full pipeline: env creation → compile → render (simple)."""

    def pipeline() -> str:
        env = _create_sandboxed_env()
        template = env.from_string(_SIMPLE_TEMPLATE)
        return template.render(**_SIMPLE_CONTEXT)

    benchmark(pipeline)


def test_bench_full_pipeline_resume(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full pipeline: env creation → compile → render (resume)."""

    def pipeline() -> str:
        env = _create_sandboxed_env()
        template = env.from_string(_RESUME_TEMPLATE)
        return template.render(**_RESUME_CONTEXT)

    benchmark(pipeline)
