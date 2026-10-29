import pytest

from revenant.surgeon.edits import Edit, EditError, Fix, apply_edit, apply_fix, parse_blocks, relax_trailing_newline


def test_exact_single_match(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    diff = apply_edit(tmp_path, Edit("a.py", "y = 2\n", "y = 3\n"))
    assert (tmp_path / "a.py").read_text() == "x = 1\ny = 3\n"
    assert "-y = 2" in diff and "+y = 3" in diff


def test_ambiguous_or_missing_text_is_refused(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n")
    with pytest.raises(EditError, match="found 2x"):
        apply_edit(tmp_path, Edit("a.py", "x = 1\n", "x = 2\n"))
    with pytest.raises(EditError, match="found 0x"):
        apply_edit(tmp_path, Edit("a.py", "nope", "x"))
    assert apply_edit(tmp_path, Edit("a.py", "x = 1\n", "x = 2\n", count=2))
    assert (tmp_path / "a.py").read_text() == "x = 2\nx = 2\n"


def test_cannot_escape_the_tree(tmp_path):
    (tmp_path / "t").mkdir()
    with pytest.raises(EditError, match="outside"):
        apply_edit(tmp_path / "t", Edit("../evil.py", "", "boom"))


def test_fix_is_all_or_nothing(tmp_path):
    (tmp_path / "a.py").write_text("a\n")
    (tmp_path / "b.py").write_text("b\n")
    fix = Fix("f", "f", [Edit("a.py", "a\n", "A\n"), Edit("new.py", "", "n\n"), Edit("b.py", "zzz", "B")], "why")
    with pytest.raises(EditError):
        apply_fix(tmp_path, fix)
    assert (tmp_path / "a.py").read_text() == "a\n" and not (tmp_path / "new.py").exists()


def test_parse_blocks_from_model_output():
    reply = """Here you go:
```python
FILE: pkg/core.py
<<<<<<< SEARCH
    loop = asyncio.get_event_loop()
=======
    loop = asyncio.new_event_loop()
>>>>>>> REPLACE
```
FILE: empty.py
<<<<<<< SEARCH
=======
print('blind create')
>>>>>>> REPLACE
"""
    edits = parse_blocks(reply)
    assert len(edits) == 1  # blind file creation from a model is ignored
    assert edits[0].path == "pkg/core.py"
    assert edits[0].search == "    loop = asyncio.get_event_loop()\n"
    assert edits[0].replace == "    loop = asyncio.new_event_loop()\n"


def test_relax_trailing_newline(tmp_path):
    (tmp_path / "a.py").write_text("last line")
    e = relax_trailing_newline(tmp_path, Edit("a.py", "last line\n", "new line\n"))
    assert e.search == "last line" and e.replace == "new line"


def test_fix_touching_outside_the_tree_leaves_outside_files_alone(tmp_path):
    tree = tmp_path / "t"
    tree.mkdir()
    (tree / "a.py").write_text("a\n")
    outside = tmp_path / "secret.txt"
    outside.write_text("keep\n")
    outside.chmod(0o400)   # rewriting it, even with the same text, would fail
    fix = Fix("f", "f", [Edit("a.py", "a\n", "A\n"), Edit("../secret.txt", "keep\n", "gone\n")], "why")
    try:
        with pytest.raises(EditError, match="outside"):
            apply_fix(tree, fix)
    finally:
        outside.chmod(0o600)
    assert (tree / "a.py").read_text() == "a\n" and outside.read_text() == "keep\n"


def test_relax_trailing_newline_ignores_paths_outside_the_tree(tmp_path):
    (tmp_path / "t").mkdir()
    e = Edit("../x.py", "y\n", "z\n")
    assert relax_trailing_newline(tmp_path / "t", e) is e
