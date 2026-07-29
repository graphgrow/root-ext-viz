"""Chart self-critique (gap plan, Gap 5, item 2).

The vision loop's weak link was never the render — it was that the tool
handed back a path and left the model to notice its own mistakes by
looking. Looking is the expensive, lossy step: a model reading a PNG can
miss three overlapping x-labels that a string-width calculation catches
exactly.

So every render reports on itself. These are DETERMINISTIC checks against
the spec and the inlined data, not image analysis — cheap enough to run
on every call, and precise where perception is vague. They accompany the
image rather than replacing it: the image is what makes an unexpected
shape visible, the diagnostics are what make a fixable defect nameable.

Each finding is `{code, severity, message}` with a `fix` when there is an
obvious one. `severity` is "warn" (the chart is misleading or unreadable)
or "note" (worth knowing, not necessarily wrong). A clean chart returns
an empty list, which is itself information — it means the checks ran.
"""

from __future__ import annotations

from typing import Any

# A rendered axis label is roughly this many points per character at the
# Vega-Lite default (11pt sans). Used only to estimate collisions, so it
# errs generous: over-reporting a collision that is not there wastes a
# round trip, under-reporting it wastes the whole chart.
_PT_PER_CHAR = 6.0
_DEFAULT_WIDTH = 200.0
_DEFAULT_HEIGHT = 200.0
# Vega-Lite's own default; a categorical scale past this many bands is
# unreadable regardless of label length.
_CROWDED_BANDS = 30
# More series than the eye can track in one legend.
_MAX_SERIES = 12
# Below this fraction of the axis range, the data occupies so little of
# the plot that the axis is lying about the scale.
_MIN_RANGE_FILL = 0.15


def _finding(code: str, severity: str, message: str, fix: str | None = None) -> dict:
    out = {"code": code, "severity": severity, "message": message}
    if fix:
        out["fix"] = fix
    return out


def _encodings(spec: dict) -> dict:
    """The chart's encoding block, whether the spec is single-view or a
    layer/facet/concat wrapper (we critique the first view we find —
    a compound spec's first layer is what the reader sees first)."""
    if isinstance(spec.get("encoding"), dict):
        return spec["encoding"]
    for key in ("layer", "hconcat", "vconcat", "concat"):
        views = spec.get(key)
        if isinstance(views, list):
            for view in views:
                if isinstance(view, dict) and isinstance(view.get("encoding"), dict):
                    return view["encoding"]
    inner = spec.get("spec")
    if isinstance(inner, dict):
        return _encodings(inner)
    return {}


def _field(channel: Any) -> str | None:
    if isinstance(channel, dict):
        field = channel.get("field")
        return field if isinstance(field, str) else None
    return None


def _numeric(values: list[dict], field: str) -> list[float]:
    out: list[float] = []
    for row in values:
        v = row.get(field)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def _axis_label_collisions(
    values: list[dict], encoding: dict, width: float
) -> dict | None:
    """Estimate whether the x labels can physically fit side by side."""
    x = encoding.get("x")
    field = _field(x)
    if not field or not values:
        return None
    kind = x.get("type") if isinstance(x, dict) else None
    if kind not in (None, "nominal", "ordinal"):
        return None  # continuous axes get ticks, not one label per datum

    labels = {str(row.get(field)) for row in values if row.get(field) is not None}
    if not labels:
        return None
    if len(labels) > _CROWDED_BANDS:
        return _finding(
            "x_axis_crowded",
            "warn",
            f"{len(labels)} distinct x values on a categorical axis — the bands "
            f"are too narrow to read",
            "aggregate into fewer categories, or make it a continuous axis",
        )
    widest = max(len(label) for label in labels) * _PT_PER_CHAR
    per_band = width / max(len(labels), 1)
    if widest > per_band:
        return _finding(
            "x_labels_collide",
            "warn",
            f"about {len(labels)} x labels at ~{widest:.0f}pt wide share "
            f"~{per_band:.0f}pt bands — they will overlap",
            'set encoding.x.axis.labelAngle to -45, or widen the chart',
        )
    return None


def _range_fill(values: list[dict], encoding: dict) -> list[dict]:
    """Does the data actually occupy its axis, and is a zero-baseline
    hiding the variation the chart exists to show?"""
    out: list[dict] = []
    for channel in ("x", "y"):
        enc = encoding.get(channel)
        field = _field(enc)
        if not field:
            continue
        nums = _numeric(values, field)
        if len(nums) < 2:
            continue
        low, high = min(nums), max(nums)
        span = high - low
        if span == 0:
            out.append(
                _finding(
                    f"{channel}_constant",
                    "note",
                    f"every {field} is {low:g} — the {channel} axis carries no information",
                )
            )
            continue
        scale = enc.get("scale") if isinstance(enc, dict) else None
        zero = True if not isinstance(scale, dict) else scale.get("zero", True)
        if zero and low > 0 and span < low * _MIN_RANGE_FILL:
            out.append(
                _finding(
                    f"{channel}_zero_baseline_flattens",
                    "warn",
                    f"{field} varies {low:g}–{high:g}, a {span / low:.1%} spread, but "
                    f"the {channel} axis starts at zero — the variation is invisible",
                    f'set encoding.{channel}.scale.zero to false',
                )
            )
    return out


def _series_count(values: list[dict], encoding: dict) -> dict | None:
    for channel in ("color", "detail", "shape"):
        field = _field(encoding.get(channel))
        if not field:
            continue
        series = {str(row.get(field)) for row in values if row.get(field) is not None}
        if len(series) > _MAX_SERIES:
            return _finding(
                "too_many_series",
                "warn",
                f"{len(series)} series on {channel} — past about {_MAX_SERIES} the "
                f"legend stops being readable and colours repeat",
                "facet, or plot the few series that carry the point",
            )
    return None


def _missing_pieces(spec: dict, encoding: dict) -> list[dict]:
    out: list[dict] = []
    if not encoding:
        out.append(
            _finding(
                "no_encoding",
                "note",
                "no encoding block found — the critique could not inspect this spec",
            )
        )
        return out
    if not any(k in spec for k in ("title", "description")):
        out.append(
            _finding(
                "no_title",
                "note",
                "the chart has no title — a reader meeting it outside this "
                "conversation has no idea what it shows",
            )
        )
    for channel in ("x", "y"):
        enc = encoding.get(channel)
        if isinstance(enc, dict) and _field(enc):
            axis = enc.get("axis")
            titled = isinstance(axis, dict) and axis.get("title")
            if not titled and enc.get("aggregate"):
                out.append(
                    _finding(
                        f"{channel}_aggregate_unlabelled",
                        "note",
                        f"the {channel} axis is an aggregate "
                        f"({enc['aggregate']}) with no axis title — it will read "
                        f"as a raw quantity",
                        f'set encoding.{channel}.axis.title',
                    )
                )
    return out


def critique(spec: dict, values: list[dict] | None) -> list[dict]:
    """Deterministic layout findings for one rendered chart, most severe
    first. `values` are the rows actually inlined into the spec — the
    critique only speaks about data the chart really carries."""
    encoding = _encodings(spec)
    rows = values or []
    findings = _missing_pieces(spec, encoding)
    if encoding:
        width = spec.get("width")
        width = float(width) if isinstance(width, (int, float)) else _DEFAULT_WIDTH
        collision = _axis_label_collisions(rows, encoding, width)
        if collision:
            findings.append(collision)
        findings.extend(_range_fill(rows, encoding))
        series = _series_count(rows, encoding)
        if series:
            findings.append(series)
    order = {"warn": 0, "note": 1}
    findings.sort(key=lambda f: order.get(f["severity"], 2))
    return findings
