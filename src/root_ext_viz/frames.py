"""Server-minted frame handles (gap plan, Gap 0).

The kernel used to hold loaded dataframes in `DATA[name]` and nothing
else. That is implicit session state pinned to one warm process, and it
had two costs.

The one users actually hit: a `py_run` over its wall kills the kernel and
respawns it EMPTY, so the next call meets a bare `NameError` about a
frame the caller loaded minutes ago and has no reason to think is gone.
The state died silently and the error blamed the code.

The one the protocol created: MCP 2026-07-28 removes sessions outright
(SEP-2575). The sanctioned replacement for cross-call state is an
explicit, server-minted handle passed back as an ordinary tool argument
(SEP-2567). Implicit `DATA[name]` cannot survive being served by more
than one replica; `DATA["sizing"]` simply is not there when the second
instance answers.

So a loaded frame is CONTENT-ADDRESSED and written down. `data_load`
returns an opaque `frame_handle`; any later call can name that handle and
get the frame back, whether or not the kernel that loaded it still
exists. The ergonomics are unchanged — load once, use many times — and
the loop now survives a kernel death.

The handle is opaque ON PURPOSE. It is `fr_` plus a truncated hash of the
frame's content, but nothing outside this module may rely on that: the
backing store moves from the session scratch to something shared the day
packs are served remotely, and that must not be a change to any tool's
contract.

Where the bytes live: `TMPDIR/root-ext-viz-frames`. Inside ROOT's sandbox
TMPDIR *is* the session scratch, so the store is session-scoped and
writable without asking for a single extra grant — it outlives the kernel
(which is what fixes the bug above) and dies with the session (which is
what keeps a dataframe from becoming a leak with a nice name).
"""

from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

HANDLE_PREFIX = "fr_"
# 16 hex of a sha256: collision-free at any plausible number of frames,
# short enough to read back in a transcript.
HANDLE_HEX = 16
_HANDLE_RE = re.compile(rf"^{HANDLE_PREFIX}[0-9a-f]{{{HANDLE_HEX}}}$")

STORE_DIRNAME = "root-ext-viz-frames"
# Long enough that a slow session never loses a frame mid-analysis, short
# enough that an abandoned one does not squat on disk. Advertised to the
# caller as `ttl_ms` so the number is the contract, not a secret.
TTL_S = 6 * 60 * 60
# Parquet is the format: typed, portable, and the obvious choice the day
# this store becomes something shared. But a dataframe is whatever user
# code bound — a column of mixed python objects is legal pandas and
# illegal parquet — and a frame that cannot be written is a frame the
# caller silently loses. Pickle is the fallback for exactly that case:
# our own bytes, in our own scratch, read back only by us.
SUFFIX = ".parquet"
FALLBACK_SUFFIX = ".pkl"
SUFFIXES = (SUFFIX, FALLBACK_SUFFIX)


def store_dir() -> Path:
    """The frame store, created on demand."""
    path = Path(tempfile.gettempdir()) / STORE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def ttl_ms() -> int:
    return TTL_S * 1000


def is_handle(value: object) -> bool:
    """Whether `value` looks like something this module minted. Used to
    tell a handle from a kernel frame NAME at the tool surface, which is
    why the two vocabularies must not overlap — a name has to be a Python
    identifier and `fr_…` hex is one, so the check is the whole shape and
    not merely the prefix."""
    return isinstance(value, str) and bool(_HANDLE_RE.match(value))


def _checked(handle: str) -> str:
    """A handle arrives as a tool argument, so it is untrusted input.
    Anything this module could not have minted is refused here, once,
    before it can become a path."""
    if not is_handle(handle):
        raise ValueError(
            f"{handle!r} is not a frame handle — pass the `frame_handle` that "
            f"data_load or py_run returned"
        )
    return handle


def path_for(handle: str, suffix: str = SUFFIX) -> Path:
    """Where a handle's bytes would live in `suffix` form."""
    return store_dir() / f"{_checked(handle)}{suffix}"


def resolve(handle: str) -> Path | None:
    """The file backing `handle`, whichever format it was written in, or
    None if the store no longer holds it (swept, or a different session's
    scratch). Callers turn None into an error that says so, rather than
    an ENOENT that says nothing."""
    for suffix in SUFFIXES:
        candidate = path_for(handle, suffix)
        if candidate.exists():
            return candidate
    return None


def _entries() -> list[Path]:
    try:
        found: list[Path] = []
        for suffix in SUFFIXES:
            found.extend(store_dir().glob(f"*{suffix}"))
        return found
    except OSError:
        return []


def sweep(now: float | None = None) -> int:
    """Drop frames past their TTL; returns how many went. Called on every
    put, so the store bounds itself without a background thread — there is
    no daemon here to outlive the server."""
    cutoff = (now if now is not None else time.time()) - TTL_S
    gone = 0
    for entry in _entries():
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                gone += 1
        except OSError:
            pass  # a frame someone else already reaped is not an error
    return gone


def known() -> list[str]:
    """Every handle the store holds, newest first — what `session_state`
    reports as durable, as against merely live."""
    dated: list[tuple[float, str]] = []
    for entry in _entries():
        try:
            if is_handle(entry.stem):
                dated.append((entry.stat().st_mtime, entry.stem))
        except OSError:
            pass
    dated.sort(reverse=True)
    return [handle for _, handle in dated]
