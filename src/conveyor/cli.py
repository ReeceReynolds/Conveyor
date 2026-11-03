"""The `conveyor` command-line interface.

This is the only module that imports Typer (an import-linter contract, ADR 0014). Commands are
thin: they call library functions and format the results as plain text. Exit codes follow ADR
0010: `0` success, `1` the command ran and found problems (an invalid agent, an unknown
version), `2` usage errors (a malformed ref, a folder that is not a project).

- `conveyor validate`: check agents and factories against the factory model.
- `conveyor agent publish | history | show | diff`: publish agent versions, list them, show
  one and compare any two.
"""

import getpass
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, NoReturn

import typer

from conveyor import __version__
from conveyor.model import NothingToValidateError, dump_yaml, validate_path
from conveyor.model.checks import AGENTS_DIR
from conveyor.registry import (
    AgentSnapshot,
    PublishError,
    RefProblem,
    Side,
    SnapshotError,
    VersionRefError,
    WorkingCopy,
    check_agent_name,
    diff_versions,
    load_snapshot,
    previous_version,
    publish,
    resolve,
    short_id,
)
from conveyor.storage import AgentVersionRecord, StorageError, Store

app = typer.Typer(
    name="conveyor",
    help="Define, validate and run agent-driven software factories.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="markdown",
    pretty_exceptions_enable=False,
)


def _count(count: int, singular: str, plural: str) -> str:
    return f"{count:,} {singular if count == 1 else plural}"


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


# --- conveyor agent ---------------------------------------------------------------------------

agent_app = typer.Typer(
    name="agent",
    help="Publish agent versions, list them, show one and compare any two.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Clock:
    """Where `conveyor agent publish` reads the time from.

    The commands look for one in the Click context object and fall back to the system clock,
    so tests pin publish times with `CliRunner().invoke(app, args, obj=Clock(now=...))`.

    Attributes:
        now: Returns the current time, timezone-aware.
    """

    now: Callable[[], datetime] = field(default=_now)


# --- Arguments and options --------------------------------------------------------------------


def _agent_name(name: str) -> str:
    try:
        return check_agent_name(name)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from None


def _required_text(value: str | None) -> str | None:
    if value is not None and not value.strip():
        message = "must not be blank"
        raise typer.BadParameter(message)
    return value


NameArgument = Annotated[
    str,
    typer.Argument(
        metavar="NAME", callback=_agent_name, help="The agent's name: its folder in agents/."
    ),
]
ProjectOption = Annotated[
    Path,
    typer.Option(
        "--project",
        file_okay=False,
        help="The project folder, holding agents/ and the registry in .conveyor/.",
    ),
]


def _project(project: Path) -> Path:
    if not (project / AGENTS_DIR).is_dir():
        message = f"{project} is not a Conveyor project: it has no {AGENTS_DIR}/ folder"
        raise typer.BadParameter(message, param_hint="'--project'")
    return project


def _default_author() -> str:
    try:
        return getpass.getuser()
    except OSError:
        message = "cannot tell who you are from the environment; pass --author"
        raise typer.BadParameter(message, param_hint="'--author'") from None


# --- Output -----------------------------------------------------------------------------------


def _bytes(text: str) -> str:
    return _count(len(text.encode()), "byte", "bytes")


FAILED: Final = 1
"""Exit code for problems: an invalid agent, an unknown version, an unreadable registry."""

FAILED_WITH_EXIT_CODE: Final = 2
"""Exit code for those problems under `diff --exit-code`, where 1 means "differences"."""


def _fail(message: str, code: int = FAILED) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


@contextmanager
def _reporting(project: Path, outcome: str = "nothing done", code: int = FAILED) -> Generator[None]:
    """Turn the service's errors into messages and exit codes.

    Args:
        project: The project folder, already checked.
        outcome: What an invalid working copy means for the command, e.g. `nothing published`.
        code: The exit code for problems (usage errors always exit 2).

    Yields:
        Nothing; the block runs inside.
    """
    try:
        yield
    except PublishError as error:
        # Problems go to stdout, as `conveyor validate` prints them, so tools parse both alike.
        for issue in error.issues:
            typer.echo(issue.render())
        problems = _count(len(error.issues), "problem", "problems")
        typer.echo(f"Found {problems} in {error.name}; {outcome}.")
        raise typer.Exit(code=code) from None
    except VersionRefError as error:
        if error.problem is RefProblem.MALFORMED:
            raise typer.BadParameter(str(error)) from None
        _fail(str(error), code)
    except (StorageError, SnapshotError) as error:
        _fail(f"The registry in {project} cannot be read: {error}", code)


def _version(record: AgentVersionRecord) -> str:
    return f"{record.agent} v{record.sequence} ({short_id(record.content_id)})"


def _date(record: AgentVersionRecord, layout: str = "%Y-%m-%d %H:%M") -> str:
    return record.created_at.strftime(layout)


def _show_lines(record: AgentVersionRecord, snapshot: AgentSnapshot) -> list[str]:
    parent = "nothing (first version)"
    if record.parent_sequence is not None:
        parent = f"v{record.parent_sequence}"
    message_first, *message_rest = record.message.splitlines() or [""]
    lines = [
        _version(record),
        f"Content ID:   {record.content_id}",
        f"Follows:      {parent}",
        f"Author:       {record.author}",
        f"Published:    {_date(record, '%Y-%m-%d %H:%M:%S UTC')}",
        f"Message:      {message_first}",
        *(f"{' ' * 14}{line}".rstrip() for line in message_rest),
        "",
        "agent.yaml",
        *(f"    {line}".rstrip() for line in dump_yaml(snapshot.agent).splitlines()),
        "",
        f"Instructions: {snapshot.agent.brief.instructions} ({_bytes(snapshot.instructions)})",
    ]
    files = snapshot.eval_files
    total = sum(len(file.content.encode()) for file in files)
    contents = f"{_count(len(files), 'file', 'files')}, {_count(total, 'byte', 'bytes')}"
    lines.append(f"Eval suite:   {snapshot.agent.quality_gate.suite} ({contents})")
    lines.extend(f"    {file.path} ({_bytes(file.content)})" for file in files)
    return lines


# --- Commands ---------------------------------------------------------------------------------


@agent_app.command("publish")
def publish_command(
    ctx: typer.Context,
    name: NameArgument,
    message: Annotated[
        str,
        typer.Option(
            "--message", "-m", callback=_required_text, help="Why you are publishing this version."
        ),
    ],
    author: Annotated[
        str | None,
        typer.Option(callback=_required_text, help="Who is publishing. [default: your user name]"),
    ] = None,
    project: ProjectOption = Path(),
) -> None:
    """Publish agents/NAME/ as the agent's next version.

    Validates the agent first and refuses to publish it if there are problems, printing each
    as `file:line:column: field: message`. Publishing content identical to the latest version
    does nothing.
    """
    project = _project(project)
    clock = ctx.find_object(Clock) or Clock()
    who = author if author is not None else _default_author()
    with _reporting(project, "nothing published"):
        result = publish(project, name, author=who, message=message, now=clock.now())

    record = result.record
    if not result.created:
        typer.echo(
            f"{name} is unchanged since v{record.sequence} ({short_id(record.content_id)}); "
            "nothing published"
        )
    elif result.diff is None:
        typer.echo(f"Published {_version(record)}: first version")
    else:
        # A summary reads `<name> vN → vM: <changes>`; names and labels never hold `: `.
        changes = result.diff.summary().split(": ", 1)[1]
        typer.echo(f"Published {_version(record)}: {changes}")


@agent_app.command("history")
def history_command(name: NameArgument, project: ProjectOption = Path()) -> None:
    """List an agent's versions, newest first.

    Each line reads `vN  short-id  date  author  message`, with dates in UTC and only the
    first line of each message.
    """
    project = _project(project)
    with _reporting(project), Store.open(project) as store:
        records = store.registry.history(name)
    if not records:
        _fail(f"agent {name!r} has no published versions")
    sequence_width = max(len(f"v{record.sequence}") for record in records)
    author_width = max(len(record.author) for record in records)
    for record in records:
        summary = (record.message.splitlines() or [""])[0]
        columns = (
            f"v{record.sequence}".ljust(sequence_width),
            short_id(record.content_id),
            _date(record),
            record.author.ljust(author_width),
            summary,
        )
        typer.echo("  ".join(columns).rstrip())


@agent_app.command("show")
def show_command(
    target: Annotated[
        str,
        typer.Argument(
            metavar="NAME[@REF]",
            help="The agent, and optionally a version: latest (the default), vN or a content "
            "ID prefix of at least 4 hex characters.",
        ),
    ],
    project: ProjectOption = Path(),
) -> None:
    """Show a version: who published it and why, its agent.yaml and its files."""
    name, at, ref = target.partition("@")
    name = _agent_name(name)
    project = _project(project)
    with _reporting(project), Store.open(project) as store:
        record = resolve(store, name, ref if at else None)
        snapshot = load_snapshot(store, record)
    for line in _show_lines(record, snapshot):
        typer.echo(line)


# One parameter per argument and option of the command; Typer reads them from the signature.
@agent_app.command("diff")
def diff_command(  # noqa: PLR0913
    name: NameArgument,
    old_ref: Annotated[
        str | None,
        typer.Argument(
            metavar="[FROM]",
            help="The old version: latest, vN or a content ID prefix. [default: the version "
            "before the latest, or the latest with --working]",
            show_default=False,
        ),
    ] = None,
    new_ref: Annotated[
        str | None,
        typer.Argument(
            metavar="[TO]",
            help="The new version. [default: the latest]",
            show_default=False,
        ),
    ] = None,
    *,
    working: Annotated[
        bool,
        typer.Option(
            "--working", help="Compare with agents/NAME/ on disk: what publishing would record."
        ),
    ] = False,
    summary: Annotated[
        bool, typer.Option("--summary", help="Print only the one-line summary.")
    ] = False,
    exit_code: Annotated[
        bool,
        typer.Option(
            "--exit-code",
            help="Exit with 1 if there are differences and 0 if not, like git diff --exit-code;"
            " problems then exit with 2.",
        ),
    ] = False,
    project: ProjectOption = Path(),
) -> None:
    """Compare two versions of an agent, or a version with the working copy.

    With no versions given, compares the version before the latest with the latest. Exits 0
    whether or not there are differences, unless --exit-code is given: then 1 means there are
    differences, and problems (an unknown version, an unreadable registry) exit with 2.
    """
    if working and new_ref is not None:
        message = "give either TO or --working, not both"
        raise typer.BadParameter(message, param_hint="TO")
    project = _project(project)
    failed = FAILED_WITH_EXIT_CODE if exit_code else FAILED
    with (
        _reporting(project, "cannot compare the working copy", failed),
        Store.open(project) as store,
    ):
        old: Side
        new: Side
        if working:
            old, new = resolve(store, name, old_ref), WorkingCopy(project)
        elif old_ref is None:
            new = resolve(store, name, None)
            if (previous := previous_version(store, new)) is None:
                _fail(
                    f"{name} has only one version, v{new.sequence} "
                    f"({short_id(new.content_id)}); use --working to compare it with "
                    f"agents/{name}/ on disk",
                    failed,
                )
            old = previous
        else:
            old, new = resolve(store, name, old_ref), resolve(store, name, new_ref)
        result = diff_versions(store, name, old, new)

    if summary:
        typer.echo(result.summary())
    else:
        typer.echo(result.render(), nl=False)
    if exit_code and not result.diff.empty:
        raise typer.Exit(code=1)


app.add_typer(agent_app)
