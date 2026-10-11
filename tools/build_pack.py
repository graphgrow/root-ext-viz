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
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_KEY = pathlib.Path(
    "~/Desktop/Professional/graphgrow-pack-signing/graphgrow-packs.key"
).expanduser()


def _project_version() -> str:
    """The version in pyproject.toml, not whatever wheel sorts last.

    `sorted()` is lexicographic, so "0.10.0" sorts BEFORE "0.5.1" and
    taking `[-1]` silently packaged a stale wheel the moment a pack
    reached 0.10. Caught in drone-eng, which built `drone-eng-0.5.1.rootx`
    from a tree whose source said 0.10.0 — signed and catalogued as a
    release. Naming the wheel we want removes the guess, and also catches
    a dist/ that was simply never rebuilt.
    """
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("no version in pyproject.toml")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", type=pathlib.Path, default=DEFAULT_KEY)
    parser.add_argument("--unsigned", action="store_true")
    args = parser.parse_args()

    version = _project_version()
    # The pack ships the COMPILED wheel (ADR-0097): `uv build` makes the
    # pure one, root-packs/tools/compile_wheel.py makes this one from it.
    # Exactly one, by exact version: never the pure wheel, never a guess.
    wheels = sorted((ROOT / "dist").glob(f"root_ext_viz-{version}-cp312-abi3-*.whl"))
    if len(wheels) != 1:
        print(
            f"need exactly one compiled wheel for {version} in dist/ (found "
            f"{len(wheels)}) — run `uv build`, then root-packs/tools/compile_wheel.py",
            file=sys.stderr,
        )
        return 1
    wheel = wheels[0]
    sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()

    # A stale wheel in dist/ is packaged silently: bump the version, forget
    # to rebuild, and this script signs the PREVIOUS release's code under
    # whatever version its filename happens to carry. `sorted()` makes it
    # worse than it sounds — it orders lexically, so 0.10.0 sorts BEFORE
    # 0.9.0 and `wheels[-1]` picks the older one. Compare against the
    # declared version instead of trusting the newest file on disk.
    declared = re.search(
        r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M
    )
    if declared and declared.group(1) != version:
        print(
            f"dist/ holds {wheel.name} but pyproject declares "
            f"{declared.group(1)} — rebuild with `uv build` (and clear the "
            "stale wheel) before packing.",
            file=sys.stderr,
        )
        return 1

    manifest = {
        "schema": 2,
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
        # ADR-0026 §2/§3: capability GRANTS, not a posture. `needs` is
        # gone with the posture axis — it was declared and never
        # enforced. Every tool here is sandboxed now, including the
        # kernel; nothing reaches the network at all (rendering is local
        # vl-convert), and nothing leaves the granted folders.
        #
        # THE KERNEL'S BARGAIN, stated plainly. This pack used to take
        # `user-program` — the user's whole filesystem, network, and
        # credentials — for one reason: a dataframe had to survive
        # between calls, and warmth was only available by accident, as a
        # side effect of the transport that posture happened to pick.
        # `session: "warm"` makes it a declared capability the client
        # enforces, so statefulness stops costing privilege.
        #
        # One warm server process holds every warm tool, and a
        # confinement is fixed at the spawn that starts it — so the warm
        # set must declare ONE grant, and it is the UNION of what those
        # tools need. `chart_spec` writes a spec beside the data and
        # `py_run` executes analysis in that same interpreter, so the
        # union is `roots-write`. Declaring `data_load` as read-only
        # while it shares an address space with `py_run` would be a word
        # the sandbox cannot enforce; the client refuses to parse that,
        # and rightly.
        #
        # `py_run` deliberately: it runs model-authored Python in the
        # kernel, with the granted folders readable and writable and NO
        # network. That is the honest scope of "a Python session working
        # on your data" — narrower than today by the whole machine, and
        # not narrowed further, because forcing data in through
        # `data_load` alone would break the analysis loop this pack
        # exists to serve while leaving the same folders reachable
        # anyway through the sibling tools in the same process.
        #
        # The three tools that DON'T touch the kernel stay per-call and
        # get exactly what they use — the cheap path, still the default.
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
            # ── per-call: never touches the kernel ──────────────────
            # Profiles a file with pandas in its own short-lived child.
            {
                "name": "data_profile",
                "side_effect": "read",
                "grants": {"filesystem": "roots-read"},
            },
            # A static template catalog. It reads nothing and writes
            # nothing — so it asks for nothing.
            {"name": "viz_recipes", "side_effect": "read", "grants": {}},
            # Renders an existing .vl.json to svg/png/html. Pure
            # vl-convert, no session state.
            {
                "name": "chart_export",
                "side_effect": "write",
                "grants": {"filesystem": "roots-write"},
            },
            # ── warm: one live interpreter, one shared grant ────────
            {
                "name": "session_state",
                "side_effect": "read",
                "grants": {"filesystem": "roots-write", "session": "warm"},
            },
            *(
                {
                    "name": name,
                    "side_effect": "write",
                    "grants": {"filesystem": "roots-write", "session": "warm"},
                    # A kernel call is analysis, not a lookup: the wall
                    # inside the pack tops out at 75 s per call, and the
                    # client's 90 s default would kill the server around
                    # it. Ten minutes is the session's budget; a caller
                    # that knows the job is big raises it per call.
                    "timeout_ms": 600_000,
                }
                for name in ("data_load", "py_run", "session_reset", "chart_spec")
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
