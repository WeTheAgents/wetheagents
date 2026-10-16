"""Local coordination must not alter the installed Hello World package identity."""

from pathlib import Path

from scripts import task_execution
from wea_vnext.tide.hello_world import package_files


def test_local_coordinator_is_outside_fingerprinted_packages():
    source = Path(task_execution.__file__).resolve()
    assert source.parent.name == "scripts"
    files = package_files()
    assert not any(name.endswith("/task_execution.py") for name in files)
