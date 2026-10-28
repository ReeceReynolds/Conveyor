"""Property tests: content IDs are stable, snapshots round-trip, and diffs see every change."""

import tempfile
from pathlib import Path
from random import Random
from typing import Any

from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import JsonValue

from conveyor.model import Agent
from conveyor.registry import (
    AgentSnapshot,
    Block,
    EvalFile,
    JsonSchema,
    build_snapshot,
    canonical_bytes,
    content_id,
    diff_snapshots,
    render,
    snapshot_from_bytes,
    summarise,
)
from conveyor.registry.canonical import MAX_SAFE_INTEGER

_words = st.text("abxyz019", min_size=1, max_size=4)
_slugs = st.lists(_words, min_size=1, max_size=2).map("-".join)
_refs = st.lists(st.text("abcXYZ_", min_size=1, max_size=4), min_size=2, max_size=2).map(".".join)
_tools = st.lists(_words, min_size=1, max_size=2).map(".".join)
_secrets = st.text("ABCXYZ_", min_size=1, max_size=4).map(lambda name: f"S{name}")
_paths = st.lists(_words, min_size=1, max_size=3).map("/".join)
# Text with any line endings, including CR, CRLF and none at the end.
_texts = st.text(st.characters(codec="utf-8", exclude_categories=("Cs",)), max_size=40)

_json_leaves = (
    st.none()
    | st.booleans()
    | st.integers(-MAX_SAFE_INTEGER, MAX_SAFE_INTEGER)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=5)
)
_json: st.SearchStrategy[JsonValue] = st.recursive(
    _json_leaves,
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=4), children, max_size=3)
    ),
    max_leaves=8,
)
_schemas: st.SearchStrategy[JsonSchema] = st.dictionaries(st.text(max_size=6), _json, max_size=4)


def _unique[T](elements: st.SearchStrategy[T]) -> st.SearchStrategy[list[T]]:
    return st.lists(elements, unique=True, max_size=3)


@st.composite
def _agents(draw: st.DrawFn) -> Agent:
    provider = draw(st.sampled_from(["openrouter", "anthropic", "openai"]))
    routing = (
        draw(
            st.none()
            | st.fixed_dictionaries(
                {"only": st.none() | _unique(_slugs), "allow_fallbacks": st.booleans()}
            )
        )
        if provider == "openrouter"
        else None
    )
    return Agent.model_validate(
        {
            "name": draw(_slugs),
            "brief": {"instructions": draw(_paths), "input": draw(_refs), "output": draw(_refs)},
            "capabilities": {
                "model": {
                    "provider": provider,
                    "id": draw(_words),
                    "temperature": draw(st.none() | st.floats(0, 2)),
                    "top_p": draw(st.none() | st.floats(0, 1)),
                    "max_tokens": draw(st.none() | st.integers(1, 1_000_000)),
                    "routing": routing,
                },
                "tools": draw(_unique(_tools)),
                "permissions": {"network": draw(st.booleans()), "secrets": draw(_unique(_secrets))},
            },
            "quality_gate": {
                "suite": draw(_paths),
                "min_pass_rate": draw(st.floats(0, 1)),
                "repeats": draw(st.integers(1, 100)),
            },
        }
    )


_eval_files = st.dictionaries(_paths, _texts, max_size=3).map(
    lambda files: tuple(EvalFile.of(path, text) for path, text in files.items())
)
snapshots = st.builds(
    AgentSnapshot,
    agent=_agents(),
    instructions=_texts,
    input_schema=_schemas,
    output_schema=_schemas,
    eval_files=_eval_files,
)


def _reversed_keys(value: JsonValue) -> JsonValue:
    """The same JSON value with every object's keys in reverse insertion order."""
    if isinstance(value, dict):
        return {key: _reversed_keys(value[key]) for key in reversed(value)}
    if isinstance(value, list):
        return [_reversed_keys(item) for item in value]
    return value


def _edit(snapshot: AgentSnapshot, edits: dict[str, Any]) -> AgentSnapshot:
    data = snapshot.model_dump(mode="json")
    for path, value in edits.items():
        *parents, last = path.split(".")
        node = data
        for key in parents:
            node = node[key]
        node[last] = value
    return AgentSnapshot.model_validate(data)


@given(snapshots)
def test_content_id_ignores_key_and_file_order(snapshot: AgentSnapshot) -> None:
    # Pydantic's JSON Schemas keep field order; identity must not depend on it.
    data = snapshot.model_dump()
    data["input_schema"] = _reversed_keys(snapshot.input_schema)
    data["output_schema"] = _reversed_keys(snapshot.output_schema)
    data["eval_files"] = list(reversed(snapshot.eval_files))

    reordered = AgentSnapshot.model_validate(data)

    assert content_id(reordered) == content_id(snapshot)
    assert diff_snapshots(snapshot, reordered).empty


@given(snapshots)
def test_canonical_bytes_round_trip(snapshot: AgentSnapshot) -> None:
    data = canonical_bytes(snapshot)

    restored = snapshot_from_bytes(data)

    assert restored == snapshot
    assert canonical_bytes(restored) == data


@given(snapshots)
def test_a_snapshot_has_no_changes_from_itself(snapshot: AgentSnapshot) -> None:
    assert diff_snapshots(snapshot, snapshot).empty


@given(snapshots, snapshots)
def test_diff_is_empty_exactly_when_ids_match_and_never_fails_to_describe(
    old: AgentSnapshot, new: AgentSnapshot
) -> None:
    diff = diff_snapshots(old, new)

    assert diff.empty == (content_id(old) == content_id(new))
    summary = summarise(diff, name=new.agent.name, old_label="v1", new_label="v2")
    assert "\n" not in summary
    assert render(diff, name=new.agent.name, old_label="v1", new_label="v2").endswith("\n")


_MODEL = "agent.capabilities.model"
_MUTATIONS: list[tuple[Block, str, st.SearchStrategy[Any]]] = [
    (Block.BRIEF, "instructions", _texts),
    (Block.BRIEF, "agent.brief.instructions", _paths),
    (Block.BRIEF, "agent.brief.input", _refs),
    (Block.BRIEF, "agent.brief.output", _refs),
    (Block.BRIEF, "input_schema", _schemas),
    (Block.BRIEF, "output_schema", _schemas),
    (Block.CAPABILITIES, f"{_MODEL}.id", _words),
    (Block.CAPABILITIES, f"{_MODEL}.temperature", st.none() | st.floats(0, 2)),
    (Block.CAPABILITIES, f"{_MODEL}.top_p", st.none() | st.floats(0, 1)),
    (Block.CAPABILITIES, f"{_MODEL}.max_tokens", st.none() | st.integers(1, 1_000_000)),
    (Block.CAPABILITIES, "agent.capabilities.tools", _unique(_tools)),
    (Block.CAPABILITIES, "agent.capabilities.permissions.network", st.booleans()),
    (Block.CAPABILITIES, "agent.capabilities.permissions.secrets", _unique(_secrets)),
    (Block.QUALITY_GATE, "agent.quality_gate.suite", _paths),
    (Block.QUALITY_GATE, "agent.quality_gate.min_pass_rate", st.floats(0, 1)),
    (Block.QUALITY_GATE, "agent.quality_gate.repeats", st.integers(1, 100)),
    (
        Block.QUALITY_GATE,
        "eval_files",
        _eval_files.map(lambda files: [file.model_dump() for file in files]),
    ),
]


@st.composite
def _single_changes(draw: st.DrawFn) -> tuple[Block, AgentSnapshot, AgentSnapshot]:
    old = draw(snapshots)
    block, path, values = draw(st.sampled_from(_MUTATIONS))
    new = _edit(old, {path: draw(values)})
    assume(content_id(new) != content_id(old))
    return block, old, new


@st.composite
def _model_profile_changes(draw: st.DrawFn) -> tuple[Block, AgentSnapshot, AgentSnapshot]:
    """Provider and routing changes, which must keep `routing` valid for the provider."""
    old = draw(snapshots)
    if old.agent.capabilities.model.routing is None:
        provider = draw(st.sampled_from(["openrouter", "anthropic", "openai"]))
        new = _edit(old, {f"{_MODEL}.provider": provider})
    elif draw(st.booleans()):
        new = _edit(old, {f"{_MODEL}.routing.only": draw(st.none() | _unique(_slugs))})
    else:
        new = _edit(old, {f"{_MODEL}.routing.allow_fallbacks": draw(st.booleans())})
    assume(content_id(new) != content_id(old))
    return Block.CAPABILITIES, old, new


@given(_single_changes() | _model_profile_changes())
def test_a_single_field_change_is_seen_in_its_block(
    change: tuple[Block, AgentSnapshot, AgentSnapshot],
) -> None:
    block, old, new = change

    diff = diff_snapshots(old, new)

    assert not diff.empty
    assert [changed.name for changed in diff.blocks] == [block]


@given(
    st.dictionaries(_paths, _texts, min_size=1, max_size=4).filter(
        # A path cannot be both a file and a folder.
        lambda files: not any(other.startswith(f"{path}/") for path in files for other in files)
    ),
    st.randoms(use_true_random=False),
)
def test_build_snapshot_ignores_file_creation_order(files: dict[str, str], random: Random) -> None:
    agent = Agent.model_validate(
        {
            "name": "solo",
            "brief": {"instructions": "prompt.md", "input": "c.In", "output": "c.Out"},
            "capabilities": {"model": {"provider": "openai", "id": "gpt"}},
            "quality_gate": {"suite": "evals", "min_pass_rate": 1.0},
        }
    )
    schemas: dict[str, JsonSchema] = {"c.In": {}, "c.Out": {}}
    ids: list[str] = []
    for order in (list(files), random.sample(list(files), len(files))):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "prompt.md").write_text("Go.\n")
            for path in order:
                file = folder / "evals" / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(files[path].encode())
            ids.append(content_id(build_snapshot(folder, agent, schemas)))

    assert ids[0] == ids[1]
