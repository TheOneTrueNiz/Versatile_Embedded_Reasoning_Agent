<template>
  <div class="voice-realtime" aria-hidden="true"></div>
</template>

<script setup>
import { computed, defineEmits, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { conversations, isVoiceModeOpen, lastLoadedConversationId, messages, selectedConversation, voiceAgentVoice, voiceModeStatus, voiceModeLevel } from '@/libs/state-management/state';
import { showToast } from '@/libs/utils/general-utils';
import { addMessage } from '@/libs/conversation-management/message-processing';
import { saveMessagesHandler } from '@/libs/conversation-management/useConversations';

const emit = defineEmits(['close-voice-mode']);

const status = ref('idle');
const errorMessage = ref('');
const transcripts = ref([]);
const isActive = ref(false);
const isBusy = ref(false);
const voiceEnabled = ref(true);

const wsRef = ref(null);
const audioContextRef = ref(null);
const playbackContextRef = ref(null);
const processorRef = ref(null);
const sourceRef = ref(null);
const gainRef = ref(null);
const streamRef = ref(null);
const playbackCursorRef = ref(0);
const playbackSampleRate = ref(24000);
const playbackRate = ref(1.04);
const lastTranscriptRef = ref({ role: '', text: '', ts: 0 });
const lastMainMessageRef = ref({ role: '', text: '', ts: 0 });
const pendingSaveRef = ref(false);
const saveInFlightRef = ref(false);
const assistantMessageId = ref(null);
const audioGateOpenRef = ref(false);
const audioQueueRef = ref([]);
const audioGateTimerRef = ref(null);
const lastStreamSaveRef = ref(0);
const smoothedLevelRef = ref(0);
const clientSpeechActiveRef = ref(false);
const lastVoiceActivityRef = ref(0);

const SILENCE_RMS_THRESHOLD = 0.02;
const SILENCE_HOLD_MS = 900;

const AUDIO_GATE_TIMEOUT_MS = 1200;
const STREAM_SAVE_INTERVAL_MS = 900;

const ensureConversationSelected = () => {
  if (selectedConversation.value) {
    return true;
  }
  if (!conversations.value.length) {
    return false;
  }
  const targetId = lastLoadedConversationId.value || conversations.value[0].id;
  const target = conversations.value.find((item) => item.id === targetId) || conversations.value[0];
  selectedConversation.value = target || null;
  lastLoadedConversationId.value = target?.id || null;
  return !!selectedConversation.value;
};

const saveIfReady = () => {
  if (saveInFlightRef.value) {
    pendingSaveRef.value = true;
    return;
  }
  saveInFlightRef.value = true;
  saveMessagesHandler()
    .catch((error) => console.error('Failed to save messages:', error))
    .finally(() => {
      saveInFlightRef.value = false;
      if (pendingSaveRef.value) {
        pendingSaveRef.value = false;
        saveIfReady();
      }
    });
};

const maybeSaveStream = () => {
  const now = Date.now();
  if (now - lastStreamSaveRef.value < STREAM_SAVE_INTERVAL_MS) {
    return;
  }
  lastStreamSaveRef.value = now;
  saveIfReady();
};

const statusLabel = computed(() => status.value);
const statusClass = computed(() => {
  if (status.value === 'speaking') return 'speaking';
  if (status.value === 'listening') return 'listening';
  if (status.value === 'processing') return 'processing';
  if (status.value === 'connecting') return 'connecting';
  if (status.value === 'error') return 'error';
  return 'idle';
});

watch(status, (value) => {
  voiceModeStatus.value = value || 'idle';
  if (value !== 'listening') {
    smoothedLevelRef.value = 0;
    voiceModeLevel.value = 0;
    clientSpeechActiveRef.value = false;
    lastVoiceActivityRef.value = 0;
  }
});

const downsampleBuffer = (buffer, inputRate, outputRate) => {
  if (outputRate === inputRate) {
    return buffer;
  }
  const ratio = inputRate / outputRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetBuffer = 0;
  for (let i = 0; i < result.length; i += 1) {
    const nextOffsetBuffer = Math.round((i + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let j = offsetBuffer; j < nextOffsetBuffer && j < buffer.length; j += 1) {
      accum += buffer[j];
      count += 1;
    }
    result[i] = count ? accum / count : 0;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
};

const floatTo16BitPCM = (input) => {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, input[i]));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
};

const enqueueAudio = (buffer) => {
  if (!playbackContextRef.value) {
    playbackContextRef.value = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: playbackSampleRate.value });
  }
  if (playbackContextRef.value.state === 'suspended') {
    playbackContextRef.value.resume().catch(() => {});
  }
  const pcm = new Int16Array(buffer);
  const audioBuffer = playbackContextRef.value.createBuffer(1, pcm.length, playbackSampleRate.value);
  const channel = audioBuffer.getChannelData(0);
  for (let i = 0; i < pcm.length; i += 1) {
    channel[i] = pcm[i] / 32768;
  }
  const source = playbackContextRef.value.createBufferSource();
  source.buffer = audioBuffer;
  const rate = playbackRate.value || 1.0;
  source.playbackRate.value = rate;
  source.connect(playbackContextRef.value.destination);
  const startAt = Math.max(playbackContextRef.value.currentTime + 0.01, playbackCursorRef.value);
  source.start(startAt);
  playbackCursorRef.value = startAt + (audioBuffer.duration / rate);
};

const openAudioGate = () => {
  if (audioGateOpenRef.value) {
    return;
  }
  audioGateOpenRef.value = true;
  if (audioGateTimerRef.value) {
    clearTimeout(audioGateTimerRef.value);
    audioGateTimerRef.value = null;
  }
  const queued = audioQueueRef.value;
  audioQueueRef.value = [];
  queued.forEach((chunk) => enqueueAudio(chunk));
};

const resetAudioGate = () => {
  audioGateOpenRef.value = false;
  audioQueueRef.value = [];
  if (audioGateTimerRef.value) {
    clearTimeout(audioGateTimerRef.value);
    audioGateTimerRef.value = null;
  }
};

const queueAudio = (buffer) => {
  audioQueueRef.value.push(buffer);
  if (!audioGateTimerRef.value) {
    audioGateTimerRef.value = setTimeout(() => {
      openAudioGate();
    }, AUDIO_GATE_TIMEOUT_MS);
  }
};

const handleWsMessage = (event) => {
  if (typeof event.data === 'string') {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === 'state') {
        status.value = payload.state || status.value;
        if (payload.state === 'processing') {
          resetAudioGate();
        }
        return;
      }
      if (payload.type === 'assistant_delta') {
        const text = payload.text || '';
        if (!text) {
          return;
        }
        const lastIndex = transcripts.value.length - 1;
        if (lastIndex >= 0 && transcripts.value[lastIndex].role === 'assistant') {
          transcripts.value[lastIndex].text = text;
        } else {
          transcripts.value.push({ role: 'assistant', text });
        }
        if (transcripts.value.length > 6) {
          transcripts.value.shift();
        }
        if (!assistantMessageId.value) {
          addMessage('assistant', [{ type: 'text', text }]);
          const lastMessage = messages.value[messages.value.length - 1];
          assistantMessageId.value = lastMessage?.id || null;
        }
        const target = messages.value.find((message) => message.id === assistantMessageId.value);
        if (target) {
          target.content = [{ type: 'text', text }];
        }
        openAudioGate();
        maybeSaveStream();
        return;
      }
      if (payload.type === 'assistant_final') {
        const text = payload.text || '';
        if (!text) {
          return;
        }
        const lastIndex = transcripts.value.length - 1;
        if (lastIndex >= 0 && transcripts.value[lastIndex].role === 'assistant') {
          transcripts.value[lastIndex].text = text;
        } else {
          transcripts.value.push({ role: 'assistant', text });
        }
        if (transcripts.value.length > 6) {
          transcripts.value.shift();
        }
        if (!assistantMessageId.value) {
          addMessage('assistant', [{ type: 'text', text }]);
          const lastMessage = messages.value[messages.value.length - 1];
          assistantMessageId.value = lastMessage?.id || null;
        }
        const target = messages.value.find((message) => message.id === assistantMessageId.value);
        if (target) {
          target.content = [{ type: 'text', text }];
        }
        openAudioGate();
        saveIfReady();
        assistantMessageId.value = null;
        return;
      }
      if (payload.type === 'transcript') {
        const role = payload.role || 'assistant';
        if (role !== 'user') {
          return;
        }
        const text = payload.text || '';
        if (!text) {
          return;
        }
        const now = Date.now();
        if (
          lastTranscriptRef.value.role === role
          && lastTranscriptRef.value.text === text
          && now - lastTranscriptRef.value.ts < 2000
        ) {
          return;
        }
        lastTranscriptRef.value = { role, text, ts: now };
        transcripts.value.push({ role, text });
        if (transcripts.value.length > 6) {
          transcripts.value.shift();
        }
        if (
          lastMainMessageRef.value.role !== role
          || lastMainMessageRef.value.text !== text
          || now - lastMainMessageRef.value.ts >= 2000
        ) {
          lastMainMessageRef.value = { role, text, ts: now };
          addMessage(role === 'assistant' ? 'assistant' : 'user', [{ type: 'text', text }]);
          saveIfReady();
        }
        return;
      }
      if (payload.type === 'error') {
        status.value = 'error';
        errorMessage.value = payload.message || 'Voice error';
        return;
      }
      if (payload.type === 'started') {
        status.value = 'listening';
        if (payload.sample_rate && payload.sample_rate !== playbackSampleRate.value) {
          playbackSampleRate.value = payload.sample_rate;
          if (playbackContextRef.value) {
            playbackContextRef.value.close().catch(() => {});
            playbackContextRef.value = null;
          }
          playbackCursorRef.value = 0;
        }
        return;
      }
    } catch (error) {
      console.error(error);
    }
    return;
  }
  if (event.data instanceof ArrayBuffer) {
    if (audioGateOpenRef.value) {
      enqueueAudio(event.data);
    } else {
      queueAudio(event.data);
    }
  }
};

const startAudioCapture = async () => {
  const audioContext = new (window.AudioContext || window.webkitAudioContext)();
  audioContextRef.value = audioContext;
  streamRef.value = await navigator.mediaDevices.getUserMedia({ audio: true });
  sourceRef.value = audioContext.createMediaStreamSource(streamRef.value);
  processorRef.value = audioContext.createScriptProcessor(4096, 1, 1);
  gainRef.value = audioContext.createGain();
  gainRef.value.gain.value = 0;

  processorRef.value.onaudioprocess = (event) => {
    if (!isActive.value) {
      voiceModeLevel.value = 0;
      return;
    }
    const input = event.inputBuffer.getChannelData(0);
    const now = Date.now();
    if (status.value === 'listening') {
      let sum = 0;
      for (let i = 0; i < input.length; i += 1) {
        sum += input[i] * input[i];
      }
      const rms = Math.sqrt(sum / input.length);
      const scaled = Math.min(1, rms * 3.5);
      const smoothed = smoothedLevelRef.value * 0.7 + scaled * 0.3;
      smoothedLevelRef.value = smoothed;
      voiceModeLevel.value = smoothed;
      if (rms >= SILENCE_RMS_THRESHOLD) {
        clientSpeechActiveRef.value = true;
        lastVoiceActivityRef.value = now;
      } else if (
        clientSpeechActiveRef.value
        && lastVoiceActivityRef.value
        && now - lastVoiceActivityRef.value > SILENCE_HOLD_MS
      ) {
        clientSpeechActiveRef.value = false;
        lastVoiceActivityRef.value = 0;
        if (wsRef.value && wsRef.value.readyState === WebSocket.OPEN) {
          wsRef.value.send(JSON.stringify({ type: 'commit' }));
        }
      }
    } else {
      smoothedLevelRef.value = 0;
      voiceModeLevel.value = 0;
      clientSpeechActiveRef.value = false;
      lastVoiceActivityRef.value = 0;
    }
    if (!wsRef.value || wsRef.value.readyState !== WebSocket.OPEN) {
      return;
    }
    const downsampled = downsampleBuffer(input, audioContext.sampleRate, 16000);
    const pcm = floatTo16BitPCM(downsampled);
    wsRef.value.send(pcm.buffer);
  };

  sourceRef.value.connect(processorRef.value);
  processorRef.value.connect(gainRef.value);
  gainRef.value.connect(audioContext.destination);
};

const stopAudioCapture = () => {
  if (processorRef.value) {
    processorRef.value.disconnect();
    processorRef.value = null;
  }
  if (sourceRef.value) {
    sourceRef.value.disconnect();
    sourceRef.value = null;
  }
  if (gainRef.value) {
    gainRef.value.disconnect();
    gainRef.value = null;
  }
  if (streamRef.value) {
    streamRef.value.getTracks().forEach((track) => track.stop());
    streamRef.value = null;
  }
  if (audioContextRef.value) {
    audioContextRef.value.close().catch(() => {});
    audioContextRef.value = null;
  }
};

const openWebSocket = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${protocol}://${window.location.host}/api/voice/ws`;
  wsRef.value = new WebSocket(wsUrl);
  wsRef.value.binaryType = 'arraybuffer';
  wsRef.value.addEventListener('open', () => {
    const voiceName = (voiceAgentVoice.value || 'eve').toLowerCase();
    wsRef.value.send(JSON.stringify({ type: 'start', voice: voiceName }));
    isActive.value = true;
  });
  wsRef.value.addEventListener('message', handleWsMessage);
  wsRef.value.addEventListener('close', () => {
    status.value = 'idle';
    isActive.value = false;
    stopAudioCapture();
    if (playbackContextRef.value) {
      playbackContextRef.value.close().catch(() => {});
      playbackContextRef.value = null;
    }
    playbackCursorRef.value = 0;
  });
  wsRef.value.addEventListener('error', () => {
    status.value = 'error';
    errorMessage.value = 'Voice socket error';
    stopAudioCapture();
  });
};

const startSession = async () => {
  if (isActive.value || isBusy.value) {
    return;
  }
  if (!voiceEnabled.value) {
    errorMessage.value = 'Voice is disabled on the server';
    showToast('Voice disabled');
    return;
  }
  isBusy.value = true;
  errorMessage.value = '';
  status.value = 'connecting';
  try {
    transcripts.value = [];
    lastTranscriptRef.value = { role: '', text: '', ts: 0 };
    lastMainMessageRef.value = { role: '', text: '', ts: 0 };
    assistantMessageId.value = null;
    playbackCursorRef.value = 0;
    resetAudioGate();
    await startAudioCapture();
    openWebSocket();
    showToast('Voice mode active');
  } catch (error) {
    status.value = 'error';
    errorMessage.value = error.message || 'Failed to start voice mode';
    stopAudioCapture();
  } finally {
    isBusy.value = false;
  }
};

const stopSession = async ({ closePanel = false } = {}) => {
  if (wsRef.value && wsRef.value.readyState === WebSocket.OPEN) {
    wsRef.value.send(JSON.stringify({ type: 'stop' }));
    wsRef.value.close();
  }
  wsRef.value = null;
  stopAudioCapture();
  if (playbackContextRef.value) {
    playbackContextRef.value.close().catch(() => {});
    playbackContextRef.value = null;
  }
  playbackCursorRef.value = 0;
  resetAudioGate();
  isActive.value = false;
  status.value = 'idle';
  clientSpeechActiveRef.value = false;
  lastVoiceActivityRef.value = 0;
  if (closePanel) {
    isVoiceModeOpen.value = false;
    emit('close-voice-mode');
  }
};

const toggleSession = () => {
  if (isActive.value) {
    stopSession();
  } else {
    startSession();
  }
};

const fetchVoiceInfo = async () => {
    try {
        const response = await fetch('/api/voice/status');
        if (!response.ok) {
            return;
        }
        const data = await response.json();
        if (data.enabled === false) {
            voiceEnabled.value = false;
            errorMessage.value = data.message || 'Voice is disabled on the server';
            return;
        }
        if (data.selected_voice && data.selected_voice !== 'eve') {
            console.warn('Voice locked to eve; server returned', data.selected_voice);
        }
  } catch (error) {
    console.error(error);
  }
};

onMounted(async () => {
  await fetchVoiceInfo();
  if (voiceEnabled.value) {
    await startSession();
  }
});

onBeforeUnmount(() => {
  voiceModeLevel.value = 0;
  voiceModeStatus.value = 'idle';
  stopSession();
});

watch(selectedConversation, (value) => {
  if (value && pendingSaveRef.value) {
    saveMessagesHandler();
    pendingSaveRef.value = false;
  }
});
</script>

<style scoped lang="scss">
$bg-card: var(--vera-glass-strong);
$border: var(--vera-accent-soft);
$text-muted: var(--vera-text-muted);
$ok: var(--vera-success);
$warn: var(--vera-warning);
$danger: var(--vera-danger);

.voice-realtime {
  position: absolute;
  bottom: 90px;
  right: 20px;
  width: 320px;
  background: $bg-card;
  border: 1px solid $border;
  border-radius: 12px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  z-index: 3;
  display: none;
}

.voice-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.voice-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.875rem;
  color: $text-muted;
}

.voice-status {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.voice-status.listening { color: $ok; }
.voice-status.speaking { color: $warn; }
.voice-status.processing { color: $warn; }
.voice-status.connecting { color: $text-muted; }
.voice-status.error { color: $danger; }

.icon-button {
  background: transparent;
  border: none;
  color: $text-muted;
  cursor: pointer;
}

.voice-controls {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 0.75rem;
  color: $text-muted;
}

.voice-locked {
  display: flex;
  gap: 6px;
  align-items: baseline;
  font-size: 0.75rem;
  color: $text-muted;
}

.voice-locked strong {
  color: var(--vera-text);
  font-weight: 600;
}

.voice-lock {
  font-size: 0.6875rem;
  color: $text-muted;
}

.primary-btn {
  background: rgba(var(--vera-success-rgb), 0.8);
  border: none;
  color: var(--primary-color-text);
  border-radius: 8px;
  padding: 6px 10px;
  cursor: pointer;
}

.voice-transcripts {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 160px;
  overflow: auto;
  font-size: 0.75rem;
}

.transcript-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.transcript-role {
  text-transform: uppercase;
  font-size: 0.625rem;
  color: $text-muted;
}

.transcript-text {
  color: var(--vera-text);
}

.voice-error {
  color: $danger;
  font-size: 0.75rem;
}
</style>
