"""Shared file discipline — the charter, in code.

**Compute and plot; outputs land only in derived or artifact
directories** (the root-ext-cad charter shape): every write tool
refuses an output path that collides with an input, and everything
returned as text is budgeted with truncation marked.
"""

from __future__ import annotations

from pathlib import Path

MAX_TEXT_CHARS = 50_000
MAX_SOURCE_BYTES = 500_000_000

DATA_SUFFIXES = (".csv", ".tsv", ".parquet", ".xlsx", ".json")
SPEC_SUFFIXES = (".vl.json",)


def checked_path(path: str, suffixes: tuple[str, ...]) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise FileNotFoundError(f"no file at {resolved}")
    name = resolved.name.lower()
    if not any(name.endswith(suffix) for suffix in suffixes):
        raise ValueError(f"expected one of {suffixes}, got {resolved.name!r}")
    if resolved.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("file exceeds the 500 MB ceiling")
    return resolved


def refuse_collision(out_path: Path, inputs: tuple[Path, ...]) -> None:
    """The charter, at the write site: outputs never land on an input."""
    resolved_out = out_path.expanduser().resolve()
    for source in inputs:
        if resolved_out == source.expanduser().resolve():
            raise ValueError(
                f"refusing to overwrite input {source} — outputs go to a "
                "distinct path (charter: compute and plot, never mutate sources)"
            )


def budget_text(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_TEXT_CHARS:
        return text, False
    return text[:MAX_TEXT_CHARS] + "\n… (truncated)", True


def safe_stem(name: str) -> str:
    """A chart name becomes one safe path segment."""
    cleaned = "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in name.strip()
    ).strip("_")
    if not cleaned:
        raise ValueError(f"chart name {name!r} has no usable characters")
    return cleaned[:80]
