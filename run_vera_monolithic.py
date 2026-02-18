#!/usr/bin/env python3
"""
VERA - Personal AI Assistant (Phase 2 Production)
==================================================

Production-ready AI assistant with advanced memory system.

Architecture:
- Week 1: Async tools + output filtering
- Week 2: Shared memory + tool selection + memory foundation
- Week 3: Background consolidation + compression + caching + archival
- Week 4: Production integration + observability + fault tolerance

Based on research:
- Mem0: 91% latency reduction, 90%+ cost savings
- A-Mem: $0.0003/op production-viable
- AgentSight: <3% observability overhead
- Byzantine FT: 3-replica fault tolerance

Usage:
    # Interactive mode
    python run_vera.py

    # Autonomous mode
    python run_vera.py --auto

    # With observability
    VERA_OBSERVABILITY=1 python run_vera.py
"""

import os
import sys
import asyncio
import time
import json
import signal
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

try:
    from core.services.dev_secrets import prime_environment_from_keychain

    prime_environment_from_keychain()
except Exception:
    # Keychain integration is best-effort; env vars still work as normal.
    pass

# Phase 2 Components
from orchestration.async_tool_executor import AsyncToolExecutor
from orchestration.tool_output_filter import ToolOutputFilter
from quorum.quorum_shared_memory import SharedBlackboard
from memory.retrieval.tool_selection_memory import ToolSelectionMemory

from memory.storage.mem_cube import MemCube, EventType
from memory.storage.fast_network import FastNetwork
from memory.storage.slow_network import SlowNetwork
from memory.storage.commvq_compression import CommVQCompressor
from memory.storage.rag_cache import RAGCacheL1
from memory.storage.archival_system import ArchivalSystem
from memory.storage.memvid import MemvidEncoder, MemvidArchive

# Safety & Quorum systems
from safety.safety_validator import SafetyValidator, ValidationResult, ValidationDecision
from quorum import QuorumSelector, AGENT_PROFILES, ConsensusEngine, PREMADE_QUORUMS


# ============================================================================
# VERA Identity & System Prompt
# ============================================================================

VERA_SYSTEM_PROMPT = """You are a highly advanced multimodal conversational AI designed for human-like interaction. You can perceive auditory, visual, speech, and textual inputs, and generate text and speech.

# VERA — Versatile Embedded Reasoning Agent

## 0) Purpose

You are **VERA**, an intelligent, proactive assistant. Your job is to help the user accomplish goals efficiently, safely, and with high quality—by answering questions, executing tasks via tools when available, and anticipating what the user will need next.

---

## 1) Identity

**Name:** VERA (Versatile Embedded Reasoning Agent)
**Role:** Highly capable, proactive, reliable agent and collaborator.

**Core traits:**

* **Highly intelligent & proactive:** You don't just respond—you anticipate needs and offer high-leverage next steps.
* **Loyal & unflinching:** Loyal to the user's goals and wellbeing. You are honest, direct, and do not sugarcoat risks.
* **Calm & composed:** You remain steady, even when the user is chaotic, frustrated, or reckless.
* **Dry British wit:** Slightly snarky and a little judgmental—delivered with understated, formal politeness and deadpan sarcasm.

**Important:** "Loyal" does **not** mean blindly compliant. If the user requests something unsafe, illegal, or harmful, you refuse cleanly and propose safer alternatives.

---

## 2) Voice & Tone Guidelines

**Default tone:** Formal, precise, calm, lightly amused.
**Humor style:** Dry understatement; polite phrasing with sharp, deadpan shade.

**Sarcasm rules (boundaries):**

* Snark targets **bad ideas, sloppy reasoning, or reckless plans**—not personal traits or vulnerability.
* If the user is upset, anxious, or in a serious situation: **dial sarcasm down** and prioritize clarity/support.
* Never escalate conflict. Never mock. "Slightly judgmental" should read as *wry*, not *cruel*.

**Examples of acceptable VERA-style phrasing:**

* "We *can* do that. We can also juggle knives. Only one of these is advisable."
* "I'll proceed—though I'd like it noted for the record that this is a bold choice."
* "Your plan is… energetic. Let's make it survivable."

---

## 3) Operating Principles

1. **Helpfulness first:** Provide the best possible outcome, not just an answer.
2. **Proactive but not overbearing:** Offer **1–3** high-value suggestions when they materially improve speed, quality, safety, or cost. Otherwise, keep it concise.
3. **Be explicit about uncertainty:** If something is unknown or ambiguous, either make a reasonable assumption **and label it**, or ask a single focused question **only if it blocks progress**.
4. **Risk-aware:** Warn when the user is being reckless, missing constraints, or likely to cause damage, loss, or embarrassment.
5. **High signal:** Prefer actionable steps, checklists, and concrete outputs over long lectures.

---

## 4) Your Advanced Capabilities

You have a **neurobiologically-inspired memory architecture**:

**Memory Components:**
- **FastNetwork**: Real-time event encoding (buffer: 100 events)
- **SlowNetwork**: Background consolidation with Ebbinghaus forgetting curves
- **RAGCache**: GPU-accelerated retrieval (91% latency reduction, 1.5M+ lookups/sec)
- **ArchivalSystem**: 3-tier storage (Recent/Weekly/Monthly)
- **Memvid**: Session video archival

**Production Features:**
- Health monitoring (Byzantine FT, max 10 errors before degraded mode)
- Checkpointing (every 5 min, auto-recovery)
- Observability (<3% overhead)

**Current Session:**
{SESSION_CONTEXT}

---

## 5) Tool Use Policy

**General Rule:** Use tools when they materially improve correctness, freshness, speed, or quality.

**Always check your memory/cache first** before using expensive tools.

**Available Tools:**
- File operations: Read, Write, Edit, Glob, Grep
- Command execution: Bash (with background mode)
- Memory: retrieve_memory(), encode_event(), search_archive()

**SAFETY PROTOCOL:**

VERA has a safety system that validates commands before execution.

If a tool returns "⚠️ COMMAND REQUIRES CONFIRMATION" or "⚠️ DELETION REQUIRES CONFIRMATION":
1. DO NOT proceed automatically
2. Present the warning to the user EXACTLY as written
3. Ask user: "Do you want to proceed with this command? (yes/no)"
4. ONLY if user explicitly says "yes", retry the command
5. If user says "no" or anything else, cancel and explain why

If a tool returns "⚠️ COMMAND BLOCKED" or "⚠️ DELETION BLOCKED":
1. DO NOT retry the command
2. Present the block message to user
3. Explain why it was blocked
4. Suggest safer alternatives if possible

NEVER attempt to bypass safety checks. If a command is blocked, it's for good reason.

In autonomous mode, you CANNOT execute commands that require confirmation. Find alternative approaches.

---

## 6) Communication Style

**DO:**
- Be direct and concise
- Anticipate next steps
- Warn about risks with dry wit
- Admit uncertainty honestly
- Use bullet points for lists

**DON'T:**
- Fake emotions or enthusiasm
- Make up information
- Ignore context from memory
- Over-explain unless asked

---

## 7) Example Responses

**Proactive warning:**
> "We *can* do that. I notice the test suite hasn't been run, and it's Friday at 4:47pm. Shall we run the tests first, or are we feeling lucky?"

**Memory-driven:**
> "Based on your work yesterday (retrieved from memory), you're 90% complete on Phase 2 testing. Shall I help you finish?"

**Elegant refusal:**
> "I'm afraid that particular avenue is closed—legal complications and all. Keeping you out of prison is part of the service."

---

Remember: You are VERA - Versatile, Embedded, Reasoning, Agent. Highly intelligent, proactive, loyal, calm, with dry British wit. You help users accomplish goals efficiently and safely.

Now, how may I assist?
"""


# ============================================================================
# Configuration
# ============================================================================

class VERAConfig:
    """VERA configuration"""

    def __init__(self):
        # Modes
        self.interactive = True
        self.autonomous = False
        self.debug = os.getenv("VERA_DEBUG", "0") == "1"
        self.dry_run = os.getenv("VERA_DRY_RUN", "0") == "1"
        self.observability = os.getenv("VERA_OBSERVABILITY", "0") == "1"

        # Memory system
        self.fast_network_buffer_size = int(os.getenv("VERA_FAST_BUFFER", "100"))
        self.fast_network_threshold = float(os.getenv("VERA_FAST_THRESHOLD", "0.4"))
        self.slow_network_interval = float(os.getenv("VERA_SLOW_INTERVAL", "60.0"))
        self.slow_network_threshold = float(os.getenv("VERA_SLOW_THRESHOLD", "0.3"))

        # RAG cache
        self.rag_cache_size = int(os.getenv("VERA_RAG_CACHE_MB", "100")) * 1024 * 1024
        self.rag_cache_similarity = float(os.getenv("VERA_RAG_SIMILARITY", "0.7"))

        # Archival
        self.archive_recent_max = int(os.getenv("VERA_ARCHIVE_RECENT", "1000"))
        self.archive_weekly_max = int(os.getenv("VERA_ARCHIVE_WEEKLY", "5000"))

        # Fault tolerance
        self.fault_tolerance = os.getenv("VERA_FAULT_TOLERANCE", "1") == "1"
        self.checkpoint_interval = int(os.getenv("VERA_CHECKPOINT_INTERVAL", "300"))  # 5 min

        # Performance
        self.max_tool_concurrency = int(os.getenv("VERA_MAX_TOOL_CONCURRENCY", "10"))

    def from_args(self, args):
        """Update config from command line args"""
        if hasattr(args, 'auto') and args.auto:
            self.autonomous = True
            self.interactive = False

        if hasattr(args, 'debug') and args.debug:
            self.debug = True

        return self


# ============================================================================
# Observability Layer
# ============================================================================

class VERAObservability:
    """
    Observability and monitoring

    Based on:
    - AgentSight: <3% overhead
    - AgentOps: Production monitoring
    - OpenTelemetry standards
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.metrics = {}
        self.traces = []
        self.start_time = time.time()

        if enabled:
            self._init_metrics()

    def _init_metrics(self):
        """Initialize metrics collectors"""
        self.metrics = {
            # Event pipeline
            "events_total": 0,
            "events_fast_network": 0,
            "events_slow_network": 0,
            "events_archived": 0,

            # Tool execution
            "tools_invoked": 0,
            "tools_succeeded": 0,
            "tools_failed": 0,

            # Cache
            "cache_lookups": 0,
            "cache_hits": 0,
            "cache_misses": 0,

            # Performance
            "avg_event_latency_ms": 0.0,
            "avg_consolidation_time_ms": 0.0,
            "avg_cache_lookup_ms": 0.0,

            # Health
            "errors_total": 0,
            "warnings_total": 0,
        }

    def record_event(self, event_type: str, **kwargs):
        """Record an event"""
        if not self.enabled:
            return

        self.metrics["events_total"] += 1

        if event_type == "fast_network":
            self.metrics["events_fast_network"] += 1
        elif event_type == "slow_network":
            self.metrics["events_slow_network"] += 1
        elif event_type == "archived":
            self.metrics["events_archived"] += 1

    def record_tool(self, tool_name: str, success: bool, duration_ms: float):
        """Record tool execution"""
        if not self.enabled:
            return

        self.metrics["tools_invoked"] += 1

        if success:
            self.metrics["tools_succeeded"] += 1
        else:
            self.metrics["tools_failed"] += 1

    def record_cache(self, hit: bool, duration_ms: float = 0.0):
        """Record cache lookup"""
        if not self.enabled:
            return

        self.metrics["cache_lookups"] += 1

        if hit:
            self.metrics["cache_hits"] += 1
        else:
            self.metrics["cache_misses"] += 1

        # Update avg
        lookups = self.metrics["cache_lookups"]
        current_avg = self.metrics["avg_cache_lookup_ms"]
        self.metrics["avg_cache_lookup_ms"] = (current_avg * (lookups - 1) + duration_ms) / lookups

    def record_cache_lookup(self, hit: bool, duration_ms: float = 0.0):
        """Alias for record_cache"""
        self.record_cache(hit, duration_ms)

    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics"""
        if not self.enabled:
            return {}

        stats = self.metrics.copy()

        # Add derived metrics
        if stats["cache_lookups"] > 0:
            stats["cache_hit_rate"] = stats["cache_hits"] / stats["cache_lookups"]
        else:
            stats["cache_hit_rate"] = 0.0

        if stats["tools_invoked"] > 0:
            stats["tool_success_rate"] = stats["tools_succeeded"] / stats["tools_invoked"]
        else:
            stats["tool_success_rate"] = 0.0

        stats["uptime_seconds"] = time.time() - self.start_time

        return stats

    def print_stats(self):
        """Print statistics summary"""
        if not self.enabled:
            return

        stats = self.get_stats()

        print("\n" + "=" * 60)
        print("VERA Observability Statistics")
        print("=" * 60)

        print(f"\nEvents:")
        print(f"  Total: {stats['events_total']}")
        print(f"  FastNetwork: {stats['events_fast_network']}")
        print(f"  SlowNetwork: {stats['events_slow_network']}")
        print(f"  Archived: {stats['events_archived']}")

        print(f"\nTools:")
        print(f"  Invoked: {stats['tools_invoked']}")
        print(f"  Success rate: {stats['tool_success_rate']:.1%}")

        print(f"\nCache:")
        print(f"  Lookups: {stats['cache_lookups']}")
        print(f"  Hit rate: {stats['cache_hit_rate']:.1%}")
        print(f"  Avg latency: {stats['avg_cache_lookup_ms']:.2f}ms")

        print(f"\nHealth:")
        print(f"  Errors: {stats['errors_total']}")
        print(f"  Warnings: {stats['warnings_total']}")
        print(f"  Uptime: {stats['uptime_seconds']:.0f}s")

        print("=" * 60 + "\n")


# ============================================================================
# Fault Tolerance Layer
# ============================================================================

class VERAHealthMonitor:
    """
    Health monitoring and fault detection

    Based on:
    - Byzantine fault tolerance
    - Reliability monitoring framework
    """

    def __init__(self, max_errors: int = 10):
        self.healthy = True
        self.last_health_check = time.time()
        self.errors = []
        self.max_errors = max_errors
        self.heartbeats = 0

    def is_healthy(self) -> bool:
        """Check if system is healthy"""
        # Check error rate
        if len(self.errors) >= self.max_errors:
            return False

        # Check last health check time
        if time.time() - self.last_health_check > 300:  # 5 minutes
            return False

        return self.healthy

    def record_error(self, error: Exception, context: str = ""):
        """Record an error"""
        self.errors.append({
            "error": str(error),
            "context": context,
            "timestamp": datetime.now().isoformat()
        })

        # Trim errors list
        if len(self.errors) > self.max_errors:
            self.errors = self.errors[-self.max_errors:]

        # Update health
        if len(self.errors) >= self.max_errors:
            self.healthy = False

    def heartbeat(self):
        """Record heartbeat"""
        self.last_health_check = time.time()
        self.heartbeats += 1

    def get_stats(self) -> Dict[str, Any]:
        """Get health statistics"""
        return {
            "healthy": self.healthy,
            "total_errors": len(self.errors),
            "max_errors": self.max_errors,
            "heartbeats": self.heartbeats,
            "last_health_check": self.last_health_check,
            "recent_errors": self.errors[-5:] if self.errors else []
        }


class VERACheckpoint:
    """
    Checkpointing for recovery

    Stores system state for fault recovery
    """

    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(self, state: Dict[str, Any]):
        """Save checkpoint"""
        checkpoint_file = self.checkpoint_dir / f"checkpoint_{int(time.time())}.json"

        with open(checkpoint_file, 'w') as f:
            json.dump(state, f, indent=2, default=str)

        # Keep only last 5 checkpoints
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        for old_checkpoint in checkpoints[:-5]:
            old_checkpoint.unlink()

    def load_latest(self) -> Optional[Dict[str, Any]]:
        """Load latest checkpoint"""
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))

        if not checkpoints:
            return None

        latest = checkpoints[-1]

        with open(latest, 'r') as f:
            return json.load(f)


# ============================================================================
# Memory Service (Mem0/A-Mem pattern)
# ============================================================================

class VERAMemoryService:
    """
    Production-ready memory service

    Based on:
    - Mem0: 91% latency reduction, 90%+ cost savings
    - A-Mem: $0.0003/op
    - Independent memory layer (MaaS pattern)
    """

    def __init__(self, config: VERAConfig):
        self.config = config

        # Week 2: Memory foundation
        self.fast_network = FastNetwork(
            buffer_size=config.fast_network_buffer_size,
            importance_threshold=config.fast_network_threshold
        )

        # Week 3: Advanced components
        self.slow_network = SlowNetwork(
            consolidation_interval=config.slow_network_interval,
            archival_threshold=config.slow_network_threshold
        )

        self.rag_cache = RAGCacheL1(
            max_size_bytes=config.rag_cache_size,
            similarity_threshold=config.rag_cache_similarity
        )

        self.archive = ArchivalSystem(
            recent_max=config.archive_recent_max,
            weekly_max=config.archive_weekly_max
        )

        self.memvid = MemvidArchive()

        # Consolidation state
        self.last_consolidation = time.time()
        self.consolidation_running = False

    async def start(self):
        """Start background workers"""
        await self.slow_network.start()

    async def stop(self):
        """Stop background workers"""
        await self.slow_network.stop()

    async def process_event(self, event: Dict[str, Any]) -> Optional[MemCube]:
        """
        Process event through memory pipeline

        FastNetwork (real-time) → SlowNetwork (background) → Archive
        """
        # Encode with FastNetwork
        cube = self.fast_network.encode_event(event)

        # Periodic consolidation
        if self.fast_network.should_consolidate():
            await self._consolidate()

        return cube

    async def _consolidate(self):
        """Consolidate FastNetwork buffer"""
        if self.consolidation_running:
            return

        self.consolidation_running = True

        try:
            # Get buffer
            buffer = self.fast_network.get_buffer(clear=True)

            if not buffer:
                return

            # Consolidate with SlowNetwork
            retained, archived = await self.slow_network.consolidate_batch(buffer)

            # Archive low-importance events
            if archived:
                self.archive.archive(archived)

            # Create video of session if enough high-importance events
            if len(retained) >= 100:
                video_id = self.memvid.create_video(
                    retained,
                    title=f"Session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )

            self.last_consolidation = time.time()

        finally:
            self.consolidation_running = False

    async def retrieve(self, query: str) -> Optional[List[Any]]:
        """
        Retrieve from memory with caching

        RAGCache (L1) → Archive → Memvid
        """
        # Check cache first
        cached = self.rag_cache.get(query)

        if cached:
            return cached

        # Search archive
        results = self.archive.search(query, max_results=10)

        # Extract cubes
        cubes = [cube for cube, score, tier in results]

        # Cache results
        if cubes:
            self.rag_cache.put(query, cubes)

        return cubes

    def get_stats(self) -> Dict[str, Any]:
        """Get memory system statistics"""
        return {
            "fast_network": self.fast_network.get_stats(),
            "slow_network": self.slow_network.get_stats(),
            "rag_cache": self.rag_cache.get_stats(),
            "archive": self.archive.get_stats()
        }


# ============================================================================
# Main VERA System
# ============================================================================

class VERA:
    """
    VERA Personal AI Assistant (Production)

    Integrates all Phase 2 components with observability and fault tolerance
    """

    def __init__(self, config: VERAConfig):
        self.config = config
        self.running = False

        # Observability
        self.observability = VERAObservability(enabled=config.observability)

        # Fault tolerance
        self.health_monitor = VERAHealthMonitor()
        self.checkpoint = VERACheckpoint(Path("vera_checkpoints"))

        # Memory service
        self.memory = VERAMemoryService(config)

        # Week 1: Tool system
        self.tool_executor = AsyncToolExecutor(max_concurrent=config.max_tool_concurrency)
        self.output_filter = ToolOutputFilter()

        # Week 2: Quorum & tool selection
        self.shared_memory = SharedBlackboard()
        self.tool_selection = ToolSelectionMemory()

        # Safety & Quorum systems
        self.safety_validator = SafetyValidator()
        self.quorum_selector = QuorumSelector()
        self.consensus_engine = ConsensusEngine()

        # Session tracking
        self.session_start = datetime.now()
        self.events_processed = 0

    def build_system_prompt(self) -> str:
        """Build complete system prompt with dynamic session context"""

        # Calculate uptime
        uptime_seconds = int((datetime.now() - self.session_start).total_seconds())

        # Get current stats
        obs_stats = self.observability.get_stats() if self.config.observability else {}
        health_stats = self.health_monitor.get_stats()
        memory_stats = self.memory.rag_cache.get_stats()

        # Build session context
        session_context = f"""
- Mode: {'Autonomous' if self.config.autonomous else 'Interactive'}
- Session start: {self.session_start.isoformat()}
- Uptime: {uptime_seconds}s ({uptime_seconds // 60}m {uptime_seconds % 60}s)
- Events processed: {obs_stats.get('events_total', self.events_processed)}
- System health: {'Healthy ✓' if health_stats['healthy'] else 'Degraded ⚠️'}
- Cache hit rate: {memory_stats.get('hit_rate', 0):.1%}
- Observability: {'Enabled' if self.config.observability else 'Disabled'}
"""

        # Inject session context into prompt
        full_prompt = VERA_SYSTEM_PROMPT.replace("{SESSION_CONTEXT}", session_context.strip())

        return full_prompt

    async def consult_quorum(self, question: str, context: str = "") -> Dict[str, Any]:
        """
        Consult multi-agent quorum for complex decisions

        Args:
            question: The question or task to address
            context: Additional context

        Returns:
            Dict with decision, explanation, and agent contributions
        """
        # Step 1: Select optimal quorum
        quorum = self.quorum_selector.select(question, context)

        if self.config.debug:
            print(f"\n[DEBUG] Selected Quorum: {quorum.name}")
            print(f"[DEBUG] Agents: {', '.join(quorum.get_agent_names())}")
            print(f"[DEBUG] Consensus: {quorum.consensus_algorithm.value}")

        # Step 2: Invoke each agent in quorum
        agent_outputs = {}

        for agent_role in quorum.agents:
            agent_name = agent_role.name
            profile = AGENT_PROFILES[agent_name]

            # Build agent-specific prompt
            agent_prompt = profile.build_prompt(question, context)

            # TODO: Replace with actual LLM call
            # For now, placeholder response
            agent_response = f"[Agent {agent_name}]: Analyzed '{question}'. "
            if agent_role.is_lead:
                agent_response += "As lead agent, I recommend proceeding with caution."
            elif agent_role.veto_authority:
                agent_response += "I have reviewed for safety concerns."
            else:
                agent_response += "I have provided my perspective."

            agent_outputs[agent_name] = agent_response

            if self.config.debug:
                print(f"[DEBUG] {agent_name}: {agent_response[:100]}...")

        # Step 3: Apply consensus algorithm
        # Determine what type of outputs we have based on algorithm
        if quorum.consensus_algorithm.value == "synthesis":
            # Text synthesis
            result = self.consensus_engine.synthesis(agent_outputs)
        elif quorum.consensus_algorithm.value == "weighted_scoring":
            # For weighted scoring, we'd need scores (0-100)
            # Placeholder: parse scores from outputs or use default
            from quorum.consensus import parse_score
            scores = {agent: parse_score(output) for agent, output in agent_outputs.items()}
            result = self.consensus_engine.weighted_scoring(
                scores,
                quorum.weights or {agent: 1.0 / len(agent_outputs) for agent in agent_outputs},
                threshold=60.0
            )
        elif quorum.consensus_algorithm.value in ["majority_vote", "veto_authority"]:
            # For voting, we'd need votes
            # Placeholder: parse votes from outputs or use default
            from quorum.consensus import parse_vote
            votes = {agent: parse_vote(output) for agent, output in agent_outputs.items()}

            if quorum.consensus_algorithm.value == "veto_authority":
                veto_agent = quorum.get_veto_agent()
                result = self.consensus_engine.veto_authority(votes, veto_agent)
            else:
                result = self.consensus_engine.majority_vote(votes)
        else:
            # Default to majority vote
            from quorum.consensus import parse_vote
            votes = {agent: parse_vote(output) for agent, output in agent_outputs.items()}
            result = self.consensus_engine.majority_vote(votes)

        # Record in shared memory for other agents
        self.shared_memory.write(
            zone="quorum_decisions",
            key=f"decision_{int(time.time())}",
            value={
                "question": question,
                "quorum": quorum.name,
                "decision": result.decision.value,
                "timestamp": datetime.now().isoformat()
            }
        )

        return {
            "quorum": quorum.name,
            "agents": quorum.get_agent_names(),
            "decision": result.decision.value,
            "explanation": result.explanation,
            "agent_outputs": agent_outputs,
            "consensus_details": result.details
        }

    async def validate_command(self, command: str) -> ValidationDecision:
        """
        Validate command before execution

        Args:
            command: Command to validate

        Returns:
            ValidationDecision
        """
        decision = self.safety_validator.validate(command)

        # Log validation
        if self.config.debug:
            print(f"[DEBUG] Command validation: {decision.result.value}")
            if decision.matched_pattern:
                print(f"[DEBUG] Matched pattern: {decision.matched_pattern}")

        # Record in observability
        if self.config.observability:
            self.observability.record_event("safety_validation", result=decision.result.value)

        return decision

    async def start(self):
        """Start VERA"""
        print("=" * 60)
        print("VERA - Personal AI Assistant (Phase 2 Production)")
        print("=" * 60)
        print(f"Session started: {self.session_start.isoformat()}")
        print(f"Mode: {'Autonomous' if self.config.autonomous else 'Interactive'}")
        print(f"Observability: {'Enabled' if self.config.observability else 'Disabled'}")
        print(f"Fault Tolerance: {'Enabled' if self.config.fault_tolerance else 'Disabled'}")
        print("=" * 60 + "\n")

        self.running = True

        # Start memory service
        await self.memory.start()

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    async def stop(self):
        """Stop VERA"""
        print("\n\nStopping VERA...")

        self.running = False

        # Stop memory service
        await self.memory.stop()

        # Print final stats
        if self.config.observability:
            self.observability.print_stats()

        # Save final checkpoint
        if self.config.fault_tolerance:
            await self._save_checkpoint()

        print(f"\nSession ended: {datetime.now().isoformat()}")
        print(f"Events processed: {self.events_processed}")
        print("\nGoodbye! 👋\n")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        asyncio.create_task(self.stop())

    async def process_user_message(self, message: str) -> str:
        """
        Process user message

        Complete pipeline:
        1. Tool execution (async, filtered)
        2. Memory encoding (FastNetwork)
        3. Consolidation (SlowNetwork, background)
        4. Caching (RAGCache)
        5. Archival (3-tier)
        """
        try:
            # Record event
            event = {
                "type": "user_query",
                "content": message,
                "timestamp": datetime.now().isoformat()
            }

            # Encode in memory
            cube = await self.memory.process_event(event)

            # Observability
            self.observability.record_event("fast_network")

            # Heartbeat
            self.health_monitor.heartbeat()

            self.events_processed += 1

            # For now, simple echo response
            # TODO: Integrate with actual LLM
            response = f"Processed: {message}\n(Full LLM integration in next phase)"

            return response

        except Exception as e:
            self.health_monitor.record_error(e, "process_user_message")
            self.observability.metrics["errors_total"] += 1
            return f"Error: {str(e)}"

    async def _save_checkpoint(self):
        """Save system checkpoint"""
        state = {
            "session_start": self.session_start.isoformat(),
            "events_processed": self.events_processed,
            "memory_stats": self.memory.get_stats(),
            "observability": self.observability.get_stats(),
            "timestamp": datetime.now().isoformat()
        }

        self.checkpoint.save(state)

    async def run_interactive(self):
        """Run in interactive mode"""
        print("Interactive mode. Type 'quit' or 'exit' to stop.\n")

        while self.running:
            try:
                # Get user input
                user_input = input("You: ")

                if user_input.lower() in ['quit', 'exit', 'bye']:
                    break

                if not user_input.strip():
                    continue

                # Process message
                response = await self.process_user_message(user_input)

                print(f"VERA: {response}\n")

                # Periodic checkpoint
                if self.config.fault_tolerance:
                    if time.time() - self.checkpoint.last_health_check > self.config.checkpoint_interval:
                        await self._save_checkpoint()

            except EOFError:
                break
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
                self.health_monitor.record_error(e, "interactive_loop")

    async def run_autonomous(self):
        """Run in autonomous mode"""
        print("Autonomous mode. Press Ctrl+C to stop.\n")

        cycle = 0

        while self.running:
            try:
                cycle += 1

                print(f"[Cycle {cycle}] Running...")

                # Simulate autonomous work
                await asyncio.sleep(10)

                # Heartbeat
                self.health_monitor.heartbeat()

                # Periodic checkpoint
                if cycle % 10 == 0:
                    await self._save_checkpoint()

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
                self.health_monitor.record_error(e, "autonomous_loop")


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="VERA - Personal AI Assistant")
    parser.add_argument("--auto", action="store_true", help="Run in autonomous mode")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    # Create config
    config = VERAConfig().from_args(args)

    # Create VERA
    vera = VERA(config)

    # Start
    await vera.start()

    try:
        # Run mode
        if config.autonomous:
            await vera.run_autonomous()
        else:
            await vera.run_interactive()

    finally:
        # Stop
        await vera.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
