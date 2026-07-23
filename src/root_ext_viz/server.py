"""root-ext-viz — the data-visualization MCP tool server.

Serves over MCP stdio for any host; in ROOT Workspace it connects
through Settings → Connected tools and every call rides the runtime's
governance (the client classifies tools from the annotations below,
fail-safe, and gates accordingly).

The design (agreed with the user, 2026-07-18) is five pillars:
a SESSIONAL KERNEL (dataframes and imports survive across calls — load
once, iterate), CHARTS AS SOURCE DOCUMENTS (.vl.json specs the
workspace renders live; pixels are derived beside them), the VISION
LOOP (every render returns its png path — read it, look, refine),
RECIPES AS PROMPT SURFACE (one read tool, not 25 chart tools), and
BOUNDED DATA PLUMBING (profile → aggregate in the kernel → only
summaries enter a spec).

Annotation contract (matches the classifier in the ROOT client):
- Read tools: ``readOnlyHint=True, openWorldHint=False``.
- Session tools (they run code / mutate kernel state) and
  derived-write tools: ``readOnlyHint=False, openWorldHint=False,
  destructiveHint=False`` — the closed-world write class, gated like
  any write.

Charter, binding for this package: **compute and plot; outputs land
only in derived or artifact directories, never on a source.** Nothing
here reaches the network — rendering is local vl-convert, pinned to
the same Vega-Lite major (v6) as the workspace's bundled viewer.

Heavy imports stay inside call bodies: the server announces its tools
without paying pandas' import cost, so the connect-form doctor stays
fast.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("viz-eng")

_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_SESSION_WRITE = ToolAnnotations(
    readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False
)
_DERIVED_WRITE = ToolAnnotations(
    readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True
)


# ── data ─────────────────────────────────────────────────────────────


@mcp.tool(annotations=_READ)
def data_profile(path: str) -> dict:
    """Describe a data file (csv/tsv/parquet/xlsx/json) BEFORE plotting
    it: row count (sampled at 100k for huge csv), column dtypes, head,
    and numeric summary. Profile → design the chart → load. Reads the
    file on this machine; nothing leaves it."""
    from . import data

    return data.data_profile(path)


@mcp.tool(annotations=_SESSION_WRITE)
def data_load(path: str, name: str) -> dict:
    """Load a data file into the SESSION KERNEL as DATA[name] — loaded
    once, it survives across calls: transform it with py_run, chart it
    with chart_spec(data=name). Starts the kernel on first use.
    Returns the loaded frame's profile."""
    from . import data

    return data.data_load(path, name)


@mcp.tool(annotations=_READ)
def session_state() -> dict:
    """What the session kernel holds right now: loaded frames (rows ×
    columns) and user variables. The kernel survives across your calls;
    a wall-timeout or session_reset empties it."""
    from . import data

    return data.session_state()


@mcp.tool(annotations=_SESSION_WRITE)
def py_run(code: str, wall_s: float = 60.0) -> dict:
    """EXECUTES Python in the persistent session kernel — pandas,
    numpy, scipy, matplotlib (Agg), plotly, altair are importable;
    DATA holds loaded frames; variables and imports SURVIVE to your
    next call. Use it to transform/aggregate before charting, or run a
    python recipe (matplotlib figures: savefig to an absolute path in
    the artifact scratch). Resource-capped (memory rlimit + your
    wall_s, max 570s); a timeout kills the kernel and names the state
    loss. stdout/stderr come back bounded."""
    from . import data

    return data.py_run(code, wall_s)


@mcp.tool(annotations=_SESSION_WRITE)
def session_reset() -> dict:
    """Empty the session kernel deliberately — loaded frames and
    variables are gone; the next data_load starts fresh."""
    from . import data

    return data.session_reset()


# ── charts ───────────────────────────────────────────────────────────


@mcp.tool(annotations=_DERIVED_WRITE)
def chart_spec(
    spec: dict,
    name: str,
    out_dir: str,
    data: str | None = None,
    max_rows: int = 5000,
) -> dict:
    """Write a Vega-Lite chart as a SOURCE DOCUMENT: <name>.vl.json +
    a rendered <name>.png land in out_dir (use the artifact scratch
    when the user asked to SEE it — the workspace opens it beside the
    conversation, live and editable). Pass data=<kernel frame name> to
    inline a loaded frame (capped at max_rows — aggregate big data in
    the kernel first). Then fs.read the .png to LOOK at your chart and
    refine the spec. Rendering is local (vl-convert, Vega-Lite v6)."""
    from . import charts

    return charts.chart_spec(spec, name, out_dir, data, max_rows)


@mcp.tool(annotations=_DERIVED_WRITE)
def chart_export(
    spec_path: str,
    out_path: str,
    image_format: str = "svg",
    scale: float = 2.0,
) -> dict:
    """Render an existing .vl.json to svg, png, or SELF-CONTAINED
    interactive html (vega js inlined — opens in the browser, works
    offline). Refuses an out_path that collides with the spec
    (charter)."""
    from . import charts

    return charts.chart_export(spec_path, out_path, image_format, scale)


# ── recipes ──────────────────────────────────────────────────────────


@mcp.tool(annotations=_READ)
def viz_recipes(topic: str = "") -> dict:
    """Engineering chart recipes — call with no topic for the index,
    with a topic for a worked template: line, scatter, bar, histogram,
    cdf, log_axes, error_bars, tolerance_band, control_chart, heatmap
    (Vega-Lite, chart_spec-ready) and bode, fft, contour (python, via
    py_run). Templates teach the shape; adapt fields to your data."""
    from . import recipes

    return recipes.viz_recipes(topic)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
