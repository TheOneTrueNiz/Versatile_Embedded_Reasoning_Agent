#!/usr/bin/env python3
"""
Master Task List
================

Hard, file-based task list with strict formatting that survives memory failures.

Source: Ported from GROKSTAR's _parse_task_blocks() and add_task_block()

Problem Solved:
- Memory systems are probabilistic - tasks can be "forgotten"
- Context overflow can lose important todos
- For critical tasks, this is unacceptable

Solution:
- Strict markdown format with regex parsing
- vera_memory/MASTER_TODO.md is the source of truth
- Uses atomic writes to prevent corruption
- Neural memory is supplementary; this file is canonical

Usage:
    from master_list import MasterTaskList, TaskPriority, TaskStatus

    # Initialize
    master = MasterTaskList()

    # Add a task
    task = master.add_task(
        title="Review Q4 reports",
        priority=TaskPriority.HIGH,
        description="Full analysis of quarterly performance",
        tags=["work", "quarterly"]
    )

    # Update status
    master.update_status(task.id, TaskStatus.IN_PROGRESS)

    # Get pending tasks
    pending = master.get_pending()

    # Get summary for prompt injection
    summary = master.summarize()
"""

import re
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
import logging
logger = logging.getLogger(__name__)

# Import atomic I/O with transactional support
try:
    from memory.persistence.atomic_io import (
        atomic_write, safe_read,
        FileTransaction, MergeStrategy, ConflictError
    )
    HAS_ATOMIC_IO = True
    HAS_TRANSACTIONS = True
except ImportError:
    try:
        from .atomic_io import atomic_write, safe_read
        HAS_ATOMIC_IO = True
        HAS_TRANSACTIONS = False
        FileTransaction = None
        MergeStrategy = None
        ConflictError = None
    except ImportError:
        HAS_ATOMIC_IO = False
        HAS_TRANSACTIONS = False
        FileTransaction = None
        MergeStrategy = None
        ConflictError = None
        def atomic_write(path, content) -> None:
            Path(path).write_text(content)
        def safe_read(path, default=""):
            try:
                return Path(path).read_text()
            except FileNotFoundError:
                return default


class TaskStatus(Enum):
    """Task status values"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    DEFERRED = "deferred"


class TaskPriority(Enum):
    """Task priority levels"""
    CRITICAL = "P0"  # Do immediately
    HIGH = "P1"      # Do today
    MEDIUM = "P2"    # Do this week
    LOW = "P3"       # Do eventually

    @property
    def sort_order(self) -> int:
        """Lower is higher priority"""
        return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}[self.value]


@dataclass
class Task:
    """A task in the master list"""
    id: str
    title: str
    status: TaskStatus
    priority: TaskPriority
    created: datetime
    updated: datetime
    description: Optional[str] = None
    due: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    line_number: int = 0

    def is_overdue(self) -> bool:
        """Check if task is past due date"""
        if self.due is None:
            return False
        return datetime.now() > self.due and self.status not in [
            TaskStatus.COMPLETED, TaskStatus.CANCELLED
        ]

    def age_days(self) -> int:
        """Get task age in days"""
        return (datetime.now() - self.created).days

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "priority": self.priority.value,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "description": self.description,
            "due": self.due.isoformat() if self.due else None,
            "tags": self.tags,
            "blockers": self.blockers,
            "notes": self.notes,
        }

    def content_hash(self) -> str:
        """Generate content hash for deduplication"""
        content = f"{self.title}|{self.description or ''}|{self.priority.value}"
        return hashlib.md5(content.encode()).hexdigest()[:12]


# =============================================================================
# Three-Way Merge for Concurrent Task List Modifications (Improvement #4)
# =============================================================================

class MarkdownTaskMerger:
    """
    Implements three-way merge for VERA's markdown task list.

    Handles concurrent additions, status updates, and ID collisions.
    Based on transactional_concurrency_management.txt design.

    Merge Logic:
    1. Parse tasks from all three versions (base, ours, theirs)
    2. Identify new, updated, and deleted tasks since base
    3. Merge changes:
       - New tasks from both sides are kept
       - ID collisions on new tasks: 'ours' gets re-indexed
       - Field-level conflicts: 'ours' wins on specific field changes
       - Deleted tasks stay deleted unless modified
    """

    # Use the same regex patterns as MasterTaskList
    TASK_HEADER_PATTERN = re.compile(
        r'^## (TASK-\d+) \[(P[0-3])\] \[(\w+)\] (.+)$'
    )
    FIELD_PATTERN = re.compile(r'^(\w+): (.+)$')
    SEPARATOR = '---'

    def __init__(self) -> None:
        pass

    def merge(self, base_text: str, our_text: str, their_text: str) -> str:
        """
        Perform task-aware three-way merge.

        Args:
            base_text: Original file content when transaction started
            our_text: Our modified version
            their_text: Current file content (modified by others)

        Returns:
            Merged content string
        """
        # Parse tasks from all three versions
        base_tasks = {t.id: t for t in self._parse_tasks(base_text)}
        our_tasks = {t.id: t for t in self._parse_tasks(our_text)}
        their_tasks = {t.id: t for t in self._parse_tasks(their_text)}

        # 1. Identify "Theirs" changes since "Base"
        their_added = {id: t for id, t in their_tasks.items() if id not in base_tasks}
        their_updated = {id: t for id, t in their_tasks.items()
                        if id in base_tasks and self._task_changed(base_tasks[id], t)}
        their_deleted = {id for id in base_tasks if id not in their_tasks}

        # 2. Identify "Ours" changes since "Base"
        our_added = {id: t for id, t in our_tasks.items() if id not in base_tasks}
        our_updated = {id: t for id, t in our_tasks.items()
                      if id in base_tasks and self._task_changed(base_tasks[id], t)}
        our_deleted = {id for id in base_tasks if id not in our_tasks}

        # 3. Start with Theirs as the baseline (it's already in the file)
        merged_tasks_dict = their_tasks.copy()

        # 4. Apply "Our" deletions (only if they didn't modify it)
        for id in our_deleted:
            if id in merged_tasks_dict and id not in their_updated:
                del merged_tasks_dict[id]

        # 5. Apply "Our" updates
        for id, our_t in our_updated.items():
            if id in their_deleted:
                # We updated, they deleted. Re-insert our version.
                merged_tasks_dict[id] = our_t
            elif id in their_updated:
                # Conflict: Both updated. Merge fields (ours wins on conflicts).
                merged_tasks_dict[id] = self._merge_task_fields(
                    base_tasks[id], our_t, their_tasks[id]
                )
            else:
                # They didn't touch it. Our update wins.
                merged_tasks_dict[id] = our_t

        # 6. Apply "Our" additions (Handle ID Collisions)
        final_list = list(merged_tasks_dict.values())
        for id, our_t in our_added.items():
            if id in their_added:
                # ID Collision! If contents differ, re-index ours.
                if our_t.content_hash() != their_added[id].content_hash():
                    new_id = self._generate_unique_id(final_list)
                    our_t.id = new_id
                    our_t.title = f"[MERGE] {our_t.title}"
                    our_t.updated = datetime.now()
                    final_list.append(our_t)
                # else: Identical task added twice. Keep their ID (already in list).
            else:
                final_list.append(our_t)

        # 7. Format and return
        return self._format_task_list(final_list)

    def _task_changed(self, original: Task, current: Task) -> bool:
        """Check if task was modified"""
        return (
            original.title != current.title or
            original.status != current.status or
            original.priority != current.priority or
            original.description != current.description or
            original.due != current.due or
            original.tags != current.tags or
            original.blockers != current.blockers or
            original.notes != current.notes
        )

    def _merge_task_fields(self, base: Task, ours: Task, theirs: Task) -> Task:
        """
        Merge individual task fields. 'Ours' wins on conflicts.

        For each field, if we changed it from base, use our value.
        Otherwise use their value.
        """
        # Start with theirs as baseline
        merged = Task(
            id=theirs.id,
            title=theirs.title,
            status=theirs.status,
            priority=theirs.priority,
            created=theirs.created,
            updated=datetime.now(),
            description=theirs.description,
            due=theirs.due,
            tags=theirs.tags.copy() if theirs.tags else [],
            blockers=theirs.blockers.copy() if theirs.blockers else [],
            notes=theirs.notes
        )

        # If we changed a field since base, our change wins
        if ours.title != base.title:
            merged.title = ours.title
        if ours.status != base.status:
            merged.status = ours.status
        if ours.priority != base.priority:
            merged.priority = ours.priority
        if ours.description != base.description:
            merged.description = ours.description
        if ours.due != base.due:
            merged.due = ours.due
        if ours.tags != base.tags:
            merged.tags = ours.tags
        if ours.blockers != base.blockers:
            merged.blockers = ours.blockers
        if ours.notes != base.notes:
            merged.notes = ours.notes

        return merged

    def _generate_unique_id(self, tasks: List[Task]) -> str:
        """Generate next available task ID"""
        max_id = 0
        for t in tasks:
            try:
                num = int(t.id.split('-')[1])
                max_id = max(max_id, num)
            except (IndexError, ValueError) as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
        return f"TASK-{max_id + 1:03d}"

    def _parse_tasks(self, content: str) -> List[Task]:
        """Parse markdown content into Task objects"""
        if not content:
            return []

        lines = content.split('\n')
        tasks = []
        current_task = None
        current_description_lines = []
        in_description = False

        for i, line in enumerate(lines):
            header_match = self.TASK_HEADER_PATTERN.match(line)

            if header_match:
                if current_task:
                    current_task.description = '\n'.join(current_description_lines).strip() or None
                    tasks.append(current_task)

                task_id, priority, status, title = header_match.groups()

                try:
                    task_status = TaskStatus(status)
                except ValueError:
                    task_status = TaskStatus.PENDING

                try:
                    task_priority = TaskPriority(priority)
                except ValueError:
                    task_priority = TaskPriority.MEDIUM

                current_task = Task(
                    id=task_id,
                    title=title,
                    status=task_status,
                    priority=task_priority,
                    created=datetime.now(),
                    updated=datetime.now(),
                    line_number=i + 1
                )
                current_description_lines = []
                in_description = False
                continue

            if current_task is None:
                continue

            field_match = self.FIELD_PATTERN.match(line)

            if field_match and not in_description:
                field_name, field_value = field_match.groups()
                field_name = field_name.lower()

                if field_name == 'created':
                    try:
                        current_task.created = datetime.fromisoformat(field_value.strip())
                    except ValueError as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
                elif field_name == 'updated':
                    try:
                        current_task.updated = datetime.fromisoformat(field_value.strip())
                    except ValueError as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
                elif field_name == 'due':
                    try:
                        due_str = field_value.strip()
                        if 'T' in due_str:
                            current_task.due = datetime.fromisoformat(due_str)
                        else:
                            current_task.due = datetime.strptime(due_str, "%Y-%m-%d")
                    except ValueError as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
                elif field_name == 'tags':
                    current_task.tags = [t.strip() for t in field_value.split(',') if t.strip()]
                elif field_name == 'blockers':
                    current_task.blockers = [b.strip() for b in field_value.split(',') if b.strip()]
                elif field_name == 'notes':
                    current_task.notes = field_value.strip()
                continue

            if line.strip() == self.SEPARATOR:
                if current_task:
                    current_task.description = '\n'.join(current_description_lines).strip() or None
                    tasks.append(current_task)
                    current_task = None
                    current_description_lines = []
                    in_description = False
                continue

            if line.strip() == '' and current_task and not in_description:
                in_description = True
                continue

            if in_description:
                current_description_lines.append(line)

        if current_task:
            current_task.description = '\n'.join(current_description_lines).strip() or None
            tasks.append(current_task)

        return tasks

    def _format_task_list(self, tasks: List[Task]) -> str:
        """Format tasks back to markdown string"""
        # Sort by ID for deterministic output
        sorted_tasks = sorted(tasks, key=lambda t: t.id)

        # Calculate stats for header
        pending = [t for t in sorted_tasks if t.status == TaskStatus.PENDING]
        overdue = [t for t in sorted_tasks if t.is_overdue()]

        header = f"""# VERA Master Task List

This is the authoritative source of truth for all tasks.
Neural memory is supplementary; this file is canonical.

**Last Updated**: {datetime.now().isoformat()}
**Total Tasks**: {len(sorted_tasks)}
**Pending**: {len(pending)}
**Overdue**: {len(overdue)}

---

"""
        task_strs = []
        for task in sorted_tasks:
            task_strs.append(self._format_single_task(task))

        return header + '\n'.join(task_strs)

    def _format_single_task(self, task: Task) -> str:
        """Format a single task as markdown"""
        lines = [
            f"## {task.id} [{task.priority.value}] [{task.status.value}] {task.title}",
            f"Created: {task.created.isoformat()}",
            f"Updated: {task.updated.isoformat()}",
        ]

        if task.tags:
            lines.append(f"Tags: {', '.join(task.tags)}")
        if task.due:
            lines.append(f"Due: {task.due.strftime('%Y-%m-%d')}")
        if task.blockers:
            lines.append(f"Blockers: {', '.join(task.blockers)}")
        if task.notes:
            lines.append(f"Notes: {task.notes}")

        lines.append("")  # Empty line before description

        if task.description:
            lines.append(task.description)

        lines.append("")
        lines.append(self.SEPARATOR)
        lines.append("")

        return '\n'.join(lines)


class MasterTaskList:
    """
    Hard, file-based task list with regex parsing.

    Format:
    ```markdown
    ## TASK-001 [P1] [pending] Task title here
    Created: 2025-12-25T10:00:00
    Updated: 2025-12-25T10:00:00
    Tags: work, urgent
    Due: 2025-12-31
    Blockers: TASK-002

    Description of the task goes here.
    Can be multiple lines.

    ---
    ```
    """

    # Regex patterns
    TASK_HEADER_PATTERN = re.compile(
        r'^## (TASK-\d+) \[(P[0-3])\] \[(\w+)\] (.+)$'
    )
    FIELD_PATTERN = re.compile(r'^(\w+): (.+)$')
    SEPARATOR = '---'

    # File header template
    FILE_HEADER = """# VERA Master Task List

This is the authoritative source of truth for all tasks.
Neural memory is supplementary; this file is canonical.

**Last Updated**: {timestamp}
**Total Tasks**: {total}
**Pending**: {pending}
**Overdue**: {overdue}

---

"""

    def __init__(self, filepath: Path = None, memory_dir: Path = None, use_transactions: bool = True) -> None:
        """
        Initialize master task list.

        Args:
            filepath: Path to MASTER_TODO.md (optional)
            memory_dir: Base memory directory (optional)
            use_transactions: Whether to use transactional concurrency (default: True)
        """
        if filepath:
            self.filepath = Path(filepath)
        elif memory_dir:
            self.filepath = Path(memory_dir) / "MASTER_TODO.md"
        else:
            self.filepath = Path("vera_memory/MASTER_TODO.md")

        # Initialize three-way merger for concurrent modifications
        self._merger = MarkdownTaskMerger()
        self._use_transactions = use_transactions and HAS_TRANSACTIONS

        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create file with header if it doesn't exist"""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

        if not self.filepath.exists():
            header = self.FILE_HEADER.format(
                timestamp=datetime.now().isoformat(),
                total=0,
                pending=0,
                overdue=0
            )
            atomic_write(self.filepath, header)

    def _next_task_id(self, tasks: List[Task]) -> str:
        """Generate next task ID"""
        if not tasks:
            return "TASK-001"

        max_id = 0
        for task in tasks:
            try:
                num = int(task.id.split('-')[1])
                max_id = max(max_id, num)
            except (IndexError, ValueError) as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

        return f"TASK-{max_id + 1:03d}"

    def parse(self) -> List[Task]:
        """
        Parse the master list file into Task objects.

        Returns:
            List of Task objects
        """
        content = safe_read(self.filepath, "")
        if not content:
            return []

        lines = content.split('\n')
        tasks = []
        current_task = None
        current_description_lines = []
        in_description = False

        for i, line in enumerate(lines):
            # Check for task header
            header_match = self.TASK_HEADER_PATTERN.match(line)

            if header_match:
                # Save previous task if exists
                if current_task:
                    current_task.description = '\n'.join(current_description_lines).strip() or None
                    tasks.append(current_task)

                # Start new task
                task_id, priority, status, title = header_match.groups()

                try:
                    task_status = TaskStatus(status)
                except ValueError:
                    task_status = TaskStatus.PENDING

                try:
                    task_priority = TaskPriority(priority)
                except ValueError:
                    task_priority = TaskPriority.MEDIUM

                current_task = Task(
                    id=task_id,
                    title=title,
                    status=task_status,
                    priority=task_priority,
                    created=datetime.now(),
                    updated=datetime.now(),
                    line_number=i + 1
                )
                current_description_lines = []
                in_description = False
                continue

            if current_task is None:
                continue

            # Check for field
            field_match = self.FIELD_PATTERN.match(line)

            if field_match and not in_description:
                field_name, field_value = field_match.groups()
                field_name = field_name.lower()

                if field_name == 'created':
                    try:
                        current_task.created = datetime.fromisoformat(field_value.strip())
                    except ValueError as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
                elif field_name == 'updated':
                    try:
                        current_task.updated = datetime.fromisoformat(field_value.strip())
                    except ValueError as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
                elif field_name == 'due':
                    try:
                        # Support both date and datetime
                        due_str = field_value.strip()
                        if 'T' in due_str:
                            current_task.due = datetime.fromisoformat(due_str)
                        else:
                            current_task.due = datetime.strptime(due_str, "%Y-%m-%d")
                    except ValueError as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
                elif field_name == 'tags':
                    current_task.tags = [t.strip() for t in field_value.split(',') if t.strip()]
                elif field_name == 'blockers':
                    current_task.blockers = [b.strip() for b in field_value.split(',') if b.strip()]
                elif field_name == 'notes':
                    current_task.notes = field_value.strip()
                continue

            # Check for separator (end of task)
            if line.strip() == self.SEPARATOR:
                if current_task:
                    current_task.description = '\n'.join(current_description_lines).strip() or None
                    tasks.append(current_task)
                    current_task = None
                    current_description_lines = []
                    in_description = False
                continue

            # Empty line before description starts the description section
            if line.strip() == '' and current_task and not in_description:
                in_description = True
                continue

            # Collect description lines
            if in_description:
                current_description_lines.append(line)

        # Don't forget last task
        if current_task:
            current_task.description = '\n'.join(current_description_lines).strip() or None
            tasks.append(current_task)

        return tasks

    def _format_task(self, task: Task) -> str:
        """Format a task as markdown"""
        lines = [
            f"## {task.id} [{task.priority.value}] [{task.status.value}] {task.title}",
            f"Created: {task.created.isoformat()}",
            f"Updated: {task.updated.isoformat()}",
        ]

        if task.tags:
            lines.append(f"Tags: {', '.join(task.tags)}")

        if task.due:
            lines.append(f"Due: {task.due.strftime('%Y-%m-%d')}")

        if task.blockers:
            lines.append(f"Blockers: {', '.join(task.blockers)}")

        if task.notes:
            lines.append(f"Notes: {task.notes}")

        lines.append("")  # Empty line before description

        if task.description:
            lines.append(task.description)

        lines.append("")
        lines.append(self.SEPARATOR)
        lines.append("")

        return '\n'.join(lines)

    def save(self, tasks: List[Task]) -> None:
        """
        Save tasks to file atomically.

        Args:
            tasks: List of tasks to save
        """
        # Calculate stats
        pending = [t for t in tasks if t.status == TaskStatus.PENDING]
        overdue = [t for t in tasks if t.is_overdue()]

        header = self.FILE_HEADER.format(
            timestamp=datetime.now().isoformat(),
            total=len(tasks),
            pending=len(pending),
            overdue=len(overdue)
        )

        content = header + '\n'.join(self._format_task(t) for t in tasks)
        atomic_write(self.filepath, content)

    def _transactional_save(self, tasks: List[Task]) -> bool:
        """
        Save tasks using transactional three-way merge.

        Returns True if save succeeded, False if conflict couldn't be resolved.
        """
        if not self._use_transactions:
            self.save(tasks)
            return True

        # Format our version
        pending = [t for t in tasks if t.status == TaskStatus.PENDING]
        overdue = [t for t in tasks if t.is_overdue()]

        header = self.FILE_HEADER.format(
            timestamp=datetime.now().isoformat(),
            total=len(tasks),
            pending=len(pending),
            overdue=len(overdue)
        )
        our_content = header + '\n'.join(self._format_task(t) for t in tasks)

        # Use transaction with custom merge
        try:
            with FileTransaction(
                self.filepath,
                merge_strategy=MergeStrategy.CUSTOM,
                custom_merge=self._merger.merge,
                max_retries=3,
                retry_delay=0.1
            ) as tx:
                # Read current state (captured at transaction start)
                _ = tx.read()  # This sets the base snapshot
                # Write our changes
                tx.write(our_content)
            return True
        except ConflictError:
            # Conflict couldn't be resolved even with merger
            return False
        except Exception:
            # Fall back to simple save on any error
            self.save(tasks)
            return True

    def add_task(
        self,
        title: str,
        priority: TaskPriority = None,
        description: str = None,
        due: datetime = None,
        tags: List[str] = None,
        blockers: List[str] = None,
        notes: str = None
    ) -> Task:
        """
        Add a new task to the list.

        Uses transactional concurrency to handle concurrent additions.
        ID collisions are automatically resolved via three-way merge.

        Args:
            title: Task title
            priority: Task priority (P0-P3)
            description: Detailed description
            due: Due date
            tags: List of tags
            blockers: List of blocking task IDs
            notes: Additional notes

        Returns:
            Created Task object
        """
        tasks = self.parse()
        now = datetime.now()

        new_task = Task(
            id=self._next_task_id(tasks),
            title=title,
            status=TaskStatus.PENDING,
            priority=priority or TaskPriority.MEDIUM,
            created=now,
            updated=now,
            description=description,
            due=due,
            tags=tags or [],
            blockers=blockers or [],
            notes=notes
        )

        tasks.append(new_task)
        self._transactional_save(tasks)

        return new_task

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        notes: str = None
    ) -> Optional[Task]:
        """
        Update a task's status.

        Uses transactional concurrency to handle concurrent updates.

        Args:
            task_id: Task ID (e.g., "TASK-001")
            status: New status
            notes: Optional notes about the status change

        Returns:
            Updated Task or None if not found
        """
        tasks = self.parse()

        for task in tasks:
            if task.id == task_id:
                task.status = status
                task.updated = datetime.now()
                if notes:
                    task.notes = notes
                self._transactional_save(tasks)
                return task

        return None

    def update_task(
        self,
        task_id: str,
        title: str = None,
        priority: TaskPriority = None,
        description: str = None,
        due: datetime = None,
        tags: List[str] = None,
        blockers: List[str] = None,
        notes: str = None
    ) -> Optional[Task]:
        """
        Update any task fields.

        Uses transactional concurrency to handle concurrent updates.

        Args:
            task_id: Task ID
            **fields: Fields to update

        Returns:
            Updated Task or None if not found
        """
        tasks = self.parse()

        for task in tasks:
            if task.id == task_id:
                if title is not None:
                    task.title = title
                if priority is not None:
                    task.priority = priority
                if description is not None:
                    task.description = description
                if due is not None:
                    task.due = due
                if tags is not None:
                    task.tags = tags
                if blockers is not None:
                    task.blockers = blockers
                if notes is not None:
                    task.notes = notes

                task.updated = datetime.now()
                self._transactional_save(tasks)
                return task

        return None

    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task from the list.

        Uses transactional concurrency to handle concurrent deletions.

        Args:
            task_id: Task ID to delete

        Returns:
            True if deleted, False if not found
        """
        tasks = self.parse()
        original_count = len(tasks)

        tasks = [t for t in tasks if t.id != task_id]

        if len(tasks) < original_count:
            self._transactional_save(tasks)
            return True

        return False

    def get_by_id(self, task_id: str) -> Optional[Task]:
        """Get a specific task by ID"""
        tasks = self.parse()
        for task in tasks:
            if task.id == task_id:
                return task
        return None

    def get_pending(self) -> List[Task]:
        """Get all pending tasks, sorted by priority then due date"""
        tasks = self.parse()
        pending = [t for t in tasks if t.status == TaskStatus.PENDING]

        return sorted(pending, key=lambda t: (
            t.priority.sort_order,
            t.due or datetime.max
        ))

    def get_in_progress(self) -> List[Task]:
        """Get all in-progress tasks"""
        tasks = self.parse()
        return [t for t in tasks if t.status == TaskStatus.IN_PROGRESS]

    def get_overdue(self) -> List[Task]:
        """Get all overdue tasks"""
        tasks = self.parse()
        return [t for t in tasks if t.is_overdue()]

    def get_by_tag(self, tag: str) -> List[Task]:
        """Get all tasks with a specific tag"""
        tasks = self.parse()
        return [t for t in tasks if tag in t.tags]

    def get_blocked(self) -> List[Task]:
        """Get all blocked tasks with their blockers"""
        tasks = self.parse()
        return [t for t in tasks if t.status == TaskStatus.BLOCKED or t.blockers]

    def summarize(self, max_per_section: int = 5) -> str:
        """
        Generate a summary for prompt injection.

        Args:
            max_per_section: Max tasks to show per section

        Returns:
            Markdown summary
        """
        tasks = self.parse()

        by_status = {}
        for task in tasks:
            by_status.setdefault(task.status, []).append(task)

        lines = [
            f"## Master Task List Summary",
            f"**Total**: {len(tasks)} tasks",
            ""
        ]

        # Overdue (always show)
        overdue = self.get_overdue()
        if overdue:
            lines.append(f"### OVERDUE ({len(overdue)})")
            for task in sorted(overdue, key=lambda t: t.due)[:max_per_section]:
                days_overdue = (datetime.now() - task.due).days
                lines.append(f"- [{task.priority.value}] **{task.id}**: {task.title} ({days_overdue}d overdue)")
            if len(overdue) > max_per_section:
                lines.append(f"- ... and {len(overdue) - max_per_section} more")
            lines.append("")

        # In Progress
        in_progress = by_status.get(TaskStatus.IN_PROGRESS, [])
        if in_progress:
            lines.append(f"### In Progress ({len(in_progress)})")
            for task in sorted(in_progress, key=lambda t: t.priority.sort_order)[:max_per_section]:
                lines.append(f"- [{task.priority.value}] **{task.id}**: {task.title}")
            if len(in_progress) > max_per_section:
                lines.append(f"- ... and {len(in_progress) - max_per_section} more")
            lines.append("")

        # Pending (top priority)
        pending = by_status.get(TaskStatus.PENDING, [])
        if pending:
            pending = sorted(pending, key=lambda t: (t.priority.sort_order, t.due or datetime.max))
            lines.append(f"### Pending ({len(pending)})")
            for task in pending[:max_per_section]:
                due_str = f" (due {task.due.strftime('%m/%d')})" if task.due else ""
                lines.append(f"- [{task.priority.value}] **{task.id}**: {task.title}{due_str}")
            if len(pending) > max_per_section:
                lines.append(f"- ... and {len(pending) - max_per_section} more")
            lines.append("")

        # Blocked
        blocked = by_status.get(TaskStatus.BLOCKED, [])
        if blocked:
            lines.append(f"### Blocked ({len(blocked)})")
            for task in blocked[:max_per_section]:
                blocker_str = f" (by: {', '.join(task.blockers)})" if task.blockers else ""
                lines.append(f"- **{task.id}**: {task.title}{blocker_str}")
            lines.append("")

        # Recently completed (last 7 days)
        completed = by_status.get(TaskStatus.COMPLETED, [])
        recent_completed = [t for t in completed if t.age_days() < 7]
        if recent_completed:
            lines.append(f"### Recently Completed ({len(recent_completed)} in 7 days)")
            for task in sorted(recent_completed, key=lambda t: t.updated, reverse=True)[:3]:
                lines.append(f"- ~~{task.id}: {task.title}~~")
            lines.append("")

        return '\n'.join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Get task statistics"""
        tasks = self.parse()

        by_status = {}
        by_priority = {}

        for task in tasks:
            by_status[task.status.value] = by_status.get(task.status.value, 0) + 1
            by_priority[task.priority.value] = by_priority.get(task.priority.value, 0) + 1

        return {
            "total": len(tasks),
            "by_status": by_status,
            "by_priority": by_priority,
            "overdue": len(self.get_overdue()),
            "pending": len([t for t in tasks if t.status == TaskStatus.PENDING]),
            "in_progress": len([t for t in tasks if t.status == TaskStatus.IN_PROGRESS]),
            "completed": len([t for t in tasks if t.status == TaskStatus.COMPLETED]),
        }


# === CLI Interface ===

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("Master Task List - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "MASTER_TODO.md"
        master = MasterTaskList(filepath=test_file)

        # Test 1: Add tasks
        print("\n=== Test 1: Add Tasks ===")
        task1 = master.add_task(
            title="Review Q4 reports",
            priority=TaskPriority.HIGH,
            description="Analyze quarterly performance metrics",
            tags=["work", "quarterly"],
            due=datetime.now() + timedelta(days=7)
        )
        print(f"   Created: {task1.id} - {task1.title}")

        task2 = master.add_task(
            title="Fix critical bug",
            priority=TaskPriority.CRITICAL,
            description="Production issue affecting users"
        )
        print(f"   Created: {task2.id} - {task2.title}")

        task3 = master.add_task(
            title="Update documentation",
            priority=TaskPriority.LOW,
            tags=["docs"]
        )
        print(f"   Created: {task3.id} - {task3.title}")
        print("   Result: PASS")

        # Test 2: Parse tasks
        print("\n=== Test 2: Parse Tasks ===")
        tasks = master.parse()
        assert len(tasks) == 3, f"Expected 3 tasks, got {len(tasks)}"
        print(f"   Parsed {len(tasks)} tasks")
        for t in tasks:
            print(f"   - {t.id}: {t.title} [{t.priority.value}] [{t.status.value}]")
        print("   Result: PASS")

        # Test 3: Update status
        print("\n=== Test 3: Update Status ===")
        updated = master.update_status(task2.id, TaskStatus.IN_PROGRESS)
        assert updated is not None
        assert updated.status == TaskStatus.IN_PROGRESS
        print(f"   Updated {task2.id} to IN_PROGRESS")
        print("   Result: PASS")

        # Test 4: Get pending (sorted by priority)
        print("\n=== Test 4: Get Pending (Priority Sorted) ===")
        pending = master.get_pending()
        assert len(pending) == 2  # task1 and task3 (task2 is in_progress)
        assert pending[0].priority.value == "P1"  # HIGH comes before LOW
        print(f"   Got {len(pending)} pending tasks")
        for t in pending:
            print(f"   - [{t.priority.value}] {t.title}")
        print("   Result: PASS")

        # Test 5: Get by tag
        print("\n=== Test 5: Get By Tag ===")
        work_tasks = master.get_by_tag("work")
        assert len(work_tasks) == 1
        print(f"   Found {len(work_tasks)} task(s) with 'work' tag")
        print("   Result: PASS")

        # Test 6: Complete task
        print("\n=== Test 6: Complete Task ===")
        master.update_status(task2.id, TaskStatus.COMPLETED)
        completed = master.get_by_id(task2.id)
        assert completed.status == TaskStatus.COMPLETED
        print(f"   Completed {task2.id}")
        print("   Result: PASS")

        # Test 7: Summary
        print("\n=== Test 7: Generate Summary ===")
        summary = master.summarize()
        assert "Master Task List" in summary
        assert "Pending" in summary
        print("   Summary generated:")
        for line in summary.split('\n')[:10]:
            print(f"   {line}")
        print("   ...")
        print("   Result: PASS")

        # Test 8: Stats
        print("\n=== Test 8: Get Stats ===")
        stats = master.get_stats()
        assert stats["total"] == 3
        print(f"   Stats: {stats}")
        print("   Result: PASS")

        # Test 9: Overdue detection
        print("\n=== Test 9: Overdue Detection ===")
        # Add overdue task
        overdue_task = master.add_task(
            title="Overdue task",
            due=datetime.now() - timedelta(days=5)  # 5 days ago
        )
        overdue = master.get_overdue()
        assert len(overdue) == 1
        assert overdue[0].id == overdue_task.id
        print(f"   Found {len(overdue)} overdue task(s)")
        print("   Result: PASS")

        # Test 10: Delete task
        print("\n=== Test 10: Delete Task ===")
        deleted = master.delete_task(task3.id)
        assert deleted == True
        assert master.get_by_id(task3.id) is None
        print(f"   Deleted {task3.id}")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nMaster Task List module is ready for integration!")
