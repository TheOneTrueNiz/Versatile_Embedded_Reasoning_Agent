"""
VERA Quorum System
==================

Multi-agent decision-making system with premade quorums optimized for task types.

Components:
- agent_profiles: Defines 7 specialized agents with capabilities
- consensus: Implements 5 consensus algorithms
- premade_quorums: Defines 7 task-optimized quorums
- quorum_selector: Maps tasks to optimal quorums
- moa_executor: Mixture-of-Agents LLM executor (Improvement #20)

Usage:
    from quorum import QuorumSelector, MoAExecutor, execute_quorum

    selector = QuorumSelector()
    quorum = selector.select(task)

    # Execute with real LLM agents (Improvement #20)
    result = await execute_quorum(quorum, task, context)
"""

from .agent_profiles import AgentProfile, AGENT_PROFILES
from .consensus import ConsensusEngine, ConsensusAlgorithm, Vote, Decision, ConsensusResult
from .premade_quorums import Quorum, AgentRole, PREMADE_QUORUMS
from .quorum_selector import QuorumSelector, TaskFeatures

# Improvement #20: Mixture-of-Agents executor
from .moa_executor import (
    MoAExecutor,
    MoAResult,
    AgentResponse,
    execute_quorum,
    execute_quorum_sync,
    AGENT_PERSONAS,
)

__all__ = [
    'AgentProfile',
    'AGENT_PROFILES',
    'ConsensusEngine',
    'ConsensusAlgorithm',
    'ConsensusResult',
    'Vote',
    'Decision',
    'Quorum',
    'AgentRole',
    'PREMADE_QUORUMS',
    'QuorumSelector',
    'TaskFeatures',
    # MoA Executor (Improvement #20)
    'MoAExecutor',
    'MoAResult',
    'AgentResponse',
    'execute_quorum',
    'execute_quorum_sync',
    'AGENT_PERSONAS',
]
