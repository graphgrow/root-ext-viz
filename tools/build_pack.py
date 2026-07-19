"""Build the signed .rootx extension pack (ADR-0018, publisher side).

Usage:
    .venv/bin/python tools/build_pack.py [--key /path/to/graphgrow-packs.key]

Reads the freshly built wheel from dist/, writes extension.json, signs
its exact bytes with the publisher's ed25519 key (detached, base64),
and zips the artifacts into dist/viz-eng-<version>.rootx. Without
--key (or if the key file is absent) it builds an UNSIGNED pack.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_KEY = pathlib.Path(
    "~/Desktop/Professional/graphgrow-pack-signing/graphgrow-packs.key"
).expanduser()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", type=pathlib.Path, default=DEFAULT_KEY)
    parser.add_argument("--unsigned", action="store_true")
    args = parser.parse_args()

    wheels = sorted((ROOT / "dist").glob("root_ext_viz-*-py3-none-any.whl"))
    if not wheels:
        print("no wheel in dist/ — run `uv build` first", file=sys.stderr)
        return 1
    wheel = wheels[-1]
    version = wheel.name.split("-")[1]
    sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()

    manifest = {
        "schema": 1,
        "id": "dev.graphgrow.viz-eng",
        "name": "viz-eng",
        "title": "Data Visualization",
        "version": version,
        "publisher": "graphgrow",
        "description": (
            "A sessional Python kernel (pandas/numpy/scipy/matplotlib/plotly/"
            "altair — state survives across calls), Vega-Lite charts as source "
            "documents rendered locally by vl-convert, and engineering chart "
            "recipes. Compute and plot; outputs land only in derived or "
            "artifact directories — by charter and by test."
        ),
        "entry": {
            "kind": "python-wheel",
            "wheel": f"wheels/{wheel.name}",
            "sha256": sha256,
            "script": "root-ext-viz",
        },
        # No network anywhere — rendering is local vl-convert.
        "needs": {},
        # First-class promotion (ADR-0019): pure reads run SANDBOXED
        # except session_state (talks to the live kernel process);
        # session tools EXECUTE code / mutate kernel state and the
        # derived-writes create artifacts — all user-program writes.
        # The pack's operating instructions (ADR-0025). Only the POINTER
        # lives in the manifest; the text rides inside the wheel, whose
        # sha256 this manifest pins — so the signature that covers the
        # manifest covers the instructions too, with nothing extra to
        # sign and one copy to keep in sync. Note what is absent: no
        # field here grants a tool or widens a permission. A skill tells
        # the model what to do; it can never change what it is allowed
        # to do.
        "skill": {"body": "root_ext_viz/SKILL.md"},
        "tools": [
            *(
                {"name": name, "side_effect": "read", "posture": "sandboxed"}
                for name in ("data_profile", "viz_recipes")
            ),
            {"name": "session_state", "side_effect": "read", "posture": "user-program"},
            *(
                {"name": name, "side_effect": "write", "posture": "user-program"}
                for name in (
                    "data_load", "py_run", "session_reset",
                    "chart_spec", "chart_export",
                )
            ),
        ],
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode()

    signature_b64 = None
    if not args.unsigned and args.key.is_file():
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        raw = base64.b64decode(args.key.read_text().strip())
        key = Ed25519PrivateKey.from_private_bytes(raw)
        signature_b64 = base64.b64encode(key.sign(manifest_bytes)).decode()
        print(f"signed as graphgrow with {args.key}")
    else:
        print("building UNSIGNED (installs as unverified)")

    out = ROOT / "dist" / f"viz-eng-{version}.rootx"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as pack:
        pack.writestr("extension.json", manifest_bytes)
        if signature_b64:
            pack.writestr("extension.json.sig", signature_b64 + "\n")
        pack.write(wheel, f"wheels/{wheel.name}")
    print(f"built {out} ({out.stat().st_size:,} bytes; wheel sha256 {sha256[:16]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
