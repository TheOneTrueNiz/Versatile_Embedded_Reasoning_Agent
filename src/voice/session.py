"""
Voice Session Manager for VERA.

Handles WebSocket connections to xAI Grok Voice Agent API.
Provides real-time bidirectional audio streaming with <1s latency.

Compatible with OpenAI Realtime API specification.
"""

import os
import json
import asyncio
import base64
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from enum import Enum
import uuid

try:
    from websockets.asyncio.client import connect, ClientConnection
    from websockets.exceptions import ConnectionClosed
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    ClientConnection = Any
    ConnectionClosed = Exception

logger = logging.getLogger(__name__)


# === Constants ===

XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"
VOICE_MODEL = os.getenv("XAI_VOICE_MODEL", "grok-voice-agent")
XAI_TOKEN_URL = "https://api.x.ai/v1/realtime/client_secrets"

# Pricing: $0.05 per minute of connection time
COST_PER_MINUTE = 0.05


class SessionState(Enum):
    """Voice session connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ACTIVE = "active"  # Audio streaming
    ERROR = "error"


class AudioFormat(Enum):
    """Supported audio formats."""
    PCM_16K = "audio/pcm;rate=16000"
    PCM_24K = "audio/pcm;rate=24000"
    PCM_44K = "audio/pcm;rate=44100"
    PCM_48K = "audio/pcm;rate=48000"
    G711_ULAW = "audio/pcmu"
    G711_ALAW = "audio/pcma"


class Voice(Enum):
    """Available xAI voices."""
    ARA = "ara"      # Expressive female voice
    REX = "rex"      # Confident male voice
    SAL = "sal"      # Neutral, smooth voice
    EVE = "eve"      # Natural female voice
    LEO = "leo"      # Male voice


class TurnDetectionMode(Enum):
    """Turn detection modes for conversation."""
    SERVER_VAD = "server_vad"  # Server-side voice activity detection
    MANUAL = "none"           # Manual turn management


@dataclass
class SessionConfig:
    """Configuration for a voice session."""
    voice: Voice = Voice.ARA
    instructions: str = (
        "Persona: VERA — Versatile Embedded Reasoning Agent. "
        "Tone: elegant, composed, precise, lightly amused. Dry British wit. "
        "Voice mode: concise, natural speech; no customer-service sign-offs; truth-first; "
        "confirm sensitive actions."
    )
    input_audio_format: AudioFormat = AudioFormat.PCM_16K
    output_audio_format: AudioFormat = AudioFormat.PCM_16K
    turn_detection: TurnDetectionMode = TurnDetectionMode.SERVER_VAD
    temperature: float = 0.8
    max_tokens: int = 4096

    # VAD settings (when using SERVER_VAD)
    vad_threshold: float = 0.5
    vad_prefix_padding_ms: int = 300
    vad_silence_duration_ms: int = 500

    # Tool configuration
    tools: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SessionStats:
    """Statistics for a voice session."""
    session_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None

    # Connection stats
    connection_duration_seconds: float = 0.0
    reconnect_count: int = 0

    # Audio stats
    audio_chunks_sent: int = 0
    audio_chunks_received: int = 0
    total_input_bytes: int = 0
    total_output_bytes: int = 0

    # Message stats
    messages_sent: int = 0
    messages_received: int = 0
    tool_calls: int = 0

    # Errors
    errors: List[str] = field(default_factory=list)

    @property
    def estimated_cost(self) -> float:
        """Estimate session cost based on connection duration."""
        minutes = self.connection_duration_seconds / 60
        return minutes * COST_PER_MINUTE


class VoiceSessionManager:
    """
    Manages WebSocket connections to xAI Grok Voice Agent API.

    Provides:
    - Real-time bidirectional audio streaming
    - Session lifecycle management
    - Tool calling integration
    - Turn detection and barge-in support
    - Cost tracking

    Usage:
        async with VoiceSessionManager(api_key) as session:
            await session.connect(config)
            await session.send_audio(audio_data)
            async for event in session.events():
                handle_event(event)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        use_ephemeral_token: bool = False
    ):
        """
        Initialize voice session manager.

        Args:
            api_key: xAI API key (or XAI_API_KEY env var)
            use_ephemeral_token: Use ephemeral token for client-side auth
        """
        if not WEBSOCKETS_AVAILABLE:
            raise ImportError(
                "websockets library required for voice integration. "
                "Install with: pip install websockets"
            )

        self.api_key = api_key or os.environ.get("XAI_API_KEY") or os.environ.get("API_KEY")
        if not self.api_key:
            raise ValueError("XAI_API_KEY environment variable or api_key parameter required")

        self.use_ephemeral_token = use_ephemeral_token
        self._ephemeral_token: Optional[str] = None

        # Connection state
        self._ws: Optional[ClientConnection] = None
        self._state = SessionState.DISCONNECTED
        self._session_id: Optional[str] = None
        self._config: Optional[SessionConfig] = None

        # Event handling
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._event_queue: asyncio.Queue = asyncio.Queue()

        # Tasks
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Stats
        self._stats: Optional[SessionStats] = None

        # Callbacks
        self._on_audio: Optional[Callable[[bytes], None]] = None
        self._on_text: Optional[Callable[[str], None]] = None
        self._on_tool_call: Optional[Callable[[Dict], Any]] = None

    @property
    def state(self) -> SessionState:
        """Get current session state."""
        return self._state

    @property
    def session_id(self) -> Optional[str]:
        """Get current session ID."""
        return self._session_id

    @property
    def stats(self) -> Optional[SessionStats]:
        """Get session statistics."""
        if self._stats:
            if self._stats.ended_at:
                duration = (self._stats.ended_at - self._stats.started_at).total_seconds()
            else:
                duration = (datetime.now() - self._stats.started_at).total_seconds()
            self._stats.connection_duration_seconds = duration
        return self._stats

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def _get_ephemeral_token(self) -> str:
        """Get ephemeral token for client-side authentication."""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    XAI_TOKEN_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
                return data["client_secret"]["value"]
        except Exception as e:
            logger.error(f"Failed to get ephemeral token: {e}")
            raise

    async def connect(
        self,
        config: Optional[SessionConfig] = None
    ) -> str:
        """
        Connect to xAI Voice Agent API.

        Args:
            config: Session configuration

        Returns:
            Session ID
        """
        if self._state != SessionState.DISCONNECTED:
            raise RuntimeError(f"Cannot connect in state: {self._state}")

        self._config = config or SessionConfig()
        self._state = SessionState.CONNECTING
        self._session_id = f"voice-{uuid.uuid4().hex[:12]}"

        # Get auth token
        if self.use_ephemeral_token:
            token = await self._get_ephemeral_token()
        else:
            token = self.api_key

        # Connect WebSocket
        try:
            headers = {"Authorization": f"Bearer {token}"}
            realtime_url = XAI_REALTIME_URL
            if VOICE_MODEL:
                realtime_url = f"{XAI_REALTIME_URL}?model={VOICE_MODEL}"
            self._ws = await connect(
                realtime_url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10
            )

            # Initialize stats
            self._stats = SessionStats(
                session_id=self._session_id,
                started_at=datetime.now()
            )

            # Send session configuration
            await self._configure_session()

            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop())

            self._state = SessionState.CONNECTED
            logger.info(f"Voice session connected: {self._session_id}")

            return self._session_id

        except Exception as e:
            self._state = SessionState.ERROR
            logger.error(f"Connection failed: {e}")
            raise

    async def _configure_session(self) -> None:
        """Send session configuration to server."""
        config = self._config

        session_update = {
            "type": "session.update",
            "session": {
                "voice": config.voice.value,
                "instructions": config.instructions,
                "input_audio_format": config.input_audio_format.value,
                "output_audio_format": config.output_audio_format.value,
                "temperature": config.temperature,
                "max_output_tokens": config.max_tokens,
            }
        }

        # Add turn detection
        if config.turn_detection == TurnDetectionMode.SERVER_VAD:
            session_update["session"]["turn_detection"] = {
                "type": "server_vad",
                "threshold": config.vad_threshold,
                "prefix_padding_ms": config.vad_prefix_padding_ms,
                "silence_duration_ms": config.vad_silence_duration_ms
            }
        else:
            session_update["session"]["turn_detection"] = {"type": "none"}

        # Add tools if configured
        if config.tools:
            session_update["session"]["tools"] = config.tools

        await self._send(session_update)

    async def _send(self, message: Dict[str, Any]) -> None:
        """Send a message to the server."""
        if not self._ws:
            raise RuntimeError("Not connected")

        data = json.dumps(message)
        await self._ws.send(data)

        if self._stats:
            self._stats.messages_sent += 1

    async def _receive_loop(self) -> None:
        """Background task to receive messages from server."""
        try:
            async for message in self._ws:
                if self._stats:
                    self._stats.messages_received += 1

                try:
                    event = json.loads(message)
                    await self._handle_event(event)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received: {message[:100]}")

        except ConnectionClosed:
            logger.info("WebSocket connection closed")
            self._state = SessionState.DISCONNECTED
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
            self._state = SessionState.ERROR
            if self._stats:
                self._stats.errors.append(str(e))

    async def _handle_event(self, event: Dict[str, Any]) -> None:
        """Handle an incoming event from the server."""
        event_type = event.get("type", "unknown")

        # Put in queue for async iteration
        await self._event_queue.put(event)

        # Handle specific event types
        if event_type in ("response.audio.delta", "response.output_audio.delta"):
            # Audio data received
            audio_b64 = event.get("delta") or event.get("audio", "")
            if audio_b64 and self._on_audio:
                audio_bytes = base64.b64decode(audio_b64)
                if self._stats:
                    self._stats.audio_chunks_received += 1
                    self._stats.total_output_bytes += len(audio_bytes)
                self._on_audio(audio_bytes)

        elif event_type in ("response.text.delta", "response.output_audio_transcript.delta", "response.output_text.delta"):
            # Text response
            text = event.get("delta", "") or event.get("text", "") or event.get("transcript", "")
            if text and self._on_text:
                self._on_text(text)

        elif event_type == "response.function_call":
            # Tool call
            if self._stats:
                self._stats.tool_calls += 1
            if self._on_tool_call:
                result = await self._on_tool_call(event)
                await self._send_tool_result(event.get("call_id"), result)

        elif event_type == "error":
            error_msg = event.get("error", {}).get("message", "Unknown error")
            logger.error(f"Server error: {error_msg}")
            if self._stats:
                self._stats.errors.append(error_msg)

        elif event_type == "session.created":
            logger.info("Session created on server")

        elif event_type == "session.updated":
            logger.info("Session configuration updated")

        # Call registered handlers
        handlers = self._event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")

    async def _send_tool_result(
        self,
        call_id: str,
        result: Any
    ) -> None:
        """Send tool call result back to server."""
        message = {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result) if not isinstance(result, str) else result
            }
        }
        await self._send(message)

    async def send_audio(self, audio_data: bytes) -> None:
        """
        Send audio data to the server.

        Args:
            audio_data: Raw audio bytes in configured format
        """
        if self._state not in (SessionState.CONNECTED, SessionState.ACTIVE):
            raise RuntimeError(f"Cannot send audio in state: {self._state}")

        self._state = SessionState.ACTIVE

        # Base64 encode audio
        audio_b64 = base64.b64encode(audio_data).decode()

        message = {
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }
        await self._send(message)

        if self._stats:
            self._stats.audio_chunks_sent += 1
            self._stats.total_input_bytes += len(audio_data)

    async def commit_audio(self) -> None:
        """
        Commit the audio buffer for processing.

        Call this when the user has finished speaking
        (only needed in manual turn detection mode).
        """
        message = {"type": "input_audio_buffer.commit"}
        await self._send(message)

    async def clear_audio_buffer(self) -> None:
        """Clear the pending audio buffer."""
        message = {"type": "input_audio_buffer.clear"}
        await self._send(message)

    async def send_text(self, text: str) -> None:
        """
        Send text input to the conversation.

        Args:
            text: Text message to send
        """
        if self._state not in (SessionState.CONNECTED, SessionState.ACTIVE):
            raise RuntimeError(f"Cannot send text in state: {self._state}")

        message = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}]
            }
        }
        await self._send(message)

        # Request response
        await self.request_response(modalities=["text", "audio"])

    async def request_response(self, modalities: Optional[List[str]] = None) -> None:
        """
        Request an assistant response.

        Args:
            modalities: Optional list of response modalities (e.g., ["text", "audio"]).
        """
        if self._state not in (SessionState.CONNECTED, SessionState.ACTIVE):
            raise RuntimeError(f"Cannot request response in state: {self._state}")

        payload: Dict[str, Any] = {"type": "response.create"}
        if modalities:
            payload["response"] = {"modalities": modalities}
        await self._send(payload)

    async def interrupt(self) -> None:
        """
        Interrupt the current response (barge-in).

        Use this when the user starts speaking while
        the assistant is still responding.
        """
        message = {"type": "response.cancel"}
        await self._send(message)

    async def events(self):
        """
        Async generator for receiving events.

        Usage:
            async for event in session.events():
                print(event["type"])
        """
        while self._state in (SessionState.CONNECTED, SessionState.ACTIVE):
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=0.5
                )
                yield event
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def on_audio(self, callback: Callable[[bytes], None]) -> None:
        """Register callback for audio output."""
        self._on_audio = callback

    def on_text(self, callback: Callable[[str], None]) -> None:
        """Register callback for text output."""
        self._on_text = callback

    def on_tool_call(self, callback: Callable[[Dict], Any]) -> None:
        """Register callback for tool calls."""
        self._on_tool_call = callback

    def on(self, event_type: str, callback: Callable) -> None:
        """
        Register an event handler.

        Args:
            event_type: Event type to handle (e.g., "response.done")
            callback: Handler function
        """
        self._event_handlers.setdefault(event_type, []).append(callback)

    async def disconnect(self) -> SessionStats:
        """
        Disconnect from the server.

        Returns:
            Final session statistics
        """
        if self._state == SessionState.DISCONNECTED:
            return self._stats

        # Cancel receive task
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                logger.debug("Suppressed Exception in session")
                pass

        # Close WebSocket
        if self._ws:
            await self._ws.close()
            self._ws = None

        # Finalize stats
        if self._stats:
            self._stats.ended_at = datetime.now()

        self._state = SessionState.DISCONNECTED
        logger.info(f"Voice session disconnected: {self._session_id}")

        return self._stats


# === Audio Utilities ===

def chunk_audio(
    audio_data: bytes,
    chunk_size: int = 4096
) -> List[bytes]:
    """
    Split audio data into chunks for streaming.

    Args:
        audio_data: Raw audio bytes
        chunk_size: Bytes per chunk

    Returns:
        List of audio chunks
    """
    return [
        audio_data[i:i + chunk_size]
        for i in range(0, len(audio_data), chunk_size)
    ]


def resample_audio(
    audio_data: bytes,
    source_rate: int,
    target_rate: int,
    channels: int = 1,
    sample_width: int = 2
) -> bytes:
    """
    Resample audio to a different sample rate.

    Requires numpy and scipy.

    Args:
        audio_data: Raw audio bytes
        source_rate: Original sample rate
        target_rate: Target sample rate
        channels: Number of audio channels
        sample_width: Bytes per sample

    Returns:
        Resampled audio bytes
    """
    try:
        import numpy as np
        from scipy import signal

        # Convert bytes to numpy array
        dtype = np.int16 if sample_width == 2 else np.int32
        samples = np.frombuffer(audio_data, dtype=dtype)

        # Reshape for channels
        if channels > 1:
            samples = samples.reshape(-1, channels)

        # Resample
        num_samples = int(len(samples) * target_rate / source_rate)
        resampled = signal.resample(samples, num_samples)

        # Convert back to bytes
        return resampled.astype(dtype).tobytes()

    except ImportError:
        raise ImportError(
            "Audio resampling requires numpy and scipy. "
            "Install with: pip install numpy scipy"
        )


# === Self-test ===

if __name__ == "__main__":
    import sys

    async def test_session():
        """Test voice session connection."""
        print("Testing Voice Session Manager...")

        # Check for API key
        api_key = os.environ.get("XAI_API_KEY") or os.environ.get("API_KEY")
        if not api_key:
            print("SKIP: XAI_API_KEY not set")
            return True

        # Test 1: Create session manager
        print("Test 1: Create session manager...", end=" ")
        try:
            manager = VoiceSessionManager(api_key)
            print("PASS")
        except Exception as e:
            print(f"FAIL: {e}")
            return False

        # Test 2: Session config
        print("Test 2: Create session config...", end=" ")
        config = SessionConfig(
            voice=Voice.ARA,
            instructions="You are a test assistant.",
            input_audio_format=AudioFormat.PCM_16K,
            output_audio_format=AudioFormat.PCM_16K,
            turn_detection=TurnDetectionMode.SERVER_VAD
        )
        print("PASS")

        # Test 3: Audio chunking
        print("Test 3: Audio chunking...", end=" ")
        test_audio = b'\x00' * 16384
        chunks = chunk_audio(test_audio, chunk_size=4096)
        assert len(chunks) == 4
        assert all(len(c) == 4096 for c in chunks)
        print("PASS")

        # Test 4: Stats tracking
        print("Test 4: Stats tracking...", end=" ")
        stats = SessionStats(
            session_id="test-123",
            started_at=datetime.now()
        )
        stats.connection_duration_seconds = 120  # 2 minutes
        assert stats.estimated_cost == 0.10  # $0.05/min * 2 min
        print("PASS")

        # Test 5: Event handler registration
        print("Test 5: Event handlers...", end=" ")
        handler_called = False

        def test_handler(event) -> None:
            nonlocal handler_called
            handler_called = True

        manager.on("test.event", test_handler)
        assert "test.event" in manager._event_handlers
        assert test_handler in manager._event_handlers["test.event"]
        print("PASS")

        print("\nAll tests passed!")
        return True

    success = asyncio.run(test_session())
    sys.exit(0 if success else 1)
