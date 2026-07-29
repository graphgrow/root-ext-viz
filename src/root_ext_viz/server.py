"""root-ext-viz — the data-visualization MCP tool server.

Serves over MCP stdio for any host; in ROOT Workspace it connects
through Settings → Connected tools and every call rides the runtime's
governance (the client classifies tools from the annotations below,
fail-safe, and gates accordingly).

The design (agreed with the user, 2026-07-18) is five pillars:
a SESSIONAL KERNEL (imports and variables survive across calls — load
once, iterate), CHARTS AS SOURCE DOCUMENTS (.vl.json specs the
workspace renders live; pixels are derived beside them), the VISION
LOOP, RECIPES AS PROMPT SURFACE (one read tool, not 25 chart tools),
and BOUNDED DATA PLUMBING (profile → aggregate in the kernel → only
summaries enter a spec).

The vision loop closes IN ONE CALL (gap plan, Gap 5): a render comes
back attached to the result that produced it, beside deterministic
diagnostics about its own layout. The original shape returned a path and
told the caller to go read it — three round trips and a second approval
surface for one chart, which is why the loop so often didn't close at
all. A tool that can already see the pixels it just made has no business
asking the model to fetch them.

And the kernel's frames are no longer implicit session state (gap plan,
Gap 0): every loaded frame is content-addressed into a store and named
by an opaque `frame_handle` the caller passes back as an ordinary tool
argument — MCP 2026-07-28's sanctioned replacement for sessions
(SEP-2567), and, more immediately, the reason a wall-timeout now costs
one call instead of the whole analysis. See `frames.py`.

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

import base64
import json

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

mcp = FastMCP("viz-eng")


def _seen(report: dict, png: bytes) -> CallToolResult:
    """A rendered chart, returned so the caller can SEE it (pillar C).

    The old shape wrote a PNG and told the caller to go read it: three
    round trips and a second permission surface for one chart, which is
    why the vision loop rarely actually closed. One `CallToolResult`
    carries the image, the report as text, and the report again as
    `structuredContent` — hosts that render images get the picture,
    hosts that only read text still get every path and finding.

    The image goes FIRST: a client that truncates a long content array
    keeps the thing that cannot be reconstructed from the other blocks.
    """
    return CallToolResult(
        content=[
            ImageContent(
                type="image",
                data=base64.b64encode(png).decode("ascii"),
                mimeType="image/png",
            ),
            TextContent(type="text", text=json.dumps(report, indent=2)),
        ],
        structuredContent=report,
    )

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
    """Load a data file into the session kernel as DATA[name] — loaded
    once, use it many times: transform with py_run, chart with
    chart_spec(data=name). Starts the kernel on first use.

    RETURNS A `frame_handle` as well as the profile. The handle is the
    durable name for this frame: it is written to a store that outlives
    the kernel, so if a wall-timeout kills the interpreter you can pass
    the handle back to py_run's `frame_handles` and carry on instead of
    reloading. Treat it as opaque; it is valid for `ttl_ms`."""
    from . import data

    return data.data_load(path, name)


@mcp.tool(annotations=_READ)
def session_state() -> dict:
    """What the kernel holds right now — loaded frames (rows × columns,
    each with its `frame_handle`) and user variables — plus
    `stored_handles`, the frames that survive the kernel. A wall-timeout
    or session_reset empties the first list and leaves the second."""
    from . import data

    return data.session_state()


@mcp.tool(annotations=_SESSION_WRITE)
def py_run(
    code: str,
    wall_s: float = 60.0,
    frame_handles: dict | None = None,
) -> dict:
    """EXECUTES Python in the session kernel — pandas, numpy, scipy,
    matplotlib (Agg), plotly, altair are importable; DATA holds loaded
    frames; variables and imports survive to your next call. Use it to
    transform/aggregate before charting, or run a python recipe
    (matplotlib figures: savefig to an absolute path in the artifact
    scratch). Resource-capped (memory rlimit + your wall_s, max 570s).

    Pass `frame_handles` as {name: handle} to put stored frames back in
    DATA before the code runs — this is how you RECOVER after a timeout
    killed the kernel, and how any call gets a frame it did not load
    itself. Returns `frame_handles` for every frame in DATA afterwards,
    re-addressed if your code changed them, so the next call always has
    a durable name for the work this one did. You get them back even
    when the code raises. stdout/stderr come back bounded."""
    from . import data

    return data.py_run(code, wall_s, frame_handles)


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
) -> CallToolResult:
    """Write a Vega-Lite chart as a SOURCE DOCUMENT: <name>.vl.json +
    a rendered <name>.png land in out_dir (use the artifact scratch
    when the user asked to SEE it — the workspace opens it beside the
    conversation, live and editable). Pass data=<kernel frame name OR
    frame_handle> to inline a frame (capped at max_rows — aggregate big
    data in the kernel first); a handle reads from the store, so it
    charts even after the kernel that made it died. THE RENDER COMES
    BACK ATTACHED TO THIS RESULT —
    look at it directly, no second read — alongside `diagnostics`,
    deterministic layout checks (label collisions, a zero baseline
    flattening the data, too many series) that name defects the image
    alone makes you squint for. Rendering is local (vl-convert,
    Vega-Lite v6)."""
    from . import charts

    report, png = charts.chart_spec(spec, name, out_dir, data, max_rows)
    return _seen(report, png)


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
