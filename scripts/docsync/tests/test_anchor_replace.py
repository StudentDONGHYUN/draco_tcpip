from pathlib import Path

from scripts.docsync.utils.fileio import AnchorUpdate, apply_updates


def test_replace_anchor(tmp_path: Path) -> None:
    target = tmp_path / "sample.md"
    target.write_text("Intro\n<!-- AUTODOC:TEST:BEGIN -->\nold\n<!-- AUTODOC:TEST:END -->\n", encoding="utf-8")
    apply_updates(target, [AnchorUpdate(name="AUTODOC:TEST", content="new content")])
    expected = "Intro\n<!-- AUTODOC:TEST:BEGIN -->\nnew content\n<!-- AUTODOC:TEST:END -->\n"
    assert target.read_text(encoding="utf-8") == expected
