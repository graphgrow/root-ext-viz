"""Profiles are bounded; recipes teach every advertised topic."""

import pytest

from root_ext_viz import charts, data, recipes
from root_ext_viz.recipes import RECIPES, viz_recipes


def test_profile_describes_without_dumping(tmp_path):
    csv = tmp_path / "log.csv"
    csv.write_text("t,temp\n" + "\n".join(f"{i},{20 + i % 5}" for i in range(1000)))
    report = data.data_profile(str(csv))
    assert report["rows_seen"] == 1000
    assert report["columns"] == {"t": "int64", "temp": "int64"}
    assert "Numeric summary" in report["profile"]
    assert report["truncated"] is False


def test_profile_refuses_non_data_suffixes(tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("hello")
    with pytest.raises(ValueError, match="expected one of"):
        data.data_profile(str(other))


def test_recipe_index_and_topics_agree():
    index = viz_recipes()
    assert set(index["topics"]) == set(RECIPES)
    for topic in RECIPES:
        recipe = viz_recipes(topic)
        assert recipe["kind"] in ("vega_lite", "python")
        assert recipe["for"]
        assert recipe["template"]


def test_engineering_recipes_carry_their_idioms():
    assert "semilogx" in viz_recipes("bode")["template"]
    assert "rfft" in viz_recipes("fft")["template"]
    assert viz_recipes("log_axes")["template"]["encoding"]["x"]["scale"]["type"] == "log"
    with pytest.raises(ValueError, match="no recipe"):
        viz_recipes("piechart3d")


# ── Gap 4: the renderings, which needed no new tools ─────────────────


def test_the_fanout_recipes_are_offered():
    """Small multiples and the time scrubber are the two shapes Gap 4
    asked for, and both are expressible in Vega-Lite — so they are
    recipes, not tools."""
    topics = recipes.viz_recipes()["topics"]
    assert "small_multiples" in topics
    assert "time_scrubber" in topics


def test_small_multiples_puts_columns_where_vega_lite_reads_it():
    """Nested inside `facet`, `columns` is silently ignored and every
    panel lands in one row — the exact mistake the recipe exists to
    stop, so the template must not make it."""
    template = recipes.viz_recipes("small_multiples")["template"]
    assert "columns" in template, "columns belongs at the top level"
    assert "columns" not in template["facet"]
    assert "facet" in template and "spec" in template


def test_the_scrubber_pins_its_x_domain():
    """Without a pinned domain the axis rescales as the slider moves and
    the motion becomes unreadable."""
    template = recipes.viz_recipes("time_scrubber")["template"]
    assert template["encoding"]["x"]["scale"]["domain"]
    assert template["params"][0]["bind"]["input"] == "range"
    assert template["transform"], "a slider with no filter does nothing"


@pytest.mark.parametrize("topic", ["small_multiples", "time_scrubber"])
def test_the_fanout_recipes_actually_render(topic, tmp_path):
    rows = [
        {"t": t / 4, "value": t / 10, "run": f"case {k}", "series": f"case {k}"}
        for k in (1, 2, 3)
        for t in range(20)
    ]
    spec = dict(recipes.viz_recipes(topic)["template"])
    spec["data"] = {"values": rows}
    _, png = charts.chart_spec(spec, topic, str(tmp_path))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("topic", ["small_multiples", "time_scrubber"])
def test_each_fanout_recipe_warns_about_its_own_trap(topic):
    notes = recipes.viz_recipes(topic)["notes"]
    assert len(notes) > 80, "a recipe whose traps are unstated teaches nothing"
