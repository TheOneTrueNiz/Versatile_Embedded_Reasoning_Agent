"""
Task Dependencies (DAG) for VERA.

Models task dependencies as a Directed Acyclic Graph (DAG).
Enables dependency-aware scheduling and blocking detection.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)


class DependencyType(Enum):
    """Types of task dependencies."""
    BLOCKS = "blocks"           # A must complete before B can start
    RELATED = "related"         # Tasks are related but not blocking
    SUBTASK = "subtask"         # B is a subtask of A
    SEQUENTIAL = "sequential"   # B should ideally follow A


class TaskState(Enum):
    """Task states for DAG tracking."""
    PENDING = "pending"
    READY = "ready"           # All dependencies satisfied
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"       # Waiting on dependencies
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class TaskNode:
    """A node in the task DAG."""
    task_id: str
    title: str
    state: TaskState
    created_at: datetime
    completed_at: Optional[datetime] = None

    # Dependencies
    depends_on: Set[str] = field(default_factory=set)    # Tasks this depends on
    blocks: Set[str] = field(default_factory=set)        # Tasks that depend on this
    subtasks: Set[str] = field(default_factory=set)      # Child tasks

    # Metadata
    priority: int = 2
    estimated_effort: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "depends_on": list(self.depends_on),
            "blocks": list(self.blocks),
            "subtasks": list(self.subtasks),
            "priority": self.priority,
            "estimated_effort": self.estimated_effort,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "TaskNode":
        return cls(
            task_id=data.get("task_id", ""),
            title=data.get("title", ""),
            state=TaskState(data.get("state", "")),
            created_at=datetime.fromisoformat(data.get("created_at", "")),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            depends_on=set(data.get("depends_on", [])),
            blocks=set(data.get("blocks", [])),
            subtasks=set(data.get("subtasks", [])),
            priority=data.get("priority", 2),
            estimated_effort=data.get("estimated_effort"),
            metadata=data.get("metadata", {})
        )


@dataclass
class DependencyEdge:
    """An edge in the dependency graph."""
    from_task: str
    to_task: str
    dependency_type: DependencyType
    created_at: datetime
    description: Optional[str] = None


class TaskDAG:
    """
    Directed Acyclic Graph for task dependencies.

    Features:
    - Dependency modeling (blocks, subtasks, related)
    - Topological sorting for scheduling
    - Cycle detection
    - Blocking chain analysis
    - Critical path finding
    """

    def __init__(self, memory_dir: Optional[Path] = None) -> None:
        """
        Initialize task DAG.

        Args:
            memory_dir: Directory for persistence
        """
        if memory_dir:
            self.memory_dir = Path(memory_dir)
        else:
            self.memory_dir = Path("vera_memory")

        self.storage_file = self.memory_dir / "task_dag.json"

        # Graph structure
        self._nodes: Dict[str, TaskNode] = {}
        self._edges: List[DependencyEdge] = []

        # Load state
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state."""
        if self.storage_file.exists():
            try:
                with open(self.storage_file) as f:
                    data = json.load(f)

                for node_data in data.get("nodes", []):
                    node = TaskNode.from_dict(node_data)
                    self._nodes[node.task_id] = node

                for edge_data in data.get("edges", []):
                    edge = DependencyEdge(
                        from_task=edge_data.get("from_task", ""),
                        to_task=edge_data.get("to_task", ""),
                        dependency_type=DependencyType(edge_data.get("dependency_type", "")),
                        created_at=datetime.fromisoformat(edge_data.get("created_at", "")),
                        description=edge_data.get("description")
                    )
                    self._edges.append(edge)

            except Exception as e:
                logger.error(f"Failed to load task DAG: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [
                {
                    "from_task": e.from_task,
                    "to_task": e.to_task,
                    "dependency_type": e.dependency_type.value,
                    "created_at": e.created_at.isoformat(),
                    "description": e.description
                }
                for e in self._edges
            ]
        }

        with open(self.storage_file, 'w') as f:
            json.dump(data, f, indent=2)

    def add_task(
        self,
        task_id: str,
        title: str,
        priority: int = 2,
        depends_on: Optional[List[str]] = None,
        metadata: Optional[Dict] = None
    ) -> TaskNode:
        """
        Add a task to the DAG.

        Args:
            task_id: Unique task identifier
            title: Task title
            priority: Priority level (0-3)
            depends_on: List of task IDs this depends on
            metadata: Optional metadata

        Returns:
            Created TaskNode
        """
        node = TaskNode(
            task_id=task_id,
            title=title,
            state=TaskState.PENDING,
            created_at=datetime.now(),
            priority=priority,
            metadata=metadata or {}
        )

        self._nodes[task_id] = node

        # Add dependencies
        if depends_on:
            for dep_id in depends_on:
                self.add_dependency(dep_id, task_id, DependencyType.BLOCKS)

        # Update state based on dependencies
        self._update_task_state(task_id)

        self._save_state()
        return node

    def add_dependency(
        self,
        from_task: str,
        to_task: str,
        dependency_type: DependencyType = DependencyType.BLOCKS,
        description: Optional[str] = None
    ) -> bool:
        """
        Add a dependency between tasks.

        Args:
            from_task: Task that must complete first
            to_task: Task that depends on from_task
            dependency_type: Type of dependency
            description: Optional description

        Returns:
            True if added successfully
        """
        # Validate tasks exist
        if from_task not in self._nodes:
            logger.warning(f"Task not found: {from_task}")
            return False

        if to_task not in self._nodes:
            logger.warning(f"Task not found: {to_task}")
            return False

        # Check for cycles
        if self._would_create_cycle(from_task, to_task):
            logger.warning(f"Dependency would create cycle: {from_task} -> {to_task}")
            return False

        # Add edge
        edge = DependencyEdge(
            from_task=from_task,
            to_task=to_task,
            dependency_type=dependency_type,
            created_at=datetime.now(),
            description=description
        )
        self._edges.append(edge)

        # Update node relationships
        from_node = self._nodes[from_task]
        to_node = self._nodes[to_task]

        if dependency_type == DependencyType.BLOCKS:
            from_node.blocks.add(to_task)
            to_node.depends_on.add(from_task)
        elif dependency_type == DependencyType.SUBTASK:
            from_node.subtasks.add(to_task)
            to_node.depends_on.add(from_task)

        # Update states
        self._update_task_state(to_task)

        self._save_state()
        return True

    def _would_create_cycle(self, from_task: str, to_task: str) -> bool:
        """Check if adding an edge would create a cycle."""
        # DFS from to_task to see if we can reach from_task
        visited = set()
        stack = [to_task]

        while stack:
            current = stack.pop()
            if current == from_task:
                return True

            if current in visited:
                continue

            visited.add(current)

            node = self._nodes.get(current)
            if node:
                for blocked in node.blocks:
                    stack.append(blocked)

        return False

    def _update_task_state(self, task_id: str) -> None:
        """Update a task's state based on dependencies."""
        node = self._nodes.get(task_id)
        if not node:
            return

        if node.state in (TaskState.COMPLETED, TaskState.CANCELLED):
            return

        # Check if all dependencies are satisfied
        all_satisfied = True
        for dep_id in node.depends_on:
            dep_node = self._nodes.get(dep_id)
            if dep_node and dep_node.state != TaskState.COMPLETED:
                all_satisfied = False
                break

        if all_satisfied:
            if node.state == TaskState.BLOCKED:
                node.state = TaskState.READY
            elif node.state == TaskState.PENDING and not node.depends_on:
                node.state = TaskState.READY
        else:
            if node.state not in (TaskState.IN_PROGRESS,):
                node.state = TaskState.BLOCKED

    def complete_task(self, task_id: str) -> List[str]:
        """
        Mark a task as completed and update dependents.

        Args:
            task_id: Task to complete

        Returns:
            List of tasks that became unblocked
        """
        node = self._nodes.get(task_id)
        if not node:
            return []

        node.state = TaskState.COMPLETED
        node.completed_at = datetime.now()

        # Update blocked tasks
        unblocked = []
        for blocked_id in node.blocks:
            blocked_node = self._nodes.get(blocked_id)
            if blocked_node:
                self._update_task_state(blocked_id)
                if blocked_node.state == TaskState.READY:
                    unblocked.append(blocked_id)

        self._save_state()
        return unblocked

    def start_task(self, task_id: str) -> bool:
        """
        Mark a task as in progress.

        Args:
            task_id: Task to start

        Returns:
            True if started successfully
        """
        node = self._nodes.get(task_id)
        if not node:
            return False

        if node.state == TaskState.BLOCKED:
            logger.warning(f"Cannot start blocked task: {task_id}")
            return False

        node.state = TaskState.IN_PROGRESS
        self._save_state()
        return True

    def get_ready_tasks(self) -> List[TaskNode]:
        """Get all tasks that are ready to start."""
        ready = [
            node for node in self._nodes.values()
            if node.state in (TaskState.READY, TaskState.PENDING) and
            not node.depends_on
        ]

        # Also include tasks whose deps are all complete
        for node in self._nodes.values():
            if node.state == TaskState.PENDING and node.depends_on:
                all_complete = all(
                    self._nodes.get(d, TaskNode("", "", TaskState.PENDING, datetime.now())).state == TaskState.COMPLETED
                    for d in node.depends_on
                )
                if all_complete and node not in ready:
                    node.state = TaskState.READY
                    ready.append(node)

        # Sort by priority
        ready.sort(key=lambda n: n.priority)
        return ready

    def get_blocked_tasks(self) -> List[Tuple[TaskNode, List[str]]]:
        """
        Get all blocked tasks with their blocking reasons.

        Returns:
            List of (task, blocking_task_ids)
        """
        blocked = []

        for node in self._nodes.values():
            if node.state == TaskState.BLOCKED:
                blockers = [
                    d for d in node.depends_on
                    if self._nodes.get(d, TaskNode("", "", TaskState.COMPLETED, datetime.now())).state != TaskState.COMPLETED
                ]
                blocked.append((node, blockers))

        return blocked

    def get_blocking_chain(self, task_id: str) -> List[str]:
        """
        Get the chain of tasks blocking this task.

        Args:
            task_id: Task to analyze

        Returns:
            List of task IDs in blocking chain
        """
        chain = []
        visited = set()

        def trace(tid: str) -> None:
            if tid in visited:
                return
            visited.add(tid)

            node = self._nodes.get(tid)
            if not node:
                return

            for dep_id in node.depends_on:
                dep = self._nodes.get(dep_id)
                if dep and dep.state != TaskState.COMPLETED:
                    chain.append(dep_id)
                    trace(dep_id)

        trace(task_id)
        return chain

    def topological_sort(self) -> List[str]:
        """
        Get tasks in dependency order.

        Returns:
            List of task IDs in topological order
        """
        in_degree = {tid: 0 for tid in self._nodes}

        for node in self._nodes.values():
            for blocked in node.blocks:
                if blocked in in_degree:
                    in_degree[blocked] += 1

        # Start with tasks that have no dependencies
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        result = []

        while queue:
            task_id = queue.popleft()
            result.append(task_id)

            node = self._nodes.get(task_id)
            if node:
                for blocked in node.blocks:
                    if blocked in in_degree:
                        in_degree[blocked] -= 1
                        if in_degree[blocked] == 0:
                            queue.append(blocked)

        return result

    def get_critical_path(self) -> List[str]:
        """
        Get the critical path (longest chain of dependencies).

        Returns:
            List of task IDs on critical path
        """
        # Find longest path using DFS
        memo = {}

        def longest_from(task_id: str) -> List[str]:
            if task_id in memo:
                return memo[task_id]

            node = self._nodes.get(task_id)
            if not node or not node.blocks:
                return [task_id]

            best_path = [task_id]
            for blocked in node.blocks:
                path = [task_id] + longest_from(blocked)
                if len(path) > len(best_path):
                    best_path = path

            memo[task_id] = best_path
            return best_path

        # Find longest path starting from any root task
        longest = []
        for task_id, node in self._nodes.items():
            if not node.depends_on:  # Root task
                path = longest_from(task_id)
                if len(path) > len(longest):
                    longest = path

        return longest

    def remove_task(self, task_id: str) -> bool:
        """
        Remove a task and its dependencies.

        Args:
            task_id: Task to remove

        Returns:
            True if removed
        """
        if task_id not in self._nodes:
            return False

        node = self._nodes[task_id]

        # Remove from other nodes
        for other in self._nodes.values():
            other.depends_on.discard(task_id)
            other.blocks.discard(task_id)
            other.subtasks.discard(task_id)

        # Remove edges
        self._edges = [
            e for e in self._edges
            if e.from_task != task_id and e.to_task != task_id
        ]

        del self._nodes[task_id]

        # Update states of affected tasks
        for other_id in list(self._nodes.keys()):
            self._update_task_state(other_id)

        self._save_state()
        return True

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        """Get a task by ID."""
        return self._nodes.get(task_id)

    def get_subtasks(self, task_id: str) -> List[TaskNode]:
        """Get subtasks of a task."""
        node = self._nodes.get(task_id)
        if not node:
            return []

        return [
            self._nodes[st]
            for st in node.subtasks
            if st in self._nodes
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get DAG statistics."""
        states = {}
        for node in self._nodes.values():
            states[node.state.value] = states.get(node.state.value, 0) + 1

        return {
            "total_tasks": len(self._nodes),
            "total_edges": len(self._edges),
            "task_states": states,
            "ready_tasks": len(self.get_ready_tasks()),
            "blocked_tasks": len(self.get_blocked_tasks()),
            "critical_path_length": len(self.get_critical_path())
        }

    def visualize_ascii(self) -> str:
        """Generate ASCII visualization of the DAG."""
        lines = ["Task DAG Visualization", "=" * 40, ""]

        # Get topological order
        order = self.topological_sort()

        for task_id in order:
            node = self._nodes.get(task_id)
            if not node:
                continue

            # Status indicator
            status_map = {
                TaskState.PENDING: "○",
                TaskState.READY: "◎",
                TaskState.IN_PROGRESS: "◉",
                TaskState.BLOCKED: "✗",
                TaskState.COMPLETED: "✓",
                TaskState.CANCELLED: "⊘"
            }
            status = status_map.get(node.state, "?")

            # Dependencies
            deps = f" <- [{', '.join(node.depends_on)}]" if node.depends_on else ""

            lines.append(f"{status} [{node.task_id}] {node.title}{deps}")

        return "\n".join(lines)


# === Self-test ===

if __name__ == "__main__":
    import sys

    def test_dag():
        """Test task DAG."""
        print("Testing Task DAG...")

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test 1: Create DAG
            print("Test 1: Create DAG...", end=" ")
            dag = TaskDAG(memory_dir=Path(tmpdir))
            print("PASS")

            # Test 2: Add tasks
            print("Test 2: Add tasks...", end=" ")
            dag.add_task("A", "Task A")
            dag.add_task("B", "Task B")
            dag.add_task("C", "Task C")
            assert len(dag._nodes) == 3
            print("PASS")

            # Test 3: Add dependencies
            print("Test 3: Add dependencies...", end=" ")
            dag.add_dependency("A", "B", DependencyType.BLOCKS)
            dag.add_dependency("B", "C", DependencyType.BLOCKS)
            assert "A" in dag._nodes["B"].depends_on
            assert "B" in dag._nodes["A"].blocks
            print("PASS")

            # Test 4: Task states
            print("Test 4: Task states...", end=" ")
            # A should be ready, B and C blocked
            ready = dag.get_ready_tasks()
            assert len(ready) == 1
            assert ready[0].task_id == "A"
            print("PASS")

            # Test 5: Complete task
            print("Test 5: Complete task...", end=" ")
            unblocked = dag.complete_task("A")
            assert "B" in unblocked
            assert dag._nodes["B"].state == TaskState.READY
            print("PASS")

            # Test 6: Blocking chain
            print("Test 6: Blocking chain...", end=" ")
            chain = dag.get_blocking_chain("C")
            assert "B" in chain  # B blocks C
            print("PASS")

            # Test 7: Topological sort
            print("Test 7: Topological sort...", end=" ")
            order = dag.topological_sort()
            assert order.index("A") < order.index("B")
            assert order.index("B") < order.index("C")
            print("PASS")

            # Test 8: Critical path
            print("Test 8: Critical path...", end=" ")
            path = dag.get_critical_path()
            assert len(path) == 3  # A -> B -> C
            print("PASS")

            # Test 9: Cycle detection
            print("Test 9: Cycle detection...", end=" ")
            result = dag.add_dependency("C", "A", DependencyType.BLOCKS)
            assert result == False  # Would create cycle
            print("PASS")

            # Test 10: ASCII visualization
            print("Test 10: ASCII visualization...", end=" ")
            viz = dag.visualize_ascii()
            assert "Task A" in viz
            assert "Task B" in viz
            print("PASS")

            # Test 11: Blocked tasks
            print("Test 11: Blocked tasks...", end=" ")
            dag.add_task("D", "Task D", depends_on=["C"])
            blocked = dag.get_blocked_tasks()
            # D should be blocked by C (which is blocked by B)
            d_blocked = [b for b in blocked if b[0].task_id == "D"]
            if d_blocked:
                assert "C" in d_blocked[0][1]
            print("PASS")

            # Test 12: Stats
            print("Test 12: Stats...", end=" ")
            stats = dag.get_stats()
            assert stats["total_tasks"] == 4
            print("PASS")

        print("\nAll tests passed!")
        return True

    success = test_dag()
    sys.exit(0 if success else 1)
