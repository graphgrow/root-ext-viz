"""The sessional kernel, parent side (the pack's design pillar A).

One persistent child interpreter per server process, so dataframes and
imports SURVIVE across tool calls: load once, iterate.

That survival is not something this pack can arrange on its own — it
depends on the CLIENT holding this server process open between calls,
so we ASK for it: the tools that use this kernel declare
`session: "warm"` in the manifest (ADR-0026 §3), and ROOT grants it by
keeping one confined server per pack alive, retiring it when the grant,
the granted roots, or the pack itself changes. An earlier version of
this docstring claimed "the bridge keeps MCP servers warm", which was
true only by accident: warmth was a side effect of the transport the
old `user-program` posture happened to pick, nothing declared it, and
nothing would have said so when it stopped being true. A client that
does not honor the grant simply gets a cold kernel each call — slower,
never wrong.

Bounds are honest and layered: the child sets memory/CPU rlimits on
itself before user code runs; the WALL bound lives here — a call over
its wall is killed and the whole kernel respawns empty, with the state
loss named in the error rather than hidden. That inner kill keeps THIS
server answering, so the client's warm session survives a runaway call;
only a failure of the server itself costs the session.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import threading

DEFAULT_WALL_S = 60.0
MAX_REPLY_BYTES = 50_000_000

_lock = threading.Lock()
_child: subprocess.Popen | None = None


def _spawn() -> subprocess.Popen:
    env = dict(os.environ)
    env.setdefault("MPLBACKEND", "Agg")  # figures render headless, always
    return subprocess.Popen(
        [sys.executable, "-m", "root_ext_viz._kernel_child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=False,
    )


def _kill(child: subprocess.Popen) -> None:
    try:
        child.kill()
        child.wait(timeout=5)
    except Exception:
        pass


def _read_reply(child: subprocess.Popen, wall_s: float) -> dict:
    """Read one JSON line with a wall deadline; a silent or flooding
    kernel is killed, never waited on forever."""
    assert child.stdout is not None
    fd = child.stdout.fileno()
    buffer = bytearray()
    import time

    deadline = time.monotonic() + wall_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        ready, _, _ = select.select([fd], [], [], min(remaining, 1.0))
        if not ready:
            continue
        chunk = os.read(fd, 65_536)
        if not chunk:
            raise RuntimeError("the kernel exited mid-call")
        buffer.extend(chunk)
        if len(buffer) > MAX_REPLY_BYTES:
            raise RuntimeError("the kernel reply exceeded the 50 MB cap")
        if buffer.endswith(b"\n"):
            return json.loads(buffer.decode())


def request(payload: dict, wall_s: float = DEFAULT_WALL_S) -> dict:
    """One round-trip. Spawns on first use; a wall-timeout kills and
    clears the kernel so the NEXT call starts fresh."""
    global _child
    with _lock:
        if _child is None or _child.poll() is not None:
            _child = _spawn()
        child = _child
        try:
            assert child.stdin is not None
            child.stdin.write((json.dumps(payload) + "\n").encode())
            child.stdin.flush()
            return _read_reply(child, wall_s)
        except TimeoutError:
            _kill(child)
            _child = None
            raise RuntimeError(
                f"the call exceeded its {wall_s:.0f}s wall and the kernel was "
                "stopped — SESSION STATE WAS LOST; data_load again and retry "
                "with smaller steps"
            ) from None
        except (BrokenPipeError, RuntimeError) as exc:
            _kill(child)
            _child = None
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(
                "the kernel died mid-call — session state was lost; data_load again"
            ) from None


def running() -> bool:
    return _child is not None and _child.poll() is None


def reset() -> None:
    """Kill the kernel; the next call starts empty."""
    global _child
    with _lock:
        if _child is not None:
            _kill(_child)
            _child = None
