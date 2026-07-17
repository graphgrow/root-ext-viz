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


def _render_png(spec: dict, out_path: Path) -> None:
    import vl_convert as vlc

    png = vlc.vegalite_to_png(json.dumps(spec), scale=RENDER_SCALE)
    out_path.write_bytes(png)


def chart_spec(
    spec,
    name: str,
    out_dir: str,
    data: str | None = None,
    max_rows: int = 5000,
) -> dict:
    """Write <name>.vl.json + <name>.png into out_dir; `data` inlines a
    loaded kernel frame into the spec."""
    spec = _validated_spec(spec)
    stem = files.safe_stem(name)
    target = Path(out_dir).expanduser()
    target.mkdir(parents=True, exist_ok=True)

    clipped = False
    total_rows = None
    if data:
        reply = kernel.request({"op": "values", "name": data, "max_rows": max_rows})
        if not reply.get("ok"):
            raise ValueError(reply.get("error", "loading the frame's values failed"))
        spec["data"] = {"values": reply["values"]}
        clipped = bool(reply.get("clipped"))
        total_rows = reply.get("total_rows")

    raw = json.dumps(spec, indent=2)
    if len(raw) > MAX_SPEC_BYTES:
        raise ValueError(
            "the spec (with inlined data) exceeds 2 MB — aggregate or sample "
            "in the kernel first (py_run), then chart the summary"
        )

    spec_path = target / f"{stem}.vl.json"
    png_path = target / f"{stem}.png"
    spec_path.write_text(raw)
    _render_png(spec, png_path)

    report = {
        "written": [
            {"path": str(spec_path), "kind": "spec"},
            {"path": str(png_path), "kind": "render"},
        ],
        "note": (
            "Read the .png with fs.read to LOOK at the chart and refine the "
            "spec; the .vl.json is the editable document the user keeps."
        ),
    }
    if clipped:
        report["data_clipped"] = f"first {max_rows} of {total_rows} rows inlined"
    return report


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
