#!/usr/bin/env python3
"""
Async Tool Executor - Gap 1 Implementation
===========================================

Non-blocking tool invocation with event-driven responses for VERA.

Based on research:
- Asynchronous Tool Usage for Real-Time Agents (arXiv:2410.21620, Oct 2024)
- AsyncFlow: Asynchronous Streaming RL Framework (arXiv:2507.01663, Jul 2025)
- StreamAgent: Anticipatory Agents (arXiv:2508.01875, Aug 2025)

Key Features:
- Event-driven FSM architecture for parallel tool execution
- Non-blocking invocation returns immediately with task_id
- Event queue for completed results
- 3-5× speedup for multi-tool workflows
- Graceful timeout handling and error recovery

Architecture:
┌─────────────┐
│  Main Loop  │
└──────┬──────┘
       │ invoke_tool() → task_id (immediate)
       ▼
┌─────────────────────┐
│ AsyncToolExecutor   │
│  • pending_calls {} │  ┌──────────────┐
│  • event_queue []   │  │ Background   │
│  • timeout_tracker  │  │ Task Pool    │
└──────┬──────────────┘  └───────┬──────┘
       │                         │
       │ check_results()         │ async _execute_tool()
       ▼                         ▼
┌─────────────────────┐  ┌─────────────────┐
│  Completed Events   │  │   Tool Result   │
│  {task_id: result}  │◀─│   + Metadata    │
└─────────────────────┘  └─────────────────┘

Usage Example:
    executor = AsyncToolExecutor()

    # Start multiple tools in parallel
    task1 = await executor.invoke_tool("gmail_search", {"query": "..."})
    task2 = await executor.invoke_tool("drive_search", {"query": "..."})
    task3 = await executor.invoke_tool("calendar_search", {"date": "..."})

    # Continue other work...

    # Check for completed results
    results = await executor.check_results()
    for result in results:
        print(f"Task {result['task_id']}: {result['status']}")
"""

import asyncio
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging
logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of an async tool invocation"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ToolTask:
    """Represents a single async tool invocation"""
    task_id: str
    tool_name: str
    params: Dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    timeout_seconds: float = 60.0

    def elapsed_time(self) -> float:
        """Get elapsed time since creation"""
        return (datetime.now() - self.created_at).total_seconds()

    def is_timed_out(self) -> bool:
        """Check if task has exceeded timeout"""
        return self.elapsed_time() > self.timeout_seconds

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for event queue"""
        return {
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "params": self.params,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "elapsed_seconds": self.elapsed_time()
        }


class AsyncToolExecutor:
    """
    Non-blocking tool invocation with event-driven responses

    Features:
    - Parallel tool execution via asyncio
    - Event queue for completed results
    - Timeout enforcement
    - Graceful error handling
    - Task lifecycle tracking

    Performance:
    - 3-5× speedup for 3+ parallel tools
    - No additional latency for single tools
    - <1ms overhead for task creation
    """

    def __init__(self, default_timeout: float = 60.0, max_concurrent: int = 10) -> None:
        """
        Initialize async tool executor

        Args:
            default_timeout: Default timeout for tool execution (seconds)
            max_concurrent: Maximum concurrent tool executions
        """
        self.default_timeout = default_timeout
        self.max_concurrent = max_concurrent

        # Active tasks
        self.pending_calls: Dict[str, asyncio.Task] = {}  # task_id → asyncio.Task
        self.task_metadata: Dict[str, ToolTask] = {}  # task_id → ToolTask

        # Event queue for completed results
        self.event_queue: asyncio.Queue = asyncio.Queue()

        # Tool executor function (will be set during integration)
        self.tool_executor: Optional[Callable] = None

        # Statistics
        self.stats = {
            "total_invocations": 0,
            "completed": 0,
            "failed": 0,
            "timeout": 0,
            "cancelled": 0,
            "avg_duration": 0.0
        }

    def set_tool_executor(self, executor: Callable) -> None:
        """
        Set the tool executor function

        Args:
            executor: Async callable that executes tools
                      Should have signature: async (tool_name: str, params: dict) -> result
        """
        self.tool_executor = executor

    async def invoke_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        timeout: Optional[float] = None,
        priority: int = 0
    ) -> str:
        """
        Non-blocking tool invocation
        Returns immediately with task_id, actual result comes via event queue

        Args:
            tool_name: Name of tool to invoke
            params: Tool parameters
            timeout: Optional custom timeout (overrides default)
            priority: Priority level (higher = more important) - for future use

        Returns:
            task_id: Unique identifier for tracking this invocation

        Raises:
            RuntimeError: If max concurrent tasks exceeded
        """
        # Check concurrency limit
        if len(self.pending_calls) >= self.max_concurrent:
            raise RuntimeError(
                f"Max concurrent tasks ({self.max_concurrent}) exceeded. "
                f"Wait for some tasks to complete or increase limit."
            )

        # Generate unique task ID
        task_id = self._generate_task_id()

        # Create task metadata
        task_meta = ToolTask(
            task_id=task_id,
            tool_name=tool_name,
            params=params,
            timeout_seconds=timeout or self.default_timeout
        )
        self.task_metadata[task_id] = task_meta

        # Create asyncio task
        async_task = asyncio.create_task(self._execute_tool(task_id))
        self.pending_calls[task_id] = async_task

        # Update stats
        self.stats["total_invocations"] += 1

        return task_id

    async def _execute_tool(self, task_id: str):
        """
        Background task execution

        Args:
            task_id: Unique task identifier
        """
        task_meta = self.task_metadata[task_id]

        try:
            # Update status
            task_meta.status = TaskStatus.RUNNING
            task_meta.started_at = datetime.now()

            # Execute tool with timeout
            if self.tool_executor is None:
                raise RuntimeError("Tool executor not set. Call set_tool_executor() first.")

            result = await asyncio.wait_for(
                self.tool_executor(task_meta.tool_name, task_meta.params),
                timeout=task_meta.timeout_seconds
            )

            # Success
            task_meta.status = TaskStatus.COMPLETED
            task_meta.result = result
            task_meta.completed_at = datetime.now()

            # Update stats
            self.stats["completed"] += 1
            duration = (task_meta.completed_at - task_meta.started_at).total_seconds()
            self._update_avg_duration(duration)

        except asyncio.TimeoutError:
            # Timeout
            task_meta.status = TaskStatus.TIMEOUT
            task_meta.error = f"Tool execution exceeded {task_meta.timeout_seconds}s timeout"
            task_meta.completed_at = datetime.now()
            self.stats["timeout"] += 1

        except asyncio.CancelledError:
            # Cancelled
            task_meta.status = TaskStatus.CANCELLED
            task_meta.error = "Tool execution was cancelled"
            task_meta.completed_at = datetime.now()
            self.stats["cancelled"] += 1
            raise  # Re-raise to propagate cancellation

        except Exception as e:
            # Error
            task_meta.status = TaskStatus.FAILED
            task_meta.error = str(e)
            task_meta.completed_at = datetime.now()
            self.stats["failed"] += 1

        finally:
            # Post result to event queue
            await self.event_queue.put(task_meta.to_dict())

            # Cleanup
            if task_id in self.pending_calls:
                del self.pending_calls[task_id]

    async def check_results(self, block: bool = False, timeout: float = 0.1) -> List[Dict[str, Any]]:
        """
        Non-blocking check for completed tasks

        Args:
            block: If True, wait for at least one result (up to timeout)
            timeout: Max time to wait if blocking (seconds)

        Returns:
            List of completed task results (empty if none ready)
        """
        results = []

        if block:
            # Wait for at least one result
            try:
                result = await asyncio.wait_for(
                    self.event_queue.get(),
                    timeout=timeout
                )
                results.append(result)
            except asyncio.TimeoutError:
                logger.debug("Suppressed Exception in async_tool_executor")
                pass  # No results within timeout

        # Drain any additional ready results (non-blocking)
        while not self.event_queue.empty():
            try:
                result = self.event_queue.get_nowait()
                results.append(result)
            except asyncio.QueueEmpty:
                break

        return results

    async def wait_for_task(self, task_id: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Wait for a specific task to complete

        Args:
            task_id: Task identifier to wait for
            timeout: Max time to wait (None = use task's timeout)

        Returns:
            Task result dictionary

        Raises:
            asyncio.TimeoutError: If timeout exceeded
            KeyError: If task_id not found
        """
        if task_id not in self.task_metadata:
            raise KeyError(f"Task {task_id} not found")

        task_meta = self.task_metadata[task_id]
        wait_timeout = timeout or task_meta.timeout_seconds

        # Wait for task to complete
        start = time.time()
        while task_meta.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
            if time.time() - start > wait_timeout:
                raise asyncio.TimeoutError(f"Timeout waiting for task {task_id}")

            await asyncio.sleep(0.01)  # Small delay to avoid busy-waiting

        return task_meta.to_dict()

    async def wait_for_all(
        self,
        task_ids: Optional[List[str]] = None,
        timeout: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Wait for multiple tasks to complete

        Args:
            task_ids: List of task IDs to wait for (None = all pending tasks)
            timeout: Max time to wait (None = no limit)

        Returns:
            List of task results

        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        if task_ids is None:
            task_ids = list(self.pending_calls.keys())

        results = []
        start = time.time()

        for task_id in task_ids:
            if timeout is not None:
                remaining = timeout - (time.time() - start)
                if remaining <= 0:
                    raise asyncio.TimeoutError("Timeout waiting for all tasks")
                task_timeout = remaining
            else:
                task_timeout = None

            result = await self.wait_for_task(task_id, timeout=task_timeout)
            results.append(result)

        return results

    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a pending task

        Args:
            task_id: Task identifier to cancel

        Returns:
            True if task was cancelled, False if already completed
        """
        if task_id not in self.pending_calls:
            return False  # Already completed or doesn't exist

        async_task = self.pending_calls[task_id]
        async_task.cancel()

        try:
            await async_task
        except asyncio.CancelledError:
            logger.debug("Suppressed Exception in async_tool_executor")
            pass

        return True

    async def cancel_all(self):
        """Cancel all pending tasks"""
        task_ids = list(self.pending_calls.keys())
        for task_id in task_ids:
            await self.cancel_task(task_id)

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """
        Get list of pending tasks

        Returns:
            List of pending task metadata
        """
        return [
            meta.to_dict()
            for task_id, meta in self.task_metadata.items()
            if meta.status in [TaskStatus.PENDING, TaskStatus.RUNNING]
        ]

    def get_stats(self) -> Dict[str, Any]:
        """
        Get execution statistics

        Returns:
            Dictionary of stats
        """
        stats = self.stats.copy()
        stats["pending"] = len(self.pending_calls)
        stats["queued_results"] = self.event_queue.qsize()
        return stats

    def _generate_task_id(self) -> str:
        """Generate unique task ID"""
        return f"task_{uuid.uuid4().hex[:12]}"

    def _update_avg_duration(self, new_duration: float):
        """Update rolling average duration"""
        completed = self.stats["completed"]
        if completed == 1:
            self.stats["avg_duration"] = new_duration
        else:
            # Exponential moving average
            alpha = 0.2
            self.stats["avg_duration"] = (
                alpha * new_duration +
                (1 - alpha) * self.stats["avg_duration"]
            )

    async def cleanup(self):
        """Cleanup resources (call on shutdown)"""
        await self.cancel_all()

        # Drain event queue
        while not self.event_queue.empty():
            try:
                self.event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break


# Example usage and testing
async def example_tool_executor(tool_name: str, params: Dict[str, Any]) -> Any:
    """
    Example tool executor for testing
    Simulates tool execution with variable delays
    """
    # Simulate different tool execution times
    delays = {
        "gmail_search": 0.5,
        "drive_search": 0.8,
        "calendar_search": 0.3,
        "slow_tool": 5.0
    }

    delay = delays.get(tool_name, 0.5)
    await asyncio.sleep(delay)

    return {
        "tool": tool_name,
        "params": params,
        "result": f"Simulated result for {tool_name}",
        "delay": delay
    }


async def run_example():
    """Example usage of AsyncToolExecutor"""
    print("=== Async Tool Executor Example ===\n")

    # Create executor
    executor = AsyncToolExecutor(default_timeout=10.0, max_concurrent=5)
    executor.set_tool_executor(example_tool_executor)

    # Example 1: Parallel execution
    print("Example 1: Parallel tool execution")
    print("-" * 40)

    start = time.time()

    # Launch 3 tools in parallel
    task1 = await executor.invoke_tool("gmail_search", {"query": "important"})
    task2 = await executor.invoke_tool("drive_search", {"query": "Q4 report"})
    task3 = await executor.invoke_tool("calendar_search", {"date": "tomorrow"})

    print(f"Tasks launched: {task1}, {task2}, {task3}")
    print(f"Launch time: {time.time() - start:.3f}s (should be <0.01s)\n")

    # Wait for all results
    all_results = await executor.wait_for_all([task1, task2, task3])

    elapsed = time.time() - start
    print(f"All results received in {elapsed:.3f}s")
    print(f"Speedup: ~{(0.5 + 0.8 + 0.3) / elapsed:.1f}× (parallel vs sequential)\n")

    for result in all_results:
        print(f"  {result.get('task_id', '')}: {result.get('status', '')} ({result.get('elapsed_seconds', ''):.3f}s)")

    # Example 2: Non-blocking check
    print("\n\nExample 2: Non-blocking result checking")
    print("-" * 40)

    task4 = await executor.invoke_tool("gmail_search", {"query": "test"})
    print(f"Task launched: {task4}")

    # Check immediately (should be empty)
    results = await executor.check_results(block=False)
    print(f"Immediate check: {len(results)} results (expected 0)")

    # Wait a bit
    await asyncio.sleep(0.6)

    # Check again (should have result)
    results = await executor.check_results(block=False)
    print(f"After 0.6s: {len(results)} results (expected 1)")

    # Example 3: Statistics
    print("\n\nExample 3: Execution statistics")
    print("-" * 40)
    stats = executor.get_stats()
    print(f"Total invocations: {stats['total_invocations']}")
    print(f"Completed: {stats['completed']}")
    logger.error(f"Failed: {stats['failed']}")
    print(f"Average duration: {stats['avg_duration']:.3f}s")
    print(f"Pending: {stats['pending']}")

    # Cleanup
    await executor.cleanup()
    print("\n✅ Executor cleaned up")


if __name__ == "__main__":
    # Run example
    asyncio.run(run_example())
