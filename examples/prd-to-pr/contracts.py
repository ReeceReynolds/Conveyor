"""Contracts for the PRD -> PR factory: what each agent receives and must produce.

Each agent's `brief.input` and `brief.output` name one of these models, so one agent's output
is exactly the next agent's input:

    PRD -> TechnicalRequirements -> TaskList -> CodeChanges -> ReviewVerdict

Every model is frozen and rejects unknown fields, so an agent that invents a field or drops a
required one fails validation instead of passing a silently different shape downstream. Field
descriptions are part of the contract: they are published in the JSON Schema each agent version
stores and are what a model reads when producing structured output.
"""

# ruff: noqa: INP001 -- Conveyor imports contract modules from the project root by path (ADR 0011)

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

type Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""Non-blank text, with surrounding whitespace removed."""

type Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Z]+-[0-9]+$")]
"""A short stable id such as `REQ-1` or `TASK-3`, for cross-referencing between contracts."""

# A path segment other than `.` or `..`, without look-around: JSON Schema consumers such as
# structured-output APIs (and pydantic-core's regex engine) often do not support it.
_SEGMENT = r"(?:[^/\\.]|\.[^/\\.]|\.\.[^/\\])[^/\\]*"
type RepoPath = Annotated[str, StringConstraints(pattern=rf"^{_SEGMENT}(?:/{_SEGMENT})*$")]
"""A POSIX path relative to the repository root that stays inside it: no leading `/`, no `..`."""

type Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
"""A full, lowercase Git commit SHA."""


class Contract(BaseModel):
    """Base for every contract: immutable and strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _check_unique(ids: Iterable[str], kind: str) -> None:
    seen: set[str] = set()
    for item_id in ids:
        if item_id in seen:
            msg = f"duplicate {kind} id {item_id!r}"
            raise ValueError(msg)
        seen.add(item_id)


# --- fetch-prd output, requirements-analyst input -----------------------------------------


class PRD(Contract):
    """A product requirements document, as fetched from the issue that triggered the run."""

    title: Text = Field(description="The feature's name, as the product owner wrote it.")
    problem: Text = Field(description="The user problem the feature solves, and for whom.")
    goals: tuple[Text, ...] = Field(
        min_length=1, description="Outcomes the feature must achieve, in priority order."
    )
    non_goals: tuple[Text, ...] = Field(
        default=(), description="Things explicitly out of scope, to stop scope creep."
    )
    user_stories: tuple[Text, ...] = Field(
        default=(), description="'As a <user>, I want <goal> so that <reason>' statements."
    )
    source_url: Text | None = Field(
        default=None, description="Where the PRD was fetched from, such as the issue URL."
    )


# --- requirements-analyst output, task-planner input --------------------------------------


class Priority(StrEnum):
    """How much a requirement matters to the release, using MoSCoW levels."""

    MUST = "must"
    SHOULD = "should"
    COULD = "could"


class Requirement(Contract):
    """One precise, testable statement of what the system must do."""

    id: Identifier = Field(description="Stable id, such as 'REQ-1', that tasks refer to.")
    statement: Text = Field(description="What the system must do, stated so it can be tested.")
    rationale: Text = Field(description="Which PRD goal or user story this requirement serves.")
    priority: Priority = Field(description="How much the requirement matters to the release.")
    acceptance_criteria: tuple[Text, ...] = Field(
        min_length=1, description="Observable conditions that show the requirement is met."
    )


class TechnicalRequirements(Contract):
    """The PRD restated as precise, testable technical requirements."""

    summary: Text = Field(description="One paragraph on what will be built and why.")
    requirements: tuple[Requirement, ...] = Field(
        min_length=1, description="The requirements, each with a unique id."
    )
    constraints: tuple[Text, ...] = Field(
        default=(),
        description="Technical limits the solution must respect: compatibility, performance, "
        "security or dependencies.",
    )
    open_questions: tuple[Text, ...] = Field(
        default=(),
        description="Ambiguities in the PRD that a human should resolve. Empty when none.",
    )

    @model_validator(mode="after")
    def _requirement_ids_are_unique(self) -> Self:
        _check_unique((requirement.id for requirement in self.requirements), "requirement")
        return self


# --- task-planner output, implementer input -----------------------------------------------


class Task(Contract):
    """One small, independently reviewable unit of implementation work."""

    id: Identifier = Field(description="Stable id, such as 'TASK-1', that other tasks depend on.")
    title: Text = Field(description="What the task does, in the imperative mood.")
    description: Text = Field(description="How to do the task: the approach and files involved.")
    acceptance_criteria: tuple[Text, ...] = Field(
        min_length=1, description="Conditions the implementation must meet to be done."
    )
    requirements: tuple[Identifier, ...] = Field(
        min_length=1, description="Ids of the requirements this task helps satisfy."
    )
    depends_on: tuple[Identifier, ...] = Field(
        default=(), description="Ids of earlier tasks that must be done first."
    )


class TaskList(Contract):
    """The requirements broken into ordered tasks: every dependency comes before its dependant."""

    tasks: tuple[Task, ...] = Field(min_length=1, description="The tasks, in the order to do them.")

    @model_validator(mode="after")
    def _dependencies_come_first(self) -> Self:
        _check_unique((task.id for task in self.tasks), "task")
        seen: set[str] = set()
        for task in self.tasks:
            for dependency in task.depends_on:
                if dependency not in seen:
                    msg = (
                        f"task {task.id!r} depends on {dependency!r}, which is not listed before it"
                    )
                    raise ValueError(msg)
            seen.add(task.id)
        return self


# --- implementer output, code-reviewer input ----------------------------------------------


class ChangeKind(StrEnum):
    """What happened to a file."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class FileChange(Contract):
    """One file the implementer changed."""

    path: RepoPath = Field(description="Path relative to the repository root.")
    kind: ChangeKind = Field(description="Whether the file was added, modified or deleted.")
    summary: Text = Field(description="What changed in the file and why.")


class CodeChanges(Contract):
    """The implementation, committed to a branch and ready for review."""

    branch: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")] = Field(
        description="The branch the changes are committed to.", examples=["feat/export-csv"]
    )
    base_commit: Sha = Field(description="Full SHA of the commit the branch starts from.")
    head_commit: Sha = Field(description="Full SHA of the branch's latest commit.")
    summary: Text = Field(description="What was implemented, written for the pull request body.")
    files: tuple[FileChange, ...] = Field(
        min_length=1, description="Every file changed, each listed once."
    )
    tasks_completed: tuple[Identifier, ...] = Field(
        min_length=1, description="Ids of the tasks these changes complete."
    )

    @model_validator(mode="after")
    def _files_are_listed_once(self) -> Self:
        seen: set[str] = set()
        for change in self.files:
            if change.path in seen:
                msg = f"file {change.path!r} is listed more than once"
                raise ValueError(msg)
            seen.add(change.path)
        return self


# --- code-reviewer output -----------------------------------------------------------------


class Severity(StrEnum):
    """How serious a review finding is."""

    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"
    NIT = "nit"


class Finding(Contract):
    """One problem the reviewer found."""

    severity: Severity = Field(
        description="'blocker' and 'major' findings require rework; 'minor' and 'nit' do not."
    )
    path: RepoPath | None = Field(
        default=None, description="The file the finding is about. Omit for change-wide findings."
    )
    line: Annotated[int, Field(ge=1)] | None = Field(
        default=None, description="1-based line in `path` the finding points at."
    )
    message: Text = Field(description="What is wrong and how to fix it.")

    @model_validator(mode="after")
    def _line_needs_path(self) -> Self:
        if self.line is not None and self.path is None:
            msg = "a finding with a line must also give its path"
            raise ValueError(msg)
        return self


_REWORK = frozenset({Severity.BLOCKER, Severity.MAJOR})


class ReviewVerdict(Contract):
    """The reviewer's decision on the code changes, with the findings behind it.

    A rejection sends the work back to the implementer (the factory's `on_reject` loop), so it
    must carry at least one finding that needs rework; an approval must carry none.
    """

    decision: Literal["approve", "reject"] = Field(
        description="'approve' to pass the changes on, 'reject' to return them for rework."
    )
    summary: Text = Field(description="The overall assessment, in a sentence or two.")
    findings: tuple[Finding, ...] = Field(
        default=(), description="Problems found, most severe first. Empty when there are none."
    )

    @model_validator(mode="after")
    def _decision_matches_findings(self) -> Self:
        needs_rework = any(finding.severity in _REWORK for finding in self.findings)
        if self.decision == "reject" and not needs_rework:
            msg = "a rejection must include at least one 'blocker' or 'major' finding"
            raise ValueError(msg)
        if self.decision == "approve" and needs_rework:
            msg = "an approval cannot include 'blocker' or 'major' findings"
            raise ValueError(msg)
        return self
