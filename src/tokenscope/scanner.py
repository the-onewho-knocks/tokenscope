"""Walk a repository, count tokens per file, and roll them up per directory."""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from .tokenizers import TokenCounter, get_tokenizer

DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode",
    "dist", "build", ".next", ".nuxt", "target", "coverage", ".gradle", ".eggs",
}
DEFAULT_IGNORE_FILES = [
    "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "*.min.js", "*.min.css", "*.map", "*.egg-info",
]
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz", ".pdf", ".zip", ".gz",
    ".tar", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war", ".class", ".so", ".dll", ".dylib",
    ".exe", ".bin", ".o", ".a", ".pyc", ".pyo", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".mov", ".avi", ".wav", ".ogg", ".sqlite", ".db", ".parquet", ".npy",
    ".pt", ".onnx", ".safetensors",
}


@dataclass
class FileStat:
    path: str            # posix path relative to scan root
    tokens: int
    chars: int
    lines: int
    ext: str


@dataclass
class DirStat:
    path: str            # "." for the root
    own_tokens: int = 0  # files directly inside this directory
    tokens: int = 0      # recursive total (own + all descendants)
    files: int = 0       # recursive file count
    own_files: int = 0


@dataclass
class ScanResult:
    root: str
    tokenizer: str
    files: list[FileStat] = field(default_factory=list)
    dirs: dict[str, DirStat] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=lambda: {
        "binary": 0, "too_large": 0, "ignored": 0, "unreadable": 0})

    @property
    def total_tokens(self) -> int:
        return sum(f.tokens for f in self.files)

    def by_extension(self) -> dict[str, tuple[int, int]]:
        """ext -> (tokens, files)"""
        out: dict[str, list[int]] = {}
        for f in self.files:
            e = out.setdefault(f.ext or "(none)", [0, 0])
            e[0] += f.tokens
            e[1] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}


def _is_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def _load_gitignore(root: Path) -> list[str]:
    gi = root / ".gitignore"
    if not gi.is_file():
        return []
    patterns = []
    for line in gi.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("!"):
            patterns.append(line)
    return patterns


def _matches(rel_posix: str, name: str, patterns: Iterable[str], is_dir: bool) -> bool:
    """Simplified gitignore-style matching (no negation, no '**' semantics beyond fnmatch)."""
    for pat in patterns:
        p = pat
        dir_only = p.endswith("/")
        p = p.rstrip("/")
        if dir_only and not is_dir:
            continue
        anchored = p.startswith("/")
        p = p.lstrip("/")
        if anchored or "/" in p:
            if fnmatch.fnmatch(rel_posix, p):
                return True
        elif fnmatch.fnmatch(name, p):
            return True
    return False


def scan_repo(
    root: str | os.PathLike,
    *,
    tokenizer: str = "auto",
    encoding: str = "cl100k_base",
    counter: Optional[TokenCounter] = None,
    extra_ignores: Iterable[str] = (),
    include_exts: Optional[Iterable[str]] = None,
    max_file_bytes: int = 1_000_000,
    use_gitignore: bool = True,
    follow_symlinks: bool = False,
    on_file: Optional[Callable[[FileStat], None]] = None,
) -> ScanResult:
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(str(root_path))

    if counter is None:
        label, counter = get_tokenizer(tokenizer, encoding)
    else:
        label = "custom"

    patterns = list(DEFAULT_IGNORE_FILES) + list(extra_ignores)
    if use_gitignore:
        patterns += _load_gitignore(root_path)
    exts = {e if e.startswith(".") else f".{e}" for e in include_exts} if include_exts else None

    result = ScanResult(root=str(root_path), tokenizer=label)
    result.dirs["."] = DirStat(path=".")

    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=follow_symlinks):
        rel_dir = Path(dirpath).relative_to(root_path).as_posix()
        rel_dir = "." if rel_dir == "." else rel_dir

        kept = []
        for d in sorted(dirnames):
            rel = d if rel_dir == "." else f"{rel_dir}/{d}"
            if d in DEFAULT_IGNORE_DIRS or d.endswith(".egg-info") or _matches(rel, d, patterns, True):
                result.skipped["ignored"] += 1
                continue
            kept.append(d)
        dirnames[:] = kept

        for fname in sorted(filenames):
            rel = fname if rel_dir == "." else f"{rel_dir}/{fname}"
            full = Path(dirpath) / fname
            ext = full.suffix.lower()

            if _matches(rel, fname, patterns, False):
                result.skipped["ignored"] += 1
                continue
            if exts is not None and ext not in exts:
                continue
            if ext in BINARY_EXTS:
                result.skipped["binary"] += 1
                continue
            try:
                if full.is_symlink() and not follow_symlinks:
                    continue
                size = full.stat().st_size
                if size > max_file_bytes:
                    result.skipped["too_large"] += 1
                    continue
                data = full.read_bytes()
            except OSError:
                result.skipped["unreadable"] += 1
                continue
            if _is_binary(data[:8192]):
                result.skipped["binary"] += 1
                continue

            text = data.decode("utf-8", errors="replace")
            fs = FileStat(
                path=rel, tokens=counter(text), chars=len(text),
                lines=text.count("\n") + (1 if text and not text.endswith("\n") else 0),
                ext=ext,
            )
            result.files.append(fs)
            if on_file:
                on_file(fs)

            # Roll up to this directory and every ancestor.
            own = result.dirs.setdefault(rel_dir, DirStat(path=rel_dir))
            own.own_tokens += fs.tokens
            own.own_files += 1
            parts = [] if rel_dir == "." else rel_dir.split("/")
            ancestors = ["."] + ["/".join(parts[: i + 1]) for i in range(len(parts))]
            for a in ancestors:
                ds = result.dirs.setdefault(a, DirStat(path=a))
                ds.tokens += fs.tokens
                ds.files += 1

    return result
