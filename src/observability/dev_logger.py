#!/usr/bin/env python3
"""
Development Logger - Enhanced Debugging System
===============================================

Provides comprehensive end-to-end logging for debugging VERA with zero mysteries.
Activated via VERA_DEV_MODE=1 environment variable.

Logs everything:
- Tool calls (inputs, outputs, timing, success/failure)
- Safety validator decisions
- Cache hits/misses
- Error handler recovery attempts
- API calls to xAI (request/response)
- File operations
- State changes
- Stack traces for all errors
- Performance metrics

Output: Structured NDJSON logs to .dev_logs/ directory
"""

import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from functools import wraps


class DevLogger:
    """
    Comprehensive development logger with zero-mystery debugging.

    Every action, decision, and error is logged with full context.
    """

    def __init__(self, enabled: bool = None, log_dir: Path = None) -> None:
        """
        Initialize dev logger.

        Args:
            enabled: Override environment variable (for testing)
            log_dir: Custom log directory
        """
        # Check environment variable
        if enabled is None:
            enabled = os.getenv("VERA_DEV_MODE", "0") == "1"

        self.enabled = enabled

        if not self.enabled:
            return

        # Set up log directory
        if log_dir is None:
            log_dir = Path(__file__).parent.parent / ".dev_logs"

        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create session-specific log file
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"dev_session_{session_id}.ndjson"

        # Performance tracking
        self._timers = {}

        # Write session start
        self._write({
            "event": "session_start",
            "timestamp": self._timestamp(),
            "session_id": session_id,
            "log_file": str(self.log_file),
            "pid": os.getpid(),
        })

        print(f"🔧 DEV MODE ENABLED: Logging to {self.log_file}")

    def _timestamp(self) -> str:
        """Get ISO timestamp"""
        return datetime.now().isoformat()

    def _write(self, data: Dict[str, Any]):
        """Write log entry as NDJSON"""
        if not self.enabled:
            return

        try:
            # Add timestamp if not present
            if "timestamp" not in data:
                data["timestamp"] = self._timestamp()

            # Write to file
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(data, default=str) + '\n')

        except Exception as e:
            # Fail silently - don't break app due to logging issues
            print(f"⚠️ Dev logger write failed: {e}")

    # === Tool Execution Logging ===

    def tool_call_start(self, tool_name: str, params: Dict[str, Any],
                       tool_call_id: Optional[str] = None):
        """Log tool call start"""
        if not self.enabled:
            return

        timer_key = f"tool_{tool_call_id or tool_name}_{time.time()}"
        self._timers[timer_key] = time.time()

        self._write({
            "event": "tool_call_start",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "params": params,
            "timer_key": timer_key,
        })

        return timer_key

    def tool_call_end(self, tool_name: str, result: Any, timer_key: str,
                     success: bool = True, error: Optional[str] = None):
        """Log tool call end"""
        if not self.enabled:
            return

        duration = time.time() - self._timers.get(timer_key, time.time())

        self._write({
            "event": "tool_call_end",
            "tool_name": tool_name,
            "success": success,
            "duration_ms": round(duration * 1000, 2),
            "result_preview": str(result)[:500] if result else None,
            "error": error,
            "timer_key": timer_key,
        })

        # Cleanup timer
        self._timers.pop(timer_key, None)

    # === Safety Validator Logging ===

    def safety_check(self, command: str, result: str, severity: int,
                    matched_pattern: Optional[str] = None, blocked: bool = False):
        """Log safety validator decision"""
        if not self.enabled:
            return

        self._write({
            "event": "safety_check",
            "command": command,
            "result": result,
            "severity": severity,
            "matched_pattern": matched_pattern,
            "blocked": blocked,
        })

    # === Cache Logging ===

    def cache_operation(self, operation: str, tool_name: str, params: Dict[str, Any],
                       hit: bool = None, result_size: int = None):
        """Log cache operation (get/put/hit/miss)"""
        if not self.enabled:
            return

        self._write({
            "event": "cache_operation",
            "operation": operation,  # 'get', 'put', 'hit', 'miss'
            "tool_name": tool_name,
            "params": params,
            "cache_hit": hit,
            "result_size_bytes": result_size,
        })

    # === Error Handler Logging ===

    def error_recovery(self, tool_name: str, error_message: str,
                      failure_type: str, recovery_action: str,
                      attempt_number: int = 1):
        """Log error handler recovery decision"""
        if not self.enabled:
            return

        self._write({
            "event": "error_recovery",
            "tool_name": tool_name,
            "error_message": error_message,
            "failure_type": failure_type,
            "recovery_action": recovery_action,
            "attempt_number": attempt_number,
        })

    # === API Call Logging ===

    def api_call_start(self, endpoint: str, model: str, messages_count: int,
                      tools_count: int):
        """Log API call start"""
        if not self.enabled:
            return

        timer_key = f"api_{time.time()}"
        self._timers[timer_key] = time.time()

        self._write({
            "event": "api_call_start",
            "endpoint": endpoint,
            "model": model,
            "messages_count": messages_count,
            "tools_count": tools_count,
            "timer_key": timer_key,
        })

        return timer_key

    def api_call_end(self, timer_key: str, response_status: int,
                    response_preview: str, tokens_used: int = None,
                    success: bool = True, error: Optional[str] = None):
        """Log API call end"""
        if not self.enabled:
            return

        duration = time.time() - self._timers.get(timer_key, time.time())

        self._write({
            "event": "api_call_end",
            "success": success,
            "response_status": response_status,
            "response_preview": response_preview[:500],
            "tokens_used": tokens_used,
            "duration_ms": round(duration * 1000, 2),
            "error": error,
            "timer_key": timer_key,
        })

        self._timers.pop(timer_key, None)

    # === File Operation Logging ===

    def file_operation(self, operation: str, path: str, success: bool = True,
                      size_bytes: int = None, error: Optional[str] = None):
        """Log file operation"""
        if not self.enabled:
            return

        self._write({
            "event": "file_operation",
            "operation": operation,  # 'read', 'write', 'delete', etc.
            "path": path,
            "success": success,
            "size_bytes": size_bytes,
            "error": error,
        })

    # === State Change Logging ===

    def state_change(self, component: str, old_state: Any, new_state: Any,
                    reason: str):
        """Log state change"""
        if not self.enabled:
            return

        self._write({
            "event": "state_change",
            "component": component,
            "old_state": old_state,
            "new_state": new_state,
            "reason": reason,
        })

    # === Error Logging with Stack Traces ===

    def exception(self, error: Exception, context: str,
                 additional_data: Dict[str, Any] = None):
        """Log exception with full stack trace"""
        if not self.enabled:
            return

        self._write({
            "event": "exception",
            "context": context,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "stack_trace": traceback.format_exc(),
            "additional_data": additional_data or {},
        })

    # === Generic Logging ===

    def log(self, event: str, **kwargs) -> None:
        """Generic logging method"""
        if not self.enabled:
            return

        self._write({
            "event": event,
            **kwargs
        })

    # === Decorator for Function Tracing ===

    def trace(self, func_name: str = None):
        """
        Decorator to trace function calls.

        Usage:
            @dev_logger.trace()
            def my_function(arg1, arg2):
                ...
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                if not self.enabled:
                    return func(*args, **kwargs)

                name = func_name or func.__name__
                timer_key = f"func_{name}_{time.time()}"
                self._timers[timer_key] = time.time()

                self._write({
                    "event": "function_start",
                    "function": name,
                    "args": str(args)[:200],
                    "kwargs": str(kwargs)[:200],
                    "timer_key": timer_key,
                })

                try:
                    result = func(*args, **kwargs)
                    duration = time.time() - self._timers.get(timer_key, time.time())

                    self._write({
                        "event": "function_end",
                        "function": name,
                        "success": True,
                        "duration_ms": round(duration * 1000, 2),
                        "timer_key": timer_key,
                    })

                    self._timers.pop(timer_key, None)
                    return result

                except Exception as e:
                    duration = time.time() - self._timers.get(timer_key, time.time())

                    self._write({
                        "event": "function_end",
                        "function": name,
                        "success": False,
                        "duration_ms": round(duration * 1000, 2),
                        "error": str(e),
                        "stack_trace": traceback.format_exc(),
                        "timer_key": timer_key,
                    })

                    self._timers.pop(timer_key, None)
                    raise

            return wrapper
        return decorator

    # === Session End ===

    def close(self) -> None:
        """Close logger and write session summary"""
        if not self.enabled:
            return

        self._write({
            "event": "session_end",
            "timestamp": self._timestamp(),
        })

        print(f"🔧 DEV MODE: Session logged to {self.log_file}")


# Global instance (initialized in run_vera.py)
_GLOBAL_DEV_LOGGER: Optional[DevLogger] = None


def get_dev_logger() -> Optional[DevLogger]:
    """Get global dev logger instance"""
    return _GLOBAL_DEV_LOGGER


def init_dev_logger(enabled: bool = None) -> DevLogger:
    """Initialize global dev logger instance"""
    global _GLOBAL_DEV_LOGGER
    _GLOBAL_DEV_LOGGER = DevLogger(enabled=enabled)
    return _GLOBAL_DEV_LOGGER


# === CLI for Log Analysis ===

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python dev_logger.py <log_file>")
        print("\nAnalyzes dev logs and provides debugging insights")
        sys.exit(1)

    log_file = Path(sys.argv[1])
    if not log_file.exists():
        print(f"❌ Log file not found: {log_file}")
        sys.exit(1)

    print(f"📊 Analyzing {log_file}...")
    print("=" * 70)

    # Read and analyze logs
    events = []
    with open(log_file, 'r') as f:
        for line in f:
            events.append(json.loads(line))

    # Summary statistics
    event_counts = {}
    tool_calls = []
    errors = []
    cache_hits = 0
    cache_misses = 0

    for event in events:
        event_type = event.get("event")
        event_counts[event_type] = event_counts.get(event_type, 0) + 1

        if event_type == "tool_call_end":
            tool_calls.append(event)
        elif event_type == "exception":
            errors.append(event)
        elif event_type == "cache_operation":
            if event.get("cache_hit"):
                cache_hits += 1
            elif event.get("cache_hit") is False:
                cache_misses += 1

    # Print summary
    print(f"\n📈 Event Summary ({len(events)} total events)")
    print("-" * 70)
    for event_type, count in sorted(event_counts.items(), key=lambda x: -x[1]):
        print(f"  {event_type:30s}: {count}")

    # Tool call analysis
    print(f"\n🔧 Tool Calls ({len(tool_calls)} total)")
    print("-" * 70)
    tool_stats = {}
    for call in tool_calls:
        name = call.get("tool_name", "unknown")
        if name not in tool_stats:
            tool_stats[name] = {"count": 0, "total_time": 0, "failures": 0}
        tool_stats[name]["count"] += 1
        tool_stats[name]["total_time"] += call.get("duration_ms", 0)
        if not call.get("success", True):
            tool_stats[name]["failures"] += 1

    for tool, stats in sorted(tool_stats.items(), key=lambda x: -x[1]["count"]):
        avg_time = stats["total_time"] / stats["count"] if stats["count"] > 0 else 0
        print(f"  {tool:30s}: {stats['count']:3d} calls, {avg_time:6.1f}ms avg, {stats['failures']} failures")

    # Cache analysis
    if cache_hits + cache_misses > 0:
        hit_rate = cache_hits / (cache_hits + cache_misses) * 100
        print(f"\n💾 Cache Performance")
        print("-" * 70)
        print(f"  Hits: {cache_hits}, Misses: {cache_misses}, Hit Rate: {hit_rate:.1f}%")

    # Error analysis
    if errors:
        print(f"\n❌ Errors ({len(errors)} total)")
        print("-" * 70)
        for error in errors[:5]:  # Show first 5
            print(f"  [{error.get('timestamp')}] {error.get('context')}")
            print(f"    {error.get('error_type')}: {error.get('error_message')}")

    print("\n" + "=" * 70)
    print("✅ Analysis complete")
