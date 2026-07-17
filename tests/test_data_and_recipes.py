"""Profiles are bounded; recipes teach every advertised topic."""

import pytest

from root_ext_viz import data
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
