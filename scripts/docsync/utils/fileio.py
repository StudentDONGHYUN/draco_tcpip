"""File IO helpers for docs sync tooling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

ANCHOR_TEMPLATE = "<!-- {name}:BEGIN -->"
ANCHOR_END_TEMPLATE = "<!-- {name}:END -->"


@dataclass(slots=True)
class AnchorUpdate:
    name: str
    content: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ensure_anchor_block(text: str, name: str, *, heading: str | None = None) -> str:
    begin = ANCHOR_TEMPLATE.format(name=name)
    end = ANCHOR_END_TEMPLATE.format(name=name)
    if begin in text and end in text:
        return text
    parts: list[str] = []
    if text:
        parts.append(text.rstrip())
    if heading:
        parts.append(heading)
    parts.append(begin)
    parts.append(end)
    return "\n\n".join(parts) + "\n"


def replace_anchor(text: str, update: AnchorUpdate) -> str:
    begin = re.escape(ANCHOR_TEMPLATE.format(name=update.name))
    end = re.escape(ANCHOR_END_TEMPLATE.format(name=update.name))
    pattern = re.compile(f"{begin}(.*?){end}", re.DOTALL)
    replacement = (
        ANCHOR_TEMPLATE.format(name=update.name)
        + "\n"
        + update.content.strip()
        + "\n"
        + ANCHOR_END_TEMPLATE.format(name=update.name)
    )
    if not pattern.search(text):
        text = ensure_anchor_block(text, update.name)
    return pattern.sub(replacement, text, count=1)


def apply_updates(path: Path, updates: list[AnchorUpdate]) -> None:
    text = read_text(path)
    for update in updates:
        text = replace_anchor(text, update)
    write_text(path, text)
