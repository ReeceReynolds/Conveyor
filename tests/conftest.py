from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = Path(__file__).parents[1] / "examples" / "prd-to-pr"


@pytest.fixture
def in_fixtures(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the test from the fixtures folder, so reported paths are short and stable."""
    monkeypatch.chdir(FIXTURES)
    return Path()


@pytest.fixture
def example() -> Path:
    """The prd-to-pr reference factory, which doubles as a valid fixture."""
    return EXAMPLE
