from __future__ import annotations

import argparse
import sys

from . import __version__
from .report import render_csv, render_json, render_table
from .scanner import scan_repo


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tokenscope",
        description="Count LLM tokens in a repository, per file and per folder/module.",
    )
    p.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    p.add_argument("-t", "--tokenizer", default="auto", choices=["auto", "tiktoken", "approx", "chars4"],
                   help="auto = tiktoken if installed, else approx")
    p.add_argument("-e", "--encoding", default="cl100k_base",
                   help="tiktoken encoding, e.g. cl100k_base or o200k_base")
    p.add_argument("-d", "--depth", type=int, default=2,
                   help="folder depth to show in the table (default 2; use -1 for all)")
    p.add_argument("-n", "--top", type=int, default=15, help="number of largest files to list")
    p.add_argument("--min-tokens", type=int, default=0, help="hide folders below this many tokens")
    p.add_argument("-f", "--format", default="table", choices=["table", "json", "csv", "csv-dirs"])
    p.add_argument("-o", "--output", help="write report to this file instead of stdout")
    p.add_argument("-i", "--ignore", action="append", default=[], metavar="GLOB",
                   help="extra ignore pattern (repeatable), e.g. -i 'tests/*' -i '*.svg'")
    p.add_argument("--ext", action="append", default=None, metavar="EXT",
                   help="only count these extensions (repeatable), e.g. --ext py --ext md")
    p.add_argument("--max-file-kb", type=int, default=1000, help="skip files bigger than this")
    p.add_argument("--no-gitignore", action="store_true", help="do not read .gitignore")
    p.add_argument("--price-per-mtok", type=float, default=None,
                   help="input price in USD per 1M tokens, to estimate cost of sending the repo")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        res = scan_repo(
            args.path, tokenizer=args.tokenizer, encoding=args.encoding,
            extra_ignores=args.ignore, include_exts=args.ext,
            max_file_bytes=args.max_file_kb * 1024, use_gitignore=not args.no_gitignore,
        )
    except (NotADirectoryError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    depth = None if args.depth < 0 else args.depth
    if args.format == "json":
        text = render_json(res)
    elif args.format == "csv":
        text = render_csv(res, "files")
    elif args.format == "csv-dirs":
        text = render_csv(res, "dirs")
    else:
        text = render_table(res, depth=depth, top_files=args.top, min_tokens=args.min_tokens,
                            price_per_mtok=args.price_per_mtok)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
