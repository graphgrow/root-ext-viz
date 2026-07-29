"""Data plumbing (pillar E): profile before you plot; load into the
kernel so iteration is cheap. The profile is parent-side and bounded —
a million-row file is described, never dumped."""

from __future__ import annotations

from . import files, frames, kernel

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
    if frames.is_handle(name):
        raise ValueError(
            f"name {name!r} looks like a frame handle — pick a name you would "
            f"write in code, so the two vocabularies never blur"
        )
    reply = kernel.request({"op": "load", "path": str(resolved), "name": name})
    if not reply.get("ok"):
        raise ValueError(reply.get("error", "load failed"))
    out = {
        "source": str(resolved),
        "name": name,
        "frame_handle": reply.get("frame_handle"),
        "ttl_ms": frames.ttl_ms(),
        **reply["profile"],
    }
    if not reply.get("persisted", True):
        # Say it rather than let the caller discover it after a kernel
        # death: the handle exists but nothing is behind it.
        out["durable"] = False
        out["note"] = (
            "this frame could not be written to the store — it lives only in "
            "the kernel, so a wall-timeout will lose it"
        )
    return out


def session_state() -> dict:
    stored = frames.known()
    if not kernel.running():
        return {
            "kernel": "not running",
            "frames": {},
            "variables": [],
            "stored_handles": stored,
            "note": (
                "data_load or py_run starts it. Frames listed under "
                "stored_handles survive the kernel — pass one to py_run's "
                "`frames` to bring it back."
                if stored
                else "data_load or py_run starts it; nothing is loaded yet."
            ),
        }
    reply = kernel.request({"op": "state"}, wall_s=10)
    if not reply.get("ok"):
        raise ValueError(reply.get("error", "state failed"))
    return {
        "kernel": "running",
        "frames": reply["frames"],
        "variables": reply["variables"],
        "stored_handles": reply.get("stored", stored),
        "ttl_ms": frames.ttl_ms(),
    }


def py_run(
    code: str,
    wall_s: float = 60.0,
    frame_handles: dict | None = None,
) -> dict:
    if not code.strip():
        raise ValueError("code is empty")
    wanted = frame_handles or {}
    if not isinstance(wanted, dict):
        raise ValueError(
            "frame_handles must be a {name: frame_handle} object — the name is "
            "what the frame is called in DATA, the handle is what data_load "
            "returned"
        )
    for name, handle in wanted.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError(f"frame name {name!r} must be a Python identifier")
        if not frames.is_handle(handle):
            raise ValueError(
                f"{handle!r} is not a frame handle — pass the `frame_handle` "
                f"that data_load or py_run returned for {name!r}"
            )
    # The cap sits just under the session budget this pack's manifest
    # declares (timeout_ms 600_000). Layers, in order: this wall kills a
    # runaway CALL and respawns the interpreter, keeping the server — and
    # so the client's warm session — alive; the client's budget is the
    # outer bound and kills the server itself. Leaving room between them
    # means a long analysis fails as a named state loss, not a dead
    # session.
    if not 1 <= wall_s <= 570:
        raise ValueError("wall_s must be 1–570 (the session budget is 600 s)")
    reply = kernel.request(
        {"op": "run", "code": code, "frames": wanted}, wall_s=wall_s
    )
    out = {
        "ok": bool(reply.get("ok")),
        "stdout": reply.get("stdout", ""),
        "stderr": reply.get("stderr", ""),
    }
    # Handles for every frame now in DATA, re-addressed if the code moved
    # them. Returned on failure too — code that transformed one frame and
    # then raised on the next must not lose the finished work.
    published = reply.get("frames")
    if isinstance(published, dict):
        note = published.pop("_error", None)
        if published:
            out["frame_handles"] = published
            out["ttl_ms"] = frames.ttl_ms()
        if note:
            out["durable"] = False
            out["note"] = note
    if not reply.get("ok"):
        out["error"] = reply.get("error", "the code raised")
    return out


def session_reset() -> dict:
    kernel.reset()
    return {"status": "reset", "note": "the kernel is empty — data_load again"}
