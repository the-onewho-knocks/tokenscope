"""Token counting backends.

* ``tiktoken`` - exact BPE counts for OpenAI-style encodings (needs ``pip install tiktoken``).
  Note: Claude uses its own tokenizer, so tiktoken is a close *proxy*, not exact.
* ``approx``   - dependency-free heuristic (no network, no install). Typically within
  ~10-20% of real BPE counts on source code and English text.
"""
from __future__ import annotations

import re
from typing import Callable

TokenCounter = Callable[[str], int]

# Words, numbers, single punctuation/symbol characters. Long words split into ~4-char pieces,
# which mimics how BPE breaks up identifiers and rare words.
_PIECE_RE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")


def approx_count(text: str) -> int:
    if not text:
        return 0
    total = 0
    for m in _PIECE_RE.finditer(text):
        piece = m.group(0)
        if piece[0].isalpha():
            total += max(1, (len(piece) + 3) // 4)
        elif piece[0].isdigit():
            total += max(1, (len(piece) + 2) // 3)
        else:
            total += 1
    return total


def chars4_count(text: str) -> int:
    """The classic 'one token is about four characters' rule of thumb."""
    return (len(text) + 3) // 4 if text else 0


def get_tokenizer(name: str = "auto", encoding: str = "cl100k_base") -> tuple[str, TokenCounter]:
    """Return ``(label, counter)``.

    name: ``auto`` (tiktoken if installed, else approx), ``tiktoken``, ``approx``, ``chars4``.
    """
    name = name.lower()
    if name in ("auto", "tiktoken"):
        try:
            import tiktoken  # type: ignore

            enc = tiktoken.get_encoding(encoding)

            def count(text: str) -> int:
                # disallowed_special=() so text like "<|endoftext|>" in repos is counted, not rejected.
                return len(enc.encode(text, disallowed_special=()))

            return f"tiktoken:{encoding}", count
        except Exception as exc:  # ImportError, or encoding data could not be fetched offline
            if name == "tiktoken":
                raise RuntimeError(
                    f"tiktoken unavailable ({exc}). Install with `pip install tokenscope[accurate]` "
                    "or use --tokenizer approx."
                ) from exc
            return "approx", approx_count
    if name == "approx":
        return "approx", approx_count
    if name == "chars4":
        return "chars4", chars4_count
    raise ValueError(f"unknown tokenizer: {name!r}")
