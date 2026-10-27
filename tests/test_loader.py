"""YAML parsing: safety, YAML 1.2 semantics and precise positions."""

import textwrap
from pathlib import Path

import pytest
from inline_snapshot import snapshot

from conveyor.model import Agent, ConfigError, Factory, Issue
from conveyor.model.errors import format_loc
from conveyor.model.loader import dump_yaml, parse_yaml, read_document, validate_document

FILE = Path("config.yaml")


def _parse_errors(text: str) -> list[tuple[str, str, str]]:
    """Parse `text` expecting failure; return each issue as (line:column, field path, message)."""
    with pytest.raises(ConfigError) as caught:
        parse_yaml(textwrap.dedent(text), FILE)
    return [
        (f"{issue.line}:{issue.column}", format_loc(issue.loc), issue.message)
        for issue in caught.value.issues
    ]


def test_parses_plain_data_with_yaml_1_2_semantics() -> None:
    document = parse_yaml("a: no\nb: 1.5\nc: 0x1F\nd: ~\ne: 2026-01-01\nf: [true, 'x']\n", FILE)

    # YAML 1.1 would read `no` as false and the date as a date; YAML 1.2 does neither.
    assert document.data == {
        "a": "no",
        "b": 1.5,
        "c": 31,
        "d": None,
        "e": "2026-01-01",
        "f": [True, "x"],
    }


def test_records_key_and_value_positions() -> None:
    document = parse_yaml("# comment\nouter:\n  inner: [1, 2]\n", FILE)

    assert document.keys[("outer",)] == document.position(("outer",), of_key=True)
    assert (document.keys[("outer", "inner")].line, document.keys[("outer", "inner")].column) == (
        3,
        3,
    )
    assert (
        document.values[("outer", "inner", 1)].line,
        document.values[("outer", "inner", 1)].column,
    ) == (3, 14)
    # Unknown locations fall back to the nearest written ancestor, then the start of the file.
    assert document.position(("outer", "inner", 7, "x")) == document.keys[("outer", "inner")]
    assert document.position(("missing",)) == document.position(())
    assert (
        document.position(("outer", "inner", 1, "x", "y")) == document.values[("outer", "inner", 1)]
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "a: [1\n",
            snapshot([("2:1", "", "expected ',' or ']', but got '<stream end>'")]),
            id="syntax",
        ),
        pytest.param(
            "a: 1\nb: 2\na: 3\n",
            snapshot([("3:1", "a", "duplicate key 'a' (first defined on line 1)")]),
            id="duplicate-key",
        ),
        pytest.param("", snapshot([("1:1", "", "file is empty")]), id="empty"),
        pytest.param(
            "# only a comment\n", snapshot([("1:1", "", "file is empty")]), id="comment-only"
        ),
        pytest.param(
            "a: !!python/object:os.system ls\n",
            snapshot(
                [("1:4", "a", "unsupported YAML tag 'tag:yaml.org,2002:python/object:os.system'")]
            ),
            id="python-tag",
        ),
        pytest.param(
            "a: !custom {x: 1}\n",
            snapshot([("1:4", "a", "unsupported YAML tag '!custom'")]),
            id="custom-tag",
        ),
        pytest.param(
            "base: &b {x: 1}\nchild:\n  <<: *b\n",
            snapshot([("3:3", "child", "merge keys ('<<') are not supported")]),
            id="merge-key",
        ),
        pytest.param(
            "a: &loop [*loop]\n",
            snapshot([("1:4", "a[0]", "recursive YAML aliases are not supported")]),
            id="recursive-alias",
        ),
        pytest.param(
            "? [1, 2]\n: x\nnull: y\n",
            snapshot(
                [
                    ("1:3", "", "mapping keys must be plain scalars"),
                    ("3:1", "", "mapping keys must be plain scalars"),
                ]
            ),
            id="non-scalar-keys",
        ),
        pytest.param(
            "!custom a: 1\n",
            snapshot([("1:1", "", "unsupported YAML tag '!custom'")]),
            id="tagged-key",
        ),
        pytest.param(
            "a: 1\n---\nb: 2\n",
            snapshot(
                [("2:1", "", "expected a single document in the stream but found another document")]
            ),
            id="two-documents",
        ),
    ],
)
def test_rejects_unsafe_or_ambiguous_yaml(text: str, expected: list[tuple[str, str, str]]) -> None:
    assert _parse_errors(text) == expected


def test_aliases_are_expanded() -> None:
    document = parse_yaml("a: &x [1, 2]\nb: *x\n", FILE)

    assert document.data == {"a": [1, 2], "b": [1, 2]}


def test_read_document_reports_unreadable_files(tmp_path: Path) -> None:
    binary = tmp_path / "binary.yaml"
    binary.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(ConfigError) as not_utf8:
        read_document(binary)
    with pytest.raises(ConfigError) as is_dir:
        read_document(tmp_path)

    assert [issue.message for issue in not_utf8.value.issues] == ["file is not valid UTF-8"]
    assert is_dir.value.issues[0].message.startswith("cannot read file: ")


def test_union_tags_are_stripped_but_real_keys_are_kept() -> None:
    text = textwrap.dedent(
        """\
        name: tags
        trigger: { manual: true }
        stages:
          - { id: one, agent: worker, agent_stage: oops }
        outcome:
          scorers: [{ human_review: { scale: 1-5, extra: 1 } }]
        """
    )

    with pytest.raises(ConfigError) as caught:
        validate_document(parse_yaml(text, FILE), Factory)

    assert [issue.render() for issue in caught.value.issues] == snapshot(
        [
            "config.yaml:4:31: stages[0].agent_stage: unknown field",
            "config.yaml:6:43: outcome.scorers[0].human_review.extra: unknown field",
        ]
    )


def test_config_error_message_lists_every_issue() -> None:
    error = ConfigError(
        [Issue(file=FILE, message="second", line=2), Issue(file=FILE, message="first", line=1)]
    )

    assert str(error) == snapshot("""\
config.yaml:1: first
config.yaml:2: second\
""")


def test_issue_render_omits_unknown_parts() -> None:
    assert Issue(file=FILE, message="m").render() == "config.yaml: m"
    assert Issue(file=FILE, line=3, message="m").render() == "config.yaml:3: m"
    assert Issue(file=FILE, line=3, column=4, loc=("a", 0, "b"), message="m").render() == (
        "config.yaml:3:4: a[0].b: m"
    )
    assert Issue(file=FILE, loc=(0,), message="m").render() == "config.yaml: [0]: m"


def test_dump_yaml_omits_defaults_and_round_trips(in_fixtures: Path) -> None:
    agent = validate_document(read_document(in_fixtures / "agents/valid-minimal.yaml"), Agent)

    text = dump_yaml(agent)

    assert "repeats" not in text
    assert validate_document(parse_yaml(text, FILE), Agent) == agent
