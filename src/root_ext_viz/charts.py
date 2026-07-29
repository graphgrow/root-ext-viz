"""Charts as source documents (the pack's design pillar B).

`chart_spec` writes the Vega-Lite spec (`.vl.json`) AND renders its
PNG/SVG beside it — the workspace shows the living document, the model
LOOKS at the render through the image-read path and refines. All
rendering is local vl-convert (no node, no network), pinned to the
same Vega-Lite major (v6) the workspace's bundled viewer carries, so a
spec never renders two ways.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import files, kernel

SCHEMA_V6 = "https://vega.github.io/schema/vega-lite/v6.json"
MAX_SPEC_BYTES = 2_000_000
RENDER_SCALE = 2.0
# The ceiling for the image that rides back INLINE (the file on disk is
# never downscaled). Roughly 250 KB of PNG ≈ 340 KB of base64 — large
# enough for a dense chart to stay legible, small enough that charting in
# a loop does not evict the conversation.
MAX_INLINE_PNG_BYTES = 250_000


def _validated_spec(spec) -> dict:
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except json.JSONDecodeError as exc:
            raise ValueError(f"spec is not valid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise ValueError("spec must be a Vega-Lite JSON object")
    spec.setdefault("$schema", SCHEMA_V6)
    return spec


def _render_png(spec: dict, out_path: Path) -> bytes:
    """Render, write, and hand the bytes BACK — the caller returns them
    inline as an image content block. Rendering twice to avoid passing
    bytes around would double the cost of every chart."""
    import vl_convert as vlc

    png = vlc.vegalite_to_png(json.dumps(spec), scale=RENDER_SCALE)
    out_path.write_bytes(png)
    return png


def _thumbnail(png: bytes, spec: dict) -> bytes:
    """A copy of the render bounded for the wire. The file on disk keeps
    full RENDER_SCALE fidelity; what rides back inline only has to be
    legible, and an unbounded image content block is a context bomb — a
    2x-scale chart of a dense scatter can run past a megabyte, which
    base64 then inflates by a third."""
    if len(png) <= MAX_INLINE_PNG_BYTES:
        return png
    import vl_convert as vlc

    payload = json.dumps(spec)
    smallest = png
    for scale in (1.0, 0.75, 0.5):
        smaller = vlc.vegalite_to_png(payload, scale=scale)
        smallest = smaller
        if len(smaller) <= MAX_INLINE_PNG_BYTES:
            break
    # Even the smallest render can exceed the cap for a genuinely dense
    # chart. Send it anyway: a chart too big to look at comfortably still
    # beats no chart, and the full-fidelity file is on disk regardless.
    return smallest


def chart_spec(
    spec,
    name: str,
    out_dir: str,
    data: str | None = None,
    max_rows: int = 5000,
) -> tuple[dict, bytes]:
    """Write <name>.vl.json + <name>.png into out_dir; `data` inlines a
    loaded kernel frame into the spec. Returns the report AND the PNG
    bytes, so the caller can hand the image straight back."""
    spec = _validated_spec(spec)
    stem = files.safe_stem(name)
    target = Path(out_dir).expanduser()
    target.mkdir(parents=True, exist_ok=True)

    clipped = False
    total_rows = None
    values: list | None = None
    if data:
        reply = kernel.request({"op": "values", "name": data, "max_rows": max_rows})
        if not reply.get("ok"):
            raise ValueError(reply.get("error", "loading the frame's values failed"))
        values = reply["values"]
        spec["data"] = {"values": values}
        clipped = bool(reply.get("clipped"))
        total_rows = reply.get("total_rows")
    elif isinstance(spec.get("data"), dict):
        inline = spec["data"].get("values")
        if isinstance(inline, list):
            values = inline

    raw = json.dumps(spec, indent=2)
    if len(raw) > MAX_SPEC_BYTES:
        raise ValueError(
            "the spec (with inlined data) exceeds 2 MB — aggregate or sample "
            "in the kernel first (py_run), then chart the summary"
        )

    spec_path = target / f"{stem}.vl.json"
    png_path = target / f"{stem}.png"
    spec_path.write_text(raw)
    png = _render_png(spec, png_path)

    from . import critique as critique_mod

    findings = critique_mod.critique(spec, values)
    report = {
        "written": [
            {"path": str(spec_path), "kind": "spec"},
            {"path": str(png_path), "kind": "render"},
        ],
        "diagnostics": findings,
        "note": (
            "The render is attached to this result — look at it. The .vl.json "
            "beside it is the editable document the user keeps."
            if not findings
            else "The render is attached to this result. The diagnostics above "
            "are deterministic layout checks, not opinions — a `warn` means "
            "the chart is misleading or unreadable as drawn."
        ),
    }
    if clipped:
        report["data_clipped"] = f"first {max_rows} of {total_rows} rows inlined"
    return report, _thumbnail(png, spec)


def chart_export(
    spec_path: str,
    out_path: str,
    image_format: str = "svg",
    scale: float = 2.0,
) -> dict:
    """Render an existing .vl.json to svg, png, or self-contained
    interactive html."""
    import vl_convert as vlc

    source = files.checked_path(spec_path, files.SPEC_SUFFIXES)
    target = Path(out_path).expanduser()
    files.refuse_collision(target, (source,))
    if not 0.5 <= scale <= 6:
        raise ValueError("scale must be 0.5–6")
    spec = json.dumps(_validated_spec(source.read_text()))
    if image_format == "svg":
        target.write_text(vlc.vegalite_to_svg(spec))
    elif image_format == "png":
        target.write_bytes(vlc.vegalite_to_png(spec, scale=scale))
    elif image_format == "html":
        # bundle=True inlines the vega js — self-contained, offline.
        target.write_text(vlc.vegalite_to_html(spec, bundle=True))
    else:
        raise ValueError("image_format must be svg, png, or html")
    target_bytes = target.stat().st_size
    return {
        "written": [{"path": str(target), "kind": image_format}],
        "bytes": target_bytes,
    }
