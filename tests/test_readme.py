"""Keeps the README honest: its Python example must actually run."""
import re
from pathlib import Path

README = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")


def test_readme_python_examples_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    blocks = re.findall(r"```python\n(.*?)```", README, re.S)
    assert blocks
    for block in blocks:
        exec(compile(block, "README", "exec"), {})
