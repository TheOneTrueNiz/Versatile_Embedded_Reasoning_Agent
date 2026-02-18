<template>
  <div class="drawer activity-drawer">
    <!-- Premium animated background layers -->
    <div class="bg-layer bg-timeline">
      <div class="timeline-line"></div>
      <span v-for="i in 6" :key="'pulse-'+i" class="timeline-pulse" :style="{ animationDelay: `${i * 1.2}s` }"></span>
    </div>
    <div class="bg-layer bg-stream">
      <span v-for="i in 10" :key="'stream-'+i" class="stream-particle" :style="{ animationDelay: `${i * 0.5}s` }"></span>
    </div>
    <div class="bg-layer bg-gradient-glow"></div>
    <div class="bg-layer bg-scan-lines"></div>

    <header class="drawer-header">
      <div class="drawer-title">
        <Radio size="18" />
        <div>
          <div class="drawer-title-text">Activity</div>
          <div class="drawer-subtitle">Real-time event feed</div>
        </div>
      </div>
      <button class="icon-btn" @click="$emit('close')" title="Close activity">
        <X size="16" />
      </button>
    </header>

    <div class="activity-controls">
      <div class="filter-chips">
        <button
          v-for="filter in filterOptions"
          :key="filter.value"
          :class="['filter-chip', { active: activeFilters.includes(filter.value) }]"
          @click="toggleFilter(filter.value)"
        >
          <component :is="filter.icon" size="12" />
          <span>{{ filter.label }}</span>
        </button>
      </div>
      <div class="activity-actions">
        <button class="secondary-btn" @click="refreshActivity">
          <RefreshCcw size="14" />
          <span>Refresh</span>
        </button>
        <button class="secondary-btn" @click="clearActivity">
          <Trash2 size="14" />
          <span>Clear</span>
        </button>
        <label class="auto-scroll-toggle">
          <input type="checkbox" v-model="autoScroll" />
          <span>Auto-scroll</span>
        </label>
      </div>
    </div>

    <div class="activity-stats">
      <div class="stat-chip">
        <span>Total</span>
        <span class="stat-value">{{ activityLog.length }}</span>
      </div>
      <div class="stat-chip">
        <span>Tools</span>
        <span class="stat-value">{{ toolCount }}</span>
      </div>
      <div class="stat-chip">
        <span>Swarm</span>
        <span class="stat-value">{{ swarmCount }}</span>
      </div>
      <div class="stat-chip">
        <span>Memory</span>
        <span class="stat-value">{{ memoryCount }}</span>
      </div>
    </div>

    <div class="activity-feed" ref="feedContainer">
      <div v-if="!filteredActivity.length" class="empty-state">
        No activity recorded yet. Events will appear here as they occur.
      </div>
      <TransitionGroup name="activity-item" tag="div" class="activity-list">
        <div
          v-for="event in filteredActivity"
          :key="event.id"
          :class="['activity-item', event.type, event.status]"
        >
          <div class="activity-icon">
            <component :is="getEventIcon(event.type)" size="14" />
          </div>
          <div class="activity-content">
            <div class="activity-header">
              <span class="activity-type">{{ formatEventType(event.type) }}</span>
              <span class="activity-time">{{ formatTimestamp(event.timestamp) }}</span>
            </div>
            <div class="activity-title">{{ event.title || event.name }}</div>
            <div v-if="event.detail" class="activity-detail">{{ event.detail }}</div>
            <div v-if="event.duration_ms" class="activity-duration">{{ event.duration_ms }}ms</div>
            <div v-if="event.error" class="activity-error">{{ event.error }}</div>
          </div>
          <div v-if="event.status" :class="['activity-status', event.status]">
            <CheckCircle v-if="event.status === 'success'" size="14" />
            <XCircle v-else-if="event.status === 'error'" size="14" />
            <Clock v-else-if="event.status === 'pending'" size="14" />
            <Loader2 v-else size="14" class="spinning" />
          </div>
        </div>
      </TransitionGroup>
    </div>

    <div class="activity-footer">
      <span class="footer-text">Last update: {{ lastUpdate || '—' }}</span>
      <span v-if="wsConnected" class="ws-indicator connected">
        <Radio size="12" /> Live
      </span>
      <span v-else class="ws-indicator disconnected">
        <Radio size="12" /> Offline
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import {
  Brain,
  CheckCircle,
  Clock,
  Database,
  Loader2,
  MessageSquare,
  Radio,
  RefreshCcw,
  Settings,
  Sparkles,
  Trash2,
  Users,
  Wrench,
  X,
  XCircle,
  Zap
} from 'lucide-vue-next';
import { showToast } from '@/libs/utils/general-utils';

defineEmits(['close']);

const activityLog = ref([]);
const activeFilters = ref(['tool', 'swarm', 'memory', 'system', 'message']);
const autoScroll = ref(true);
const lastUpdate = ref('');
const wsConnected = ref(false);
const wsRef = ref(null);
const feedContainer = ref(null);

const filterOptions = [
  { value: 'tool', label: 'Tools', icon: Wrench },
  { value: 'swarm', label: 'Swarm', icon: Users },
  { value: 'memory', label: 'Memory', icon: Database },
  { value: 'system', label: 'System', icon: Settings },
  { value: 'message', label: 'Messages', icon: MessageSquare }
];

const toolCount = computed(() => activityLog.value.filter(e => e.type === 'tool').length);
const swarmCount = computed(() => activityLog.value.filter(e => e.type === 'swarm').length);
const memoryCount = computed(() => activityLog.value.filter(e => e.type === 'memory').length);

const filteredActivity = computed(() => {
  return activityLog.value
    .filter(event => activeFilters.value.includes(event.type))
    .slice(-100);
});

const toggleFilter = (filter) => {
  const idx = activeFilters.value.indexOf(filter);
  if (idx === -1) {
    activeFilters.value.push(filter);
  } else {
    activeFilters.value.splice(idx, 1);
  }
};

const formatTimestamp = (value) => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString();
};

const formatEventType = (type) => {
  const labels = {
    tool: 'Tool Call',
    swarm: 'Swarm',
    memory: 'Memory',
    system: 'System',
    message: 'Message'
  };
  return labels[type] || type;
};

const getEventIcon = (type) => {
  const icons = {
    tool: Wrench,
    swarm: Users,
    memory: Database,
    system: Settings,
    message: MessageSquare,
    ai: Brain,
    evolution: Sparkles,
    action: Zap
  };
  return icons[type] || Zap;
};

const scrollToBottom = () => {
  if (autoScroll.value && feedContainer.value) {
    nextTick(() => {
      feedContainer.value.scrollTop = feedContainer.value.scrollHeight;
    });
  }
};

const fetchActivity = async () => {
  try {
    const response = await fetch('/api/activity?limit=100');
    if (!response.ok) {
      throw new Error('Failed to fetch activity');
    }
    const data = await response.json();
    activityLog.value = Array.isArray(data) ? data : (data.events || []);
    lastUpdate.value = new Date().toLocaleTimeString();
    scrollToBottom();
  } catch (error) {
    console.error('Unable to fetch activity:', error);
  }
};

const refreshActivity = async () => {
  await fetchActivity();
  showToast('Activity refreshed');
};

const clearActivity = async () => {
  try {
    await fetch('/api/activity/clear', { method: 'POST' });
    activityLog.value = [];
    showToast('Activity cleared');
  } catch (error) {
    showToast('Unable to clear activity');
    console.error(error);
  }
};

const connectWebSocket = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${protocol}://${window.location.host}/ws/activity`;

  try {
    wsRef.value = new WebSocket(wsUrl);
  } catch (error) {
    wsConnected.value = false;
    return;
  }

  wsRef.value.addEventListener('open', () => {
    wsConnected.value = true;
  });

  wsRef.value.addEventListener('message', (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'activity' && data.event) {
        activityLog.value.push({
          ...data.event,
          id: data.event.id || `${Date.now()}-${Math.random().toString(36).slice(2)}`
        });
        lastUpdate.value = new Date().toLocaleTimeString();
        scrollToBottom();
      }
    } catch (e) {
      console.error('Failed to parse activity event:', e);
    }
  });

  wsRef.value.addEventListener('close', () => {
    wsConnected.value = false;
    // Attempt reconnect after 5 seconds
    setTimeout(connectWebSocket, 5000);
  });

  wsRef.value.addEventListener('error', () => {
    wsConnected.value = false;
  });
};

watch(filteredActivity, () => {
  scrollToBottom();
});

onMounted(async () => {
  await fetchActivity();
  connectWebSocket();
});

onBeforeUnmount(() => {
  if (wsRef.value) {
    wsRef.value.close();
  }
});
</script>

<style scoped lang="scss">
// ============================================
// VERA ActivityDrawer Premium Animation System
// Timeline pulse, stream particles, event markers
// Uses theme CSS variables for consistency
// ============================================

// Secondary accent for visual variety (purple tones)
// Uses CSS variable --vera-secondary from theming system

.activity-drawer {
  position: relative;
  height: 100%;
  padding: 20px 18px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: hidden;
  color: var(--vera-text);
  background: var(--vera-drawer-bg);
}

// ============================================
// Background Layers
// ============================================

.bg-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

// Layer 1: Timeline with pulse markers
.bg-timeline {
  z-index: 1;

  .timeline-line {
    position: absolute;
    left: 30px;
    top: 0;
    bottom: 0;
    width: 2px;
    background: linear-gradient(180deg,
      transparent 0%,
      var(--vera-accent-soft) 10%,
      var(--vera-accent-soft) 90%,
      transparent 100%
    );
    animation: timelinePulse 4s ease-in-out infinite;
  }

  .timeline-pulse {
    position: absolute;
    left: 26px;
    width: 10px;
    height: 10px;
    background: var(--vera-accent);
    border-radius: 50%;
    filter: blur(2px);
    animation: pulseMarker 8s ease-in-out infinite;

    @for $i from 1 through 6 {
      &:nth-child(#{$i + 1}) {
        top: (10 + ($i - 1) * 15) * 1%;
      }
    }
  }
}

// Layer 2: Data stream particles
.bg-stream {
  z-index: 2;

  .stream-particle {
    position: absolute;
    width: 2px;
    height: 20px;
    background: linear-gradient(180deg, var(--vera-accent), transparent);
    border-radius: 2px;
    animation: streamFlow 5s linear infinite;
    opacity: 0;

    @for $i from 1 through 10 {
      &:nth-child(#{$i}) {
        left: (5 + ($i - 1) * 10) * 1%;
        animation-duration: (4 + ($i % 3)) * 1s;
      }
    }
  }
}

// Layer 3: Gradient glow
.bg-gradient-glow {
  z-index: 3;
  background:
    radial-gradient(ellipse at 20% 30%, var(--vera-accent-12), transparent 50%),
    radial-gradient(ellipse at 80% 70%, var(--vera-secondary-08), transparent 45%);
  animation: glowShift 8s ease-in-out infinite;
}

// Layer 4: Scan lines
.bg-scan-lines {
  z-index: 4;
  background: repeating-linear-gradient(
    0deg,
    var(--vera-accent-05) 0 1px,
    transparent 1px 6px
  );
  animation: scanDown 15s linear infinite;
  opacity: 0.6;
}

// ============================================
// Content (above background layers)
// ============================================

.activity-drawer > *:not(.bg-layer) {
  position: relative;
  z-index: 10;
}

// ============================================
// Header
// ============================================

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--vera-border);
  padding-bottom: 10px;
  flex-shrink: 0;
  position: relative;

  &::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    width: 60px;
    height: 2px;
    background: linear-gradient(90deg, var(--vera-accent), transparent);
    animation: headerGlow 3s ease-in-out infinite;
  }
}

.drawer-title {
  display: flex;
  gap: 10px;
  align-items: center;

  svg {
    color: var(--vera-accent);
    filter: drop-shadow(0 0 4px var(--vera-accent-soft));
    animation: radioWave 2s ease-in-out infinite;
  }
}

.drawer-title-text {
  font-size: 1rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--vera-text) 0%, var(--vera-accent) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.drawer-subtitle {
  font-size: 0.75rem;
  color: var(--vera-text-muted);
}

.icon-btn {
  border: 1px solid var(--vera-border);
  background: color-mix(in srgb, var(--vera-panel) 60%, transparent);
  color: var(--vera-text);
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-soft);
    box-shadow: 0 0 8px var(--vera-accent-soft);
    transform: scale(1.05);
  }
}

// ============================================
// Controls
// ============================================

.activity-controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex-shrink: 0;
}

.filter-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--vera-border);
  background: var(--vera-filter-button-bg);
  color: var(--vera-text-muted);
  font-size: 0.6875rem;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-soft);
    color: var(--vera-text);
  }

  &.active {
    background: var(--vera-filter-button-active-bg);
    color: var(--vera-text);
    border-color: var(--vera-accent);
    box-shadow: 0 0 10px var(--vera-accent-soft);
    animation: chipGlow 3s ease-in-out infinite;
  }
}

.activity-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.secondary-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  justify-content: center;
  border-radius: 10px;
  border: 1px solid var(--vera-border);
  padding: 6px 10px;
  font-size: 0.6875rem;
  cursor: pointer;
  color: var(--vera-text);
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;

  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(var(--vera-contrast-rgb), 0.1), transparent);
    transition: left 0.4s ease;
  }

  &:hover {
    border-color: var(--vera-accent-soft);
    box-shadow: 0 0 10px var(--vera-accent-15);
    &::before {
      left: 100%;
    }
  }
}

.auto-scroll-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  cursor: pointer;

  input {
    accent-color: var(--vera-accent);
  }
}

// ============================================
// Stats
// ============================================

.activity-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  flex-shrink: 0;
}

.stat-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px;
  background: color-mix(in srgb, var(--vera-panel) 60%, transparent);
  border: 1px solid var(--vera-border);
  border-radius: 10px;
  font-size: 0.625rem;
  color: var(--vera-text-muted);
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;

  &::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, var(--vera-accent-05), transparent);
    opacity: 0;
    transition: opacity 0.3s ease;
  }

  &:hover {
    border-color: var(--vera-accent-soft);
    transform: translateY(-2px);
    &::before {
      opacity: 1;
    }
  }
}

.stat-value {
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--vera-text);
  position: relative;
}

// ============================================
// Activity Feed
// ============================================

.activity-feed {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-right: 4px;

  &::-webkit-scrollbar {
    width: 6px;
  }
  &::-webkit-scrollbar-track {
    background: rgba(var(--vera-shadow-rgb), 0.2);
    border-radius: 3px;
  }
  &::-webkit-scrollbar-thumb {
    background: var(--vera-accent-soft);
    border-radius: 3px;
    &:hover {
      background: var(--vera-accent);
    }
  }
}

.activity-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.activity-item {
  display: flex;
  gap: 10px;
  padding: 10px;
  background: color-mix(in srgb, var(--vera-panel) 72%, transparent);
  border: 1px solid var(--vera-border);
  border-radius: 10px;
  border-left: 3px solid var(--vera-border);
  backdrop-filter: blur(8px);
  transition: all 0.3s ease;
  position: relative;

  // Timeline connector dot
  &::before {
    content: '';
    position: absolute;
    left: -8px;
    top: 50%;
    width: 6px;
    height: 6px;
    background: var(--vera-border);
    border-radius: 50%;
    transform: translateY(-50%);
    transition: all 0.3s ease;
  }

  &:hover {
    border-color: var(--vera-accent-soft);
    box-shadow: 0 0 15px var(--vera-accent-10),
                inset 0 0 20px rgba(var(--vera-accent-rgb), 0.02);
    transform: translateX(4px);

    &::before {
      background: var(--vera-accent);
      box-shadow: 0 0 8px var(--vera-accent-soft);
    }
  }

  &.tool {
    border-left-color: var(--vera-accent);
    &::before { background: var(--vera-accent); }
  }

  &.swarm {
    border-left-color: var(--vera-secondary);
    &::before { background: var(--vera-secondary); }
  }

  &.memory {
    border-left-color: var(--vera-event-memory);
    &::before { background: var(--vera-event-memory); }
  }

  &.system {
    border-left-color: var(--vera-status-warning);
    &::before { background: var(--vera-status-warning); }
  }

  &.message {
    border-left-color: var(--vera-status-info);
    &::before { background: var(--vera-status-info); }
  }

  &.success {
    border-left-color: var(--vera-success);
    &::before { background: var(--vera-success); }
  }

  &.error {
    border-left-color: var(--vera-danger);
    &::before { background: var(--vera-danger); }
  }
}

.activity-icon {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--vera-panel) 60%, transparent);
  border-radius: 8px;
  flex-shrink: 0;
  transition: all 0.2s ease;

  .activity-item:hover & {
    background: var(--vera-accent-10);
    box-shadow: 0 0 8px var(--vera-accent-soft);
  }
}

.activity-content {
  flex: 1;
  min-width: 0;
}

.activity-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.activity-type {
  font-size: 0.625rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--vera-text-muted);
}

.activity-time {
  font-size: 0.625rem;
  color: var(--vera-text-muted);
}

.activity-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--vera-text);
  word-break: break-word;
}

.activity-detail {
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  margin-top: 4px;
}

.activity-duration {
  font-size: 0.625rem;
  color: var(--vera-text-muted);
  margin-top: 2px;
}

.activity-error {
  font-size: 0.6875rem;
  color: var(--vera-danger);
  margin-top: 4px;
}

.activity-status {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;

  &.success {
    color: var(--vera-success);
    filter: drop-shadow(0 0 4px var(--vera-success-40));
  }

  &.error {
    color: var(--vera-danger);
    filter: drop-shadow(0 0 4px var(--vera-error-40));
  }

  &.pending {
    color: var(--vera-warning);
    filter: drop-shadow(0 0 4px var(--vera-warning-40));
  }
}

.spinning {
  animation: spin 1s linear infinite;
}

.empty-state {
  padding: 40px 20px;
  text-align: center;
  font-size: 0.75rem;
  color: var(--vera-text-muted);
}

// ============================================
// Footer
// ============================================

.activity-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 10px;
  border-top: 1px solid var(--vera-border);
  flex-shrink: 0;
}

.footer-text {
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
}

.ws-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.6875rem;
  padding: 4px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
  border: 1px solid transparent;

  &.connected {
    color: var(--vera-success);
    border-color: var(--vera-success-30);
    animation: liveIndicator 2s ease-in-out infinite;

    svg {
      animation: radioWave 1.5s ease-in-out infinite;
    }
  }

  &.disconnected {
    color: var(--vera-text-muted);
  }
}

// ============================================
// Transitions
// ============================================

.activity-item-enter-active {
  transition: all 0.4s ease;
}

.activity-item-leave-active {
  transition: all 0.2s ease;
}

.activity-item-enter-from {
  opacity: 0;
  transform: translateX(-20px) scale(0.98);
}

.activity-item-leave-to {
  opacity: 0;
  transform: translateX(20px) scale(0.98);
}

// ============================================
// Keyframe Animations
// ============================================

@keyframes timelinePulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.8; }
}

@keyframes pulseMarker {
  0%, 100% {
    transform: scale(0.8);
    opacity: 0.3;
  }
  50% {
    transform: scale(1.2);
    opacity: 0.8;
  }
}

@keyframes streamFlow {
  0% {
    top: -30px;
    opacity: 0;
  }
  10% { opacity: 0.6; }
  90% { opacity: 0.6; }
  100% {
    top: 100%;
    opacity: 0;
  }
}

@keyframes glowShift {
  0%, 100% {
    opacity: 0.5;
    transform: scale(1);
  }
  50% {
    opacity: 0.8;
    transform: scale(1.05);
  }
}

@keyframes scanDown {
  0% { background-position: 0 0; }
  100% { background-position: 0 120px; }
}

@keyframes headerGlow {
  0%, 100% { width: 60px; opacity: 0.6; }
  50% { width: 100px; opacity: 1; }
}

@keyframes radioWave {
  0%, 100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.1);
    opacity: 0.7;
  }
}

@keyframes chipGlow {
  0%, 100% { box-shadow: 0 0 8px var(--vera-accent-soft); }
  50% { box-shadow: 0 0 15px var(--vera-accent); }
}

@keyframes liveIndicator {
  0%, 100% {
    box-shadow: 0 0 4px var(--vera-success-20);
  }
  50% {
    box-shadow: 0 0 10px var(--vera-success-40);
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

// ============================================
// Reduced Motion
// ============================================

@media (prefers-reduced-motion: reduce) {
  .bg-layer,
  .timeline-pulse,
  .stream-particle,
  .filter-chip.active,
  .ws-indicator.connected,
  .drawer-title svg,
  .spinning {
    animation: none !important;
  }
}
</style>
