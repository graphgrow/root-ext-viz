"""Charts as documents: spec + render land together; exports honor the
charter; the local renderer is real (vl-convert, no network)."""

import json

import pytest

from root_ext_viz import charts, data, kernel


@pytest.fixture(autouse=True)
def fresh_kernel():
    kernel.reset()
    yield
    kernel.reset()


SPEC = {
    "mark": "bar",
    "data": {"values": [{"c": "a", "v": 3}, {"c": "b", "v": 7}]},
    "encoding": {
        "x": {"field": "c", "type": "nominal"},
        "y": {"field": "v", "type": "quantitative"},
    },
}


def test_chart_spec_writes_document_and_render(tmp_path):
    report, inline = charts.chart_spec(SPEC, "loads", str(tmp_path))
    paths = [w["path"] for w in report["written"]]
    assert paths == [str(tmp_path / "loads.vl.json"), str(tmp_path / "loads.png")]
    saved = json.loads((tmp_path / "loads.vl.json").read_text())
    assert saved["$schema"].endswith("v6.json")  # pinned to the viewer's major
    png = (tmp_path / "loads.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # The bytes come BACK as well as landing on disk — the whole of P1.
    assert inline[:8] == b"\x89PNG\r\n\x1a\n"
    assert "attached" in report["note"]
    assert isinstance(report["diagnostics"], list)


def test_the_inline_render_is_bounded_but_the_file_is_not(tmp_path, monkeypatch):
    """A chart returned inline is context the caller pays for, so it is
    capped; the document on disk keeps full fidelity regardless."""
    monkeypatch.setattr(charts, "MAX_INLINE_PNG_BYTES", 1)
    report, inline = charts.chart_spec(SPEC, "big", str(tmp_path))
    on_disk = (tmp_path / "big.png").read_bytes()
    assert len(inline) < len(on_disk), "the inline copy was scaled down"
    assert inline[:8] == b"\x89PNG\r\n\x1a\n", "and is still a PNG"


def test_chart_spec_inlines_a_kernel_frame_with_caps(tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_text("x,y\n" + "\n".join(f"{i},{i * i}" for i in range(50)))
    data.data_load(str(csv), "d")
    spec = {
        "mark": "line",
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }
    report, _ = charts.chart_spec(spec, "curve", str(tmp_path), data="d", max_rows=10)
    assert report["data_clipped"] == "first 10 of 50 rows inlined"
    saved = json.loads((tmp_path / "curve.vl.json").read_text())
    assert len(saved["data"]["values"]) == 10


def test_chart_spec_refuses_an_unknown_frame(tmp_path):
    data.py_run("pass")  # kernel up, nothing loaded
    with pytest.raises(ValueError, match="no loaded frame"):
        charts.chart_spec(SPEC, "x", str(tmp_path), data="ghost")


def test_export_formats_and_collision(tmp_path):
    charts.chart_spec(SPEC, "loads", str(tmp_path))
    spec_path = tmp_path / "loads.vl.json"
    svg = charts.chart_export(str(spec_path), str(tmp_path / "loads.svg"))
    assert (tmp_path / "loads.svg").read_text().lstrip().startswith("<svg")
    assert svg["written"][0]["kind"] == "svg"
    html = charts.chart_export(str(spec_path), str(tmp_path / "loads.html"), "html")
    text = (tmp_path / "loads.html").read_text()
    assert "<script" in text and "cdn" not in text.lower()  # self-contained
    assert html["bytes"] > 100_000  # the vega js is really inlined
    with pytest.raises(ValueError, match="refusing to overwrite input"):
        charts.chart_export(str(spec_path), str(spec_path))


def test_bad_specs_are_named_errors(tmp_path):
    with pytest.raises(ValueError, match="not valid JSON"):
        charts.chart_spec("{nope", "x", str(tmp_path))
    with pytest.raises(ValueError, match="chart name"):
        charts.chart_spec(SPEC, "///", str(tmp_path))
