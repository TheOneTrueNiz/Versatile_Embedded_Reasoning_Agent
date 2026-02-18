<template>
  <div class="drawer diagnostics-drawer">
    <!-- Animated background -->
    <div class="diag-bg">
      <div class="grid-overlay"></div>
      <div class="pulse-ring pulse-1"></div>
      <div class="pulse-ring pulse-2"></div>
      <div class="data-stream">
        <span v-for="i in 8" :key="i" class="stream-dot"></span>
      </div>
    </div>

    <!-- Header -->
    <header class="diag-header">
      <div class="header-left">
        <div class="header-icon">
          <Activity size="20" />
        </div>
        <div class="header-text">
          <h2>System Diagnostics</h2>
          <span class="header-sub">Real-time telemetry</span>
        </div>
      </div>
      <div class="header-actions">
        <button class="refresh-btn" @click="refreshAll" title="Refresh all">
          <RefreshCcw size="14" :class="{ spinning: isRefreshing }" />
        </button>
        <button class="close-btn" @click="$emit('close')" title="Close">
          <X size="16" />
        </button>
      </div>
    </header>

    <!-- Quick Status Bar -->
    <div class="quick-status">
      <div class="status-item" :class="wsStatusClass">
        <div class="status-dot"></div>
        <span class="status-label">WebSocket</span>
        <span class="status-value">{{ wsStatusLabel }}</span>
      </div>
      <div class="status-item" :class="apiHealthClass">
        <div class="status-dot"></div>
        <span class="status-label">API</span>
        <span class="status-value">{{ apiHealthLabel }}</span>
      </div>
      <div class="status-item" :class="voiceStatusClass">
        <div class="status-dot"></div>
        <span class="status-label">Voice</span>
        <span class="status-value">{{ voiceStatusLabel }}</span>
      </div>
      <div class="status-item" :class="browserStatusClass">
        <div class="status-dot"></div>
        <span class="status-label">Browser</span>
        <span class="status-value">{{ browserStatusLabel }}</span>
      </div>
    </div>

    <!-- Main Content -->
    <div class="diag-content">
      <!-- Session Metrics -->
      <section class="diag-section">
        <div class="section-header">
          <span class="section-icon"><BarChart3 size="14" /></span>
          <span class="section-title">Session Metrics</span>
          <span class="section-badge">{{ sessionTokenSummary }}</span>
        </div>
        <div class="metrics-grid" v-if="sessionStats">
          <div class="metric">
            <span class="metric-value">{{ sessionStats.message_count ?? 0 }}</span>
            <span class="metric-label">Messages</span>
          </div>
          <div class="metric">
            <span class="metric-value">{{ formatCompact(sessionStats.input_tokens) }}</span>
            <span class="metric-label">Input Tokens</span>
          </div>
          <div class="metric">
            <span class="metric-value">{{ formatCompact(sessionStats.output_tokens) }}</span>
            <span class="metric-label">Output Tokens</span>
          </div>
          <div class="metric">
            <span class="metric-value">{{ sessionStats.tool_calls ?? 0 }}</span>
            <span class="metric-label">Tool Calls</span>
          </div>
          <div class="metric highlight">
            <span class="metric-value">${{ sessionStats.estimated_cost?.toFixed(4) || '0.00' }}</span>
            <span class="metric-label">Est. Cost</span>
          </div>
        </div>
        <div v-else class="empty-state">Loading session data...</div>
      </section>

      <!-- API Health -->
      <section class="diag-section">
        <div class="section-header">
          <span class="section-icon"><Zap size="14" /></span>
          <span class="section-title">API Connection</span>
          <span :class="['section-badge', apiHealthClass]">{{ apiHealthLabel }}</span>
        </div>
        <div class="api-info" v-if="apiHealth">
          <div class="info-row">
            <span class="info-label">Model</span>
            <span class="info-value">{{ apiHealth.model || '—' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">Latency</span>
            <span class="info-value">{{ apiHealth.latency_ms ? `${apiHealth.latency_ms}ms` : '—' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">Last Check</span>
            <span class="info-value">{{ formatTimestamp(apiHealth.checked_at) }}</span>
          </div>
          <div v-if="apiHealth.error" class="error-row">
            <span class="info-label">Error</span>
            <span class="info-value error">{{ apiHealth.error }}</span>
          </div>
        </div>
        <button class="action-btn" :disabled="apiPinging" @click="pingApi">
          <Zap size="12" />
          <span>{{ apiPinging ? 'Pinging...' : 'Test Connection' }}</span>
        </button>
      </section>

      <!-- Error Log -->
      <section class="diag-section" :class="{ 'has-errors': errorLogCount > 0 }">
        <div class="section-header">
          <span class="section-icon"><AlertTriangle size="14" /></span>
          <span class="section-title">Error Log</span>
          <span :class="['section-badge', errorLogCount > 0 ? 'danger' : '']">{{ errorLogCount }}</span>
        </div>
        <div v-if="!errorLog.length" class="empty-state">No errors logged</div>
        <div v-else class="error-list">
          <div v-for="(err, idx) in errorLog.slice(0, 5)" :key="idx" class="error-item">
            <span class="error-time">{{ formatTimestamp(err.timestamp) }}</span>
            <span class="error-type">{{ err.type || 'error' }}</span>
            <span class="error-msg">{{ err.message }}</span>
          </div>
        </div>
        <button v-if="errorLog.length" class="action-btn danger" @click="clearErrorLog">
          <Trash2 size="12" />
          <span>Clear Log</span>
        </button>
      </section>

      <!-- Memory Stats -->
      <section class="diag-section">
        <div class="section-header">
          <span class="section-icon"><Database size="14" /></span>
          <span class="section-title">Memory</span>
          <span class="section-badge">{{ memorySummary }}</span>
        </div>
        <div class="memory-info" v-if="memoryStats">
          <div class="memory-tiers">
            <div class="tier">
              <span class="tier-value">{{ memoryStats.tiers?.session ?? 0 }}</span>
              <span class="tier-label">Session</span>
            </div>
            <div class="tier">
              <span class="tier-value">{{ memoryStats.tiers?.working ?? 0 }}</span>
              <span class="tier-label">Working</span>
            </div>
            <div class="tier">
              <span class="tier-value">{{ memoryStats.tiers?.long_term_videos ?? 0 }}</span>
              <span class="tier-label">Long-term</span>
            </div>
          </div>
          <div v-if="memoryStats.rag_cache" class="cache-bar">
            <span class="cache-label">Cache Hit Rate</span>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: `${(memoryStats.rag_cache.hit_rate || 0) * 100}%` }"></div>
            </div>
            <span class="cache-value">{{ formatPercent(memoryStats.rag_cache.hit_rate) }}</span>
          </div>
        </div>
        <div v-else class="empty-state">Loading memory stats...</div>
      </section>

      <!-- Services Status -->
      <section class="diag-section">
        <div class="section-header">
          <span class="section-icon"><Settings size="14" /></span>
          <span class="section-title">Services</span>
        </div>
        <div class="services-grid">
          <!-- OAuth -->
          <div class="service-item" :class="googleAuthClass">
            <div class="service-icon"><Shield size="16" /></div>
            <div class="service-info">
              <span class="service-name">OAuth</span>
              <span class="service-status">{{ googleAuthLabel }}</span>
            </div>
          </div>
          <!-- Voice -->
          <div class="service-item" :class="voiceStatusClass">
            <div class="service-icon"><Mic size="16" /></div>
            <div class="service-info">
              <span class="service-name">Voice</span>
              <span class="service-status">{{ voiceStatusLabel }}</span>
            </div>
            <button
              v-if="voiceStatus?.enabled"
              class="service-action"
              :disabled="voiceTesting"
              @click="runVoiceTest"
            >
              {{ voiceTesting ? '...' : 'Test' }}
            </button>
          </div>
          <!-- Browser -->
          <div class="service-item" :class="browserStatusClass">
            <div class="service-icon"><Globe size="16" /></div>
            <div class="service-info">
              <span class="service-name">Browser</span>
              <span class="service-status">{{ browserStatusLabel }}</span>
            </div>
            <button
              v-if="browserStatus?.available && !browserStatus?.launched"
              class="service-action"
              :disabled="browserLaunching"
              @click="launchBrowser"
            >
              {{ browserLaunching ? '...' : 'Launch' }}
            </button>
            <button
              v-else-if="browserStatus?.launched"
              class="service-action danger"
              :disabled="browserClosing"
              @click="closeBrowser"
            >
              {{ browserClosing ? '...' : 'Close' }}
            </button>
          </div>
        </div>
      </section>
    </div>

    <!-- Footer Status -->
    <div class="diag-footer">
      <span class="footer-status">Last update: {{ lastUpdate || 'Never' }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, onErrorCaptured, ref } from 'vue';
import {
  Activity, AlertTriangle, BarChart3, Database, Globe, Mic,
  RefreshCcw, Settings, Shield, Trash2, X, Zap
} from 'lucide-vue-next';
import { showToast } from '@/libs/utils/general-utils';

// Polling interval for real-time updates (5 seconds)
const POLL_INTERVAL_MS = 5000;

defineEmits(['close']);

const wsStatus = ref('disconnected');
const lastUpdate = ref('');
let pollIntervalId = null;
const wsRef = ref(null);
const isRefreshing = ref(false);

const apiHealth = ref(null);
const apiPinging = ref(false);
const sessionStats = ref(null);
const errorLog = ref([]);

const googleAuthStatus = ref(null);
const voiceStatus = ref(null);
const voiceTesting = ref(false);
const memoryStats = ref(null);
const browserStatus = ref(null);
const browserLaunching = ref(false);
const browserClosing = ref(false);

const wsStatusLabel = computed(() => {
  if (wsStatus.value === 'connected') return 'connected';
  if (wsStatus.value === 'connecting') return 'connecting';
  if (wsStatus.value === 'error') return 'error';
  return 'offline';
});

const wsStatusClass = computed(() => {
  if (wsStatus.value === 'connected') return 'ok';
  if (wsStatus.value === 'connecting') return 'warn';
  if (wsStatus.value === 'error') return 'danger';
  return 'neutral';
});

const apiHealthLabel = computed(() => {
  if (!apiHealth.value) return 'unknown';
  if (apiHealth.value.status === 'ok') return 'healthy';
  if (apiHealth.value.status === 'degraded') return 'degraded';
  if (apiHealth.value.status === 'error') return 'error';
  // If we have model info or latency, consider it healthy even without explicit status
  if (apiHealth.value.model || apiHealth.value.latency_ms) return 'healthy';
  return apiHealth.value.status || 'unknown';
});

const apiHealthClass = computed(() => {
  if (!apiHealth.value) return 'neutral';
  if (apiHealth.value.status === 'ok') return 'ok';
  if (apiHealth.value.status === 'degraded') return 'warn';
  if (apiHealth.value.status === 'error') return 'danger';
  // If we have model info or latency, consider it healthy even without explicit status
  if (apiHealth.value.model || apiHealth.value.latency_ms) return 'ok';
  return 'neutral';
});

const sessionTokenSummary = computed(() => {
  if (!sessionStats.value) return '—';
  const total = sessionStats.value.total_tokens ?? 0;
  return `${formatCompact(total)} tokens`;
});

const errorLogCount = computed(() => errorLog.value.length);

const googleAuthLabel = computed(() => {
  const status = googleAuthStatus.value?.status;
  if (status === 'authorized') return 'authorized';
  if (status === 'unauthorized') return 'unauthorized';
  if (status === 'missing') return 'missing';
  return 'unknown';
});

const googleAuthClass = computed(() => {
  const status = googleAuthStatus.value?.status;
  if (status === 'authorized') return 'ok';
  if (status === 'unauthorized') return 'warn';
  if (status === 'missing') return 'danger';
  return 'neutral';
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
  if (!voiceStatus.value) return 'neutral';
  if (voiceStatus.value.enabled && voiceStatus.value.backend_ready && voiceStatus.value.websockets_available) {
    return 'ok';
  }
  if (!voiceStatus.value.enabled) return 'warn';
  return 'danger';
});

const memorySummary = computed(() => {
  const tiers = memoryStats.value?.tiers;
  if (!tiers) return '—';
  const total = (tiers.session ?? 0) + (tiers.working ?? 0) + (tiers.long_term_videos ?? 0);
  return `${total} items`;
});

const browserStatusLabel = computed(() => {
  if (!browserStatus.value) return 'unknown';
  if (!browserStatus.value.enabled) return 'disabled';
  if (browserStatus.value.launched) return 'active';
  if (browserStatus.value.available) return 'ready';
  return 'unavailable';
});

const browserStatusClass = computed(() => {
  if (!browserStatus.value) return 'neutral';
  if (!browserStatus.value.enabled) return 'warn';
  if (browserStatus.value.launched) return 'warn'; // Yellow when deployed/active
  if (browserStatus.value.available) return 'ok'; // Green when ready to launch
  return 'danger'; // Red when unavailable/error
});

const setUpdateTimestamp = () => {
  lastUpdate.value = new Date().toLocaleTimeString();
};

const formatTimestamp = (value) => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString();
};

const formatCompact = (value) => {
  if (value === null || value === undefined) return '—';
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return value.toString();
};

const formatPercent = (value) => {
  if (value === null || value === undefined) return '—';
  return `${Math.round(value * 100)}%`;
};

const fetchApiHealth = async () => {
  try {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error('Failed to fetch API health');
    apiHealth.value = await response.json();
    setUpdateTimestamp();
  } catch (error) {
    apiHealth.value = { status: 'error', error: error.message };
  }
};

const pingApi = async () => {
  apiPinging.value = true;
  const startTime = Date.now();
  try {
    const response = await fetch('/api/ping');
    const latency = Date.now() - startTime;
    if (!response.ok) throw new Error('Ping failed');
    const data = await response.json();
    apiHealth.value = {
      ...apiHealth.value,
      status: 'ok',
      latency_ms: latency,
      checked_at: new Date().toISOString(),
      model: data.model || apiHealth.value?.model
    };
    showToast(`API responding (${latency}ms)`);
  } catch (error) {
    apiHealth.value = {
      ...apiHealth.value,
      status: 'error',
      error: error.message,
      checked_at: new Date().toISOString()
    };
    showToast('API ping failed');
  } finally {
    apiPinging.value = false;
  }
};

const fetchSessionStats = async () => {
  try {
    const response = await fetch('/api/session/stats');
    if (!response.ok) throw new Error('Failed');
    sessionStats.value = await response.json();
    setUpdateTimestamp();
  } catch (error) {
    console.error('Session stats error:', error);
  }
};

const fetchErrorLog = async () => {
  try {
    const response = await fetch('/api/errors?limit=20');
    if (!response.ok) throw new Error('Failed');
    const data = await response.json();
    errorLog.value = Array.isArray(data) ? data : (data.errors || []);
    setUpdateTimestamp();
  } catch (error) {
    console.error('Error log error:', error);
  }
};

const clearErrorLog = async () => {
  try {
    await fetch('/api/errors/clear', { method: 'POST' });
    errorLog.value = [];
    showToast('Error log cleared');
  } catch (error) {
    showToast('Unable to clear error log');
  }
};

const fetchGoogleAuthStatus = async () => {
  try {
    const response = await fetch('/api/google/auth/status');
    if (!response.ok) throw new Error('Failed');
    googleAuthStatus.value = await response.json();
    setUpdateTimestamp();
  } catch (error) {
    console.error('Google auth error:', error);
  }
};

const fetchVoiceStatus = async () => {
  try {
    const response = await fetch('/api/voice/status');
    if (!response.ok) throw new Error('Failed');
    voiceStatus.value = await response.json();
    setUpdateTimestamp();
  } catch (error) {
    console.error('Voice status error:', error);
  }
};

const fetchMemoryStats = async () => {
  try {
    const response = await fetch('/api/memory/stats');
    if (!response.ok) throw new Error('Failed');
    memoryStats.value = await response.json();
    setUpdateTimestamp();
  } catch (error) {
    console.error('Memory stats error:', error);
  }
};

const fetchBrowserStatus = async () => {
  try {
    const response = await fetch('/api/browser/status');
    if (!response.ok) throw new Error('Failed');
    browserStatus.value = await response.json();
    setUpdateTimestamp();
  } catch (error) {
    console.error('Browser status error:', error);
  }
};

const refreshAll = async () => {
  isRefreshing.value = true;
  await Promise.all([
    fetchApiHealth(),
    fetchSessionStats(),
    fetchErrorLog(),
    fetchGoogleAuthStatus(),
    fetchVoiceStatus(),
    fetchMemoryStats(),
    fetchBrowserStatus()
  ]);
  isRefreshing.value = false;
};

const runVoiceTest = async () => {
  voiceTesting.value = true;
  try {
    const selectedVoice = voiceStatus.value?.selected_voice || 'eve';
    const response = await fetch('/api/voice/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ include_audio: true, voice: selectedVoice })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Voice test failed');
    if (data.audio_b64) {
      const binary = atob(data.audio_b64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], { type: data.audio_format || 'audio/wav' });
      const audio = new Audio(URL.createObjectURL(blob));
      audio.play().catch(() => {});
    }
    showToast('Voice test succeeded');
  } catch (error) {
    showToast('Voice test failed');
  } finally {
    voiceTesting.value = false;
  }
};

const launchBrowser = async () => {
  browserLaunching.value = true;
  try {
    await fetch('/api/browser/launch', { method: 'POST' });
    await fetchBrowserStatus();
  } catch (error) {
    showToast('Unable to launch browser');
  } finally {
    browserLaunching.value = false;
  }
};

const closeBrowser = async () => {
  browserClosing.value = true;
  try {
    await fetch('/api/browser/close', { method: 'POST' });
    await fetchBrowserStatus();
  } catch (error) {
    showToast('Unable to close browser');
  } finally {
    browserClosing.value = false;
  }
};

const connectWebSocket = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${protocol}://${window.location.host}/ws`;
  wsStatus.value = 'connecting';
  try {
    wsRef.value = new WebSocket(wsUrl);
    wsRef.value.addEventListener('open', () => { wsStatus.value = 'connected'; });
    wsRef.value.addEventListener('message', () => { setUpdateTimestamp(); });
    wsRef.value.addEventListener('close', () => { wsStatus.value = 'disconnected'; });
    wsRef.value.addEventListener('error', () => { wsStatus.value = 'error'; });
  } catch {
    wsStatus.value = 'error';
  }
};

onMounted(async () => {
  await refreshAll();
  connectWebSocket();
  // Start polling for real-time updates
  pollIntervalId = setInterval(() => {
    refreshAll();
  }, POLL_INTERVAL_MS);
});

onBeforeUnmount(() => {
  if (wsRef.value) wsRef.value.close();
  // Clean up polling interval
  if (pollIntervalId) {
    clearInterval(pollIntervalId);
    pollIntervalId = null;
  }
});

onErrorCaptured(() => false);
</script>

<style scoped lang="scss">
// ============================================
// DIAGNOSTICS DRAWER - REDESIGNED
// Uses theme CSS variables for consistency
// ============================================

.diagnostics-drawer {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--vera-sidebar-bg);
  color: var(--vera-text);
  overflow: hidden;
}

// ============================================
// BACKGROUND EFFECTS
// ============================================

.diag-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.grid-overlay {
  position: absolute;
  inset: 0;
  background: var(--vera-grid-line);
  background-image:
    linear-gradient(90deg, var(--vera-accent-faint) 1px, transparent 1px),
    linear-gradient(var(--vera-accent-faint) 1px, transparent 1px);
  background-size: 40px 40px;
  animation: gridPan 30s linear infinite;
}

.pulse-ring {
  position: absolute;
  border-radius: 50%;
  border: 1px solid var(--vera-accent-soft);
  animation: pulseExpand 4s ease-out infinite;

  &.pulse-1 {
    top: 10%;
    right: 10%;
    width: 60px;
    height: 60px;
  }

  &.pulse-2 {
    bottom: 20%;
    left: 5%;
    width: 40px;
    height: 40px;
    animation-delay: 2s;
  }
}

.data-stream {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 100%;

  .stream-dot {
    position: absolute;
    width: 4px;
    height: 4px;
    background: var(--vera-accent);
    border-radius: 50%;
    box-shadow: 0 0 8px var(--vera-accent);
    animation: streamFlow 6s linear infinite;

    @for $i from 1 through 8 {
      &:nth-child(#{$i}) {
        left: (10 + $i * 10) * 1%;
        animation-delay: ($i * 0.75) * 1s;
        opacity: 0.3 + ($i % 3) * 0.2;
      }
    }
  }
}

// ============================================
// HEADER
// ============================================

.diag-header {
  position: relative;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 18px;
  border-bottom: 1px solid var(--vera-glass-border);
  background: linear-gradient(180deg, var(--vera-accent-faint) 0%, transparent 100%);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--vera-accent-soft) 0%, var(--vera-accent-faint) 100%);
  border: 1px solid var(--vera-accent-soft);
  border-radius: var(--vera-radius-md);
  color: var(--vera-accent);
  animation: iconGlow 3s ease-in-out infinite;
}

.header-text {
  h2 {
    font-size: 0.9375rem;
    font-weight: 600;
    margin: 0;
    color: var(--vera-text);
  }

  .header-sub {
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
}

.header-actions {
  display: flex;
  gap: 8px;
}

.refresh-btn, .close-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--vera-glass-bg);
  border: 1px solid var(--vera-border);
  border-radius: var(--vera-radius-sm);
  color: var(--vera-text-muted);
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    background: var(--vera-accent-faint);
    border-color: var(--vera-accent-soft);
    color: var(--vera-accent);
  }

  .spinning {
    animation: spin 1s linear infinite;
  }
}

// ============================================
// QUICK STATUS BAR
// ============================================

.quick-status {
  position: relative;
  z-index: 10;
  display: flex;
  gap: 8px;
  padding: 12px 18px;
  background: var(--vera-panel-muted);
  border-bottom: 1px solid var(--vera-border);
}

.status-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 8px;
  background: var(--vera-glass-bg);
  border: 1px solid var(--vera-border);
  border-radius: var(--vera-radius-md);
  transition: all 0.3s ease;

  &:hover {
    background: var(--vera-glass-strong);
  }

  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--vera-text-muted);
    transition: all 0.3s ease;
  }

  .status-label {
    font-size: 0.625rem;
    color: var(--vera-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }

  .status-value {
    font-size: 0.6875rem;
    font-weight: 500;
    color: var(--vera-text);
  }

  &.ok {
    border-color: rgba(var(--vera-success), 0.2);
    .status-dot {
      background: var(--vera-success);
      box-shadow: 0 0 8px var(--vera-success);
      animation: dotPulse 2s ease-in-out infinite;
    }
    .status-value { color: var(--vera-success); }
  }

  &.warn {
    border-color: rgba(var(--vera-warning), 0.2);
    .status-dot {
      background: var(--vera-warning);
      box-shadow: 0 0 8px var(--vera-warning);
    }
    .status-value { color: var(--vera-warning); }
  }

  &.danger {
    border-color: rgba(var(--vera-danger), 0.2);
    .status-dot {
      background: var(--vera-danger);
      box-shadow: 0 0 8px var(--vera-danger);
      animation: dotPulse 1s ease-in-out infinite;
    }
    .status-value { color: var(--vera-danger); }
  }
}

// ============================================
// CONTENT AREA
// ============================================

.diag-content {
  position: relative;
  z-index: 10;
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;

  &::-webkit-scrollbar {
    width: 4px;
  }

  &::-webkit-scrollbar-track {
    background: var(--vera-scrollbar-track);
  }

  &::-webkit-scrollbar-thumb {
    background: var(--vera-scrollbar-thumb);
    border-radius: 2px;
  }
}

// ============================================
// SECTIONS
// ============================================

.diag-section {
  background: var(--vera-glass-bg);
  border: 1px solid var(--vera-border);
  border-radius: var(--vera-radius-lg);
  padding: 14px;
  transition: all 0.3s ease;

  &:hover {
    border-color: var(--vera-glass-border);
    background: var(--vera-glass-strong);
  }

  &.has-errors {
    border-color: var(--vera-danger);
    background: var(--vera-error-05);
  }
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--vera-border);
}

.section-icon {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--vera-accent-faint);
  border-radius: var(--vera-radius-sm);
  color: var(--vera-accent);
}

.section-title {
  flex: 1;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--vera-text);
}

.section-badge {
  padding: 3px 10px;
  background: var(--vera-accent-faint);
  border: 1px solid var(--vera-accent-soft);
  border-radius: var(--vera-radius-full);
  font-size: 0.6875rem;
  font-weight: 500;
  color: var(--vera-accent);

  &.ok { color: var(--vera-success); background: var(--vera-success-10); border-color: var(--vera-success-20); }
  &.warn { color: var(--vera-warning); background: var(--vera-warning-10); border-color: var(--vera-warning-20); }
  &.danger { color: var(--vera-danger); background: var(--vera-error-10); border-color: var(--vera-error-20); }
}

// ============================================
// METRICS GRID
// ============================================

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 8px;
  background: var(--vera-card-bg);
  border-radius: var(--vera-radius-sm);
  border: 1px solid var(--vera-border);

  .metric-value {
    font-size: 1rem;
    font-weight: 600;
    color: var(--vera-text);
  }

  .metric-label {
    font-size: 0.625rem;
    color: var(--vera-text-muted);
    text-transform: uppercase;
    margin-top: 4px;
  }

  &.highlight {
    background: var(--vera-accent-faint);
    border-color: var(--vera-accent-soft);
    grid-column: span 3;

    .metric-value {
      color: var(--vera-accent);
      font-size: 1.125rem;
    }
  }
}

// ============================================
// API INFO
// ============================================

.api-info, .memory-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  background: var(--vera-panel-muted);
  border-radius: var(--vera-radius-sm);

  .info-label {
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
  }

  .info-value {
    font-size: 0.75rem;
    color: var(--vera-text);
    font-family: var(--vera-font-mono);

    &.error {
      color: var(--vera-danger);
    }
  }
}

// ============================================
// MEMORY TIERS
// ============================================

.memory-tiers {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.tier {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px;
  background: var(--vera-panel-muted);
  border-radius: var(--vera-radius-sm);

  .tier-value {
    font-size: 1.125rem;
    font-weight: 600;
    color: var(--vera-accent);
  }

  .tier-label {
    font-size: 0.625rem;
    color: var(--vera-text-muted);
    margin-top: 4px;
  }
}

.cache-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  background: var(--vera-panel-muted);
  border-radius: var(--vera-radius-sm);

  .cache-label {
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
    white-space: nowrap;
  }

  .progress-bar {
    flex: 1;
    height: 6px;
    background: var(--vera-border);
    border-radius: 3px;
    overflow: hidden;

    .progress-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--vera-accent), var(--vera-success));
      border-radius: 3px;
      transition: width 0.5s ease;
    }
  }

  .cache-value {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--vera-accent);
    min-width: 40px;
    text-align: right;
  }
}

// ============================================
// ERROR LIST
// ============================================

.error-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 150px;
  overflow-y: auto;
  margin-bottom: 12px;
}

.error-item {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  background: var(--vera-error-05);
  border-left: 2px solid var(--vera-danger);
  border-radius: 0 var(--vera-radius-sm) var(--vera-radius-sm) 0;
  font-size: 0.6875rem;

  .error-time {
    color: var(--vera-text-muted);
    font-family: var(--vera-font-mono);
  }

  .error-type {
    padding: 2px 6px;
    background: var(--vera-error-20);
    border-radius: var(--vera-radius-sm);
    color: var(--vera-danger);
    font-weight: 500;
    text-transform: uppercase;
    font-size: 0.5625rem;
  }

  .error-msg {
    color: var(--vera-text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

// ============================================
// SERVICES GRID
// ============================================

.services-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.service-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: var(--vera-card-bg);
  border: 1px solid var(--vera-border);
  border-radius: var(--vera-radius-sm);
  transition: all 0.2s ease;

  &:hover {
    background: var(--vera-glass-bg);
  }

  .service-icon {
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--vera-glass-bg);
    border-radius: var(--vera-radius-sm);
    color: var(--vera-text-muted);
  }

  .service-info {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;

    .service-name {
      font-size: 0.75rem;
      font-weight: 500;
      color: var(--vera-text);
    }

    .service-status {
      font-size: 0.625rem;
      color: var(--vera-text-muted);
    }
  }

  &.ok {
    border-color: var(--vera-success-15);
    .service-icon { color: var(--vera-success); background: var(--vera-success-10); }
    .service-status { color: var(--vera-success); }
  }

  &.warn {
    border-color: var(--vera-warning-15);
    .service-icon { color: var(--vera-warning); background: var(--vera-warning-10); }
    .service-status { color: var(--vera-warning); }
  }

  &.danger {
    border-color: var(--vera-error-15);
    .service-icon { color: var(--vera-danger); background: var(--vera-error-10); }
    .service-status { color: var(--vera-danger); }
  }
}

.service-action {
  padding: 6px 12px;
  background: var(--vera-accent-faint);
  border: 1px solid var(--vera-accent-soft);
  border-radius: var(--vera-radius-sm);
  color: var(--vera-accent);
  font-size: 0.6875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover:not(:disabled) {
    background: var(--vera-accent-soft);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  &.danger {
    background: var(--vera-error-10);
    border-color: var(--vera-error-20);
    color: var(--vera-danger);

    &:hover:not(:disabled) {
      background: var(--vera-error-20);
    }
  }
}

// ============================================
// ACTION BUTTONS
// ============================================

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  background: var(--vera-accent-faint);
  border: 1px solid var(--vera-accent-soft);
  border-radius: var(--vera-radius-sm);
  color: var(--vera-accent);
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover:not(:disabled) {
    background: var(--vera-accent-soft);
    border-color: var(--vera-accent);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  &.danger {
    background: rgba(var(--vera-error-rgb), 0.08);
    border-color: var(--vera-error-20);
    color: var(--vera-danger);

    &:hover:not(:disabled) {
      background: var(--vera-error-15);
    }
  }
}

// ============================================
// FOOTER
// ============================================

.diag-footer {
  position: relative;
  z-index: 10;
  padding: 10px 18px;
  border-top: 1px solid var(--vera-border);
  background: var(--vera-panel-muted);

  .footer-status {
    font-size: 0.625rem;
    color: var(--vera-text-muted);
  }
}

// ============================================
// EMPTY STATE
// ============================================

.empty-state {
  padding: 16px;
  text-align: center;
  font-size: 0.75rem;
  color: var(--vera-text-muted);
  font-style: italic;
}

// ============================================
// KEYFRAMES
// ============================================

@keyframes gridPan {
  0% { transform: translate(0, 0); }
  100% { transform: translate(40px, 40px); }
}

@keyframes pulseExpand {
  0% {
    transform: scale(0.8);
    opacity: 0.8;
  }
  100% {
    transform: scale(2);
    opacity: 0;
  }
}

@keyframes streamFlow {
  0% {
    top: -10px;
    opacity: 0;
  }
  10% {
    opacity: 0.8;
  }
  90% {
    opacity: 0.6;
  }
  100% {
    top: 100%;
    opacity: 0;
  }
}

@keyframes iconGlow {
  0%, 100% {
    box-shadow: var(--vera-glow-soft);
  }
  50% {
    box-shadow: var(--vera-glow-strong);
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes dotPulse {
  0%, 100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.3);
  }
}

// ============================================
// REDUCED MOTION
// ============================================

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
