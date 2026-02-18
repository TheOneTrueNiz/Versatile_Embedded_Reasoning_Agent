"""
Voice Manager
=============

Encapsulates voice session lifecycle.
"""

from __future__ import annotations

import logging
from typing import Any

from voice import VoiceAgent, Voice, VoiceToolBridge

logger = logging.getLogger(__name__)


class VoiceManager:
    """Voice session support extracted from VERA."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner, name)

    async def start_voice_session(self, voice_name: str = "ara") -> str:
        """Start a voice session using the Grok Voice Agent."""
        if self._voice_agent and self._voice_agent.is_active:
            return "Voice session already active."

        voice_key = voice_name.lower()
        try:
            voice = Voice(voice_key)
        except ValueError:
            valid = ", ".join(v.value for v in Voice)
            return f"Unknown voice '{voice_name}'. Available: {valid}"

        agent = VoiceAgent(voice=voice)
        bridge = VoiceToolBridge(self._owner)

        def _build_handler(tool: str):
            async def handler(**kwargs):
                return await bridge.execute_tool(tool, kwargs)
            return handler

        for tool_def in bridge.tools:
            func = tool_def.get("function", {})
            name = func.get("name", "")
            if not name:
                continue
            agent.register_tool(
                name=name,
                description=func.get("description", ""),
                parameters=func.get("parameters", {"type": "object", "properties": {}}),
                handler=_build_handler(name),
            )

        agent.on_transcript(self.handle_voice_transcript)

        try:
            session_id = await agent.start_conversation()
        except Exception as exc:
            logger.error("Voice session failed: %s", exc)
            return f"Voice session failed: {exc}"

        self._voice_agent = agent
        self._voice_bridge = bridge

        return f"Voice session started: {session_id} (voice={voice.value})"

    async def stop_voice_session(self) -> str:
        """Stop the active voice session."""
        if not self._voice_agent or not self._voice_agent.is_active:
            return "No active voice session."

        await self._voice_agent.end_conversation()
        self._voice_agent = None
        self._voice_bridge = None
        return "Voice session ended."

    def voice_status(self) -> str:
        """Return a concise voice status line."""
        if not self._voice_agent:
            return "Voice session: inactive"

        stats = self._voice_agent.get_stats()
        voice = stats.get("voice", "unknown")
        state = stats.get("state", "unknown")
        backend = stats.get("audio_backend", "unknown")
        convo = stats.get("conversation", {})
        convo_id = convo.get("id", "n/a")
        return f"Voice session: {state} (voice={voice}, backend={backend}, id={convo_id})"

    def handle_voice_transcript(self, role: str, text: str) -> None:
        """Print voice transcripts to the console."""
        print(f"[Voice {role}] {text}")

    async def shutdown(self) -> None:
        """End any active voice session."""
        if self._voice_agent and self._voice_agent.is_active:
            await self._voice_agent.end_conversation()
            self._voice_agent = None
            self._voice_bridge = None
