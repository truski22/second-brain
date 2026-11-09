import pytest

from second_brain_app.instance import InstanceLock


def test_single_instance_and_stale_file(tmp_path):
    first = InstanceLock(tmp_path)
    try:
        with pytest.raises(RuntimeError):
            InstanceLock(tmp_path)
    finally:
        first.close()
    second = InstanceLock(tmp_path)
    second.close()
