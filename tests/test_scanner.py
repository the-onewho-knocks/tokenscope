import json

from tokenscope.cli import main
from tokenscope.scanner import scan_repo
from tokenscope.tokenizers import approx_count, get_tokenizer


def make_repo(tmp_path):
    (tmp_path / "pkg" / "core").mkdir(parents=True)
    (tmp_path / "pkg" / "utils").mkdir()
    (tmp_path / "node_modules" / "junk").mkdir(parents=True)
    (tmp_path / "README.md").write_text("hello world\n")
    (tmp_path / "pkg" / "a.py").write_text("def f():\n    return 1\n")
    (tmp_path / "pkg" / "core" / "b.py").write_text("x = 1\n" * 50)
    (tmp_path / "pkg" / "utils" / "c.py").write_text("y = 2\n" * 10)
    (tmp_path / "node_modules" / "junk" / "big.js").write_text("var a;\n" * 1000)
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    (tmp_path / "blob.dat").write_bytes(b"abc\x00def")
    return tmp_path


def count(text):
    return approx_count(text)


def test_totals_and_rollup(tmp_path):
    root = make_repo(tmp_path)
    res = scan_repo(root, tokenizer="approx")
    paths = {f.path for f in res.files}
    assert paths == {"README.md", "pkg/a.py", "pkg/core/b.py", "pkg/utils/c.py"}

    # root total == sum of files, and folder totals are recursive
    assert res.dirs["."].tokens == res.total_tokens
    assert res.dirs["pkg"].tokens == sum(f.tokens for f in res.files if f.path.startswith("pkg/"))
    assert res.dirs["pkg"].own_tokens == count("def f():\n    return 1\n")
    assert res.dirs["pkg/core"].tokens == count("x = 1\n" * 50)
    assert res.dirs["pkg"].files == 3


def test_skips_ignored_and_binary(tmp_path):
    res = scan_repo(make_repo(tmp_path), tokenizer="approx")
    assert not any("node_modules" in f.path for f in res.files)
    assert res.skipped["binary"] == 2  # .png by extension, .dat by NUL byte


def test_gitignore_and_extra_ignore(tmp_path):
    root = make_repo(tmp_path)
    (root / ".gitignore").write_text("pkg/utils/\n")
    res = scan_repo(root, tokenizer="approx", extra_ignores=["*.md"])
    paths = {f.path for f in res.files}
    assert "pkg/utils/c.py" not in paths
    assert "README.md" not in paths
    assert "pkg/a.py" in paths


def test_include_exts_and_size_limit(tmp_path):
    root = make_repo(tmp_path)
    res = scan_repo(root, tokenizer="approx", include_exts=["py"])
    assert all(f.ext == ".py" for f in res.files)
    res = scan_repo(root, tokenizer="approx", max_file_bytes=20)
    assert res.skipped["too_large"] >= 1


def test_tokenizers():
    assert approx_count("") == 0
    assert approx_count("hello world") == 4  # hello->2, world->2 (ceil(5/4))
    label, fn = get_tokenizer("chars4")
    assert label == "chars4" and fn("abcdefgh") == 2
    label, _ = get_tokenizer("auto")
    assert label == "approx" or label.startswith("tiktoken")


def test_cli_json_and_table(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert main([str(root), "-t", "approx", "-f", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_tokens"] == sum(f["tokens"] for f in data["files"])

    assert main([str(root), "-t", "approx", "--price-per-mtok", "3"]) == 0
    out = capsys.readouterr().out
    assert "Tokens per folder" in out and "pkg/core" in out

    assert main([str(tmp_path / "missing")]) == 2
