"""The `conveyor` command-line interface."""

from pathlib import Path
from typing import Annotated

import typer

from conveyor import __version__
from conveyor.cli_agent import agent_app
from conveyor.model import NothingToValidateError, validate_path

app = typer.Typer(
    name="conveyor",
    help="Define, validate and run agent-driven software factories.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="markdown",
    pretty_exceptions_enable=False,
)
app.add_typer(agent_app)


def _count(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"conveyor {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """Define, validate and run agent-driven software factories."""


@app.command()
def validate(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            metavar="PATH",
            help="An agent folder, a factory file, or a project directory with agents/ and "
            "factories/.",
        ),
    ],
) -> None:
    """Check agents and factories against the factory model.

    Prints every problem as `file:line:column: field: message`. Exits 0 when everything is
    valid, 1 when there are problems and 2 on a usage error.
    """
    try:
        report = validate_path(path)
    except NothingToValidateError as error:
        raise typer.BadParameter(str(error), param_hint="PATH") from None

    counts = [
        _count(len(report.agents), "agent", "agents") if report.agents else "",
        _count(len(report.factories), "factory", "factories") if report.factories else "",
    ]
    checked = " and ".join(count for count in counts if count)
    for issue in report.issues:
        typer.echo(issue.render())
    if report.ok:
        typer.echo(f"Validated {checked}: no problems found.")
        return
    typer.echo(f"Found {_count(len(report.issues), 'problem', 'problems')} in {checked}.")
    raise typer.Exit(code=1)
