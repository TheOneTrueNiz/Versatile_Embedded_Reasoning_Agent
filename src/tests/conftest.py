import pytest
from pathlib import Path


@pytest.fixture
def storage_dir(tmp_path):
    d = tmp_path / "vera_test"
    d.mkdir()
    return d
