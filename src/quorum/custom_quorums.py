#!/usr/bin/env python3
"""
Custom Quorums - VERA Quorum System
===================================

Persistence layer for user-defined quorums.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.persistence.atomic_io import atomic_json_write, safe_json_read
from .premade_quorums import Quorum, AgentRole, PREMADE_QUORUMS
from .consensus import ConsensusAlgorithm
from .agent_profiles import AGENT_PROFILES


CUSTOM_QUORUM_PATH = Path("vera_memory/custom_quorums.json")


def _normalize_name(name: str) -> str:
    return (name or "").strip()


def _normalize_consensus(value: str) -> ConsensusAlgorithm:
    normalized = (value or "").strip().lower()
    mapping = {
        "majority": "majority_vote",
        "majority_vote": "majority_vote",
        "weighted": "weighted_scoring",
        "weighted_scoring": "weighted_scoring",
        "synthesis": "synthesis",
        "veto": "veto_authority",
        "veto_authority": "veto_authority",
    }
    algo = mapping.get(normalized)
    if not algo:
        raise ValueError(f"Unsupported consensus algorithm: {value}")
    return ConsensusAlgorithm(algo)


def _load_raw() -> Dict[str, Any]:
    data = safe_json_read(CUSTOM_QUORUM_PATH, default={})
    if not isinstance(data, dict):
        return {"quorums": []}
    quorums = data.get("quorums", [])
    if not isinstance(quorums, list):
        quorums = []
    return {"quorums": quorums}


def list_custom_quorum_specs() -> List[Dict[str, Any]]:
    data = _load_raw()
    return list(data.get("quorums", []))


def get_custom_quorum_spec(name: str) -> Optional[Dict[str, Any]]:
    target = _normalize_name(name)
    if not target:
        return None
    for spec in list_custom_quorum_specs():
        if _normalize_name(spec.get("name")) == target:
            return spec
    return None


def _build_agent_roles(agent_specs: List[Dict[str, Any]]) -> List[AgentRole]:
    roles = []
    for spec in agent_specs:
        name = _normalize_name(spec.get("name", ""))
        if not name:
            continue
        roles.append(AgentRole(
            name=name,
            weight=float(spec.get("weight", 1.0)),
            veto_authority=bool(spec.get("veto_authority", False)),
            is_lead=bool(spec.get("is_lead", False)),
        ))
    return roles


def _resolve_tool_access(agent_names: List[str]) -> List[str]:
    tool_access = set()
    for name in agent_names:
        profile = AGENT_PROFILES.get(name)
        if profile:
            tool_access.update(profile.tool_access)
    if not tool_access:
        tool_access.update(["vera_memory", "file_operations"])
    return sorted(tool_access)


def build_quorum_from_spec(spec: Dict[str, Any]) -> Quorum:
    name = _normalize_name(spec.get("name", ""))
    if not name:
        raise ValueError("Custom quorum is missing a name.")

    purpose = (spec.get("purpose") or "").strip() or "Custom quorum"
    description = (spec.get("description") or "").strip()
    consensus = _normalize_consensus(spec.get("consensus", "majority_vote"))

    raw_agents = spec.get("agents", [])
    if not isinstance(raw_agents, list):
        raise ValueError("Agents must be a list.")
    if not raw_agents:
        raise ValueError("Custom quorum requires at least one agent.")

    agent_specs: List[Dict[str, Any]] = []
    for entry in raw_agents:
        if isinstance(entry, str):
            agent_specs.append({"name": entry})
        elif isinstance(entry, dict):
            agent_specs.append(entry)
        else:
            raise ValueError("Invalid agent entry in custom quorum.")

    agent_names = [_normalize_name(item.get("name", "")) for item in agent_specs if _normalize_name(item.get("name", ""))]
    invalid_agents = [name for name in agent_names if name not in AGENT_PROFILES]
    if invalid_agents:
        raise ValueError(f"Unknown agents: {', '.join(invalid_agents)}")

    agents = _build_agent_roles(agent_specs)
    tool_access = spec.get("tool_access")
    if not isinstance(tool_access, list) or not tool_access:
        tool_access = _resolve_tool_access([role.name for role in agents])

    return Quorum(
        name=name,
        purpose=purpose,
        agents=agents,
        tool_access=tool_access,
        consensus_algorithm=consensus,
        triggers=[],
        description=description,
        weights=spec.get("weights"),
    )


def get_custom_quorum(name: str) -> Optional[Quorum]:
    spec = get_custom_quorum_spec(name)
    if not spec:
        return None
    return build_quorum_from_spec(spec)


def save_custom_quorum_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    quorum = build_quorum_from_spec(spec)
    name = quorum.name

    if name in PREMADE_QUORUMS:
        raise ValueError(f"{name} is reserved for a built-in quorum.")

    agent_specs = []
    for agent in quorum.agents:
        agent_specs.append({
            "name": agent.name,
            "weight": agent.weight,
            "veto_authority": agent.veto_authority,
            "is_lead": agent.is_lead,
        })

    stored = {
        "name": quorum.name,
        "purpose": quorum.purpose,
        "description": quorum.description or "",
        "consensus": quorum.consensus_algorithm.value,
        "agents": agent_specs,
        "tool_access": quorum.tool_access,
        "weights": quorum.weights,
        "is_swarm": bool(spec.get("is_swarm", False)),
        "source": "custom",
    }

    data = _load_raw()
    quorums = data.get("quorums", [])
    updated = False
    for idx, existing in enumerate(quorums):
        if _normalize_name(existing.get("name")) == name:
            quorums[idx] = stored
            updated = True
            break
    if not updated:
        quorums.append(stored)

    CUSTOM_QUORUM_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(CUSTOM_QUORUM_PATH, {"quorums": quorums}, indent=2)
    return stored


def delete_custom_quorum(name: str) -> bool:
    target = _normalize_name(name)
    if not target:
        return False
    data = _load_raw()
    quorums = data.get("quorums", [])
    new_quorums = [spec for spec in quorums if _normalize_name(spec.get("name")) != target]
    if len(new_quorums) == len(quorums):
        return False
    CUSTOM_QUORUM_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(CUSTOM_QUORUM_PATH, {"quorums": new_quorums}, indent=2)
    return True
