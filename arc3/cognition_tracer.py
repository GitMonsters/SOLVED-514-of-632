"""
Cognition Tracer — Lightweight function-call tracing for ARC/RE-ARC solvers.

Captures per-run execution traces (function calls, durations, call counts)
that feed into the multilayer cognition graph pipeline.

Usage:
    tracer = CognitionTracer()
    with tracer.trace(solver_id="009d5c81", puzzle_id="009d5c81",
                      family="color_map", target_module="solver"):
        result = solve(grid)
    record = tracer.last_record
"""

from __future__ import annotations

import ast
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class TraceEvent:
    """A single function call captured during solver execution."""
    func_name: str          # Python function name
    file_path: str          # Absolute path (empty string for builtins)
    module_name: str        # Dotted module name or solver file stem
    start_ns: int           # time.perf_counter_ns() at call
    end_ns: int = 0         # time.perf_counter_ns() at return (0 = not yet returned)
    depth: int = 0          # call stack depth at time of call
    call_count: int = 1     # incremented when same function called multiple times

    @property
    def duration_us(self) -> float:
        return (self.end_ns - self.start_ns) / 1_000 if self.end_ns else 0.0


@dataclass
class RunRecord:
    """Complete trace record for a single (solver, puzzle) run."""
    solver_id: str
    solver_family: str          # e.g. "specialized", "pipeline", "baseline"
    puzzle_id: str
    puzzle_family: str          # e.g. "tiling", "symmetry", "color_map"
    success: bool
    total_runtime_ms: float
    events: list[TraceEvent] = field(default_factory=list)

    # Aggregate stats (populated by finalize())
    unique_functions: int = 0
    total_calls: int = 0
    hot_functions: list[str] = field(default_factory=list)  # top-5 by call count

    def finalize(self) -> None:
        """Compute aggregate stats from events."""
        self.unique_functions = len({e.func_name for e in self.events})
        self.total_calls = sum(e.call_count for e in self.events)
        by_count = sorted(self.events, key=lambda e: e.call_count, reverse=True)
        self.hot_functions = [e.func_name for e in by_count[:5]]

    def to_jsonl_line(self) -> str:
        """Serialize to a single JSONL line."""
        d = asdict(self)
        # Convert TraceEvent lists to lightweight dicts
        d["events"] = [
            {
                "fn": e.func_name,
                "mod": e.module_name,
                "dur_us": e.duration_us,
                "calls": e.call_count,
                "depth": e.depth,
            }
            for e in self.events
        ]
        return json.dumps(d)

    @staticmethod
    def from_jsonl_line(line: str) -> "RunRecord":
        """Deserialize from a JSONL line (events as lightweight dicts)."""
        d = json.loads(line)
        # Reconstruct minimal TraceEvent objects
        events = [
            TraceEvent(
                func_name=ev["fn"],
                file_path="",
                module_name=ev.get("mod", ""),
                start_ns=0,
                end_ns=int(ev.get("dur_us", 0) * 1_000),
                depth=ev.get("depth", 0),
                call_count=ev.get("calls", 1),
            )
            for ev in d.pop("events", [])
        ]
        rec = RunRecord(**d, events=events)
        return rec


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class CognitionTracer:
    """
    Wraps solver execution with sys.settrace to capture all function calls
    within the target module (solver file), recording timing and call counts.

    Only functions defined in files matching `target_file_prefix` are traced
    to avoid enormous traces from Python internals.
    """

    def __init__(self, target_file_prefix: Optional[str] = None):
        """
        Args:
            target_file_prefix: Only trace functions in files whose path starts
                with this prefix.  Defaults to arc-puzzle-catalog root.
        """
        if target_file_prefix is None:
            # Default: only trace code inside the arc-puzzle-catalog tree
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            target_file_prefix = here
        self.target_file_prefix = target_file_prefix
        self.last_record: Optional[RunRecord] = None

    @contextmanager
    def trace(
        self,
        solver_id: str,
        puzzle_id: str,
        puzzle_family: str,
        solver_family: str = "specialized",
    ):
        """Context manager that traces all function calls during the `with` block.

        Example:
            with tracer.trace("009d5c81", "009d5c81", "color_map"):
                result = solve(grid)
        """
        events: list[TraceEvent] = []
        call_stack: list[TraceEvent] = []
        func_registry: dict[str, TraceEvent] = {}   # func_key → latest event

        def _local_trace(frame, event, arg):
            """Per-function local tracer (handles 'return')."""
            if event == "return":
                fn = frame.f_code.co_name
                fp = frame.f_code.co_filename or ""
                key = f"{fp}:{fn}"
                if key in func_registry:
                    func_registry[key].end_ns = time.perf_counter_ns()
                if call_stack and call_stack[-1].func_name == fn:
                    call_stack.pop()
            return _local_trace

        def _global_trace(frame, event, arg):
            """Global tracer — fires on every 'call' event."""
            if event != "call":
                return None
            fp = frame.f_code.co_filename or ""
            # Skip builtins and external libraries
            if fp and not fp.startswith(self.target_file_prefix):
                return None
            fn = frame.f_code.co_name
            # Skip dunder/private internals that are uninteresting
            if fn.startswith("__") and fn not in ("__init__",):
                return None
            # Derive a stable module name from the file path
            mod = _file_to_module(fp)
            key = f"{fp}:{fn}"
            if key in func_registry:
                func_registry[key].call_count += 1
                return _local_trace
            ev = TraceEvent(
                func_name=fn,
                file_path=fp,
                module_name=mod,
                start_ns=time.perf_counter_ns(),
                depth=len(call_stack),
            )
            func_registry[key] = ev
            events.append(ev)
            call_stack.append(ev)
            return _local_trace

        t0 = time.perf_counter()
        old_trace = sys.gettrace()
        sys.settrace(_global_trace)
        try:
            yield
        finally:
            sys.settrace(old_trace)
            elapsed_ms = (time.perf_counter() - t0) * 1_000

        record = RunRecord(
            solver_id=solver_id,
            solver_family=solver_family,
            puzzle_id=puzzle_id,
            puzzle_family=puzzle_family,
            success=False,              # caller must set this after the `with` block
            total_runtime_ms=elapsed_ms,
            events=events,
        )
        record.finalize()
        self.last_record = record

    def set_success(self, success: bool) -> None:
        """Call immediately after the trace context to mark success."""
        if self.last_record is not None:
            self.last_record.success = success


# ---------------------------------------------------------------------------
# JSONL log utilities
# ---------------------------------------------------------------------------

class TraceLog:
    """Appends RunRecords to a JSONL file; supports iteration."""

    def __init__(self, path: str):
        self.path = path

    def append(self, record: RunRecord) -> None:
        with open(self.path, "a") as fh:
            fh.write(record.to_jsonl_line() + "\n")

    def __iter__(self):
        if not os.path.exists(self.path):
            return
        with open(self.path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield RunRecord.from_jsonl_line(line)

    def all_records(self) -> list[RunRecord]:
        return list(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_to_module(fp: str) -> str:
    """Convert an absolute file path to a short module label."""
    if not fp:
        return "<builtin>"
    # e.g. .../solves/009d5c81/solver.py  → "009d5c81.solver"
    parts = fp.replace("\\", "/").split("/")
    # Drop .py extension from last part
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    # Keep last 2 meaningful segments
    return ".".join(parts[-2:]) if len(parts) >= 2 else parts[-1]


def extract_static_functions(source: str) -> list[dict]:
    """
    Parse Python source and return a list of function info dicts:
        {"name": str, "lineno": int, "calls": [str], "docstring": str}
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    class FuncVisitor(ast.NodeVisitor):
        def __init__(self):
            self.functions: list[dict] = []
            self._current: list[str] = []

        def visit_FunctionDef(self, node):
            doc = ast.get_docstring(node) or ""
            calls: list[str] = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls.append(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls.append(child.func.attr)
            self.functions.append({
                "name": node.name,
                "lineno": node.lineno,
                "calls": calls,
                "docstring": doc[:120],
            })
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

    v = FuncVisitor()
    v.visit(tree)
    return v.functions
