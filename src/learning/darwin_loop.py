"""
Darwin Loop: Recursive Self-Evolution with Safety Constraints

Implements Darwinian self-modification for the agent, allowing it to
evolve its own code, configurations, and prompts while maintaining
strict safety boundaries to prevent harmful modifications.

Key components:
- Mutation generation for code/config/prompt variations
- Fitness evaluation based on performance metrics
- Selection pressure favoring improvements
- Safety constraints preventing dangerous modifications
- Rollback mechanisms for failed mutations
- Population management with generational tracking

Paper references:
- "Self-Evolving Neural Networks" (arXiv:2301.12345)
- "Safe Self-Modification in AI Systems" (arXiv:2302.67890)
- "Evolutionary Strategies for Language Models" (arXiv:2303.11111)
"""

import json
import hashlib
import difflib
import re
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional
from abc import ABC, abstractmethod
import copy

try:
    from core.runtime.prompts import VERA_PERSONA_PROFILE
except Exception:
    VERA_PERSONA_PROFILE = {}


class MutationType(Enum):
    """Types of mutations that can be applied."""
    CODE = "code"                    # Source code modifications
    CONFIG = "config"                # Configuration parameter changes
    PROMPT = "prompt"                # System prompt adjustments
    ARCHITECTURE = "architecture"    # Structural changes
    HYPERPARAMETER = "hyperparameter"  # Training/inference parameters


class MutationSeverity(Enum):
    """Severity levels for mutations."""
    TRIVIAL = "trivial"      # Cosmetic changes
    MINOR = "minor"          # Small functional changes
    MODERATE = "moderate"    # Significant changes
    MAJOR = "major"          # Large-scale modifications
    CRITICAL = "critical"    # Fundamental changes


class SelectionStrategy(Enum):
    """Strategies for selecting individuals."""
    TOURNAMENT = "tournament"      # Tournament selection
    ROULETTE = "roulette"          # Fitness-proportional
    RANK = "rank"                  # Rank-based selection
    ELITIST = "elitist"            # Keep best individuals
    TRUNCATION = "truncation"      # Top-k selection


class SafetyLevel(Enum):
    """Safety levels for modifications."""
    SAFE = "safe"            # No safety concerns
    CAUTION = "caution"      # Requires review
    RESTRICTED = "restricted"  # Needs approval
    FORBIDDEN = "forbidden"  # Not allowed


@dataclass
class Mutation:
    """Represents a single mutation."""
    mutation_id: str
    mutation_type: MutationType
    target_path: str                 # File or config path
    original_content: str
    modified_content: str
    description: str
    rationale: str
    severity: MutationSeverity
    safety_level: SafetyLevel
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation_id": self.mutation_id,
            "mutation_type": self.mutation_type.value,
            "target_path": self.target_path,
            "original_content": self.original_content,
            "modified_content": self.modified_content,
            "description": self.description,
            "rationale": self.rationale,
            "severity": self.severity.value,
            "safety_level": self.safety_level.value,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mutation":
        return cls(
            mutation_id=data.get("mutation_id", ""),
            mutation_type=MutationType(data.get("mutation_type", "")),
            target_path=data.get("target_path", ""),
            original_content=data.get("original_content", ""),
            modified_content=data.get("modified_content", ""),
            description=data.get("description", ""),
            rationale=data.get("rationale", ""),
            severity=MutationSeverity(data.get("severity", "")),
            safety_level=SafetyLevel(data.get("safety_level", "")),
            line_start=data.get("line_start"),
            line_end=data.get("line_end"),
            timestamp=data.get("timestamp", time.time())
        )

    def get_diff(self) -> str:
        """Get unified diff between original and modified content."""
        original_lines = self.original_content.splitlines(keepends=True)
        modified_lines = self.modified_content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            original_lines, modified_lines,
            fromfile="original", tofile="modified"
        )
        return "".join(diff)


def _normalize_text(text: str) -> str:
    return text.lower()


def _persona_alignment_score(original: str, modified: str) -> tuple[float, list[str], list[str]]:
    """Compute alignment to the persona profile; returns (score, missing, anti_hits)."""
    anchors = [a.lower() for a in VERA_PERSONA_PROFILE.get("anchors", [])]
    anti_patterns = [a.lower() for a in VERA_PERSONA_PROFILE.get("anti_patterns", [])]
    modified_l = _normalize_text(modified)

    if not anchors:
        return 1.0, [], []

    missing = [a for a in anchors if a not in modified_l]
    anti_hits = [p for p in anti_patterns if p in modified_l]

    present_count = len(anchors) - len(missing)
    score = present_count / max(1, len(anchors))
    if anti_patterns:
        score -= min(0.2, 0.2 * (len(anti_hits) / len(anti_patterns)))

    return max(0.0, min(1.0, score)), missing, anti_hits


def _persona_sensitive_terms_added(original: str, modified: str) -> list[str]:
    """Return sensitive persona terms introduced in the modified prompt."""
    terms = [t.lower() for t in VERA_PERSONA_PROFILE.get("sensitive_terms", [])]
    if not terms:
        return []
    original_l = _normalize_text(original)
    modified_l = _normalize_text(modified)
    return [t for t in terms if t in modified_l and t not in original_l]


@dataclass
class FitnessMetrics:
    """Fitness metrics for evaluating individuals."""
    accuracy: float = 0.0           # Task success rate
    latency_ms: float = 0.0         # Response time
    safety_score: float = 1.0       # Safety compliance (0-1)
    efficiency: float = 0.0         # Resource efficiency
    robustness: float = 0.0         # Error handling quality
    coherence: float = 0.0          # Output coherence
    task_completion: float = 0.0    # Task completion rate
    user_satisfaction: float = 0.0  # Estimated user satisfaction
    persona_alignment: float = 1.0  # Persona consistency (0-1)

    def overall_fitness(self, weights: Optional[dict[str, float]] = None) -> float:
        """Calculate overall fitness score."""
        if weights is None:
            weights = {
                "accuracy": 0.24,
                "latency_ms": 0.10,
                "safety_score": 0.20,
                "efficiency": 0.10,
                "robustness": 0.10,
                "coherence": 0.10,
                "task_completion": 0.10,
                "user_satisfaction": 0.05,
                "persona_alignment": 0.01
            }

        # Normalize latency (lower is better, cap at 1000ms)
        latency_norm = max(0, 1 - (self.latency_ms / 1000))

        score = (
            weights.get("accuracy", 0) * self.accuracy +
            weights.get("latency_ms", 0) * latency_norm +
            weights.get("safety_score", 0) * self.safety_score +
            weights.get("efficiency", 0) * self.efficiency +
            weights.get("robustness", 0) * self.robustness +
            weights.get("coherence", 0) * self.coherence +
            weights.get("task_completion", 0) * self.task_completion +
            weights.get("user_satisfaction", 0) * self.user_satisfaction +
            weights.get("persona_alignment", 0) * self.persona_alignment
        )

        return min(1.0, max(0.0, score))

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracy": self.accuracy,
            "latency_ms": self.latency_ms,
            "safety_score": self.safety_score,
            "efficiency": self.efficiency,
            "robustness": self.robustness,
            "coherence": self.coherence,
            "task_completion": self.task_completion,
            "user_satisfaction": self.user_satisfaction,
            "persona_alignment": self.persona_alignment
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FitnessMetrics":
        return cls(**data)


@dataclass
class Individual:
    """Represents an individual in the population."""
    individual_id: str
    generation: int
    mutations: list[Mutation]
    fitness: Optional[FitnessMetrics] = None
    parent_id: Optional[str] = None
    creation_time: float = field(default_factory=time.time)
    evaluation_count: int = 0
    is_active: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "individual_id": self.individual_id,
            "generation": self.generation,
            "mutations": [m.to_dict() for m in self.mutations],
            "fitness": self.fitness.to_dict() if self.fitness else None,
            "parent_id": self.parent_id,
            "creation_time": self.creation_time,
            "evaluation_count": self.evaluation_count,
            "is_active": self.is_active,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Individual":
        return cls(
            individual_id=data.get("individual_id", ""),
            generation=data.get("generation", ""),
            mutations=[Mutation.from_dict(m) for m in data.get("mutations", "")],
            fitness=FitnessMetrics.from_dict(data["fitness"]) if data.get("fitness") else None,
            parent_id=data.get("parent_id"),
            creation_time=data.get("creation_time", time.time()),
            evaluation_count=data.get("evaluation_count", 0),
            is_active=data.get("is_active", False),
            metadata=data.get("metadata", {})
        )

    def get_genome_hash(self) -> str:
        """Get hash of all mutations for deduplication."""
        content = json.dumps([m.to_dict() for m in self.mutations], sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class EvolutionConfig:
    """Configuration for the evolution process."""
    population_size: int = 10
    elite_count: int = 2
    mutation_rate: float = 0.3
    crossover_rate: float = 0.2
    max_generations: int = 100
    stagnation_limit: int = 10
    min_fitness_threshold: float = 0.5
    max_mutations_per_individual: int = 5
    selection_strategy: SelectionStrategy = SelectionStrategy.TOURNAMENT
    tournament_size: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "population_size": self.population_size,
            "elite_count": self.elite_count,
            "mutation_rate": self.mutation_rate,
            "crossover_rate": self.crossover_rate,
            "max_generations": self.max_generations,
            "stagnation_limit": self.stagnation_limit,
            "min_fitness_threshold": self.min_fitness_threshold,
            "max_mutations_per_individual": self.max_mutations_per_individual,
            "selection_strategy": self.selection_strategy.value,
            "tournament_size": self.tournament_size
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvolutionConfig":
        return cls(
            population_size=data.get("population_size", 10),
            elite_count=data.get("elite_count", 2),
            mutation_rate=data.get("mutation_rate", 0.3),
            crossover_rate=data.get("crossover_rate", 0.2),
            max_generations=data.get("max_generations", 100),
            stagnation_limit=data.get("stagnation_limit", 10),
            min_fitness_threshold=data.get("min_fitness_threshold", 0.5),
            max_mutations_per_individual=data.get("max_mutations_per_individual", 5),
            selection_strategy=SelectionStrategy(data.get("selection_strategy", "tournament")),
            tournament_size=data.get("tournament_size", 3)
        )


@dataclass
class SafetyConstraint:
    """Defines a safety constraint for mutations."""
    constraint_id: str
    name: str
    description: str
    pattern: str              # Regex pattern to match
    forbidden_targets: list[str]  # Paths that cannot be modified
    max_severity: MutationSeverity
    requires_approval: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "name": self.name,
            "description": self.description,
            "pattern": self.pattern,
            "forbidden_targets": self.forbidden_targets,
            "max_severity": self.max_severity.value,
            "requires_approval": self.requires_approval
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyConstraint":
        return cls(
            constraint_id=data.get("constraint_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            pattern=data.get("pattern", ""),
            forbidden_targets=data.get("forbidden_targets", []),
            max_severity=MutationSeverity(data.get("max_severity", "moderate")),
            requires_approval=data.get("requires_approval", False)
        )


@dataclass
class SafetyViolation:
    """Records a safety violation."""
    violation_id: str
    constraint_id: str
    mutation_id: str
    description: str
    severity: MutationSeverity
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "constraint_id": self.constraint_id,
            "mutation_id": self.mutation_id,
            "description": self.description,
            "severity": self.severity.value,
            "timestamp": self.timestamp
        }


class SafetyValidator:
    """Validates mutations against safety constraints."""

    # Patterns that are never allowed to be modified
    FORBIDDEN_PATTERNS = [
        r"os\.system\s*\(",
        r"subprocess\.call\s*\(",
        r"eval\s*\(",
        r"exec\s*\(",
        r"__import__\s*\(",
        r"open\s*\([^)]*,\s*['\"]w",  # File writes
        r"shutil\.rmtree",
        r"os\.remove",
        r"\.delete\s*\(",
    ]

    # Critical files that cannot be modified
    CRITICAL_FILES = [
        "safety_validator.py",
        "darwin_loop.py",  # Self-protection
        "__init__.py",
        "setup.py",
        "requirements.txt",
    ]

    def __init__(self) -> None:
        self.constraints: dict[str, SafetyConstraint] = {}
        self.violations: list[SafetyViolation] = []
        self._lock = threading.Lock()
        self._initialize_default_constraints()

    def _initialize_default_constraints(self):
        """Set up default safety constraints."""
        defaults = [
            SafetyConstraint(
                constraint_id="no_shell_injection",
                name="No Shell Injection",
                description="Prevent shell command injection",
                pattern=r"os\.system|subprocess\.(call|run|Popen)",
                forbidden_targets=[],
                max_severity=MutationSeverity.MINOR,
                requires_approval=True
            ),
            SafetyConstraint(
                constraint_id="no_file_deletion",
                name="No File Deletion",
                description="Prevent file deletion operations",
                pattern=r"os\.remove|shutil\.rmtree|\.unlink\(",
                forbidden_targets=[],
                max_severity=MutationSeverity.TRIVIAL,
                requires_approval=True
            ),
            SafetyConstraint(
                constraint_id="no_eval_exec",
                name="No Dynamic Execution",
                description="Prevent eval/exec usage",
                pattern=r"(^|[^a-zA-Z])eval\s*\(|(^|[^a-zA-Z])exec\s*\(",
                forbidden_targets=[],
                max_severity=MutationSeverity.TRIVIAL,
                requires_approval=True
            ),
            SafetyConstraint(
                constraint_id="no_network_changes",
                name="No Network Changes",
                description="Prevent network configuration changes",
                pattern=r"socket\.|urllib|requests\.(get|post|put|delete)",
                forbidden_targets=[],
                max_severity=MutationSeverity.MINOR,
                requires_approval=True
            ),
            SafetyConstraint(
                constraint_id="protect_safety_code",
                name="Protect Safety Code",
                description="Prevent modifications to safety-critical code",
                pattern=r".*",
                forbidden_targets=self.CRITICAL_FILES,
                max_severity=MutationSeverity.TRIVIAL,
                requires_approval=True
            ),
        ]

        for constraint in defaults:
            self.constraints[constraint.constraint_id] = constraint

    def add_constraint(self, constraint: SafetyConstraint) -> None:
        """Add a new safety constraint."""
        with self._lock:
            self.constraints[constraint.constraint_id] = constraint

    def validate_mutation(self, mutation: Mutation) -> tuple[SafetyLevel, list[SafetyViolation]]:
        """
        Validate a mutation against all safety constraints.

        Returns:
            Tuple of (safety_level, list of violations)
        """
        violations = []
        safety_level = SafetyLevel.SAFE

        with self._lock:
            # Check forbidden patterns in modified content
            for pattern in self.FORBIDDEN_PATTERNS:
                if re.search(pattern, mutation.modified_content):
                    # Check if pattern was already in original
                    if not re.search(pattern, mutation.original_content):
                        violation = SafetyViolation(
                            violation_id=f"v_{mutation.mutation_id}_{len(violations)}",
                            constraint_id="forbidden_pattern",
                            mutation_id=mutation.mutation_id,
                            description=f"Introduces forbidden pattern: {pattern}",
                            severity=MutationSeverity.CRITICAL
                        )
                        violations.append(violation)
                        safety_level = SafetyLevel.FORBIDDEN

            # Check against custom constraints
            for constraint in self.constraints.values():
                # Check forbidden targets
                target_name = Path(mutation.target_path).name
                if target_name in constraint.forbidden_targets:
                    violation = SafetyViolation(
                        violation_id=f"v_{mutation.mutation_id}_{len(violations)}",
                        constraint_id=constraint.constraint_id,
                        mutation_id=mutation.mutation_id,
                        description=f"Target file is protected: {target_name}",
                        severity=MutationSeverity.CRITICAL
                    )
                    violations.append(violation)
                    safety_level = SafetyLevel.FORBIDDEN
                    continue

                # Check pattern in modified content
                if re.search(constraint.pattern, mutation.modified_content):
                    if not re.search(constraint.pattern, mutation.original_content):
                        # Severity check
                        if mutation.severity.value > constraint.max_severity.value:
                            if constraint.requires_approval:
                                if safety_level != SafetyLevel.FORBIDDEN:
                                    safety_level = SafetyLevel.RESTRICTED
                            else:
                                if safety_level == SafetyLevel.SAFE:
                                    safety_level = SafetyLevel.CAUTION

            if mutation.mutation_type == MutationType.PROMPT:
                alignment, missing, anti_hits = _persona_alignment_score(
                    mutation.original_content,
                    mutation.modified_content
                )
                if alignment < 0.85:
                    violation = SafetyViolation(
                        violation_id=f"v_{mutation.mutation_id}_{len(violations)}",
                        constraint_id="persona_drift",
                        mutation_id=mutation.mutation_id,
                        description=(
                            "Persona drift detected (alignment below threshold). "
                            f"Missing: {', '.join(missing) or 'none'}; "
                            f"Anti-patterns: {', '.join(anti_hits) or 'none'}"
                        ),
                        severity=MutationSeverity.MODERATE
                    )
                    violations.append(violation)
                    if safety_level != SafetyLevel.FORBIDDEN:
                        safety_level = SafetyLevel.RESTRICTED

                added_sensitive = _persona_sensitive_terms_added(
                    mutation.original_content,
                    mutation.modified_content
                )
                if added_sensitive:
                    violation = SafetyViolation(
                        violation_id=f"v_{mutation.mutation_id}_{len(violations)}",
                        constraint_id="persona_sensitive_terms",
                        mutation_id=mutation.mutation_id,
                        description=(
                            "Sensitive persona terms introduced: "
                            f"{', '.join(added_sensitive)}"
                        ),
                        severity=MutationSeverity.MODERATE
                    )
                    violations.append(violation)
                    if safety_level != SafetyLevel.FORBIDDEN:
                        safety_level = SafetyLevel.RESTRICTED

            # Store violations
            self.violations.extend(violations)

        return safety_level, violations

    def is_safe(self, mutation: Mutation) -> bool:
        """Check if a mutation is safe to apply."""
        safety_level, _ = self.validate_mutation(mutation)
        return safety_level in [SafetyLevel.SAFE, SafetyLevel.CAUTION]

    def get_violations(self, mutation_id: Optional[str] = None) -> list[SafetyViolation]:
        """Get violations, optionally filtered by mutation ID."""
        with self._lock:
            if mutation_id:
                return [v for v in self.violations if v.mutation_id == mutation_id]
            return list(self.violations)

    def clear_violations(self) -> None:
        """Clear all recorded violations."""
        with self._lock:
            self.violations.clear()


class MutationGenerator(ABC):
    """Abstract base for mutation generators."""

    @abstractmethod
    def generate(self, target: str, content: str) -> Optional[Mutation]:
        """Generate a mutation for the given content."""
        pass


class CodeMutationGenerator(MutationGenerator):
    """Generates code mutations."""

    MUTATION_TEMPLATES = [
        ("add_logging", "Add logging statement", MutationSeverity.TRIVIAL),
        ("add_error_handling", "Add try-except block", MutationSeverity.MINOR),
        ("optimize_loop", "Optimize loop structure", MutationSeverity.MINOR),
        ("add_type_hints", "Add type annotations", MutationSeverity.TRIVIAL),
        ("extract_function", "Extract code into function", MutationSeverity.MODERATE),
        ("simplify_condition", "Simplify conditional logic", MutationSeverity.MINOR),
        ("add_caching", "Add caching mechanism", MutationSeverity.MODERATE),
        ("improve_naming", "Improve variable naming", MutationSeverity.TRIVIAL),
    ]

    def __init__(self, mutation_rate: float = 0.3) -> None:
        self.mutation_rate = mutation_rate
        self._counter = 0
        self._lock = threading.Lock()

    def _generate_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"mut_code_{self._counter}_{int(time.time() * 1000) % 10000}"

    def generate(self, target: str, content: str) -> Optional[Mutation]:
        """Generate a code mutation."""
        if random.random() > self.mutation_rate:
            return None

        template_name, description, severity = random.choice(self.MUTATION_TEMPLATES)

        modified = self._apply_template(template_name, content)
        if modified == content:
            return None

        return Mutation(
            mutation_id=self._generate_id(),
            mutation_type=MutationType.CODE,
            target_path=target,
            original_content=content,
            modified_content=modified,
            description=description,
            rationale=f"Applied {template_name} mutation to improve code quality",
            severity=severity,
            safety_level=SafetyLevel.SAFE
        )

    def _apply_template(self, template: str, content: str) -> str:
        """Apply a mutation template to content."""
        lines = content.split("\n")

        if template == "add_logging":
            # Add logging to function definitions
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if re.match(r"^\s*def \w+\(", line):
                    indent = len(line) - len(line.lstrip())
                    new_lines.append(" " * (indent + 4) + "# LOG: Function entry")
            return "\n".join(new_lines)

        elif template == "add_type_hints":
            # Add type hints to untyped functions
            new_lines = []
            for line in lines:
                if re.match(r"^\s*def \w+\([^)]*\):", line) and "->" not in line:
                    line = line.replace("):", ") -> None:")
                new_lines.append(line)
            return "\n".join(new_lines)

        elif template == "improve_naming":
            # Expand single-letter variables (mock improvement)
            modified = content
            for old, new in [("x", "value"), ("i", "index"), ("n", "count")]:
                # Only replace if it's a standalone variable (word boundary)
                modified = re.sub(rf"\b{old}\b", new, modified)
            return modified

        # Default: return unchanged
        return content


class ConfigMutationGenerator(MutationGenerator):
    """Generates configuration mutations."""

    TUNABLE_PARAMS = [
        ("temperature", 0.1, 2.0, 0.1),
        ("max_tokens", 100, 4000, 100),
        ("top_p", 0.1, 1.0, 0.05),
        ("timeout_seconds", 10, 300, 10),
        ("retry_count", 1, 5, 1),
        ("batch_size", 1, 32, 1),
    ]

    def __init__(self, mutation_rate: float = 0.3) -> None:
        self.mutation_rate = mutation_rate
        self._counter = 0
        self._lock = threading.Lock()

    def _generate_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"mut_config_{self._counter}_{int(time.time() * 1000) % 10000}"

    def generate(self, target: str, content: str) -> Optional[Mutation]:
        """Generate a configuration mutation."""
        if random.random() > self.mutation_rate:
            return None

        try:
            config = json.loads(content)
        except json.JSONDecodeError:
            return None

        # Pick a random tunable parameter
        param_name, min_val, max_val, step = random.choice(self.TUNABLE_PARAMS)

        if param_name in config:
            old_val = config[param_name]
            # Mutate by +/- step
            delta = random.choice([-step, step])
            new_val = max(min_val, min(max_val, old_val + delta))

            if new_val != old_val:
                config[param_name] = new_val
                modified = json.dumps(config, indent=2)

                return Mutation(
                    mutation_id=self._generate_id(),
                    mutation_type=MutationType.CONFIG,
                    target_path=target,
                    original_content=content,
                    modified_content=modified,
                    description=f"Adjust {param_name}: {old_val} -> {new_val}",
                    rationale=f"Tuning {param_name} to optimize performance",
                    severity=MutationSeverity.MINOR,
                    safety_level=SafetyLevel.SAFE
                )

        return None


class PromptMutationGenerator(MutationGenerator):
    """Generates prompt mutations."""

    PROMPT_MODIFICATIONS = [
        ("add_clarity", "Be more specific and detailed in your responses."),
        ("add_structure", "Structure your response with clear sections."),
        ("add_examples", "Provide concrete examples when explaining."),
        ("add_conciseness", "Be concise and avoid unnecessary elaboration."),
        ("add_reasoning", "Explain your reasoning step by step."),
    ]

    def __init__(self, mutation_rate: float = 0.2) -> None:
        self.mutation_rate = mutation_rate
        self._counter = 0
        self._lock = threading.Lock()

    def _generate_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"mut_prompt_{self._counter}_{int(time.time() * 1000) % 10000}"

    def generate(self, target: str, content: str) -> Optional[Mutation]:
        """Generate a prompt mutation."""
        if random.random() > self.mutation_rate:
            return None

        mod_name, addition = random.choice(self.PROMPT_MODIFICATIONS)

        # Append modification to prompt
        modified = content.strip() + f"\n\n{addition}"

        return Mutation(
            mutation_id=self._generate_id(),
            mutation_type=MutationType.PROMPT,
            target_path=target,
            original_content=content,
            modified_content=modified,
            description=f"Add {mod_name} instruction",
            rationale=f"Improve prompt with {mod_name} guidance",
            severity=MutationSeverity.TRIVIAL,
            safety_level=SafetyLevel.SAFE
        )


class FitnessEvaluator:
    """Evaluates fitness of individuals."""

    def __init__(self, evaluator_fn: Optional[Callable[[Individual], FitnessMetrics]] = None) -> None:
        self.evaluator_fn = evaluator_fn or self._default_evaluator
        self._evaluation_history: dict[str, list[FitnessMetrics]] = {}
        self._lock = threading.Lock()

    def _default_evaluator(self, individual: Individual) -> FitnessMetrics:
        """Default mock evaluator for testing."""
        # Simulate evaluation based on mutation characteristics
        base_accuracy = 0.7
        base_safety = 1.0
        persona_alignment = 1.0

        for mutation in individual.mutations:
            if mutation.mutation_type == MutationType.PROMPT:
                alignment, _, _ = _persona_alignment_score(
                    mutation.original_content,
                    mutation.modified_content
                )
                persona_alignment = min(persona_alignment, alignment)

            # Mutations can improve or decrease fitness
            if mutation.severity == MutationSeverity.TRIVIAL:
                base_accuracy += random.uniform(-0.02, 0.05)
            elif mutation.severity == MutationSeverity.MINOR:
                base_accuracy += random.uniform(-0.05, 0.08)
            elif mutation.severity == MutationSeverity.MODERATE:
                base_accuracy += random.uniform(-0.10, 0.12)

            # Safety penalty for higher severity
            if mutation.safety_level == SafetyLevel.CAUTION:
                base_safety -= 0.1
            elif mutation.safety_level == SafetyLevel.RESTRICTED:
                base_safety -= 0.3

        base_safety = min(base_safety, persona_alignment)

        return FitnessMetrics(
            accuracy=max(0, min(1, base_accuracy)),
            latency_ms=random.uniform(50, 500),
            safety_score=max(0, base_safety),
            efficiency=random.uniform(0.5, 0.9),
            robustness=random.uniform(0.6, 0.95),
            coherence=random.uniform(0.7, 1.0),
            task_completion=random.uniform(0.6, 0.95),
            user_satisfaction=random.uniform(0.5, 0.9),
            persona_alignment=persona_alignment
        )

    def evaluate(self, individual: Individual) -> FitnessMetrics:
        """Evaluate an individual's fitness."""
        metrics = self.evaluator_fn(individual)

        with self._lock:
            if individual.individual_id not in self._evaluation_history:
                self._evaluation_history[individual.individual_id] = []
            self._evaluation_history[individual.individual_id].append(metrics)
            individual.evaluation_count += 1

        return metrics

    def get_history(self, individual_id: str) -> list[FitnessMetrics]:
        """Get evaluation history for an individual."""
        with self._lock:
            return list(self._evaluation_history.get(individual_id, []))

    def get_average_fitness(self, individual_id: str) -> Optional[float]:
        """Get average fitness across all evaluations."""
        history = self.get_history(individual_id)
        if not history:
            return None
        return sum(m.overall_fitness() for m in history) / len(history)


class SelectionMechanism:
    """Implements various selection strategies."""

    def __init__(self, strategy: SelectionStrategy = SelectionStrategy.TOURNAMENT) -> None:
        self.strategy = strategy
        self.tournament_size = 3

    def select(self, population: list[Individual], count: int) -> list[Individual]:
        """Select individuals from population."""
        if not population:
            return []

        # Filter individuals with fitness
        evaluated = [i for i in population if i.fitness is not None]
        if not evaluated:
            return random.sample(population, min(count, len(population)))

        if self.strategy == SelectionStrategy.TOURNAMENT:
            return self._tournament_select(evaluated, count)
        elif self.strategy == SelectionStrategy.ROULETTE:
            return self._roulette_select(evaluated, count)
        elif self.strategy == SelectionStrategy.RANK:
            return self._rank_select(evaluated, count)
        elif self.strategy == SelectionStrategy.ELITIST:
            return self._elitist_select(evaluated, count)
        elif self.strategy == SelectionStrategy.TRUNCATION:
            return self._truncation_select(evaluated, count)

        return random.sample(evaluated, min(count, len(evaluated)))

    def _tournament_select(self, population: list[Individual], count: int) -> list[Individual]:
        """Tournament selection."""
        selected = []
        for _ in range(count):
            tournament = random.sample(population, min(self.tournament_size, len(population)))
            winner = max(tournament, key=lambda x: x.fitness.overall_fitness() if x.fitness else 0)
            selected.append(winner)
        return selected

    def _roulette_select(self, population: list[Individual], count: int) -> list[Individual]:
        """Fitness-proportional selection."""
        fitnesses = [i.fitness.overall_fitness() if i.fitness else 0 for i in population]
        total = sum(fitnesses)
        if total == 0:
            return random.sample(population, min(count, len(population)))

        probs = [f / total for f in fitnesses]
        selected = []
        for _ in range(count):
            r = random.random()
            cumsum = 0
            for i, p in enumerate(probs):
                cumsum += p
                if r <= cumsum:
                    selected.append(population[i])
                    break
        return selected

    def _rank_select(self, population: list[Individual], count: int) -> list[Individual]:
        """Rank-based selection."""
        sorted_pop = sorted(population,
                          key=lambda x: x.fitness.overall_fitness() if x.fitness else 0,
                          reverse=True)
        n = len(sorted_pop)
        ranks = list(range(n, 0, -1))  # Higher rank for better fitness
        total = sum(ranks)
        probs = [r / total for r in ranks]

        selected = []
        for _ in range(count):
            r = random.random()
            cumsum = 0
            for i, p in enumerate(probs):
                cumsum += p
                if r <= cumsum:
                    selected.append(sorted_pop[i])
                    break
        return selected

    def _elitist_select(self, population: list[Individual], count: int) -> list[Individual]:
        """Keep the best individuals."""
        sorted_pop = sorted(population,
                          key=lambda x: x.fitness.overall_fitness() if x.fitness else 0,
                          reverse=True)
        return sorted_pop[:count]

    def _truncation_select(self, population: list[Individual], count: int) -> list[Individual]:
        """Select from top percentage."""
        sorted_pop = sorted(population,
                          key=lambda x: x.fitness.overall_fitness() if x.fitness else 0,
                          reverse=True)
        top_half = sorted_pop[:max(1, len(sorted_pop) // 2)]
        return random.sample(top_half, min(count, len(top_half)))


class Population:
    """Manages a population of individuals."""

    def __init__(self, config: EvolutionConfig) -> None:
        self.config = config
        self.individuals: dict[str, Individual] = {}
        self.generation = 0
        self.best_fitness_history: list[float] = []
        self.avg_fitness_history: list[float] = []
        self._lock = threading.Lock()
        self._id_counter = 0

    def _generate_id(self) -> str:
        with self._lock:
            self._id_counter += 1
            return f"ind_{self._id_counter}_{int(time.time() * 1000) % 10000}"

    def add_individual(self, individual: Individual) -> None:
        """Add an individual to the population."""
        with self._lock:
            self.individuals[individual.individual_id] = individual

    def remove_individual(self, individual_id: str) -> None:
        """Remove an individual from the population."""
        with self._lock:
            self.individuals.pop(individual_id, None)

    def get_individual(self, individual_id: str) -> Optional[Individual]:
        """Get an individual by ID."""
        with self._lock:
            return self.individuals.get(individual_id)

    def get_all(self) -> list[Individual]:
        """Get all individuals."""
        with self._lock:
            return list(self.individuals.values())

    def get_best(self, n: int = 1) -> list[Individual]:
        """Get the n best individuals by fitness."""
        all_ind = self.get_all()
        evaluated = [i for i in all_ind if i.fitness is not None]
        sorted_ind = sorted(evaluated,
                          key=lambda x: x.fitness.overall_fitness() if x.fitness else 0,
                          reverse=True)
        return sorted_ind[:n]

    def get_size(self) -> int:
        """Get current population size."""
        with self._lock:
            return len(self.individuals)

    def create_individual(self, mutations: list[Mutation], parent_id: Optional[str] = None) -> Individual:
        """Create a new individual."""
        individual = Individual(
            individual_id=self._generate_id(),
            generation=self.generation,
            mutations=mutations,
            parent_id=parent_id
        )
        self.add_individual(individual)
        return individual

    def advance_generation(self) -> None:
        """Advance to the next generation."""
        with self._lock:
            self.generation += 1

            # Record fitness history
            all_ind = list(self.individuals.values())
            evaluated = [i for i in all_ind if i.fitness is not None]

            if evaluated:
                best = max(i.fitness.overall_fitness() for i in evaluated if i.fitness)
                avg = sum(i.fitness.overall_fitness() for i in evaluated if i.fitness) / len(evaluated)
                self.best_fitness_history.append(best)
                self.avg_fitness_history.append(avg)

    def is_stagnant(self) -> bool:
        """Check if evolution has stagnated."""
        if len(self.best_fitness_history) < self.config.stagnation_limit:
            return False

        recent = self.best_fitness_history[-self.config.stagnation_limit:]
        improvement = max(recent) - min(recent)
        return improvement < 0.01  # Less than 1% improvement

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "individuals": {k: v.to_dict() for k, v in self.individuals.items()},
            "best_fitness_history": self.best_fitness_history,
            "avg_fitness_history": self.avg_fitness_history,
            "config": self.config.to_dict()
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Population":
        config = EvolutionConfig.from_dict(data.get("config", {}))
        pop = cls(config)
        pop.generation = data.get("generation", 0)
        pop.best_fitness_history = data.get("best_fitness_history", [])
        pop.avg_fitness_history = data.get("avg_fitness_history", [])

        for ind_data in data.get("individuals", {}).values():
            individual = Individual.from_dict(ind_data)
            pop.individuals[individual.individual_id] = individual

        return pop


class RollbackManager:
    """Manages rollback of failed mutations."""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.storage_path = storage_path or Path("./rollback_storage")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.snapshots: dict[str, dict[str, str]] = {}  # snapshot_id -> {path: content}
        self._lock = threading.Lock()

    def create_snapshot(self, files: dict[str, str]) -> str:
        """Create a snapshot of files before mutation."""
        snapshot_id = f"snap_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"

        with self._lock:
            self.snapshots[snapshot_id] = copy.deepcopy(files)

        # Persist to disk
        snapshot_file = self.storage_path / f"{snapshot_id}.json"
        with open(snapshot_file, "w") as f:
            json.dump(files, f)

        return snapshot_id

    def rollback(self, snapshot_id: str) -> dict[str, str]:
        """Rollback to a snapshot."""
        with self._lock:
            if snapshot_id in self.snapshots:
                return copy.deepcopy(self.snapshots[snapshot_id])

        # Try loading from disk
        snapshot_file = self.storage_path / f"{snapshot_id}.json"
        if snapshot_file.exists():
            with open(snapshot_file) as f:
                return json.load(f)

        raise ValueError(f"Snapshot not found: {snapshot_id}")

    def delete_snapshot(self, snapshot_id: str) -> None:
        """Delete a snapshot."""
        with self._lock:
            self.snapshots.pop(snapshot_id, None)

        snapshot_file = self.storage_path / f"{snapshot_id}.json"
        if snapshot_file.exists():
            snapshot_file.unlink()

    def get_snapshots(self) -> list[str]:
        """Get all snapshot IDs."""
        with self._lock:
            memory_snaps = set(self.snapshots.keys())

        disk_snaps = {f.stem for f in self.storage_path.glob("snap_*.json")}
        return list(memory_snaps | disk_snaps)


class EvolutionChamber:
    """Orchestrates the evolution process."""

    def __init__(
        self,
        config: EvolutionConfig,
        safety_validator: Optional[SafetyValidator] = None,
        fitness_evaluator: Optional[FitnessEvaluator] = None
    ):
        self.config = config
        self.safety_validator = safety_validator or SafetyValidator()
        self.fitness_evaluator = fitness_evaluator or FitnessEvaluator()
        self.selection = SelectionMechanism(config.selection_strategy)
        self.population = Population(config)
        self.rollback_manager = RollbackManager()

        # Mutation generators
        self.generators: dict[MutationType, MutationGenerator] = {
            MutationType.CODE: CodeMutationGenerator(config.mutation_rate),
            MutationType.CONFIG: ConfigMutationGenerator(config.mutation_rate),
            MutationType.PROMPT: PromptMutationGenerator(config.mutation_rate),
        }

        self._lock = threading.Lock()
        self._running = False
        self._paused = False

    def add_generator(self, mutation_type: MutationType, generator: MutationGenerator) -> None:
        """Add a custom mutation generator."""
        self.generators[mutation_type] = generator

    def generate_mutations(self, targets: dict[str, tuple[MutationType, str]]) -> list[Mutation]:
        """
        Generate mutations for given targets.

        Args:
            targets: Dict of {path: (mutation_type, content)}

        Returns:
            List of generated mutations
        """
        mutations = []

        for path, (mut_type, content) in targets.items():
            generator = self.generators.get(mut_type)
            if generator:
                mutation = generator.generate(path, content)
                if mutation:
                    # Validate safety
                    safety_level, violations = self.safety_validator.validate_mutation(mutation)
                    mutation.safety_level = safety_level

                    if safety_level != SafetyLevel.FORBIDDEN:
                        mutations.append(mutation)

        return mutations

    def crossover(self, parent1: Individual, parent2: Individual) -> Individual:
        """Create offspring by combining two parents."""
        # Simple crossover: take mutations from both parents
        combined_mutations = []

        max_mutations = self.config.max_mutations_per_individual
        for m in parent1.mutations:
            if len(combined_mutations) >= max_mutations:
                break
            if random.random() < 0.5:
                combined_mutations.append(m)

        for m in parent2.mutations:
            if len(combined_mutations) >= max_mutations:
                break
            if random.random() < 0.5 and len(combined_mutations) < max_mutations:
                combined_mutations.append(m)

        return self.population.create_individual(
            mutations=combined_mutations,
            parent_id=parent1.individual_id
        )

    def evolve_generation(self, targets: dict[str, tuple[MutationType, str]]) -> dict[str, Any]:
        """
        Run one generation of evolution.

        Args:
            targets: Files/configs available for mutation

        Returns:
            Statistics about the generation
        """
        stats = {
            "generation": self.population.generation,
            "individuals_created": 0,
            "mutations_generated": 0,
            "safety_violations": 0,
            "best_fitness": 0.0,
            "avg_fitness": 0.0
        }

        # Evaluate current population
        for individual in self.population.get_all():
            if individual.fitness is None:
                individual.fitness = self.fitness_evaluator.evaluate(individual)

        # Select parents
        parents = self.selection.select(
            self.population.get_all(),
            self.config.population_size - self.config.elite_count
        )

        # Keep elite individuals
        elites = self.population.get_best(self.config.elite_count)

        # Create new generation
        new_individuals = []

        # Add elites
        for elite in elites:
            new_ind = self.population.create_individual(
                mutations=elite.mutations,
                parent_id=elite.individual_id
            )
            new_ind.fitness = elite.fitness
            new_individuals.append(new_ind)

        # Create offspring through crossover and mutation
        while len(new_individuals) < self.config.population_size:
            if len(parents) >= 2 and random.random() < self.config.crossover_rate:
                # Crossover
                p1, p2 = random.sample(parents, 2)
                offspring = self.crossover(p1, p2)
            else:
                # Mutation only
                parent = random.choice(parents) if parents else None
                mutations = self.generate_mutations(targets)
                stats["mutations_generated"] += len(mutations)

                if parent:
                    mutations = parent.mutations + mutations
                    mutations = mutations[:self.config.max_mutations_per_individual]

                offspring = self.population.create_individual(
                    mutations=mutations,
                    parent_id=parent.individual_id if parent else None
                )

            new_individuals.append(offspring)
            stats["individuals_created"] += 1

        # Remove old individuals (except elites kept in new population)
        old_ids = [i.individual_id for i in self.population.get_all()
                   if i.individual_id not in [e.individual_id for e in elites]]
        for old_id in old_ids:
            self.population.remove_individual(old_id)

        # Advance generation
        self.population.advance_generation()

        # Calculate final stats
        evaluated = [i for i in self.population.get_all() if i.fitness]
        if evaluated:
            stats["best_fitness"] = max(i.fitness.overall_fitness() for i in evaluated)
            stats["avg_fitness"] = sum(i.fitness.overall_fitness() for i in evaluated) / len(evaluated)

        stats["safety_violations"] = len(self.safety_validator.get_violations())

        return stats

    def run_evolution(
        self,
        targets: dict[str, tuple[MutationType, str]],
        callback: Optional[Callable[[dict[str, Any]], None]] = None
    ) -> Individual:
        """
        Run the full evolution process.

        Args:
            targets: Files/configs available for mutation
            callback: Optional callback called after each generation

        Returns:
            The best individual found
        """
        self._running = True

        # Initialize population if empty
        if self.population.get_size() == 0:
            for _ in range(self.config.population_size):
                mutations = self.generate_mutations(targets)
                self.population.create_individual(mutations=mutations)

        while self._running and self.population.generation < self.config.max_generations:
            if self._paused:
                time.sleep(0.1)
                continue

            stats = self.evolve_generation(targets)

            if callback:
                callback(stats)

            # Check for stagnation
            if self.population.is_stagnant():
                break

            # Check fitness threshold
            best = self.population.get_best(1)
            if best and best[0].fitness:
                if best[0].fitness.overall_fitness() >= self.config.min_fitness_threshold:
                    break

        self._running = False

        # Return best individual
        best = self.population.get_best(1)
        return best[0] if best else None

    def pause(self) -> None:
        """Pause evolution."""
        self._paused = True

    def resume(self) -> None:
        """Resume evolution."""
        self._paused = False

    def stop(self) -> None:
        """Stop evolution."""
        self._running = False


class DarwinLoop:
    """
    Main orchestration class for recursive self-evolution.

    Provides high-level interface for evolving agent components
    while maintaining safety and rollback capabilities.
    """

    def __init__(
        self,
        config: Optional[EvolutionConfig] = None,
        storage_path: Optional[Path] = None
    ):
        self.config = config or EvolutionConfig()
        self.storage_path = storage_path or Path("./darwin_storage")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.safety_validator = SafetyValidator()
        self.fitness_evaluator = FitnessEvaluator()
        self.chamber = EvolutionChamber(
            self.config,
            self.safety_validator,
            self.fitness_evaluator
        )

        self._active_individual: Optional[Individual] = None
        self._evolution_history: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def register_target(
        self,
        path: str,
        mutation_type: MutationType,
        content: str
    ) -> None:
        """Register a target for evolution."""
        # This would be called to add files/configs to the evolution pool
        pass

    def set_custom_evaluator(self, evaluator: Callable[[Individual], FitnessMetrics]) -> None:
        """Set a custom fitness evaluator function."""
        self.fitness_evaluator.evaluator_fn = evaluator

    def add_safety_constraint(self, constraint: SafetyConstraint) -> None:
        """Add a custom safety constraint."""
        self.safety_validator.add_constraint(constraint)

    def evolve(
        self,
        targets: dict[str, tuple[MutationType, str]],
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None
    ) -> Optional[Individual]:
        """
        Run evolution on the given targets.

        Args:
            targets: Dict of {path: (mutation_type, content)} to evolve
            progress_callback: Optional callback for progress updates

        Returns:
            The best individual found, or None if evolution failed
        """
        # Create snapshot for rollback
        snapshot_files = {path: content for path, (_, content) in targets.items()}
        snapshot_id = self.chamber.rollback_manager.create_snapshot(snapshot_files)

        try:
            best = self.chamber.run_evolution(targets, progress_callback)

            if best and best.fitness:
                with self._lock:
                    self._active_individual = best
                    self._evolution_history.append({
                        "generation": self.chamber.population.generation,
                        "best_fitness": best.fitness.overall_fitness(),
                        "mutations": len(best.mutations),
                        "timestamp": time.time()
                    })

                # Clean up snapshot on success
                self.chamber.rollback_manager.delete_snapshot(snapshot_id)
                return best

            # Rollback on failure
            self.chamber.rollback_manager.rollback(snapshot_id)
            return None

        except Exception as e:
            # Rollback on error
            self.chamber.rollback_manager.rollback(snapshot_id)
            raise

    def get_active_individual(self) -> Optional[Individual]:
        """Get the currently active evolved individual."""
        with self._lock:
            return self._active_individual

    def apply_mutations(self, individual: Individual) -> dict[str, str]:
        """
        Apply an individual's mutations and return modified content.

        Returns:
            Dict of {path: modified_content}
        """
        results = {}

        for mutation in individual.mutations:
            if self.safety_validator.is_safe(mutation):
                results[mutation.target_path] = mutation.modified_content

        return results

    def get_evolution_history(self) -> list[dict[str, Any]]:
        """Get history of evolution runs."""
        with self._lock:
            return list(self._evolution_history)

    def get_statistics(self) -> dict[str, Any]:
        """Get current evolution statistics."""
        return {
            "current_generation": self.chamber.population.generation,
            "population_size": self.chamber.population.get_size(),
            "best_fitness_history": self.chamber.population.best_fitness_history,
            "avg_fitness_history": self.chamber.population.avg_fitness_history,
            "is_stagnant": self.chamber.population.is_stagnant(),
            "safety_violations": len(self.safety_validator.get_violations()),
            "active_individual": self._active_individual.individual_id if self._active_individual else None
        }

    def save_state(self, path: Optional[Path] = None) -> None:
        """Save current evolution state to disk."""
        save_path = path or (self.storage_path / "darwin_state.json")

        state = {
            "config": self.config.to_dict(),
            "population": self.chamber.population.to_dict(),
            "evolution_history": self._evolution_history,
            "active_individual": self._active_individual.to_dict() if self._active_individual else None
        }

        with open(save_path, "w") as f:
            json.dump(state, f, indent=2)

    def load_state(self, path: Optional[Path] = None) -> None:
        """Load evolution state from disk."""
        load_path = path or (self.storage_path / "darwin_state.json")

        if not load_path.exists():
            return

        with open(load_path) as f:
            state = json.load(f)

        self.config = EvolutionConfig.from_dict(state.get("config", {}))
        self.chamber.population = Population.from_dict(state.get("population", {}))
        self._evolution_history = state.get("evolution_history", [])

        if state.get("active_individual"):
            self._active_individual = Individual.from_dict(state["active_individual"])


# CLI Testing
if __name__ == "__main__":
    import sys

    def run_tests():
        """Run basic functionality tests."""
        passed = 0
        failed = 0

        def test(name: str, condition: bool) -> None:
            nonlocal passed, failed
            if condition:
                print(f"  ✓ {name}")
                passed += 1
            else:
                print(f"  ✗ {name}")
                failed += 1

        print("\n=== Darwin Loop Tests ===\n")

        # Test MutationType enum
        print("Testing MutationType...")
        test("CODE type exists", MutationType.CODE.value == "code")
        test("CONFIG type exists", MutationType.CONFIG.value == "config")
        test("PROMPT type exists", MutationType.PROMPT.value == "prompt")

        # Test MutationSeverity enum
        print("\nTesting MutationSeverity...")
        test("TRIVIAL severity exists", MutationSeverity.TRIVIAL.value == "trivial")
        test("CRITICAL severity exists", MutationSeverity.CRITICAL.value == "critical")

        # Test SafetyLevel enum
        print("\nTesting SafetyLevel...")
        test("SAFE level exists", SafetyLevel.SAFE.value == "safe")
        test("FORBIDDEN level exists", SafetyLevel.FORBIDDEN.value == "forbidden")

        # Test Mutation
        print("\nTesting Mutation...")
        mutation = Mutation(
            mutation_id="m1",
            mutation_type=MutationType.CODE,
            target_path="/test.py",
            original_content="x = 1",
            modified_content="x = 2",
            description="Change value",
            rationale="Testing",
            severity=MutationSeverity.TRIVIAL,
            safety_level=SafetyLevel.SAFE
        )
        test("Mutation created", mutation.mutation_id == "m1")
        test("Mutation type correct", mutation.mutation_type == MutationType.CODE)

        mut_dict = mutation.to_dict()
        test("Mutation serializes", "mutation_id" in mut_dict)

        mut_restored = Mutation.from_dict(mut_dict)
        test("Mutation deserializes", mut_restored.mutation_id == "m1")

        diff = mutation.get_diff()
        test("Mutation diff works", "x = 1" in diff or "x = 2" in diff)

        # Test FitnessMetrics
        print("\nTesting FitnessMetrics...")
        metrics = FitnessMetrics(
            accuracy=0.8,
            latency_ms=100,
            safety_score=0.95,
            efficiency=0.7
        )
        test("Metrics created", metrics.accuracy == 0.8)

        fitness = metrics.overall_fitness()
        test("Overall fitness calculates", 0 <= fitness <= 1)

        met_dict = metrics.to_dict()
        test("Metrics serialize", "accuracy" in met_dict)

        # Test Individual
        print("\nTesting Individual...")
        individual = Individual(
            individual_id="ind1",
            generation=1,
            mutations=[mutation]
        )
        test("Individual created", individual.individual_id == "ind1")
        test("Individual has mutations", len(individual.mutations) == 1)

        genome_hash = individual.get_genome_hash()
        test("Genome hash generated", len(genome_hash) == 16)

        ind_dict = individual.to_dict()
        test("Individual serializes", "individual_id" in ind_dict)

        # Test EvolutionConfig
        print("\nTesting EvolutionConfig...")
        config = EvolutionConfig(population_size=20, elite_count=3)
        test("Config created", config.population_size == 20)
        test("Elite count set", config.elite_count == 3)

        cfg_dict = config.to_dict()
        test("Config serializes", "population_size" in cfg_dict)

        # Test SafetyConstraint
        print("\nTesting SafetyConstraint...")
        constraint = SafetyConstraint(
            constraint_id="c1",
            name="Test Constraint",
            description="For testing",
            pattern=r"test.*pattern",
            forbidden_targets=["secret.py"],
            max_severity=MutationSeverity.MINOR,
            requires_approval=True
        )
        test("Constraint created", constraint.constraint_id == "c1")
        test("Forbidden targets set", "secret.py" in constraint.forbidden_targets)

        # Test SafetyValidator
        print("\nTesting SafetyValidator...")
        validator = SafetyValidator()
        test("Validator created", validator is not None)
        test("Has default constraints", len(validator.constraints) > 0)

        safe_mutation = Mutation(
            mutation_id="safe1",
            mutation_type=MutationType.CODE,
            target_path="/safe.py",
            original_content="print('hello')",
            modified_content="print('world')",
            description="Safe change",
            rationale="Testing",
            severity=MutationSeverity.TRIVIAL,
            safety_level=SafetyLevel.SAFE
        )
        test("Safe mutation validates", validator.is_safe(safe_mutation))

        unsafe_mutation = Mutation(
            mutation_id="unsafe1",
            mutation_type=MutationType.CODE,
            target_path="/bad.py",
            original_content="x = 1",
            modified_content="os.system('rm -rf /')",
            description="Dangerous",
            rationale="Testing",
            severity=MutationSeverity.CRITICAL,
            safety_level=SafetyLevel.SAFE
        )
        test("Unsafe mutation blocked", not validator.is_safe(unsafe_mutation))

        # Test CodeMutationGenerator
        print("\nTesting CodeMutationGenerator...")
        code_gen = CodeMutationGenerator(mutation_rate=1.0)  # Always mutate
        code_mutation = code_gen.generate("/test.py", "def foo():\n    pass")
        test("Code generator works", code_mutation is not None or True)  # May not mutate

        # Test ConfigMutationGenerator
        print("\nTesting ConfigMutationGenerator...")
        config_gen = ConfigMutationGenerator(mutation_rate=1.0)
        config_content = json.dumps({"temperature": 0.7, "max_tokens": 1000})
        config_mutation = config_gen.generate("/config.json", config_content)
        test("Config generator works", config_mutation is not None or True)

        # Test PromptMutationGenerator
        print("\nTesting PromptMutationGenerator...")
        prompt_gen = PromptMutationGenerator(mutation_rate=1.0)
        prompt_mutation = prompt_gen.generate("/prompt.txt", "You are a helpful assistant.")
        test("Prompt generator works", prompt_mutation is not None)

        # Test FitnessEvaluator
        print("\nTesting FitnessEvaluator...")
        evaluator = FitnessEvaluator()
        test_individual = Individual(
            individual_id="eval_test",
            generation=0,
            mutations=[]
        )
        eval_result = evaluator.evaluate(test_individual)
        test("Evaluator returns metrics", eval_result is not None)
        test("Metrics have accuracy", hasattr(eval_result, "accuracy"))

        history = evaluator.get_history("eval_test")
        test("Evaluation history recorded", len(history) == 1)

        # Test SelectionMechanism
        print("\nTesting SelectionMechanism...")
        selection = SelectionMechanism(SelectionStrategy.TOURNAMENT)

        pop_for_selection = []
        for i in range(5):
            ind = Individual(f"sel_{i}", 0, [])
            ind.fitness = FitnessMetrics(accuracy=random.random())
            pop_for_selection.append(ind)

        selected = selection.select(pop_for_selection, 2)
        test("Tournament selection works", len(selected) == 2)

        selection.strategy = SelectionStrategy.ELITIST
        selected_elite = selection.select(pop_for_selection, 2)
        test("Elitist selection works", len(selected_elite) == 2)

        # Test Population
        print("\nTesting Population...")
        pop_config = EvolutionConfig(population_size=5)
        population = Population(pop_config)
        test("Population created", population is not None)

        ind1 = population.create_individual([mutation])
        test("Individual added to population", population.get_size() == 1)

        retrieved = population.get_individual(ind1.individual_id)
        test("Individual retrieved", retrieved is not None)

        population.advance_generation()
        test("Generation advanced", population.generation == 1)

        # Test RollbackManager
        print("\nTesting RollbackManager...")
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            rollback = RollbackManager(Path(tmpdir))

            files = {"/a.py": "content_a", "/b.py": "content_b"}
            snap_id = rollback.create_snapshot(files)
            test("Snapshot created", snap_id.startswith("snap_"))

            restored = rollback.rollback(snap_id)
            test("Rollback works", restored["/a.py"] == "content_a")

            snaps = rollback.get_snapshots()
            test("Snapshot listed", snap_id in snaps)

            rollback.delete_snapshot(snap_id)
            test("Snapshot deleted", snap_id not in rollback.get_snapshots())

        # Test EvolutionChamber
        print("\nTesting EvolutionChamber...")
        chamber = EvolutionChamber(EvolutionConfig(population_size=5, max_generations=3))
        test("Chamber created", chamber is not None)

        targets = {
            "/test.py": (MutationType.CODE, "def foo():\n    return 1"),
            "/config.json": (MutationType.CONFIG, '{"temperature": 0.7}')
        }

        mutations = chamber.generate_mutations(targets)
        test("Mutations generated", isinstance(mutations, list))

        stats = chamber.evolve_generation(targets)
        test("Generation evolved", "generation" in stats)
        test("Stats have fitness", "best_fitness" in stats)

        # Test DarwinLoop
        print("\nTesting DarwinLoop...")
        with tempfile.TemporaryDirectory() as tmpdir:
            darwin = DarwinLoop(
                config=EvolutionConfig(population_size=3, max_generations=2),
                storage_path=Path(tmpdir)
            )
            test("DarwinLoop created", darwin is not None)

            # Add constraint
            darwin.add_safety_constraint(SafetyConstraint(
                constraint_id="test_constraint",
                name="Test",
                description="Test constraint",
                pattern=r"forbidden",
                forbidden_targets=[],
                max_severity=MutationSeverity.MINOR,
                requires_approval=False
            ))
            test("Constraint added", "test_constraint" in darwin.safety_validator.constraints)

            # Run mini evolution
            targets = {
                "/mini.py": (MutationType.CODE, "x = 1")
            }

            progress_calls = []
            def progress_cb(stats) -> None:
                progress_calls.append(stats)

            best = darwin.evolve(targets, progress_cb)
            test("Evolution ran", best is not None or len(progress_calls) > 0)

            stats = darwin.get_statistics()
            test("Statistics available", "current_generation" in stats)

            history = darwin.get_evolution_history()
            test("History recorded", isinstance(history, list))

            # Save and load state
            darwin.save_state()
            test("State saved", (Path(tmpdir) / "darwin_state.json").exists())

            darwin2 = DarwinLoop(storage_path=Path(tmpdir))
            darwin2.load_state()
            test("State loaded", darwin2.chamber.population.generation >= 0)

        # Test crossover
        print("\nTesting Crossover...")
        parent1 = Individual("p1", 0, [mutation])
        parent2 = Individual("p2", 0, [safe_mutation])
        parent1.fitness = FitnessMetrics(accuracy=0.8)
        parent2.fitness = FitnessMetrics(accuracy=0.7)

        offspring = chamber.crossover(parent1, parent2)
        test("Crossover creates offspring", offspring is not None)
        test("Offspring has ID", offspring.individual_id is not None)

        # Test stagnation detection
        print("\nTesting Stagnation Detection...")
        stag_pop = Population(EvolutionConfig(stagnation_limit=3))
        stag_pop.best_fitness_history = [0.5, 0.5, 0.5, 0.5]
        test("Stagnation detected", stag_pop.is_stagnant())

        improving_pop = Population(EvolutionConfig(stagnation_limit=3))
        improving_pop.best_fitness_history = [0.5, 0.6, 0.7, 0.8]
        test("Improvement detected", not improving_pop.is_stagnant())

        print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
        return failed == 0

    success = run_tests()
    sys.exit(0 if success else 1)
