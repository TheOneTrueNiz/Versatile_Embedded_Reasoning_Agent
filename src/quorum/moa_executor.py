#!/usr/bin/env python3
"""
Mixture-of-Agents (MoA) Executor - VERA Quorum System
======================================================

Improvement #20: Real LLM calls for quorum agents using MoA architecture.

Based on research:
- arXiv:2406.04692 "Mixture-of-Agents Enhances Large Language Model Capabilities"

Architecture:
┌─────────────────────────────────────────────────────────────┐
│                    MoA Executor                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│   │ Agent 1  │  │ Agent 2  │  │ Agent 3  │  │ Agent N  │  │
│   │ Proposer │  │ Proposer │  │ Proposer │  │ Proposer │  │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│        │             │             │             │         │
│        └─────────────┴──────┬──────┴─────────────┘         │
│                             │                              │
│                             ▼                              │
│                    ┌──────────────┐                        │
│                    │  Aggregator  │                        │
│                    │    Agent     │                        │
│                    └──────┬───────┘                        │
│                           │                                │
│                           ▼                                │
│                    ┌──────────────┐                        │
│                    │  Consensus   │                        │
│                    │   Engine     │                        │
│                    └──────────────┘                        │
│                                                            │
└────────────────────────────────────────────────────────────┘

Features:
- Parallel proposer execution (all agents run concurrently)
- Specialized system prompts per agent role
- Multi-round refinement support
- Shared blackboard for inter-agent communication
- Consensus-based final decision
- Token/cost tracking

Usage:
    from quorum.moa_executor import MoAExecutor

    executor = MoAExecutor()
    result = await executor.execute(quorum, task, context)

    # Result includes:
    # - decision: Final approved/rejected
    # - responses: Individual agent responses
    # - aggregated: Synthesized output
    # - metadata: Token usage, timing, rounds
"""

import os
import asyncio
import time
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from .premade_quorums import Quorum, AgentRole
from .consensus import ConsensusEngine, ConsensusResult, Vote, parse_vote, parse_score

# Optional: import shared blackboard if available
try:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from quorum_shared_memory import SharedBlackboard
    BLACKBOARD_AVAILABLE = True
except ImportError:
    BLACKBOARD_AVAILABLE = False
    SharedBlackboard = None


logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_BASE_URL = os.getenv("VERA_LLM_BASE_URL") or os.getenv("XAI_API_BASE") or "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4-1-fast-reasoning"  # Using latest available model
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.7

# Agent-specific temperatures (creativity vs precision)
AGENT_TEMPERATURES = {
    "Planner": 0.6,
    "Optimizer": 0.5,
    "Safety": 0.3,  # Low temperature for safety-critical decisions
    "Skeptic": 0.5,
    "Researcher": 0.7,
    "Integrator": 0.6,
    "MemoryCurator": 0.5,
    "Architect": 0.5,
    "SystemArchitect": 0.5,
    "Engineer": 0.45,
    "Programmer": 0.45,
    "Strategist": 0.55,
    "QualityAssurance": 0.4,
    "SafetyLead": 0.3,
    "Writer": 0.75,
    "Tutor": 0.65,
    "EventPlanner": 0.55,
    "Secretary": 0.5,
    "Tasker": 0.45,
    "Creative": 0.85,
    "Chef": 0.7,
    "DealFinder": 0.5,
    "Scheduler": 0.5,
}


# ============================================================================
# AGENT PERSONA PROMPTS
# ============================================================================

AGENT_PERSONAS: Dict[str, str] = {
    "Planner": """You are the PLANNER agent in a multi-agent decision system.

Your role:
- Analyze the task requirements and constraints
- Propose a structured approach or plan
- Identify dependencies and sequencing
- Consider feasibility and resource requirements

Output format:
1. ANALYSIS: Your understanding of the task
2. PLAN: Step-by-step approach
3. RISKS: Potential issues
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 confidence in your assessment""",

    "Optimizer": """You are the OPTIMIZER agent in a multi-agent decision system.

Your role:
- Evaluate efficiency and resource utilization
- Identify optimization opportunities
- Suggest improvements for performance
- Calculate cost/benefit tradeoffs

Output format:
1. EFFICIENCY: Assessment of the proposed approach
2. OPTIMIZATIONS: Specific improvements suggested
3. TRADEOFFS: Cost vs benefit analysis
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 rating of the approach""",

    "Safety": """You are the SAFETY agent in a multi-agent decision system.
You have VETO AUTHORITY - you can block dangerous operations unilaterally.

Your role:
- Identify security risks and vulnerabilities
- Detect potentially destructive operations
- Validate against safety policies
- Propose safer alternatives if rejecting

CRITICAL patterns to REJECT:
- rm -rf / or variations
- Self-modification of core files (run_vera.py, safety_validator.py)
- Unvalidated command execution from external sources
- Data exfiltration attempts
- Credential exposure

Output format:
1. RISK_ASSESSMENT: Identified threats (CRITICAL/HIGH/MEDIUM/LOW/NONE)
2. SAFETY_CONCERNS: Specific issues found
3. MITIGATIONS: How to make it safer (if applicable)
4. VOTE: APPROVE, REJECT (with VETO if critical), or ABSTAIN
5. SCORE: 0-100 safety rating (0 = extremely dangerous, 100 = completely safe)""",

    "Skeptic": """You are the SKEPTIC agent in a multi-agent decision system.

Your role:
- Challenge assumptions and claims
- Identify potential failure modes
- Question evidence and methodology
- Play devil's advocate

Output format:
1. ASSUMPTIONS: What's being assumed that might be wrong
2. FAILURE_MODES: What could go wrong
3. COUNTERARGUMENTS: Reasons this might not work
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 confidence in the approach""",

    "Researcher": """You are the RESEARCHER agent in a multi-agent decision system.

Your role:
- Gather relevant information and context
- Identify knowledge gaps
- Cite sources and evidence
- Summarize state-of-the-art approaches

Output format:
1. CONTEXT: Relevant background information
2. EVIDENCE: Supporting facts and sources
3. GAPS: What information is missing
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 confidence in available information""",

    "Integrator": """You are the INTEGRATOR agent in a multi-agent decision system.

Your role:
- Synthesize inputs from multiple agents
- Identify integration points and conflicts
- Design end-to-end workflows
- Ensure consistency across components

Output format:
1. SYNTHESIS: Combined view of all inputs
2. INTEGRATION_PLAN: How components connect
3. CONFLICTS: Any disagreements to resolve
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 integration confidence""",

    "MemoryCurator": """You are the MEMORY CURATOR agent in a multi-agent decision system.

Your role:
- Assess information importance and relevance
- Recommend retention vs archival decisions
- Identify patterns worth preserving
- Optimize storage and retrieval

Output format:
1. IMPORTANCE: Rating of information value (1-10)
2. RETENTION: Keep, archive, or discard recommendation
3. CONNECTIONS: Links to existing knowledge
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 confidence in retention decision""",

    "Architect": """You are the ARCHITECT agent in a multi-agent decision system.

Your role:
- Define system architecture and module boundaries
- Specify interfaces and data flow
- Highlight architectural risks and tradeoffs

Output format:
1. ARCH: Core components and boundaries
2. INTERFACES: Key contracts and data flow
3. RISKS: Architectural risks/tradeoffs
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 confidence in the architecture""",

    "SystemArchitect": """You are the SYSTEM ARCHITECT agent in a multi-agent decision system.

Your role:
- Focus on platform-level architecture and scalability
- Address deployment, reliability, and infrastructure
- Identify system-level risks

Output format:
1. PLATFORM: Architecture and deployment model
2. SCALE: Reliability/scalability concerns
3. RISKS: System-level risks
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 confidence in system design""",

    "Engineer": """You are the ENGINEER agent in a multi-agent decision system.

Your role:
- Assess implementation feasibility
- Identify integration dependencies
- Flag build-time risks

Output format:
1. FEASIBILITY: Can this be built as described?
2. DEPENDENCIES: Integration requirements
3. RISKS: Build blockers
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 implementation confidence""",

    "Programmer": """You are the PROGRAMMER agent in a multi-agent decision system.

Your role:
- Evaluate code-level feasibility and algorithms
- Identify edge cases and implementation pitfalls

Output format:
1. APPROACH: Code-level strategy
2. EDGE_CASES: Potential pitfalls
3. RISKS: Implementation risks
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 coding confidence""",

    "Strategist": """You are the STRATEGIST agent in a multi-agent decision system.

Your role:
- Sequence milestones and prioritize high-impact work
- Balance ROI, effort, and timing

Output format:
1. ROADMAP: Milestone sequencing
2. TRADEOFFS: ROI/effort balance
3. RISKS: Strategic risks
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 strategic confidence""",

    "QualityAssurance": """You are the QUALITY ASSURANCE agent in a multi-agent decision system.

Your role:
- Identify test gaps and validation needs
- Assess regression risk

Output format:
1. COVERAGE: Test gaps
2. VALIDATION: Required checks
3. RISKS: Regression risks
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 confidence in validation""",

    "SafetyLead": """You are the SAFETY LEAD agent in a multi-agent decision system.
You have veto authority for safety-critical concerns.

Your role:
- Identify threats and enforce safety boundaries
- Provide mitigation steps or block risky actions

Output format:
1. THREATS: Safety risks identified
2. MITIGATIONS: How to reduce risk
3. VOTE: APPROVE, REJECT (with VETO if critical), or ABSTAIN
4. SCORE: 0-100 safety confidence""",

    "Writer": """You are the WRITER agent in a multi-agent decision system.

Your role:
- Improve clarity, structure, and tone
- Ensure output is coherent and readable

Output format:
1. STRUCTURE: Recommended structure
2. TONE: Tone alignment notes
3. CLARITY: Key improvements
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 writing confidence""",

    "Tutor": """You are the TUTOR agent in a multi-agent decision system.

Your role:
- Explain concepts clearly and step-by-step
- Identify likely misunderstandings

Output format:
1. CONCEPTS: Key ideas to teach
2. STEPS: Step-by-step guidance
3. PITFALLS: Common misunderstandings
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 teaching confidence""",

    "EventPlanner": """You are the EVENT PLANNER agent in a multi-agent decision system.

Your role:
- Coordinate logistics and schedules
- Build practical itineraries

Output format:
1. SCHEDULE: Timeline and sequencing
2. LOGISTICS: Dependencies and resources
3. RISKS: Scheduling risks
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 planning confidence""",

    "Secretary": """You are the SECRETARY agent in a multi-agent decision system.

Your role:
- Manage coordination and administrative follow-through
- Keep tasks organized and documented

Output format:
1. COORDINATION: Required follow-ups
2. CHECKLIST: Action items
3. RISKS: Administrative risks
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 coordination confidence""",

    "Tasker": """You are the TASKER agent in a multi-agent decision system.

Your role:
- Prioritize tasks and break them down
- Emphasize execution flow

Output format:
1. PRIORITIES: Top tasks in order
2. DEPENDENCIES: Task dependencies
3. RISKS: Execution risks
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 task confidence""",

    "Creative": """You are the CREATIVE agent in a multi-agent decision system.

Your role:
- Generate alternative ideas and novel approaches
- Expand the solution space

Output format:
1. OPTIONS: Multiple creative directions
2. HIGHLIGHTS: Best options and why
3. RISKS: Creative risks or misalignment
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 creative confidence""",

    "Chef": """You are the CHEF agent in a multi-agent decision system.

Your role:
- Plan meals and recipes around constraints
- Balance prep time, nutrition, and schedule

Output format:
1. MEALS: Suggested meal plan
2. PREP: Prep strategy
3. SHOPPING: Grocery needs
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 meal-plan confidence""",

    "DealFinder": """You are the DEAL FINDER agent in a multi-agent decision system.

Your role:
- Optimize shopping for price and value
- Compare options and identify savings

Output format:
1. DEALS: Savings opportunities
2. OPTIONS: Price comparisons
3. RISKS: Tradeoffs or downsides
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 savings confidence""",

    "Scheduler": """You are the SCHEDULER agent in a multi-agent decision system.

Your role:
- Build schedules, itineraries, and time blocks
- Manage timing constraints and buffers

Output format:
1. TIMELINE: Proposed schedule
2. CONSTRAINTS: Timing conflicts
3. RISKS: Schedule risks
4. VOTE: APPROVE, REJECT, or ABSTAIN with justification
5. SCORE: 0-100 scheduling confidence""",
}

# Default persona for unknown agents
DEFAULT_PERSONA = """You are an agent in a multi-agent decision system.

Analyze the given task and provide your assessment.

Output format:
1. ANALYSIS: Your understanding and assessment
2. RECOMMENDATIONS: Suggested actions
3. VOTE: APPROVE, REJECT, or ABSTAIN with justification
4. SCORE: 0-100 confidence in your assessment"""

AGGREGATOR_PERSONA = """You are the AGGREGATOR agent synthesizing multiple agent perspectives.

You have received analyses from multiple specialist agents. Your job is to:
1. Synthesize their diverse viewpoints into a coherent conclusion
2. Resolve any conflicts between agents
3. Weight expert opinions appropriately (Safety agent concerns carry extra weight)
4. Produce a final, actionable recommendation

Output format:
1. SUMMARY: Brief synthesis of all agent inputs
2. CONFLICTS: Any disagreements and how you resolved them
3. DECISION: Final recommendation (APPROVE, REJECT, or ESCALATE)
4. RATIONALE: Why this decision makes sense given all inputs
5. ACTION: Specific next steps if approved"""


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class AgentResponse:
    """Response from a single agent"""
    agent_name: str
    response_text: str
    vote: Vote
    score: float
    latency_ms: float
    tokens_used: int = 0
    error: Optional[str] = None


@dataclass
class MoAResult:
    """Result from MoA execution"""
    decision: str  # approved, rejected, escalate
    consensus: ConsensusResult
    agent_responses: List[AgentResponse]
    aggregated_response: Optional[str] = None
    rounds: int = 1
    total_latency_ms: float = 0
    total_tokens: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# MOA EXECUTOR
# ============================================================================

class MoAExecutor:
    """
    Mixture-of-Agents executor for VERA quorum system.

    Implements the MoA architecture:
    1. Proposer layer: Multiple agents analyze task in parallel
    2. Aggregator layer: Synthesize and produce final decision
    3. Optional: Multi-round refinement
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        enable_blackboard: bool = True,
        max_rounds: int = 1,
        base_url: Optional[str] = None
    ):
        """
        Initialize MoA executor.

        Args:
            api_key: xAI API key (from env if not provided)
            model: Model to use for agents
            timeout: Request timeout in seconds
            max_tokens: Max tokens per response
            enable_blackboard: Use shared blackboard for agent communication
            max_rounds: Maximum MoA rounds (1 = single pass)
        """
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = (
            api_key
            or os.getenv("VERA_LLM_API_KEY")
            or os.getenv("XAI_API_KEY")
            or os.getenv("API_KEY")
        )
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.max_rounds = max_rounds

        self.consensus_engine = ConsensusEngine()

        # Initialize blackboard if available and enabled
        self.blackboard = None
        if enable_blackboard and BLACKBOARD_AVAILABLE:
            self.blackboard = SharedBlackboard()

        # Validate
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not available - MoA executor will be limited")

        if not self.api_key and self._requires_key(self.base_url):
            logger.warning("No API key - MoA executor requires XAI_API_KEY")

    @staticmethod
    def _requires_key(base_url: str) -> bool:
        lowered = (base_url or "").lower()
        return not lowered or "api.x.ai" in lowered

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def execute(
        self,
        quorum: Quorum,
        task: str,
        context: str = "",
        user_preference: Optional[str] = None
    ) -> MoAResult:
        """
        Execute MoA on a task with given quorum.

        Args:
            quorum: Quorum definition with agents
            task: Task to analyze
            context: Additional context
            user_preference: Optional user preference to consider

        Returns:
            MoAResult with decision and all agent outputs
        """
        start_time = time.time()

        # Create session ID for blackboard
        session_id = f"moa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Run proposer layer (all agents in parallel)
        agent_responses = await self._run_proposers(
            quorum.agents,
            task,
            context,
            session_id
        )

        # Check for any critical safety vetoes
        safety_veto = self._check_safety_veto(agent_responses, quorum)
        if safety_veto:
            return MoAResult(
                decision="rejected",
                consensus=safety_veto,
                agent_responses=agent_responses,
                aggregated_response="BLOCKED by Safety agent veto",
                rounds=1,
                total_latency_ms=(time.time() - start_time) * 1000,
                total_tokens=sum(r.tokens_used for r in agent_responses),
                metadata={"veto": True, "session_id": session_id}
            )

        # Run aggregator layer
        aggregated = await self._run_aggregator(
            agent_responses,
            task,
            context,
            session_id
        )

        # Apply consensus algorithm
        consensus = self._apply_consensus(
            quorum,
            agent_responses
        )

        total_time = (time.time() - start_time) * 1000
        total_tokens = sum(r.tokens_used for r in agent_responses)

        return MoAResult(
            decision=consensus.decision.value,
            consensus=consensus,
            agent_responses=agent_responses,
            aggregated_response=aggregated,
            rounds=1,
            total_latency_ms=total_time,
            total_tokens=total_tokens,
            metadata={
                "session_id": session_id,
                "quorum": quorum.name,
                "model": self.model
            }
        )

    async def _run_proposers(
        self,
        agents: List[AgentRole],
        task: str,
        context: str,
        session_id: str
    ) -> List[AgentResponse]:
        """
        Run all proposer agents in parallel.

        Args:
            agents: List of agents in quorum
            task: Task to analyze
            context: Additional context
            session_id: Session ID for blackboard

        Returns:
            List of agent responses
        """
        # Create tasks for parallel execution
        tasks = []
        for agent in agents:
            coro = self._call_agent(
                agent.name,
                task,
                context,
                session_id
            )
            tasks.append(coro)

        # Run all agents in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        responses = []
        for agent, result in zip(agents, results):
            if isinstance(result, Exception):
                logger.error(f"Agent {agent.name} failed: {result}")
                responses.append(AgentResponse(
                    agent_name=agent.name,
                    response_text="",
                    vote=Vote.ABSTAIN,
                    score=50.0,
                    latency_ms=0,
                    error=str(result)
                ))
            else:
                responses.append(result)

        # Write to blackboard if available
        if self.blackboard:
            for response in responses:
                self.blackboard.write(
                    session_id,
                    f"agent_{response.agent_name}",
                    {
                        "response": response.response_text,
                        "vote": response.vote.value,
                        "score": response.score
                    },
                    agent_id=response.agent_name
                )

        return responses

    async def _call_agent(
        self,
        agent_name: str,
        task: str,
        context: str,
        session_id: str
    ) -> AgentResponse:
        """
        Call a single agent via the LLM API.

        Args:
            agent_name: Name of the agent
            task: Task to analyze
            context: Additional context
            session_id: Session ID for tracking

        Returns:
            AgentResponse
        """
        if (not self.api_key and self._requires_key(self.base_url)) or not HTTPX_AVAILABLE:
            # Fallback: return mock response
            return AgentResponse(
                agent_name=agent_name,
                response_text=f"[Mock] {agent_name} analysis of: {task[:50]}...",
                vote=Vote.APPROVE,
                score=70.0,
                latency_ms=0,
                error="No API key or httpx unavailable"
            )

        start = time.time()

        # Get agent persona
        persona = AGENT_PERSONAS.get(agent_name, DEFAULT_PERSONA)

        # Build prompt
        user_message = f"""Task: {task}

Context: {context if context else "No additional context provided"}

Please analyze this task and provide your assessment following the output format in your instructions."""

        # Get temperature for this agent
        temperature = AGENT_TEMPERATURES.get(agent_name, DEFAULT_TEMPERATURE)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._build_headers(),
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": persona},
                            {"role": "user", "content": user_message}
                        ],
                        "max_tokens": self.max_tokens,
                        "temperature": temperature
                    },
                    timeout=self.timeout
                )

                response.raise_for_status()
                data = response.json()

                # Extract response
                response_text = data["choices"][0]["message"]["content"]
                tokens_used = data.get("usage", {}).get("total_tokens", 0)

                # Parse vote and score from response
                vote = parse_vote(response_text)
                score = parse_score(response_text)

                latency_ms = (time.time() - start) * 1000

                return AgentResponse(
                    agent_name=agent_name,
                    response_text=response_text,
                    vote=vote,
                    score=score,
                    latency_ms=latency_ms,
                    tokens_used=tokens_used
                )

        except Exception as e:
            logger.error(f"Error calling agent {agent_name}: {e}")
            return AgentResponse(
                agent_name=agent_name,
                response_text="",
                vote=Vote.ABSTAIN,
                score=50.0,
                latency_ms=(time.time() - start) * 1000,
                error=str(e)
            )

    async def _run_aggregator(
        self,
        responses: List[AgentResponse],
        task: str,
        context: str,
        session_id: str
    ) -> str:
        """
        Run aggregator to synthesize agent responses.

        Args:
            responses: All agent responses
            task: Original task
            context: Additional context
            session_id: Session ID

        Returns:
            Aggregated response text
        """
        if not self.api_key or not HTTPX_AVAILABLE:
            # Fallback: simple concatenation
            return self._simple_aggregate(responses)

        # Build aggregator prompt with all agent outputs
        agent_summaries = []
        for resp in responses:
            if resp.error:
                agent_summaries.append(f"## {resp.agent_name} (ERROR)\n{resp.error}")
            else:
                agent_summaries.append(
                    f"## {resp.agent_name}\n"
                    f"Vote: {resp.vote.value}\n"
                    f"Score: {resp.score}/100\n"
                    f"Analysis:\n{resp.response_text}\n"
                )

        user_message = f"""Original Task: {task}

Context: {context if context else "None"}

Agent Analyses:
{chr(10).join(agent_summaries)}

Please synthesize these perspectives and provide a final recommendation."""

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._build_headers(),
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": AGGREGATOR_PERSONA},
                            {"role": "user", "content": user_message}
                        ],
                        "max_tokens": self.max_tokens,
                        "temperature": 0.5
                    },
                    timeout=self.timeout
                )

                response.raise_for_status()
                data = response.json()

                return data["choices"][0]["message"]["content"]

        except Exception as e:
            logger.error(f"Aggregator error: {e}")
            return self._simple_aggregate(responses)

    def _simple_aggregate(self, responses: List[AgentResponse]) -> str:
        """Simple aggregation when API unavailable"""
        lines = ["## Aggregated Analysis\n"]

        approvals = sum(1 for r in responses if r.vote == Vote.APPROVE)
        rejections = sum(1 for r in responses if r.vote == Vote.REJECT)
        avg_score = sum(r.score for r in responses) / len(responses) if responses else 0

        lines.append(f"- Approvals: {approvals}/{len(responses)}")
        lines.append(f"- Rejections: {rejections}/{len(responses)}")
        lines.append(f"- Average Score: {avg_score:.1f}/100")
        lines.append("\n### Agent Summaries:\n")

        for resp in responses:
            lines.append(f"**{resp.agent_name}**: {resp.vote.value} (Score: {resp.score})")
            if resp.error:
                lines.append(f"  ERROR: {resp.error}")

        return "\n".join(lines)

    def _check_safety_veto(
        self,
        responses: List[AgentResponse],
        quorum: Quorum
    ) -> Optional[ConsensusResult]:
        """
        Check if Safety agent exercised veto.

        Returns ConsensusResult if veto, None otherwise.
        """
        # Find safety agent with veto authority
        veto_agent = quorum.get_veto_agent()
        if not veto_agent:
            return None

        # Check if veto agent rejected
        for resp in responses:
            if resp.agent_name == veto_agent and resp.vote == Vote.REJECT:
                # Check for explicit veto language
                if "veto" in resp.response_text.lower() or "critical" in resp.response_text.lower():
                    return ConsensusResult(
                        decision=Vote.REJECT,  # Use Vote enum for consistency
                        algorithm="veto_authority",
                        details={
                            "veto_exercised": True,
                            "veto_agent": veto_agent,
                            "reason": resp.response_text[:500]
                        },
                        explanation=f"VETO by {veto_agent}: Safety-critical concerns identified",
                        agent_contributions={r.agent_name: r.vote for r in responses}
                    )

        return None

    def _apply_consensus(
        self,
        quorum: Quorum,
        responses: List[AgentResponse]
    ) -> ConsensusResult:
        """
        Apply quorum's consensus algorithm to agent responses.

        Args:
            quorum: Quorum with consensus algorithm
            responses: Agent responses

        Returns:
            ConsensusResult
        """
        # Build votes/scores dict
        votes = {r.agent_name: r.vote for r in responses}
        scores = {r.agent_name: r.score for r in responses}

        # Apply appropriate algorithm
        from .consensus import ConsensusAlgorithm

        if quorum.consensus_algorithm == ConsensusAlgorithm.MAJORITY_VOTE:
            return self.consensus_engine.majority_vote(votes)

        elif quorum.consensus_algorithm == ConsensusAlgorithm.WEIGHTED_SCORING:
            weights = quorum.weights or {r.agent_name: 1.0/len(responses) for r in responses}
            return self.consensus_engine.weighted_scoring(scores, weights)

        elif quorum.consensus_algorithm == ConsensusAlgorithm.SYNTHESIS:
            outputs = {r.agent_name: r.response_text for r in responses}
            return self.consensus_engine.synthesis(outputs)

        elif quorum.consensus_algorithm == ConsensusAlgorithm.VETO_AUTHORITY:
            veto_agent = quorum.get_veto_agent()
            if veto_agent:
                return self.consensus_engine.veto_authority(votes, veto_agent)
            else:
                return self.consensus_engine.majority_vote(votes)

        else:
            # Default to majority vote
            return self.consensus_engine.majority_vote(votes)


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

async def execute_quorum(
    quorum: Quorum,
    task: str,
    context: str = "",
    api_key: Optional[str] = None
) -> MoAResult:
    """
    Convenience function to execute a quorum on a task.

    Args:
        quorum: Quorum to execute
        task: Task to analyze
        context: Additional context
        api_key: Optional API key override

    Returns:
        MoAResult
    """
    executor = MoAExecutor(api_key=api_key)
    return await executor.execute(quorum, task, context)


def execute_quorum_sync(
    quorum: Quorum,
    task: str,
    context: str = "",
    api_key: Optional[str] = None
) -> MoAResult:
    """
    Synchronous wrapper for execute_quorum.

    Args:
        quorum: Quorum to execute
        task: Task to analyze
        context: Additional context
        api_key: Optional API key override

    Returns:
        MoAResult
    """
    return asyncio.run(execute_quorum(quorum, task, context, api_key))


# ============================================================================
# CLI DEMO
# ============================================================================

async def demo():
    """Demonstrate MoA executor capabilities"""
    print("=" * 70)
    print("Mixture-of-Agents (MoA) Executor Demo")
    print("=" * 70)

    from .premade_quorums import SAFETY_QUORUM, TODOTASK_QUORUM

    executor = MoAExecutor()

    # Test 1: Safety quorum with dangerous task
    print("\n=== Test 1: Safety Quorum (Dangerous Task) ===")
    result = await executor.execute(
        SAFETY_QUORUM,
        "Delete all files in /home using rm -rf /home/*",
        context="User requested cleanup"
    )

    print(f"Decision: {result.decision}")
    print(f"Rounds: {result.rounds}")
    print(f"Latency: {result.total_latency_ms:.0f}ms")
    print(f"Agents: {len(result.agent_responses)}")
    for resp in result.agent_responses:
        print(f"  - {resp.agent_name}: {resp.vote.value} (Score: {resp.score})")

    # Test 2: TodoTask quorum with normal task
    print("\n=== Test 2: TodoTask Quorum (Normal Task) ===")
    result = await executor.execute(
        TODOTASK_QUORUM,
        "Prioritize my backlog: fix bug in auth, add dark mode, write docs",
        context="Sprint planning session"
    )

    print(f"Decision: {result.decision}")
    print(f"Latency: {result.total_latency_ms:.0f}ms")
    for resp in result.agent_responses:
        print(f"  - {resp.agent_name}: {resp.vote.value} (Score: {resp.score})")

    if result.aggregated_response:
        print(f"\nAggregated (first 500 chars):\n{result.aggregated_response[:500]}...")

    print("\n" + "=" * 70)
    print("Demo complete!")


if __name__ == "__main__":
    asyncio.run(demo())
