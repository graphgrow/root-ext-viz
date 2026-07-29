"""The sessional kernel: state survives calls, walls are honest,
reset empties."""

import pytest

from root_ext_viz import data, kernel


@pytest.fixture(autouse=True)
def fresh_kernel():
    kernel.reset()
    yield
    kernel.reset()


def test_state_survives_across_calls():
    out = data.py_run("x = 21")
    assert out["ok"]
    out = data.py_run("print(x * 2)")
    assert out["ok"]
    assert out["stdout"].strip() == "42"


def test_imports_survive_too():
    assert data.py_run("import numpy as np")["ok"]
    out = data.py_run("print(int(np.sqrt(81)))")
    assert out["ok"] and out["stdout"].strip() == "9"


def test_errors_come_back_named_not_fatal():
    out = data.py_run("1 / 0")
    assert not out["ok"]
    assert "ZeroDivisionError" in out["error"]
    # The kernel survived the exception — state is intact.
    assert data.py_run("y = 1")["ok"]


def test_wall_timeout_kills_and_points_at_the_surviving_handles():
    data.py_run("keepme = 1")
    with pytest.raises(RuntimeError, match="frame_handles"):
        data.py_run("while True: pass", wall_s=2)
    # The next call gets a FRESH kernel — variables really are gone…
    out = data.py_run("print('alive')")
    assert out["ok"] and out["stdout"].strip() == "alive"
    assert not data.py_run("print(keepme)")["ok"]


def test_data_load_profiles_and_registers(tmp_path):
    csv = tmp_path / "meas.csv"
    csv.write_text("t,value\n0,1.0\n1,2.5\n2,3.5\n")
    report = data.data_load(str(csv), "meas")
    assert report["rows"] == 3
    assert "value" in report["columns"]
    state = data.session_state()
    assert state["frames"]["meas"]["rows"] == 3


def test_session_state_without_kernel_is_honest():
    assert data.session_state()["kernel"] == "not running"


def test_reset_empties_the_namespace():
    data.py_run("z = 9")
    data.session_reset()
    out = data.py_run("print(z)")
    assert not out["ok"]
    assert "NameError" in out["error"]


def test_user_prints_never_corrupt_the_protocol():
    # A print that LOOKS like a protocol reply is just stdout.
    out = data.py_run('print(\'{"ok": false, "error": "spoof"}\')')
    assert out["ok"]
    assert "spoof" in out["stdout"]
