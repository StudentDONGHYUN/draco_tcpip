from __future__ import annotations

from pathlib import Path
from typing import Iterable

DEFAULT_PLAN_PATH = Path("docs/tests/perf/latency_benchmark_plan.md")


def _parse_front_matter(lines: Iterable[str]) -> dict[str, object]:
    data: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(0, data)]
    for raw in lines:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key_value = raw.strip().split(":", 1)
        key = key_value[0]
        value = key_value[1].strip() if len(key_value) > 1 else ""
        while stack and indent < stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value:
            try:
                parent[key] = float(value) if value.replace(".", "", 1).isdigit() else value
            except ValueError:
                parent[key] = value
        else:
            node: dict[str, object] = {}
            parent[key] = node
            stack.append((indent + 2, node))
    return data


def load_latency_threshold(plan_path: Path | str = DEFAULT_PLAN_PATH) -> float:
    """Load the p95 latency threshold from docs/tests/perf/latency_benchmark_plan.md."""

    path = Path(plan_path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    threshold = 250.0
    if lines and lines[0].strip() == "---":
        try:
            end = lines[1:].index("---") + 1
        except ValueError:
            end = len(lines)
        front_matter = _parse_front_matter(lines[1:end])
        threshold_ms = front_matter.get("threshold_ms")
        if isinstance(threshold_ms, dict):
            p95 = threshold_ms.get("p95")
            if isinstance(p95, (int, float)):
                threshold = float(p95)
    return threshold


__all__ = ["load_latency_threshold"]
