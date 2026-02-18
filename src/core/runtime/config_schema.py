"""
VERA 2.0 Configuration Schema
===============================

Pydantic v2 models for structured, validated configuration.
Replaces the flat env-var-only VERAConfig with hierarchical
config that loads from the genome runtime (canonical), with
optional YAML fallback and env-var overrides.

Backward compatible: old VERAConfig still works via from_v2().
"""

from typing import Any, Dict, List, Optional
try:
    from pydantic import BaseModel, Field
    PYDANTIC_AVAILABLE = True
except ImportError:
    # Fallback: use dataclasses if pydantic not available
    from dataclasses import field as dc_field
    PYDANTIC_AVAILABLE = False


if PYDANTIC_AVAILABLE:

    class ProviderConfig(BaseModel):
        """Configuration for a single LLM provider."""
        provider_id: str
        model: str = ""
        base_url: Optional[str] = None
        api_key_env: Optional[str] = None  # Env var name for API key
        timeout: float = 60.0
        extra: Dict[str, Any] = Field(default_factory=dict)

    class LLMConfig(BaseModel):
        """LLM provider and fallback chain configuration."""
        fallback_chain: List[str] = Field(
            default=["grok", "claude", "gemini", "openai"]
        )
        providers: Dict[str, ProviderConfig] = Field(default_factory=dict)
        max_tool_rounds: int = 5
        timeout: float = 60.0
        max_retries_per_provider: int = 2
        cooldown_seconds: float = 60.0

    class DiscordConfig(BaseModel):
        """Discord channel configuration."""
        enabled: bool = False
        token: Optional[str] = None
        token_env: str = "DISCORD_BOT_TOKEN"
        allowed_guilds: List[str] = Field(default_factory=list)
        allowed_users: List[str] = Field(default_factory=list)
        command_prefix: str = "!"

    class ChannelsConfig(BaseModel):
        """Configuration for all messaging channels."""
        discord: DiscordConfig = Field(default_factory=DiscordConfig)
        # Future: telegram, slack, etc.

    class HooksConfig(BaseModel):
        """Hook system configuration."""
        enabled: bool = True

    class SessionsConfig(BaseModel):
        """Session management configuration."""
        scope: str = "per_sender"  # per_sender | global | per_channel
        transcript_dir: str = "vera_memory/transcripts"
        ttl_seconds: int = 3600
        max_history_messages: int = 50

    class MemoryConfig(BaseModel):
        """Memory system configuration."""
        fast_buffer_size: int = 100
        fast_threshold: float = 0.4
        slow_interval: float = 60.0
        slow_threshold: float = 0.3
        retention_threshold: float = 0.5
        retention_staleness_hours: float = 48.0
        memvid_promotion_min: int = 20
        rag_cache_mb: int = 100
        rag_similarity: float = 0.7
        archive_recent_max: int = 1000
        archive_weekly_max: int = 5000

    class SafetyConfig(BaseModel):
        """Safety system configuration."""
        fault_tolerance: bool = True
        checkpoint_interval: int = 300
        max_tool_concurrency: int = 10

    class VERAConfigV2(BaseModel):
        """Full VERA 2.0 configuration with Pydantic validation.

        Hierarchical structure that replaces flat env vars with
        organized sections while maintaining backward compatibility.
        """
        # Core modes
        debug: bool = False
        dry_run: bool = False
        observability: bool = False
        interactive: bool = True
        autonomous: bool = False

        # Subsystem configs
        llm: LLMConfig = Field(default_factory=LLMConfig)
        channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
        hooks: HooksConfig = Field(default_factory=HooksConfig)
        sessions: SessionsConfig = Field(default_factory=SessionsConfig)
        memory: MemoryConfig = Field(default_factory=MemoryConfig)
        safety: SafetyConfig = Field(default_factory=SafetyConfig)

        def to_legacy_config(self) -> "VERAConfigLegacy":
            """Convert to legacy VERAConfig format for backward compatibility."""
            from core.runtime.config import VERAConfig
            legacy = VERAConfig.__new__(VERAConfig)
            legacy.interactive = self.interactive
            legacy.autonomous = self.autonomous
            legacy.debug = self.debug
            legacy.dry_run = self.dry_run
            legacy.observability = self.observability
            legacy.fast_network_buffer_size = self.memory.fast_buffer_size
            legacy.fast_network_threshold = self.memory.fast_threshold
            legacy.slow_network_interval = self.memory.slow_interval
            legacy.slow_network_threshold = self.memory.slow_threshold
            legacy.slow_network_retention_threshold = self.memory.retention_threshold
            legacy.retention_staleness_hours = self.memory.retention_staleness_hours
            legacy.memvid_promotion_min = self.memory.memvid_promotion_min
            legacy.rag_cache_size = self.memory.rag_cache_mb * 1024 * 1024
            legacy.rag_cache_similarity = self.memory.rag_similarity
            legacy.archive_recent_max = self.memory.archive_recent_max
            legacy.archive_weekly_max = self.memory.archive_weekly_max
            legacy.fault_tolerance = self.safety.fault_tolerance
            legacy.checkpoint_interval = self.safety.checkpoint_interval
            legacy.max_tool_concurrency = self.safety.max_tool_concurrency
            return legacy

else:
    # Minimal fallback without Pydantic
    class VERAConfigV2:  # type: ignore
        """Fallback config without Pydantic validation."""
        def __init__(self, **kwargs) -> None:
            self.debug = kwargs.get("debug", False)
            self.dry_run = kwargs.get("dry_run", False)
            self.observability = kwargs.get("observability", False)
            self.interactive = kwargs.get("interactive", True)
            self.autonomous = kwargs.get("autonomous", False)
