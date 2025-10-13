"""Extract CLI flag metadata from console script entrypoints."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from scripts.docsync.renderers.markdown import TableColumn, format_table


@dataclass(slots=True)
class CLIArgument:
    command: str
    flags: str
    arg_type: str
    default: str
    required: str
    description: str
    source: str


@dataclass(slots=True)
class ConsoleScript:
    command: str
    module: str
    qualname: str
    path: Path
    package_root: Path


class _CLIVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.parser_names: set[str] = set()
        self.group_names: set[str] = set()
        self.arguments: list[tuple[ast.Call, Sequence[str]]] = []

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: D401 - AST hook
        call = node.value
        if isinstance(call, ast.Call) and _is_argument_parser_ctor(call):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.parser_names.add(target.id)
        elif isinstance(call, ast.Call) and _is_group_ctor(call):
            name = _maybe_name(call.func)
            if name and name in self.parser_names:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.group_names.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: D401 - AST hook
        self._capture_argument(node)
        self.generic_visit(node)

    def _capture_argument(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "add_argument":
            owner = _maybe_name(func.value)
            if owner in self.parser_names or owner in self.group_names:
                options = _stringify_options(node.args)
                self.arguments.append((node, options))
        elif isinstance(func, ast.Attribute) and func.attr in {
            "add_argument_group",
            "add_mutually_exclusive_group",
        }:
            owner = _maybe_name(func.value)
            if owner in self.parser_names:
                # Track derived group variable names when assigned
                pass


def _maybe_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _stringify_options(args: Iterable[ast.expr]) -> List[str]:
    options: list[str] = []
    for arg in args:
        value = _literal(arg)
        if isinstance(value, str):
            options.append(value)
    return options


def _literal(node: ast.AST) -> object:
    try:
        return ast.literal_eval(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{_literal(node.value)}.{node.attr}" if hasattr(node, "value") else node.attr
        return getattr(ast, "unparse", lambda x: "?")(node)


def _is_argument_parser_ctor(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr == "ArgumentParser"
    if isinstance(func, ast.Name):
        return func.id == "ArgumentParser"
    return False


def _is_group_ctor(call: ast.Call) -> bool:
    func = call.func
    return isinstance(func, ast.Attribute) and func.attr in {
        "add_argument_group",
        "add_mutually_exclusive_group",
    }


def parse_console_scripts(setup_path: Path) -> list[ConsoleScript]:
    tree = ast.parse(setup_path.read_text(encoding="utf-8"), filename=str(setup_path))
    scripts: list[ConsoleScript] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(getattr(node.func, "id", None), "lower", lambda: "")() == "setup":
            for kw in node.keywords:
                if kw.arg == "entry_points":
                    mapping = ast.literal_eval(kw.value)
                    for raw in mapping.get("console_scripts", []):
                        command, target = [item.strip() for item in raw.split("=", 1)]
                        module, qualname = target.split(":", 1)
                        module_path = module.replace(".", "/") + ".py"
                        scripts.append(
                            ConsoleScript(
                                command=command,
                                module=module,
                                qualname=qualname,
                                path=setup_path.parent / module_path,
                                package_root=setup_path.parent,
                            )
                        )
    return scripts


def _resolve_module_path(script: ConsoleScript) -> Path:
    if script.path.exists():
        return script.path
    module_parts = script.module.split(".")
    root = script.path.parent
    for depth in range(len(module_parts), 0, -1):
        candidate = root / "/".join(module_parts[:depth])
        file_path = candidate.with_suffix(".py")
        if file_path.exists():
            return file_path
    return script.path


def _follow_proxy(script: ConsoleScript, *, search_root: Path, seen: set[str]) -> Path:
    path = _resolve_module_path(script)
    if not path.exists():
        return path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _CLIVisitor()
    visitor.visit(tree)
    if visitor.arguments:
        return path
    # Attempt to resolve proxy imports exposing ``main``
    for node in tree.body:
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            for alias in node.names:
                if alias.asname == script.qualname or alias.name == script.qualname:
                    target_module = node.module if isinstance(node, ast.ImportFrom) else alias.name
                    if not target_module:
                        continue
                    if target_module in seen:
                        continue
                    seen.add(target_module)
                    candidate = script.package_root / (target_module.replace(".", "/") + ".py")
                    if candidate.exists():
                        return candidate
                    if node.level and isinstance(node, ast.ImportFrom):
                        rel_base = path.parent
                        for _ in range(node.level):
                            rel_base = rel_base.parent
                        rel_candidate = rel_base / (target_module.replace(".", "/") + ".py")
                        if rel_candidate.exists():
                            return rel_candidate
                    matches = list(search_root.glob(f"**/{target_module.replace('.', '/')}\.py"))
                    if matches:
                        return matches[0]
    return path


def collect_cli_arguments(repo_root: Path) -> list[CLIArgument]:
    ros_ws = repo_root / "ros2_ws"
    search_root = ros_ws / "src"
    setup_files = list(search_root.glob("*/setup.py"))
    arguments: list[CLIArgument] = []
    for setup in setup_files:
        scripts = parse_console_scripts(setup)
        for script in scripts:
            target_path = _follow_proxy(script, search_root=search_root, seen={script.module})
            if not target_path.exists():
                continue
            args = _parse_arguments_from_file(target_path, script.command, repo_root=repo_root)
            arguments.extend(args)
    return arguments


def _parse_arguments_from_file(path: Path, command: str, *, repo_root: Path) -> list[CLIArgument]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _CLIVisitor()
    visitor.visit(tree)
    results: list[CLIArgument] = []
    for call, options in visitor.arguments:
        flags = ", ".join(options) if options else "<positional>"
        kw = {kw.arg: kw.value for kw in call.keywords if kw.arg}
        action = _literal(kw.get("action")) if "action" in kw else None
        arg_type = _literal(kw.get("type")) if "type" in kw else ("bool" if action in {"store_true", "store_false"} else "str")
        if isinstance(arg_type, ast.AST):
            arg_type = _literal(arg_type)
        if action == "store_true":
            default = "False"
            arg_type = "bool"
        elif action == "store_false":
            default = "True"
            arg_type = "bool"
        else:
            default_val = _literal(kw.get("default")) if "default" in kw else ""
            default = str(default_val) if default_val not in (None, "None") else ""
        required_val = _literal(kw.get("required")) if "required" in kw else False
        required = "yes" if required_val else "no"
        help_text = _literal(kw.get("help")) if "help" in kw else ""
        choices_val = _literal(kw.get("choices")) if "choices" in kw else None
        if choices_val:
            choices_str = ", ".join(map(str, choices_val)) if isinstance(choices_val, (list, tuple, set)) else str(choices_val)
            help_text = f"{help_text} Choices: {choices_str}".strip()
        try:
            rel_path = path.relative_to(repo_root)
        except ValueError:
            rel_path = path
        source = f"{rel_path}:{call.lineno}"
        results.append(
            CLIArgument(
                command=command,
                flags=flags if isinstance(flags, str) else ", ".join(map(str, flags)),
                arg_type=str(arg_type),
                default=default,
                required=required,
                description=str(help_text),
                source=source,
            )
        )
    return results


def render_cli_table(arguments: list[CLIArgument]) -> str:
    headers = [
        TableColumn("Command"),
        TableColumn("Flag"),
        TableColumn("Type"),
        TableColumn("Default"),
        TableColumn("Required"),
        TableColumn("Description"),
        TableColumn("Source"),
    ]
    rows = [
        [
            arg.command,
            arg.flags,
            arg.arg_type,
            arg.default,
            arg.required,
            arg.description,
            arg.source,
        ]
        for arg in sorted(arguments, key=lambda item: (item.command, item.flags))
    ]
    return format_table(headers, rows)


def render_cli_summary(arguments: list[CLIArgument]) -> str:
    headers = [
        TableColumn("Command"),
        TableColumn("Flag"),
        TableColumn("Default"),
        TableColumn("Description"),
    ]
    rows = [
        [
            arg.command,
            arg.flags,
            arg.default,
            arg.description,
        ]
        for arg in sorted(arguments, key=lambda item: (item.command, item.flags))
    ]
    return format_table(headers, rows)
