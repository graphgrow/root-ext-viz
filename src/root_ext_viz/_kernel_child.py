"""The sessional kernel's child program (`python -m root_ext_viz._kernel_child`).

A plain interpreter holding a namespace — no notebook machinery. The
parent speaks JSON lines on stdin/stdout; user code runs with its
stdout/stderr REDIRECTED (a print must never corrupt the protocol) and
under resource limits set before anything user-controlled runs. State
is one dict: `DATA` for loaded frames, plus whatever the code binds.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import traceback

from . import frames

MAX_STREAM_CHARS = 20_000
MAX_VALUE_ROWS = 5_000
# Where the namespace records which handle each loaded frame was last
# published under. Underscore-led so `state` does not list it as a user
# variable, and inside the namespace rather than a module global so a
# `session_reset` clears it with everything else.
HANDLES = "_HANDLES"


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


def _content_key(frame) -> str:
    """A stable content address for a dataframe.

    Hashes the shape, the column names, the dtypes and every value —
    `hash_pandas_object` is vectorized C, so this is cheap next to the
    parquet write it usually saves. Two frames with the same content get
    the same handle and share one file, which is what makes "load the
    same CSV twice" free rather than doubling the store.
    """
    import pandas as pd

    digest = hashlib.sha256()
    digest.update(repr(frame.shape).encode())
    digest.update(repr([str(c) for c in frame.columns]).encode())
    digest.update(repr([str(t) for t in frame.dtypes]).encode())
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    return frames.HANDLE_PREFIX + digest.hexdigest()[: frames.HANDLE_HEX]


def _publish(frame) -> str:
    """Write a frame into the store under its content address and return
    the handle. Idempotent: an identical frame already on disk is only
    touched, so its TTL refreshes and the bytes are never rewritten."""
    handle = _content_key(frame)
    existing = frames.resolve(handle)
    if existing is not None:
        existing.touch()
        frames.sweep()
        return handle

    target = frames.path_for(handle)
    # Write to a sibling and rename: a reader must never open a frame
    # that is still being written, and rename is atomic within a dir.
    staging = target.with_suffix(".partial")
    try:
        frame.to_parquet(staging, index=True)
    except Exception:
        staging.unlink(missing_ok=True)
        target = frames.path_for(handle, frames.FALLBACK_SUFFIX)
        staging = target.with_suffix(".partial")
        frame.to_pickle(staging)
    staging.replace(target)
    frames.sweep()
    return handle


def _restore(handle: str):
    """Read a frame back out of the store by handle."""
    import pandas as pd

    path = frames.resolve(handle)
    if path is None:
        raise KeyError(
            f"frame handle {handle!r} is not in the store — it expired "
            f"(handles live {frames.TTL_S // 3600}h) or belonged to an earlier "
            f"session; data_load the source again"
        )
    if path.suffix == frames.FALLBACK_SUFFIX:
        return pd.read_pickle(path)
    return pd.read_parquet(path)


def _publish_changed(namespace: dict) -> dict:
    """Re-address every loaded frame whose content moved, and return the
    name → handle map. Called after each run so a transformation the code
    performed is durable the moment it finishes, without the caller
    having to ask for it."""
    import pandas as pd

    recorded = namespace.setdefault(HANDLES, {})
    out: dict[str, str] = {}
    for name, frame in namespace["DATA"].items():
        if not isinstance(frame, pd.DataFrame):
            continue
        key = _content_key(frame)
        if recorded.get(name) != key:
            _publish(frame)
            recorded[name] = key
        out[name] = key
    # A frame the code deleted stops being recorded; its bytes age out.
    for gone in set(recorded) - set(out):
        recorded.pop(gone, None)
    return out


def _safe_publish(namespace: dict) -> dict:
    """`_publish_changed`, but a store that cannot be written must never
    turn a successful run into a failed one. Durability is an upgrade
    over the old behaviour, not a new way to lose an answer — so a
    publish failure degrades to the warm-kernel semantics we already
    had, and says so."""
    try:
        return _publish_changed(namespace)
    except Exception as exc:  # noqa: BLE001 — any store failure, same answer
        return {"_error": f"frames could not be persisted ({exc}); they live only in this kernel"}


def _rehydrate(namespace: dict, wanted: dict) -> list[str]:
    """Put handles back into DATA under the names the caller chose. This
    is what makes a kernel death survivable: the frames come back from
    the store, not from a process that no longer exists."""
    restored = []
    for name, handle in wanted.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError(f"frame name {name!r} must be a Python identifier")
        namespace["DATA"][name] = _restore(handle)
        namespace.setdefault(HANDLES, {})[name] = handle
        restored.append(name)
    return restored


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
        # Rehydrate BEFORE the code runs: the caller named the handles it
        # needs, and whether this kernel is the one that loaded them —
        # or a fresh one after a wall-timeout killed its predecessor —
        # is exactly the detail handles exist to make irrelevant.
        wanted = request.get("frames") or {}
        if wanted:
            try:
                _rehydrate(namespace, wanted)
            except Exception as exc:
                return {"ok": False, "stdout": "", "stderr": "", "error": str(exc)}
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                exec(request.get("code", ""), namespace)  # noqa: S102 — the tool's whole point
        except Exception:
            return {
                "ok": False,
                "stdout": _clip(out.getvalue()),
                "stderr": _clip(err.getvalue()),
                "error": _clip(traceback.format_exc(limit=8)),
                # Publish even on failure: the code may have transformed
                # one frame and then raised on the next, and losing the
                # finished work is the behaviour this whole change exists
                # to end.
                "frames": _safe_publish(namespace),
            }
        return {
            "ok": True,
            "stdout": _clip(out.getvalue()),
            "stderr": _clip(err.getvalue()),
            "frames": _safe_publish(namespace),
        }
    if op == "rehydrate":
        try:
            restored = _rehydrate(namespace, request.get("frames") or {})
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "rehydrated": restored}
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
        handle = _content_key(frame)
        published = True
        try:
            _publish(frame)
        except Exception:
            published = False
        namespace.setdefault(HANDLES, {})[name] = handle
        return {
            "ok": True,
            "profile": _profile(frame),
            "frame_handle": handle,
            "persisted": published,
        }
    if op == "state":
        import pandas as pd

        loaded = {
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
        recorded = namespace.get(HANDLES, {})
        for name, entry in loaded.items():
            if name in recorded:
                entry["frame_handle"] = recorded[name]
        return {
            "ok": True,
            "frames": loaded,
            "variables": variables,
            "stored": frames.known(),
        }
    if op == "values":
        # A handle reads straight from the store, so charting a frame
        # never depends on the kernel that produced it still being alive.
        requested = request.get("name", "")
        if frames.is_handle(requested):
            frame = _restore(requested)
        else:
            frame = _frame(namespace, requested)
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
