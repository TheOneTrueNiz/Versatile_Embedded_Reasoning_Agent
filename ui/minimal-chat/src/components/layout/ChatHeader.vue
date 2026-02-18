<!-- eslint-disable no-unused-vars -->

<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue';
import { Menu } from 'lucide-vue-next';
import {
  isSidebarOpen,
  showConversationOptions,
  showStoredFiles,
  availableModels,
  localModelName,
  isLoading,
  pendingQuorumMode,
  streamedMessageText,
  a11ySoundEffects,
  a11yAutoPlayMedia
} from '@/libs/state-management/state';
import ContextWindow from '@/components/controls/ContextWindow.vue';
import ConfirmationDialog from '@/components/controls/ConfirmationDialog.vue';
import Dropdown from 'primevue/dropdown';
import { update } from '@/libs/utils/settings-utils';
import { determineModelDisplayName } from '@/libs/utils/general-utils';
import VeraLogo from '@/components/controls/VeraLogo.vue';

// Wing state management
const hasBooted = ref(false);
const bootPhase = ref(0); // 0: not started, 1: booting, 2: complete

// Advanced state tracking
const isStreaming = ref(false);
const showSuccess = ref(false);
const showError = ref(false);
const tokenRate = ref(1); // Multiplier for animation speed (0.5 = slow, 2 = fast)

// Token rate calculation
let lastStreamLength = 0;
let lastStreamTime = Date.now();
let tokenRateInterval = null;

// Startup boot sequence
onMounted(() => {
  // Small delay to ensure DOM is ready
  setTimeout(() => {
    bootPhase.value = 1; // Start boot animation
    setTimeout(() => {
      bootPhase.value = 2; // Boot complete, transition to idle
      hasBooted.value = true;
    }, 2000); // Boot animation duration
  }, 100);

  // Token rate calculation interval
  tokenRateInterval = setInterval(() => {
    if (isStreaming.value && streamedMessageText.value) {
      const now = Date.now();
      const timeDelta = (now - lastStreamTime) / 1000; // seconds
      const charDelta = streamedMessageText.value.length - lastStreamLength;

      if (timeDelta > 0) {
        // Rough estimate: ~4 chars per token
        const tokensPerSecond = (charDelta / 4) / timeDelta;
        // Normalize to 0.5-2.0 range (10 tok/s = 0.5, 50 tok/s = 1.0, 100+ tok/s = 2.0)
        tokenRate.value = Math.min(2, Math.max(0.5, tokensPerSecond / 50));
      }

      lastStreamLength = streamedMessageText.value.length;
      lastStreamTime = now;
    }
  }, 200);
});

onUnmounted(() => {
  if (tokenRateInterval) {
    clearInterval(tokenRateInterval);
  }
});

// Watch for streaming state changes
watch(streamedMessageText, (newVal, oldVal) => {
  if (isLoading.value && newVal && newVal.length > (oldVal?.length || 0)) {
    isStreaming.value = true;
  }
});

// Watch for loading state transitions (success/error detection)
let wasLoading = false;
watch(isLoading, (newVal) => {
  if (wasLoading && !newVal) {
    // Loading just finished
    if (streamedMessageText.value && streamedMessageText.value.length > 0) {
      // Success - we got a response
      showSuccess.value = true;
      setTimeout(() => {
        showSuccess.value = false;
      }, 1500);
    }
    // Reset streaming state
    isStreaming.value = false;
    lastStreamLength = 0;
    tokenRate.value = 1;
  }
  wasLoading = newVal;
});

// Error detection - listen for error events on window
onMounted(() => {
  const handleError = (event) => {
    if (event.detail?.type === 'api_error' || event.detail?.type === 'stream_error') {
      showError.value = true;
      setTimeout(() => {
        showError.value = false;
      }, 2000);
    }
  };
  window.addEventListener('vera-error', handleError);

  // Cleanup
  onUnmounted(() => {
    window.removeEventListener('vera-error', handleError);
  });
});

// Computed wing state based on app state (priority order matters!)
const wingState = computed(() => {
  if (!hasBooted.value) return 'boot';
  if (showError.value) return 'error';
  if (showSuccess.value) return 'success';
  if (pendingQuorumMode.value === 'swarm') return 'swarm';
  if (pendingQuorumMode.value === 'quorum') return 'quorum';
  if (isStreaming.value) return 'streaming';
  if (isLoading.value) return 'thinking';
  return 'idle';
});

// CSS variable for token rate (used in animations)
const tokenRateStyle = computed(() => ({
  '--wing-token-rate': tokenRate.value
}));

const logoReady = ref(false);
const logoFailed = ref(false);

const showRiveLogo = computed(() => logoReady.value && !logoFailed.value);

const logoState = computed(() => {
  if (wingState.value === 'error') return 'error';
  // Only show quorum/swarm aperture when actually loading/processing
  // Not just when queued (pendingQuorumMode set but not yet loading)
  if (isLoading.value || isStreaming.value) {
    if (pendingQuorumMode.value === 'quorum') return 'quorum';
    if (pendingQuorumMode.value === 'swarm') return 'swarm';
    // Default thinking state when loading without quorum/swarm
    return 'swarm';
  }
  if (wingState.value === 'success') return 'quorum';
  return 'idle';
});

const logoIntensity = computed(() => {
  if (logoState.value === 'swarm') return Math.min(1, tokenRate.value / 2);
  if (logoState.value === 'quorum') return Math.min(1, tokenRate.value / 2);
  return 0;
});

const logoPulse = computed(() => {
  if (logoState.value !== 'quorum') return 0;
  return Math.min(1, tokenRate.value / 2);
});

const logoSoundEnabled = computed(() => a11ySoundEffects.value && a11yAutoPlayMedia.value);

const handleLogoReady = () => {
  logoReady.value = true;
  logoFailed.value = false;
};

const handleLogoError = () => {
  logoFailed.value = true;
  logoReady.value = false;
};

// Define props
const props = defineProps({
  storedConversations: Array,
});

const contextWindow = ref(null);
const isShuttingDown = ref(false);
const shutdownStage = ref('idle');
const autoCloseNext = ref(false);
const showExitConfirm = ref(false);

try {
  autoCloseNext.value = window.localStorage.getItem('veraAutoClose') === '1';
} catch (error) {
  autoCloseNext.value = false;
}

const emit = defineEmits([
  'toggle-sidebar',
  'toggle-conversations',
  'delete-conversation',
  'new-conversation',
  'change-model'
]);

function toggleSidebar() {
  event.stopPropagation();
  isSidebarOpen.value = !isSidebarOpen.value;
}

function clearMessages() {
  // Implement message clearing logic
  emit('new-conversation');
}

function onShowConversationsClick() {
  event.stopPropagation();
  showConversationOptions.value = !showConversationOptions.value;
}

function handleUpdate(field, value) {
  update(field, value);
}


function attemptCloseTab() {
  try {
    window.open('', '_self');
    window.close();
  } catch (error) {
    console.error('Window close failed:', error);
  }
}

async function requestShutdown() {
  if (isShuttingDown.value) {
    return;
  }
  showExitConfirm.value = false;
  isShuttingDown.value = true;
  shutdownStage.value = 'working';
  try {
    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), 1500);
    fetch('/api/exit', { method: 'POST', signal: controller.signal, keepalive: true })
      .catch((error) => {
        console.error('Shutdown request failed:', error);
      })
      .finally(() => {
        clearTimeout(abortTimer);
      });
  } catch (error) {
    console.error('Shutdown request failed:', error);
  }
  setTimeout(() => {
    shutdownStage.value = 'ready';
    if (autoCloseNext.value) {
      attemptCloseTab();
    }
  }, 5000);
}

function promptShutdown() {
  if (isShuttingDown.value) {
    return;
  }
  showExitConfirm.value = true;
}

watch(autoCloseNext, (value) => {
  try {
    window.localStorage.setItem('veraAutoClose', value ? '1' : '0');
  } catch (error) {
    console.error('Failed to persist auto-close preference:', error);
  }
});
</script>

<template>
  <div class="header">
    <!-- Header background image layer -->
    <div class="header-bg-image" aria-hidden="true"></div>

    <!-- Desktop View -->
    <div class="header-content desktop-only">
      <div class="app-title">
        <div class="vera-brand" :class="[`wing-state-${wingState}`, { 'boot-phase-1': bootPhase === 1, 'boot-phase-2': bootPhase === 2 }]" :style="tokenRateStyle">
          <span class="vera-glow"></span>
          <!-- Left wing -->
          <div class="vera-wing wing-left">
            <div class="wing-line"></div>
            <div class="wing-pulse"></div>
            <div class="wing-pulse pulse-2"></div>
            <div class="wing-node node-1"></div>
            <div class="wing-node node-2"></div>
            <div class="wing-terminus"></div>
          </div>
          <div class="vera-logo-stack">
            <VeraLogo
              class="vera-logo"
              :status="logoState"
              :intensity="logoIntensity"
              :speech-pulse="logoPulse"
              :sound-enabled="logoSoundEnabled"
              :width="180"
              :height="48"
              @ready="handleLogoReady"
              @error="handleLogoError"
            />
            <h1 class="vera-text" :class="{ 'is-hidden': showRiveLogo }">VERA</h1>
            <!-- Holographic scanlines -->
            <div class="vera-scanlines">
              <div class="scanline-sweep"></div>
              <div class="scanline-grid"></div>
            </div>
            <!-- Holographic glitch layers -->
            <div class="vera-holo-glitch">
              <span class="holo-layer holo-r">VERA</span>
              <span class="holo-layer holo-g">VERA</span>
              <span class="holo-layer holo-b">VERA</span>
            </div>
          </div>
          <!-- Right wing -->
          <div class="vera-wing wing-right">
            <div class="wing-line"></div>
            <div class="wing-pulse"></div>
            <div class="wing-pulse pulse-2"></div>
            <div class="wing-node node-1"></div>
            <div class="wing-node node-2"></div>
            <div class="wing-terminus"></div>
          </div>
          <!-- Particle field -->
          <div class="vera-particles">
            <span v-for="n in 20" :key="n" class="particle" :class="`p-${n}`"></span>
          </div>
          <!-- Electric arcs between nodes -->
          <svg class="vera-arcs" viewBox="0 0 400 60" preserveAspectRatio="none">
            <path class="arc arc-left-1" d="M 80 30 Q 100 15, 120 30" />
            <path class="arc arc-left-2" d="M 60 30 Q 75 40, 90 30" />
            <path class="arc arc-right-1" d="M 280 30 Q 300 15, 320 30" />
            <path class="arc arc-right-2" d="M 310 30 Q 325 40, 340 30" />
          </svg>
          <!-- Data cascade streams -->
          <div class="vera-data-cascade">
            <div class="data-stream stream-left">
              <span v-for="n in 8" :key="`dl-${n}`" class="data-bit" :class="`bit-${n}`">{{ n % 2 }}</span>
            </div>
            <div class="data-stream stream-right">
              <span v-for="n in 8" :key="`dr-${n}`" class="data-bit" :class="`bit-${n}`">{{ (n + 1) % 2 }}</span>
            </div>
          </div>
        </div>
      </div>

    </div>

    <!-- Mobile View -->
    <div class="header-content mobile-only">
      <div class="header-left">
        <button class="action-btn" @click="toggleSidebar">
          <Menu size="24" />
        </button>
      </div>
      
      <div class="header-center">
        <h1 class="app-title-mobile">VERA</h1>
      </div>
      
      <div class="header-right">
        <div class="context-action">
          <ContextWindow ref="contextWindow" />
        </div>
      </div>
    </div>
    <Teleport to="body">
      <div v-if="isShuttingDown" class="shutdown-overlay">
        <div class="shutdown-card">
          <div v-if="shutdownStage === 'working'" class="shutdown-stage">
            <div class="spinner"></div>
            <div class="shutdown-title">Shutting down</div>
            <div class="shutdown-subtitle">Excuse me while I clean things up a bit before I go.</div>
            <div class="shutdown-hint">One moment, please.</div>
          </div>
          <div v-else class="shutdown-stage">
            <div class="shutdown-title">Cleanup complete</div>
            <div class="shutdown-subtitle">You may now close this browser tab.</div>
            <label class="shutdown-toggle">
              <input type="checkbox" v-model="autoCloseNext" />
              <span>Auto-close after shutdown next time</span>
            </label>
            <div class="shutdown-actions">
              <button class="shutdown-btn" @click="attemptCloseTab">Close tab</button>
              <button class="shutdown-btn secondary" @click="isShuttingDown = false">Stay open</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
    <Teleport to="body">
      <ConfirmationDialog
        v-model:visible="showExitConfirm"
        title="Exit VERA?"
        message="Exit Vera and shut down services?"
        confirmLabel="Exit"
        cancelLabel="Cancel"
        :isWarning="true"
        @confirm="requestShutdown"
      />
    </Teleport>
  </div>
</template>

<style lang="scss" scoped>
// Variables
$primary-color: var(--vera-accent);
$primary-dark: var(--vera-accent-strong);
$primary-light: var(--vera-accent-strong);
$background-dark: var(--vera-surface);
$background-header: var(--vera-header-bg);
$header-border: var(--vera-glass-border);
$icon-color: var(--vera-icon);
$text-color: var(--vera-text);
$transition-speed: 0.2s;
$border-radius: 8px;
$overlay-bg: rgba(var(--vera-shadow-rgb), 0.65);
$card-bg: var(--vera-panel-alt);
$card-border: var(--vera-border);
$spinner-bg: var(--vera-accent-soft);
$spinner-fg: var(--vera-accent-strong);

// Desktop/Mobile display helpers
.desktop-only {
  @media (max-width: 600px) {
    display: none !important;
  }
}

.mobile-only {
  display: none !important;
  
  @media (max-width: 600px) {
    display: flex !important;
  }
}

// Header styling
.header {
  background: $background-header;
  width: 100%;
  height: 60px;
  min-height: 60px;
  flex: 0 0 auto;
  position: relative;
  z-index: 1;
  backdrop-filter: blur(var(--vera-header-blur));
  font-family: var(--vera-font-header);
  color: var(--vera-text-header);
  overflow: hidden; // Clip the background image layer

  // Background image layer (lowest z-index)
  .header-bg-image {
    position: absolute;
    inset: 0;
    background-image: var(--vera-header-image, none);
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    opacity: var(--vera-header-image-opacity, 0.25);
    filter: blur(var(--vera-header-image-blur, 6px));
    pointer-events: none;
    z-index: 0;
  }

  // Layered glass effect
  &::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
      radial-gradient(ellipse 80% 50% at 20% 0%, var(--vera-accent-faint), transparent 50%),
      radial-gradient(ellipse 60% 40% at 80% 0%, var(--vera-accent-faint), transparent 45%),
      linear-gradient(180deg, rgba(var(--vera-contrast-rgb), 0.03) 0%, transparent 100%);
    pointer-events: none;
    z-index: 1;
  }

  // Top edge highlight
  &::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 1px;
    background: linear-gradient(90deg,
      transparent 0%,
      rgba(var(--vera-contrast-rgb), 0.1) 20%,
      rgba(var(--vera-contrast-rgb), 0.2) 50%,
      rgba(var(--vera-contrast-rgb), 0.1) 80%,
      transparent 100%
    );
    pointer-events: none;
  }

  // Bottom accent border
  border-bottom: 1px solid transparent;
  border-image: linear-gradient(90deg,
    transparent 0%,
    var(--vera-accent-faint) 15%,
    var(--vera-accent-soft) 50%,
    var(--vera-accent-faint) 85%,
    transparent 100%
  ) 1;
  box-shadow:
    0 8px 32px rgba(var(--vera-shadow-rgb), 0.4),
    0 2px 8px rgba(var(--vera-shadow-rgb), 0.2),
    inset 0 -1px 0 rgba(var(--vera-shadow-rgb), 0.2);
}

.shutdown-overlay {
  position: fixed;
  inset: 0;
  background: $overlay-bg;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(3px);
}

.shutdown-card {
  background: var(--vera-glass-strong);
  border: 1px solid var(--vera-glass-border);
  border-radius: 12px;
  padding: 24px 28px;
  width: min(420px, 90vw);
  text-align: center;
  color: $text-color;
  box-shadow: 0 18px 40px rgba(var(--vera-shadow-rgb), 0.4);
}

.shutdown-stage {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.shutdown-title {
  font-size: 1.25rem;
  font-weight: 600;
  margin-top: 12px;
}

.shutdown-subtitle {
  margin-top: 8px;
  color: var(--vera-text);
  line-height: 1.4;
}

.shutdown-hint {
  margin-top: 12px;
  font-size: 0.8125rem;
  color: var(--vera-text-muted);
}

.shutdown-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
  font-size: 0.8125rem;
  color: var(--vera-text);

  input {
    width: 16px;
    height: 16px;
    accent-color: $primary-light;
  }
}

.shutdown-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 12px;
}

.shutdown-btn {
  background: $primary-color;
  border: none;
  border-radius: 6px;
  color: $text-color;
  padding: 8px 14px;
  font-size: 0.8125rem;
  cursor: pointer;
  transition: background $transition-speed ease;

  &:hover {
    background: $primary-light;
  }

  &.secondary {
    background: transparent;
    border: 1px solid var(--vera-accent-soft);
    color: var(--vera-text);

    &:hover {
      background: var(--vera-accent-faint);
    }
  }
}

.spinner {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 3px solid $spinner-bg;
  border-top-color: $spinner-fg;
  margin: 0 auto;
  animation: spin calc(0.9s / var(--vera-anim-speed, 1)) linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

// Desktop header
.header-content {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  height: 60px;
  padding: 0 20px;
  position: relative;
  z-index: 2; // Above background image layer
  gap: 8px;

  @media (max-width: 900px) {
    padding: 0 12px;
    gap: 4px;
  }

  &.desktop-only {
    .model-selectors {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }

    .app-title {
      // Use fixed positioning to center logo relative to viewport, not header
      position: fixed;
      left: 50%;
      transform: translateX(-50%);
      top: 0;
      height: 60px;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 10;
      pointer-events: none; // Allow clicks to pass through to header below

      .vera-brand {
        pointer-events: auto; // Re-enable interactions on the logo itself
      }
    }
  }
}

// VERA Brand styling
.vera-brand {
  --brand-padding: 20px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 var(--brand-padding);
  flex-shrink: 0;

  @media (max-width: 750px) {
    --brand-padding: 8px;
  }

  .vera-glow {
    position: absolute;
    width: 120px;
    height: 40px;
    background: radial-gradient(ellipse, var(--vera-accent-soft) 0%, transparent 70%);
    filter: blur(12px);
    opacity: 0.6;
    animation: veraBrandPulse calc(4s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    pointer-events: none;
  }

  .vera-text {
    margin: 0;
    font-size: clamp(18px, 2.8vw, 26px);
    font-weight: 700;
    letter-spacing: 6px;
    text-transform: uppercase;
    background: linear-gradient(
      135deg,
      var(--vera-text) 0%,
      var(--vera-accent-strong) 40%,
      var(--vera-accent) 60%,
      var(--vera-text) 100%
    );
    background-size: 200% 200%;
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: veraTextShimmer calc(8s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    position: relative;
    text-shadow: 0 0 30px var(--vera-accent-faint);

    &::after {
      content: 'VERA';
      position: absolute;
      inset: 0;
      background: inherit;
      -webkit-background-clip: text;
      background-clip: text;
      -webkit-text-fill-color: transparent;
      filter: blur(8px);
      opacity: 0.5;
      z-index: -1;
    }
  }
}

.vera-logo-stack {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: clamp(150px, 18vw, 220px);
  height: 48px;
}

.vera-logo {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.vera-text.is-hidden {
  opacity: 0;
}

.vera-logo:not(.is-hidden) {
  opacity: 1;
}

@keyframes veraBrandPulse {
  0%, 100% {
    opacity: 0.4;
    transform: scale(1);
  }
  50% {
    opacity: 0.7;
    transform: scale(1.1);
  }
}

@keyframes veraTextShimmer {
  0%, 100% {
    background-position: 0% 50%;
  }
  50% {
    background-position: 100% 50%;
  }
}

// Cyberpunk wing styling
.vera-wing {
  position: absolute;
  // Align with the aperture/stream position (62% from top matches the logo split)
  top: 62%;
  transform: translateY(-50%);
  height: 2px;
  width: clamp(30px, 6vw, 100px);
  pointer-events: none;
  transition: width 0.3s ease, opacity 0.3s ease;

  // Position wings at the edges of the logo-stack
  // Fine-tuned for visual symmetry with the logo
  &.wing-left {
    right: calc(100% - var(--brand-padding, 20px));
  }

  &.wing-right {
    left: calc(100% - var(--brand-padding, 20px));
  }

  // Progressive shrinking to prevent overlap with buttons
  @media (max-width: 1200px) {
    width: clamp(20px, 4vw, 60px);
  }

  @media (max-width: 1000px) {
    width: clamp(15px, 3vw, 40px);
  }

  // Hide wings completely on narrow screens
  @media (max-width: 850px) {
    opacity: 0;
    width: 0;
    display: none;
  }

  // Main line with gradient fade
  .wing-line {
    position: absolute;
    top: 0;
    height: 100%;
    width: 100%;
    background: linear-gradient(
      90deg,
      transparent 0%,
      var(--vera-accent-faint) 20%,
      var(--vera-accent-soft) 60%,
      var(--vera-accent) 100%
    );
    border-radius: 1px;
    box-shadow: 0 0 8px var(--vera-accent-faint);
  }

  &.wing-left .wing-line {
    background: linear-gradient(
      90deg,
      var(--vera-accent) 0%,
      var(--vera-accent-soft) 40%,
      var(--vera-accent-faint) 80%,
      transparent 100%
    );
  }

  // Traveling pulse animation
  .wing-pulse {
    position: absolute;
    top: -2px;
    height: 6px;
    width: 30px;
    background: linear-gradient(
      90deg,
      transparent 0%,
      var(--vera-accent-strong) 50%,
      transparent 100%
    );
    border-radius: 3px;
    filter: blur(2px);
    opacity: 0.8;
    animation: wingPulseRight calc(3s / var(--vera-anim-speed, 1)) ease-in-out infinite;
  }

  &.wing-left .wing-pulse {
    animation: wingPulseLeft calc(3s / var(--vera-anim-speed, 1)) ease-in-out infinite;
  }

  // Circuit nodes - small geometric accents
  .wing-node {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    width: 4px;
    height: 4px;
    background: var(--vera-accent);
    border-radius: 1px;
    box-shadow:
      0 0 6px var(--vera-accent),
      0 0 12px var(--vera-accent-faint);

    &::before {
      content: '';
      position: absolute;
      top: -3px;
      left: 50%;
      transform: translateX(-50%);
      width: 1px;
      height: 3px;
      background: var(--vera-accent-soft);
    }

    &::after {
      content: '';
      position: absolute;
      bottom: -3px;
      left: 50%;
      transform: translateX(-50%);
      width: 1px;
      height: 3px;
      background: var(--vera-accent-soft);
    }

    &.node-1 {
      right: 30%;
    }

    &.node-2 {
      right: 60%;
      width: 3px;
      height: 3px;
      opacity: 0.7;
    }
  }

  &.wing-left .wing-node {
    &.node-1 {
      left: 30%;
      right: auto;
    }

    &.node-2 {
      left: 60%;
      right: auto;
    }
  }

  // Terminus - end cap with glow effect
  .wing-terminus {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    right: 0;
    width: 6px;
    height: 6px;
    background: var(--vera-accent);
    border-radius: 50%;
    box-shadow:
      0 0 8px var(--vera-accent),
      0 0 16px var(--vera-accent-soft),
      inset 0 0 2px rgba(var(--vera-contrast-rgb), 0.5);
    animation: terminusPulse calc(2s / var(--vera-anim-speed, 1)) ease-in-out infinite;

    &::before {
      content: '';
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 2px;
      height: 2px;
      background: rgba(var(--vera-contrast-rgb), 1);
      border-radius: 50%;
    }

    // Outer ring
    &::after {
      content: '';
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 12px;
      height: 12px;
      border: 1px solid var(--vera-accent-faint);
      border-radius: 50%;
      opacity: 0.5;
    }
  }

  &.wing-left .wing-terminus {
    left: 0;
    right: auto;
  }
}

@keyframes wingPulseRight {
  0%, 100% {
    left: -10%;
    opacity: 0;
  }
  10% {
    opacity: 0.8;
  }
  90% {
    opacity: 0.8;
  }
  100% {
    left: 100%;
    opacity: 0;
  }
}

@keyframes wingPulseLeft {
  0%, 100% {
    right: -10%;
    left: auto;
    opacity: 0;
  }
  10% {
    opacity: 0.8;
  }
  90% {
    opacity: 0.8;
  }
  100% {
    right: 100%;
    left: auto;
    opacity: 0;
  }
}

@keyframes terminusPulse {
  0%, 100% {
    box-shadow:
      0 0 8px var(--vera-accent),
      0 0 16px var(--vera-accent-soft),
      inset 0 0 2px rgba(var(--vera-contrast-rgb), 0.5);
  }
  50% {
    box-shadow:
      0 0 12px var(--vera-accent),
      0 0 24px var(--vera-accent-soft),
      0 0 32px var(--vera-accent-faint),
      inset 0 0 2px rgba(var(--vera-contrast-rgb), 0.8);
  }
}

// ============================================
// WING STATE ANIMATIONS
// ============================================

// Hide second pulse by default
.vera-wing .wing-pulse.pulse-2 {
  opacity: 0;
}

// --- BOOT STATE ---
// Wings grow outward, nodes light up in sequence
.vera-brand.wing-state-boot {
  .vera-wing {
    .wing-line {
      transform: scaleX(0);
      transform-origin: right center;
      transition: transform 0.8s cubic-bezier(0.34, 1.56, 0.64, 1);
    }

    &.wing-left .wing-line {
      transform-origin: left center;
    }

    .wing-node, .wing-terminus {
      opacity: 0;
      transform: translateY(-50%) scale(0);
      transition: all 0.3s ease;
    }

    .wing-pulse {
      opacity: 0;
    }
  }

  &.boot-phase-1 {
    .vera-wing {
      .wing-line {
        transform: scaleX(1);
      }

      .wing-node.node-1 {
        opacity: 1;
        transform: translateY(-50%) scale(1);
        transition-delay: 0.4s;
      }

      .wing-node.node-2 {
        opacity: 0.7;
        transform: translateY(-50%) scale(1);
        transition-delay: 0.6s;
      }

      .wing-terminus {
        opacity: 1;
        transform: translateY(-50%) scale(1);
        transition-delay: 0.8s;
      }

      .wing-pulse {
        animation: bootPulse calc(0.4s / var(--vera-anim-speed, 1)) ease-out calc(1s / var(--vera-anim-speed, 1)) 3;
      }

      &.wing-left .wing-pulse {
        animation: bootPulseLeft calc(0.4s / var(--vera-anim-speed, 1)) ease-out calc(1s / var(--vera-anim-speed, 1)) 3;
      }
    }
  }
}

@keyframes bootPulse {
  0% {
    left: -10%;
    opacity: 0;
  }
  50% {
    opacity: 1;
  }
  100% {
    left: 110%;
    opacity: 0;
  }
}

@keyframes bootPulseLeft {
  0% {
    right: -10%;
    left: auto;
    opacity: 0;
  }
  50% {
    opacity: 1;
  }
  100% {
    right: 110%;
    left: auto;
    opacity: 0;
  }
}

// --- IDLE STATE ---
// Calm, slow breathing
.vera-brand.wing-state-idle {
  .vera-wing {
    .wing-pulse {
      animation: wingPulseRight calc(4s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    &.wing-left .wing-pulse {
      animation: wingPulseLeft calc(4s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    .wing-terminus {
      animation: terminusPulse calc(3s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }
  }
}

// --- THINKING STATE ---
// Fast bidirectional pulses, brighter glow, data processing feel
.vera-brand.wing-state-thinking {
  .vera-wing {
    .wing-line {
      box-shadow: 0 0 12px var(--vera-accent-soft);
      filter: brightness(1.3);
    }

    .wing-pulse {
      animation: thinkingPulseRight calc(0.8s / var(--vera-anim-speed, 1)) linear infinite;
      filter: brightness(1.5);

      &.pulse-2 {
        opacity: 0.6;
        animation: thinkingPulseRight calc(0.8s / var(--vera-anim-speed, 1)) linear infinite calc(0.4s / var(--vera-anim-speed, 1));
      }
    }

    &.wing-left .wing-pulse {
      animation: thinkingPulseLeft calc(0.8s / var(--vera-anim-speed, 1)) linear infinite;

      &.pulse-2 {
        animation: thinkingPulseLeft calc(0.8s / var(--vera-anim-speed, 1)) linear infinite calc(0.4s / var(--vera-anim-speed, 1));
      }
    }

    .wing-node {
      animation: nodeFlicker calc(0.3s / var(--vera-anim-speed, 1)) ease-in-out infinite alternate;
    }

    .wing-terminus {
      animation: terminusThinking calc(0.6s / var(--vera-anim-speed, 1)) ease-in-out infinite;
      filter: brightness(1.4);
    }
  }

  .vera-glow {
    animation: glowThinking calc(0.8s / var(--vera-anim-speed, 1)) ease-in-out infinite !important;
    opacity: 0.9 !important;
  }
}

@keyframes thinkingPulseRight {
  0% {
    left: 120%;
    opacity: 0;
  }
  20% {
    opacity: 1;
  }
  80% {
    opacity: 1;
  }
  100% {
    left: -20%;
    opacity: 0;
  }
}

@keyframes thinkingPulseLeft {
  0% {
    right: 120%;
    left: auto;
    opacity: 0;
  }
  20% {
    opacity: 1;
  }
  80% {
    opacity: 1;
  }
  100% {
    right: -20%;
    left: auto;
    opacity: 0;
  }
}

@keyframes nodeFlicker {
  0% {
    opacity: 0.5;
    box-shadow: 0 0 4px var(--vera-accent), 0 0 8px var(--vera-accent-faint);
  }
  100% {
    opacity: 1;
    box-shadow: 0 0 8px var(--vera-accent), 0 0 16px var(--vera-accent-soft);
  }
}

@keyframes terminusThinking {
  0%, 100% {
    box-shadow:
      0 0 10px var(--vera-accent),
      0 0 20px var(--vera-accent-soft),
      inset 0 0 3px rgba(var(--vera-contrast-rgb), 0.6);
    transform: translateY(-50%) scale(1);
  }
  50% {
    box-shadow:
      0 0 16px var(--vera-accent),
      0 0 32px var(--vera-accent-soft),
      0 0 48px var(--vera-accent-faint),
      inset 0 0 4px rgba(var(--vera-contrast-rgb), 1);
    transform: translateY(-50%) scale(1.2);
  }
}

@keyframes glowThinking {
  0%, 100% {
    opacity: 0.6;
    transform: scale(1);
  }
  50% {
    opacity: 1;
    transform: scale(1.2);
  }
}

// --- QUORUM STATE ---
// Multiple overlapping pulses, cyan tint for collaborative feel
.vera-brand.wing-state-quorum {
  .vera-wing {
    .wing-line {
      background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(var(--vera-accent-rgb), 0.3) 20%,
        rgba(var(--vera-accent-rgb), 0.5) 60%,
        rgba(var(--vera-accent-rgb), 0.8) 100%
      ) !important;
      box-shadow: 0 0 10px rgba(var(--vera-accent-rgb), 0.4);
    }

    &.wing-left .wing-line {
      background: linear-gradient(
        90deg,
        rgba(var(--vera-accent-rgb), 0.8) 0%,
        rgba(var(--vera-accent-rgb), 0.5) 40%,
        rgba(var(--vera-accent-rgb), 0.3) 80%,
        transparent 100%
      ) !important;
    }

    .wing-pulse {
      background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(var(--vera-accent-rgb), 0.9) 50%,
        transparent 100%
      ) !important;
      animation: quorumPulseRight calc(1.5s / var(--vera-anim-speed, 1)) ease-in-out infinite;

      &.pulse-2 {
        opacity: 0.7;
        animation: quorumPulseRight calc(1.5s / var(--vera-anim-speed, 1)) ease-in-out infinite calc(0.5s / var(--vera-anim-speed, 1));
      }
    }

    &.wing-left .wing-pulse {
      animation: quorumPulseLeft calc(1.5s / var(--vera-anim-speed, 1)) ease-in-out infinite;

      &.pulse-2 {
        animation: quorumPulseLeft calc(1.5s / var(--vera-anim-speed, 1)) ease-in-out infinite calc(0.5s / var(--vera-anim-speed, 1));
      }
    }

    .wing-node {
      background: rgba(var(--vera-accent-rgb), 1);
      box-shadow: 0 0 8px rgba(var(--vera-accent-rgb), 0.8), 0 0 16px rgba(var(--vera-accent-rgb), 0.4);
      animation: quorumNodePulse calc(1s / var(--vera-anim-speed, 1)) ease-in-out infinite;

      &.node-2 {
        animation-delay: calc(0.33s / var(--vera-anim-speed, 1));
      }
    }

    .wing-terminus {
      background: rgba(var(--vera-accent-rgb), 1);
      box-shadow:
        0 0 10px rgba(var(--vera-accent-rgb), 0.8),
        0 0 20px rgba(var(--vera-accent-rgb), 0.5),
        inset 0 0 3px rgba(var(--vera-contrast-rgb), 0.7);
      animation: quorumTerminus calc(1.2s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }
  }
}

@keyframes quorumPulseRight {
  0% {
    left: -15%;
    opacity: 0;
  }
  15% {
    opacity: 0.9;
  }
  85% {
    opacity: 0.9;
  }
  100% {
    left: 115%;
    opacity: 0;
  }
}

@keyframes quorumPulseLeft {
  0% {
    right: -15%;
    left: auto;
    opacity: 0;
  }
  15% {
    opacity: 0.9;
  }
  85% {
    opacity: 0.9;
  }
  100% {
    right: 115%;
    left: auto;
    opacity: 0;
  }
}

@keyframes quorumNodePulse {
  0%, 100% {
    transform: translateY(-50%) scale(1);
    opacity: 0.7;
  }
  50% {
    transform: translateY(-50%) scale(1.3);
    opacity: 1;
  }
}

@keyframes quorumTerminus {
  0%, 100% {
    box-shadow:
      0 0 10px rgba(var(--vera-accent-rgb), 0.8),
      0 0 20px rgba(var(--vera-accent-rgb), 0.5),
      inset 0 0 3px rgba(var(--vera-contrast-rgb), 0.7);
  }
  50% {
    box-shadow:
      0 0 16px rgba(var(--vera-accent-rgb), 1),
      0 0 32px rgba(var(--vera-accent-rgb), 0.7),
      0 0 48px rgba(var(--vera-accent-rgb), 0.3),
      inset 0 0 4px rgba(var(--vera-contrast-rgb), 1);
  }
}

// --- SWARM STATE ---
// Most complex - multiple parallel pulses, warm orange/gold tint, chaotic energy
.vera-brand.wing-state-swarm {
  .vera-wing {
    .wing-line {
      background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(var(--vera-warning-rgb), 0.3) 20%,
        rgba(var(--vera-warning-rgb), 0.6) 60%,
        rgba(var(--vera-warning-rgb), 0.9) 100%
      ) !important;
      box-shadow: 0 0 12px rgba(var(--vera-warning-rgb), 0.5);
      animation: swarmLineFlicker calc(0.15s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    &.wing-left .wing-line {
      background: linear-gradient(
        90deg,
        rgba(var(--vera-warning-rgb), 0.9) 0%,
        rgba(var(--vera-warning-rgb), 0.6) 40%,
        rgba(var(--vera-warning-rgb), 0.3) 80%,
        transparent 100%
      ) !important;
    }

    .wing-pulse {
      background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(var(--vera-warning-rgb), 1) 50%,
        transparent 100%
      ) !important;
      width: 20px;
      animation: swarmPulseRight calc(0.6s / var(--vera-anim-speed, 1)) linear infinite;
      filter: brightness(1.3);

      &.pulse-2 {
        opacity: 0.8;
        width: 15px;
        animation: swarmPulseRight calc(0.6s / var(--vera-anim-speed, 1)) linear infinite calc(0.2s / var(--vera-anim-speed, 1));
      }
    }

    &.wing-left .wing-pulse {
      animation: swarmPulseLeft calc(0.6s / var(--vera-anim-speed, 1)) linear infinite;

      &.pulse-2 {
        animation: swarmPulseLeft calc(0.6s / var(--vera-anim-speed, 1)) linear infinite calc(0.2s / var(--vera-anim-speed, 1));
      }
    }

    .wing-node {
      background: rgba(var(--vera-warning-rgb), 1);
      box-shadow: 0 0 10px rgba(var(--vera-warning-rgb), 0.9), 0 0 20px rgba(var(--vera-warning-rgb), 0.5);
      animation: swarmNodeBurst calc(0.4s / var(--vera-anim-speed, 1)) ease-in-out infinite;

      &.node-2 {
        animation-delay: calc(0.15s / var(--vera-anim-speed, 1));
      }

      &::before, &::after {
        background: rgba(var(--vera-warning-rgb), 0.8);
      }
    }

    .wing-terminus {
      background: rgba(var(--vera-warning-rgb), 1);
      box-shadow:
        0 0 12px rgba(var(--vera-warning-rgb), 1),
        0 0 24px rgba(var(--vera-warning-rgb), 0.7),
        inset 0 0 4px rgba(var(--vera-warning-rgb), 0.8);
      animation: swarmTerminus calc(0.5s / var(--vera-anim-speed, 1)) ease-in-out infinite;

      &::after {
        border-color: rgba(var(--vera-warning-rgb), 0.6);
        animation: swarmRing calc(0.8s / var(--vera-anim-speed, 1)) ease-out infinite;
      }
    }
  }

  .vera-glow {
    background: radial-gradient(ellipse, rgba(var(--vera-warning-rgb), 0.6) 0%, transparent 70%) !important;
    animation: swarmGlow calc(0.3s / var(--vera-anim-speed, 1)) ease-in-out infinite !important;
  }
}

@keyframes swarmLineFlicker {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.85;
  }
}

@keyframes swarmPulseRight {
  0% {
    left: -15%;
    opacity: 0;
  }
  10% {
    opacity: 1;
  }
  90% {
    opacity: 1;
  }
  100% {
    left: 115%;
    opacity: 0;
  }
}

@keyframes swarmPulseLeft {
  0% {
    right: -15%;
    left: auto;
    opacity: 0;
  }
  10% {
    opacity: 1;
  }
  90% {
    opacity: 1;
  }
  100% {
    right: 115%;
    left: auto;
    opacity: 0;
  }
}

@keyframes swarmNodeBurst {
  0%, 100% {
    transform: translateY(-50%) scale(1);
    box-shadow: 0 0 10px rgba(var(--vera-warning-rgb), 0.9), 0 0 20px rgba(var(--vera-warning-rgb), 0.5);
  }
  50% {
    transform: translateY(-50%) scale(1.4);
    box-shadow: 0 0 16px rgba(var(--vera-warning-rgb), 1), 0 0 32px rgba(var(--vera-warning-rgb), 0.8);
  }
}

@keyframes swarmTerminus {
  0%, 100% {
    transform: translateY(-50%) scale(1);
  }
  50% {
    transform: translateY(-50%) scale(1.3);
  }
}

@keyframes swarmRing {
  0% {
    transform: translate(-50%, -50%) scale(1);
    opacity: 0.6;
  }
  100% {
    transform: translate(-50%, -50%) scale(2);
    opacity: 0;
  }
}

@keyframes swarmGlow {
  0%, 100% {
    opacity: 0.5;
    transform: scale(1);
  }
  50% {
    opacity: 0.8;
    transform: scale(1.15);
  }
}

// --- STREAMING STATE ---
// Data flowing INWARD toward VERA - reversed pulse direction, green-tinted
.vera-brand.wing-state-streaming {
  // Animation duration based on token rate
  --stream-duration: calc(1.2s / var(--wing-token-rate, 1) / var(--vera-anim-speed, 1));

  .vera-wing {
    .wing-line {
      background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(var(--vera-success-rgb), 0.2) 20%,
        rgba(var(--vera-success-rgb), 0.5) 60%,
        rgba(var(--vera-success-rgb), 0.8) 100%
      ) !important;
      box-shadow: 0 0 10px rgba(var(--vera-success-rgb), 0.4);
    }

    &.wing-left .wing-line {
      background: linear-gradient(
        90deg,
        rgba(var(--vera-success-rgb), 0.8) 0%,
        rgba(var(--vera-success-rgb), 0.5) 40%,
        rgba(var(--vera-success-rgb), 0.2) 80%,
        transparent 100%
      ) !important;
    }

    // Pulses flow INWARD (toward VERA)
    .wing-pulse {
      background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(var(--vera-success-rgb), 0.9) 50%,
        transparent 100%
      ) !important;
      animation: streamPulseRightInward var(--stream-duration) linear infinite;

      &.pulse-2 {
        opacity: 0.6;
        animation: streamPulseRightInward var(--stream-duration) linear infinite calc(var(--stream-duration) / 3);
      }
    }

    &.wing-left .wing-pulse {
      animation: streamPulseLeftInward var(--stream-duration) linear infinite;

      &.pulse-2 {
        animation: streamPulseLeftInward var(--stream-duration) linear infinite calc(var(--stream-duration) / 3);
      }
    }

    .wing-node {
      background: rgba(var(--vera-success-rgb), 1);
      box-shadow: 0 0 8px rgba(var(--vera-success-rgb), 0.8), 0 0 16px rgba(var(--vera-success-rgb), 0.4);
      animation: streamNodePulse calc(0.6s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    .wing-terminus {
      background: rgba(var(--vera-success-rgb), 1);
      box-shadow:
        0 0 10px rgba(var(--vera-success-rgb), 0.8),
        0 0 20px rgba(var(--vera-success-rgb), 0.5),
        inset 0 0 3px rgba(var(--vera-contrast-rgb), 0.7);
      animation: streamTerminus calc(0.8s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }
  }

  .vera-glow {
    background: radial-gradient(ellipse, rgba(var(--vera-success-rgb), 0.5) 0%, transparent 70%) !important;
    animation: streamGlow calc(0.5s / var(--vera-anim-speed, 1)) ease-in-out infinite !important;
  }

  .vera-text {
    animation: streamTextPulse calc(0.8s / var(--vera-anim-speed, 1)) ease-in-out infinite !important;
  }
}

// Inward pulses - RIGHT wing: pulse travels LEFT (toward center)
@keyframes streamPulseRightInward {
  0% {
    left: 100%;
    opacity: 0;
  }
  10% {
    opacity: 1;
  }
  90% {
    opacity: 1;
  }
  100% {
    left: -20%;
    opacity: 0;
  }
}

// Inward pulses - LEFT wing: pulse travels RIGHT (toward center)
@keyframes streamPulseLeftInward {
  0% {
    right: 100%;
    left: auto;
    opacity: 0;
  }
  10% {
    opacity: 1;
  }
  90% {
    opacity: 1;
  }
  100% {
    right: -20%;
    left: auto;
    opacity: 0;
  }
}

@keyframes streamNodePulse {
  0%, 100% {
    transform: translateY(-50%) scale(1);
    opacity: 0.8;
  }
  50% {
    transform: translateY(-50%) scale(1.2);
    opacity: 1;
  }
}

@keyframes streamTerminus {
  0%, 100% {
    box-shadow:
      0 0 10px rgba(var(--vera-success-rgb), 0.8),
      0 0 20px rgba(var(--vera-success-rgb), 0.5),
      inset 0 0 3px rgba(var(--vera-contrast-rgb), 0.7);
  }
  50% {
    box-shadow:
      0 0 14px rgba(var(--vera-success-rgb), 1),
      0 0 28px rgba(var(--vera-success-rgb), 0.7),
      inset 0 0 4px rgba(var(--vera-contrast-rgb), 1);
  }
}

@keyframes streamGlow {
  0%, 100% {
    opacity: 0.5;
    transform: scale(1);
  }
  50% {
    opacity: 0.7;
    transform: scale(1.1);
  }
}

@keyframes streamTextPulse {
  0%, 100% {
    filter: brightness(1);
  }
  50% {
    filter: brightness(1.2);
  }
}

// --- SUCCESS STATE ---
// Brief green flash, satisfying outward burst
.vera-brand.wing-state-success {
  .vera-wing {
    .wing-line {
      background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(var(--vera-success-rgb), 0.4) 20%,
        rgba(var(--vera-success-rgb), 0.7) 60%,
        rgba(var(--vera-success-rgb), 1) 100%
      ) !important;
      box-shadow: 0 0 16px rgba(var(--vera-success-rgb), 0.6);
      animation: successLineFlash calc(0.3s / var(--vera-anim-speed, 1)) ease-out;
    }

    &.wing-left .wing-line {
      background: linear-gradient(
        90deg,
        rgba(var(--vera-success-rgb), 1) 0%,
        rgba(var(--vera-success-rgb), 0.7) 40%,
        rgba(var(--vera-success-rgb), 0.4) 80%,
        transparent 100%
      ) !important;
    }

    .wing-pulse {
      background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(var(--vera-success-rgb), 1) 50%,
        transparent 100%
      ) !important;
      width: 40px;
      animation: successBurst calc(0.5s / var(--vera-anim-speed, 1)) ease-out forwards;
      filter: brightness(1.5);

      &.pulse-2 {
        opacity: 0.7;
        width: 30px;
        animation: successBurst calc(0.5s / var(--vera-anim-speed, 1)) ease-out calc(0.1s / var(--vera-anim-speed, 1)) forwards;
      }
    }

    &.wing-left .wing-pulse {
      animation: successBurstLeft calc(0.5s / var(--vera-anim-speed, 1)) ease-out forwards;

      &.pulse-2 {
        animation: successBurstLeft calc(0.5s / var(--vera-anim-speed, 1)) ease-out calc(0.1s / var(--vera-anim-speed, 1)) forwards;
      }
    }

    .wing-node {
      background: rgba(var(--vera-success-rgb), 1);
      box-shadow: 0 0 12px rgba(var(--vera-success-rgb), 1), 0 0 24px rgba(var(--vera-success-rgb), 0.6);
      animation: successNodePop calc(0.4s / var(--vera-anim-speed, 1)) cubic-bezier(0.68, -0.55, 0.265, 1.55);
    }

    .wing-terminus {
      background: rgba(var(--vera-success-rgb), 1);
      box-shadow:
        0 0 16px rgba(var(--vera-success-rgb), 1),
        0 0 32px rgba(var(--vera-success-rgb), 0.7),
        0 0 48px rgba(var(--vera-success-rgb), 0.4),
        inset 0 0 4px rgba(var(--vera-contrast-rgb), 1);
      animation: successTerminus calc(0.5s / var(--vera-anim-speed, 1)) ease-out;

      &::after {
        animation: successRing calc(0.6s / var(--vera-anim-speed, 1)) ease-out;
        border-color: rgba(var(--vera-success-rgb), 0.8);
      }
    }
  }

  .vera-glow {
    background: radial-gradient(ellipse, rgba(var(--vera-success-rgb), 0.7) 0%, transparent 70%) !important;
    animation: successGlow calc(0.5s / var(--vera-anim-speed, 1)) ease-out !important;
  }

  .vera-text {
    animation: successTextFlash calc(0.5s / var(--vera-anim-speed, 1)) ease-out !important;
  }
}

@keyframes successLineFlash {
  0% {
    filter: brightness(2);
  }
  100% {
    filter: brightness(1);
  }
}

@keyframes successBurst {
  0% {
    left: 0;
    opacity: 1;
    transform: scaleX(1);
  }
  100% {
    left: 120%;
    opacity: 0;
    transform: scaleX(1.5);
  }
}

@keyframes successBurstLeft {
  0% {
    right: 0;
    left: auto;
    opacity: 1;
    transform: scaleX(1);
  }
  100% {
    right: 120%;
    left: auto;
    opacity: 0;
    transform: scaleX(1.5);
  }
}

@keyframes successNodePop {
  0% {
    transform: translateY(-50%) scale(1);
  }
  50% {
    transform: translateY(-50%) scale(1.8);
  }
  100% {
    transform: translateY(-50%) scale(1);
  }
}

@keyframes successTerminus {
  0% {
    transform: translateY(-50%) scale(1.5);
    filter: brightness(2);
  }
  100% {
    transform: translateY(-50%) scale(1);
    filter: brightness(1);
  }
}

@keyframes successRing {
  0% {
    transform: translate(-50%, -50%) scale(1);
    opacity: 1;
    border-width: 2px;
  }
  100% {
    transform: translate(-50%, -50%) scale(3);
    opacity: 0;
    border-width: 1px;
  }
}

@keyframes successGlow {
  0% {
    opacity: 1;
    transform: scale(1.5);
  }
  100% {
    opacity: 0.5;
    transform: scale(1);
  }
}

@keyframes successTextFlash {
  0% {
    filter: brightness(1.5) drop-shadow(0 0 10px rgba(var(--vera-success-rgb), 0.8));
  }
  100% {
    filter: brightness(1) drop-shadow(0 0 0 transparent);
  }
}

// --- ERROR STATE ---
// Red, glitchy, erratic animation
.vera-brand.wing-state-error {
  .vera-wing {
    .wing-line {
      background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(var(--vera-error-rgb), 0.3) 20%,
        rgba(var(--vera-error-rgb), 0.6) 60%,
        rgba(var(--vera-error-rgb), 0.9) 100%
      ) !important;
      box-shadow: 0 0 12px rgba(var(--vera-error-rgb), 0.5);
      animation: errorLineGlitch calc(0.1s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    &.wing-left .wing-line {
      background: linear-gradient(
        90deg,
        rgba(var(--vera-error-rgb), 0.9) 0%,
        rgba(var(--vera-error-rgb), 0.6) 40%,
        rgba(var(--vera-error-rgb), 0.3) 80%,
        transparent 100%
      ) !important;
    }

    .wing-pulse {
      background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(var(--vera-error-rgb), 1) 50%,
        transparent 100%
      ) !important;
      animation: errorPulseGlitch calc(0.2s / var(--vera-anim-speed, 1)) ease-in-out infinite;

      &.pulse-2 {
        opacity: 0.6;
        animation: errorPulseGlitch calc(0.2s / var(--vera-anim-speed, 1)) ease-in-out infinite calc(0.1s / var(--vera-anim-speed, 1));
      }
    }

    .wing-node {
      background: rgba(var(--vera-error-rgb), 1);
      box-shadow: 0 0 10px rgba(var(--vera-error-rgb), 0.9), 0 0 20px rgba(var(--vera-error-rgb), 0.5);
      animation: errorNodeGlitch calc(0.15s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    .wing-terminus {
      background: rgba(var(--vera-error-rgb), 1);
      box-shadow:
        0 0 14px rgba(var(--vera-error-rgb), 1),
        0 0 28px rgba(var(--vera-error-rgb), 0.7),
        inset 0 0 4px rgba(var(--vera-error-rgb), 0.8);
      animation: errorTerminusGlitch calc(0.12s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }
  }

  .vera-glow {
    background: radial-gradient(ellipse, rgba(var(--vera-error-rgb), 0.6) 0%, transparent 70%) !important;
    animation: errorGlowFlicker calc(0.1s / var(--vera-anim-speed, 1)) ease-in-out infinite !important;
  }

  .vera-text {
    animation: errorTextGlitch calc(0.15s / var(--vera-anim-speed, 1)) ease-in-out infinite !important;
  }
}

@keyframes errorLineGlitch {
  0%, 100% {
    opacity: 1;
    transform: scaleX(1);
  }
  25% {
    opacity: 0.7;
    transform: scaleX(0.98);
  }
  50% {
    opacity: 1;
    transform: scaleX(1.02);
  }
  75% {
    opacity: 0.8;
    transform: scaleX(0.99);
  }
}

@keyframes errorPulseGlitch {
  0%, 100% {
    opacity: 0.8;
    left: 20%;
  }
  33% {
    opacity: 1;
    left: 50%;
  }
  66% {
    opacity: 0.5;
    left: 70%;
  }
}

@keyframes errorNodeGlitch {
  0%, 100% {
    transform: translateY(-50%) scale(1);
    opacity: 1;
  }
  50% {
    transform: translateY(-50%) scale(0.8);
    opacity: 0.6;
  }
}

@keyframes errorTerminusGlitch {
  0%, 100% {
    transform: translateY(-50%) scale(1) translateX(0);
    opacity: 1;
  }
  25% {
    transform: translateY(-50%) scale(1.1) translateX(-2px);
    opacity: 0.8;
  }
  50% {
    transform: translateY(-50%) scale(0.9) translateX(2px);
    opacity: 1;
  }
  75% {
    transform: translateY(-50%) scale(1.05) translateX(-1px);
    opacity: 0.7;
  }
}

@keyframes errorGlowFlicker {
  0%, 100% {
    opacity: 0.6;
  }
  50% {
    opacity: 0.3;
  }
}

@keyframes errorTextGlitch {
  0%, 100% {
    transform: translateX(0);
    filter: brightness(1);
  }
  25% {
    transform: translateX(-1px);
    filter: brightness(1.2) hue-rotate(-10deg);
  }
  50% {
    transform: translateX(1px);
    filter: brightness(0.8);
  }
  75% {
    transform: translateX(-0.5px);
    filter: brightness(1.1) hue-rotate(5deg);
  }
}

// ============================================
// PARTICLE FIELD
// ============================================
.vera-particles {
  position: absolute;
  inset: -20px;
  pointer-events: none;
  overflow: visible;
  z-index: 0;

  @media (max-width: 850px) {
    display: none;
  }
}

.particle {
  position: absolute;
  width: 2px;
  height: 2px;
  background: var(--vera-accent);
  border-radius: 50%;
  opacity: 0;
  filter: blur(0.5px);
  box-shadow: 0 0 4px var(--vera-accent);

  // Manually positioned particles for reliable rendering
  &.p-1 { left: 5%; top: 20%; animation: particleFloat1 4s ease-in-out infinite; animation-delay: -0.5s; }
  &.p-2 { left: 15%; top: 60%; animation: particleFloat2 5s ease-in-out infinite; animation-delay: -1.2s; }
  &.p-3 { left: 25%; top: 35%; animation: particleFloat3 4.5s ease-in-out infinite; animation-delay: -2.1s; }
  &.p-4 { left: 35%; top: 75%; animation: particleFloat4 3.5s ease-in-out infinite; animation-delay: -0.8s; }
  &.p-5 { left: 45%; top: 15%; animation: particleFloat1 5.5s ease-in-out infinite; animation-delay: -1.5s; }
  &.p-6 { left: 55%; top: 85%; animation: particleFloat2 4s ease-in-out infinite; animation-delay: -2.5s; }
  &.p-7 { left: 65%; top: 45%; animation: particleFloat3 3.8s ease-in-out infinite; animation-delay: -0.3s; }
  &.p-8 { left: 75%; top: 25%; animation: particleFloat4 4.2s ease-in-out infinite; animation-delay: -1.8s; }
  &.p-9 { left: 85%; top: 70%; animation: particleFloat1 5s ease-in-out infinite; animation-delay: -2.8s; }
  &.p-10 { left: 95%; top: 40%; animation: particleFloat2 3.5s ease-in-out infinite; animation-delay: -0.1s; }
  &.p-11 { left: 10%; top: 50%; animation: particleFloat3 4.8s ease-in-out infinite; animation-delay: -1.0s; }
  &.p-12 { left: 20%; top: 10%; animation: particleFloat4 4.3s ease-in-out infinite; animation-delay: -2.3s; }
  &.p-13 { left: 30%; top: 90%; animation: particleFloat1 3.7s ease-in-out infinite; animation-delay: -1.7s; }
  &.p-14 { left: 40%; top: 30%; animation: particleFloat2 5.2s ease-in-out infinite; animation-delay: -0.6s; }
  &.p-15 { left: 50%; top: 55%; animation: particleFloat3 4.1s ease-in-out infinite; animation-delay: -2.0s; }
  &.p-16 { left: 60%; top: 5%; animation: particleFloat4 3.9s ease-in-out infinite; animation-delay: -1.3s; }
  &.p-17 { left: 70%; top: 65%; animation: particleFloat1 4.6s ease-in-out infinite; animation-delay: -2.6s; }
  &.p-18 { left: 80%; top: 80%; animation: particleFloat2 3.6s ease-in-out infinite; animation-delay: -0.9s; }
  &.p-19 { left: 90%; top: 15%; animation: particleFloat3 5.1s ease-in-out infinite; animation-delay: -1.9s; }
  &.p-20 { left: 98%; top: 95%; animation: particleFloat4 4.4s ease-in-out infinite; animation-delay: -2.2s; }
}

// 4 different float patterns
@keyframes particleFloat1 {
  0%, 100% {
    transform: translate(0, 0) scale(1);
    opacity: 0;
  }
  10% { opacity: 0.6; }
  50% {
    transform: translate(12px, -8px) scale(1.5);
    opacity: 0.8;
  }
  90% { opacity: 0.6; }
}

@keyframes particleFloat2 {
  0%, 100% {
    transform: translate(0, 0) scale(0.8);
    opacity: 0;
  }
  15% { opacity: 0.5; }
  50% {
    transform: translate(-15px, 10px) scale(1.2);
    opacity: 0.7;
  }
  85% { opacity: 0.5; }
}

@keyframes particleFloat3 {
  0%, 100% {
    transform: translate(0, 0) scale(1.2);
    opacity: 0;
  }
  20% { opacity: 0.4; }
  50% {
    transform: translate(8px, 12px) scale(0.9);
    opacity: 0.6;
  }
  80% { opacity: 0.4; }
}

@keyframes particleFloat4 {
  0%, 100% {
    transform: translate(0, 0) scale(1);
    opacity: 0;
  }
  5% { opacity: 0.7; }
  50% {
    transform: translate(-10px, -6px) scale(1.3);
    opacity: 0.9;
  }
  95% { opacity: 0.7; }
}

// State-based particle behavior
.vera-brand.wing-state-idle .vera-particles .particle {
  animation-duration: 6s;
  opacity: 0.3;
}

.vera-brand.wing-state-thinking .vera-particles .particle {
  animation-duration: 2s;
  filter: blur(0.5px) brightness(1.3);
}

.vera-brand.wing-state-streaming .vera-particles .particle {
  animation-duration: 1.5s;
  background: rgba(var(--vera-success-rgb), 1);
  box-shadow: 0 0 6px rgba(var(--vera-success-rgb), 0.8);
}

.vera-brand.wing-state-quorum .vera-particles .particle {
  animation-duration: 2.5s;
  background: rgba(var(--vera-accent-rgb), 1);
  box-shadow: 0 0 6px rgba(var(--vera-accent-rgb), 0.8);
}

.vera-brand.wing-state-swarm .vera-particles .particle {
  animation-duration: 1s;
  background: rgba(var(--vera-warning-rgb), 1);
  box-shadow: 0 0 8px rgba(var(--vera-warning-rgb), 0.9);
  filter: blur(0.5px) brightness(1.4);
}

.vera-brand.wing-state-error .vera-particles .particle {
  animation-duration: 0.5s;
  background: rgba(var(--vera-error-rgb), 1);
  box-shadow: 0 0 6px rgba(var(--vera-error-rgb), 0.8);
}

// ============================================
// ELECTRIC ARCS
// ============================================
.vera-arcs {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 3;
  opacity: 0;
  transition: opacity 0.3s ease;

  @media (max-width: 850px) {
    display: none;
  }
}

.arc {
  fill: none;
  stroke: var(--vera-accent);
  stroke-width: 1.5;
  stroke-linecap: round;
  filter: drop-shadow(0 0 3px var(--vera-accent));
  stroke-dasharray: 100;
  stroke-dashoffset: 100;
  opacity: 0;
}

// Show arcs in active states
.vera-brand.wing-state-thinking .vera-arcs,
.vera-brand.wing-state-swarm .vera-arcs,
.vera-brand.wing-state-quorum .vera-arcs {
  opacity: 1;
}

.vera-brand.wing-state-thinking .arc {
  animation: arcStrike calc(0.8s / var(--vera-anim-speed, 1)) ease-out infinite;
  stroke: var(--vera-accent);
}

.vera-brand.wing-state-swarm .arc {
  animation: arcStrike calc(0.3s / var(--vera-anim-speed, 1)) ease-out infinite;
  stroke: rgba(var(--vera-warning-rgb), 1);
  filter: drop-shadow(0 0 4px rgba(var(--vera-warning-rgb), 0.8));
}

.vera-brand.wing-state-quorum .arc {
  animation: arcStrike calc(0.6s / var(--vera-anim-speed, 1)) ease-out infinite;
  stroke: rgba(var(--vera-accent-rgb), 1);
  filter: drop-shadow(0 0 4px rgba(var(--vera-accent-rgb), 0.8));
}

.arc-left-2 { animation-delay: 0.15s !important; }
.arc-right-1 { animation-delay: 0.1s !important; }
.arc-right-2 { animation-delay: 0.25s !important; }

@keyframes arcStrike {
  0% {
    stroke-dashoffset: 100;
    opacity: 0;
  }
  20% {
    stroke-dashoffset: 0;
    opacity: 1;
  }
  40% {
    stroke-dashoffset: 0;
    opacity: 0.8;
  }
  60% {
    stroke-dashoffset: -100;
    opacity: 0.4;
  }
  100% {
    stroke-dashoffset: -100;
    opacity: 0;
  }
}

// ============================================
// DATA CASCADE
// ============================================
.vera-data-cascade {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 2;
  opacity: 0;
  transition: opacity 0.3s ease;

  @media (max-width: 850px) {
    display: none;
  }
}

.data-stream {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  gap: 4px;
  font-family: 'Courier New', monospace;
  font-size: 0.5rem;
  font-weight: bold;
}

.stream-left {
  right: calc(100% + 30px);
  flex-direction: row-reverse;
}

.stream-right {
  left: calc(100% + 30px);
}

.data-bit {
  color: var(--vera-accent);
  text-shadow: 0 0 4px var(--vera-accent);
  opacity: 0;
  animation: dataBitFlow 2s linear infinite;

  &.bit-1 { animation-delay: 0s; }
  &.bit-2 { animation-delay: 0.15s; }
  &.bit-3 { animation-delay: 0.3s; }
  &.bit-4 { animation-delay: 0.45s; }
  &.bit-5 { animation-delay: 0.6s; }
  &.bit-6 { animation-delay: 0.75s; }
  &.bit-7 { animation-delay: 0.9s; }
  &.bit-8 { animation-delay: 1.05s; }
}

@keyframes dataBitFlow {
  0% {
    opacity: 0;
    transform: translateX(10px);
  }
  20% {
    opacity: 0.9;
    transform: translateX(0);
  }
  80% {
    opacity: 0.9;
    transform: translateX(0);
  }
  100% {
    opacity: 0;
    transform: translateX(-10px);
  }
}

.stream-left .data-bit {
  animation-name: dataBitFlowReverse;
}

@keyframes dataBitFlowReverse {
  0% {
    opacity: 0;
    transform: translateX(-10px);
  }
  20% {
    opacity: 0.9;
    transform: translateX(0);
  }
  80% {
    opacity: 0.9;
    transform: translateX(0);
  }
  100% {
    opacity: 0;
    transform: translateX(10px);
  }
}

// Show data cascade in streaming/processing states
.vera-brand.wing-state-streaming .vera-data-cascade,
.vera-brand.wing-state-thinking .vera-data-cascade {
  opacity: 1;
}

.vera-brand.wing-state-streaming .data-bit {
  color: rgba(var(--vera-success-rgb), 1);
  text-shadow: 0 0 6px rgba(var(--vera-success-rgb), 0.8);
  animation-duration: 1s;
}

.vera-brand.wing-state-swarm .vera-data-cascade {
  opacity: 1;
}

.vera-brand.wing-state-swarm .data-bit {
  color: rgba(var(--vera-warning-rgb), 1);
  text-shadow: 0 0 6px rgba(var(--vera-warning-rgb), 0.8);
  animation-duration: 0.6s;
}

.vera-brand.wing-state-quorum .vera-data-cascade {
  opacity: 0.7;
}

.vera-brand.wing-state-quorum .data-bit {
  color: rgba(var(--vera-accent-rgb), 1);
  text-shadow: 0 0 6px rgba(var(--vera-accent-rgb), 0.8);
  animation-duration: 1.2s;
}

// ============================================
// HOLOGRAPHIC SCANLINES
// ============================================
.vera-scanlines {
  position: absolute;
  inset: -15px;
  pointer-events: none;
  overflow: visible;
  opacity: 0;
  transition: opacity 0.3s ease;
  z-index: 5;
  // Ultra-soft vignette - very gradual fade
  -webkit-mask-image: radial-gradient(
    ellipse 70% 80% at center,
    rgba(var(--vera-shadow-rgb), 1) 0%,
    rgba(var(--vera-shadow-rgb), 1) 20%,
    rgba(var(--vera-shadow-rgb), 0.8) 35%,
    rgba(var(--vera-shadow-rgb), 0.5) 50%,
    rgba(var(--vera-shadow-rgb), 0.2) 65%,
    transparent 80%
  );
  mask-image: radial-gradient(
    ellipse 70% 80% at center,
    rgba(var(--vera-shadow-rgb), 1) 0%,
    rgba(var(--vera-shadow-rgb), 1) 20%,
    rgba(var(--vera-shadow-rgb), 0.8) 35%,
    rgba(var(--vera-shadow-rgb), 0.5) 50%,
    rgba(var(--vera-shadow-rgb), 0.2) 65%,
    transparent 80%
  );
}

.scanline-sweep {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    180deg,
    transparent 0%,
    rgba(var(--vera-contrast-rgb), 0.03) 45%,
    rgba(var(--vera-contrast-rgb), 0.08) 50%,
    rgba(var(--vera-contrast-rgb), 0.03) 55%,
    transparent 100%
  );
  animation: scanlineSweep 3s linear infinite;
  transform: translateY(-100%);
}

.scanline-grid {
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent 0px,
    transparent 2px,
    rgba(var(--vera-contrast-rgb), 0.02) 2px,
    rgba(var(--vera-contrast-rgb), 0.02) 4px
  );
  opacity: 0.5;
}

@keyframes scanlineSweep {
  0% {
    transform: translateY(-100%);
  }
  100% {
    transform: translateY(200%);
  }
}

// Show scanlines in active states
.vera-brand.wing-state-thinking .vera-scanlines,
.vera-brand.wing-state-streaming .vera-scanlines,
.vera-brand.wing-state-quorum .vera-scanlines,
.vera-brand.wing-state-swarm .vera-scanlines {
  opacity: 1;
}

.vera-brand.wing-state-swarm .scanline-sweep {
  animation-duration: 1s;
  background: linear-gradient(
    180deg,
    transparent 0%,
    rgba(var(--vera-warning-rgb), 0.05) 45%,
    rgba(var(--vera-warning-rgb), 0.15) 50%,
    rgba(var(--vera-warning-rgb), 0.05) 55%,
    transparent 100%
  );
}

.vera-brand.wing-state-quorum .scanline-sweep {
  animation-duration: 2s;
  background: linear-gradient(
    180deg,
    transparent 0%,
    rgba(var(--vera-accent-rgb), 0.05) 45%,
    rgba(var(--vera-accent-rgb), 0.12) 50%,
    rgba(var(--vera-accent-rgb), 0.05) 55%,
    transparent 100%
  );
}

// ============================================
// HOLOGRAPHIC GLITCH TEXT
// ============================================
.vera-holo-glitch {
  position: absolute;
  inset: -10px;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  opacity: 0;
  z-index: 4;
  // Ultra-soft vignette - very gradual fade
  -webkit-mask-image: radial-gradient(
    ellipse 75% 85% at center,
    rgba(var(--vera-shadow-rgb), 1) 0%,
    rgba(var(--vera-shadow-rgb), 1) 25%,
    rgba(var(--vera-shadow-rgb), 0.7) 40%,
    rgba(var(--vera-shadow-rgb), 0.4) 55%,
    rgba(var(--vera-shadow-rgb), 0.15) 70%,
    transparent 85%
  );
  mask-image: radial-gradient(
    ellipse 75% 85% at center,
    rgba(var(--vera-shadow-rgb), 1) 0%,
    rgba(var(--vera-shadow-rgb), 1) 25%,
    rgba(var(--vera-shadow-rgb), 0.7) 40%,
    rgba(var(--vera-shadow-rgb), 0.4) 55%,
    rgba(var(--vera-shadow-rgb), 0.15) 70%,
    transparent 85%
  );
}

.holo-layer {
  position: absolute;
  font-size: clamp(18px, 2.8vw, 26px);
  font-weight: 700;
  letter-spacing: 6px;
  text-transform: uppercase;
  opacity: 0.5;
  mix-blend-mode: screen;

  &.holo-r {
    color: rgba(var(--vera-error-rgb), 0.6);
    animation: holoGlitchR 4s ease-in-out infinite;
  }

  &.holo-g {
    color: rgba(var(--vera-success-rgb), 0.6);
    animation: holoGlitchG 4s ease-in-out infinite;
    animation-delay: 0.1s;
  }

  &.holo-b {
    color: rgba(var(--vera-accent-rgb), 0.6);
    animation: holoGlitchB 4s ease-in-out infinite;
    animation-delay: 0.2s;
  }
}

@keyframes holoGlitchR {
  0%, 100% { transform: translate(0, 0); opacity: 0; }
  2% { transform: translate(-2px, 0); opacity: 0.4; }
  4% { transform: translate(0, 0); opacity: 0; }
  50% { transform: translate(0, 0); opacity: 0; }
  52% { transform: translate(1px, -1px); opacity: 0.3; }
  54% { transform: translate(0, 0); opacity: 0; }
}

@keyframes holoGlitchG {
  0%, 100% { transform: translate(0, 0); opacity: 0; }
  2% { transform: translate(2px, 1px); opacity: 0.4; }
  4% { transform: translate(0, 0); opacity: 0; }
  48% { transform: translate(0, 0); opacity: 0; }
  50% { transform: translate(-1px, 1px); opacity: 0.3; }
  52% { transform: translate(0, 0); opacity: 0; }
}

@keyframes holoGlitchB {
  0%, 100% { transform: translate(0, 0); opacity: 0; }
  3% { transform: translate(0, 2px); opacity: 0.4; }
  5% { transform: translate(0, 0); opacity: 0; }
  51% { transform: translate(1px, 0); opacity: 0.3; }
  53% { transform: translate(0, 0); opacity: 0; }
}

// Show glitch in active states (more intense in swarm/error)
.vera-brand.wing-state-thinking .vera-holo-glitch,
.vera-brand.wing-state-streaming .vera-holo-glitch {
  opacity: 0.3;
}

.vera-brand.wing-state-swarm .vera-holo-glitch {
  opacity: 0.6;

  .holo-layer {
    animation-duration: 1s;
  }
}

.vera-brand.wing-state-error .vera-holo-glitch {
  opacity: 0.8;

  .holo-layer {
    animation-duration: 0.3s;

    &.holo-r { color: rgba(var(--vera-error-rgb), 0.8); }
    &.holo-g { color: rgba(var(--vera-warning-rgb), 0.6); }
    &.holo-b { color: rgba(var(--vera-error-rgb), 0.7); }
  }
}

// Desktop header continued
.header-content.desktop-only {
  .model-selectors {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    justify-self: end;
  }
}

// Action button groups and dividers
.action-group {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: 10px;
  background: rgba(var(--vera-contrast-rgb), 0.03);
  border: 1px solid rgba(var(--vera-contrast-rgb), 0.04);
  transition: all 0.2s ease;

  &:hover {
    background: rgba(var(--vera-contrast-rgb), 0.06);
    border-color: rgba(var(--vera-contrast-rgb), 0.08);
  }
}

.action-divider {
  width: 1px;
  height: 24px;
  background: linear-gradient(
    180deg,
    transparent 0%,
    var(--vera-border) 30%,
    var(--vera-border) 70%,
    transparent 100%
  );
  margin: 0 4px;
}

// Mobile header
.header-content.mobile-only {
  height: 56px;
  padding: 0 16px;
  
  .header-left, .header-right {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .header-right {
    max-width: 60vw;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .header-right::-webkit-scrollbar {
    display: none;
  }
  
  .header-center {
    .app-title-mobile {
      margin: 0;
      font-size: 1.125rem;
      font-weight: 600;
      color: $text-color;
    }
  }
}

// Action buttons
.action-btn {
  background: var(--vera-action-btn-bg);
  border: 1px solid transparent;
  backdrop-filter: blur(8px);
  color: $icon-color;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  position: relative;

  svg {
    transition: all 0.2s ease;
  }

  &:hover {
    background: var(--vera-btn-bg-hover);
    border-color: var(--vera-accent-soft);
    color: var(--vera-accent-strong);

    svg {
      transform: scale(1.1);
    }
  }

  &:active {
    transform: scale(0.95);
  }

  // Tools button - rotates on hover
  &.tools-btn:hover svg {
    transform: rotate(90deg) scale(1.1);
  }

  // Power button - pulses red on hover
  &.power-btn {
    &:hover {
      background: var(--vera-glass-strong);
      border-color: var(--vera-danger);
      color: var(--vera-danger);
      box-shadow: 0 0 12px rgba(var(--vera-error-rgb), 0.3);

      svg {
        animation: powerPulse calc(0.6s / var(--vera-anim-speed, 1)) ease-in-out infinite;
      }
    }
  }
}

@keyframes powerPulse {
  0%, 100% {
    transform: scale(1.1);
    opacity: 1;
  }
  50% {
    transform: scale(1.2);
    opacity: 0.8;
  }
}

// Model badge styling
.model-badge {
  display: flex;
  align-items: center;
  gap: 0;
  background: var(--vera-glass-bg);
  border: 1px solid var(--vera-glass-border);
  border-radius: 20px;
  padding: 2px 2px 2px 12px;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-soft);
    background: var(--vera-panel);
    box-shadow: 0 0 20px var(--vera-accent-faint);
  }

  .model-status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--vera-success);
    box-shadow: 0 0 8px var(--vera-success);
    animation: statusPulse calc(2s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    margin-right: 8px;
  }
}

@keyframes statusPulse {
  0%, 100% {
    opacity: 1;
    box-shadow: 0 0 8px var(--vera-success);
  }
  50% {
    opacity: 0.7;
    box-shadow: 0 0 12px var(--vera-success);
  }
}

// Dropdown styling (inside model-badge)
.model-dropdown {
  min-width: 140px;

  :deep(.p-dropdown) {
    background: transparent;
    border: none;
    border-radius: 18px;
    width: 100%;
    font-size: 0.8125rem;
    height: 32px;
    transition: all 0.2s ease;

    &:hover {
      background: rgba(var(--vera-contrast-rgb), 0.05);
    }

    &:focus {
      outline: none;
    }

    .p-dropdown-label {
      padding: 6px 8px 6px 0;
      color: $text-color;
      font-weight: 500;
    }

    .p-dropdown-trigger {
      width: 28px;
      color: var(--vera-accent);
      padding-right: 4px;
    }

    .p-dropdown-panel {
      background-color: var(--vera-glass-strong);
      border: 1px solid var(--vera-glass-border);
      border-radius: 12px;
      margin-top: 8px;
      box-shadow: 0 12px 32px rgba(var(--vera-shadow-rgb), 0.4);

      .p-dropdown-items-wrapper {
        .p-dropdown-item {
          padding: 10px 14px;
          color: $text-color;
          transition: background-color 0.15s ease;
          font-size: 0.8125rem;

          &:hover {
            background-color: var(--vera-accent-faint);
          }

          &.p-highlight {
            background-color: var(--vera-accent-soft);
            color: $text-color;
          }
        }
      }
    }
  }
}
</style>
