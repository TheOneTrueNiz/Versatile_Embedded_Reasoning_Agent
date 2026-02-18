<template>
  <div class="drawer model-config-drawer">
    <!-- Premium animated background layers -->
    <div class="bg-layer bg-neural">
      <svg class="neural-svg" viewBox="0 0 400 800" preserveAspectRatio="xMidYMid slice">
        <defs>
          <radialGradient id="nodeGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="var(--vera-accent-60)" />
            <stop offset="100%" stop-color="transparent" />
          </radialGradient>
        </defs>
        <!-- Neural network nodes -->
        <circle v-for="node in neuralNodes" :key="'node-'+node.id"
          :cx="node.x" :cy="node.y" :r="node.r"
          class="neural-node" :style="{ animationDelay: node.delay }" />
        <!-- Neural connections -->
        <line v-for="conn in neuralConnections" :key="'conn-'+conn.id"
          :x1="conn.x1" :y1="conn.y1" :x2="conn.x2" :y2="conn.y2"
          class="neural-conn" :style="{ animationDelay: conn.delay }" />
      </svg>
    </div>
    <div class="bg-layer bg-grid-pattern"></div>
    <div class="bg-layer bg-glow-spots">
      <span class="glow-spot spot-1"></span>
      <span class="glow-spot spot-2"></span>
    </div>

    <header class="drawer-header">
      <div class="drawer-title">
        <Bot size="18" />
        <div>
          <div class="drawer-title-text">Model Configuration</div>
          <div class="drawer-subtitle">{{ currentModelName }}</div>
        </div>
      </div>
      <button class="icon-btn" @click="$emit('close')" title="Close configuration">
        <X size="16" />
      </button>
    </header>

    <!-- Scrollable content area -->
    <div class="drawer-content">
      <!-- Model Selection Section -->
      <section class="drawer-card model-card">
        <div class="card-header">
          <Cpu size="16" />
          <span>Model Selection</span>
          <span class="pill">{{ availableModels.length }} available</span>
        </div>
        <div class="model-content">
          <div class="setting-row">
            <label class="setting-label">Active Model</label>
            <Dropdown
              v-model="localModelName"
              :options="availableModels"
              optionLabel="name"
              optionValue="id"
              placeholder="Select Model"
              class="model-dropdown"
              @change="onModelChange"
            />
          </div>
        </div>
      </section>

      <!-- Model Settings Section -->
      <section class="drawer-card settings-card">
        <div class="card-header">
          <SlidersHorizontal size="16" />
          <span>Model Settings</span>
        </div>
        <div class="settings-content">
          <div class="setting-row">
            <div class="setting-header">
              <label class="setting-label">Temperature</label>
              <span class="setting-value">{{ localTemperature.toFixed(2) }}</span>
            </div>
            <Slider v-model="localTemperature" :min="0" :max="2" :step="0.01" class="setting-slider" @change="onTemperatureChange" />
            <p class="setting-hint">Lower = more focused, Higher = more creative</p>
          </div>

          <div class="setting-row">
            <div class="setting-header">
              <label class="setting-label">Max Tokens</label>
              <span class="setting-value">{{ localMaxTokens }}</span>
            </div>
            <Slider v-model="localMaxTokens" :min="256" :max="128000" :step="256" class="setting-slider" @change="onMaxTokensChange" />
            <p class="setting-hint">Maximum response length</p>
          </div>

          <div class="setting-row">
            <div class="setting-header">
              <label class="setting-label">Top P</label>
              <span class="setting-value">{{ localTopP.toFixed(2) }}</span>
            </div>
            <Slider v-model="localTopP" :min="0" :max="1" :step="0.01" class="setting-slider" @change="onTopPChange" />
            <p class="setting-hint">Nucleus sampling threshold</p>
          </div>

          <div class="setting-row">
            <div class="setting-header">
              <label class="setting-label">Repetition Penalty</label>
              <span class="setting-value">{{ localRepetitionPenalty.toFixed(2) }}</span>
            </div>
            <Slider v-model="localRepetitionPenalty" :min="1" :max="2" :step="0.01" class="setting-slider" @change="onRepetitionPenaltyChange" />
            <p class="setting-hint">Discourages repetitive text</p>
          </div>

          <div class="setting-row">
            <div class="setting-header">
              <label class="setting-label">Presence Penalty</label>
              <span class="setting-value">{{ localPresencePenalty.toFixed(2) }}</span>
            </div>
            <Slider v-model="localPresencePenalty" :min="0" :max="2" :step="0.01" class="setting-slider" @change="onPresencePenaltyChange" />
            <p class="setting-hint">Encourages new topics</p>
          </div>
        </div>
      </section>

      <!-- Voice Agent Section -->
      <section class="drawer-card voice-card">
        <div class="card-header">
          <Mic size="16" />
          <span>Voice Agent</span>
          <span v-if="voiceStatus" :class="['pill', voiceStatusClass]">{{ voiceStatusLabel }}</span>
        </div>
        <div class="voice-content">
          <div class="setting-row">
            <label class="setting-label">Voice Persona</label>
            <div class="voice-options">
              <button
                v-for="voice in voiceOptions"
                :key="voice.value"
                class="voice-option"
                :class="{ active: voiceAgentVoice === voice.value }"
                @click="setVoiceAgentVoice(voice.value)"
              >
                {{ voice.label }}
              </button>
            </div>
          </div>

          <div class="setting-row">
            <div class="setting-header">
              <label class="setting-label">Audio Speed</label>
              <span class="setting-value">{{ localAudioSpeed.toFixed(2) }}x</span>
            </div>
            <Slider v-model="localAudioSpeed" :min="0.5" :max="2" :step="0.05" class="setting-slider" @change="onAudioSpeedChange" />
            <p class="setting-hint">Playback speed for voice responses</p>
          </div>

          <div class="setting-row">
            <div class="setting-header">
              <label class="setting-label">Whisper Temperature</label>
              <span class="setting-value">{{ localWhisperTemp.toFixed(2) }}</span>
            </div>
            <Slider v-model="localWhisperTemp" :min="0" :max="1" :step="0.05" class="setting-slider" @change="onWhisperTempChange" />
            <p class="setting-hint">Speech recognition sensitivity</p>
          </div>

          <div class="setting-row toggle-row">
            <div class="toggle-info">
              <label class="setting-label">Push to Talk</label>
              <p class="setting-hint">Hold button to speak</p>
            </div>
            <InputSwitch v-model="localPushToTalk" @change="onPushToTalkChange" />
          </div>

          <div class="setting-row toggle-row">
            <div class="toggle-info">
              <label class="setting-label">Use Whisper</label>
              <p class="setting-hint">OpenAI Whisper for transcription</p>
            </div>
            <InputSwitch v-model="localUseWhisper" @change="onUseWhisperChange" />
          </div>

          <div v-if="voiceStatus" class="voice-status-card">
            <div class="status-row">
              <span class="status-label">Backend</span>
              <span class="status-value">{{ voiceStatus.backend || 'Not configured' }}</span>
            </div>
            <div class="status-row">
              <span class="status-label">WebSockets</span>
              <span :class="['status-value', voiceStatus.websockets_available ? 'ok' : 'warn']">
                {{ voiceStatus.websockets_available ? 'Available' : 'Unavailable' }}
              </span>
            </div>
            <div class="status-row">
              <span class="status-label">API Key</span>
              <span :class="['status-value', voiceStatus.api_key_present ? 'ok' : 'warn']">
                {{ voiceStatus.api_key_present ? 'Configured' : 'Missing' }}
              </span>
            </div>
            <div v-if="voiceStatus.message" class="status-note">
              {{ voiceStatus.message }}
            </div>
          </div>

          <div class="voice-actions">
            <button class="secondary-btn" @click="fetchVoiceStatus">
              <RefreshCcw size="14" />
              <span>Refresh Status</span>
            </button>
          </div>
        </div>
      </section>

      <!-- Connection Info Section -->
      <section class="drawer-card connection-card">
        <div class="card-header">
          <Link size="16" />
          <span>Connection</span>
        </div>
        <div class="connection-content">
          <div class="connection-info">
            <div class="info-row">
              <span class="info-label">Endpoint</span>
              <span class="info-value endpoint">{{ localModelEndpoint || 'Not configured' }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">API Key</span>
              <span class="info-value">{{ localModelKey ? '••••••••' : 'Not set' }}</span>
            </div>
          </div>
          <button class="primary-btn" @click="openSettings">
            <Settings size="14" />
            <span>Configure in Settings</span>
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { Bot, X, Cpu, Mic, RefreshCcw, Link, Settings, SlidersHorizontal } from 'lucide-vue-next';
import Dropdown from 'primevue/dropdown';
import Slider from 'primevue/slider';
import InputSwitch from 'primevue/inputswitch';
import { showToast } from '@/libs/utils/general-utils';
import { handleUpdate } from '@/libs/utils/settings-utils';
import {
  availableModels,
  localModelName,
  localModelEndpoint,
  localModelKey,
  localSliderValue,
  maxTokens,
  top_P,
  repetitionPenalty,
  presencePenalty,
  voiceAgentVoice,
  audioSpeed,
  whisperTemperature,
  pushToTalkMode,
  useWhisper,
  isSidebarOpen
} from '@/libs/state-management/state';

const emit = defineEmits(['close']);

const voiceStatus = ref(null);

// Local refs for model settings (synced with state)
const localTemperature = ref(localSliderValue.value);
const localMaxTokens = ref(maxTokens.value);
const localTopP = ref(top_P.value);
const localRepetitionPenalty = ref(repetitionPenalty.value);
const localPresencePenalty = ref(presencePenalty.value);

// Local refs for voice settings
const localAudioSpeed = ref(audioSpeed.value);
const localWhisperTemp = ref(whisperTemperature.value);
const localPushToTalk = ref(pushToTalkMode.value);
const localUseWhisper = ref(useWhisper.value);

// Neural network background nodes
const neuralNodes = [
  { id: 1, x: 80, y: 100, r: 6, delay: '0s' },
  { id: 2, x: 200, y: 150, r: 8, delay: '0.5s' },
  { id: 3, x: 320, y: 100, r: 5, delay: '1s' },
  { id: 4, x: 100, y: 300, r: 7, delay: '1.5s' },
  { id: 5, x: 280, y: 350, r: 6, delay: '2s' },
  { id: 6, x: 160, y: 500, r: 8, delay: '2.5s' },
  { id: 7, x: 300, y: 550, r: 5, delay: '3s' },
  { id: 8, x: 80, y: 650, r: 6, delay: '3.5s' },
  { id: 9, x: 240, y: 700, r: 7, delay: '4s' },
];

const neuralConnections = [
  { id: 1, x1: 80, y1: 100, x2: 200, y2: 150, delay: '0.2s' },
  { id: 2, x1: 200, y1: 150, x2: 320, y2: 100, delay: '0.7s' },
  { id: 3, x1: 200, y1: 150, x2: 100, y2: 300, delay: '1.2s' },
  { id: 4, x1: 100, y1: 300, x2: 280, y2: 350, delay: '1.7s' },
  { id: 5, x1: 280, y1: 350, x2: 160, y2: 500, delay: '2.2s' },
  { id: 6, x1: 160, y1: 500, x2: 300, y2: 550, delay: '2.7s' },
  { id: 7, x1: 300, y1: 550, x2: 80, y2: 650, delay: '3.2s' },
  { id: 8, x1: 80, y1: 650, x2: 240, y2: 700, delay: '3.7s' },
];

const currentModelName = computed(() => {
  if (!localModelName.value) return 'No model selected';
  const model = availableModels.value.find(m => m.id === localModelName.value);
  return model?.name || localModelName.value;
});

const voiceOptions = computed(() => {
  const available = voiceStatus.value?.available_voices;
  const voices = Array.isArray(available) && available.length
    ? available
    : ['eve', 'ara', 'rex', 'sal', 'leo'];
  return voices.map((voice) => {
    const label = voice.charAt(0).toUpperCase() + voice.slice(1);
    return { label, value: voice };
  });
});

const voiceStatusLabel = computed(() => {
  if (!voiceStatus.value) return 'unknown';
  if (!voiceStatus.value.enabled) return 'disabled';
  if (voiceStatus.value.backend_ready && voiceStatus.value.websockets_available && voiceStatus.value.api_key_present) {
    return 'ready';
  }
  return 'degraded';
});

const voiceStatusClass = computed(() => {
  const label = voiceStatusLabel.value;
  if (label === 'ready') return 'ok';
  if (label === 'degraded') return 'warn';
  return 'muted';
});

// Model change handlers
const onModelChange = (event) => {
  handleUpdate('localModelName', event.value);
};

const onTemperatureChange = () => {
  handleUpdate('localSliderValue', localTemperature.value);
  localStorage.setItem('local-attitude', localTemperature.value);
};

const onMaxTokensChange = () => {
  handleUpdate('maxTokens', localMaxTokens.value);
  localStorage.setItem('maxTokens', localMaxTokens.value);
};

const onTopPChange = () => {
  handleUpdate('top_P', localTopP.value);
  localStorage.setItem('top_P', localTopP.value);
};

const onRepetitionPenaltyChange = () => {
  handleUpdate('repetitionPenalty', localRepetitionPenalty.value);
  localStorage.setItem('repetitionPenalty', localRepetitionPenalty.value);
};

const onPresencePenaltyChange = () => {
  handleUpdate('presencePenalty', localPresencePenalty.value);
  localStorage.setItem('presencePenalty', localPresencePenalty.value);
};

// Voice change handlers
const setVoiceAgentVoice = (voice) => {
  voiceAgentVoice.value = voice;
  localStorage.setItem('voice-agent-voice', voice);
};

const onAudioSpeedChange = () => {
  audioSpeed.value = localAudioSpeed.value;
  localStorage.setItem('audio-speed', localAudioSpeed.value);
};

const onWhisperTempChange = () => {
  whisperTemperature.value = localWhisperTemp.value;
  localStorage.setItem('whisper-temperature', localWhisperTemp.value);
};

const onPushToTalkChange = () => {
  pushToTalkMode.value = localPushToTalk.value;
  localStorage.setItem('use-push-to-talk', JSON.stringify(localPushToTalk.value));
};

const onUseWhisperChange = () => {
  useWhisper.value = localUseWhisper.value;
  localStorage.setItem('use-whisper', JSON.stringify(localUseWhisper.value));
};

const fetchVoiceStatus = async () => {
  try {
    const response = await fetch('/api/voice/status');
    if (!response.ok) {
      throw new Error('Failed to fetch voice status');
    }
    voiceStatus.value = await response.json();
  } catch (error) {
    showToast('Unable to fetch voice status');
    console.error(error);
  }
};

const openSettings = () => {
  isSidebarOpen.value = true;
  emit('close');
};

onMounted(fetchVoiceStatus);
</script>

<style lang="scss" scoped>
// ============================================
// VERA Model Config Drawer - Cool Spectrum Glass
// Cyan/violet accents for unified UI
// ============================================

$vera-cyan: var(--vera-accent);
$vera-violet: var(--vera-secondary);
$vera-glass-bg: var(--vera-drawer-bg);
$vera-glass-border: var(--vera-accent-12);

.model-config-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--vera-drawer-bg);
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(16px);
}

// Background layers
.bg-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.bg-neural {
  opacity: 0.35;

  .neural-svg {
    width: 100%;
    height: 100%;
  }

  .neural-node {
    fill: url(#nodeGlow);
    animation: nodePulse 4s ease-in-out infinite;
  }

  .neural-conn {
    stroke: var(--vera-accent-12);
    stroke-width: 1;
    animation: connPulse 3s ease-in-out infinite;
  }
}

@keyframes nodePulse {
  0%, 100% { opacity: 0.3; transform: scale(1); }
  50% { opacity: 0.8; transform: scale(1.2); }
}

@keyframes connPulse {
  0%, 100% { opacity: 0.1; }
  50% { opacity: 0.4; }
}

.bg-grid-pattern {
  background-image:
    linear-gradient(var(--vera-accent-05) 1px, transparent 1px),
    linear-gradient(90deg, var(--vera-accent-05) 1px, transparent 1px);
  background-size: 24px 24px;
}

.bg-glow-spots {
  .glow-spot {
    position: absolute;
    border-radius: 50%;
    filter: blur(60px);
    animation: glowFloat 10s ease-in-out infinite;

    &.spot-1 {
      width: 200px;
      height: 200px;
      background: var(--vera-accent-08);
      top: 10%;
      left: -50px;
    }

    &.spot-2 {
      width: 150px;
      height: 150px;
      background: var(--vera-secondary-05);
      bottom: 20%;
      right: -40px;
      animation-delay: 5s;
    }
  }
}

@keyframes glowFloat {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(20px, 20px); }
}

// Header
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid $vera-glass-border;
  position: relative;
  z-index: 2;
  background: color-mix(in srgb, var(--vera-panel) 60%, transparent);

  // Top accent glow
  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: 15%;
    right: 15%;
    height: 1px;
    background: linear-gradient(90deg,
      transparent,
      var(--vera-accent-30),
      $vera-cyan,
      var(--vera-accent-30),
      transparent);
    box-shadow: 0 0 8px var(--vera-accent-20);
  }
}

.drawer-title {
  display: flex;
  align-items: center;
  gap: 12px;
  color: $vera-cyan;

  svg {
    opacity: 0.9;
    filter: drop-shadow(0 0 4px var(--vera-accent-40));
  }
}

.drawer-title-text {
  font-size: 0.9375rem;
  font-weight: 600;
  color: $vera-cyan;
  text-shadow: 0 0 8px var(--vera-accent-30);
}

.drawer-subtitle {
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  margin-top: 2px;
}

.icon-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid $vera-glass-border;
  background: color-mix(in srgb, var(--vera-panel) 60%, transparent);
  color: var(--vera-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-30);
    color: $vera-cyan;
    background: var(--vera-accent-10);
    box-shadow: 0 0 12px var(--vera-accent-10);
  }
}

// Cards
.drawer-card {
  margin: 16px;
  background: var(--vera-drawer-card-bg);
  border: 1px solid $vera-glass-border;
  border-radius: 16px;
  backdrop-filter: blur(16px);
  overflow: hidden;
  position: relative;
  z-index: 2;
  transition: all 0.3s ease;

  &:hover {
    border-color: var(--vera-accent-20);
    box-shadow: 0 0 25px var(--vera-accent-06);
  }
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
  border-bottom: 1px solid $vera-glass-border;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--vera-text);

  svg {
    color: $vera-cyan;
    opacity: 0.9;
    filter: drop-shadow(0 0 3px var(--vera-accent-40));
  }

  .pill {
    margin-left: auto;
    padding: 3px 8px;
    font-size: 0.625rem;
    font-weight: 500;
    border-radius: 20px;
    background: var(--vera-accent-12);
    color: $vera-cyan;

    &.ok {
      background: var(--vera-success-15);
      color: var(--vera-status-success);
    }

    &.warn {
      background: var(--vera-warning-15);
      color: var(--vera-status-warning);
    }

    &.muted {
      background: var(--vera-black-15);
      color: var(--vera-text-muted);
    }
  }
}

// Model Section
.model-content {
  padding: 16px;
}

.current-model {
  margin-bottom: 16px;
}

.model-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: linear-gradient(135deg, var(--vera-accent-12), var(--vera-accent-04));
  border: 1px solid var(--vera-accent-25);
  border-radius: 20px;

  .model-status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: $vera-cyan;
    box-shadow: 0 0 8px $vera-cyan;
    animation: dotPulse 2s ease-in-out infinite;
  }

  .model-name {
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--vera-text);
  }
}

@keyframes dotPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.model-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 200px;
  overflow-y: auto;
  padding-right: 8px;

  &::-webkit-scrollbar {
    width: 4px;
  }

  &::-webkit-scrollbar-track {
    background: transparent;
  }

  &::-webkit-scrollbar-thumb {
    background: var(--vera-accent-20);
    border-radius: 4px;
  }
}

.model-option {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
  border: 1px solid $vera-glass-border;
  border-radius: 10px;
  text-align: left;
  cursor: pointer;
  transition: all 0.25s ease;

  &:hover {
    border-color: var(--vera-accent-25);
    background: var(--vera-accent-05);
  }

  &.active {
    border-color: var(--vera-accent-35);
    background: linear-gradient(135deg, var(--vera-accent-12), var(--vera-accent-04));
    box-shadow: 0 0 16px var(--vera-accent-08);

    .model-option-name {
      color: $vera-cyan;
    }
  }

  .model-option-name {
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--vera-text);
  }

  .model-option-desc {
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
  }
}

// Voice Section
.voice-content {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.voice-setting {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.voice-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--vera-text);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.voice-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.voice-option {
  padding: 8px 14px;
  font-size: 0.75rem;
  font-weight: 500;
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
  border: 1px solid $vera-glass-border;
  border-radius: 8px;
  color: var(--vera-text-muted);
  cursor: pointer;
  transition: all 0.25s ease;

  &:hover {
    border-color: var(--vera-accent-25);
    color: var(--vera-text);
  }

  &.active {
    border-color: var(--vera-accent-35);
    background: linear-gradient(135deg, var(--vera-accent-15), var(--vera-accent-06));
    color: $vera-cyan;
    box-shadow: 0 0 12px var(--vera-accent-10);
  }
}

.voice-hint {
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  margin: 0;
}

.voice-status-card {
  padding: 12px;
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
  border: 1px solid $vera-glass-border;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.status-label {
  font-size: 0.75rem;
  color: var(--vera-text-muted);
}

.status-value {
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--vera-text);

  &.ok {
    color: var(--vera-status-success);
  }

  &.warn {
    color: var(--vera-status-warning);
  }
}

.status-note {
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  padding-top: 8px;
  border-top: 1px solid var(--vera-border);
}

.voice-actions {
  display: flex;
  gap: 8px;
}

// Connection Section
.connection-content {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.connection-info {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.info-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--vera-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.info-value {
  font-size: 0.8125rem;
  color: var(--vera-text);

  &.endpoint {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.6875rem;
    color: var(--vera-accent);
    word-break: break-all;
  }
}

// Buttons
.primary-btn,
.secondary-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 16px;
  font-size: 0.75rem;
  font-weight: 500;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.25s ease;
}

.primary-btn {
  background: linear-gradient(135deg, var(--vera-accent-20), var(--vera-accent-08));
  border: 1px solid var(--vera-accent-35);
  color: $vera-cyan;

  &:hover {
    background: linear-gradient(135deg, var(--vera-accent-30), var(--vera-accent-12));
    box-shadow: 0 0 20px var(--vera-accent-15);
  }
}

.secondary-btn {
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
  border: 1px solid $vera-glass-border;
  color: var(--vera-text-muted);

  &:hover {
    border-color: var(--vera-accent-25);
    color: $vera-cyan;
    background: var(--vera-accent-08);
  }
}

// Scrollable content area
.drawer-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  position: relative;
  z-index: 2;
  padding-bottom: 20px;

  &::-webkit-scrollbar {
    width: 6px;
  }

  &::-webkit-scrollbar-track {
    background: var(--vera-accent-02);
    border-radius: 3px;
  }

  &::-webkit-scrollbar-thumb {
    background: var(--vera-accent-15);
    border-radius: 3px;

    &:hover {
      background: var(--vera-accent-25);
    }
  }
}

// Settings content
.settings-content {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

// Setting row
.setting-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.setting-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.setting-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--vera-text);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.setting-value {
  font-size: 0.75rem;
  font-weight: 600;
  color: $vera-cyan;
  font-family: 'JetBrains Mono', monospace;
  text-shadow: 0 0 6px var(--vera-accent-30);
}

.setting-hint {
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  margin: 0;
  margin-top: 2px;
}

// Toggle row (for switches)
.toggle-row {
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-top: 1px solid var(--vera-border);

  &:first-of-type {
    border-top: none;
    padding-top: 0;
  }

  .toggle-info {
    display: flex;
    flex-direction: column;
    gap: 2px;

    .setting-label {
      text-transform: none;
    }

    .setting-hint {
      margin-top: 0;
    }
  }
}

// PrimeVue Dropdown styling
.model-dropdown {
  width: 100%;

  :deep(.p-dropdown) {
    width: 100%;
    background: color-mix(in srgb, var(--vera-panel) 60%, transparent);
    border: 1px solid $vera-glass-border;
    border-radius: 10px;
    transition: all 0.25s ease;

    &:hover {
      border-color: var(--vera-accent-25);
    }

    &.p-focus,
    &:focus {
      border-color: var(--vera-accent-40);
      box-shadow: 0 0 0 2px var(--vera-accent-08);
    }

    .p-dropdown-label {
      color: var(--vera-text);
      font-size: 0.8125rem;
      font-weight: 500;
      padding: 10px 14px;
    }

    .p-dropdown-trigger {
      color: var(--vera-text-muted);
      width: 36px;
    }
  }

  :deep(.p-dropdown-panel) {
    background: color-mix(in srgb, var(--vera-panel) 98%, transparent);
    border: 1px solid var(--vera-accent-15);
    border-radius: 10px;
    backdrop-filter: blur(16px);
    box-shadow: 0 8px 32px rgba(var(--vera-shadow-rgb), 0.4);

    .p-dropdown-items {
      padding: 6px;

      .p-dropdown-item {
        padding: 10px 12px;
        border-radius: 6px;
        color: var(--vera-text);
        font-size: 0.8125rem;
        transition: all 0.2s ease;

        &:hover {
          background: var(--vera-accent-08);
        }

        &.p-highlight {
          background: linear-gradient(135deg, var(--vera-accent-15), var(--vera-accent-06));
          color: $vera-cyan;
        }
      }
    }
  }
}

// PrimeVue Slider styling
.setting-slider {
  width: 100%;

  :deep(.p-slider) {
    background: var(--vera-accent-10);
    border-radius: 4px;
    height: 6px;

    .p-slider-range {
      background: linear-gradient(90deg, $vera-cyan, var(--vera-accent-60));
      border-radius: 4px;
    }

    .p-slider-handle {
      width: 16px;
      height: 16px;
      background: $vera-cyan;
      border: 2px solid color-mix(in srgb, var(--vera-panel) 90%, transparent);
      border-radius: 50%;
      box-shadow: 0 0 10px var(--vera-accent-40);
      transition: all 0.2s ease;

      &:hover {
        transform: scale(1.15);
        box-shadow: 0 0 16px var(--vera-accent-60);
      }

      &:focus {
        box-shadow: 0 0 0 3px var(--vera-accent-12), 0 0 16px var(--vera-accent-50);
      }
    }
  }
}

// PrimeVue InputSwitch styling
:deep(.p-inputswitch) {
  width: 44px;
  height: 24px;

  .p-inputswitch-slider {
    background: color-mix(in srgb, var(--vera-text-muted) 30%, transparent);
    border-radius: 12px;
    transition: all 0.25s ease;

    &::before {
      width: 18px;
      height: 18px;
      background: rgba(var(--vera-contrast-rgb), 0.7);
      border-radius: 50%;
      margin-top: -9px;
      left: 3px;
      transition: all 0.25s ease;
    }
  }

  &.p-inputswitch-checked {
    .p-inputswitch-slider {
      background: linear-gradient(135deg, $vera-cyan, var(--vera-accent-70));

      &::before {
        transform: translateX(20px);
        background: rgb(var(--vera-contrast-rgb));
        box-shadow: 0 0 8px var(--vera-accent-50);
      }
    }
  }

  &:hover .p-inputswitch-slider {
    background: color-mix(in srgb, var(--vera-text-muted) 40%, transparent);
  }

  &.p-inputswitch-checked:hover .p-inputswitch-slider {
    background: linear-gradient(135deg, $vera-cyan, var(--vera-accent-85));
  }
}
</style>
