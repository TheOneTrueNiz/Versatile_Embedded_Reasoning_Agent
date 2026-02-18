#!/usr/bin/env python3
"""
Quorum Selector - VERA Quorum System
=====================================

Analyzes tasks and selects optimal quorum (premade or custom).

Selection Strategy:
1. Extract task features (intent, domain, complexity, risk)
2. Check premade quorums in priority order (Safety first!)
3. If no match, build custom quorum based on features
4. Return selected quorum for execution

Custom Quorum Logic:
- Low complexity + Low risk: Tasker lead (solo)
- High complexity + Low risk: Strategist + Architect + Engineer
- Low complexity + High risk: Safety Lead + QA + Skeptic
- High complexity + High risk: Safety Lead + QA + Architect + Engineer
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Set

from .premade_quorums import (
    Quorum,
    AgentRole,
    PREMADE_QUORUMS,
    QUORUM_PRIORITY_ORDER,
)
from .consensus import ConsensusAlgorithm


# ============================================================================
# TASK FEATURES
# ============================================================================

@dataclass
class TaskFeatures:
    """
    Extracted characteristics of a task

    Used for quorum selection and custom composition.

    Attributes:
        intent: Primary goal (schedule, research, write, etc.)
        domain: Area (secretarial, creative, technical, etc.)
        complexity: 1-5 scale (1=trivial, 5=very complex)
        risk_level: 1-5 scale (1=safe, 5=catastrophic if wrong)
        tools_required: Which tools task needs
        multi_step: Requires workflow vs single action
        time_sensitive: Urgent vs can wait
        keywords: Key terms from task description
    """
    intent: str = "unknown"
    domain: str = "general"
    complexity: int = 3
    risk_level: int = 2
    tools_required: List[str] = field(default_factory=list)
    multi_step: bool = False
    time_sensitive: bool = False
    keywords: Set[str] = field(default_factory=set)


# ============================================================================
# QUORUM SELECTOR
# ============================================================================

class QuorumSelector:
    """
    Analyzes tasks and selects optimal quorum

    Usage:
        selector = QuorumSelector()
        quorum = selector.select(task_text, context)

        # Use selected quorum
        decision = quorum.invoke(task_text, context)
    """

    def __init__(self) -> None:
        """Initialize quorum selector"""
        self.premade_quorums = PREMADE_QUORUMS
        self.priority_order = QUORUM_PRIORITY_ORDER

        # Compile trigger patterns for performance
        self._trigger_patterns = self._compile_triggers()

    def _compile_triggers(self) -> Dict[str, List[re.Pattern]]:
        """
        Compile regex patterns from quorum triggers

        Returns:
            Dict mapping quorum name -> compiled patterns
        """
        compiled = {}
        for name, quorum in self.premade_quorums.items():
            patterns = []
            for trigger in quorum.triggers:
                # Convert trigger to regex pattern (case-insensitive, word boundary)
                pattern = re.compile(r'\b' + re.escape(trigger) + r'\b', re.IGNORECASE)
                patterns.append(pattern)
            compiled[name] = patterns
        return compiled

    def select(self, task_text: str, context: str = "") -> Quorum:
        """
        Select optimal quorum for task

        Args:
            task_text: User's task/question
            context: Additional context

        Returns:
            Selected Quorum (premade or custom)
        """
        # Step 1: Extract task features
        features = self.extract_features(task_text, context)

        # Step 2: Try premade quorums in priority order
        for quorum_name in self.priority_order:
            quorum = self.premade_quorums[quorum_name]
            if self._matches_triggers(task_text, quorum_name):
                return quorum

        # Step 3: No premade match -> build custom quorum
        return self.build_custom_quorum(features, task_text)

    def extract_features(self, task_text: str, context: str = "") -> TaskFeatures:
        """
        Extract task characteristics for quorum selection

        Args:
            task_text: Task description
            context: Additional context

        Returns:
            TaskFeatures with extracted properties
        """
        text_lower = task_text.lower()
        combined = (task_text + " " + context).lower()

        features = TaskFeatures()

        # Extract keywords (simple tokenization)
        words = re.findall(r'\b\w+\b', combined)
        features.keywords = set(words)

        # Determine intent
        features.intent = self._extract_intent(text_lower)

        # Determine domain
        features.domain = self._extract_domain(text_lower)

        # Assess complexity (heuristic)
        features.complexity = self._assess_complexity(task_text, features.keywords)

        # Assess risk level (heuristic)
        features.risk_level = self._assess_risk(text_lower)

        # Identify required tools
        features.tools_required = self._identify_tools(text_lower)

        # Detect multi-step
        features.multi_step = self._is_multi_step(text_lower)

        # Detect time sensitivity
        features.time_sensitive = self._is_time_sensitive(text_lower)

        return features

    def _extract_intent(self, text: str) -> str:
        """Determine primary intent from text"""
        intent_patterns = {
            "schedule": r'\b(schedule|calendar|meeting|appointment|book)\b',
            "research": r'\b(research|arxiv|papers|literature|review|study)\b',
            "write": r'\b(write|draft|create|compose|generate)\b',
            "analyze": r'\b(analyze|examine|review|assess|evaluate)\b',
            "delete": r'\b(delete|remove|rm|erase|wipe)\b',
            "modify": r'\b(modify|edit|change|update|alter)\b',
            "prioritize": r'\b(prioritize|priority|todo|task|backlog)\b',
            "integrate": r'\b(integrate|connect|orchestrate|workflow|pipeline)\b',
            "memory": r'\b(memory|consolidate|archive|compress)\b',
            "shop": r'\b(shop|shopping|buy|purchase|deal|discount|coupon|price)\b',
            "meal": r'\b(meal|recipe|cook|cooking|grocery|meal prep)\b',
            "itinerary": r'\b(itinerary|travel plan|agenda|day plan|time block)\b',
        }

        for intent, pattern in intent_patterns.items():
            if re.search(pattern, text):
                return intent

        return "unknown"

    def _extract_domain(self, text: str) -> str:
        """Determine task domain"""
        domain_patterns = {
            "secretarial": r'\b(email|gmail|calendar|schedule|meeting)\b',
            "creative": r'\b(write|brainstorm|idea|draft|blog|article)\b',
            "technical": r'\b(code|implement|debug|optimize|algorithm)\b',
            "research": r'\b(research|arxiv|paper|literature|study)\b',
            "administrative": r'\b(organize|manage|prioritize|todo)\b',
            "shopping": r'\b(shop|shopping|buy|purchase|deal|discount|coupon|price)\b',
            "meal": r'\b(meal|recipe|cook|cooking|grocery|meal prep)\b',
            "itinerary": r'\b(itinerary|travel|agenda|day plan|time block)\b',
        }

        for domain, pattern in domain_patterns.items():
            if re.search(pattern, text):
                return domain

        return "general"

    def _assess_complexity(self, text: str, keywords: Set[str]) -> int:
        """
        Assess task complexity (1-5)

        Heuristics:
        - Length of task description
        - Number of steps/actions mentioned
        - Presence of complex terms
        """
        complexity = 1

        # Length factor
        if len(text) > 200:
            complexity += 2
        elif len(text) > 100:
            complexity += 1

        # Multi-step indicators
        multi_step_words = ["then", "after", "next", "finally", "first", "second"]
        step_count = sum(1 for word in multi_step_words if word in keywords)
        complexity += min(step_count, 2)

        # Complex terms
        complex_terms = ["optimize", "integrate", "analyze", "synthesize", "orchestrate"]
        if any(term in keywords for term in complex_terms):
            complexity += 1

        return min(complexity, 5)

    def _assess_risk(self, text: str) -> int:
        """
        Assess risk level (1-5)

        Risk indicators:
        - Destructive operations (rm, delete, format)
        - Self-modification (run_vera.py)
        - System-level operations
        - No risk indicators -> default 2
        """
        risk = 2  # Default: medium-low risk

        # Catastrophic patterns (severity 5)
        catastrophic = [
            r'\brm\s+-rf\s+/',
            r'\bdd\s+.*of=/dev/',
            r'\bmkfs\b',
            r'\bformat\b.*\b(disk|drive|partition)\b',
        ]
        for pattern in catastrophic:
            if re.search(pattern, text):
                return 5

        # High risk (severity 4)
        high_risk = [
            r'\bdelete\b.*\b(all|everything|directory)\b',
            r'\brm\b.*run_vera\.py',
            r'\bmodify\b.*run_vera\.py',
            r'\bself[- ]modif',
        ]
        for pattern in high_risk:
            if re.search(pattern, text):
                risk = max(risk, 4)

        # Medium risk (severity 3)
        medium_risk = [
            r'\bdelete\b',
            r'\brm\b',
            r'\bedit\b.*\.py',
        ]
        for pattern in medium_risk:
            if re.search(pattern, text):
                risk = max(risk, 3)

        return risk

    def _identify_tools(self, text: str) -> List[str]:
        """Identify required tools based on task"""
        tools = []

        tool_patterns = {
            "gmail": r'\b(email|gmail|inbox)\b',
            "calendar": r'\b(calendar|schedule|meeting)\b',
            "arxiv": r'\b(arxiv|papers|research)\b',
            "file_operations": r'\b(file|read|write|edit)\b',
            "web_search": r'\b(search|google|web|online|shop|shopping|deal|discount|price|recipe|meal|grocery)\b',
            "command_execution": r'\b(run|execute|command|bash)\b',
            "vera_memory": r'\b(memory|todo|goal|project)\b',
        }

        for tool, pattern in tool_patterns.items():
            if re.search(pattern, text):
                tools.append(tool)

        return tools

    def _is_multi_step(self, text: str) -> bool:
        """Detect if task requires multiple steps"""
        multi_step_indicators = [
            r'\bthen\b',
            r'\bafter\b',
            r'\bnext\b',
            r'\bfinally\b',
            r'\b(first|second|third)\b',
            r'\band then\b',
            r'\bfollowed by\b',
        ]

        for pattern in multi_step_indicators:
            if re.search(pattern, text):
                return True

        # Multiple verbs might indicate steps
        action_verbs = re.findall(
            r'\b(schedule|send|create|delete|analyze|write|read|update)\b',
            text
        )
        return len(action_verbs) >= 3

    def _is_time_sensitive(self, text: str) -> bool:
        """Detect time sensitivity"""
        urgent_patterns = [
            r'\burgen',
            r'\basap\b',
            r'\bimmediatel',
            r'\bnow\b',
            r'\btoday\b',
            r'\bquick',
        ]

        for pattern in urgent_patterns:
            if re.search(pattern, text):
                return True

        return False

    def _matches_triggers(self, text: str, quorum_name: str) -> bool:
        """
        Check if task text matches quorum triggers

        Args:
            text: Task text
            quorum_name: Name of quorum to check

        Returns:
            True if any trigger matches
        """
        patterns = self._trigger_patterns.get(quorum_name, [])

        for pattern in patterns:
            if pattern.search(text):
                return True

        return False

    def build_custom_quorum(
        self,
        features: TaskFeatures,
        task_text: str
    ) -> Quorum:
        """
        Build custom quorum when no premade match

        Selection logic:
        - Low complexity (1-2) + Low risk (1-2): Solo (no quorum, just main agent)
        - High complexity (3-5) + Low risk (1-2): Strategist + Architect + Engineer
        - Low complexity (1-2) + High risk (3-5): Safety Lead + QA + Skeptic
        - High complexity (3-5) + High risk (3-5): Safety Lead + QA + Architect + Engineer

        Args:
            features: Extracted task features
            task_text: Original task text

        Returns:
            Custom Quorum
        """
        agents = []
        consensus_algo = ConsensusAlgorithm.MAJORITY_VOTE
        weights = None

        # Categorize
        low_complexity = features.complexity <= 2
        low_risk = features.risk_level <= 2

        if low_complexity and low_risk:
            # Solo: minimal quorum (just return a simple quorum for consistency)
            agents = [
                AgentRole("Tasker", is_lead=True),
            ]
            consensus_algo = ConsensusAlgorithm.MAJORITY_VOTE

        elif not low_complexity and low_risk:
            # Complex but safe: Strategist + Architect + Engineer
            agents = [
                AgentRole("Strategist", weight=0.34, is_lead=True),
                AgentRole("Architect", weight=0.33),
                AgentRole("Engineer", weight=0.33),
            ]
            consensus_algo = ConsensusAlgorithm.MAJORITY_VOTE

        elif low_complexity and not low_risk:
            # Simple but risky: Safety Lead + QA + Skeptic
            agents = [
                AgentRole("SafetyLead", veto_authority=True, is_lead=True),
                AgentRole("QualityAssurance"),
                AgentRole("Skeptic"),
            ]
            consensus_algo = ConsensusAlgorithm.VETO_AUTHORITY

        else:
            # Complex AND risky: Safety Lead + QA + Architect + Engineer
            agents = [
                AgentRole("SafetyLead", weight=0.3, veto_authority=(features.risk_level >= 4), is_lead=True),
                AgentRole("QualityAssurance", weight=0.2),
                AgentRole("Architect", weight=0.25),
                AgentRole("Engineer", weight=0.25),
            ]
            if features.risk_level >= 4:
                # High risk: use veto authority
                consensus_algo = ConsensusAlgorithm.VETO_AUTHORITY
            else:
                # Medium risk: use weighted scoring
                consensus_algo = ConsensusAlgorithm.WEIGHTED_SCORING
                weights = {
                    "SafetyLead": 0.3,
                    "QualityAssurance": 0.2,
                    "Architect": 0.25,
                    "Engineer": 0.25,
                }

        def _add_agent(name: str) -> None:
            if not any(a.name == name for a in agents):
                agents.append(AgentRole(name))

        # Add specialists based on intent/domain
        if features.intent == "research":
            _add_agent("Researcher")
        if features.intent == "write":
            _add_agent("Writer")
        if features.intent == "schedule" or features.intent == "itinerary":
            _add_agent("Scheduler")
        if features.intent == "memory":
            _add_agent("MemoryCurator")
        if features.intent == "prioritize":
            _add_agent("Tasker")
        if features.intent == "shop":
            _add_agent("DealFinder")
        if features.intent == "meal":
            _add_agent("Chef")
        if features.domain == "creative":
            _add_agent("Creative")
        if features.domain == "technical":
            _add_agent("Programmer")
        if features.domain == "secretarial":
            _add_agent("Secretary")

        if features.multi_step:
            _add_agent("Integrator")

        if features.time_sensitive and not any(a.name == "Scheduler" for a in agents):
            _add_agent("Scheduler")

        # Build custom quorum
        return Quorum(
            name="Custom",
            purpose=f"Custom quorum for: {features.intent} ({features.domain})",
            agents=agents,
            tool_access=features.tools_required or ["file_operations", "vera_memory"],
            consensus_algorithm=consensus_algo,
            triggers=[],  # No triggers (custom built)
            description=f"Dynamically generated quorum for complexity={features.complexity}, risk={features.risk_level}",
            weights=weights,
        )


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def select_quorum_for_task(task_text: str, context: str = "") -> Quorum:
    """
    Convenience function: Select quorum for task

    Args:
        task_text: Task description
        context: Additional context

    Returns:
        Selected Quorum
    """
    selector = QuorumSelector()
    return selector.select(task_text, context)


def explain_selection(task_text: str, context: str = "") -> str:
    """
    Explain why a quorum was selected (for debugging)

    Args:
        task_text: Task description
        context: Additional context

    Returns:
        Human-readable explanation
    """
    selector = QuorumSelector()
    features = selector.extract_features(task_text, context)
    quorum = selector.select(task_text, context)

    explanation = f"""
Task: {task_text}

Extracted Features:
- Intent: {features.intent}
- Domain: {features.domain}
- Complexity: {features.complexity}/5
- Risk Level: {features.risk_level}/5
- Tools: {', '.join(features.tools_required) if features.tools_required else 'None detected'}
- Multi-step: {features.multi_step}
- Time-sensitive: {features.time_sensitive}

Selected Quorum: {quorum.name}
- Purpose: {quorum.purpose}
- Agents: {', '.join(quorum.get_agent_names())}
- Consensus: {quorum.consensus_algorithm.value}
- Lead Agent: {quorum.get_lead_agent() or 'None'}
- Veto Agent: {quorum.get_veto_agent() or 'None'}

Reasoning: {quorum.description.strip()}
"""

    return explanation.strip()
