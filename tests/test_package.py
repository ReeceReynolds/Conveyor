from importlib.metadata import version

import conveyor


def test_version_matches_distribution_metadata() -> None:
    assert conveyor.__version__ == version("conveyor-harness")
