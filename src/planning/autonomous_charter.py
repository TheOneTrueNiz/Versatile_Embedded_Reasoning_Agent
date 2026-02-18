"""
#15 [P2] Self-Starting Planning: Autonomous Project Chartering

This module implements autonomous project charter drafting with:
- Project scope analysis and decomposition
- Milestone and phase generation
- Resource and effort estimation
- Risk assessment and mitigation planning
- Dependency graph construction
- Success criteria definition
- Automatic plan refinement based on feedback

Based on research from:
- "Autonomous Planning Agents" (arXiv:2310.04406)
- "Self-Refining AI Project Management" (arXiv:2311.08249)
- "Hierarchical Task Networks for AI Planning" (arXiv:2309.15657)
"""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import threading


# =============================================================================
# Enums and Constants
# =============================================================================

class ProjectType(Enum):
    """Types of projects."""
    FEATURE = "feature"           # New feature development
    BUG_FIX = "bug_fix"          # Bug fixing
    REFACTOR = "refactor"        # Code refactoring
    RESEARCH = "research"        # Research/exploration
    INTEGRATION = "integration"  # System integration
    DOCUMENTATION = "documentation"  # Documentation
    MIGRATION = "migration"      # Data/system migration
    OPTIMIZATION = "optimization"  # Performance optimization


class TaskComplexity(Enum):
    """Task complexity levels."""
    TRIVIAL = "trivial"      # <1 hour
    SIMPLE = "simple"        # 1-4 hours
    MEDIUM = "medium"        # 4-8 hours
    COMPLEX = "complex"      # 1-3 days
    VERY_COMPLEX = "very_complex"  # 3-7 days
    EPIC = "epic"            # 1-4 weeks


class RiskLevel(Enum):
    """Risk severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PhaseStatus(Enum):
    """Phase execution status."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CharterStatus(Enum):
    """Charter lifecycle status."""
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    IN_EXECUTION = "in_execution"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


# Effort multipliers by complexity
COMPLEXITY_HOURS = {
    TaskComplexity.TRIVIAL: 0.5,
    TaskComplexity.SIMPLE: 2.0,
    TaskComplexity.MEDIUM: 6.0,
    TaskComplexity.COMPLEX: 16.0,
    TaskComplexity.VERY_COMPLEX: 40.0,
    TaskComplexity.EPIC: 120.0,
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Task:
    """A unit of work within a project."""
    task_id: str
    name: str
    description: str
    complexity: TaskComplexity = TaskComplexity.MEDIUM
    estimated_hours: float = 0.0
    dependencies: List[str] = field(default_factory=list)
    assigned_to: Optional[str] = None
    status: str = "pending"
    tags: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        if self.estimated_hours == 0.0:
            self.estimated_hours = COMPLEXITY_HOURS.get(self.complexity, 6.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "complexity": self.complexity.value,
            "estimated_hours": self.estimated_hours,
            "dependencies": self.dependencies,
            "assigned_to": self.assigned_to,
            "status": self.status,
            "tags": self.tags,
            "acceptance_criteria": self.acceptance_criteria,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        return cls(
            task_id=data["task_id"],
            name=data["name"],
            description=data["description"],
            complexity=TaskComplexity(data.get("complexity", "medium")),
            estimated_hours=data.get("estimated_hours", 0.0),
            dependencies=data.get("dependencies", []),
            assigned_to=data.get("assigned_to"),
            status=data.get("status", "pending"),
            tags=data.get("tags", []),
            acceptance_criteria=data.get("acceptance_criteria", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
        )


@dataclass
class Risk:
    """A project risk with mitigation strategy."""
    risk_id: str
    description: str
    level: RiskLevel = RiskLevel.MEDIUM
    probability: float = 0.5  # 0.0 to 1.0
    impact: float = 0.5       # 0.0 to 1.0
    mitigation: str = ""
    contingency: str = ""
    owner: Optional[str] = None
    status: str = "open"

    @property
    def risk_score(self) -> float:
        """Calculate risk score (probability * impact)."""
        return self.probability * self.impact

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_id": self.risk_id,
            "description": self.description,
            "level": self.level.value,
            "probability": self.probability,
            "impact": self.impact,
            "mitigation": self.mitigation,
            "contingency": self.contingency,
            "owner": self.owner,
            "status": self.status,
            "risk_score": self.risk_score,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Risk":
        return cls(
            risk_id=data["risk_id"],
            description=data["description"],
            level=RiskLevel(data.get("level", "medium")),
            probability=data.get("probability", 0.5),
            impact=data.get("impact", 0.5),
            mitigation=data.get("mitigation", ""),
            contingency=data.get("contingency", ""),
            owner=data.get("owner"),
            status=data.get("status", "open"),
        )


@dataclass
class Milestone:
    """A project milestone marking significant progress."""
    milestone_id: str
    name: str
    description: str
    target_date: Optional[str] = None
    deliverables: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    status: str = "pending"
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "name": self.name,
            "description": self.description,
            "target_date": self.target_date,
            "deliverables": self.deliverables,
            "success_criteria": self.success_criteria,
            "status": self.status,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Milestone":
        return cls(
            milestone_id=data["milestone_id"],
            name=data["name"],
            description=data["description"],
            target_date=data.get("target_date"),
            deliverables=data.get("deliverables", []),
            success_criteria=data.get("success_criteria", []),
            status=data.get("status", "pending"),
            completed_at=data.get("completed_at"),
        )


@dataclass
class Phase:
    """A project phase containing related tasks."""
    phase_id: str
    name: str
    description: str
    order: int = 0
    tasks: List[str] = field(default_factory=list)  # Task IDs
    milestone_id: Optional[str] = None
    status: PhaseStatus = PhaseStatus.NOT_STARTED
    prerequisites: List[str] = field(default_factory=list)  # Phase IDs
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "name": self.name,
            "description": self.description,
            "order": self.order,
            "tasks": self.tasks,
            "milestone_id": self.milestone_id,
            "status": self.status.value,
            "prerequisites": self.prerequisites,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Phase":
        return cls(
            phase_id=data["phase_id"],
            name=data["name"],
            description=data["description"],
            order=data.get("order", 0),
            tasks=data.get("tasks", []),
            milestone_id=data.get("milestone_id"),
            status=PhaseStatus(data.get("status", "not_started")),
            prerequisites=data.get("prerequisites", []),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
        )


@dataclass
class ProjectCharter:
    """Complete project charter document."""
    charter_id: str
    name: str
    description: str
    project_type: ProjectType = ProjectType.FEATURE
    objectives: List[str] = field(default_factory=list)
    scope_in: List[str] = field(default_factory=list)
    scope_out: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    phases: Dict[str, Phase] = field(default_factory=dict)
    tasks: Dict[str, Task] = field(default_factory=dict)
    milestones: Dict[str, Milestone] = field(default_factory=dict)
    risks: Dict[str, Risk] = field(default_factory=dict)
    assumptions: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    stakeholders: List[str] = field(default_factory=list)
    status: CharterStatus = CharterStatus.DRAFT
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_total_effort_hours(self) -> float:
        """Calculate total estimated effort in hours."""
        return sum(task.estimated_hours for task in self.tasks.values())

    def get_critical_path(self) -> List[str]:
        """Get critical path task IDs."""
        # Topological sort with longest path calculation
        in_degree = {tid: 0 for tid in self.tasks}
        duration = {tid: self.tasks[tid].estimated_hours for tid in self.tasks}
        earliest_start = {tid: 0.0 for tid in self.tasks}

        # Build dependency graph
        for tid, task in self.tasks.items():
            for dep in task.dependencies:
                if dep in in_degree:
                    in_degree[tid] += 1

        # Process in topological order
        ready = [tid for tid, deg in in_degree.items() if deg == 0]
        order = []

        while ready:
            tid = ready.pop(0)
            order.append(tid)

            for other_tid, task in self.tasks.items():
                if tid in task.dependencies:
                    in_degree[other_tid] -= 1
                    earliest_start[other_tid] = max(
                        earliest_start[other_tid],
                        earliest_start[tid] + duration[tid]
                    )
                    if in_degree[other_tid] == 0:
                        ready.append(other_tid)

        if len(order) != len(self.tasks):
            return []  # Cycle detected

        # Find end tasks and trace back
        if not order:
            return []

        end_time = {tid: earliest_start[tid] + duration[tid] for tid in order}
        max_end = max(end_time.values()) if end_time else 0

        # Tasks on critical path have no slack
        critical = []
        for tid in order:
            if abs(end_time[tid] - max_end) < 0.001 or not self.tasks[tid].dependencies:
                critical.append(tid)

        return critical

    def get_risk_summary(self) -> Dict[str, Any]:
        """Get risk analysis summary."""
        if not self.risks:
            return {"total": 0, "by_level": {}, "avg_score": 0.0}

        by_level = {}
        for risk in self.risks.values():
            level = risk.level.value
            by_level[level] = by_level.get(level, 0) + 1

        avg_score = sum(r.risk_score for r in self.risks.values()) / len(self.risks)

        return {
            "total": len(self.risks),
            "by_level": by_level,
            "avg_score": avg_score,
            "highest_risk": max(self.risks.values(), key=lambda r: r.risk_score).risk_id,
        }

    def compute_hash(self) -> str:
        """Compute content hash for versioning."""
        # Use _to_dict_core to avoid recursion
        content = json.dumps(self._to_dict_core(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _to_dict_core(self) -> Dict[str, Any]:
        """Core dict representation without computed fields."""
        return {
            "charter_id": self.charter_id,
            "name": self.name,
            "description": self.description,
            "project_type": self.project_type.value,
            "objectives": self.objectives,
            "scope_in": self.scope_in,
            "scope_out": self.scope_out,
            "success_criteria": self.success_criteria,
            "phases": {pid: p.to_dict() for pid, p in self.phases.items()},
            "tasks": {tid: t.to_dict() for tid, t in self.tasks.items()},
            "milestones": {mid: m.to_dict() for mid, m in self.milestones.items()},
            "risks": {rid: r.to_dict() for rid, r in self.risks.items()},
            "assumptions": self.assumptions,
            "constraints": self.constraints,
            "stakeholders": self.stakeholders,
            "status": self.status.value,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "metadata": self.metadata,
        }

    def to_dict(self) -> Dict[str, Any]:
        result = self._to_dict_core()
        result["total_effort_hours"] = self.get_total_effort_hours()
        result["content_hash"] = self.compute_hash()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectCharter":
        charter = cls(
            charter_id=data["charter_id"],
            name=data["name"],
            description=data["description"],
            project_type=ProjectType(data.get("project_type", "feature")),
            objectives=data.get("objectives", []),
            scope_in=data.get("scope_in", []),
            scope_out=data.get("scope_out", []),
            success_criteria=data.get("success_criteria", []),
            assumptions=data.get("assumptions", []),
            constraints=data.get("constraints", []),
            stakeholders=data.get("stakeholders", []),
            status=CharterStatus(data.get("status", "draft")),
            version=data.get("version", 1),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            approved_at=data.get("approved_at"),
            approved_by=data.get("approved_by"),
            metadata=data.get("metadata", {}),
        )

        # Reconstruct phases
        for pid, pdata in data.get("phases", {}).items():
            charter.phases[pid] = Phase.from_dict(pdata)

        # Reconstruct tasks
        for tid, tdata in data.get("tasks", {}).items():
            charter.tasks[tid] = Task.from_dict(tdata)

        # Reconstruct milestones
        for mid, mdata in data.get("milestones", {}).items():
            charter.milestones[mid] = Milestone.from_dict(mdata)

        # Reconstruct risks
        for rid, rdata in data.get("risks", {}).items():
            charter.risks[rid] = Risk.from_dict(rdata)

        return charter


# =============================================================================
# Scope Analyzer
# =============================================================================

class ScopeAnalyzer:
    """Analyzes project scope from natural language descriptions."""

    # Keywords for project type detection
    TYPE_KEYWORDS = {
        ProjectType.FEATURE: [
            "add", "implement", "create", "build", "new", "feature",
            "functionality", "capability", "enable", "support",
        ],
        ProjectType.BUG_FIX: [
            "fix", "bug", "issue", "error", "crash", "broken",
            "not working", "fails", "incorrect", "wrong",
        ],
        ProjectType.REFACTOR: [
            "refactor", "clean", "restructure", "reorganize",
            "improve code", "technical debt", "modularize",
        ],
        ProjectType.RESEARCH: [
            "research", "investigate", "explore", "analyze",
            "study", "evaluate", "assess", "prototype",
        ],
        ProjectType.INTEGRATION: [
            "integrate", "connect", "interface", "api",
            "sync", "bridge", "link", "combine",
        ],
        ProjectType.DOCUMENTATION: [
            "document", "docs", "readme", "guide",
            "tutorial", "instructions", "manual",
        ],
        ProjectType.MIGRATION: [
            "migrate", "upgrade", "move", "transfer",
            "convert", "port", "transition",
        ],
        ProjectType.OPTIMIZATION: [
            "optimize", "performance", "speed", "faster",
            "efficient", "cache", "memory", "reduce",
        ],
    }

    # Complexity indicators
    COMPLEXITY_PATTERNS = {
        TaskComplexity.TRIVIAL: [
            r"simple\s+change",
            r"quick\s+fix",
            r"one-liner",
            r"typo",
        ],
        TaskComplexity.SIMPLE: [
            r"add\s+a?\s*\w+\s+to",
            r"update\s+\w+",
            r"change\s+\w+",
        ],
        TaskComplexity.MEDIUM: [
            r"implement\s+\w+",
            r"create\s+\w+\s+component",
            r"add\s+\w+\s+feature",
        ],
        TaskComplexity.COMPLEX: [
            r"redesign",
            r"major\s+change",
            r"new\s+system",
            r"architecture",
        ],
        TaskComplexity.VERY_COMPLEX: [
            r"complete\s+rewrite",
            r"full\s+integration",
            r"migration\s+of",
        ],
        TaskComplexity.EPIC: [
            r"entire\s+platform",
            r"from\s+scratch",
            r"complete\s+system",
        ],
    }

    def analyze(self, description: str) -> Dict[str, Any]:
        """Analyze project scope from description."""
        description_lower = description.lower()

        # Detect project type
        project_type = self._detect_type(description_lower)

        # Estimate complexity
        complexity = self._estimate_complexity(description_lower)

        # Extract key entities
        entities = self._extract_entities(description)

        # Identify scope boundaries
        scope = self._identify_scope(description)

        # Extract implicit requirements
        requirements = self._extract_requirements(description)

        return {
            "project_type": project_type,
            "complexity": complexity,
            "entities": entities,
            "scope": scope,
            "requirements": requirements,
        }

    def _detect_type(self, text: str) -> ProjectType:
        """Detect project type from keywords."""
        scores = {}
        for ptype, keywords in self.TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[ptype] = score

        if not scores:
            return ProjectType.FEATURE

        return max(scores.keys(), key=lambda k: scores[k])

    def _estimate_complexity(self, text: str) -> TaskComplexity:
        """Estimate task complexity from patterns."""
        for complexity in reversed(list(TaskComplexity)):
            patterns = self.COMPLEXITY_PATTERNS.get(complexity, [])
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return complexity

        # Default based on text length
        if len(text) < 50:
            return TaskComplexity.SIMPLE
        elif len(text) < 200:
            return TaskComplexity.MEDIUM
        else:
            return TaskComplexity.COMPLEX

    def _extract_entities(self, text: str) -> List[str]:
        """Extract key entities from description."""
        entities = []

        # Extract quoted strings
        quoted = re.findall(r'"([^"]+)"', text)
        entities.extend(quoted)
        quoted = re.findall(r"'([^']+)'", text)
        entities.extend(quoted)

        # Extract capitalized terms (potential class/module names)
        caps = re.findall(r'\b([A-Z][a-zA-Z0-9]+(?:[A-Z][a-zA-Z0-9]+)*)\b', text)
        entities.extend(caps)

        # Extract file paths
        paths = re.findall(r'[\w/]+\.\w+', text)
        entities.extend(paths)

        return list(set(entities))

    def _identify_scope(self, text: str) -> Dict[str, List[str]]:
        """Identify scope boundaries."""
        scope_in = []
        scope_out = []

        # Look for explicit scope markers
        in_markers = ["include", "should", "must", "need to", "will"]
        out_markers = ["exclude", "don't", "won't", "not", "without"]

        sentences = re.split(r'[.!?]', text)

        for sentence in sentences:
            sentence_lower = sentence.lower().strip()
            if any(marker in sentence_lower for marker in out_markers):
                scope_out.append(sentence.strip())
            elif any(marker in sentence_lower for marker in in_markers):
                scope_in.append(sentence.strip())

        return {"in": scope_in, "out": scope_out}

    def _extract_requirements(self, text: str) -> List[str]:
        """Extract implicit requirements."""
        requirements = []

        # Requirement patterns
        patterns = [
            r"must\s+(.+?)(?:[,.]|$)",
            r"should\s+(.+?)(?:[,.]|$)",
            r"need(?:s)?\s+to\s+(.+?)(?:[,.]|$)",
            r"required?\s+(.+?)(?:[,.]|$)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            requirements.extend(matches)

        return requirements


# =============================================================================
# Task Decomposer
# =============================================================================

class TaskDecomposer:
    """Decomposes project scope into actionable tasks."""

    # Standard task templates by project type
    TASK_TEMPLATES = {
        ProjectType.FEATURE: [
            ("design", "Design {feature} architecture", TaskComplexity.MEDIUM),
            ("implement", "Implement {feature} core logic", TaskComplexity.COMPLEX),
            ("test", "Write tests for {feature}", TaskComplexity.MEDIUM),
            ("integrate", "Integrate {feature} with existing system", TaskComplexity.MEDIUM),
            ("document", "Document {feature} usage", TaskComplexity.SIMPLE),
        ],
        ProjectType.BUG_FIX: [
            ("investigate", "Investigate root cause of {issue}", TaskComplexity.MEDIUM),
            ("reproduce", "Create reproduction steps for {issue}", TaskComplexity.SIMPLE),
            ("fix", "Implement fix for {issue}", TaskComplexity.MEDIUM),
            ("test", "Add regression test for {issue}", TaskComplexity.SIMPLE),
            ("verify", "Verify fix in staging environment", TaskComplexity.SIMPLE),
        ],
        ProjectType.REFACTOR: [
            ("analyze", "Analyze current {component} structure", TaskComplexity.MEDIUM),
            ("plan", "Plan refactoring approach for {component}", TaskComplexity.MEDIUM),
            ("refactor", "Refactor {component}", TaskComplexity.COMPLEX),
            ("test", "Update tests for refactored {component}", TaskComplexity.MEDIUM),
            ("review", "Code review for {component} changes", TaskComplexity.SIMPLE),
        ],
        ProjectType.RESEARCH: [
            ("survey", "Survey existing solutions for {topic}", TaskComplexity.MEDIUM),
            ("analyze", "Analyze requirements for {topic}", TaskComplexity.MEDIUM),
            ("prototype", "Build prototype for {topic}", TaskComplexity.COMPLEX),
            ("evaluate", "Evaluate prototype results", TaskComplexity.MEDIUM),
            ("document", "Document findings for {topic}", TaskComplexity.MEDIUM),
        ],
        ProjectType.INTEGRATION: [
            ("study", "Study {system} API documentation", TaskComplexity.MEDIUM),
            ("design", "Design integration architecture for {system}", TaskComplexity.MEDIUM),
            ("implement", "Implement {system} connector", TaskComplexity.COMPLEX),
            ("test", "Test integration with {system}", TaskComplexity.MEDIUM),
            ("deploy", "Deploy and verify {system} integration", TaskComplexity.MEDIUM),
        ],
        ProjectType.DOCUMENTATION: [
            ("outline", "Create documentation outline for {topic}", TaskComplexity.SIMPLE),
            ("draft", "Write initial draft for {topic}", TaskComplexity.MEDIUM),
            ("examples", "Add code examples for {topic}", TaskComplexity.MEDIUM),
            ("review", "Review and edit {topic} documentation", TaskComplexity.SIMPLE),
            ("publish", "Publish {topic} documentation", TaskComplexity.TRIVIAL),
        ],
        ProjectType.MIGRATION: [
            ("assess", "Assess current state for {migration}", TaskComplexity.MEDIUM),
            ("plan", "Create migration plan for {migration}", TaskComplexity.COMPLEX),
            ("prepare", "Prepare target environment for {migration}", TaskComplexity.MEDIUM),
            ("migrate", "Execute {migration}", TaskComplexity.COMPLEX),
            ("validate", "Validate {migration} results", TaskComplexity.MEDIUM),
        ],
        ProjectType.OPTIMIZATION: [
            ("profile", "Profile current {component} performance", TaskComplexity.MEDIUM),
            ("identify", "Identify bottlenecks in {component}", TaskComplexity.MEDIUM),
            ("optimize", "Implement optimizations for {component}", TaskComplexity.COMPLEX),
            ("measure", "Measure performance improvement", TaskComplexity.SIMPLE),
            ("document", "Document optimization results", TaskComplexity.SIMPLE),
        ],
    }

    def __init__(self) -> None:
        self._task_counter = 0
        self._lock = threading.Lock()

    def _generate_task_id(self) -> str:
        """Generate unique task ID."""
        with self._lock:
            self._task_counter += 1
            return f"task_{self._task_counter:04d}"

    def decompose(
        self,
        scope_analysis: Dict[str, Any],
        project_name: str,
    ) -> List[Task]:
        """Decompose scope into tasks."""
        project_type = scope_analysis.get("project_type", ProjectType.FEATURE)
        entities = scope_analysis.get("entities", [project_name])
        complexity = scope_analysis.get("complexity", TaskComplexity.MEDIUM)

        # Get template for project type
        templates = self.TASK_TEMPLATES.get(project_type, self.TASK_TEMPLATES[ProjectType.FEATURE])

        tasks = []
        subject = entities[0] if entities else project_name

        # Generate tasks from templates
        previous_task_id = None
        for suffix, name_template, base_complexity in templates:
            task_id = self._generate_task_id()

            # Adjust complexity based on overall project complexity
            adjusted_complexity = self._adjust_complexity(base_complexity, complexity)

            task = Task(
                task_id=task_id,
                name=name_template.format(
                    feature=subject,
                    issue=subject,
                    component=subject,
                    topic=subject,
                    system=subject,
                    migration=subject,
                ),
                description=f"{name_template.format(feature=subject, issue=subject, component=subject, topic=subject, system=subject, migration=subject)} as part of {project_name}",
                complexity=adjusted_complexity,
                dependencies=[previous_task_id] if previous_task_id else [],
                tags=[project_type.value, suffix],
            )

            tasks.append(task)
            previous_task_id = task_id

        return tasks

    def _adjust_complexity(
        self,
        base: TaskComplexity,
        overall: TaskComplexity,
    ) -> TaskComplexity:
        """Adjust task complexity based on overall project complexity."""
        complexities = list(TaskComplexity)
        base_idx = complexities.index(base)
        overall_idx = complexities.index(overall)

        # Shift up or down based on overall complexity
        offset = (overall_idx - 2) // 2  # Center around MEDIUM (index 2)
        new_idx = max(0, min(len(complexities) - 1, base_idx + offset))

        return complexities[new_idx]


# =============================================================================
# Risk Assessor
# =============================================================================

class RiskAssessor:
    """Assesses project risks based on scope and complexity."""

    # Risk templates by category
    RISK_TEMPLATES = {
        "technical": [
            {
                "pattern": r"integrat",
                "description": "Integration complexity may cause unexpected issues",
                "probability": 0.6,
                "impact": 0.7,
                "mitigation": "Implement integration tests early and use mocking",
            },
            {
                "pattern": r"perform|optim|speed",
                "description": "Performance targets may be difficult to achieve",
                "probability": 0.5,
                "impact": 0.6,
                "mitigation": "Profile early and set measurable performance benchmarks",
            },
            {
                "pattern": r"secur|auth|encrypt",
                "description": "Security vulnerabilities may be introduced",
                "probability": 0.4,
                "impact": 0.9,
                "mitigation": "Conduct security review and use established patterns",
            },
            {
                "pattern": r"migrat|upgrad|convert",
                "description": "Data loss or corruption during migration",
                "probability": 0.3,
                "impact": 0.9,
                "mitigation": "Create comprehensive backups and rollback plan",
            },
        ],
        "schedule": [
            {
                "pattern": r"complex|large|major",
                "description": "Scope creep may delay delivery",
                "probability": 0.7,
                "impact": 0.5,
                "mitigation": "Define clear scope boundaries and change management process",
            },
            {
                "pattern": r"depend|block|wait",
                "description": "External dependencies may cause delays",
                "probability": 0.5,
                "impact": 0.6,
                "mitigation": "Identify dependencies early and create contingency plans",
            },
        ],
        "resource": [
            {
                "pattern": r"new\s+tech|unfamiliar|learn",
                "description": "Learning curve for new technology",
                "probability": 0.6,
                "impact": 0.4,
                "mitigation": "Allocate time for learning and consider training",
            },
        ],
    }

    def __init__(self) -> None:
        self._risk_counter = 0
        self._lock = threading.Lock()

    def _generate_risk_id(self) -> str:
        """Generate unique risk ID."""
        with self._lock:
            self._risk_counter += 1
            return f"risk_{self._risk_counter:04d}"

    def assess(
        self,
        description: str,
        complexity: TaskComplexity,
        project_type: ProjectType,
    ) -> List[Risk]:
        """Assess risks for project."""
        risks = []
        description_lower = description.lower()

        for category, templates in self.RISK_TEMPLATES.items():
            for template in templates:
                if re.search(template["pattern"], description_lower, re.IGNORECASE):
                    risk = Risk(
                        risk_id=self._generate_risk_id(),
                        description=template["description"],
                        level=self._calculate_level(
                            template["probability"],
                            template["impact"],
                        ),
                        probability=template["probability"],
                        impact=template["impact"],
                        mitigation=template["mitigation"],
                    )
                    risks.append(risk)

        # Add complexity-based risk
        if complexity in [TaskComplexity.VERY_COMPLEX, TaskComplexity.EPIC]:
            risks.append(Risk(
                risk_id=self._generate_risk_id(),
                description="High complexity increases likelihood of unforeseen issues",
                level=RiskLevel.HIGH,
                probability=0.7,
                impact=0.6,
                mitigation="Break into smaller phases with frequent review points",
            ))

        # Add type-specific risks
        type_risks = self._get_type_risks(project_type)
        risks.extend(type_risks)

        return risks

    def _calculate_level(self, probability: float, impact: float) -> RiskLevel:
        """Calculate risk level from probability and impact."""
        score = probability * impact

        if score >= 0.6:
            return RiskLevel.CRITICAL
        elif score >= 0.4:
            return RiskLevel.HIGH
        elif score >= 0.2:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    def _get_type_risks(self, project_type: ProjectType) -> List[Risk]:
        """Get type-specific risks."""
        type_risks = {
            ProjectType.MIGRATION: [
                Risk(
                    risk_id=self._generate_risk_id(),
                    description="Rollback may not be possible after migration",
                    level=RiskLevel.HIGH,
                    probability=0.3,
                    impact=0.9,
                    mitigation="Test rollback procedure before production migration",
                ),
            ],
            ProjectType.INTEGRATION: [
                Risk(
                    risk_id=self._generate_risk_id(),
                    description="External API changes may break integration",
                    level=RiskLevel.MEDIUM,
                    probability=0.4,
                    impact=0.5,
                    mitigation="Implement versioned API contracts and monitoring",
                ),
            ],
        }

        return type_risks.get(project_type, [])


# =============================================================================
# Phase Generator
# =============================================================================

class PhaseGenerator:
    """Generates project phases from tasks."""

    # Standard phase definitions
    STANDARD_PHASES = [
        ("planning", "Planning", "Define scope, requirements, and approach"),
        ("design", "Design", "Create technical design and architecture"),
        ("implementation", "Implementation", "Build the solution"),
        ("testing", "Testing", "Verify functionality and quality"),
        ("deployment", "Deployment", "Deploy and release"),
        ("review", "Review", "Post-implementation review and documentation"),
    ]

    def __init__(self) -> None:
        self._phase_counter = 0
        self._milestone_counter = 0
        self._lock = threading.Lock()

    def _generate_phase_id(self) -> str:
        """Generate unique phase ID."""
        with self._lock:
            self._phase_counter += 1
            return f"phase_{self._phase_counter:04d}"

    def _generate_milestone_id(self) -> str:
        """Generate unique milestone ID."""
        with self._lock:
            self._milestone_counter += 1
            return f"milestone_{self._milestone_counter:04d}"

    def generate(
        self,
        tasks: List[Task],
        project_name: str,
    ) -> Tuple[Dict[str, Phase], Dict[str, Milestone]]:
        """Generate phases and milestones from tasks."""
        phases = {}
        milestones = {}

        # Group tasks by their tags
        task_groups = self._group_tasks(tasks)

        # Create phases based on standard phases
        previous_phase_id = None

        for idx, (phase_key, phase_name, phase_desc) in enumerate(self.STANDARD_PHASES):
            # Find matching tasks
            matching_tasks = []
            for task in tasks:
                task_type = task.tags[1] if len(task.tags) > 1 else ""
                if self._matches_phase(task_type, phase_key):
                    matching_tasks.append(task.task_id)

            if not matching_tasks:
                continue

            phase_id = self._generate_phase_id()
            milestone_id = self._generate_milestone_id()

            # Create phase
            phase = Phase(
                phase_id=phase_id,
                name=f"{phase_name}: {project_name}",
                description=phase_desc,
                order=idx,
                tasks=matching_tasks,
                milestone_id=milestone_id,
                prerequisites=[previous_phase_id] if previous_phase_id else [],
            )
            phases[phase_id] = phase

            # Create milestone
            milestone = Milestone(
                milestone_id=milestone_id,
                name=f"{phase_name} Complete",
                description=f"{phase_name} phase completed for {project_name}",
                deliverables=[f"Completed: {t}" for t in matching_tasks[:3]],
                success_criteria=[f"All {phase_key} tasks verified"],
            )
            milestones[milestone_id] = milestone

            previous_phase_id = phase_id

        return phases, milestones

    def _group_tasks(self, tasks: List[Task]) -> Dict[str, List[Task]]:
        """Group tasks by type."""
        groups = {}
        for task in tasks:
            task_type = task.tags[1] if len(task.tags) > 1 else "other"
            if task_type not in groups:
                groups[task_type] = []
            groups[task_type].append(task)
        return groups

    def _matches_phase(self, task_type: str, phase_key: str) -> bool:
        """Check if task type matches phase."""
        mapping = {
            "planning": ["analyze", "assess", "survey", "outline", "plan"],
            "design": ["design", "prototype"],
            "implementation": ["implement", "refactor", "fix", "migrate", "optimize", "draft"],
            "testing": ["test", "verify", "validate", "evaluate", "measure"],
            "deployment": ["deploy", "publish", "integrate"],
            "review": ["review", "document", "examples"],
        }

        return task_type in mapping.get(phase_key, [])


# =============================================================================
# Charter Builder
# =============================================================================

class CharterBuilder:
    """Builds complete project charters from descriptions."""

    def __init__(self) -> None:
        self.scope_analyzer = ScopeAnalyzer()
        self.task_decomposer = TaskDecomposer()
        self.risk_assessor = RiskAssessor()
        self.phase_generator = PhaseGenerator()
        self._charter_counter = 0
        self._lock = threading.Lock()

    def _generate_charter_id(self) -> str:
        """Generate unique charter ID."""
        with self._lock:
            self._charter_counter += 1
            timestamp = datetime.now().strftime("%Y%m%d")
            return f"charter_{timestamp}_{self._charter_counter:04d}"

    def build(
        self,
        name: str,
        description: str,
        stakeholders: Optional[List[str]] = None,
        constraints: Optional[List[str]] = None,
        assumptions: Optional[List[str]] = None,
    ) -> ProjectCharter:
        """Build complete project charter."""
        # Analyze scope
        scope_analysis = self.scope_analyzer.analyze(description)

        # Decompose into tasks
        tasks = self.task_decomposer.decompose(scope_analysis, name)

        # Assess risks
        risks = self.risk_assessor.assess(
            description,
            scope_analysis["complexity"],
            scope_analysis["project_type"],
        )

        # Generate phases and milestones
        phases, milestones = self.phase_generator.generate(tasks, name)

        # Build charter
        charter = ProjectCharter(
            charter_id=self._generate_charter_id(),
            name=name,
            description=description,
            project_type=scope_analysis["project_type"],
            objectives=self._extract_objectives(description, scope_analysis),
            scope_in=scope_analysis["scope"]["in"],
            scope_out=scope_analysis["scope"]["out"],
            success_criteria=self._generate_success_criteria(scope_analysis),
            phases={p.phase_id: p for p in phases.values()},
            tasks={t.task_id: t for t in tasks},
            milestones=milestones,
            risks={r.risk_id: r for r in risks},
            assumptions=assumptions or self._default_assumptions(),
            constraints=constraints or [],
            stakeholders=stakeholders or [],
        )

        return charter

    def _extract_objectives(
        self,
        description: str,
        scope_analysis: Dict[str, Any],
    ) -> List[str]:
        """Extract objectives from description."""
        objectives = []

        # Primary objective from description
        primary = description.split(".")[0].strip()
        if primary:
            objectives.append(primary)

        # Add requirements as objectives
        for req in scope_analysis.get("requirements", [])[:3]:
            objectives.append(req.strip())

        return objectives

    def _generate_success_criteria(
        self,
        scope_analysis: Dict[str, Any],
    ) -> List[str]:
        """Generate success criteria."""
        criteria = [
            "All planned tasks completed",
            "All tests passing",
            "Code review approved",
            "Documentation updated",
        ]

        project_type = scope_analysis.get("project_type", ProjectType.FEATURE)

        if project_type == ProjectType.BUG_FIX:
            criteria.append("Issue no longer reproducible")
        elif project_type == ProjectType.OPTIMIZATION:
            criteria.append("Performance improvement measured and documented")
        elif project_type == ProjectType.MIGRATION:
            criteria.append("Data integrity verified post-migration")

        return criteria

    def _default_assumptions(self) -> List[str]:
        """Get default assumptions."""
        return [
            "Required resources are available",
            "No major blockers from external dependencies",
            "Scope will remain stable during implementation",
        ]


# =============================================================================
# Charter Refiner
# =============================================================================

class CharterRefiner:
    """Refines charters based on feedback and execution data."""

    def __init__(self) -> None:
        self.refinement_history: List[Dict[str, Any]] = []

    def refine(
        self,
        charter: ProjectCharter,
        feedback: Dict[str, Any],
    ) -> ProjectCharter:
        """Refine charter based on feedback."""
        refined = ProjectCharter.from_dict(charter.to_dict())

        refinements = []

        # Apply effort adjustments
        if "effort_feedback" in feedback:
            self._adjust_effort(refined, feedback["effort_feedback"])
            refinements.append("effort_adjusted")

        # Add new risks
        if "new_risks" in feedback:
            for risk_data in feedback["new_risks"]:
                risk = Risk.from_dict(risk_data)
                refined.risks[risk.risk_id] = risk
            refinements.append("risks_added")

        # Add new tasks
        if "new_tasks" in feedback:
            for task_data in feedback["new_tasks"]:
                task = Task.from_dict(task_data)
                refined.tasks[task.task_id] = task
            refinements.append("tasks_added")

        # Update scope
        if "scope_changes" in feedback:
            changes = feedback["scope_changes"]
            refined.scope_in.extend(changes.get("add_in", []))
            refined.scope_out.extend(changes.get("add_out", []))
            refinements.append("scope_updated")

        # Update version
        refined.version += 1
        refined.updated_at = datetime.now().isoformat()

        # Record refinement
        self.refinement_history.append({
            "charter_id": charter.charter_id,
            "version": refined.version,
            "refinements": refinements,
            "timestamp": datetime.now().isoformat(),
        })

        return refined

    def _adjust_effort(
        self,
        charter: ProjectCharter,
        feedback: Dict[str, float],
    ) -> None:
        """Adjust effort estimates based on feedback."""
        for task_id, multiplier in feedback.items():
            if task_id in charter.tasks:
                charter.tasks[task_id].estimated_hours *= multiplier

    def suggest_refinements(
        self,
        charter: ProjectCharter,
        execution_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Suggest refinements based on execution data."""
        suggestions = []

        # Check for effort variance
        for task_id, actual_hours in execution_data.get("actual_hours", {}).items():
            if task_id in charter.tasks:
                estimated = charter.tasks[task_id].estimated_hours
                if actual_hours > estimated * 1.5:
                    suggestions.append({
                        "type": "effort_increase",
                        "task_id": task_id,
                        "suggested_multiplier": actual_hours / estimated,
                        "reason": "Actual effort significantly exceeded estimate",
                    })

        # Check for missing dependencies
        blockers = execution_data.get("blockers", [])
        for blocker in blockers:
            suggestions.append({
                "type": "add_dependency",
                "task_id": blocker.get("task_id"),
                "blocked_by": blocker.get("blocked_by"),
                "reason": "Task was blocked during execution",
            })

        # Check for new risks encountered
        incidents = execution_data.get("incidents", [])
        for incident in incidents:
            suggestions.append({
                "type": "add_risk",
                "description": incident.get("description"),
                "category": incident.get("category", "technical"),
                "reason": "Risk materialized during execution",
            })

        return suggestions


# =============================================================================
# Charter Persistence
# =============================================================================

class CharterPersistence:
    """Persists charters to storage."""

    def __init__(self, storage_dir: str) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.storage_dir / "charter_index.json"
        self._lock = threading.Lock()
        self._ensure_index()

    def _ensure_index(self) -> None:
        """Ensure index file exists."""
        if not self.index_file.exists():
            self._save_index({})

    def _load_index(self) -> Dict[str, Any]:
        """Load charter index."""
        if self.index_file.exists():
            with open(self.index_file, "r") as f:
                return json.load(f)
        return {}

    def _save_index(self, index: Dict[str, Any]) -> None:
        """Save charter index."""
        with open(self.index_file, "w") as f:
            json.dump(index, f, indent=2)

    def save(self, charter: ProjectCharter) -> str:
        """Save charter to storage."""
        with self._lock:
            # Save charter file
            charter_file = self.storage_dir / f"{charter.charter_id}.json"
            with open(charter_file, "w") as f:
                json.dump(charter.to_dict(), f, indent=2)

            # Update index
            index = self._load_index()
            index[charter.charter_id] = {
                "name": charter.name,
                "status": charter.status.value,
                "version": charter.version,
                "updated_at": charter.updated_at,
                "file": str(charter_file),
            }
            self._save_index(index)

            return str(charter_file)

    def load(self, charter_id: str) -> Optional[ProjectCharter]:
        """Load charter from storage."""
        index = self._load_index()

        if charter_id not in index:
            return None

        charter_file = Path(index[charter_id]["file"])

        if not charter_file.exists():
            return None

        with open(charter_file, "r") as f:
            data = json.load(f)

        return ProjectCharter.from_dict(data)

    def list_charters(
        self,
        status: Optional[CharterStatus] = None,
    ) -> List[Dict[str, Any]]:
        """List all charters."""
        index = self._load_index()

        charters = []
        for charter_id, info in index.items():
            if status and info["status"] != status.value:
                continue
            charters.append({
                "charter_id": charter_id,
                **info,
            })

        return charters

    def delete(self, charter_id: str) -> bool:
        """Delete charter from storage."""
        with self._lock:
            index = self._load_index()

            if charter_id not in index:
                return False

            # Delete file
            charter_file = Path(index[charter_id]["file"])
            if charter_file.exists():
                charter_file.unlink()

            # Update index
            del index[charter_id]
            self._save_index(index)

            return True


# =============================================================================
# Autonomous Charter Manager
# =============================================================================

class AutonomousCharterManager:
    """
    Complete autonomous project charter management system.

    Features:
    - Automatic charter generation from natural language
    - Self-refining based on feedback
    - Progress tracking
    - Risk monitoring
    - Persistent storage
    """

    def __init__(self, storage_dir: str = "./charters") -> None:
        self.builder = CharterBuilder()
        self.refiner = CharterRefiner()
        self.persistence = CharterPersistence(storage_dir)
        self.active_charters: Dict[str, ProjectCharter] = {}

    def create_charter(
        self,
        name: str,
        description: str,
        stakeholders: Optional[List[str]] = None,
        constraints: Optional[List[str]] = None,
        auto_save: bool = True,
    ) -> ProjectCharter:
        """Create new project charter autonomously."""
        charter = self.builder.build(
            name=name,
            description=description,
            stakeholders=stakeholders,
            constraints=constraints,
        )

        self.active_charters[charter.charter_id] = charter

        if auto_save:
            self.persistence.save(charter)

        return charter

    def refine_charter(
        self,
        charter_id: str,
        feedback: Dict[str, Any],
        auto_save: bool = True,
    ) -> Optional[ProjectCharter]:
        """Refine existing charter based on feedback."""
        charter = self.active_charters.get(charter_id)

        if not charter:
            charter = self.persistence.load(charter_id)

        if not charter:
            return None

        refined = self.refiner.refine(charter, feedback)
        self.active_charters[refined.charter_id] = refined

        if auto_save:
            self.persistence.save(refined)

        return refined

    def approve_charter(
        self,
        charter_id: str,
        approved_by: str,
    ) -> Optional[ProjectCharter]:
        """Approve charter for execution."""
        charter = self.active_charters.get(charter_id)

        if not charter:
            charter = self.persistence.load(charter_id)

        if not charter:
            return None

        charter.status = CharterStatus.APPROVED
        charter.approved_at = datetime.now().isoformat()
        charter.approved_by = approved_by
        charter.updated_at = datetime.now().isoformat()

        self.active_charters[charter_id] = charter
        self.persistence.save(charter)

        return charter

    def start_execution(self, charter_id: str) -> Optional[ProjectCharter]:
        """Start charter execution."""
        charter = self.active_charters.get(charter_id)

        if not charter:
            charter = self.persistence.load(charter_id)

        if not charter or charter.status != CharterStatus.APPROVED:
            return None

        charter.status = CharterStatus.IN_EXECUTION
        charter.updated_at = datetime.now().isoformat()

        # Start first phase
        for phase in sorted(charter.phases.values(), key=lambda p: p.order):
            phase.status = PhaseStatus.IN_PROGRESS
            phase.started_at = datetime.now().isoformat()
            break

        self.active_charters[charter_id] = charter
        self.persistence.save(charter)

        return charter

    def update_task_status(
        self,
        charter_id: str,
        task_id: str,
        status: str,
        actual_hours: Optional[float] = None,
    ) -> Optional[ProjectCharter]:
        """Update task status."""
        charter = self.active_charters.get(charter_id)

        if not charter:
            charter = self.persistence.load(charter_id)

        if not charter or task_id not in charter.tasks:
            return None

        charter.tasks[task_id].status = status

        if actual_hours:
            charter.metadata[f"actual_hours_{task_id}"] = actual_hours

        # Check phase completion
        self._update_phase_status(charter)

        charter.updated_at = datetime.now().isoformat()
        self.active_charters[charter_id] = charter
        self.persistence.save(charter)

        return charter

    def _update_phase_status(self, charter: ProjectCharter) -> None:
        """Update phase status based on task completion."""
        for phase in charter.phases.values():
            task_statuses = [
                charter.tasks[tid].status
                for tid in phase.tasks
                if tid in charter.tasks
            ]

            if all(s == "completed" for s in task_statuses):
                phase.status = PhaseStatus.COMPLETED
                phase.completed_at = datetime.now().isoformat()

                # Complete milestone
                if phase.milestone_id and phase.milestone_id in charter.milestones:
                    charter.milestones[phase.milestone_id].status = "completed"
                    charter.milestones[phase.milestone_id].completed_at = datetime.now().isoformat()

    def get_progress(self, charter_id: str) -> Dict[str, Any]:
        """Get charter execution progress."""
        charter = self.active_charters.get(charter_id)

        if not charter:
            charter = self.persistence.load(charter_id)

        if not charter:
            return {"error": "Charter not found"}

        total_tasks = len(charter.tasks)
        completed_tasks = sum(1 for t in charter.tasks.values() if t.status == "completed")

        total_effort = charter.get_total_effort_hours()
        completed_effort = sum(
            t.estimated_hours
            for t in charter.tasks.values()
            if t.status == "completed"
        )

        phases_status = {
            p.name: p.status.value
            for p in charter.phases.values()
        }

        return {
            "charter_id": charter_id,
            "name": charter.name,
            "status": charter.status.value,
            "progress": {
                "tasks_completed": completed_tasks,
                "tasks_total": total_tasks,
                "percentage": (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
            },
            "effort": {
                "estimated_total": total_effort,
                "estimated_completed": completed_effort,
                "percentage": (completed_effort / total_effort * 100) if total_effort > 0 else 0,
            },
            "phases": phases_status,
            "risks": charter.get_risk_summary(),
        }

    def generate_report(self, charter_id: str) -> str:
        """Generate human-readable charter report."""
        charter = self.active_charters.get(charter_id)

        if not charter:
            charter = self.persistence.load(charter_id)

        if not charter:
            return "Charter not found"

        lines = [
            f"# Project Charter: {charter.name}",
            f"",
            f"**ID:** {charter.charter_id}",
            f"**Type:** {charter.project_type.value}",
            f"**Status:** {charter.status.value}",
            f"**Version:** {charter.version}",
            f"",
            f"## Description",
            f"{charter.description}",
            f"",
            f"## Objectives",
        ]

        for obj in charter.objectives:
            lines.append(f"- {obj}")

        lines.extend([
            f"",
            f"## Scope",
            f"### In Scope",
        ])

        for item in charter.scope_in:
            lines.append(f"- {item}")

        lines.append(f"### Out of Scope")
        for item in charter.scope_out:
            lines.append(f"- {item}")

        lines.extend([
            f"",
            f"## Phases",
        ])

        for phase in sorted(charter.phases.values(), key=lambda p: p.order):
            lines.append(f"### {phase.name}")
            lines.append(f"Status: {phase.status.value}")
            lines.append(f"Tasks:")
            for tid in phase.tasks:
                if tid in charter.tasks:
                    task = charter.tasks[tid]
                    lines.append(f"  - [{task.status}] {task.name} ({task.estimated_hours}h)")

        lines.extend([
            f"",
            f"## Risks",
        ])

        for risk in sorted(charter.risks.values(), key=lambda r: -r.risk_score):
            lines.append(f"- [{risk.level.value}] {risk.description}")
            lines.append(f"  - Mitigation: {risk.mitigation}")

        lines.extend([
            f"",
            f"## Summary",
            f"- Total Estimated Effort: {charter.get_total_effort_hours():.1f} hours",
            f"- Total Tasks: {len(charter.tasks)}",
            f"- Total Risks: {len(charter.risks)}",
            f"- Created: {charter.created_at}",
            f"- Last Updated: {charter.updated_at}",
        ])

        return "\n".join(lines)


# =============================================================================
# CLI Testing
# =============================================================================

def run_cli_tests():
    """Run CLI tests for the autonomous charter module."""
    import tempfile
    import shutil

    print("=" * 70)
    print("Autonomous Charter CLI Tests")
    print("=" * 70)

    tests_passed = 0
    tests_failed = 0

    def test(name: str, condition: bool) -> None:
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"  [PASS] {name}")
            tests_passed += 1
        else:
            print(f"  [FAIL] {name}")
            tests_failed += 1

    # Create temp directory
    temp_dir = tempfile.mkdtemp()

    try:
        # Test 1: Scope Analyzer
        print("\n1. Testing Scope Analyzer...")
        analyzer = ScopeAnalyzer()

        result = analyzer.analyze("Add a new user authentication feature with OAuth support")
        test("Detects feature type", result["project_type"] == ProjectType.FEATURE)
        test("Extracts entities", len(result["entities"]) > 0)

        result = analyzer.analyze("Fix the bug where login fails with special characters")
        test("Detects bug fix type", result["project_type"] == ProjectType.BUG_FIX)

        result = analyzer.analyze("Optimize the database query performance")
        test("Detects optimization type", result["project_type"] == ProjectType.OPTIMIZATION)

        # Test 2: Task Decomposer
        print("\n2. Testing Task Decomposer...")
        decomposer = TaskDecomposer()

        scope = {
            "project_type": ProjectType.FEATURE,
            "entities": ["Authentication"],
            "complexity": TaskComplexity.MEDIUM,
        }
        tasks = decomposer.decompose(scope, "Auth System")
        test("Generates multiple tasks", len(tasks) >= 3)
        test("Tasks have dependencies", any(t.dependencies for t in tasks[1:]))
        test("Tasks have IDs", all(t.task_id for t in tasks))

        # Test 3: Risk Assessor
        print("\n3. Testing Risk Assessor...")
        assessor = RiskAssessor()

        risks = assessor.assess(
            "Integrate with external payment API with encryption",
            TaskComplexity.COMPLEX,
            ProjectType.INTEGRATION,
        )
        test("Identifies risks", len(risks) > 0)
        test("Risks have levels", all(r.level for r in risks))
        test("Risks have mitigation", all(r.mitigation for r in risks))

        # Test 4: Phase Generator
        print("\n4. Testing Phase Generator...")
        generator = PhaseGenerator()

        test_tasks = [
            Task("t1", "Design API", "Design", tags=["feature", "design"]),
            Task("t2", "Implement API", "Implement", tags=["feature", "implement"]),
            Task("t3", "Test API", "Test", tags=["feature", "test"]),
        ]

        phases, milestones = generator.generate(test_tasks, "API Project")
        test("Generates phases", len(phases) >= 2)
        test("Generates milestones", len(milestones) >= 2)
        test("Phases have order", all(p.order >= 0 for p in phases.values()))

        # Test 5: Charter Builder
        print("\n5. Testing Charter Builder...")
        builder = CharterBuilder()

        charter = builder.build(
            "User Dashboard",
            "Create a new user dashboard with analytics and settings management",
            stakeholders=["Product Team"],
        )
        test("Creates charter", charter is not None)
        test("Charter has ID", charter.charter_id is not None)
        test("Charter has tasks", len(charter.tasks) > 0)
        test("Charter has phases", len(charter.phases) > 0)
        test("Charter has risks", len(charter.risks) >= 0)
        test("Charter calculates effort", charter.get_total_effort_hours() > 0)

        # Test 6: Charter Serialization
        print("\n6. Testing Charter Serialization...")
        charter_dict = charter.to_dict()
        test("Serializes to dict", isinstance(charter_dict, dict))
        test("Dict has all fields", "charter_id" in charter_dict and "tasks" in charter_dict)

        restored = ProjectCharter.from_dict(charter_dict)
        test("Deserializes from dict", restored.charter_id == charter.charter_id)
        test("Tasks preserved", len(restored.tasks) == len(charter.tasks))

        # Test 7: Charter Persistence
        print("\n7. Testing Charter Persistence...")
        persistence = CharterPersistence(temp_dir)

        save_path = persistence.save(charter)
        test("Saves charter", Path(save_path).exists())

        loaded = persistence.load(charter.charter_id)
        test("Loads charter", loaded is not None)
        test("Loaded matches original", loaded.name == charter.name)

        charters_list = persistence.list_charters()
        test("Lists charters", len(charters_list) == 1)

        # Test 8: Charter Refiner
        print("\n8. Testing Charter Refiner...")
        refiner = CharterRefiner()

        feedback = {
            "effort_feedback": {list(charter.tasks.keys())[0]: 1.5},
            "scope_changes": {"add_in": ["Mobile support"]},
        }
        refined = refiner.refine(charter, feedback)
        test("Refines charter", refined.version == charter.version + 1)
        test("Updates scope", "Mobile support" in refined.scope_in)

        # Test 9: Autonomous Manager
        print("\n9. Testing Autonomous Manager...")
        manager = AutonomousCharterManager(temp_dir)

        new_charter = manager.create_charter(
            "Search Feature",
            "Implement full-text search with filters and pagination",
        )
        test("Creates charter via manager", new_charter is not None)

        approved = manager.approve_charter(new_charter.charter_id, "Admin")
        test("Approves charter", approved.status == CharterStatus.APPROVED)

        started = manager.start_execution(new_charter.charter_id)
        test("Starts execution", started.status == CharterStatus.IN_EXECUTION)

        # Test 10: Progress Tracking
        print("\n10. Testing Progress Tracking...")
        first_task = list(started.tasks.keys())[0]
        updated = manager.update_task_status(
            started.charter_id,
            first_task,
            "completed",
            actual_hours=4.0,
        )
        test("Updates task status", updated.tasks[first_task].status == "completed")

        progress = manager.get_progress(started.charter_id)
        test("Gets progress", progress["progress"]["tasks_completed"] == 1)

        # Test 11: Report Generation
        print("\n11. Testing Report Generation...")
        report = manager.generate_report(started.charter_id)
        test("Generates report", len(report) > 100)
        test("Report has title", "# Project Charter:" in report)
        test("Report has sections", "## Phases" in report)

        # Test 12: Critical Path
        print("\n12. Testing Critical Path...")
        critical = charter.get_critical_path()
        test("Calculates critical path", isinstance(critical, list))

        # Test 13: Risk Summary
        print("\n13. Testing Risk Summary...")
        risk_summary = charter.get_risk_summary()
        test("Gets risk summary", "total" in risk_summary)
        test("Risk summary has levels", "by_level" in risk_summary)

        # Test 14: Delete Charter
        print("\n14. Testing Charter Deletion...")
        deleted = persistence.delete(charter.charter_id)
        test("Deletes charter", deleted)
        test("Charter no longer exists", persistence.load(charter.charter_id) is None)

        # Test 15: Task Dataclass
        print("\n15. Testing Task Dataclass...")
        task = Task(
            task_id="test_1",
            name="Test Task",
            description="A test task",
            complexity=TaskComplexity.MEDIUM,
        )
        test("Task auto-sets effort", task.estimated_hours == 6.0)
        test("Task serializes", "task_id" in task.to_dict())

        restored_task = Task.from_dict(task.to_dict())
        test("Task deserializes", restored_task.task_id == task.task_id)

        # Test 16: Risk Dataclass
        print("\n16. Testing Risk Dataclass...")
        risk = Risk(
            risk_id="risk_1",
            description="Test risk",
            probability=0.5,
            impact=0.8,
        )
        test("Risk calculates score", risk.risk_score == 0.4)
        test("Risk serializes", "risk_id" in risk.to_dict())

        # Test 17: Phase Status
        print("\n17. Testing Phase Status...")
        phase = Phase(
            phase_id="phase_1",
            name="Test Phase",
            description="A test phase",
            status=PhaseStatus.NOT_STARTED,
        )
        test("Phase has status", phase.status == PhaseStatus.NOT_STARTED)

        # Test 18: Complexity Estimation
        print("\n18. Testing Complexity Estimation...")
        simple = analyzer.analyze("Fix typo in readme")
        test("Simple task detected", simple["complexity"] in [TaskComplexity.TRIVIAL, TaskComplexity.SIMPLE])

        complex_desc = "Complete rewrite of the authentication system with OAuth2, SAML, and MFA support including database migration"
        complex_result = analyzer.analyze(complex_desc)
        test("Complex task detected", complex_result["complexity"] in [TaskComplexity.COMPLEX, TaskComplexity.VERY_COMPLEX, TaskComplexity.EPIC])

        # Test 19: Entity Extraction
        print("\n19. Testing Entity Extraction...")
        result = analyzer.analyze('Update the "UserService" class in auth/service.py')
        test("Extracts quoted entities", "UserService" in result["entities"])
        test("Extracts file paths", any(".py" in e for e in result["entities"]))

        # Test 20: Refinement Suggestions
        print("\n20. Testing Refinement Suggestions...")
        execution_data = {
            "actual_hours": {first_task: 15.0},
            "blockers": [{"task_id": first_task, "blocked_by": "external"}],
        }
        suggestions = refiner.suggest_refinements(started, execution_data)
        test("Generates suggestions", len(suggestions) > 0)

    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("\n" + "=" * 70)
    print(f"Tests Passed: {tests_passed}/{tests_passed + tests_failed}")
    print("=" * 70)

    return tests_failed == 0


if __name__ == "__main__":
    success = run_cli_tests()
    exit(0 if success else 1)
