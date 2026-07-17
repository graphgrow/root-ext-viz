"""Server wiring: every tool present, annotations honest per the
classification contract; no network tools exist in this pack at all."""

import asyncio

from root_ext_viz.server import mcp

READ_TOOLS = {"data_profile", "viz_recipes", "session_state"}
WRITE_TOOLS = {"data_load", "py_run", "session_reset", "chart_spec", "chart_export"}


def list_tools():
    return asyncio.run(mcp.list_tools())


def test_all_tools_registered():
    names = {tool.name for tool in list_tools()}
    assert names == READ_TOOLS | WRITE_TOOLS


def test_read_tools_declare_read_only_closed_world():
    for tool in list_tools():
        if tool.name in READ_TOOLS:
            assert tool.annotations is not None, tool.name
            assert tool.annotations.readOnlyHint is True, tool.name
            assert tool.annotations.openWorldHint is False, tool.name


def test_write_tools_declare_closed_world_write():
    for tool in list_tools():
        if tool.name in WRITE_TOOLS:
            assert tool.annotations is not None, tool.name
            assert tool.annotations.readOnlyHint is False, tool.name
            assert tool.annotations.openWorldHint is False, tool.name
            assert tool.annotations.destructiveHint is False, tool.name


def test_no_tool_claims_the_open_world():
    for tool in list_tools():
        assert tool.annotations.openWorldHint is False, tool.name


def test_descriptions_teach():
    for tool in list_tools():
        assert tool.description and len(tool.description) > 40, tool.name


def test_no_inplace_mutation_tools_exist():
    # The charter, as a test: compute and plot — nothing overwrites,
    # deletes, moves, or edits a user's file.
    names = {tool.name for tool in list_tools()}
    for forbidden in ("overwrite", "delete", "remove", "move", "rename", "save_as", "edit"):
        assert not any(forbidden in name for name in names), forbidden


def test_py_run_says_it_executes_and_names_its_bounds():
    run = next(tool for tool in list_tools() if tool.name == "py_run")
    assert "EXECUTES" in run.description
    assert "SURVIVE" in run.description  # the sessional contract is stated
    assert "wall_s" in run.description


def test_chart_spec_teaches_the_vision_loop():
    spec = next(tool for tool in list_tools() if tool.name == "chart_spec")
    assert "LOOK" in spec.description
    assert ".vl.json" in spec.description
