"""CLI layer (thin/delegates to engine)."""

import typer

from .commands.evaluate import evaluate
from .commands.fixtures import list_fixtures
from .commands.qualify_document import qualify_document
from .commands.results import results
from .commands.run import run

app = typer.Typer(
    name="llm-benchmark",
    help="LLM Model Benchmark Tool for Nohiki",
    no_args_is_help=True,
)

app.command()(run)
app.command()(evaluate)
app.command(name="qualify-document")(qualify_document)
app.command()(results)
app.command(name="fixtures")(list_fixtures)


def main() -> None:
    """CLI entry point for the ``llm-benchmark`` script."""
    app()
