"""Markdown rendering helpers for the docs sync pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(slots=True)
class TableColumn:
    header: str
    alignment: str = "-"


def format_table(headers: Sequence[TableColumn], rows: Iterable[Sequence[str]]) -> str:
    header_titles = [col.header for col in headers]
    alignments = [col.alignment for col in headers]
    lines = ["| " + " | ".join(header_titles) + " |"]
    lines.append("| " + " | ".join(alignment if alignment else "-" for alignment in alignments) + " |")
    for row in rows:
        cells = [cell.replace("\n", "<br>") if cell else "" for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def format_bullet_list(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def format_code_block(text: str, *, language: str = "") -> str:
    fence = f"```{language}".rstrip()
    return f"{fence}\n{text}\n```"
