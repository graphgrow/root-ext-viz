"""The sessional kernel's child program (`python -m root_ext_viz._kernel_child`).

A plain interpreter holding a namespace — no notebook machinery. The
parent speaks JSON lines on stdin/stdout; user code runs with its
stdout/stderr REDIRECTED (a print must never corrupt the protocol) and
under resource limits set before anything user-controlled runs. State
is one dict: `DATA` for loaded frames, plus whatever the code binds.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import traceback

MAX_STREAM_CHARS = 20_000
MAX_VALUE_ROWS = 5_000


def _set_limits() -> None:
    try:
        import resource

        gib = 1 << 30
        # Address-space cap (best-effort on macOS) + a cumulative CPU
        # ceiling as the spin backstop; the WALL bound lives in the
        # parent, which kills and respawns on timeout.
        resource.setrlimit(resource.RLIMIT_AS, (4 * gib, 4 * gib))
        resource.setrlimit(resource.RLIMIT_CPU, (600, 600))
    except Exception:
        pass  # limits are a backstop, not a feature gate


def _clip(text: str) -> str:
    if len(text) <= MAX_STREAM_CHARS:
        return text
    return text[:MAX_STREAM_CHARS] + "\n… (truncated)"


def _frame(namespace: dict, name: str):
    import pandas as pd

    frame = namespace["DATA"].get(name)
    if frame is None:
        raise KeyError(
            f"no loaded frame {name!r} — data_load it first "
            f"(loaded: {sorted(namespace['DATA'])})"
        )
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"DATA[{name!r}] is {type(frame).__name__}, not a DataFrame")
    return frame


def _profile(frame) -> dict:
    head = frame.head(5).to_markdown(index=False)
    numeric = frame.select_dtypes("number")
    describe = numeric.describe().round(4).to_markdown() if not numeric.empty else ""
    return {
        "rows": int(len(frame)),
        "columns": {c: str(t) for c, t in frame.dtypes.items()},
        "head": head,
        "numeric_summary": describe,
    }


def _handle(namespace: dict, request: dict) -> dict:
    op = request.get("op", "")
    if op == "run":
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                exec(request.get("code", ""), namespace)  # noqa: S102 — the tool's whole point
            return {"ok": True, "stdout": _clip(out.getvalue()), "stderr": _clip(err.getvalue())}
        except Exception:
            return {
                "ok": False,
                "stdout": _clip(out.getvalue()),
                "stderr": _clip(err.getvalue()),
                "error": _clip(traceback.format_exc(limit=8)),
            }
    if op == "load":
        import pandas as pd

        path, name = request["path"], request["name"]
        lowered = path.lower()
        if lowered.endswith((".csv", ".tsv")):
            frame = pd.read_csv(path, sep="\t" if lowered.endswith(".tsv") else ",")
        elif lowered.endswith(".parquet"):
            frame = pd.read_parquet(path)
        elif lowered.endswith(".xlsx"):
            frame = pd.read_excel(path)
        elif lowered.endswith(".json"):
            frame = pd.read_json(path)
        else:
            return {"ok": False, "error": f"no loader for {path!r}"}
        namespace["DATA"][name] = frame
        return {"ok": True, "profile": _profile(frame)}
    if op == "state":
        import pandas as pd

        frames = {
            name: {"rows": int(len(f)), "columns": list(map(str, f.columns))}
            for name, f in namespace["DATA"].items()
            if isinstance(f, pd.DataFrame)
        }
        variables = sorted(
            name
            for name, value in namespace.items()
            if not name.startswith("_")
            and name not in ("DATA",)
            and not callable(value)
            and not isinstance(value, type(sys))
        )
        return {"ok": True, "frames": frames, "variables": variables}
    if op == "values":
        frame = _frame(namespace, request["name"])
        rows = min(int(request.get("max_rows", MAX_VALUE_ROWS)), MAX_VALUE_ROWS)
        clipped = len(frame) > rows
        records = json.loads(frame.head(rows).to_json(orient="records"))
        return {"ok": True, "values": records, "clipped": clipped, "total_rows": int(len(frame))}
    return {"ok": False, "error": f"unknown op {op!r}"}


def main() -> None:
    _set_limits()
    os.environ.setdefault("MPLBACKEND", "Agg")
    protocol_out = sys.stdout
    namespace: dict = {"DATA": {}, "__name__": "__kernel__"}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            reply = {"ok": False, "error": f"bad request line: {exc}"}
        else:
            try:
                reply = _handle(namespace, request)
            except Exception:
                reply = {"ok": False, "error": _clip(traceback.format_exc(limit=8))}
        protocol_out.write(json.dumps(reply) + "\n")
        protocol_out.flush()


if __name__ == "__main__":
    main()
