"""
Voice Integration Module for VERA.

Provides real-time speech-to-speech conversation using xAI Grok Voice Agent API.
"""

from .session import (
    VoiceSessionManager,
    SessionConfig,
    SessionStats,
    SessionState,
    AudioFormat,
    Voice,
    TurnDetectionMode,
    chunk_audio,
    resample_audio,
    COST_PER_MINUTE
)

from .agent import (
    VoiceAgent,
    AudioBackend,
    ConversationState,
    ConversationTurn,
    Conversation,
    create_voice_agent,
    get_available_backend
)

from .tools import (
    VoiceToolBridge,
    VoiceToolDef,
    VERA_VOICE_TOOLS,
    create_tool_bridge
)

__all__ = [
    # Session
    "VoiceSessionManager",
    "SessionConfig",
    "SessionStats",
    "SessionState",
    "AudioFormat",
    "Voice",
    "TurnDetectionMode",
    "chunk_audio",
    "resample_audio",
    "COST_PER_MINUTE",

    # Agent
    "VoiceAgent",
    "AudioBackend",
    "ConversationState",
    "ConversationTurn",
    "Conversation",
    "create_voice_agent",
    "get_available_backend",

    # Tools
    "VoiceToolBridge",
    "VoiceToolDef",
    "VERA_VOICE_TOOLS",
    "create_tool_bridge",
]

__version__ = "1.0.0"
