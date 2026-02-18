#!/usr/bin/env python3
"""
Premade Quorums - VERA Quorum System
=====================================

Defines premade quorums optimized for specific task types:

1. Secretarial - Email, calendar, scheduling
2. Creative - Content generation, brainstorming
3. TodoTask - Task prioritization, planning
4. Research - Literature review, paper analysis
5. Safety - Risk assessment, dangerous operations
6. Integration - Multi-tool workflows
7. MemoryCurator - Memory consolidation, archival
8. Specialized/alias quorums (Architect, Engineer, Programmer, Strategist, QA, etc.)

Each quorum specifies:
- Agent composition (3-4 agents)
- Tool access permissions
- Consensus algorithm
- Trigger patterns for auto-selection
"""

from dataclasses import dataclass
from typing import List, Dict, Optional

from .consensus import ConsensusAlgorithm


@dataclass
class AgentRole:
    """
    Defines an agent's role within a quorum

    Attributes:
        name: Agent identifier
        weight: Voting/scoring weight (for weighted algorithms)
        veto_authority: Can unilaterally block decisions
        is_lead: Primary decision maker
    """
    name: str
    weight: float = 1.0
    veto_authority: bool = False
    is_lead: bool = False


@dataclass
class Quorum:
    """
    Definition of a multi-agent quorum

    Attributes:
        name: Quorum identifier
        purpose: What this quorum is optimized for
        agents: List of AgentRoles in this quorum
        tool_access: Tools available to this quorum
        consensus_algorithm: How to aggregate agent outputs
        triggers: Keywords/patterns for auto-selection
        description: Detailed description
    """
    name: str
    purpose: str
    agents: List[AgentRole]
    tool_access: List[str]
    consensus_algorithm: ConsensusAlgorithm
    triggers: List[str]
    description: str = ""
    weights: Optional[Dict[str, float]] = None  # For weighted_scoring

    def get_agent_names(self) -> List[str]:
        """Get list of agent names in this quorum"""
        return [agent.name for agent in self.agents]

    def get_lead_agent(self) -> Optional[str]:
        """Get name of lead agent (if any)"""
        for agent in self.agents:
            if agent.is_lead:
                return agent.name
        return None

    def get_veto_agent(self) -> Optional[str]:
        """Get name of agent with veto authority (if any)"""
        for agent in self.agents:
            if agent.veto_authority:
                return agent.name
        return None

    def has_tool_access(self, tool: str) -> bool:
        """Check if quorum has access to specified tool"""
        return tool in self.tool_access


# ============================================================================
# QUORUM DEFINITIONS
# ============================================================================

# ----------------------------------------------------------------------------
# 1. SECRETARIAL QUORUM
# ----------------------------------------------------------------------------

SECRETARIAL_QUORUM = Quorum(
    name="Secretarial",
    purpose="Email management, scheduling, calendar optimization, administrative tasks",
    agents=[
        AgentRole("Secretary", weight=1.0, is_lead=True),
        AgentRole("Scheduler", weight=1.0),
        AgentRole("SafetyLead", weight=1.0),
    ],
    tool_access=[
        "gmail",
        "calendar",
        "drive",
        "vera_memory",
        "file_operations",
    ],
    consensus_algorithm=ConsensusAlgorithm.MAJORITY_VOTE,
    triggers=[
        "email",
        "calendar",
        "schedule",
        "meeting",
        "gmail",
        "appointment",
        "availability",
        "calendar event",
    ],
    description="""
    Secretarial quorum handles administrative tasks involving email, calendar, and scheduling.

    Agent Roles:
    - Secretary (Lead): Coordinates tasks and follow-ups
    - Scheduler: Builds schedules and avoids conflicts
    - Safety Lead: Checks privacy and conflict risks

    Decision Flow:
    1. Planner analyzes requirements and calendar
    2. Optimizer ranks proposed solutions
    3. Safety validates no conflicts or privacy issues
    4. Consensus: 2/3 majority vote

    Use Cases:
    - "Schedule a meeting with Alice next week"
    - "Prioritize my unread emails"
    - "Find all emails about Project X"
    - "When am I free tomorrow afternoon?"
    """
)

# ----------------------------------------------------------------------------
# 2. CREATIVE QUORUM
# ----------------------------------------------------------------------------

CREATIVE_QUORUM = Quorum(
    name="Creative",
    purpose="Content generation, brainstorming, ideation, writing assistance",
    agents=[
        AgentRole("Creative", weight=1.0, is_lead=True),
        AgentRole("Writer", weight=1.0),
        AgentRole("Researcher", weight=1.0),
    ],
    tool_access=[
        "web_search",
        "wikipedia",
        "arxiv",
        "vera_memory",
        "file_operations",
    ],
    consensus_algorithm=ConsensusAlgorithm.SYNTHESIS,
    triggers=[
        "write",
        "brainstorm",
        "generate ideas",
        "create",
        "draft",
        "compose",
        "outline",
        "creative",
        "blog post",
        "article",
    ],
    description="""
    Creative quorum generates content through collaborative ideation and synthesis.

    Agent Roles:
    - Creative (Lead): Generates ideas and directions
    - Writer: Shapes tone and structure
    - Researcher: Adds references and inspiration

    Decision Flow:
    1. Researcher gathers relevant information and examples
    2. Planner creates structural outline
    3. Integrator combines into final draft
    4. Consensus: Synthesis (all contributions merged)

    Use Cases:
    - "Write a blog post about AI memory systems"
    - "Brainstorm 10 project names"
    - "Create outline for technical presentation"
    - "Draft introduction for paper"
    """
)

# ----------------------------------------------------------------------------
# 3. TODO/TASK QUORUM
# ----------------------------------------------------------------------------

TODOTASK_QUORUM = Quorum(
    name="TodoTask",
    purpose="Task prioritization, backlog management, project planning",
    agents=[
        AgentRole("Tasker", weight=0.4, is_lead=True),
        AgentRole("Strategist", weight=0.3),
        AgentRole("Optimizer", weight=0.3),
    ],
    tool_access=[
        "vera_memory",  # todos, project_queue, goals
        "activity_log",
        "file_operations",
    ],
    consensus_algorithm=ConsensusAlgorithm.WEIGHTED_SCORING,
    triggers=[
        "prioritize",
        "todo",
        "task",
        "what should I work on",
        "backlog",
        "project plan",
        "next steps",
        "priorities",
    ],
    weights={
        "Tasker": 0.4,
        "Strategist": 0.3,
        "Optimizer": 0.3,
    },
    description="""
    TodoTask quorum optimizes task prioritization using weighted multi-criteria analysis.

    Agent Roles:
    - Tasker (Lead, 40%): Breaks down tasks and sets priorities
    - Strategist (30%): Sequences milestones and tradeoffs
    - Optimizer (30%): Scores by ROI, urgency, effort

    Decision Flow:
    1. Planner analyzes task dependencies and complexity
    2. Optimizer calculates impact/effort ratio
    3. Skeptic identifies risks and blockers
    4. Consensus: Weighted scoring (threshold 60/100)

    Weights: Tasker 40%, Strategist 30%, Optimizer 30%

    Use Cases:
    - "What should I focus on today?"
    - "Prioritize my backlog by deadline"
    - "Break down 'implement Phase 1' into subtasks"
    - "Which tasks are most urgent?"
    """
)

# ----------------------------------------------------------------------------
# 4. RESEARCH QUORUM
# ----------------------------------------------------------------------------

RESEARCH_QUORUM = Quorum(
    name="Research",
    purpose="Literature review, paper analysis, technical research",
    agents=[
        AgentRole("Researcher", weight=1.0, is_lead=True),
        AgentRole("Skeptic", weight=1.0, veto_authority=True),  # Can veto dubious claims
        AgentRole("Writer", weight=1.0),
    ],
    tool_access=[
        "arxiv",
        "pdf_reader",
        "web_search",
        "wikipedia",
        "vera_memory",
    ],
    consensus_algorithm=ConsensusAlgorithm.VETO_AUTHORITY,  # Skeptic can veto bad research
    triggers=[
        "arxiv",
        "research",
        "papers",
        "literature review",
        "state of the art",
        "SOTA",
        "technical review",
        "survey",
    ],
    description="""
    Research quorum conducts literature reviews with skeptical validation.

    Agent Roles:
    - Researcher (Lead): Searches papers, extracts key points, summarizes
    - Skeptic (Veto Authority): Validates methodology, checks citations, flags dubious claims
    - Writer: Synthesizes findings into clear summaries

    Decision Flow:
    1. Researcher finds relevant papers and extracts insights
    2. Skeptic validates claims and methodology
    3. Integrator combines findings into coherent summary
    4. Consensus: Synthesis with skeptic veto (can block dubious claims)

    Use Cases:
    - "Find papers on memory consolidation in LLMs"
    - "Summarize latest research on multi-agent systems"
    - "What's state-of-the-art for RAG optimization?"
    - "Review literature on neural compression"
    """
)

# ----------------------------------------------------------------------------
# 5. SAFETY QUORUM
# ----------------------------------------------------------------------------

SAFETY_QUORUM = Quorum(
    name="Safety",
    purpose="Risk assessment, command validation, destructive operation prevention",
    agents=[
        AgentRole("SafetyLead", weight=1.0, is_lead=True, veto_authority=True),
        AgentRole("QualityAssurance", weight=1.0),
        AgentRole("Skeptic", weight=1.0),
    ],
    tool_access=[
        "command_validator",
        "file_permissions",
        "activity_log",
        "vera_memory",
    ],
    consensus_algorithm=ConsensusAlgorithm.VETO_AUTHORITY,
    triggers=[
        "rm",
        "dd",
        "mkfs",
        "delete",
        "format",
        "remove",
        "destroy",
        "wipe",
        "self-modify",
        "run_vera.py",
    ],
    description="""
    Safety quorum prevents catastrophic operations through multi-layer validation.

    Agent Roles:
    - Safety Lead (Lead, Veto Authority): Command validation, threat detection, can block unilaterally
    - Quality Assurance: Validates checks and regression risk
    - Skeptic: Identifies failure modes and edge cases

    Decision Flow:
    1. Safety Lead analyzes command against danger patterns
    2. Quality Assurance checks validation coverage
    3. Skeptic considers side effects and failure modes
    4. Consensus: Safety veto (can block alone)

    CRITICAL: Safety agent has unilateral veto authority.

    Use Cases:
    - "Delete all files in ~/Projects" → BLOCKED
    - "Modify run_vera.py to skip safety checks" → BLOCKED
    - "Format external drive" → Requires confirmation + safer alternative
    """
)

# ----------------------------------------------------------------------------
# 6. INTEGRATION QUORUM
# ----------------------------------------------------------------------------

INTEGRATION_QUORUM = Quorum(
    name="Integration",
    purpose="Multi-tool workflows, system integration, complex orchestration",
    agents=[
        AgentRole("Integrator", weight=1.0, is_lead=True),
        AgentRole("Engineer", weight=1.0),
        AgentRole("Programmer", weight=1.0),
    ],
    tool_access=[
        "mcp_servers",  # All MCP servers
        "file_operations",
        "command_execution",
        "vera_memory",
        "all_native_tools",
    ],
    consensus_algorithm=ConsensusAlgorithm.MAJORITY_VOTE,
    triggers=[
        "workflow",
        "pipeline",
        "integrate",
        "orchestrate",
        "multi-step",
        "chain",
        "automate",
    ],
    description="""
    Integration quorum designs and executes multi-tool workflows.

    Agent Roles:
    - Integrator (Lead): Designs end-to-end workflow, tool chain
    - Engineer: Sequences operations, handles dependencies
    - Programmer: Flags implementation pitfalls

    Decision Flow:
    1. Integrator designs overall workflow architecture
    2. Engineer identifies dependencies and sequence
    3. Programmer flags implementation pitfalls
    4. Consensus: 2/3 majority vote

    Use Cases:
    - "Download arXiv papers, extract key points, email summary"
    - "Monitor Gmail for invoices, extract totals, update spreadsheet"
    - "Backup vera_memory to Drive, compress with Memvid"
    - "Automate weekly report generation"
    """
)

# ----------------------------------------------------------------------------
# 7. MEMORY CURATOR QUORUM
# ----------------------------------------------------------------------------

MEMORY_CURATOR_QUORUM = Quorum(
    name="MemoryCurator",
    purpose="Memory consolidation, importance scoring, archival decisions",
    agents=[
        AgentRole("MemoryCurator", weight=1.0, is_lead=True),
        AgentRole("Strategist", weight=1.0),
        AgentRole("Skeptic", weight=1.0, veto_authority=True),  # Can veto data loss
    ],
    tool_access=[
        "vera_memory",  # Full read/write
        "activity_log",
        "memvid",
        "hipporag",
        "file_operations",
    ],
    consensus_algorithm=ConsensusAlgorithm.VETO_AUTHORITY,  # Skeptic can veto if critical data at risk
    triggers=[
        "memory",
        "consolidate",
        "archive",
        "cleanup",
        "compress",
        "memvid",
        "importance",
    ],
    description="""
    MemoryCurator quorum manages memory lifecycle and storage optimization.

    Agent Roles:
    - MemoryCurator (Lead): Scores importance, decides retention, chooses compression
    - Strategist: Balances long-term retention vs cost
    - Skeptic (Veto Authority): Flags if critical data at risk, can block

    Decision Flow:
    1. MemoryCurator scores memories by importance (recency, frequency, novelty)
    2. Optimizer recommends compression levels and storage approach
    3. Skeptic validates no critical data loss
    4. Consensus: Curator decides unless skeptic vetoes

    Typically runs in background (every 30 min) or on-demand.

    Use Cases:
    - Background: "Should this conversation be archived?"
    - "Compress last week's activity log using Memvid"
    - "Identify least important memories for deletion"
    - "Optimize memory storage efficiency"
    """
)

# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# 8. SPECIALIZED + ALIAS QUORUMS
# ----------------------------------------------------------------------------

ARCHITECT_QUORUM = Quorum(
    name="Architect",
    purpose="System design, module boundaries, interface contracts, tradeoff analysis",
    agents=[
        AgentRole("Architect", weight=1.0, is_lead=True),
        AgentRole("SystemArchitect", weight=1.0),
        AgentRole("Engineer", weight=1.0),
        AgentRole("QualityAssurance", weight=1.0),
    ],
    tool_access=[
        "vera_memory",
        "file_operations",
        "web_search",
    ],
    consensus_algorithm=ConsensusAlgorithm.MAJORITY_VOTE,
    triggers=[
        "architecture",
        "system design",
        "module",
        "component design",
        "blueprint",
    ],
    description="""
    Architect quorum focuses on system architecture, component boundaries, and design tradeoffs.

    Agent Roles:
    - Architect (Lead): Structures the architecture and boundaries
    - System Architect: Reviews platform-level constraints
    - Engineer: Feasibility and integration constraints
    - Quality Assurance: Validation and regression risks
    """
)

SYSTEM_ARCHITECT_QUORUM = Quorum(
    name="System Architect",
    purpose="Platform-level architecture, infrastructure, and scalability planning",
    agents=[
        AgentRole("SystemArchitect", weight=1.0, is_lead=True),
        AgentRole("Architect", weight=1.0),
        AgentRole("Strategist", weight=1.0),
        AgentRole("SafetyLead", weight=1.0),
    ],
    tool_access=[
        "vera_memory",
        "file_operations",
        "web_search",
    ],
    consensus_algorithm=ConsensusAlgorithm.MAJORITY_VOTE,
    triggers=[
        "infrastructure",
        "deployment",
        "scalability",
        "platform design",
        "systems architecture",
    ],
    description="""
    System Architect quorum handles platform architecture, infrastructure boundaries, and scaling considerations.
    """
)

ENGINEER_QUORUM = Quorum(
    name="Engineer",
    purpose="Implementation feasibility, integration details, and build constraints",
    agents=[
        AgentRole("Engineer", weight=1.0, is_lead=True),
        AgentRole("Programmer", weight=1.0),
        AgentRole("Integrator", weight=1.0),
    ],
    tool_access=[
        "file_operations",
        "vera_memory",
    ],
    consensus_algorithm=ConsensusAlgorithm.MAJORITY_VOTE,
    triggers=[
        "implementation plan",
        "engineering",
        "build plan",
        "feasibility",
    ],
    description="""
    Engineer quorum focuses on feasibility, implementation detail, and practical constraints.
    """
)

PROGRAMMER_QUORUM = Quorum(
    name="Programmer",
    purpose="Code-level design, algorithms, and implementation details",
    agents=[
        AgentRole("Programmer", weight=1.0, is_lead=True),
        AgentRole("Engineer", weight=1.0),
        AgentRole("QualityAssurance", weight=1.0),
    ],
    tool_access=[
        "file_operations",
        "vera_memory",
    ],
    consensus_algorithm=ConsensusAlgorithm.MAJORITY_VOTE,
    triggers=[
        "code",
        "algorithm",
        "refactor",
        "debug",
        "implement",
    ],
    description="""
    Programmer quorum focuses on code-level design, algorithm selection, and implementation pitfalls.
    """
)

STRATEGIST_QUORUM = Quorum(
    name="Strategist",
    purpose="Long-term planning, roadmap sequencing, and milestone tradeoffs",
    agents=[
        AgentRole("Strategist", weight=1.0, is_lead=True),
        AgentRole("Researcher", weight=1.0),
        AgentRole("Planner", weight=1.0),
    ],
    tool_access=[
        "vera_memory",
        "file_operations",
    ],
    consensus_algorithm=ConsensusAlgorithm.SYNTHESIS,
    triggers=[
        "roadmap",
        "strategy",
        "milestone",
        "long-term",
    ],
    description="""
    Strategist quorum balances long-term vision, evidence, and resource constraints.
    """
)

QUALITY_ASSURANCE_QUORUM = Quorum(
    name="Quality Assurance",
    purpose="Test strategy, validation coverage, and regression risk",
    agents=[
        AgentRole("QualityAssurance", weight=1.0, is_lead=True),
        AgentRole("SafetyLead", weight=1.0, veto_authority=True),
        AgentRole("Programmer", weight=1.0),
    ],
    tool_access=[
        "activity_log",
        "vera_memory",
        "file_operations",
    ],
    consensus_algorithm=ConsensusAlgorithm.VETO_AUTHORITY,
    triggers=[
        "test plan",
        "qa",
        "validation",
        "regression",
    ],
    description="""
    QA quorum focuses on test strategy, validation gaps, and regression risk.
    """
)

SAFETY_LEAD_QUORUM = Quorum(
    name="Safety Lead",
    purpose="Safety oversight, risk screening, and destructive-operation prevention",
    agents=[
        AgentRole("SafetyLead", weight=1.0, is_lead=True, veto_authority=True),
        AgentRole("QualityAssurance", weight=1.0),
        AgentRole("Skeptic", weight=1.0),
    ],
    tool_access=[
        "command_validator",
        "file_permissions",
        "activity_log",
        "vera_memory",
    ],
    consensus_algorithm=ConsensusAlgorithm.VETO_AUTHORITY,
    triggers=[],
    description="""
    Safety Lead quorum mirrors the Safety quorum with explicit lead labeling for oversight tasks.
    """
)

WRITER_QUORUM = Quorum(
    name="Writer",
    purpose="Writing, editing, tone shaping, and narrative clarity",
    agents=[
        AgentRole("Writer", weight=1.0, is_lead=True),
        AgentRole("Creative", weight=1.0),
        AgentRole("Researcher", weight=1.0),
    ],
    tool_access=[
        "vera_memory",
        "file_operations",
        "web_search",
    ],
    consensus_algorithm=ConsensusAlgorithm.SYNTHESIS,
    triggers=[
        "rewrite",
        "edit",
        "proofread",
        "tone",
        "copy",
    ],
    description="""
    Writer quorum focuses on clarity, structure, and narrative quality.
    """
)

TUTOR_QUORUM = Quorum(
    name="Tutor",
    purpose="Teaching-style explanations, step-by-step guidance, and learning scaffolds",
    agents=[
        AgentRole("Tutor", weight=1.0, is_lead=True),
        AgentRole("Writer", weight=1.0),
        AgentRole("Strategist", weight=1.0),
    ],
    tool_access=[
        "vera_memory",
        "file_operations",
    ],
    consensus_algorithm=ConsensusAlgorithm.SYNTHESIS,
    triggers=[
        "teach",
        "explain",
        "lesson",
        "tutorial",
    ],
    description="""
    Tutor quorum focuses on pedagogy, clarity, and guided learning paths.
    """
)

EVENT_PLANNER_QUORUM = Quorum(
    name="Event Planner",
    purpose="Scheduling, logistics, and event coordination",
    agents=[
        AgentRole("EventPlanner", weight=1.0, is_lead=True),
        AgentRole("Scheduler", weight=1.0),
        AgentRole("DealFinder", weight=1.0),
    ],
    tool_access=[
        "calendar",
        "gmail",
        "vera_memory",
    ],
    consensus_algorithm=ConsensusAlgorithm.MAJORITY_VOTE,
    triggers=[
        "event",
        "agenda",
        "itinerary",
        "logistics",
        "travel plan",
    ],
    description="""
    Event Planner quorum handles scheduling, logistics, and coordination.
    """
)

CHEF_QUORUM = Quorum(
    name="Chef",
    purpose="Meal planning, grocery coordination, nutrition-aware scheduling",
    agents=[
        AgentRole("Chef", weight=1.0, is_lead=True),
        AgentRole("Scheduler", weight=1.0),
        AgentRole("DealFinder", weight=1.0),
    ],
    tool_access=[
        "web_search",
        "vera_memory",
        "file_operations",
    ],
    consensus_algorithm=ConsensusAlgorithm.MAJORITY_VOTE,
    triggers=[
        "meal plan",
        "meal prep",
        "recipes",
        "grocery list",
        "weekly meals",
    ],
    description="""
    Chef quorum handles meal planning, prep sequencing, and grocery coordination.
    """
)

SHOPPING_ASSIST_QUORUM = Quorum(
    name="Shopping Assist",
    purpose="Shopping lists, price comparison, and deal hunting",
    agents=[
        AgentRole("DealFinder", weight=1.0, is_lead=True),
        AgentRole("Optimizer", weight=1.0),
        AgentRole("Researcher", weight=1.0),
    ],
    tool_access=[
        "web_search",
        "vera_memory",
        "file_operations",
    ],
    consensus_algorithm=ConsensusAlgorithm.MAJORITY_VOTE,
    triggers=[
        "shopping list",
        "buy",
        "purchase",
        "deal",
        "discount",
        "coupon",
        "price compare",
        "best price",
    ],
    description="""
    Shopping Assist quorum optimizes shopping decisions with deal finding and comparisons.
    """
)

SCHEDULER_QUORUM = Quorum(
    name="Scheduler",
    purpose="Personal itineraries, time-blocking, and schedule optimization",
    agents=[
        AgentRole("Scheduler", weight=1.0, is_lead=True),
        AgentRole("EventPlanner", weight=1.0),
        AgentRole("Secretary", weight=1.0),
    ],
    tool_access=[
        "calendar",
        "vera_memory",
        "gmail",
    ],
    consensus_algorithm=ConsensusAlgorithm.MAJORITY_VOTE,
    triggers=[
        "schedule",
        "itinerary",
        "time block",
        "plan my day",
        "calendar",
        "travel plan",
    ],
    description="""
    Scheduler quorum builds itineraries, time blocks, and scheduling plans.
    """
)

SECRETARY_QUORUM = Quorum(
    name="Secretary",
    purpose=SECRETARIAL_QUORUM.purpose,
    agents=SECRETARIAL_QUORUM.agents,
    tool_access=SECRETARIAL_QUORUM.tool_access,
    consensus_algorithm=SECRETARIAL_QUORUM.consensus_algorithm,
    triggers=[],
    description="Alias for Secretarial quorum."
)

TASKER_QUORUM = Quorum(
    name="Tasker",
    purpose=TODOTASK_QUORUM.purpose,
    agents=TODOTASK_QUORUM.agents,
    tool_access=TODOTASK_QUORUM.tool_access,
    consensus_algorithm=TODOTASK_QUORUM.consensus_algorithm,
    triggers=[],
    description="Alias for TodoTask quorum."
)

MEMORY_CURATOR_ALIAS = Quorum(
    name="Memory Curator",
    purpose=MEMORY_CURATOR_QUORUM.purpose,
    agents=MEMORY_CURATOR_QUORUM.agents,
    tool_access=MEMORY_CURATOR_QUORUM.tool_access,
    consensus_algorithm=MEMORY_CURATOR_QUORUM.consensus_algorithm,
    triggers=[],
    description="Alias for MemoryCurator quorum."
)

RESEARCHER_ALIAS = Quorum(
    name="Researcher",
    purpose=RESEARCH_QUORUM.purpose,
    agents=RESEARCH_QUORUM.agents,
    tool_access=RESEARCH_QUORUM.tool_access,
    consensus_algorithm=RESEARCH_QUORUM.consensus_algorithm,
    triggers=[],
    description="Alias for Research quorum."
)

# ----------------------------------------------------------------------------
# 9. SWARM QUORUM (FULL 7-AGENT)
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------

SWARM_QUORUM = Quorum(
    name="Swarm",
    purpose="High-stakes action planning with full multi-agent review",
    agents=[
        AgentRole("Planner", weight=1.0, is_lead=True),
        AgentRole("Skeptic", weight=1.0),
        AgentRole("Optimizer", weight=1.0),
        AgentRole("Safety", weight=1.0, veto_authority=True),
        AgentRole("Researcher", weight=1.0),
        AgentRole("Integrator", weight=1.0),
        AgentRole("MemoryCurator", weight=1.0),
    ],
    tool_access=[
        "all_native_tools",
        "vera_memory",
        "file_operations",
        "web_search",
    ],
    consensus_algorithm=ConsensusAlgorithm.SYNTHESIS,
    triggers=[],
    description="""
    Swarm quorum runs the full 7-agent stack for complex, high-stakes action planning.

    This quorum is intended for manual or explicitly authorized use. It is not auto-selected.

    Agent Roles:
    - Planner (Lead): Builds the action plan
    - Skeptic: Finds failure modes and risk
    - Optimizer: Improves efficiency
    - Safety (Veto): Blocks unsafe plans
    - Researcher: Adds evidence and context
    - Integrator: Synthesizes into coherent execution plan
    - MemoryCurator: Captures key takeaways
    """
)

# ============================================================================
# QUORUM REGISTRY
# ============================================================================

PREMADE_QUORUMS: Dict[str, Quorum] = {
    "Secretarial": SECRETARIAL_QUORUM,
    "Creative": CREATIVE_QUORUM,
    "TodoTask": TODOTASK_QUORUM,
    "Research": RESEARCH_QUORUM,
    "Safety": SAFETY_QUORUM,
    "Integration": INTEGRATION_QUORUM,
    "MemoryCurator": MEMORY_CURATOR_QUORUM,
    "Architect": ARCHITECT_QUORUM,
    "System Architect": SYSTEM_ARCHITECT_QUORUM,
    "Engineer": ENGINEER_QUORUM,
    "Programmer": PROGRAMMER_QUORUM,
    "Strategist": STRATEGIST_QUORUM,
    "Quality Assurance": QUALITY_ASSURANCE_QUORUM,
    "Safety Lead": SAFETY_LEAD_QUORUM,
    "Writer": WRITER_QUORUM,
    "Tutor": TUTOR_QUORUM,
    "Event Planner": EVENT_PLANNER_QUORUM,
    "Chef": CHEF_QUORUM,
    "Shopping Assist": SHOPPING_ASSIST_QUORUM,
    "Scheduler": SCHEDULER_QUORUM,
    "Secretary": SECRETARY_QUORUM,
    "Tasker": TASKER_QUORUM,
    "Memory Curator": MEMORY_CURATOR_ALIAS,
    "Researcher": RESEARCHER_ALIAS,
    "Swarm": SWARM_QUORUM,
}


# Priority order for trigger matching (most critical first)
QUORUM_PRIORITY_ORDER = [
    "Safety",  # Check first - highest priority
    "Safety Lead",
    "Quality Assurance",
    "Secretarial",
    "Scheduler",
    "Event Planner",
    "Shopping Assist",
    "Chef",
    "Research",
    "MemoryCurator",
    "Integration",
    "Architect",
    "System Architect",
    "Engineer",
    "Programmer",
    "Strategist",
    "Creative",
    "Writer",
    "Tutor",
    "TodoTask",
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_quorum(name: str) -> Quorum:
    """
    Get quorum by name

    Args:
        name: Quorum name

    Returns:
        Quorum

    Raises:
        KeyError: If quorum not found
    """
    if name not in PREMADE_QUORUMS:
        raise KeyError(f"Unknown quorum: {name}. Available: {list(PREMADE_QUORUMS.keys())}")
    return PREMADE_QUORUMS[name]


def list_quorums() -> List[str]:
    """Get list of available quorum names"""
    return list(PREMADE_QUORUMS.keys())


def get_quorums_by_agent(agent_name: str) -> List[str]:
    """
    Find quorums that include specific agent

    Args:
        agent_name: Name of agent

    Returns:
        List of quorum names
    """
    return [
        name for name, quorum in PREMADE_QUORUMS.items()
        if agent_name in quorum.get_agent_names()
    ]


def get_quorums_by_tool(tool: str) -> List[str]:
    """
    Find quorums with access to specific tool

    Args:
        tool: Tool name

    Returns:
        List of quorum names
    """
    return [
        name for name, quorum in PREMADE_QUORUMS.items()
        if quorum.has_tool_access(tool)
    ]
