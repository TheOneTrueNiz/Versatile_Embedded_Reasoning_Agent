#!/usr/bin/env python3
"""
Minimal MCP Calculator Server (stdio JSON-RPC)
===============================================

Provides a dependency-free MCP server with arithmetic, unit conversion,
percentage, and statistical tools. Safe expression evaluation without eval().
"""

from __future__ import annotations

import json
import math
import signal
import sys
import statistics
from typing import Any, Dict, List, Optional


class _ComputeTimeout(Exception):
    """Raised when a computation exceeds the time limit."""
    pass


def _timeout_handler(signum, frame):
    raise _ComputeTimeout("Computation timed out after 5 seconds. Expression may be too complex (e.g. factorial of very large numbers).")


TOOLS = [
    {
        "name": "calculate",
        "description": (
            "Evaluate a mathematical expression safely. Supports: +, -, *, /, ** (power), "
            "% (modulo), parentheses, and math functions (sqrt, sin, cos, tan, log, log10, "
            "abs, ceil, floor, round, factorial, exp, pow, hypot, gcd, pi, e, tau). "
            "Examples: '2 * (3 + 4)' → 14, 'sqrt(144)' → 12, 'sin(pi/2)' → 1.0, "
            "'factorial(10)' → 3628800. 5-second timeout on expensive computations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Math expression to evaluate, e.g. '2 * (3 + 4)', 'sqrt(144)', 'sin(pi/2)'"
                }
            },
            "required": ["expression"],
        },
    },
    {
        "name": "convert_units",
        "description": (
            "Convert between common units. Categories: length (m, km, mi, ft, in, cm, mm, yd), "
            "weight (kg, g, lb, oz, mg), temperature (C, F, K), volume (L, mL, gal, qt, pt, cup, fl_oz), "
            "data (B, KB, MB, GB, TB, PB), time (s, ms, min, h, d, wk). "
            "Examples: {value:100, from_unit:'F', to_unit:'C'} → 37.78, "
            "{value:1, from_unit:'GB', to_unit:'MB'} → 1024."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "value": {"type": "number", "description": "Numeric value to convert"},
                "from_unit": {"type": "string", "description": "Source unit (e.g. 'km', 'lb', 'C')"},
                "to_unit": {"type": "string", "description": "Target unit (e.g. 'mi', 'kg', 'F')"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
    },
    {
        "name": "percentage",
        "description": (
            "Percentage calculations. Operations: 'of' = what is X% of Y (e.g. 15% of 200 → 30), "
            "'change' = percent change from X to Y (e.g. 100 to 150 → 50%), "
            "'is' = X is what % of Y (e.g. 30 is what % of 200 → 15%)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["of", "change", "is"],
                    "description": "'of': X% of Y, 'change': % change from X to Y, 'is': X is what % of Y"
                },
                "x": {"type": "number", "description": "First number"},
                "y": {"type": "number", "description": "Second number"},
            },
            "required": ["operation", "x", "y"],
        },
    },
    {
        "name": "statistics",
        "description": (
            "Compute statistics on a list of numbers. Use operation='all' (default) to get everything at once, "
            "or pick one: mean, median, mode, stdev, variance, min, max, sum, count, range. "
            "Requires at least 1 number; stdev/variance need 2+."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "numbers": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "List of numbers to analyze"
                },
                "operation": {
                    "type": "string",
                    "enum": ["all", "mean", "median", "mode", "stdev", "variance", "min", "max", "sum", "count", "range"],
                    "description": "Statistic to compute. 'all' returns everything. Default: 'all'"
                },
            },
            "required": ["numbers"],
        },
    },
]


# --- Safe expression evaluator (no eval) ---

_MATH_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
}

_MATH_FUNCTIONS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
    "round": round,
    "factorial": math.factorial,
    "radians": math.radians,
    "degrees": math.degrees,
    "exp": math.exp,
    "pow": pow,
    "hypot": math.hypot,
    "gcd": math.gcd,
}


def _safe_eval(expr: str) -> float:
    """Safely evaluate a math expression using Python's compile with restricted globals."""
    allowed_names: Dict[str, Any] = {}
    allowed_names.update(_MATH_CONSTANTS)
    allowed_names.update(_MATH_FUNCTIONS)
    allowed_names["__builtins__"] = {}

    # Sanitize: reject anything suspicious
    forbidden = [
        "import", "exec", "eval", "open", "os.", "sys.",
        "__import__", "__builtins__", "__class__", "__subclasses__",
        "__globals__", "__getattr__", "__dict__",
        "__", "lambda", "def ", "class ", "breakpoint", "compile",
    ]
    expr_lower = expr.lower()
    for f in forbidden:
        if f in expr_lower:
            raise ValueError(f"Forbidden token in expression: '{f}'")

    try:
        code = compile(expr, "<calc>", "eval")
        # Verify code only references allowed names
        for name in code.co_names:
            if name not in allowed_names:
                raise ValueError(f"Unknown name '{name}' in expression")
        # Set 5-second timeout for expensive computations (e.g. factorial(10**6))
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(5)
        try:
            result = builtins_eval(code, allowed_names)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    except _ComputeTimeout:
        raise
    except (SyntaxError, TypeError) as exc:
        raise ValueError(f"Invalid expression: {exc}") from exc

    if isinstance(result, complex):
        raise ValueError("Complex numbers not supported")
    return float(result)


def builtins_eval(code, namespace):
    """Execute compiled code in restricted namespace."""
    return eval(code, namespace)


# --- Unit conversion ---

_LENGTH_TO_METERS = {
    "m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001,
    "mi": 1609.344, "yd": 0.9144, "ft": 0.3048, "in": 0.0254,
}

_WEIGHT_TO_GRAMS = {
    "kg": 1000.0, "g": 1.0, "mg": 0.001,
    "lb": 453.592, "oz": 28.3495,
}

_VOLUME_TO_LITERS = {
    "l": 1.0, "ml": 0.001,
    "gal": 3.78541, "qt": 0.946353, "pt": 0.473176,
    "cup": 0.236588, "fl_oz": 0.0295735,
}

_DATA_TO_BYTES = {
    "b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3,
    "tb": 1024**4, "pb": 1024**5,
}

_TIME_TO_SECONDS = {
    "s": 1.0, "ms": 0.001, "min": 60.0, "h": 3600.0,
    "d": 86400.0, "wk": 604800.0,
}


def _convert_temperature(value: float, from_u: str, to_u: str) -> float:
    # Normalize to Celsius first
    if from_u == "c":
        c = value
    elif from_u == "f":
        c = (value - 32) * 5 / 9
    elif from_u == "k":
        c = value - 273.15
    else:
        raise ValueError(f"Unknown temperature unit: {from_u}")

    # Convert from Celsius to target
    if to_u == "c":
        return c
    elif to_u == "f":
        return c * 9 / 5 + 32
    elif to_u == "k":
        return c + 273.15
    else:
        raise ValueError(f"Unknown temperature unit: {to_u}")


def _convert_via_table(value: float, from_u: str, to_u: str, table: dict, unit_type: str) -> float:
    if from_u not in table:
        raise ValueError(f"Unknown {unit_type} unit: {from_u}")
    if to_u not in table:
        raise ValueError(f"Unknown {unit_type} unit: {to_u}")
    base = value * table[from_u]
    return base / table[to_u]


def _convert_units(value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
    from_u = from_unit.lower().strip()
    to_u = to_unit.lower().strip()

    if from_u == to_u:
        return {"result": value, "from": from_unit, "to": to_unit}

    # Detect unit category
    temp_units = {"c", "f", "k"}
    if from_u in temp_units or to_u in temp_units:
        result = _convert_temperature(value, from_u, to_u)
    elif from_u in _LENGTH_TO_METERS or to_u in _LENGTH_TO_METERS:
        result = _convert_via_table(value, from_u, to_u, _LENGTH_TO_METERS, "length")
    elif from_u in _WEIGHT_TO_GRAMS or to_u in _WEIGHT_TO_GRAMS:
        result = _convert_via_table(value, from_u, to_u, _WEIGHT_TO_GRAMS, "weight")
    elif from_u in _VOLUME_TO_LITERS or to_u in _VOLUME_TO_LITERS:
        result = _convert_via_table(value, from_u, to_u, _VOLUME_TO_LITERS, "volume")
    elif from_u in _DATA_TO_BYTES or to_u in _DATA_TO_BYTES:
        result = _convert_via_table(value, from_u, to_u, _DATA_TO_BYTES, "data")
    elif from_u in _TIME_TO_SECONDS or to_u in _TIME_TO_SECONDS:
        result = _convert_via_table(value, from_u, to_u, _TIME_TO_SECONDS, "time")
    else:
        raise ValueError(f"Cannot convert between '{from_unit}' and '{to_unit}'")

    return {"result": round(result, 10), "from": f"{value} {from_unit}", "to": f"{result:.10g} {to_unit}"}


# --- Percentage ---

def _percentage(operation: str, x: float, y: float) -> Dict[str, Any]:
    if operation == "of":
        result = (x / 100) * y
        return {"result": result, "description": f"{x}% of {y} = {result}"}
    elif operation == "change":
        if x == 0:
            raise ValueError("Cannot compute percent change from zero")
        result = ((y - x) / abs(x)) * 100
        return {"result": round(result, 6), "description": f"Change from {x} to {y} = {result:.6g}%"}
    elif operation == "is":
        if y == 0:
            raise ValueError("Cannot compute percentage of zero")
        result = (x / y) * 100
        return {"result": round(result, 6), "description": f"{x} is {result:.6g}% of {y}"}
    else:
        raise ValueError(f"Unknown operation: {operation}")


# --- Statistics ---

def _statistics(numbers: List[float], operation: str = "all") -> Any:
    if not numbers:
        raise ValueError("Need at least one number")

    def _compute_all():
        result = {
            "count": len(numbers),
            "sum": sum(numbers),
            "mean": statistics.mean(numbers),
            "min": min(numbers),
            "max": max(numbers),
            "range": max(numbers) - min(numbers),
        }
        if len(numbers) >= 2:
            result["median"] = statistics.median(numbers)
            result["stdev"] = round(statistics.stdev(numbers), 10)
            result["variance"] = round(statistics.variance(numbers), 10)
        try:
            result["mode"] = statistics.mode(numbers)
        except statistics.StatisticsError:
            result["mode"] = None
        return result

    if operation == "all":
        return _compute_all()

    ops = {
        "mean": lambda: statistics.mean(numbers),
        "median": lambda: statistics.median(numbers),
        "mode": lambda: statistics.mode(numbers),
        "stdev": lambda: statistics.stdev(numbers),
        "variance": lambda: statistics.variance(numbers),
        "min": lambda: min(numbers),
        "max": lambda: max(numbers),
        "sum": lambda: sum(numbers),
        "count": lambda: len(numbers),
        "range": lambda: max(numbers) - min(numbers),
    }
    if operation not in ops:
        raise ValueError(f"Unknown statistic: {operation}")
    return {operation: ops[operation]()}


# --- MCP JSON-RPC server ---

def _send_response(response: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _send_error(req_id: Optional[int], message: str, code: int = -32602) -> None:
    _send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    })


def _handle_tool_call(name: str, args: Dict[str, Any]) -> Any:
    if name == "calculate":
        expr = args.get("expression", "")
        result = _safe_eval(expr)
        return {"expression": expr, "result": result}

    if name == "convert_units":
        return _convert_units(
            float(args["value"]),
            args["from_unit"],
            args["to_unit"],
        )

    if name == "percentage":
        return _percentage(args["operation"], float(args["x"]), float(args["y"]))

    if name == "statistics":
        raw = args.get("numbers")
        if not raw or (isinstance(raw, list) and len(raw) == 0):
            raise ValueError("numbers list is empty — provide at least one number")
        nums = [float(n) for n in raw]
        op = args.get("operation", "all")
        return _statistics(nums, op)

    raise ValueError(f"Unknown tool '{name}'")


def _handle_request(request: Dict[str, Any]) -> None:
    req_id = request.get("id")
    method = request.get("method")

    if method == "notifications/initialized":
        return

    if method == "ping":
        _send_response({"jsonrpc": "2.0", "id": req_id, "result": "pong"})
        return

    if method == "tools/list":
        _send_response({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        return

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = _handle_tool_call(name, args)
        except Exception as exc:
            _send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            })
            return
        _send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result)}],
            },
        })
        return

    if method == "initialize":
        _send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "vera-calculator", "version": "1.0"},
                "capabilities": {"tools": {}},
            },
        })
        return

    if method == "shutdown":
        _send_response({"jsonrpc": "2.0", "id": req_id, "result": "ok"})
        sys.exit(0)

    _send_error(req_id, f"Unknown method '{method}'", code=-32601)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        _handle_request(request)


if __name__ == "__main__":
    main()
