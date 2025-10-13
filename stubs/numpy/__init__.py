"""Lightweight numpy stub for CLI help invocation in constrained environments."""

float32 = "float32"


class ndarray(list):
    """Placeholder ndarray type for type annotations."""


def dtype(arg):  # pragma: no cover - stub
    return arg


def empty(shape, dtype=None):  # pragma: no cover - stub
    return [[0] * (shape[1] if isinstance(shape, tuple) and len(shape) > 1 else 0) for _ in range(shape[0] if isinstance(shape, tuple) else 0)]


def asarray(obj, dtype=None):  # pragma: no cover - stub
    return obj
