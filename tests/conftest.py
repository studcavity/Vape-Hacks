import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo():
    return REPO
