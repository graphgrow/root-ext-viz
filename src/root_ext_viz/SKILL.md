---
name: viz-eng
description: >
  Operating instructions for charting with this pack — profile before you
  plot, aggregate in the session kernel before a spec, and look at the
  render (it comes back attached to the call) plus its diagnostics before
  calling a chart done. Use when plotting data, building charts or
  dashboards, exploring a CSV or parquet file, or running Python over a
  dataframe.
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
2. **`data_load`** it into the kernel under a name. Keep the
   `frame_handle` it returns — that is the frame's durable name, and it
   is what gets you back on your feet if the kernel dies.
3. **`py_run`** to filter, join and aggregate. Do the reduction here.
4. **`viz_recipes`** with a topic for a worked template if the chart
   shape is not obvious. Call it with no topic for the index.
5. **`chart_spec`** with `data: "<frame name>"`.
6. **Look at the render — it comes back attached to that same call** —
   and read its `diagnostics`. No second read, no separate approval.
   Then refine and write again.

Step 6 is the point of the pack. A chart you have not looked at is a
guess.

### The diagnostics are not opinions

Every render reports on itself: label collisions, a zero baseline
flattening a 1% spread, too many series for a legend, a constant axis, a
missing title. These are deterministic checks against the spec and the
rows actually inlined — a string-width calculation catches three
overlapping x-labels exactly, where looking at a PNG catches them
"probably". Findings carry a `fix` when there is an obvious one.

`severity: "warn"` means the chart is misleading or unreadable **as
drawn**; fix it before showing the user. `note` is worth knowing. An
empty list means the checks ran and found nothing, which is information.

Use both. The diagnostics name what is fixable; the image is what makes
an unexpected SHAPE visible — a bimodal distribution, a cliff, an outlier
dragging a fit — and no layout check will ever tell you that.

## Two kinds of state, and only one of them is fragile

Variables and imports live in the kernel. **Frames live in a store, and
have handles.** The difference matters the moment something goes wrong.

`data_load` returns a `frame_handle` alongside the profile. It is opaque,
content-addressed, and valid for `ttl_ms` (6 hours). Keep it. Every
`py_run` returns `frame_handles` for whatever is in `DATA` afterwards,
re-addressed if your code changed the data — so the handle for a frame
you transformed is not the handle you started with, and *both* keep
working. You get them back even when your code raises.

A `py_run` that exceeds its wall budget (`wall_s`, max 570 s) **kills the
whole kernel**, not just that call. Variables and imports are gone. Your
frames are not:

```
py_run(code, frame_handles={"sizing": "fr_ae6caa3c3c5539b6"})
```

That puts the frame back in `DATA["sizing"]` before your code runs, and
you carry on. `session_state` lists `stored_handles` whenever you are
unsure what survived — including when the kernel is not running at all.
`chart_spec(data=<handle>)` works the same way, reading from the store,
so a chart draws even with no kernel alive.

Long work still belongs in smaller `py_run` calls, and a genuinely big
step still wants a raised `wall_s` rather than a shrunken analysis. The
difference is that a timeout is now a setback of one call, not of the
whole session.

## One computation, three renderings — pick by reader

A time series, a parameter sweep, a set of runs: the same data wants a
different shape depending on who is reading it. All three come out of
tools already here, so this is a choice, not a build.

**For yourself — small multiples.** `viz_recipes("small_multiples")`
gives a faceted grid: every condition at once, on shared scales, which
is what invites the comparison. This is the form a model can actually
read. An animation shows one frame at a time and you cannot hold the
others in mind while looking at it.

**For a human at a desk — the time scrubber.**
`viz_recipes("time_scrubber")` is a Vega-Lite param bound to a range
input; `chart_export(image_format="html")` inlines the vega runtime so
the file works offline, from a file:// URL, with no server. Note that
rendering it to PNG gives a still at the slider's default — if the
deliverable is static, use small multiples instead.

**For the record — the numbers.** Chart last. The series itself, or a
summary of it, is usually the thing worth keeping; a picture is how you
notice something, not how you record it.

There is deliberately no animated-GIF tool. A model reads only the first
frame of one, so it would be a rendering for humans that costs a
dependency and a code path — and for humans the scrubber is better,
because they can stop on the interesting frame.

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
