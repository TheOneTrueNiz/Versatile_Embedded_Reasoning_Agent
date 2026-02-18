<template>
  <div class="drawer tools-drawer">
    <!-- Premium animated background layers -->
    <div class="bg-layer bg-circuit">
      <svg class="circuit-svg" viewBox="0 0 400 800" preserveAspectRatio="xMidYMid slice">
        <defs>
          <linearGradient id="traceGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="transparent" />
            <stop offset="50%" stop-color="var(--vera-accent-80)" />
            <stop offset="100%" stop-color="transparent" />
          </linearGradient>
        </defs>
        <!-- Horizontal circuit traces -->
        <path class="circuit-trace" d="M0,80 H120 L140,100 H260 L280,80 H400" />
        <path class="circuit-trace" d="M0,200 H80 L100,180 H200 L220,200 H320 L340,220 H400" />
        <path class="circuit-trace" d="M0,350 H160 L180,330 H300 L320,350 H400" />
        <path class="circuit-trace" d="M0,500 H100 L120,520 H280 L300,500 H400" />
        <path class="circuit-trace" d="M0,650 H200 L220,630 H400" />
        <!-- Vertical traces -->
        <path class="circuit-trace vertical" d="M100,0 V150 L120,170 V350" />
        <path class="circuit-trace vertical" d="M300,0 V100 L280,120 V280" />
        <path class="circuit-trace vertical" d="M200,200 V400 L220,420 V600" />
        <!-- Circuit nodes -->
        <circle v-for="i in 12" :key="'node-'+i" class="circuit-node"
          :cx="circuitNodes[i-1].x" :cy="circuitNodes[i-1].y" r="4" />
      </svg>
    </div>
    <div class="bg-layer bg-grid-pattern"></div>
    <div class="bg-layer bg-data-stream">
      <span v-for="i in 8" :key="'data-'+i" class="data-particle" :style="{ animationDelay: `${i * 0.6}s` }"></span>
    </div>
    <div class="bg-layer bg-glow-spots">
      <span class="glow-spot spot-1"></span>
      <span class="glow-spot spot-2"></span>
      <span class="glow-spot spot-3"></span>
    </div>

    <header class="drawer-header">
      <div class="drawer-title">
        <Wrench size="18" />
        <div>
          <div class="drawer-title-text">Tools</div>
          <div class="drawer-subtitle">{{ mcpSummary }}</div>
        </div>
      </div>
      <button class="icon-btn" @click="$emit('close')" title="Close tools">
        <X size="16" />
      </button>
    </header>

    <div class="drawer-actions">
      <button class="primary-btn" @click="refreshAll">
        <RefreshCcw size="14" />
        <span>Refresh</span>
      </button>
      <button class="secondary-btn" @click="startStoppedTools">
        <Play size="14" />
        <span>Start Stopped</span>
      </button>
      <button class="secondary-btn" @click="restartUnhealthyTools">
        <RefreshCcw size="14" />
        <span>Restart Unhealthy</span>
      </button>
      <button class="primary-btn" :disabled="isVerifying" @click="verifyTools">
        <ShieldCheck size="14" />
        <span>{{ isVerifying ? 'Verifying...' : 'Verify Tools' }}</span>
      </button>
      <div class="last-update">Updated {{ lastUpdate || '—' }}</div>
    </div>

    <section class="drawer-card verify-card" v-if="verifySummary">
      <div class="card-header">
        <span>Verification</span>
        <span class="pill">{{ verifySummary.ok }} ok · {{ verifySummary.skipped }} skip · {{ verifySummary.failed }} fail</span>
      </div>
      <div class="verify-grid">
        <div v-for="result in verifyResults" :key="result.server" :class="['verify-item', result.status]">
          <span>{{ result.server }}</span>
          <span>{{ result.status }}</span>
          <span v-if="result.detail">{{ result.detail }}</span>
        </div>
      </div>
    </section>

    <!-- Tool Execution History -->
    <section class="drawer-card history-card">
      <div class="card-header">
        <span>Execution History</span>
        <span class="pill">{{ toolHistory.length }} recent</span>
      </div>
      <div v-if="!toolHistory.length" class="empty-state">No tool executions recorded yet.</div>
      <div v-else class="history-list">
        <div v-for="(call, idx) in toolHistory" :key="idx" class="history-item" :class="call.status">
          <div class="history-header">
            <span class="history-tool">{{ call.tool_name }}</span>
            <span :class="['badge', call.status === 'success' ? 'ok' : 'danger']">{{ call.status }}</span>
          </div>
          <div class="history-meta">
            <span>{{ call.server || 'native' }}</span>
            <span>{{ call.duration_ms ? `${call.duration_ms}ms` : '—' }}</span>
            <span>{{ formatTimestamp(call.timestamp) }}</span>
          </div>
          <div v-if="call.error" class="history-error">{{ call.error }}</div>
        </div>
      </div>
      <button v-if="toolHistory.length" class="secondary-btn" @click="clearHistory">
        <Trash2 size="14" />
        <span>Clear History</span>
      </button>
    </section>

    <!-- MCP Server Controls -->
    <section class="drawer-card servers-card" v-if="toolStatus">
      <div class="card-header">
        <span>MCP Servers</span>
        <span class="pill">{{ mcpSummary }}</span>
      </div>
      <div class="servers-list">
        <div v-for="(server, name) in toolStatus.mcp.servers" :key="name" class="server-item">
          <div class="server-info">
            <span class="server-name">{{ name }}</span>
            <div class="server-badges">
              <span :class="['badge', server.running ? 'ok' : 'warn']">
                {{ server.running ? 'running' : 'stopped' }}
              </span>
              <span v-if="server.health" :class="['badge', server.health === 'healthy' ? 'ok' : 'warn']">
                {{ server.health }}
              </span>
              <span v-if="server.missing_env && server.missing_env.length" class="badge danger">
                missing {{ server.missing_env.length }}
              </span>
            </div>
          </div>
          <div class="server-actions">
            <button
              v-if="!server.running"
              class="mini-btn ok"
              :disabled="serverActionPending[name]"
              @click="startServer(name)"
              title="Start server"
            >
              <Play size="12" />
            </button>
            <button
              v-else
              class="mini-btn warn"
              :disabled="serverActionPending[name]"
              @click="stopServer(name)"
              title="Stop server"
            >
              <Square size="12" />
            </button>
            <button
              class="mini-btn"
              :disabled="serverActionPending[name] || !server.running"
              @click="restartServer(name)"
              title="Restart server"
            >
              <RotateCcw size="12" />
            </button>
          </div>
        </div>
      </div>
    </section>

    <section class="drawer-card payload-card" v-if="lastPayload">
      <div class="card-header">
        <span>Routing Snapshot</span>
        <span class="pill">{{ payloadToolCount }} tools</span>
      </div>
      <div class="payload-grid">
        <div><strong>Tools used:</strong> {{ payloadToolsUsed }}</div>
        <div><strong>Servers:</strong> {{ payloadServers }}</div>
        <div><strong>Native/MCP:</strong> {{ lastPayload.native_included ?? 0 }}/{{ lastPayload.mcp_included ?? 0 }}</div>
        <div><strong>Tool choice:</strong> {{ lastPayload.tool_choice || 'auto' }}</div>
      </div>
      <div class="payload-tools">{{ payloadToolNames }}</div>
    </section>

    <section class="drawer-card inventory-card" v-if="toolInventory">
      <div class="card-header">
        <span>Tool Inventory</span>
        <span class="pill">{{ inventoryCount }} tools</span>
      </div>
      <div class="inventory-grid">
        <div v-for="section in inventorySections" :key="section.label" class="inventory-section">
          <div class="inventory-header">
            <span>{{ section.label }}</span>
            <span>{{ section.count }}</span>
          </div>
          <details v-for="item in section.items" :key="item.name">
            <summary>{{ item.name }} ({{ item.tools.length }})</summary>
            <div class="tool-list">
              {{ item.tools.length ? item.tools.join(', ') : 'No tools reported.' }}
            </div>
          </details>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { Play, RefreshCcw, RotateCcw, ShieldCheck, Square, Trash2, Wrench, X } from 'lucide-vue-next';
import { showToast } from '@/libs/utils/general-utils';

// Polling interval for real-time updates (5 seconds)
const POLL_INTERVAL_MS = 5000;

defineEmits(['close']);

// Circuit node positions for background visualization
const circuitNodes = [
  { x: 120, y: 80 }, { x: 280, y: 80 }, { x: 140, y: 100 },
  { x: 100, y: 180 }, { x: 220, y: 200 }, { x: 340, y: 220 },
  { x: 180, y: 330 }, { x: 320, y: 350 }, { x: 120, y: 520 },
  { x: 300, y: 500 }, { x: 220, y: 630 }, { x: 200, y: 400 }
];

const toolStatus = ref(null);
const toolInventory = ref(null);
const lastPayload = ref(null);
const verifySummary = ref(null);
const verifyResults = ref([]);
const isVerifying = ref(false);
const lastUpdate = ref('');
const toolHistory = ref([]);
const serverActionPending = reactive({});
let pollIntervalId = null;

const setUpdateTimestamp = () => {
  lastUpdate.value = new Date().toLocaleTimeString();
};

const formatTimestamp = (value) => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString();
};

const mcpSummary = computed(() => {
  const servers = toolStatus.value?.mcp?.servers;
  if (!servers) return 'MCP: —';
  const entries = Object.values(servers);
  const total = entries.length;
  const running = entries.filter((server) => server.running).length;
  const unhealthy = entries.filter((server) => server.running && server.health && server.health !== 'healthy').length;
  const missing = entries.filter((server) => server.missing_env && server.missing_env.length).length;
  let summary = `${running}/${total} running`;
  if (unhealthy) summary += ` · ${unhealthy} unhealthy`;
  if (missing) summary += ` · ${missing} missing`;
  return summary;
});

const inventoryCount = computed(() => {
  if (!toolInventory.value?.tools) return 0;
  return Object.values(toolInventory.value.tools).reduce((sum, tools) => sum + tools.length, 0);
});

const inventorySections = computed(() => {
  const tools = toolInventory.value?.tools || {};
  const sections = [];
  const used = new Set();

  const addSection = (label, names) => {
    const items = [];
    let count = 0;
    names.forEach((name) => {
      if (Object.prototype.hasOwnProperty.call(tools, name)) {
        const entry = tools[name] || [];
        items.push({ name, tools: entry });
        count += entry.length;
        used.add(name);
      }
    });
    if (items.length) {
      sections.push({ label, items, count });
    }
  };

  addSection('Core', ['filesystem', 'memory', 'time', 'sequential-thinking']);
  addSection('Search', ['brave-search', 'searxng']);
  addSection('Knowledge', ['wikipedia', 'pdf-reader']);
  addSection('Notes', ['obsidian-vault']);
  addSection('Automation Hub', ['mcp-hub']);
  addSection('Workspace', ['google-workspace']);
  addSection('Dev', ['github']);
  addSection('Media', ['memvid', 'youtube-transcript']);

  const otherNames = Object.keys(tools)
    .filter((name) => !used.has(name))
    .sort();
  if (otherNames.length) {
    const items = otherNames.map((name) => ({ name, tools: tools[name] || [] }));
    const count = items.reduce((sum, item) => sum + item.tools.length, 0);
    sections.push({ label: 'Other', items, count });
  }

  return sections;
});

const payloadToolCount = computed(() => lastPayload.value?.tool_count || 0);
const payloadToolNames = computed(() => {
  const names = lastPayload.value?.tool_names;
  if (!names || !names.length) return 'No tools recorded.';
  const total = lastPayload.value?.tool_names_total || names.length;
  if (lastPayload.value?.tool_names_truncated && total > names.length) {
    return `${names.join(', ')} (+${total - names.length} more)`;
  }
  return names.join(', ');
});
const payloadServers = computed(() => {
  const servers = lastPayload.value?.selected_servers;
  if (!servers || !servers.length) return '—';
  return servers.join(', ');
});
const payloadToolsUsed = computed(() => {
  const tools = lastPayload.value?.last_tools_used;
  if (!tools) return '—';
  if (!tools.length) return 'none';
  return tools.join(', ');
});

const fetchToolStatus = async () => {
  try {
    const response = await fetch('/api/tools');
    if (!response.ok) {
      throw new Error('Failed to fetch tool status');
    }
    toolStatus.value = await response.json();
    setUpdateTimestamp();
  } catch (error) {
    showToast('Unable to fetch tool status');
    console.error(error);
  }
};

const fetchToolInventory = async () => {
  try {
    const response = await fetch('/api/tools/list');
    if (!response.ok) {
      throw new Error('Failed to fetch tool inventory');
    }
    toolInventory.value = await response.json();
    setUpdateTimestamp();
  } catch (error) {
    showToast('Unable to fetch tool inventory');
    console.error(error);
  }
};

const fetchLastPayload = async () => {
  try {
    const response = await fetch('/api/tools/last_payload');
    if (!response.ok) {
      throw new Error('Failed to fetch tool payload');
    }
    const data = await response.json();
    lastPayload.value = data.payload || data;
    setUpdateTimestamp();
  } catch (error) {
    showToast('Unable to fetch last tool payload');
    console.error(error);
  }
};

const fetchToolHistory = async () => {
  try {
    const response = await fetch('/api/tools/history?limit=15');
    if (!response.ok) {
      console.warn('[ToolsDrawer] history fetch failed:', response.status);
      return;
    }
    const data = await response.json();
    const entries = Array.isArray(data) ? data : (data.history || []);
    console.warn('[ToolsDrawer] history entries:', entries.length, JSON.stringify(entries));
    toolHistory.value = entries;
    setUpdateTimestamp();
  } catch (error) {
    console.error('[ToolsDrawer] Unable to fetch tool history:', error);
  }
};

const clearHistory = async () => {
  try {
    await fetch('/api/tools/history/clear', { method: 'POST' });
    toolHistory.value = [];
    showToast('Tool history cleared');
  } catch (error) {
    showToast('Unable to clear history');
    console.error(error);
  }
};

const refreshAll = async () => {
  await Promise.all([fetchToolStatus(), fetchToolInventory(), fetchLastPayload(), fetchToolHistory()]);
};

const startStoppedTools = async () => {
  try {
    const response = await fetch('/api/tools/start', { method: 'POST' });
    if (!response.ok) {
      throw new Error('Failed to start tools');
    }
    await fetchToolStatus();
    showToast('Started stopped tools');
  } catch (error) {
    showToast('Unable to start tools');
    console.error(error);
  }
};

const restartUnhealthyTools = async () => {
  try {
    const response = await fetch('/api/tools/restart', { method: 'POST' });
    if (!response.ok) {
      throw new Error('Failed to restart tools');
    }
    await fetchToolStatus();
    showToast('Restarted unhealthy tools');
  } catch (error) {
    showToast('Unable to restart tools');
    console.error(error);
  }
};

const startServer = async (serverName) => {
  serverActionPending[serverName] = true;
  try {
    const response = await fetch('/api/tools/server/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ server: serverName })
    });
    if (!response.ok) {
      throw new Error('Failed to start server');
    }
    await fetchToolStatus();
    showToast(`Started ${serverName}`);
  } catch (error) {
    showToast(`Unable to start ${serverName}`);
    console.error(error);
  } finally {
    serverActionPending[serverName] = false;
  }
};

const stopServer = async (serverName) => {
  serverActionPending[serverName] = true;
  try {
    const response = await fetch('/api/tools/server/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ server: serverName })
    });
    if (!response.ok) {
      throw new Error('Failed to stop server');
    }
    await fetchToolStatus();
    showToast(`Stopped ${serverName}`);
  } catch (error) {
    showToast(`Unable to stop ${serverName}`);
    console.error(error);
  } finally {
    serverActionPending[serverName] = false;
  }
};

const restartServer = async (serverName) => {
  serverActionPending[serverName] = true;
  try {
    const response = await fetch('/api/tools/server/restart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ server: serverName })
    });
    if (!response.ok) {
      throw new Error('Failed to restart server');
    }
    await fetchToolStatus();
    showToast(`Restarted ${serverName}`);
  } catch (error) {
    showToast(`Unable to restart ${serverName}`);
    console.error(error);
  } finally {
    serverActionPending[serverName] = false;
  }
};

const verifyTools = async () => {
  if (isVerifying.value) return;
  isVerifying.value = true;
  try {
    const response = await fetch('/api/tools/verify', { method: 'POST' });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.error || 'Verification failed');
    }
    verifySummary.value = data.summary;
    verifyResults.value = data.results || [];
    showToast('Tool verification complete');
  } catch (error) {
    showToast('Tool verification failed');
    console.error(error);
  } finally {
    isVerifying.value = false;
  }
};

onMounted(async () => {
  await refreshAll();
  // Start polling for real-time updates
  pollIntervalId = setInterval(() => {
    refreshAll();
  }, POLL_INTERVAL_MS);
});

onUnmounted(() => {
  // Clean up polling interval
  if (pollIntervalId) {
    clearInterval(pollIntervalId);
    pollIntervalId = null;
  }
});
</script>

<style scoped lang="scss">
// ============================================
// VERA ToolsDrawer Premium Animation System
// Circuit board traces, data flow, node pulses
// Uses theme CSS variables for consistency
// ============================================

// Secondary accent for visual variety (green/teal tones)
$secondary-accent: var(--vera-status-success);
$secondary-accent-soft: var(--vera-success-60);

.tools-drawer {
  position: relative;
  height: 100%;
  padding: 20px 18px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  overflow-x: hidden;
  color: var(--vera-text);

  // Custom scrollbar
  &::-webkit-scrollbar {
    width: 6px;
  }
  &::-webkit-scrollbar-track {
    background: var(--vera-black-20);
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

// ============================================
// Background Layers
// ============================================

.bg-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

// Layer 1: SVG Circuit traces
.bg-circuit {
  z-index: 1;
  opacity: 0.5;

  .circuit-svg {
    width: 100%;
    height: 100%;
  }

  .circuit-trace {
    fill: none;
    stroke: var(--vera-accent-soft);
    stroke-width: 1.5;
    stroke-dasharray: 200;
    stroke-dashoffset: 200;
    animation: traceFlow 8s ease-in-out infinite;

    @for $i from 1 through 8 {
      &:nth-child(#{$i + 1}) {
        animation-delay: ($i * 0.5) * 1s;
        animation-duration: (6 + ($i % 3)) * 1s;
      }
    }

    &.vertical {
      animation-duration: 10s;
    }
  }

  .circuit-node {
    fill: var(--vera-accent);
    filter: drop-shadow(0 0 4px var(--vera-accent));
    animation: nodePulse 3s ease-in-out infinite;

    @for $i from 1 through 12 {
      &:nth-child(#{$i + 9}) {
        animation-delay: ($i * 0.25) * 1s;
      }
    }
  }
}

// Layer 2: Grid pattern
.bg-grid-pattern {
  z-index: 2;
  background:
    repeating-linear-gradient(90deg, var(--vera-accent-soft) 0 1px, transparent 1px 20px),
    repeating-linear-gradient(0deg, var(--vera-accent-08) 0 1px, transparent 1px 20px);
  animation: gridDrift 30s linear infinite;
  opacity: 0.4;
}

// Layer 3: Data stream particles
.bg-data-stream {
  z-index: 3;

  .data-particle {
    position: absolute;
    width: 3px;
    height: 12px;
    background: linear-gradient(180deg, var(--vera-accent), transparent);
    border-radius: 2px;
    animation: dataStream 4s linear infinite;
    opacity: 0;

    @for $i from 1 through 8 {
      &:nth-child(#{$i}) {
        left: (5 + ($i - 1) * 12) * 1%;
        animation-duration: (3 + ($i % 3)) * 1s;
      }
    }
  }
}

// Layer 4: Glow spots
.bg-glow-spots {
  z-index: 4;

  .glow-spot {
    position: absolute;
    border-radius: 50%;
    filter: blur(40px);
    animation: spotPulse 6s ease-in-out infinite;

    &.spot-1 {
      width: 120px;
      height: 120px;
      top: 10%;
      left: 10%;
      background: var(--vera-accent-15);
    }

    &.spot-2 {
      width: 100px;
      height: 100px;
      top: 40%;
      right: 15%;
      background: var(--vera-success-10);
      animation-delay: 2s;
    }

    &.spot-3 {
      width: 80px;
      height: 80px;
      bottom: 20%;
      left: 30%;
      background: var(--vera-accent-12);
      animation-delay: 4s;
    }
  }
}

// ============================================
// Content (above background layers)
// ============================================

.tools-drawer > *:not(.bg-layer) {
  position: relative;
  z-index: 10;
}

// ============================================
// Header
// ============================================

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--vera-border);
  position: relative;

  &::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    width: 50px;
    height: 2px;
    background: linear-gradient(90deg, var(--vera-accent), transparent);
    animation: headerTrace 3s ease-in-out infinite;
  }
}

.drawer-title {
  display: flex;
  gap: 10px;
  align-items: center;

  svg {
    color: var(--vera-accent);
    filter: drop-shadow(0 0 4px var(--vera-accent-soft));
    animation: iconSpin 20s linear infinite;
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
// Actions Bar
// ============================================

.drawer-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  align-items: center;

  .last-update {
    grid-column: span 2;
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
  }
}

.primary-btn,
.secondary-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  justify-content: center;
  border-radius: 10px;
  border: 1px solid var(--vera-border);
  padding: 8px 10px;
  font-size: 0.75rem;
  cursor: pointer;
  color: var(--vera-text);
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

  &:hover::before {
    left: 100%;
  }
}

.primary-btn {
  background: linear-gradient(135deg, var(--vera-accent-20), var(--vera-accent-10));
  border-color: var(--vera-accent-soft);
  box-shadow: 0 0 14px var(--vera-accent-20);

  &:hover {
    box-shadow: 0 0 20px var(--vera-accent-soft);
    transform: translateY(-1px);
  }
}

.secondary-btn {
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);

  &:hover {
    border-color: var(--vera-accent-soft);
    box-shadow: 0 0 10px var(--vera-accent-15);
  }
}

.primary-btn:disabled,
.secondary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  &:hover {
    transform: none;
    box-shadow: none;
  }
}

// ============================================
// Cards with staggered entry
// ============================================

.drawer-card {
  border: 1px solid var(--vera-border);
  border-radius: 14px;
  padding: 14px;
  background: var(--vera-card-bg);
  backdrop-filter: blur(16px);
  display: flex;
  flex-direction: column;
  gap: 12px;
  opacity: 0;
  animation: cardSlideIn 0.5s ease forwards;
  transition: all 0.3s ease;
  position: relative;

  &:hover {
    border-color: var(--vera-accent-soft);
    box-shadow: 0 0 20px var(--vera-accent-10),
                inset 0 0 30px var(--vera-accent-03);
    transform: translateY(-2px);
  }

  // Corner accent
  &::before {
    content: '';
    position: absolute;
    top: -1px;
    left: -1px;
    width: 20px;
    height: 20px;
    border-top: 2px solid var(--vera-accent-soft);
    border-left: 2px solid var(--vera-accent-soft);
    border-radius: 14px 0 0 0;
    opacity: 0;
    transition: opacity 0.3s ease;
  }

  &:hover::before {
    opacity: 1;
  }

  @for $i from 1 through 6 {
    &:nth-of-type(#{$i}) {
      animation-delay: ($i * 0.1) * 1s;
    }
  }
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.8125rem;
  font-weight: 600;
}

.pill {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--vera-accent-15);
  font-size: 0.6875rem;
  color: var(--vera-text);
  animation: pillGlow 4s ease-in-out infinite;
}

.empty-state {
  font-size: 0.75rem;
  color: var(--vera-text-muted);
}

// ============================================
// History List
// ============================================

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 220px;
  overflow-y: auto;
}

.history-item {
  padding: 8px;
  background: color-mix(in srgb, var(--vera-panel) 60%, transparent);
  border-radius: 8px;
  border-left: 3px solid var(--vera-border);
  transition: all 0.2s ease;

  &:hover {
    background: var(--vera-accent-05);
  }

  &.success {
    border-left-color: var(--vera-success);
    &:hover {
      box-shadow: inset 0 0 20px var(--vera-success-05);
    }
  }

  &.error {
    border-left-color: var(--vera-danger);
    &:hover {
      box-shadow: inset 0 0 20px var(--vera-error-05);
    }
  }
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.history-tool {
  font-weight: 600;
  font-size: 0.75rem;
}

.history-meta {
  display: flex;
  gap: 12px;
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
}

.history-error {
  font-size: 0.6875rem;
  color: var(--vera-danger);
  margin-top: 4px;
}

// ============================================
// Server List
// ============================================

.servers-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.server-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px;
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
  border-radius: 8px;
  transition: all 0.2s ease;
  position: relative;

  &::before {
    content: '';
    position: absolute;
    left: 0;
    top: 50%;
    width: 3px;
    height: 0;
    background: var(--vera-accent);
    border-radius: 0 2px 2px 0;
    transform: translateY(-50%);
    transition: height 0.2s ease;
  }

  &:hover {
    background: var(--vera-accent-05);
    &::before {
      height: 60%;
    }
  }
}

.server-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.server-name {
  font-weight: 600;
  font-size: 0.75rem;
}

.server-badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.server-actions {
  display: flex;
  gap: 4px;
}

.mini-btn {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: 1px solid var(--vera-border);
  background: color-mix(in srgb, var(--vera-panel) 60%, transparent);
  color: var(--vera-text);
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

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    &:hover {
      transform: none;
      box-shadow: none;
    }
  }

  &.ok {
    color: var(--vera-success);
    &:hover {
      box-shadow: 0 0 8px var(--vera-success-40);
    }
  }

  &.warn {
    color: var(--vera-warning);
    &:hover {
      box-shadow: 0 0 8px var(--vera-warning-40);
    }
  }
}

// ============================================
// Badges
// ============================================

.badge {
  font-size: 0.6875rem;
  padding: 2px 6px;
  border-radius: 999px;
  border: 1px solid transparent;
  transition: all 0.2s ease;

  &.ok {
    background: var(--vera-success-20);
    color: var(--vera-success);
    border-color: var(--vera-success-50);
    animation: badgeOkPulse 3s ease-in-out infinite;
  }

  &.warn {
    background: var(--vera-warning-20);
    color: var(--vera-warning);
    border-color: rgba(var(--vera-warning-rgb), 0.45);
    animation: badgeWarnPulse 2s ease-in-out infinite;
  }

  &.danger {
    background: var(--vera-error-20);
    color: var(--vera-danger);
    border-color: rgba(var(--vera-error-rgb), 0.45);
    animation: badgeDangerPulse 1.5s ease-in-out infinite;
  }
}

// ============================================
// Verify Grid
// ============================================

.verify-grid {
  display: grid;
  gap: 8px;
}

.verify-item {
  display: grid;
  grid-template-columns: 120px 80px 1fr;
  gap: 8px;
  font-size: 0.75rem;
  padding: 4px;
  border-radius: 4px;
  transition: background 0.2s ease;

  &:hover {
    background: var(--vera-accent-05);
  }

  &.ok { color: var(--vera-success); }
  &.failed { color: var(--vera-danger); }
  &.skipped { color: var(--vera-warning); }
}

// ============================================
// Payload & Inventory
// ============================================

.payload-grid {
  display: grid;
  gap: 6px;
  font-size: 0.75rem;
  color: var(--vera-text-muted);

  strong {
    color: var(--vera-text);
  }
}

.payload-tools {
  font-size: 0.75rem;
  color: var(--vera-text);
  border-top: 1px solid var(--vera-border);
  padding-top: 8px;
}

.inventory-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.inventory-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.inventory-header {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--vera-text-muted);
}

.tool-list {
  font-size: 0.75rem;
  color: var(--vera-text-muted);
  padding: 6px 0;
}

details {
  summary {
    cursor: pointer;
    font-size: 0.75rem;
    color: var(--vera-text);
    margin-bottom: 4px;
    padding: 4px;
    border-radius: 4px;
    transition: background 0.2s ease;

    &:hover {
      background: var(--vera-accent-05);
    }
  }
}

// ============================================
// Keyframe Animations
// ============================================

@keyframes traceFlow {
  0% { stroke-dashoffset: 200; stroke-opacity: 0.3; }
  50% { stroke-dashoffset: 0; stroke-opacity: 0.8; }
  100% { stroke-dashoffset: -200; stroke-opacity: 0.3; }
}

@keyframes nodePulse {
  0%, 100% {
    r: 3;
    filter: drop-shadow(0 0 3px var(--vera-accent-soft));
  }
  50% {
    r: 5;
    filter: drop-shadow(0 0 8px var(--vera-accent));
  }
}

@keyframes gridDrift {
  0% { background-position: 0 0, 0 0; }
  100% { background-position: 200px 200px, 200px 200px; }
}

@keyframes dataStream {
  0% {
    top: -20px;
    opacity: 0;
  }
  10% { opacity: 0.8; }
  90% { opacity: 0.8; }
  100% {
    top: 100%;
    opacity: 0;
  }
}

@keyframes spotPulse {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 0.7; transform: scale(1.2); }
}

@keyframes cardSlideIn {
  0% {
    opacity: 0;
    transform: translateY(15px) scale(0.98);
  }
  60% {
    transform: translateY(-3px) scale(1.01);
  }
  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes headerTrace {
  0%, 100% { width: 50px; opacity: 0.6; }
  50% { width: 80px; opacity: 1; }
}

@keyframes iconSpin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes pillGlow {
  0%, 100% { box-shadow: 0 0 4px transparent; }
  50% { box-shadow: 0 0 8px var(--vera-accent-soft); }
}

@keyframes badgeOkPulse {
  0%, 100% { box-shadow: 0 0 4px transparent; }
  50% { box-shadow: 0 0 6px var(--vera-success-30); }
}

@keyframes badgeWarnPulse {
  0%, 100% { box-shadow: 0 0 4px transparent; }
  50% { box-shadow: 0 0 6px var(--vera-warning-30); }
}

@keyframes badgeDangerPulse {
  0%, 100% { box-shadow: 0 0 4px transparent; }
  50% { box-shadow: 0 0 8px var(--vera-error-40); }
}

// ============================================
// Reduced Motion
// ============================================

@media (prefers-reduced-motion: reduce) {
  .bg-layer,
  .drawer-card,
  .circuit-trace,
  .circuit-node,
  .data-particle,
  .glow-spot,
  .badge,
  .pill {
    animation: none !important;
  }

  .drawer-card {
    opacity: 1;
  }

  .drawer-title svg {
    animation: none;
  }
}
</style>
