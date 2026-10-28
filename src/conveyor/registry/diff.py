"""Structured diffs between agent snapshots, in the terms of the factory model.

A diff is a tree: the blocks that changed (Brief, Capabilities, Quality Gate), the components
inside each (instructions, contract pair, model profile, toolkit, eval suite) and the primitive
changes inside those (an instruction, a contract, a model setting, a tool, a permission, an eval
case, a threshold). `summarise` turns a diff into one line and `render` into a full report:

    implementer v1 → v2: Capabilities changed; model profile changed; model switched (a → b)

Every field of a snapshot maps to exactly one place in the tree, so a diff is empty exactly
when the two snapshots have the same content ID.
"""

import difflib
import json
from collections.abc import Callable, Iterator, Sequence
from enum import StrEnum
from itertools import groupby
from typing import NamedTuple

from pydantic import Field, JsonValue

from conveyor.model.agent import Agent, ModelProfile, Routing
from conveyor.model.base import ConfigModel
from conveyor.registry.canonical import canonical_json
from conveyor.registry.snapshot import AgentSnapshot

ARROW = "→"
MINUS = "\N{MINUS SIGN}"  # So line counts read like GitHub's, e.g. "+3 \N{MINUS SIGN}1".
MAX_SUMMARY_CHANGES = 6
"""Most changes a summary spells out; the rest are counted as `and N more`."""
MAX_SUMMARY_VALUE = 40
"""Longest value a summary shows before eliding the rest with `…`."""


class Block(StrEnum):
    """The three blocks every agent is made of."""

    BRIEF = "Brief"
    CAPABILITIES = "Capabilities"
    QUALITY_GATE = "Quality Gate"


class Component(StrEnum):
    """Groups of primitives with one job, in the order diffs list them."""

    INSTRUCTIONS = "instructions"
    CONTRACT_PAIR = "contract pair"
    MODEL_PROFILE = "model profile"
    TOOLKIT = "toolkit"
    EVAL_SUITE = "eval suite"


BLOCK_OF: dict[Component, Block] = {
    Component.INSTRUCTIONS: Block.BRIEF,
    Component.CONTRACT_PAIR: Block.BRIEF,
    Component.MODEL_PROFILE: Block.CAPABILITIES,
    Component.TOOLKIT: Block.CAPABILITIES,
    Component.EVAL_SUITE: Block.QUALITY_GATE,
}
"""The block each component belongs to."""


class Primitive(StrEnum):
    """The kinds of unit a change is made to."""

    INSTRUCTION = "instruction"
    CONTRACT = "contract"
    MODEL_SETTING = "model setting"
    TOOL = "tool"
    PERMISSION = "permission"
    EVAL_CASE = "eval case"
    THRESHOLD = "threshold"


class Change(StrEnum):
    """How a primitive changed."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class TextDiff(ConfigModel):
    """A line-by-line diff of two texts, in unified format."""

    unified: str = Field(description="The diff, with `---`/`+++` headers and `@@` hunks.")
    added: int = Field(ge=0, description="Number of lines added.")
    removed: int = Field(ge=0, description="Number of lines removed.")


class PrimitiveChange(ConfigModel):
    """One change to one primitive.

    `old` is meaningful for removed and changed primitives and `new` for added and changed
    ones; the absent side is `None`.
    """

    kind: Primitive = Field(description="What kind of primitive changed.")
    field: str = Field(
        description="Dotted path of the snapshot field, e.g. 'agent.capabilities.model.id'."
    )
    item: str | None = Field(
        default=None,
        description=(
            "Which part of the field changed: a tool or secret name, an eval file path, or a "
            "JSON Pointer into a contract schema. None when the field changed as a whole."
        ),
    )
    change: Change = Field(description="Whether the primitive was added, removed or changed.")
    old: JsonValue = Field(default=None, description="The value before.")
    new: JsonValue = Field(default=None, description="The value after.")
    text_diff: TextDiff | None = Field(
        default=None, description="For instructions and eval files, the line-by-line diff."
    )


class ComponentDiff(ConfigModel):
    """The changes inside one component."""

    name: Component = Field(description="The component.")
    changes: tuple[PrimitiveChange, ...] = Field(description="Its changed primitives, in order.")


class BlockDiff(ConfigModel):
    """The changed components of one block."""

    name: Block = Field(description="The block.")
    components: tuple[ComponentDiff, ...] = Field(description="Its changed components, in order.")


class AgentDiff(ConfigModel):
    """Everything that differs between two snapshots, by block, component and primitive."""

    renamed: tuple[str, str] | None = Field(
        default=None, description="The old and new agent name, if the name changed."
    )
    blocks: tuple[BlockDiff, ...] = Field(default=(), description="Changed blocks, in order.")

    @property
    def empty(self) -> bool:
        """Whether the two snapshots have the same content."""
        return self.renamed is None and not self.blocks

    def changes(self) -> Iterator[tuple[Block, Component, PrimitiveChange]]:
        """Iterate over every primitive change, with the block and component it is in.

        Yields:
            (block, component, change) triples, in diff order.
        """
        for block in self.blocks:
            for component in block.components:
                for change in component.changes:
                    yield block.name, component.name, change


# --- Building a diff --------------------------------------------------------------------------

type _Found = list[tuple[Component, PrimitiveChange]]


def _same(old: JsonValue, new: JsonValue) -> bool:
    # Compare as JSON, not Python: in Python `True == 1` and `1 == 1.0`, in JSON only the latter.
    return canonical_json(old) == canonical_json(new)


class _At(NamedTuple):
    """Where a change goes: its component, the kind of primitive and the snapshot field."""

    component: Component
    kind: Primitive
    field: str


def _value(found: _Found, at: _At, old: JsonValue, new: JsonValue) -> None:
    """Record a change to a single-valued field, where `None` on either side means unset."""
    if _same(old, new):
        return
    change = Change.ADDED if old is None else Change.REMOVED if new is None else Change.CHANGED
    primitive = PrimitiveChange(kind=at.kind, field=at.field, change=change, old=old, new=new)
    found.append((at.component, primitive))


def _members(found: _Found, at: _At, old: Sequence[str], new: Sequence[str]) -> None:
    """Record names added to or removed from a list, or, failing that, a change of order."""
    kind, field = at.kind, at.field
    for name in old:
        if name not in new:
            primitive = PrimitiveChange(
                kind=kind, field=field, item=name, change=Change.REMOVED, old=name
            )
            found.append((at.component, primitive))
    for name in new:
        if name not in old:
            primitive = PrimitiveChange(
                kind=kind, field=field, item=name, change=Change.ADDED, new=name
            )
            found.append((at.component, primitive))
    if set(old) == set(new) and list(old) != list(new):
        primitive = PrimitiveChange(
            kind=kind, field=field, change=Change.CHANGED, old=list(old), new=list(new)
        )
        found.append((at.component, primitive))


def _lines(text: str) -> list[str]:
    """Split text into newline-terminated lines, marking a missing final newline as Git does."""
    if not text:
        return []
    lines = [f"{line}\n" for line in text.split("\n")]
    if text.endswith("\n"):
        lines.pop()
    else:
        lines[-1] += "\\ No newline at end of file\n"
    return lines


def text_diff(old: str, new: str, *, old_name: str, new_name: str) -> TextDiff:
    """Diff two texts line by line, with three lines of context.

    Args:
        old: The text before.
        new: The text after.
        old_name: File name for the `---` header, shown as `a/<old_name>`.
        new_name: File name for the `+++` header, shown as `b/<new_name>`.

    Returns:
        The unified diff and its line counts; an empty diff if the texts are equal.
    """
    diff = list(
        difflib.unified_diff(_lines(old), _lines(new), f"a/{old_name}", f"b/{new_name}", n=3)
    )
    body = diff[2:]  # The two file headers also start with `-` and `+`.
    added = sum(line.startswith("+") for line in body)
    removed = sum(line.startswith("-") for line in body)
    return TextDiff(unified="".join(diff), added=added, removed=removed)


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def json_changes(
    old: JsonValue, new: JsonValue, pointer: str = ""
) -> Iterator[tuple[Change, str, JsonValue, JsonValue]]:
    """Find where two JSON values differ, located by JSON Pointer (RFC 6901).

    Objects are compared key by key and arrays of equal length item by item. An array whose
    length changed, or a value whose type changed, is reported as one change at its pointer.

    Args:
        old: The value before.
        new: The value after.
        pointer: Where `old` and `new` are in their documents.

    Yields:
        (change, pointer, old value, new value), in key order; the absent side of an addition
        or removal is `None`.
    """
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            at = f"{pointer}/{_escape(key)}"
            if key not in new:
                yield Change.REMOVED, at, old[key], None
            elif key not in old:
                yield Change.ADDED, at, None, new[key]
            else:
                yield from json_changes(old[key], new[key], at)
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for index, (old_item, new_item) in enumerate(zip(old, new, strict=True)):
            yield from json_changes(old_item, new_item, f"{pointer}/{index}")
    elif not _same(old, new):
        yield Change.CHANGED, pointer, old, new


def _schema(found: _Found, field: str, old: JsonValue, new: JsonValue) -> None:
    for change, pointer, old_value, new_value in json_changes(old, new):
        primitive = PrimitiveChange(
            kind=Primitive.CONTRACT,
            field=field,
            item=pointer,
            change=change,
            old=old_value,
            new=new_value,
        )
        found.append((Component.CONTRACT_PAIR, primitive))


def _routing(found: _Found, old: Routing | None, new: Routing | None) -> None:
    field = "agent.capabilities.model.routing"
    if old is None or new is None:
        old_value = None if old is None else old.model_dump(mode="json")
        new_value = None if new is None else new.model_dump(mode="json")
        at = _At(Component.MODEL_PROFILE, Primitive.MODEL_SETTING, field)
        _value(found, at, old_value, new_value)
        return
    settings: tuple[tuple[str, JsonValue, JsonValue], ...] = (
        (
            "only",
            None if old.only is None else list(old.only),
            None if new.only is None else list(new.only),
        ),
        ("allow_fallbacks", old.allow_fallbacks, new.allow_fallbacks),
    )
    for name, old_value, new_value in settings:
        # `only: null` means any provider, so setting or clearing it is a change, not a removal.
        if not _same(old_value, new_value):
            primitive = PrimitiveChange(
                kind=Primitive.MODEL_SETTING,
                field=f"{field}.{name}",
                change=Change.CHANGED,
                old=old_value,
                new=new_value,
            )
            found.append((Component.MODEL_PROFILE, primitive))


def _model(found: _Found, old: ModelProfile, new: ModelProfile) -> None:
    settings: tuple[tuple[str, JsonValue, JsonValue], ...] = (
        ("provider", old.provider, new.provider),
        ("id", old.id, new.id),
        ("temperature", old.temperature, new.temperature),
        ("top_p", old.top_p, new.top_p),
        ("max_tokens", old.max_tokens, new.max_tokens),
    )
    for name, old_value, new_value in settings:
        field = f"agent.capabilities.model.{name}"
        _value(
            found,
            _At(Component.MODEL_PROFILE, Primitive.MODEL_SETTING, field),
            old_value,
            new_value,
        )
    _routing(found, old.routing, new.routing)


def _agent(found: _Found, old: Agent, new: Agent) -> None:
    at = _At(Component.INSTRUCTIONS, Primitive.INSTRUCTION, "agent.brief.instructions")
    _value(found, at, str(old.brief.instructions), str(new.brief.instructions))
    for name, old_ref, new_ref in (
        ("input", old.brief.input, new.brief.input),
        ("output", old.brief.output, new.brief.output),
    ):
        at = _At(Component.CONTRACT_PAIR, Primitive.CONTRACT, f"agent.brief.{name}")
        _value(found, at, old_ref, new_ref)

    old_caps, new_caps = old.capabilities, new.capabilities
    _model(found, old_caps.model, new_caps.model)
    at = _At(Component.TOOLKIT, Primitive.TOOL, "agent.capabilities.tools")
    _members(found, at, old_caps.tools, new_caps.tools)
    old_perms, new_perms = old_caps.permissions, new_caps.permissions
    at = _At(Component.TOOLKIT, Primitive.PERMISSION, "agent.capabilities.permissions.network")
    _value(found, at, old_perms.network, new_perms.network)
    at = _At(Component.TOOLKIT, Primitive.PERMISSION, "agent.capabilities.permissions.secrets")
    _members(found, at, old_perms.secrets, new_perms.secrets)

    old_gate, new_gate = old.quality_gate, new.quality_gate
    at = _At(Component.EVAL_SUITE, Primitive.EVAL_CASE, "agent.quality_gate.suite")
    _value(found, at, str(old_gate.suite), str(new_gate.suite))
    for name, old_value, new_value in (
        ("min_pass_rate", old_gate.min_pass_rate, new_gate.min_pass_rate),
        ("repeats", old_gate.repeats, new_gate.repeats),
    ):
        at = _At(Component.EVAL_SUITE, Primitive.THRESHOLD, f"agent.quality_gate.{name}")
        _value(found, at, old_value, new_value)


def _instructions(found: _Found, old: AgentSnapshot, new: AgentSnapshot) -> None:
    if old.instructions == new.instructions:
        return
    diff = text_diff(
        old.instructions,
        new.instructions,
        old_name=str(old.agent.brief.instructions),
        new_name=str(new.agent.brief.instructions),
    )
    primitive = PrimitiveChange(
        kind=Primitive.INSTRUCTION,
        field="instructions",
        change=Change.CHANGED,
        old=old.instructions,
        new=new.instructions,
        text_diff=diff,
    )
    found.append((Component.INSTRUCTIONS, primitive))


def _eval_files(found: _Found, old: AgentSnapshot, new: AgentSnapshot) -> None:
    old_files = {file.path: file for file in old.eval_files}
    new_files = {file.path: file for file in new.eval_files}
    old_suite, new_suite = old.agent.quality_gate.suite, new.agent.quality_gate.suite
    for path in sorted(old_files.keys() | new_files.keys()):
        before, after = old_files.get(path), new_files.get(path)
        if before is None:
            change, old_text, new_text = Change.ADDED, None, new_files[path].content
        elif after is None:
            change, old_text, new_text = Change.REMOVED, before.content, None
        elif before.digest != after.digest:
            change, old_text, new_text = Change.CHANGED, before.content, after.content
        else:
            continue
        diff = text_diff(
            old_text or "",
            new_text or "",
            old_name=f"{old_suite}/{path}",
            new_name=f"{new_suite}/{path}",
        )
        primitive = PrimitiveChange(
            kind=Primitive.EVAL_CASE,
            field="eval_files",
            item=path,
            change=change,
            old=old_text,
            new=new_text,
            text_diff=diff,
        )
        found.append((Component.EVAL_SUITE, primitive))


def diff_snapshots(old: AgentSnapshot, new: AgentSnapshot) -> AgentDiff:
    """Compare two snapshots of an agent.

    Args:
        old: The earlier snapshot.
        new: The later snapshot.

    Returns:
        The changes from `old` to `new`; empty exactly when their content IDs are equal.
    """
    found: _Found = []
    _agent(found, old.agent, new.agent)
    _instructions(found, old, new)
    _schema(found, "input_schema", old.input_schema, new.input_schema)
    _schema(found, "output_schema", old.output_schema, new.output_schema)
    _eval_files(found, old, new)

    # Order by the factory model; `sort` is stable, so each component keeps its field order.
    order = list(Component)
    found.sort(key=lambda pair: order.index(pair[0]))
    components = [
        ComponentDiff(name=component, changes=tuple(change for _, change in group))
        for component, group in groupby(found, key=lambda pair: pair[0])
    ]
    blocks = tuple(
        BlockDiff(name=block, components=tuple(group))
        for block, group in groupby(components, key=lambda component: BLOCK_OF[component.name])
    )
    renamed = None if old.agent.name == new.agent.name else (old.agent.name, new.agent.name)
    return AgentDiff(renamed=renamed, blocks=blocks)


# --- Describing a diff ------------------------------------------------------------------------


def _json(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _show(value: JsonValue, limit: int | None) -> str:
    """Format a value for a phrase, eliding it beyond `limit` characters.

    Names read best bare: strings as they are and lists of names comma-separated. Anything
    else is shown as JSON.
    """
    match value:
        case str():
            text = value
        case list() if all(isinstance(item, str) for item in value):
            text = ", ".join(str(item) for item in value) or "none"
        case _:
            text = _json(value)
    if limit is not None and len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _from_to(change: PrimitiveChange, limit: int | None) -> str:
    return f"{_show(change.old, limit)} {ARROW} {_show(change.new, limit)}"


def _line_counts(diff: TextDiff | None) -> str:
    added, removed = (diff.added, diff.removed) if diff is not None else (0, 0)
    return f"+{added} {MINUS}{removed} lines"


def _last(field: str) -> str:
    return field.rsplit(".", 1)[-1]


def _instruction_phrase(change: PrimitiveChange, limit: int | None) -> str:
    if change.field == "instructions":
        return f"instructions edited ({_line_counts(change.text_diff)})"
    return f"instructions file renamed ({_from_to(change, limit)})"


def _contract_phrase(change: PrimitiveChange, limit: int | None) -> str:
    side = "input" if "input" in change.field else "output"
    if change.field.startswith("agent."):
        return f"{side} contract switched ({_from_to(change, limit)})"
    return f"{side} contract changed"


_SWITCHED = {"provider": "provider", "id": "model"}


def _routing_phrase(change: PrimitiveChange, limit: int | None) -> str:
    name = _last(change.field)
    if name == "routing":
        return f"routing {change.change}"
    if name == "only":
        old = "any" if change.old is None else _show(change.old, limit)
        new = "any" if change.new is None else _show(change.new, limit)
        return f"routing providers changed ({old} {ARROW} {new})"
    return "fallbacks allowed" if change.new else "fallbacks disallowed"


def _model_setting_phrase(change: PrimitiveChange, limit: int | None) -> str:
    name = _last(change.field)
    if name in _SWITCHED:
        return f"{_SWITCHED[name]} switched ({_from_to(change, limit)})"
    if ".routing" in change.field or name == "routing":
        return _routing_phrase(change, limit)
    if change.change is Change.ADDED:
        return f"{name} set ({_show(change.new, limit)})"
    if change.change is Change.REMOVED:
        return f"{name} unset (was {_show(change.old, limit)})"
    return f"{name} changed ({_from_to(change, limit)})"


def _member_phrase(noun: str, change: PrimitiveChange, limit: int | None) -> str:
    if change.change is Change.CHANGED:
        return f"{noun}s reordered"
    return f"{noun} {change.change} ({_show(change.item, limit)})"


def _tool_phrase(change: PrimitiveChange, limit: int | None) -> str:
    return _member_phrase("tool", change, limit)


def _permission_phrase(change: PrimitiveChange, limit: int | None) -> str:
    if _last(change.field) == "network":
        return "network permission granted" if change.new else "network permission revoked"
    return _member_phrase("secret", change, limit)


def _eval_case_phrase(change: PrimitiveChange, limit: int | None) -> str:
    if change.item is None:
        return f"eval suite moved ({_from_to(change, limit)})"
    path = _show(change.item, limit)
    if change.change is Change.CHANGED:
        return f"eval case edited ({path}, {_line_counts(change.text_diff)})"
    return f"eval case {change.change} ({path})"


def _threshold_phrase(change: PrimitiveChange, limit: int | None) -> str:
    name, up, down = (
        ("pass threshold", "raised", "lowered")
        if _last(change.field) == "min_pass_rate"
        else ("repeats", "increased", "decreased")
    )
    old, new = change.old, change.new
    rising = isinstance(old, int | float) and isinstance(new, int | float) and new > old
    return f"{name} {up if rising else down} ({_from_to(change, limit)})"


_PHRASES: dict[Primitive, Callable[[PrimitiveChange, int | None], str]] = {
    Primitive.INSTRUCTION: _instruction_phrase,
    Primitive.CONTRACT: _contract_phrase,
    Primitive.MODEL_SETTING: _model_setting_phrase,
    Primitive.TOOL: _tool_phrase,
    Primitive.PERMISSION: _permission_phrase,
    Primitive.EVAL_CASE: _eval_case_phrase,
    Primitive.THRESHOLD: _threshold_phrase,
}


def phrase(change: PrimitiveChange, *, limit: int | None = None) -> str:
    """Describe one primitive change in a few words, e.g. `tool added (github.search)`.

    Args:
        change: The change.
        limit: Elide each value shown beyond this many characters; `None` shows values whole.

    Returns:
        The phrase.
    """
    return _PHRASES[change.kind](change, limit)


def _entries(
    changes: Sequence[PrimitiveChange], limit: int | None
) -> list[tuple[str, list[PrimitiveChange]]]:
    """Phrase a component's changes; the schema changes of one contract share one phrase."""
    entries: list[tuple[str, list[PrimitiveChange]]] = []
    for change in changes:
        text = phrase(change, limit=limit)
        if change.field.endswith("_schema") and entries and entries[-1][0] == text:
            entries[-1][1].append(change)
        else:
            entries.append((text, [change]))
    return entries


def _heading(name: str, old_label: str, new_label: str) -> str:
    return f"{name} {old_label} {ARROW} {new_label}"


def summarise(diff: AgentDiff, *, name: str, old_label: str, new_label: str) -> str:
    """Describe a diff in one line.

    Each changed block is named, then each changed component in it, then what changed:
    `implementer v1 → v2: Capabilities changed; model profile changed; model switched (a → b)`.
    The schema changes of one contract read as one change (`output contract changed`). At most
    `MAX_SUMMARY_CHANGES` changes are spelled out and the rest are counted as `and N more`;
    values longer than `MAX_SUMMARY_VALUE` characters are elided.

    Args:
        diff: The diff.
        name: The agent's name.
        old_label: How to refer to the old version, e.g. `v1`.
        new_label: How to refer to the new version, e.g. `v2`.

    Returns:
        The summary; `<name> <old> → <new>: no changes` for an empty diff.
    """
    heading = _heading(name, old_label, new_label)
    if diff.empty:
        return f"{heading}: no changes"

    # Each change carries the headers that introduce it, so a header is only shown with one.
    changes: list[tuple[list[str], str]] = []
    if diff.renamed is not None:
        old, new = (_show(part, MAX_SUMMARY_VALUE) for part in diff.renamed)
        changes.append(([], f"renamed ({old} {ARROW} {new})"))
    for block in diff.blocks:
        headers = [f"{block.name} changed"]
        for component in block.components:
            headers.append(f"{component.name} changed")
            for text, _ in _entries(component.changes, MAX_SUMMARY_VALUE):
                changes.append((headers, text))
                headers = []

    parts: list[str] = []
    for headers, text in changes[:MAX_SUMMARY_CHANGES]:
        parts.extend([*headers, text])
    hidden = len(changes) - MAX_SUMMARY_CHANGES
    if hidden > 0:
        parts.append(f"and {hidden} more")
    return f"{heading}: {'; '.join(parts)}"


def _details(change: PrimitiveChange) -> list[str]:
    if change.text_diff is not None:
        return change.text_diff.unified.splitlines()
    if change.field.endswith("_schema"):
        # Schema values are shown as JSON, so `"string"` and `["a"]` keep their types.
        where = change.item or "(root)"
        old, new = _json(change.old), _json(change.new)
        if change.change is Change.ADDED:
            return [f"{where} added ({new})"]
        if change.change is Change.REMOVED:
            return [f"{where} removed (was {old})"]
        return [f"{where} changed ({old} {ARROW} {new})"]
    return []


def render(diff: AgentDiff, *, name: str, old_label: str, new_label: str) -> str:
    """Describe a diff in full, grouped by block and component, with line-by-line text diffs.

    Contract changes are listed by JSON Pointer under the contract they belong to; instruction
    and eval file changes are followed by their unified diff.

    Args:
        diff: The diff.
        name: The agent's name.
        old_label: How to refer to the old version, e.g. `v1`.
        new_label: How to refer to the new version, e.g. `v2`.

    Returns:
        Multi-line text ending in a newline.
    """
    heading = _heading(name, old_label, new_label)
    if diff.empty:
        return f"{heading}: no changes\n"
    lines = [heading]
    if diff.renamed is not None:
        lines.append(f"  renamed ({diff.renamed[0]} {ARROW} {diff.renamed[1]})")
    for block in diff.blocks:
        lines.append(f"  {block.name}")
        for component in block.components:
            lines.append(f"    {component.name}")
            for text, changes in _entries(component.changes, None):
                lines.append(f"      {text}")
                lines.extend(f"        {line}" for change in changes for line in _details(change))
    return "\n".join(lines) + "\n"
