"""Configuration discovery for docs sync."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

from scripts.docsync.renderers.markdown import TableColumn, format_table


@dataclass(slots=True)
class ConfigEntry:
    source: Path
    key: str
    value: str
    context: str


@dataclass(slots=True)
class EnvVarUsage:
    name: str
    default: str
    location: str
    note: str


class _EnvVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.usages: list[EnvVarUsage] = []
        self._filename: Path | None = None

    def load(self, path: Path) -> None:
        self._filename = path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        self.visit(tree)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: D401 - AST hook
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get":
            owner = func.value
            if _is_os_environ(owner):
                name = _literal(node.args[0]) if node.args else ""
                default = _literal(node.args[1]) if len(node.args) > 1 else _literal(node.keywords[0].value) if node.keywords else ""
                location = f"{self._relative_path()}:{node.lineno}"
                self.usages.append(
                    EnvVarUsage(
                        name=str(name),
                        default=str(default) if default not in (None, "None") else "",
                        location=location,
                        note="dict.get",
                    )
                )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:  # noqa: D401 - AST hook
        if _is_os_environ(node.value):
            name = _literal(node.slice)
            location = f"{self._relative_path()}:{node.lineno}"
            self.usages.append(
                EnvVarUsage(
                    name=str(name),
                    default="",
                    location=location,
                    note="direct access",
                )
            )
        self.generic_visit(node)

    def _relative_path(self) -> Path:
        assert self._filename is not None
        repo_root = _find_repo_root(self._filename)
        try:
            return self._filename.relative_to(repo_root)
        except ValueError:
            return self._filename


def _is_os_environ(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        return _literal(node.value) == "os"
    return False


def _literal(node: ast.AST | None) -> Any:
    if node is None:
        return ""
    try:
        return ast.literal_eval(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = _literal(node.value) if hasattr(node, "value") else ""
            return f"{base}.{node.attr}" if base else node.attr
        if hasattr(ast, "unparse"):
            return ast.unparse(node)
        return "?"


def _find_repo_root(path: Path) -> Path:
    current = path
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return path


def _flatten_mapping(prefix: str, node: Any, *, source: Path, entries: List[ConfigEntry]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            new_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_mapping(new_prefix, value, source=source, entries=entries)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            new_prefix = f"{prefix}[{idx}]"
            _flatten_mapping(new_prefix, value, source=source, entries=entries)
    else:
        entries.append(
            ConfigEntry(
                source=source,
                key=prefix,
                value=json.dumps(node, ensure_ascii=False) if isinstance(node, (dict, list)) else str(node),
                context="profile",
            )
        )


def collect_config_entries(repo_root: Path) -> list[ConfigEntry]:
    configs_dir = repo_root / "configs"
    entries: list[ConfigEntry] = []
    for path in sorted(configs_dir.glob("**/*")):
        if path.suffix.lower() in {".yaml", ".yml"}:
            data = _load_yaml(path.read_text(encoding="utf-8"))
            _flatten_mapping("", data, source=path.relative_to(repo_root), entries=entries)
        elif path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            _flatten_mapping("", data, source=path.relative_to(repo_root), entries=entries)
    return entries


def collect_env_vars(repo_root: Path) -> list[EnvVarUsage]:
    visitor = _EnvVisitor()
    sources = list((repo_root / "ros2_ws" / "src").glob("**/*.py")) + list((repo_root / "scripts").glob("**/*.py"))
    usages: list[EnvVarUsage] = []
    for source in sources:
        try:
            visitor.load(source)
        except SyntaxError:
            continue
        usages.extend(visitor.usages)
        visitor.usages = []
    return usages


def render_config_table(entries: list[ConfigEntry]) -> str:
    headers = [
        TableColumn("Key"),
        TableColumn("Default/Value"),
        TableColumn("Source"),
        TableColumn("Context"),
    ]
    rows = [
        [
            entry.key,
            entry.value,
            str(entry.source),
            entry.context,
        ]
        for entry in sorted(entries, key=lambda item: (item.source, item.key))
    ]
    return format_table(headers, rows)


def _load_yaml(text: str) -> Any:
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    if yaml is not None:
        data = yaml.safe_load(text)  # type: ignore[no-any-unimported]
        return data or {}
    return _simple_yaml(text)


def _simple_yaml(text: str) -> Any:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(0, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if line.startswith("-"):
            container = stack[-1][1]
            if isinstance(container, list):
                container.append(_parse_scalar(line[1:].strip()))
            else:
                # create synthetic list on first encounter
                new_list: list[Any] = []
                if isinstance(container, dict):
                    synthetic_key = "_list"
                    existing = container.get(synthetic_key)
                    if not isinstance(existing, list):
                        container[synthetic_key] = new_list
                        container = new_list
                    else:
                        container = existing
                if isinstance(container, list):
                    container.append(_parse_scalar(line[1:].strip()))
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        while stack and indent < stack[-1][0]:
            stack.pop()
        container = stack[-1][1]
        if value == "":
            node: dict[str, Any] = {}
            if isinstance(container, dict):
                container[key] = node
            elif isinstance(container, list):
                container.append({key: node})
            stack.append((indent + 2, node))
        else:
            parsed = _parse_scalar(value)
            if isinstance(container, dict):
                container[key] = parsed
            elif isinstance(container, list):
                container.append({key: parsed})
    return root


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "~"}:
        return None
    if value.startswith("\"") and value.endswith("\""):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def render_env_table(usages: list[EnvVarUsage]) -> str:
    headers = [
        TableColumn("Environment Variable"),
        TableColumn("Default"),
        TableColumn("Source"),
        TableColumn("Notes"),
    ]
    grouped: dict[str, dict[str, Any]] = {}
    for usage in usages:
        bucket = grouped.setdefault(
            usage.name,
            {"defaults": set(), "sources": [], "notes": set()},
        )
        if usage.default:
            bucket["defaults"].add(usage.default)
        source_entry = usage.location
        if usage.note and usage.note not in {"", "dict.get"}:
            source_entry = f"{source_entry} ({usage.note})"
        bucket["sources"].append(source_entry)
        if usage.note:
            bucket["notes"].add(usage.note)
    rows = []
    for name in sorted(grouped):
        bucket = grouped[name]
        defaults = ", ".join(sorted(bucket["defaults"]))
        sources = "<br>".join(sorted(bucket["sources"]))
        notes = ", ".join(sorted(bucket["notes"]))
        rows.append([name, defaults, sources, notes])
    return format_table(headers, rows)
