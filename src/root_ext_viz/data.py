"""Data plumbing (pillar E): profile before you plot; load into the
kernel so iteration is cheap. The profile is parent-side and bounded —
a million-row file is described, never dumped."""

from __future__ import annotations

from . import files, kernel

PROFILE_SAMPLE_ROWS = 100_000


def data_profile(path: str) -> dict:
    import pandas as pd

    resolved = files.checked_path(path, files.DATA_SUFFIXES)
    lowered = resolved.name.lower()
    sampled = False
    if lowered.endswith((".csv", ".tsv")):
        sep = "\t" if lowered.endswith(".tsv") else ","
        frame = pd.read_csv(resolved, sep=sep, nrows=PROFILE_SAMPLE_ROWS)
        sampled = len(frame) == PROFILE_SAMPLE_ROWS
    elif lowered.endswith(".parquet"):
        frame = pd.read_parquet(resolved)
    elif lowered.endswith(".xlsx"):
        frame = pd.read_excel(resolved)
    else:
        frame = pd.read_json(resolved)

    numeric = frame.select_dtypes("number")
    text, truncated = files.budget_text(
        f"## Head\n{frame.head(5).to_markdown(index=False)}\n\n## Numeric summary\n"
        + (numeric.describe().round(4).to_markdown() if not numeric.empty else "(no numeric columns)")
    )
    return {
        "source": str(resolved),
        "rows_seen": int(len(frame)),
        "sampled": sampled,
        "columns": {c: str(t) for c, t in frame.dtypes.items()},
        "profile": text,
        "truncated": truncated,
    }


def data_load(path: str, name: str) -> dict:
    resolved = files.checked_path(path, files.DATA_SUFFIXES)
    if not name.isidentifier():
        raise ValueError(f"name {name!r} must be a Python identifier (it becomes DATA[{name!r}])")
    reply = kernel.request({"op": "load", "path": str(resolved), "name": name})
    if not reply.get("ok"):
        raise ValueError(reply.get("error", "load failed"))
    return {"source": str(resolved), "name": name, **reply["profile"]}


def session_state() -> dict:
    if not kernel.running():
        return {
            "kernel": "not running",
            "note": "data_load or py_run starts it; nothing is loaded yet.",
        }
    reply = kernel.request({"op": "state"}, wall_s=10)
    if not reply.get("ok"):
        raise ValueError(reply.get("error", "state failed"))
    return {"kernel": "running", "frames": reply["frames"], "variables": reply["variables"]}


def py_run(code: str, wall_s: float = 60.0) -> dict:
    if not code.strip():
        raise ValueError("code is empty")
    if not 1 <= wall_s <= 75:
        raise ValueError("wall_s must be 1–75 (the bridge ceiling is 90)")
    reply = kernel.request({"op": "run", "code": code}, wall_s=wall_s)
    out = {
        "ok": bool(reply.get("ok")),
        "stdout": reply.get("stdout", ""),
        "stderr": reply.get("stderr", ""),
    }
    if not reply.get("ok"):
        out["error"] = reply.get("error", "the code raised")
    return out


def session_reset() -> dict:
    kernel.reset()
    return {"status": "reset", "note": "the kernel is empty — data_load again"}
