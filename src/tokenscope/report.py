"""Render a ScanResult as a table, JSON or CSV."""
from __future__ import annotations

import csv
import io
import json
from typing import Optional

from .scanner import ScanResult

CONTEXT_WINDOWS = {
    "8k": 8_000, "32k": 32_000, "128k": 128_000, "200k": 200_000, "1M": 1_000_000,
}


def _bar(frac: float, width: int = 20) -> str:
    n = int(round(frac * width))
    return "█" * n + "░" * (width - n)


def _fmt(n: int) -> str:
    return f"{n:,}"


def _dir_depth(path: str) -> int:
    return 0 if path == "." else path.count("/") + 1


def dir_rows(res: ScanResult, depth: Optional[int] = None, min_tokens: int = 0):
    total = res.total_tokens or 1
    rows = []
    for d in res.dirs.values():
        if depth is not None and _dir_depth(d.path) > depth:
            continue
        if d.tokens < min_tokens:
            continue
        rows.append((d, d.tokens / total))
    # Keep tree order (alphabetical by path) so children sit under parents.
    rows.sort(key=lambda r: (r[0].path != ".", r[0].path))
    return rows


def render_table(
    res: ScanResult, *, depth: Optional[int] = 2, top_files: int = 15,
    min_tokens: int = 0, price_per_mtok: Optional[float] = None,
) -> str:
    out = io.StringIO()
    w = out.write
    total = res.total_tokens
    w(f"Repository : {res.root}\n")
    w(f"Tokenizer  : {res.tokenizer}\n")
    w(f"Files      : {_fmt(len(res.files))}   Total tokens: {_fmt(total)}\n")
    skipped = ", ".join(f"{k}={v}" for k, v in res.skipped.items() if v)
    if skipped:
        w(f"Skipped    : {skipped}\n")
    w("\n")

    w("Context-window fit (whole repo in one prompt)\n")
    for label, size in CONTEXT_WINDOWS.items():
        pct = total / size * 100
        mark = "fits" if total <= size else "too big"
        w(f"  {label:>4}: {pct:8.1f}%  {mark}\n")
    if price_per_mtok is not None:
        w(f"\nEstimated input cost per full-repo prompt: ${total / 1e6 * price_per_mtok:,.4f} "
          f"(at ${price_per_mtok}/1M tokens)\n")

    w("\nTokens per folder (recursive)\n")
    rows = dir_rows(res, depth, min_tokens)
    name_w = max([len(r[0].path) for r in rows] + [6])
    w(f"  {'folder':<{name_w}}  {'tokens':>12}  {'share':>6}  {'files':>6}  {'own':>10}\n")
    for d, frac in rows:
        w(f"  {d.path:<{name_w}}  {_fmt(d.tokens):>12}  {frac * 100:5.1f}%  {d.files:>6}  "
          f"{_fmt(d.own_tokens):>10}  {_bar(frac)}\n")

    w(f"\nTop {top_files} files by tokens\n")
    for f in sorted(res.files, key=lambda f: f.tokens, reverse=True)[:top_files]:
        w(f"  {_fmt(f.tokens):>10}  {f.tokens / (total or 1) * 100:5.1f}%  {f.path}\n")

    w("\nBy file type\n")
    for ext, (tok, n) in sorted(res.by_extension().items(), key=lambda kv: -kv[1][0])[:12]:
        w(f"  {ext:<10} {_fmt(tok):>12}  {tok / (total or 1) * 100:5.1f}%  {n:>5} files\n")
    return out.getvalue()


def render_json(res: ScanResult) -> str:
    return json.dumps({
        "root": res.root,
        "tokenizer": res.tokenizer,
        "total_tokens": res.total_tokens,
        "skipped": res.skipped,
        "directories": [
            {"path": d.path, "tokens": d.tokens, "own_tokens": d.own_tokens,
             "files": d.files, "own_files": d.own_files}
            for d in sorted(res.dirs.values(), key=lambda d: d.path)
        ],
        "files": [
            {"path": f.path, "tokens": f.tokens, "chars": f.chars, "lines": f.lines, "ext": f.ext}
            for f in sorted(res.files, key=lambda f: f.path)
        ],
    }, indent=2)


def render_csv(res: ScanResult, kind: str = "files") -> str:
    buf = io.StringIO()
    wr = csv.writer(buf)
    if kind == "dirs":
        wr.writerow(["path", "tokens", "own_tokens", "files", "own_files"])
        for d in sorted(res.dirs.values(), key=lambda d: d.path):
            wr.writerow([d.path, d.tokens, d.own_tokens, d.files, d.own_files])
    else:
        wr.writerow(["path", "tokens", "chars", "lines", "ext"])
        for f in sorted(res.files, key=lambda f: -f.tokens):
            wr.writerow([f.path, f.tokens, f.chars, f.lines, f.ext])
    return buf.getvalue()
