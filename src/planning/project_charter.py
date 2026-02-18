#!/usr/bin/env python3
"""
Project Charters
================

Planning documentation system for complex multi-step projects.

Source: Ported from GROKSTAR's design document requirement

Problem Solved:
- Complex projects need upfront planning before execution
- Without documentation, context is lost across sessions
- "What were we trying to do?" should have a clear answer

Solution:
- Require charter creation for multi-step projects
- Track goals, approach, risks, success criteria
- Gate execution on charter approval
- Enable progress tracking against charter

Usage:
    from project_charter import ProjectCharter, CharterManager

    manager = CharterManager()

    # Create a charter
    charter = manager.create_charter(
        title="Implement Voice Integration",
        goal="Add voice input/output to VERA",
        approach="Use xAI Grok Voice API with WebSocket connection",
        success_criteria=["Voice input works", "Voice output works", "Tool calling works"],
        estimated_tasks=5
    )

    # Check if execution is gated
    if not charter.is_approved:
        print("Charter needs approval before execution")

    # Track progress
    manager.record_milestone(charter.id, "WebSocket connection established")
"""

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum

# Import atomic operations
try:
    from atomic_io import atomic_json_write, safe_json_read
    HAS_ATOMIC = True
except ImportError:
    HAS_ATOMIC = False


class CharterStatus(Enum):
    """Status of a project charter"""
    DRAFT = "draft"              # Being written
    PENDING_REVIEW = "pending"   # Awaiting approval
    APPROVED = "approved"        # Approved for execution
    IN_PROGRESS = "in_progress"  # Actively being worked on
    COMPLETED = "completed"      # Successfully finished
    ABANDONED = "abandoned"      # Cancelled or failed
    ON_HOLD = "on_hold"          # Paused


class RiskLevel(Enum):
    """Risk level for a project"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Risk:
    """A project risk"""
    description: str
    level: RiskLevel
    mitigation: str
    occurred: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "level": self.level.value,
            "mitigation": self.mitigation,
            "occurred": self.occurred
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Risk':
        return cls(
            description=data.get("description", ""),
            level=RiskLevel(data.get("level", "")),
            mitigation=data.get("mitigation", ""),
            occurred=data.get("occurred", False)
        )


@dataclass
class Milestone:
    """A project milestone"""
    description: str
    timestamp: str
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectCharter:
    """A project planning document"""
    id: str
    title: str
    created_at: str
    updated_at: str
    status: CharterStatus

    # Core planning
    goal: str
    context: str
    approach: str
    success_criteria: List[str]

    # Estimation
    estimated_tasks: int
    estimated_complexity: str  # "simple", "moderate", "complex"

    # Risks
    risks: List[Risk]

    # Progress tracking
    milestones: List[Milestone]
    tasks_completed: int
    criteria_met: List[bool]

    # Metadata
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    completed_at: Optional[str] = None
    notes: str = ""

    @property
    def is_approved(self) -> bool:
        return self.status in (CharterStatus.APPROVED, CharterStatus.IN_PROGRESS, CharterStatus.COMPLETED)

    @property
    def progress_percent(self) -> float:
        if self.estimated_tasks == 0:
            return 0.0
        return (self.tasks_completed / self.estimated_tasks) * 100

    @property
    def criteria_progress(self) -> float:
        if not self.success_criteria:
            return 0.0
        met = sum(1 for c in self.criteria_met if c)
        return (met / len(self.success_criteria)) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status.value,
            "goal": self.goal,
            "context": self.context,
            "approach": self.approach,
            "success_criteria": self.success_criteria,
            "estimated_tasks": self.estimated_tasks,
            "estimated_complexity": self.estimated_complexity,
            "risks": [r.to_dict() for r in self.risks],
            "milestones": [m.to_dict() for m in self.milestones],
            "tasks_completed": self.tasks_completed,
            "criteria_met": self.criteria_met,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "completed_at": self.completed_at,
            "notes": self.notes
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectCharter':
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            status=CharterStatus(data.get("status", "")),
            goal=data.get("goal", ""),
            context=data.get("context", ""),
            approach=data.get("approach", ""),
            success_criteria=data.get("success_criteria", ""),
            estimated_tasks=data.get("estimated_tasks", ""),
            estimated_complexity=data.get("estimated_complexity", "moderate"),
            risks=[Risk.from_dict(r) for r in data.get("risks", [])],
            milestones=[Milestone(**m) for m in data.get("milestones", [])],
            tasks_completed=data.get("tasks_completed", 0),
            criteria_met=data.get("criteria_met", [False] * len(data["success_criteria"])),
            approved_at=data.get("approved_at"),
            approved_by=data.get("approved_by"),
            completed_at=data.get("completed_at"),
            notes=data.get("notes", "")
        )

    def to_markdown(self) -> str:
        """Generate markdown representation of charter"""
        lines = [
            f"# Project Charter: {self.title}",
            "",
            f"**ID**: {self.id}",
            f"**Status**: {self.status.value}",
            f"**Created**: {self.created_at[:10]}",
            f"**Progress**: {self.progress_percent:.0f}% ({self.tasks_completed}/{self.estimated_tasks} tasks)",
            "",
            "## Goal",
            self.goal,
            ""
        ]

        if self.context:
            lines.extend([
                "## Context",
                self.context,
                ""
            ])

        lines.extend([
            "## Approach",
            self.approach,
            "",
            "## Success Criteria",
        ])

        for i, criterion in enumerate(self.success_criteria):
            status = "[x]" if self.criteria_met[i] else "[ ]"
            lines.append(f"- {status} {criterion}")

        lines.append("")

        if self.risks:
            lines.extend([
                "## Risks",
            ])
            for risk in self.risks:
                status = "(OCCURRED)" if risk.occurred else ""
                lines.append(f"- **{risk.level.value.upper()}**: {risk.description} {status}")
                lines.append(f"  - Mitigation: {risk.mitigation}")
            lines.append("")

        if self.milestones:
            lines.extend([
                "## Milestones",
            ])
            for milestone in self.milestones:
                lines.append(f"- [{milestone.timestamp[:10]}] {milestone.description}")
            lines.append("")

        if self.notes:
            lines.extend([
                "## Notes",
                self.notes,
                ""
            ])

        return "\n".join(lines)


class CharterManager:
    """
    Manages project charters.

    Provides:
    - Charter CRUD operations
    - Approval workflow
    - Progress tracking
    - Execution gating
    """

    def __init__(
        self,
        storage_dir: Path = None,
        memory_dir: Path = None,
        require_approval: bool = True
    ):
        """
        Initialize charter manager.

        Args:
            storage_dir: Directory for charter storage
            memory_dir: Base memory directory
            require_approval: Whether to require approval before execution
        """
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        elif memory_dir:
            self.storage_dir = Path(memory_dir) / "charters"
        else:
            self.storage_dir = Path("vera_memory/charters")

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.require_approval = require_approval

        # Index file for quick lookup
        self.index_path = self.storage_dir / "index.json"

        # Load index
        self._index: Dict[str, str] = {}  # id -> filename
        self._load_index()

        # Charter counter
        self._charter_count = len(self._index)

    def _load_index(self) -> None:
        """Load charter index"""
        if not self.index_path.exists():
            return

        try:
            if HAS_ATOMIC:
                self._index = safe_json_read(self.index_path, default={})
            else:
                self._index = json.loads(self.index_path.read_text())
        except Exception:
            self._index = {}

    def _save_index(self) -> None:
        """Save charter index"""
        if HAS_ATOMIC:
            atomic_json_write(self.index_path, self._index)
        else:
            self.index_path.write_text(json.dumps(self._index, indent=2))

    def _generate_id(self) -> str:
        """Generate unique charter ID"""
        self._charter_count += 1
        date_str = datetime.now().strftime("%Y%m%d")
        return f"PROJ-{date_str}-{self._charter_count:03d}"

    def create_charter(
        self,
        title: str,
        goal: str,
        approach: str,
        success_criteria: List[str],
        estimated_tasks: int = 5,
        context: str = "",
        complexity: str = "moderate",
        risks: List[Dict[str, str]] = None,
        auto_approve: bool = False
    ) -> ProjectCharter:
        """
        Create a new project charter.

        Args:
            title: Project title
            goal: What we're trying to achieve
            approach: How we'll achieve it
            success_criteria: List of success criteria
            estimated_tasks: Estimated number of tasks
            context: Background context
            complexity: "simple", "moderate", or "complex"
            risks: List of risks with description, level, mitigation
            auto_approve: Skip approval requirement

        Returns:
            Created charter
        """
        now = datetime.now().isoformat()

        # Parse risks
        parsed_risks = []
        for r in (risks or []):
            parsed_risks.append(Risk(
                description=r.get("description", ""),
                level=RiskLevel(r.get("level", "medium")),
                mitigation=r.get("mitigation", "")
            ))

        charter = ProjectCharter(
            id=self._generate_id(),
            title=title,
            created_at=now,
            updated_at=now,
            status=CharterStatus.APPROVED if auto_approve else CharterStatus.DRAFT,
            goal=goal,
            context=context,
            approach=approach,
            success_criteria=success_criteria,
            estimated_tasks=estimated_tasks,
            estimated_complexity=complexity,
            risks=parsed_risks,
            milestones=[],
            tasks_completed=0,
            criteria_met=[False] * len(success_criteria),
            approved_at=now if auto_approve else None,
            approved_by="auto" if auto_approve else None
        )

        self._save_charter(charter)

        return charter

    def _save_charter(self, charter: ProjectCharter) -> None:
        """Save charter to disk"""
        charter.updated_at = datetime.now().isoformat()

        filename = f"{charter.id}.json"
        filepath = self.storage_dir / filename

        if HAS_ATOMIC:
            atomic_json_write(filepath, charter.to_dict())
        else:
            filepath.write_text(json.dumps(charter.to_dict(), indent=2))

        # Also save markdown version
        md_path = self.storage_dir / f"{charter.id}.md"
        md_path.write_text(charter.to_markdown())

        # Update index
        self._index[charter.id] = filename
        self._save_index()

    def get_charter(self, charter_id: str) -> Optional[ProjectCharter]:
        """Get a charter by ID"""
        filename = self._index.get(charter_id)
        if not filename:
            return None

        filepath = self.storage_dir / filename
        if not filepath.exists():
            return None

        try:
            if HAS_ATOMIC:
                data = safe_json_read(filepath)
            else:
                data = json.loads(filepath.read_text())
            return ProjectCharter.from_dict(data)
        except Exception:
            return None

    def list_charters(
        self,
        status: CharterStatus = None,
        limit: int = 20
    ) -> List[ProjectCharter]:
        """List charters, optionally filtered by status"""
        charters = []

        for charter_id in list(self._index.keys())[-limit:]:
            charter = self.get_charter(charter_id)
            if charter:
                if status is None or charter.status == status:
                    charters.append(charter)

        return sorted(charters, key=lambda c: c.updated_at, reverse=True)

    def approve_charter(
        self,
        charter_id: str,
        approved_by: str = "user"
    ) -> Optional[ProjectCharter]:
        """Approve a charter for execution"""
        charter = self.get_charter(charter_id)
        if not charter:
            return None

        charter.status = CharterStatus.APPROVED
        charter.approved_at = datetime.now().isoformat()
        charter.approved_by = approved_by

        self._save_charter(charter)
        return charter

    def start_execution(self, charter_id: str) -> Optional[ProjectCharter]:
        """Mark charter as in progress"""
        charter = self.get_charter(charter_id)
        if not charter:
            return None

        if self.require_approval and not charter.is_approved:
            return None  # Can't start without approval

        charter.status = CharterStatus.IN_PROGRESS
        self._save_charter(charter)
        return charter

    def record_milestone(
        self,
        charter_id: str,
        description: str,
        notes: str = None
    ) -> Optional[ProjectCharter]:
        """Record a milestone for a charter"""
        charter = self.get_charter(charter_id)
        if not charter:
            return None

        milestone = Milestone(
            description=description,
            timestamp=datetime.now().isoformat(),
            notes=notes
        )
        charter.milestones.append(milestone)

        self._save_charter(charter)
        return charter

    def record_task_completion(
        self,
        charter_id: str,
        count: int = 1
    ) -> Optional[ProjectCharter]:
        """Record task completion"""
        charter = self.get_charter(charter_id)
        if not charter:
            return None

        charter.tasks_completed += count
        self._save_charter(charter)
        return charter

    def mark_criterion_met(
        self,
        charter_id: str,
        criterion_index: int
    ) -> Optional[ProjectCharter]:
        """Mark a success criterion as met"""
        charter = self.get_charter(charter_id)
        if not charter:
            return None

        if 0 <= criterion_index < len(charter.criteria_met):
            charter.criteria_met[criterion_index] = True

        # Check if all criteria met
        if all(charter.criteria_met):
            charter.status = CharterStatus.COMPLETED
            charter.completed_at = datetime.now().isoformat()

        self._save_charter(charter)
        return charter

    def mark_risk_occurred(
        self,
        charter_id: str,
        risk_index: int
    ) -> Optional[ProjectCharter]:
        """Mark a risk as having occurred"""
        charter = self.get_charter(charter_id)
        if not charter:
            return None

        if 0 <= risk_index < len(charter.risks):
            charter.risks[risk_index].occurred = True

        self._save_charter(charter)
        return charter

    def complete_charter(
        self,
        charter_id: str,
        notes: str = None
    ) -> Optional[ProjectCharter]:
        """Mark charter as completed"""
        charter = self.get_charter(charter_id)
        if not charter:
            return None

        charter.status = CharterStatus.COMPLETED
        charter.completed_at = datetime.now().isoformat()
        if notes:
            charter.notes = notes

        self._save_charter(charter)
        return charter

    def abandon_charter(
        self,
        charter_id: str,
        reason: str = None
    ) -> Optional[ProjectCharter]:
        """Mark charter as abandoned"""
        charter = self.get_charter(charter_id)
        if not charter:
            return None

        charter.status = CharterStatus.ABANDONED
        if reason:
            charter.notes = f"Abandoned: {reason}"

        self._save_charter(charter)
        return charter

    def can_execute(self, charter_id: str) -> Tuple[bool, str]:
        """
        Check if a charter can be executed.

        Returns:
            Tuple of (can_execute, reason)
        """
        charter = self.get_charter(charter_id)

        if not charter:
            return (False, "Charter not found")

        if charter.status == CharterStatus.DRAFT:
            return (False, "Charter is still in draft. Submit for review first.")

        if charter.status == CharterStatus.PENDING_REVIEW:
            return (False, "Charter is pending review. Awaiting approval.")

        if charter.status == CharterStatus.ABANDONED:
            return (False, "Charter has been abandoned.")

        if charter.status == CharterStatus.COMPLETED:
            return (False, "Charter is already completed.")

        if charter.status == CharterStatus.ON_HOLD:
            return (False, "Charter is on hold.")

        if self.require_approval and not charter.is_approved:
            return (False, "Charter requires approval before execution.")

        return (True, "Ready for execution")

    def get_active_charter(self) -> Optional[ProjectCharter]:
        """Get the currently active (in-progress) charter"""
        for charter_id in self._index:
            charter = self.get_charter(charter_id)
            if charter and charter.status == CharterStatus.IN_PROGRESS:
                return charter
        return None

    def summarize(self) -> str:
        """Generate summary of all charters"""
        charters = self.list_charters(limit=50)

        if not charters:
            return "No project charters found."

        by_status = {}
        for charter in charters:
            by_status.setdefault(charter.status.value, []).append(charter)

        lines = ["**Project Charters Summary**", ""]

        for status, status_charters in by_status.items():
            lines.append(f"**{status.replace('_', ' ').title()}** ({len(status_charters)})")
            for c in status_charters[:3]:
                progress = f"{c.progress_percent:.0f}%" if c.status == CharterStatus.IN_PROGRESS else ""
                lines.append(f"  - [{c.id}] {c.title} {progress}")
            if len(status_charters) > 3:
                lines.append(f"  - ... and {len(status_charters) - 3} more")
            lines.append("")

        return "\n".join(lines)


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("Project Charter Manager - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = CharterManager(storage_dir=Path(tmpdir))

        # Test 1: Create charter
        print("\n=== Test 1: Create Charter ===")
        charter = manager.create_charter(
            title="Voice Integration",
            goal="Add voice input/output to VERA",
            approach="Use xAI Grok Voice API with WebSocket",
            success_criteria=[
                "Voice input works",
                "Voice output works",
                "Tool calling works"
            ],
            estimated_tasks=5,
            risks=[
                {"description": "API rate limits", "level": "medium", "mitigation": "Implement backoff"}
            ]
        )
        assert charter.id.startswith("PROJ-")
        assert charter.status == CharterStatus.DRAFT
        print(f"   Created: {charter.id}")
        print(f"   Status: {charter.status.value}")
        print("   Result: PASS")

        # Test 2: Execution gating (should fail before approval)
        print("\n=== Test 2: Execution Gating ===")
        can_exec, reason = manager.can_execute(charter.id)
        assert not can_exec
        print(f"   Can execute (draft): {can_exec}")
        print(f"   Reason: {reason}")
        print("   Result: PASS")

        # Test 3: Approve charter
        print("\n=== Test 3: Approve Charter ===")
        charter = manager.approve_charter(charter.id)
        assert charter.is_approved
        can_exec, reason = manager.can_execute(charter.id)
        assert can_exec
        print(f"   Approved: {charter.is_approved}")
        print(f"   Can execute now: {can_exec}")
        print("   Result: PASS")

        # Test 4: Start execution
        print("\n=== Test 4: Start Execution ===")
        charter = manager.start_execution(charter.id)
        assert charter.status == CharterStatus.IN_PROGRESS
        print(f"   Status: {charter.status.value}")
        print("   Result: PASS")

        # Test 5: Record progress
        print("\n=== Test 5: Record Progress ===")
        manager.record_milestone(charter.id, "WebSocket connection established")
        manager.record_task_completion(charter.id, 2)
        charter = manager.get_charter(charter.id)
        assert charter.tasks_completed == 2
        assert len(charter.milestones) == 1
        print(f"   Tasks: {charter.tasks_completed}/{charter.estimated_tasks}")
        print(f"   Progress: {charter.progress_percent:.0f}%")
        print(f"   Milestones: {len(charter.milestones)}")
        print("   Result: PASS")

        # Test 6: Mark criterion met
        print("\n=== Test 6: Mark Criterion Met ===")
        manager.mark_criterion_met(charter.id, 0)
        charter = manager.get_charter(charter.id)
        assert charter.criteria_met[0] == True
        print(f"   Criterion 0 met: {charter.criteria_met[0]}")
        print(f"   Criteria progress: {charter.criteria_progress:.0f}%")
        print("   Result: PASS")

        # Test 7: Markdown export
        print("\n=== Test 7: Markdown Export ===")
        md = charter.to_markdown()
        assert "# Project Charter:" in md
        assert "Voice Integration" in md
        print("   Markdown generated")
        print("   Result: PASS")

        # Test 8: Complete charter
        print("\n=== Test 8: Complete Charter ===")
        manager.mark_criterion_met(charter.id, 1)
        manager.mark_criterion_met(charter.id, 2)
        charter = manager.get_charter(charter.id)
        assert charter.status == CharterStatus.COMPLETED
        print(f"   Status: {charter.status.value}")
        print("   Result: PASS")

        # Test 9: Summary
        print("\n=== Test 9: Summary ===")
        summary = manager.summarize()
        assert "Project Charters Summary" in summary
        print("   Summary generated")
        print("   Result: PASS")

        # Test 10: Auto-approve
        print("\n=== Test 10: Auto-Approve ===")
        charter2 = manager.create_charter(
            title="Quick Fix",
            goal="Fix a bug",
            approach="Direct fix",
            success_criteria=["Bug fixed"],
            auto_approve=True
        )
        assert charter2.is_approved
        print(f"   Auto-approved: {charter2.is_approved}")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nProject Charter Manager is ready for integration!")
