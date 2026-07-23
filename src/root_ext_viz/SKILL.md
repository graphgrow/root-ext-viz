---
name: viz-eng
description: >
  Operating instructions for charting with this pack — profile before you
  plot, aggregate in the session kernel before a spec, and look at the
  rendered PNG before calling a chart done. Use when plotting data,
  building charts or dashboards, exploring a CSV or parquet file, or
  running Python over a dataframe.
paths:
  - "*.vl.json"
  - "*.csv"
  - "*.tsv"
  - "*.parquet"
  - "*.xlsx"
license: MIT
---

# Data visualization — operating notes

Charts here are **source documents**, not pictures. `chart_spec` writes a
`.vl.json` the user keeps and can edit, and renders a `.png` beside it.
The workspace renders the `.vl.json` live. Never treat the PNG as the
deliverable.

## The loop that actually works

1. **`data_profile`** the file. Always, before designing anything. You
   need the row count, the dtypes and the numeric summary before you can
   choose a chart — guessing the shape and then fixing the spec twice is
   slower than looking once.
2. **`data_load`** it into the session kernel under a name. It starts the
   kernel on first use and the frame survives your later calls.
3. **`py_run`** to filter, join and aggregate. Do the reduction here.
4. **`viz_recipes`** with a topic for a worked template if the chart
   shape is not obvious. Call it with no topic for the index.
5. **`chart_spec`** with `data: "<frame name>"`.
6. **`fs.read` the returned `.png` and actually look at it.** Overlapping
   labels, a broken scale, an empty facet — none of these appear in the
   spec. Then refine and write again.

Step 6 is the point of the pack. A chart you have not looked at is a
guess.

## The kernel survives — and dies all at once

Variables, imports and loaded frames persist across `py_run` calls. Load
once, iterate cheaply.

But a `py_run` that exceeds its wall budget (`wall_s`, max 570 s) **kills
the whole kernel**, not just that call. Every loaded frame and every
variable is gone, and the error says so. After a timeout you must
`data_load` again before anything else will work. If you are unsure what
survived, `session_state` tells you exactly what the kernel holds.

Long work belongs in smaller `py_run` calls for this reason — and when a
single step is genuinely big, raise `wall_s` for that call rather than
shrinking the analysis to fit the default.

## Aggregate before you plot

`chart_spec` inlines the frame into the spec and caps it at `max_rows`
(5000 by default). A million-row frame does not become a chart — it
becomes a truncated one.

Reduce in the kernel first: group, bin, sample deliberately. A chart of
50 aggregated rows is both correct and legible; a chart of 5000 raw ones
is neither.

`data_profile` is bounded the same way and samples at 100k rows for large
CSVs, so treat its row count as approximate on big files.

## Where output goes

When the user asked to *see* something, write into the artifact scratch —
the workspace opens it beside the conversation, live and editable.
Otherwise write beside the source in a derived directory.

Outputs never land on a source file. `chart_export` refuses an output
path that collides with the spec it is rendering.

## Rendering is local and version-pinned

vl-convert renders on this machine — no node, no network. It is pinned to
Vega-Lite **v6**, the same major the workspace viewer carries, so a spec
never renders two different ways. Write v6 specs; if you reach for syntax
from another major, it will not render the way you expect.

`chart_export` also produces self-contained interactive HTML with the
Vega runtime inlined — it opens in a browser and works offline. That is
the right format when the user wants to hand the chart to someone
without this workspace.

## Recipes teach shape, not answers

`viz_recipes` returns worked templates: line, scatter, bar, histogram,
cdf, log_axes, error_bars, tolerance_band, control_chart and heatmap as
Vega-Lite; bode, fft and contour as Python for `py_run`. Adapt the fields
to the actual data — the template's column names are illustrative.

## What this pack will refuse

It computes and plots. It does not overwrite, delete, move or edit a
user's file, and nothing here reaches the network. `py_run` executes real
Python and says so in capitals — treat it as the write-class tool it is,
and do not use it to work around a refusal elsewhere.
