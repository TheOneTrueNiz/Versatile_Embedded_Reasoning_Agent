#!/usr/bin/env python3
"""
Safe Code Sandbox for VERA
==========================

Provides a minimal Python execution sandbox with AST validation,
timeout isolation, and optional session memory.
"""

from __future__ import annotations

import ast
import io
import os
import queue
import time
from contextlib import redirect_stdout
from dataclasses import dataclass
from multiprocessing import Process, Queue
from typing import Any, Dict, List, Optional


SAFE_BUILTINS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "sorted": sorted,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "float": float,
    "int": int,
    "str": str,
    "bool": bool,
}


ALLOWED_NODES = {
    ast.Module,
    ast.Expression,
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.Subscript,
    ast.Slice,
    ast.Call,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
}

if hasattr(ast, "Index"):
    ALLOWED_NODES.add(ast.Index)


DISALLOWED_NODES = {
    ast.Import,
    ast.ImportFrom,
    ast.Attribute,
    ast.Lambda,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Raise,
    ast.Global,
    ast.Nonlocal,
    ast.While,
    ast.For,
    ast.AsyncFor,
    ast.Delete,
    ast.Yield,
    ast.YieldFrom,
    ast.Await,
}


@dataclass
class SandboxResult:
    success: bool
    result: Optional[Any] = None
    stdout: str = ""
    error: str = ""
    duration_ms: float = 0.0
    truncated: bool = False


class SandboxSafetyError(Exception):
    pass


class SandboxTimeout(Exception):
    pass


def _validate_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if type(node) in DISALLOWED_NODES:
            raise SandboxSafetyError(f"Disallowed syntax: {type(node).__name__}")
        if type(node) not in ALLOWED_NODES:
            raise SandboxSafetyError(f"Unsupported syntax: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in SAFE_BUILTINS:
                    raise SandboxSafetyError(f"Call not allowed: {node.func.id}")
            else:
                raise SandboxSafetyError("Only direct function calls are allowed")
        if isinstance(node, ast.Name):
            if node.id.startswith("__"):
                raise SandboxSafetyError("Dunder access is not allowed")


def _run_code(
    code: str,
    locals_state: Dict[str, Any],
    output_queue: Queue,
    max_output_chars: int,
) -> None:
    start = time.time()
    stdout_buffer = io.StringIO()
    safe_globals = {"__builtins__": SAFE_BUILTINS}
    safe_locals = dict(locals_state)
    result_value = None

    try:
        parsed = ast.parse(code, mode="exec")
        _validate_ast(parsed)

        final_expr = None
        if parsed.body and isinstance(parsed.body[-1], ast.Expr):
            final_expr = parsed.body.pop()
        with redirect_stdout(stdout_buffer):
            exec(compile(parsed, "<sandbox>", "exec"), safe_globals, safe_locals)
            if final_expr is not None:
                expr_ast = ast.Expression(final_expr.value)
                _validate_ast(expr_ast)
                result_value = eval(compile(expr_ast, "<sandbox>", "eval"), safe_globals, safe_locals)

        locals_state.clear()
        locals_state.update({k: v for k, v in safe_locals.items() if not k.startswith("__")})

        stdout_value = stdout_buffer.getvalue()
        truncated = False
        if max_output_chars > 0 and len(stdout_value) > max_output_chars:
            stdout_value = stdout_value[:max_output_chars] + "...[truncated]"
            truncated = True

        output_queue.put({
            "success": True,
            "result": result_value,
            "stdout": stdout_value,
            "error": "",
            "duration_ms": (time.time() - start) * 1000,
            "locals_state": locals_state,
            "truncated": truncated,
        })
    except Exception as exc:
        output_queue.put({
            "success": False,
            "result": None,
            "stdout": stdout_buffer.getvalue(),
            "error": str(exc),
            "duration_ms": (time.time() - start) * 1000,
            "locals_state": locals_state,
            "truncated": False,
        })


class SandboxToolBridge:
    def __init__(self) -> None:
        self._sessions: Dict[str, Dict[str, Any]] = {}
        try:
            self._max_sessions = int(os.getenv("VERA_SANDBOX_MAX_SESSIONS", "8"))
        except (ValueError, TypeError):
            self._max_sessions = 8

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "sandbox_python",
                    "description": (
                        "Execute small Python snippets in a safe sandbox with AST validation. "
                        "Use for: mathematical calculations, data transformations, unit conversions, "
                        "string manipulation, list/dict operations, quick computations. "
                        "Returns: result (last expression value), stdout (print output), error (if any), duration_ms. "
                        "Available builtins: abs, round, min, max, sum, len, sorted, range, enumerate, "
                        "zip, map, filter, list, dict, set, tuple, float, int, str, bool. "
                        "BLOCKED: imports, file I/O, network, loops, function/class definitions, attribute access. "
                        "Tip: Use session_id to persist variables between calls. Use print() for intermediate output. "
                        "Example: 'x = [1,2,3]; sum(x) * 2' returns 12."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python code to execute. Last expression is returned as result. Use print() for output."
                            },
                            "session_id": {
                                "type": "string",
                                "description": "Session key to persist variables between calls. Use same ID to continue computation."
                            },
                            "timeout_ms": {
                                "type": "integer",
                                "description": "Max execution time in milliseconds (default: 1500). Kills process if exceeded."
                            },
                            "max_output_chars": {
                                "type": "integer",
                                "description": "Max stdout characters (default: 2000). Truncated if exceeded."
                            },
                            "reset_session": {
                                "type": "boolean",
                                "description": "Clear session variables before execution (default: false)."
                            },
                        },
                        "required": ["code"],
                    },
                },
            }
        ]

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name != "sandbox_python":
            return {"success": False, "error": f"Unknown sandbox tool: {tool_name}"}

        code = str(params.get("code", "")).strip()
        if not code:
            return {"success": False, "error": "No code provided."}

        session_id = str(params.get("session_id") or "default")
        timeout_ms = int(params.get("timeout_ms", 1500))
        max_output_chars = int(params.get("max_output_chars", 2000))
        reset_session = bool(params.get("reset_session", False))

        if reset_session:
            self._sessions.pop(session_id, None)

        if session_id not in self._sessions:
            if len(self._sessions) >= self._max_sessions:
                oldest = next(iter(self._sessions.keys()))
                self._sessions.pop(oldest, None)
            self._sessions[session_id] = {}

        state = self._sessions[session_id]
        result = self._run_in_process(code, state, timeout_ms, max_output_chars)
        if result.success:
            self._sessions[session_id] = state

        return {
            "success": result.success,
            "result": result.result,
            "stdout": result.stdout,
            "error": result.error,
            "duration_ms": round(result.duration_ms, 2),
            "truncated": result.truncated,
            "session_id": session_id,
        }

    def _run_in_process(
        self,
        code: str,
        state: Dict[str, Any],
        timeout_ms: int,
        max_output_chars: int,
    ) -> SandboxResult:
        output_queue: Queue = Queue()
        process = Process(
            target=_run_code,
            args=(code, dict(state), output_queue, max_output_chars),
        )
        start = time.time()
        process.start()
        process.join(timeout_ms / 1000.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=0.5)
            return SandboxResult(
                success=False,
                error="Sandbox timeout exceeded.",
                duration_ms=(time.time() - start) * 1000,
            )

        try:
            payload = output_queue.get_nowait()
        except queue.Empty:
            return SandboxResult(
                success=False,
                error="Sandbox returned no output.",
                duration_ms=(time.time() - start) * 1000,
            )

        if payload.get("locals_state") is not None:
            state.clear()
            state.update(payload.get("locals_state", {}))

        return SandboxResult(
            success=bool(payload.get("success")),
            result=payload.get("result"),
            stdout=str(payload.get("stdout") or ""),
            error=str(payload.get("error") or ""),
            duration_ms=float(payload.get("duration_ms", 0.0)),
            truncated=bool(payload.get("truncated", False)),
        )
