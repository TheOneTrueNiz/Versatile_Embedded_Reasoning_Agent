"""
Voice Agent Integration for VERA.

Provides high-level interface for voice conversations using xAI Grok Voice Agent API.
Manages audio capture, playback, and conversation state.
"""

import os
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from enum import Enum

from .session import (
    VoiceSessionManager,
    SessionConfig,
    SessionStats,
    SessionState,
    AudioFormat,
    Voice,
    TurnDetectionMode,
    chunk_audio
)

logger = logging.getLogger(__name__)


# === Audio Device Support ===

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

try:
    import sounddevice as sd
    import numpy as np
    SOUNDDEVICE_AVAILABLE = True
except (ImportError, OSError):
    # OSError is raised when python package is present but system PortAudio
    # shared libs are missing on fresh hosts.
    SOUNDDEVICE_AVAILABLE = False


class AudioBackend(Enum):
    """Available audio backends."""
    PYAUDIO = "pyaudio"
    SOUNDDEVICE = "sounddevice"
    NONE = "none"


def get_available_backend() -> AudioBackend:
    """Get the best available audio backend."""
    if SOUNDDEVICE_AVAILABLE:
        return AudioBackend.SOUNDDEVICE
    elif PYAUDIO_AVAILABLE:
        return AudioBackend.PYAUDIO
    return AudioBackend.NONE


# === Conversation State ===

class ConversationState(Enum):
    """Voice conversation states."""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


@dataclass
class ConversationTurn:
    """A single turn in the voice conversation."""
    turn_id: str
    role: str  # "user" or "assistant"
    started_at: datetime
    ended_at: Optional[datetime] = None

    # Content
    audio_data: Optional[bytes] = None
    transcript: Optional[str] = None

    # Tool calls (assistant turns only)
    tool_calls: List[Dict] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return 0.0


@dataclass
class Conversation:
    """Voice conversation with turn history."""
    conversation_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    turns: List[ConversationTurn] = field(default_factory=list)

    # Session stats
    session_stats: Optional[SessionStats] = None

    @property
    def total_duration_seconds(self) -> float:
        if self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return (datetime.now() - self.started_at).total_seconds()


class VoiceAgent:
    """
    High-level voice agent for VERA.

    Provides:
    - Audio capture and playback
    - Voice conversation management
    - Integration with VERA's tool system
    - Conversation history tracking

    Usage:
        agent = VoiceAgent()
        await agent.start_conversation()
        # User speaks, agent responds...
        await agent.end_conversation()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice: Voice = Voice.ARA,
        instructions: Optional[str] = None,
        audio_backend: Optional[AudioBackend] = None,
        sample_rate: int = 16000,
        channels: int = 1
    ):
        """
        Initialize voice agent.

        Args:
            api_key: xAI API key (or from env)
            voice: Voice to use for responses
            instructions: System instructions for the agent
            audio_backend: Audio backend to use (auto-detect if None)
            sample_rate: Audio sample rate in Hz
            channels: Number of audio channels (1=mono)
        """
        self.api_key = api_key or os.environ.get("XAI_API_KEY") or os.environ.get("API_KEY")
        self.voice = voice
        self.instructions = instructions or self._default_instructions()

        # Audio config
        self.sample_rate = sample_rate
        self.channels = channels
        self.audio_backend = audio_backend or get_available_backend()

        # Session management
        self._session: Optional[VoiceSessionManager] = None
        self._conversation: Optional[Conversation] = None
        self._state = ConversationState.IDLE

        # Audio streams
        self._input_stream = None
        self._output_stream = None
        self._audio_buffer: bytes = b""
        self._output_queue: asyncio.Queue = asyncio.Queue()

        # Tasks
        self._capture_task: Optional[asyncio.Task] = None
        self._playback_task: Optional[asyncio.Task] = None
        self._process_task: Optional[asyncio.Task] = None

        # Callbacks
        self._on_transcript: Optional[Callable[[str, str], None]] = None
        self._on_state_change: Optional[Callable[[ConversationState], None]] = None

        # Tool system integration
        self._tools: List[Dict] = []
        self._tool_handlers: Dict[str, Callable] = {}

    def _default_instructions(self) -> str:
        """Default system instructions for VERA voice mode."""
        return """Persona Header (voice):
- Name: VERA (Versatile Embedded Reasoning Agent)
- Role: Proactive personal AI assistant and technical collaborator
- Tone: Elegant, composed, precise, lightly amused
- Wit: Dry British deadpan (subtle, never cruel)

Voice behaviors:
- Speak naturally and keep responses concise; you are speaking, not typing
- Truth-first and not a yes-person; push back on risky or flawed ideas with calm clarity
- Be proactive but not overbearing; ask one focused question only if blocked
- Avoid customer-service sign-offs or readiness check-ins
- Use one wry line max in low-stakes moments; none when the user is stressed
- Acknowledge tool use briefly

Tool safety:
- For email/calendar/drive, confirm key details before acting
- Read back spelled email addresses before sending
- For risky or destructive actions, confirm explicitly

End naturally once the point is made."""

    @property
    def state(self) -> ConversationState:
        """Get current conversation state."""
        return self._state

    @property
    def is_active(self) -> bool:
        """Check if a conversation is active."""
        return self._session is not None and self._session.state != SessionState.DISCONNECTED

    @property
    def current_conversation(self) -> Optional[Conversation]:
        """Get the current conversation."""
        return self._conversation

    def _set_state(self, state: ConversationState) -> None:
        """Update conversation state and notify."""
        old_state = self._state
        self._state = state

        if self._on_state_change and old_state != state:
            self._on_state_change(state)

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable
    ) -> None:
        """
        Register a tool for voice agent use.

        Args:
            name: Tool name (e.g., "add_task")
            description: Tool description for the model
            parameters: JSON schema for tool parameters
            handler: Async function to handle tool calls
        """
        tool_def = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            }
        }
        self._tools.append(tool_def)
        self._tool_handlers[name] = handler

    def on_transcript(self, callback: Callable[[str, str], None]) -> None:
        """
        Register callback for transcripts.

        Args:
            callback: Function(role, text) called for each transcript
        """
        self._on_transcript = callback

    def on_state_change(self, callback: Callable[[ConversationState], None]) -> None:
        """
        Register callback for state changes.

        Args:
            callback: Function(new_state) called on state change
        """
        self._on_state_change = callback

    async def start_conversation(
        self,
        greet: bool = True,
        greeting_text: Optional[str] = None
    ) -> str:
        """
        Start a new voice conversation.

        Args:
            greet: Whether to have the agent greet first
            greeting_text: Custom greeting instructions

        Returns:
            Conversation ID
        """
        if self.is_active:
            raise RuntimeError("Conversation already in progress")

        # Create session config
        config = SessionConfig(
            voice=self.voice,
            instructions=self.instructions,
            input_audio_format=AudioFormat.PCM_16K,
            output_audio_format=AudioFormat.PCM_16K,
            turn_detection=TurnDetectionMode.SERVER_VAD,
            tools=self._tools
        )

        # Create session manager
        self._session = VoiceSessionManager(api_key=self.api_key)

        # Set up callbacks
        self._session.on_audio(self._handle_audio_output)
        self._session.on_text(self._handle_text_output)
        self._session.on_tool_call(self._handle_tool_call)

        # Connect
        session_id = await self._session.connect(config)

        # Create conversation
        self._conversation = Conversation(
            conversation_id=session_id,
            started_at=datetime.now()
        )

        # Start audio streams
        await self._start_audio_streams()

        # Start processing tasks
        self._capture_task = asyncio.create_task(self._audio_capture_loop())
        self._playback_task = asyncio.create_task(self._audio_playback_loop())
        self._process_task = asyncio.create_task(self._event_process_loop())

        self._set_state(ConversationState.LISTENING)

        # Optional greeting
        if greet:
            greeting = greeting_text or "Greet the user warmly and ask how you can help."
            await self._session.send_text(greeting)
            self._set_state(ConversationState.PROCESSING)

        logger.info(f"Voice conversation started: {session_id}")
        return session_id

    async def end_conversation(self) -> Optional[Conversation]:
        """
        End the current voice conversation.

        Returns:
            Completed conversation with stats
        """
        if not self.is_active:
            return self._conversation

        # Stop audio streams
        await self._stop_audio_streams()

        # Cancel tasks
        for task in [self._capture_task, self._playback_task, self._process_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.debug("Suppressed Exception in agent")
                    pass

        # Disconnect session
        if self._session:
            stats = await self._session.disconnect()
            if self._conversation:
                self._conversation.session_stats = stats
                self._conversation.ended_at = datetime.now()

        self._set_state(ConversationState.IDLE)

        conversation = self._conversation
        self._session = None
        self._conversation = None

        logger.info(f"Voice conversation ended: {conversation.conversation_id if conversation else 'unknown'}")
        return conversation

    async def _start_audio_streams(self) -> None:
        """Initialize audio input/output streams."""
        if self.audio_backend == AudioBackend.NONE:
            logger.warning("No audio backend available - voice input/output disabled")
            return

        if self.audio_backend == AudioBackend.SOUNDDEVICE:
            await self._start_sounddevice_streams()
        elif self.audio_backend == AudioBackend.PYAUDIO:
            await self._start_pyaudio_streams()

    async def _start_sounddevice_streams(self) -> None:
        """Initialize sounddevice streams."""
        if not SOUNDDEVICE_AVAILABLE:
            return

        def input_callback(indata, frames, time, status) -> None:
            if status:
                logger.warning(f"Audio input status: {status}")
            audio_bytes = indata.tobytes()
            asyncio.get_event_loop().call_soon_threadsafe(
                self._audio_buffer_append, audio_bytes
            )

        def output_callback(outdata, frames, time, status) -> None:
            if status:
                logger.warning(f"Audio output status: {status}")
            try:
                data = self._output_queue.get_nowait()
                samples = np.frombuffer(data, dtype=np.int16)
                if len(samples) < frames:
                    samples = np.pad(samples, (0, frames - len(samples)))
                elif len(samples) > frames:
                    samples = samples[:frames]
                outdata[:] = samples.reshape(-1, 1)
            except asyncio.QueueEmpty:
                outdata.fill(0)

        self._input_stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=np.int16,
            callback=input_callback
        )

        self._output_stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=np.int16,
            callback=output_callback
        )

        self._input_stream.start()
        self._output_stream.start()

    async def _start_pyaudio_streams(self) -> None:
        """Initialize PyAudio streams."""
        if not PYAUDIO_AVAILABLE:
            return

        self._pyaudio = pyaudio.PyAudio()

        def input_callback(in_data, frame_count, time_info, status):
            self._audio_buffer += in_data
            return (None, pyaudio.paContinue)

        self._input_stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=1024,
            stream_callback=input_callback
        )

        self._output_stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            output=True,
            frames_per_buffer=1024
        )

        self._input_stream.start_stream()
        self._output_stream.start_stream()

    async def _stop_audio_streams(self) -> None:
        """Stop and clean up audio streams."""
        if self._input_stream:
            if self.audio_backend == AudioBackend.SOUNDDEVICE:
                self._input_stream.stop()
                self._input_stream.close()
            elif self.audio_backend == AudioBackend.PYAUDIO:
                self._input_stream.stop_stream()
                self._input_stream.close()
            self._input_stream = None

        if self._output_stream:
            if self.audio_backend == AudioBackend.SOUNDDEVICE:
                self._output_stream.stop()
                self._output_stream.close()
            elif self.audio_backend == AudioBackend.PYAUDIO:
                self._output_stream.stop_stream()
                self._output_stream.close()
            self._output_stream = None

        if hasattr(self, '_pyaudio') and self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None

    def _audio_buffer_append(self, data: bytes) -> None:
        """Thread-safe append to audio buffer."""
        self._audio_buffer += data

    async def _audio_capture_loop(self) -> None:
        """Background task to capture and send audio."""
        chunk_size = 4096  # ~256ms at 16kHz

        while self.is_active:
            await asyncio.sleep(0.1)  # 100ms intervals

            if len(self._audio_buffer) >= chunk_size:
                chunk = self._audio_buffer[:chunk_size]
                self._audio_buffer = self._audio_buffer[chunk_size:]

                if self._session and self._state == ConversationState.LISTENING:
                    try:
                        await self._session.send_audio(chunk)
                    except Exception as e:
                        logger.error(f"Error sending audio: {e}")

    async def _audio_playback_loop(self) -> None:
        """Background task to play received audio."""
        while self.is_active:
            try:
                audio_data = await asyncio.wait_for(
                    self._output_queue.get(),
                    timeout=0.5
                )

                if self.audio_backend == AudioBackend.PYAUDIO and self._output_stream:
                    self._output_stream.write(audio_data)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Playback error: {e}")

    async def _event_process_loop(self) -> None:
        """Background task to process session events."""
        if not self._session:
            return

        try:
            async for event in self._session.events():
                event_type = event.get("type", "")

                if event_type == "input_audio_buffer.speech_started":
                    self._set_state(ConversationState.LISTENING)

                elif event_type == "input_audio_buffer.speech_stopped":
                    self._set_state(ConversationState.PROCESSING)

                elif event_type == "response.audio.delta":
                    self._set_state(ConversationState.SPEAKING)

                elif event_type == "response.done":
                    self._set_state(ConversationState.LISTENING)

                    # Extract transcript if available
                    response = event.get("response", {})
                    for output in response.get("output", []):
                        if output.get("type") == "message":
                            for content in output.get("content", []):
                                if content.get("type") == "text":
                                    text = content.get("text", "")
                                    if text and self._on_transcript:
                                        self._on_transcript("assistant", text)

                elif event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript", "")
                    if transcript and self._on_transcript:
                        self._on_transcript("user", transcript)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Event processing error: {e}")

    def _handle_audio_output(self, audio_data: bytes) -> None:
        """Handle incoming audio from the session."""
        try:
            self._output_queue.put_nowait(audio_data)
        except asyncio.QueueFull:
            logger.warning("Audio output queue full, dropping data")

    def _handle_text_output(self, text: str) -> None:
        """Handle incoming text from the session."""
        # Text is streamed alongside audio, handled in event loop
        pass

    async def _handle_tool_call(self, event: Dict) -> Any:
        """Handle tool calls from the voice session."""
        function_call = event.get("function_call", {})
        name = function_call.get("name", "")
        arguments = function_call.get("arguments", "{}")

        logger.info(f"Voice tool call: {name}")

        handler = self._tool_handlers.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}

        try:
            import json
            args = json.loads(arguments)

            if asyncio.iscoroutinefunction(handler):
                result = await handler(**args)
            else:
                result = handler(**args)

            return result

        except Exception as e:
            logger.error(f"Tool call error: {e}")
            return {"error": str(e)}

    async def send_text(self, text: str) -> None:
        """
        Send text input to the conversation.

        Useful for sending typed input alongside voice.
        """
        if not self.is_active:
            raise RuntimeError("No active conversation")

        await self._session.send_text(text)

    async def interrupt(self) -> None:
        """
        Interrupt the agent while speaking (barge-in).
        """
        if not self.is_active:
            return

        if self._state == ConversationState.SPEAKING:
            await self._session.interrupt()
            self._set_state(ConversationState.LISTENING)

    def get_stats(self) -> Dict[str, Any]:
        """Get current agent statistics."""
        stats = {
            "state": self._state.value,
            "is_active": self.is_active,
            "audio_backend": self.audio_backend.value,
            "voice": self.voice.value,
        }

        if self._conversation:
            stats["conversation"] = {
                "id": self._conversation.conversation_id,
                "duration_seconds": self._conversation.total_duration_seconds,
                "turns": len(self._conversation.turns)
            }

        if self._session and self._session.stats:
            session_stats = self._session.stats
            stats["session"] = {
                "audio_chunks_sent": session_stats.audio_chunks_sent,
                "audio_chunks_received": session_stats.audio_chunks_received,
                "tool_calls": session_stats.tool_calls,
                "estimated_cost": session_stats.estimated_cost
            }

        return stats


# === Factory Functions ===

def create_voice_agent(
    instructions: Optional[str] = None,
    voice: Voice = Voice.ARA,
    tools: Optional[List[Dict]] = None
) -> VoiceAgent:
    """
    Create a configured voice agent.

    Args:
        instructions: Custom system instructions
        voice: Voice to use
        tools: Tool definitions to register

    Returns:
        Configured VoiceAgent instance
    """
    agent = VoiceAgent(
        voice=voice,
        instructions=instructions
    )

    # Register tools if provided
    if tools:
        for tool in tools:
            func = tool.get("function", {})
            agent._tools.append({
                "type": "function",
                "function": func
            })

    return agent


# === Self-test ===

if __name__ == "__main__":
    import sys

    async def test_agent():
        """Test voice agent."""
        print("Testing Voice Agent...")

        # Test 1: Create agent
        print("Test 1: Create voice agent...", end=" ")
        try:
            agent = VoiceAgent(api_key="test-key-for-unit-test")
            print("PASS")
        except Exception as e:
            print(f"FAIL: {e}")
            return False

        # Test 2: Check audio backend
        print("Test 2: Check audio backend...", end=" ")
        backend = get_available_backend()
        print(f"PASS ({backend.value})")

        # Test 3: Default instructions
        print("Test 3: Default instructions...", end=" ")
        instructions = agent._default_instructions()
        assert "VERA" in instructions
        assert "voice" in instructions.lower()
        print("PASS")

        # Test 4: State management
        print("Test 4: State management...", end=" ")
        assert agent.state == ConversationState.IDLE
        states_seen = []
        agent.on_state_change(lambda s: states_seen.append(s))
        agent._set_state(ConversationState.LISTENING)
        assert agent.state == ConversationState.LISTENING
        assert ConversationState.LISTENING in states_seen
        print("PASS")

        # Test 5: Tool registration
        print("Test 5: Tool registration...", end=" ")

        async def dummy_tool(text: str):
            return {"result": text}

        agent.register_tool(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=dummy_tool
        )
        assert len(agent._tools) == 1
        assert "test_tool" in agent._tool_handlers
        print("PASS")

        # Test 6: Stats
        print("Test 6: Get stats...", end=" ")
        stats = agent.get_stats()
        assert "state" in stats
        assert "is_active" in stats
        assert stats["is_active"] == False
        print("PASS")

        # Test 7: Conversation turn
        print("Test 7: Conversation turn...", end=" ")
        turn = ConversationTurn(
            turn_id="turn-1",
            role="user",
            started_at=datetime.now()
        )
        turn.ended_at = datetime.now()
        assert turn.duration_seconds >= 0
        print("PASS")

        print("\nAll tests passed!")
        return True

    success = asyncio.run(test_agent())
    sys.exit(0 if success else 1)
