"""Server-minted frame handles (Gap 0).

The point of the whole feature is the last test in this file: a kernel
dies mid-analysis and the work does not.
"""

import pytest

from root_ext_viz import charts, data, frames, kernel


@pytest.fixture(autouse=True)
def fresh_kernel():
    kernel.reset()
    yield
    kernel.reset()


@pytest.fixture
def csv(tmp_path):
    path = tmp_path / "meas.csv"
    rows = "\n".join(f"{i},{i * 1.5}" for i in range(50))
    path.write_text(f"t,value\n{rows}\n")
    return str(path)


# ── the handle vocabulary ────────────────────────────────────────────


def test_only_a_minted_handle_is_a_handle():
    assert frames.is_handle("fr_" + "a1" * 8)
    assert not frames.is_handle("sizing")
    assert not frames.is_handle("fr_short")
    assert not frames.is_handle("fr_" + "Z" * 16), "hex only"
    assert not frames.is_handle(None)


def test_a_handle_can_never_become_a_path_traversal():
    """A handle arrives as a tool argument, so it is untrusted."""
    for hostile in ("../../etc/passwd", "fr_../../x", "/etc/passwd", ""):
        with pytest.raises(ValueError, match="not a frame handle"):
            frames.path_for(hostile)


def test_a_missing_handle_says_so_rather_than_erroring_obscurely(csv):
    data.data_load(csv, "meas")
    out = data.py_run("pass", frame_handles={"gone": "fr_" + "0" * 16})
    assert not out["ok"]
    assert "not in the store" in out["error"]
    assert "data_load the source again" in out["error"]


def test_a_name_that_looks_like_a_handle_is_refused(csv):
    """The two vocabularies must not blur — `fr_…` hex is a legal Python
    identifier, so nothing stops a caller naming a frame that way except
    this."""
    with pytest.raises(ValueError, match="looks like a frame handle"):
        data.data_load(csv, "fr_" + "a1" * 8)


def test_py_run_refuses_a_bad_frame_handles_argument(csv):
    with pytest.raises(ValueError, match="not a frame handle"):
        data.py_run("pass", frame_handles={"meas": "nonsense"})
    with pytest.raises(ValueError, match="must be a Python identifier"):
        data.py_run("pass", frame_handles={"not an identifier": "fr_" + "a1" * 8})


# ── minting and re-addressing ────────────────────────────────────────


def test_data_load_mints_a_handle_with_a_stated_ttl(csv):
    report = data.data_load(csv, "meas")
    assert frames.is_handle(report["frame_handle"])
    assert report["ttl_ms"] == frames.ttl_ms()
    assert report["rows"] == 50


def test_the_same_content_gets_the_same_handle(csv, tmp_path):
    """Content addressing, and the dedupe that comes with it: loading an
    identical file twice must not double the store."""
    twin = tmp_path / "twin.csv"
    twin.write_text(open(csv).read())
    first = data.data_load(csv, "a")["frame_handle"]
    second = data.data_load(str(twin), "b")["frame_handle"]
    assert first == second


def test_changing_a_frame_re_addresses_it_and_the_old_handle_survives(csv):
    loaded = data.data_load(csv, "meas")["frame_handle"]
    out = data.py_run('DATA["meas"]["doubled"] = DATA["meas"].value * 2')
    assert out["ok"]
    changed = out["frame_handles"]["meas"]
    assert changed != loaded, "different content, different address"

    # Both still resolve — history is free under content addressing.
    kernel.reset()
    before = data.py_run("print(len(DATA['m'].columns))", frame_handles={"m": loaded})
    after = data.py_run("print(len(DATA['m'].columns))", frame_handles={"m": changed})
    assert before["stdout"].strip() == "2"
    assert after["stdout"].strip() == "3"


def test_handles_come_back_even_when_the_code_raises(csv):
    """Code that transforms one frame and then raises must not lose the
    finished work — that is the failure this feature exists to end."""
    data.data_load(csv, "meas")
    out = data.py_run('DATA["meas"]["ok"] = 1\nraise ValueError("late")')
    assert not out["ok"] and "late" in out["error"]
    assert frames.is_handle(out["frame_handles"]["meas"])


# ── the point of the whole feature ───────────────────────────────────


def test_a_wall_timeout_no_longer_costs_the_analysis(csv):
    handle = data.data_load(csv, "meas")["frame_handle"]

    with pytest.raises(RuntimeError):
        data.py_run("while True: pass", wall_s=2)
    assert not kernel.running(), "the kernel really did die"

    # The frame is not in the kernel — this is the bare KeyError that
    # used to be the whole story, and told the caller nothing about why.
    orphaned = data.py_run('print(DATA["meas"].shape)')
    assert not orphaned["ok"] and "KeyError" in orphaned["error"]

    # …but session_state offers its handle, and it comes straight back.
    state = data.session_state()
    assert handle in state["stored_handles"]
    recovered = data.py_run('print(DATA["meas"].shape)', frame_handles={"meas": handle})
    assert recovered["ok"]
    assert recovered["stdout"].strip() == "(50, 2)"


def test_a_chart_draws_from_a_handle_with_no_kernel_at_all(csv, tmp_path):
    handle = data.data_load(csv, "meas")["frame_handle"]
    kernel.reset()
    assert not kernel.running()

    report, png = charts.chart_spec(
        {
            "title": "from a handle",
            "mark": "line",
            "encoding": {
                "x": {"field": "t", "type": "quantitative"},
                "y": {"field": "value", "type": "quantitative"},
            },
        },
        "handle-chart",
        str(tmp_path),
        data=handle,
    )
    assert png, "the store served the rows"
    assert report["diagnostics"] == [], "a clean chart reports nothing"


def test_session_state_separates_live_from_durable(csv):
    handle = data.data_load(csv, "meas")["frame_handle"]
    live = data.session_state()
    assert live["kernel"] == "running"
    assert live["frames"]["meas"]["frame_handle"] == handle

    kernel.reset()
    dead = data.session_state()
    assert dead["kernel"] == "not running"
    assert dead["frames"] == {}, "nothing is live"
    assert handle in dead["stored_handles"], "and yet the frame is not lost"
    assert "stored_handles" in dead["note"]
