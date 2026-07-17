# root-ext-viz

Data-visualization MCP tool server for ROOT Workspace (and any MCP
host). Five pillars:

1. **Sessional kernel** — `data_load` / `py_run` / `session_state` /
   `session_reset`: dataframes, imports, and variables survive across
   tool calls (pandas, numpy, scipy, matplotlib, plotly, altair).
   Resource-capped child interpreter; a wall-timeout names its state
   loss, never hides it.
2. **Charts as source documents** — `chart_spec` writes the Vega-Lite
   `.vl.json` AND renders its PNG beside it. The workspace renders the
   spec live (bundled vega, same v6 major as our vl-convert), the user
   keeps editing it; pixels are derived.
3. **The vision loop** — every render returns its path; the model reads
   the PNG back through the workspace's image-read path, looks, and
   refines.
4. **Recipes, not 25 tools** — `viz_recipes`: line/scatter/bar/
   histogram/cdf/log_axes/error_bars/tolerance_band/control_chart/
   heatmap (Vega-Lite) + bode/fft/contour (python).
5. **Bounded data plumbing** — `data_profile` first; inlined chart data
   capped; aggregate in the kernel, chart the summary.

**Charter, binding and tested: compute and plot; outputs land only in
derived or artifact directories, never on a source.** Nothing reaches
the network — rendering is local vl-convert (no node).

## Develop

```sh
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest
```

## Package (signed .rootx, ADR-0018)

```sh
uv build
.venv/bin/python tools/build_pack.py   # --unsigned for a test build
```
