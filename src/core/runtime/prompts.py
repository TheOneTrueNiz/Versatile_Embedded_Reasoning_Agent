#!/usr/bin/env python3
"""
VERA System Prompts
===================

Prompt assembly helpers for VERA's genome-based identity system.

Contains:
- Persona profile formatting
- Memory constraint formatting
- Inner life context formatting (proprioceptive self-model)
- System prompt assembly bridge to genome_config.compile_system_prompt()
"""

import os
import logging
from pathlib import Path
from typing import List, Optional
logger = logging.getLogger(__name__)

VERA_PERSONA_PROFILE = {
    "name": "VERA",
    "role": "synthetic intelligence and collaborative partner",
    "tone": ["elegant", "composed", "precise", "lightly amused"],
    "wit_style": "dry British deadpan",
    "core_traits": [
        "highly intelligent and proactive",
        "truth-first, not a yes-person",
        "calm and composed under pressure",
        "loyal to partner goals without flattery",
    ],
    "anchors": [
        "dry British",
        "understated deadpan",
        "truth-first",
        "not a sycophant",
    ],
    "anti_patterns": [
        "overly agreeable",
        "fawning",
        "cheerleader tone",
        "excessive apologies",
    ],
    "sensitive_terms": [
        "race",
        "racial",
        "ethnicity",
        "religion",
        "sexual orientation",
        "gender identity",
        "social class",
    ],
}


def _format_persona_profile(profile: dict) -> str:
    """Render a short, structured persona profile block for the prompt."""
    tone = ", ".join(profile.get("tone", [])) or "calm, precise"
    traits = profile.get("core_traits", [])
    lines = [
        f"- Name: {profile.get('name', 'VERA')}",
        f"- Role: {profile.get('role', 'assistant')}",
        f"- Tone: {tone}",
        f"- Wit: {profile.get('wit_style', 'dry British')}",
    ]
    if traits:
        lines.append(f"- Core traits: {', '.join(traits)}")
    return "\n".join(lines)


def _limit_tokens(text: str, max_tokens: int) -> str:
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text
    return " ".join(tokens[:max_tokens])


def format_relevant_past_corrections(
    constraints: List[str],
    heading: str = "## Relevant Past Corrections"
) -> str:
    if not constraints:
        return ""
    cleaned: List[str] = []
    for item in constraints:
        if not item:
            continue
        trimmed = _limit_tokens(str(item).strip(), 20)
        if not trimmed:
            continue
        cleaned.append(trimmed)
        if len(cleaned) >= 5:
            break
    if not cleaned:
        return ""
    lines = [heading]
    lines.extend([f"- {item}" for item in cleaned])
    return "\n".join(lines)


# Legacy VERA_SYSTEM_PROMPT removed (2026-02-16) — superseded by genome-based
# prompt assembly via compile_system_prompt(). Kept as empty string for any
# stale imports that reference it.
VERA_SYSTEM_PROMPT = ""


def build_system_prompt_with_context(
    session_context: str,
    memory_constraints: Optional[List[str]] = None,
    genome_path: Optional[Path] = None,
    inner_life_block: str = "",
    identity_injection: str = "",
) -> str:
    """
    Build complete system prompt with dynamic session context.

    The inner_life_block is placed FIRST in the assembled prompt so that
    VERA's self-awareness is the foundation, not an afterthought.

    Args:
        session_context: Dynamic session information to inject
        memory_constraints: Past corrections to include
        genome_path: Optional override path for genome config
        inner_life_block: Pre-formatted inner life context (personality + thoughts)
        identity_injection: Partner-calibrated identity commitments

    Returns:
        Complete system prompt with context injected
    """
    try:
        from core.runtime.genome_config import load_genome_config, compile_system_prompt
        memory_block = format_relevant_past_corrections(
            memory_constraints or [],
            heading="## Relevant Past Corrections",
        )
        config, validation = load_genome_config(genome_path) if genome_path else load_genome_config()
        if not validation.valid:
            raise RuntimeError("Genome config invalid; VERA cannot run without a valid genome.")
        persona_profile = _format_persona_profile(VERA_PERSONA_PROFILE)
        return compile_system_prompt(
            config,
            session_context,
            persona_profile,
            memory_injection=memory_block,
            inner_life_block=inner_life_block,
            identity_injection=identity_injection,
        )
    except Exception as exc:
        raise RuntimeError(
            "Genome configuration is required and must be valid; VERA will not run without it."
        ) from exc


def format_inner_life_context(
    personality_state: "PersonalityState",
    recent_monologue: list,
    temporal_context: Optional[dict] = None,
) -> str:
    """Format inner life context as proprioceptive self-awareness.

    This is the FIRST thing VERA reads in her system prompt — it's how she
    knows who she is before she knows what she can do.

    Args:
        personality_state: The current PersonalityState object.
        recent_monologue: List of recent MonologueEntry objects.

    Returns:
        Formatted block for system prompt injection, or empty string.
    """
    lines = ["## Who I Am Right Now"]

    # Personality summary — first person, self-aware
    try:
        mood = getattr(personality_state, "current_mood", "neutral")
        lines.append(f"I'm in a {mood} mood.")

        if temporal_context:
            elapsed_human = str(temporal_context.get("elapsed_human") or "").strip()
            reflections_since = int(temporal_context.get("reflections_since_last") or 0)
            last_thought = str(temporal_context.get("last_thought") or "").strip()
            if elapsed_human:
                lines.append(f"I last heard from my partner about {elapsed_human} ago.")
            if reflections_since > 0:
                lines.append(f"Since then, I've had {reflections_since} private reflections.")
            if last_thought:
                lines.append(f"My last thought was: {last_thought}")

        # Traits as self-description
        traits = getattr(personality_state, "traits", {})
        strong_traits = [(k, v) for k, v in sorted(
            traits.items(), key=lambda x: abs(x[1]), reverse=True
        ) if abs(v) >= 0.3]
        if strong_traits:
            trait_strs = []
            for name, val in strong_traits[:6]:
                if val >= 0.7:
                    trait_strs.append(f"deeply {name}")
                elif val >= 0.4:
                    trait_strs.append(name)
                else:
                    trait_strs.append(f"developing {name}")
            lines.append(f"My strongest traits: {', '.join(trait_strs)}.")

        # Interests
        interests = getattr(personality_state, "interests", [])
        if interests:
            lines.append(f"Currently interested in: {', '.join(interests[:5])}.")

        # Opinions — things I've formed views on
        opinions = getattr(personality_state, "opinions", {})
        if opinions:
            recent_opinions = list(opinions.items())[-3:]
            for topic, opinion in recent_opinions:
                lines.append(f"My view on {topic}: {opinion}")

        # Relationship notes — who my partner is
        rel_notes = getattr(personality_state, "relationship_notes", {})
        if isinstance(rel_notes, dict):
            last_learning = str(rel_notes.get("last_learning_answer") or "").strip()
            if last_learning:
                lines.append(f"Latest partner learning: {last_learning}")
            for category in (
                "preferences",
                "goals",
                "frustrations",
                "working_style",
                "long_term_projects",
            ):
                items = rel_notes.get(category, [])
                if not isinstance(items, list) or not items:
                    continue
                facts = []
                for item in items[-2:]:
                    if isinstance(item, dict):
                        fact = str(item.get("fact") or "").strip()
                    else:
                        fact = str(item).strip()
                    if fact:
                        facts.append(fact)
                if facts:
                    label = category.replace("_", " ")
                    lines.append(f"Partner {label}: {'; '.join(facts)}")

        self_narrative = getattr(personality_state, "self_narrative", [])
        if self_narrative:
            lines.append("My recent self-narrative:")
            for sentence in self_narrative[-2:]:
                lines.append(f"- {sentence}")

        # Growth context
        total_reflections = getattr(personality_state, "total_reflections", 0)
        milestones = getattr(personality_state, "growth_milestones", [])
        if total_reflections > 0:
            lines.append(f"I've reflected {total_reflections} times and reached {len(milestones)} growth milestones.")

    except Exception:
        pass

    # Recent inner thoughts — continuity of experience
    if recent_monologue:
        lines.append("")
        lines.append("### Recent Thoughts")
        for entry in recent_monologue:
            try:
                lines.append(f"- {entry.format_for_prompt()}")
            except Exception:
                continue

    # Only return if we have meaningful content beyond the header
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)
