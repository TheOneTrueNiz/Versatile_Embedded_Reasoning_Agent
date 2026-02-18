<template>
  <div class="drawer swarm-drawer">
    <!-- Premium animated background layers -->
    <div class="bg-layer bg-constellation">
      <svg class="constellation-svg" viewBox="0 0 400 600" preserveAspectRatio="xMidYMid slice">
        <defs>
          <radialGradient id="nodeGlow">
            <stop offset="0%" stop-color="var(--vera-accent-80)" />
            <stop offset="100%" stop-color="rgba(var(--vera-accent-rgb), 0)" />
          </radialGradient>
        </defs>
        <!-- Connection lines -->
        <line v-for="i in 12" :key="'line-'+i" class="constellation-line"
          :x1="constellationNodes[i % 8].x" :y1="constellationNodes[i % 8].y"
          :x2="constellationNodes[(i + 3) % 8].x" :y2="constellationNodes[(i + 3) % 8].y" />
        <!-- Nodes -->
        <circle v-for="(node, idx) in constellationNodes" :key="'node-'+idx" class="constellation-node"
          :cx="node.x" :cy="node.y" r="3" :style="{ animationDelay: `${idx * 0.3}s` }" />
      </svg>
    </div>
    <div class="bg-layer bg-network-grid"></div>
    <div class="bg-layer bg-energy-flow">
      <span v-for="i in 6" :key="'energy-'+i" class="energy-particle" :style="{ animationDelay: `${i * 0.8}s` }"></span>
    </div>
    <div class="bg-layer bg-orbital">
      <span v-for="i in 4" :key="'orbit-'+i" class="orbital-particle" :style="{ animationDelay: `${i * 1.5}s` }"></span>
    </div>
    <div class="bg-layer bg-pulse-rings">
      <span class="pulse-ring" style="animation-delay: 0s"></span>
      <span class="pulse-ring" style="animation-delay: 2s"></span>
      <span class="pulse-ring" style="animation-delay: 4s"></span>
    </div>

    <header class="drawer-header">
      <div class="drawer-title">
        <Network size="18" />
        <div>
          <div class="drawer-title-text">Quorum / Swarm</div>
          <div class="drawer-subtitle">{{ quorumModeLabel }}</div>
        </div>
      </div>
      <button class="icon-btn" @click="$emit('close')" title="Close swarm">
        <X size="16" />
      </button>
    </header>

    <section class="drawer-card swarm-hero">
      <div class="hero-indicator">
        <SwarmIndicator
          :status="swarmIndicatorStatus"
          :intensity="swarmIndicatorIntensity"
          :active="swarmIndicatorActive"
          :status-class="quorumStatusClass"
          :size="78"
          :sound-enabled="swarmSoundEnabled"
        />
      </div>
      <div class="hero-meta">
        <div><strong>Status:</strong> {{ quorumStatusLabel }}</div>
        <div><strong>Trigger:</strong> {{ quorumTriggerLabel }}</div>
        <div><strong>Quorum:</strong> {{ quorumState.quorum || '—' }}</div>
        <div><strong>Agents:</strong> {{ quorumState.agents?.length || 0 }}</div>
        <div><strong>Consensus:</strong> {{ formatConsensus(quorumState.consensus) }}</div>
        <div><strong>Latency:</strong> {{ quorumState.latency_ms ? `${quorumState.latency_ms} ms` : '—' }}</div>
      </div>
      <div class="hero-summary">
        {{ quorumSummaryText }}
      </div>
    </section>

    <section class="drawer-card control-card">
      <div class="card-header">
        <span>Auto Controls</span>
        <span class="pill">{{ quorumUsageLabel }}</span>
      </div>
      <div class="toggle-row">
        <SliderCheckbox inputId="auto-quorum" labelText="Auto Quorum" v-model="quorumAutoEnabled" />
        <span class="helper-text">Allow Vera to consult a quorum during responses.</span>
      </div>
      <div class="toggle-row">
        <SliderCheckbox inputId="auto-swarm" labelText="Auto Swarm" v-model="swarmAutoEnabled" />
        <span class="helper-text">Allow Vera to coordinate swarms for complex actions.</span>
      </div>
    </section>

    <section class="drawer-card manual-card">
      <div class="card-header">
        <span>Manual Run</span>
        <span v-if="pendingModeLabel" class="pill warn">Queued: {{ pendingModeLabel }}</span>
      </div>
      <div class="form-row">
        <label for="quorum-select">Quorum</label>
        <select id="quorum-select" v-model="selectedQuorumName" :disabled="!availableQuorums.length">
          <option value="">Auto (selector)</option>
          <option v-for="quorum in availableQuorums" :key="quorum.name" :value="quorum.name">
            {{ quorum.is_swarm ? `${quorum.name} (Swarm)` : quorum.name }}
          </option>
        </select>
      </div>
      <div v-if="selectedQuorumProfile" class="profile-card">
        <div class="profile-title">{{ selectedQuorumProfile.name }}</div>
        <div class="profile-meta">
          <span>Mode: {{ selectedQuorumProfile.is_swarm ? 'Swarm' : 'Quorum' }}</span>
          <span>Consensus: {{ formatConsensus(selectedQuorumProfile.consensus) }}</span>
          <span>Lead: {{ selectedQuorumProfile.lead_agent || '—' }}</span>
          <span>Veto: {{ selectedQuorumProfile.veto_agent || '—' }}</span>
        </div>
        <div class="profile-agents">
          Agents: {{ selectedQuorumProfile.agents?.map(formatAgentName).join(', ') || '—' }}
        </div>
      </div>
      <div class="button-row">
        <button class="primary-btn" :class="{ active: pendingQuorumMode === 'quorum' }" @click="queueQuorum">
          Queue Quorum
        </button>
        <button class="secondary-btn" :class="{ active: pendingQuorumMode === 'swarm' }" @click="queueSwarm">
          Queue Swarm
        </button>
        <button v-if="pendingQuorumMode" class="ghost-btn" @click="clearQueuedMode">Clear</button>
      </div>
      <div class="helper-text">Queued runs apply to your next message only.</div>
    </section>

    <section class="drawer-card custom-card">
      <div class="card-header">
        <span>Custom Quorum</span>
      </div>
      <div class="form-row">
        <label for="custom-quorum-select">Saved Presets</label>
        <select id="custom-quorum-select" v-model="customQuorumPreset">
          <option value="">New custom quorum</option>
          <option v-for="quorum in customQuorums" :key="quorum.name" :value="quorum.name">
            {{ quorum.name }}
          </option>
        </select>
      </div>
      <div class="form-row">
        <label for="custom-quorum-name">Name</label>
        <input id="custom-quorum-name" v-model="customQuorumName" type="text" placeholder="Architect" />
      </div>
      <div class="form-row">
        <label for="custom-quorum-purpose">Purpose</label>
        <input id="custom-quorum-purpose" v-model="customQuorumPurpose" type="text" placeholder="Short intent statement" />
      </div>
      <div class="form-row">
        <label for="custom-quorum-description">Description</label>
        <textarea id="custom-quorum-description" v-model="customQuorumDescription" rows="2" placeholder="Optional detail"></textarea>
      </div>
      <div class="form-row">
        <label for="custom-quorum-consensus">Consensus</label>
        <select id="custom-quorum-consensus" v-model="customQuorumConsensus">
          <option v-for="option in consensusOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>
      <div class="form-row">
        <SliderCheckbox inputId="custom-swarm-mode" labelText="Treat as Swarm" v-model="customQuorumIsSwarm" />
        <span class="helper-text">Uses swarm gating, limits, and cost warnings.</span>
      </div>
      <div class="agent-grid">
        <button
          v-for="agent in agentOptions"
          :key="agent.name"
          type="button"
          class="agent-chip"
          :class="{ active: customQuorumAgents.includes(agent.name) }"
          @click="toggleCustomAgent(agent.name)"
        >
          {{ agent.label }}
        </button>
      </div>
      <div class="form-row">
        <label for="custom-quorum-lead">Lead</label>
        <select id="custom-quorum-lead" v-model="customQuorumLead">
          <option value="">None</option>
          <option v-for="agent in customQuorumAgents" :key="agent" :value="agent">
            {{ agent }}
          </option>
        </select>
      </div>
      <div class="form-row">
        <label for="custom-quorum-veto">Veto</label>
        <select id="custom-quorum-veto" v-model="customQuorumVeto">
          <option value="">None</option>
          <option v-for="agent in customQuorumAgents" :key="agent" :value="agent">
            {{ agent }}
          </option>
        </select>
      </div>
      <div class="button-row">
        <button class="primary-btn" :disabled="customQuorumSaving" @click="saveCustomQuorum">
          Save Custom
        </button>
        <button class="secondary-btn" :disabled="!customQuorumPreset" @click="deleteCustomQuorumPreset">
          Delete Custom
        </button>
        <button class="ghost-btn" @click="clearCustomForm">Clear</button>
      </div>
      <div class="helper-text">Large quorums increase token usage and latency.</div>
    </section>
  </div>

  <ConfirmationDialog
    v-model:visible="showQueueWarning"
    title="High Cost Operation"
    :message="queueWarningMessage"
    confirm-label="Continue"
    cancel-label="Cancel"
    :is-warning="true"
    @confirm="confirmQueueAction"
  />
  <ConfirmationDialog
    v-model:visible="showCustomQuorumWarning"
    title="Large Quorum Warning"
    :message="customQuorumWarningMessage"
    confirm-label="Continue"
    cancel-label="Cancel"
    :is-warning="true"
    @confirm="confirmLargeCustomQuorum"
  />
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { Network, X } from 'lucide-vue-next';
import SliderCheckbox from '@/components/controls/SliderCheckbox.vue';
import SwarmIndicator from '@/components/controls/SwarmIndicator.vue';
import ConfirmationDialog from '@/components/controls/ConfirmationDialog.vue';
import { showToast } from '@/libs/utils/general-utils';
import {
  pendingQuorumMode,
  pendingQuorumName,
  quorumAutoEnabled,
  swarmAutoEnabled,
  quorumUiMode,
  quorumUiActive,
  isLoading,
  a11ySoundEffects,
  a11yAutoPlayMedia
} from '@/libs/state-management/state';

defineEmits(['close']);

// Constellation node positions for network visualization
const constellationNodes = [
  { x: 80, y: 100 },
  { x: 320, y: 80 },
  { x: 200, y: 180 },
  { x: 60, y: 280 },
  { x: 340, y: 260 },
  { x: 150, y: 400 },
  { x: 280, y: 380 },
  { x: 200, y: 520 }
];

const quorumStatus = ref(null);
const quorumCatalog = ref([]);
const selectedQuorumName = ref('');
const customQuorumName = ref('');
const customQuorumPurpose = ref('');
const customQuorumDescription = ref('');
const customQuorumConsensus = ref('majority_vote');
const customQuorumAgents = ref([]);
const customQuorumLead = ref('');
const customQuorumVeto = ref('');
const customQuorumPreset = ref('');
const customQuorumIsSwarm = ref(false);
const customQuorumSaving = ref(false);
const showQueueWarning = ref(false);
const queueWarningMessage = ref('');
const pendingQueueAction = ref(null);
const showCustomQuorumWarning = ref(false);
const customQuorumWarningMessage = ref('');
const pendingCustomQuorumPayload = ref(null);
const quorumSyncInFlight = ref(false);
const quorumSettingsReady = ref(false);

// Polling interval for real-time updates (5 seconds)
const POLL_INTERVAL_MS = 5000;
let pollIntervalId = null;

const agentOptions = [
  { name: 'Planner', label: 'Planner' },
  { name: 'Skeptic', label: 'Skeptic' },
  { name: 'Optimizer', label: 'Optimizer' },
  { name: 'Safety', label: 'Safety' },
  { name: 'SafetyLead', label: 'Safety Lead' },
  { name: 'QualityAssurance', label: 'Quality Assurance' },
  { name: 'Researcher', label: 'Researcher' },
  { name: 'Integrator', label: 'Integrator' },
  { name: 'MemoryCurator', label: 'Memory Curator' },
  { name: 'Architect', label: 'Architect' },
  { name: 'SystemArchitect', label: 'System Architect' },
  { name: 'Engineer', label: 'Engineer' },
  { name: 'Programmer', label: 'Programmer' },
  { name: 'Strategist', label: 'Strategist' },
  { name: 'Writer', label: 'Writer' },
  { name: 'Tutor', label: 'Tutor' },
  { name: 'Creative', label: 'Creative' },
  { name: 'Secretary', label: 'Secretary' },
  { name: 'Tasker', label: 'Tasker' },
  { name: 'EventPlanner', label: 'Event Planner' },
  { name: 'Scheduler', label: 'Scheduler' },
  { name: 'Chef', label: 'Chef' },
  { name: 'DealFinder', label: 'Deal Finder' }
];

const consensusOptions = [
  { value: 'majority_vote', label: 'Majority Vote' },
  { value: 'weighted_scoring', label: 'Weighted Scoring' },
  { value: 'synthesis', label: 'Synthesis' },
  { value: 'veto_authority', label: 'Veto Authority' }
];

const quorumState = computed(() => quorumStatus.value?.state || {});
const availableQuorums = computed(() =>
  (quorumCatalog.value || []).filter((quorum) => !quorum.is_swarm || quorum.source === 'custom')
);
const customQuorums = computed(() => (quorumCatalog.value || []).filter((quorum) => quorum.source === 'custom'));
const selectedQuorumProfile = computed(() =>
  availableQuorums.value.find((quorum) => quorum.name === selectedQuorumName.value)
);
const quorumStatusLabel = computed(() => quorumState.value.status || 'idle');
const quorumModeLabel = computed(() => {
  const rawMode = quorumState.value.mode || 'quorum';
  const baseMode = rawMode === 'swarm' ? 'Swarm' : 'Quorum';
  const quorumName = quorumState.value.quorum || '';
  if (quorumName && quorumName !== 'Swarm' && quorumName !== baseMode) {
    return `${baseMode} · ${quorumName}`;
  }
  return baseMode;
});
const quorumTriggerLabel = computed(() => quorumState.value.trigger || 'auto');
const quorumSummaryText = computed(() => quorumState.value.summary || quorumState.value.reason || 'No swarm/quorum activity recorded.');
const quorumUsageLabel = computed(() => {
  if (!quorumStatus.value?.settings) {
    return 'Usage: —';
  }
  const settings = quorumStatus.value.settings;
  const quorumCalls = settings.quorum_calls ?? 0;
  const quorumMax = settings.quorum_max_calls ?? '—';
  const swarmCalls = settings.swarm_calls ?? 0;
  const swarmMax = settings.swarm_max_calls ?? '—';
  return `Quorum ${quorumCalls}/${quorumMax} · Swarm ${swarmCalls}/${swarmMax}`;
});
const quorumStatusClass = computed(() => {
  const status = quorumStatusLabel.value;
  if (status === 'completed') return 'ok';
  if (status === 'running') return 'warn';
  if (status === 'blocked' || status === 'error') return 'danger';
  return 'neutral';
});
const immediateQuorumMode = computed(() => {
  if (!isLoading.value || !quorumUiActive.value) {
    return null;
  }
  return quorumUiMode.value;
});
const swarmIndicatorStatus = computed(() => {
  const status = quorumStatusLabel.value;
  if (status === 'blocked' || status === 'error') {
    return 'error';
  }
  if (status === 'running' || status === 'completed') {
    const mode = String(quorumState.value.mode || 'quorum').toLowerCase();
    return mode === 'swarm' ? 'swarm' : 'quorum';
  }
  if (immediateQuorumMode.value) {
    return immediateQuorumMode.value;
  }
  return 'idle';
});
const swarmIndicatorIntensity = computed(() => {
  if (swarmIndicatorStatus.value === 'swarm') {
    if (quorumStatusLabel.value === 'running' || immediateQuorumMode.value === 'swarm') {
      return 0.9;
    }
    return 0.6;
  }
  if (swarmIndicatorStatus.value === 'quorum') {
    if (quorumStatusLabel.value === 'running' || immediateQuorumMode.value === 'quorum') {
      return 0.7;
    }
    return 0.35;
  }
  return 0.15;
});
const swarmIndicatorActive = computed(() => quorumStatusLabel.value === 'running' || Boolean(immediateQuorumMode.value));
const swarmSoundEnabled = computed(() => a11ySoundEffects.value && a11yAutoPlayMedia.value);
const pendingModeLabel = computed(() => {
  if (pendingQuorumMode.value === 'swarm') {
    return pendingQuorumName.value ? `Swarm · ${pendingQuorumName.value}` : 'Swarm';
  }
  if (pendingQuorumMode.value === 'quorum') {
    return pendingQuorumName.value ? `Quorum · ${pendingQuorumName.value}` : 'Quorum';
  }
  return '';
});

const formatConsensus = (value) => {
  if (!value) return '—';
  return String(value).replace(/_/g, ' ');
};

const formatAgentName = (value) => {
  if (!value) return '';
  return value.replace(/([A-Z])/g, ' $1').trim();
};

const fetchQuorumStatus = async () => {
  try {
    const response = await fetch('/api/quorum/status');
    if (!response.ok) {
      throw new Error('Failed to fetch quorum status');
    }
    quorumStatus.value = await response.json();
    if (!quorumSettingsReady.value && quorumStatus.value?.settings) {
      quorumAutoEnabled.value = Boolean(quorumStatus.value.settings.quorum_auto_enabled);
      swarmAutoEnabled.value = Boolean(quorumStatus.value.settings.swarm_auto_enabled);
      quorumSettingsReady.value = true;
    }
  } catch (error) {
    showToast('Unable to fetch quorum status');
    console.error(error);
  }
};

const fetchQuorumCatalog = async () => {
  try {
    const response = await fetch('/api/quorum/list');
    if (!response.ok) {
      throw new Error('Failed to fetch quorum catalog');
    }
    const data = await response.json();
    quorumCatalog.value = Array.isArray(data) ? data : (data?.quorums || []);
  } catch (error) {
    showToast('Unable to fetch quorum catalog');
    console.error(error);
  }
};

const refreshAll = async () => {
  await Promise.all([fetchQuorumStatus(), fetchQuorumCatalog()]);
};

const syncQuorumSettings = async () => {
  if (quorumSyncInFlight.value) return;
  quorumSyncInFlight.value = true;
  try {
    const response = await fetch('/api/quorum/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        quorum_auto_enabled: Boolean(quorumAutoEnabled.value),
        swarm_auto_enabled: Boolean(swarmAutoEnabled.value)
      })
    });
    if (!response.ok) {
      throw new Error('Failed to update quorum settings');
    }
    const data = await response.json();
    if (data?.settings) {
      quorumAutoEnabled.value = Boolean(data.settings.quorum_auto_enabled);
      swarmAutoEnabled.value = Boolean(data.settings.swarm_auto_enabled);
    }
  } catch (error) {
    showToast('Unable to update quorum settings');
    console.error(error);
  } finally {
    quorumSyncInFlight.value = false;
  }
};

const requestQueueConfirmation = (message, action) => {
  queueWarningMessage.value = message;
  pendingQueueAction.value = action;
  showQueueWarning.value = true;
};

const confirmQueueAction = () => {
  if (pendingQueueAction.value) {
    pendingQueueAction.value();
  }
  pendingQueueAction.value = null;
};

const queueQuorum = () => {
  const targetName = selectedQuorumName.value || '';
  const profile = availableQuorums.value.find((quorum) => quorum.name === targetName);
  const agentCount = profile?.agents?.length || 0;
  const isSwarmSelection = Boolean(profile?.is_swarm);
  const proceed = () => {
    pendingQuorumMode.value = isSwarmSelection ? 'swarm' : 'quorum';
    pendingQuorumName.value = targetName;
    const label = pendingQuorumName.value
      ? `${isSwarmSelection ? 'Swarm' : 'Quorum'} · ${pendingQuorumName.value}`
      : (isSwarmSelection ? 'Swarm' : 'Quorum');
    showToast(`Next message will use ${label}`);
  };
  if (isSwarmSelection) {
    requestQueueConfirmation('Custom swarm uses swarm gating/limits and can be expensive. Continue?', proceed);
    return;
  }
  if (agentCount >= 5) {
    requestQueueConfirmation(
      `This quorum uses ${agentCount} agents. Large quorums increase token usage and latency. Continue?`,
      proceed
    );
    return;
  }
  proceed();
};

const queueSwarm = () => {
  requestQueueConfirmation('Swarm uses the full multi-agent stack and can be expensive. Continue?', () => {
    pendingQuorumMode.value = 'swarm';
    pendingQuorumName.value = '';
    showToast('Next message will use Swarm');
  });
};

const clearQueuedMode = () => {
  pendingQuorumMode.value = null;
  pendingQuorumName.value = '';
};

const buildCustomQuorumPayload = () => {
  const name = customQuorumName.value.trim();
  const purpose = customQuorumPurpose.value.trim();
  const description = customQuorumDescription.value.trim();
  const agents = customQuorumAgents.value.map((agent) => ({
    name: agent,
    is_lead: agent === customQuorumLead.value,
    veto_authority: agent === customQuorumVeto.value,
    weight: 1.0
  }));

  if (!name) {
    showToast('Custom quorum name is required.');
    return null;
  }
  if (!purpose) {
    showToast('Add a short purpose for the custom quorum.');
    return null;
  }
  if (agents.length < 2) {
    showToast('Select at least two agents.');
    return null;
  }
  if (customQuorumConsensus.value === 'veto_authority' && !customQuorumVeto.value) {
    showToast('Select a veto agent for veto authority.');
    return null;
  }

  return {
    name,
    purpose,
    description,
    consensus: customQuorumConsensus.value,
    agents,
    is_swarm: Boolean(customQuorumIsSwarm.value),
    lead_agent: customQuorumLead.value,
    veto_agent: customQuorumVeto.value
  };
};

const saveCustomQuorum = async () => {
  const payload = buildCustomQuorumPayload();
  if (!payload) return;
  if (payload.is_swarm && payload.agents.length >= 6) {
    customQuorumWarningMessage.value = `This swarm uses ${payload.agents.length} agents. Continue?`;
    pendingCustomQuorumPayload.value = payload;
    showCustomQuorumWarning.value = true;
    return;
  }
  await persistCustomQuorum(payload);
};

const confirmLargeCustomQuorum = async () => {
  if (!pendingCustomQuorumPayload.value) return;
  const payload = pendingCustomQuorumPayload.value;
  pendingCustomQuorumPayload.value = null;
  await persistCustomQuorum(payload);
};

const persistCustomQuorum = async (payload) => {
  customQuorumSaving.value = true;
  try {
    const response = await fetch('/api/quorum/custom', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      throw new Error('Failed to save custom quorum');
    }
    await fetchQuorumCatalog();
    customQuorumPreset.value = payload.name;
    showToast('Custom quorum saved');
  } catch (error) {
    showToast('Unable to save custom quorum');
    console.error(error);
  } finally {
    customQuorumSaving.value = false;
  }
};

const deleteCustomQuorumPreset = async () => {
  if (!customQuorumPreset.value) return;
  try {
    const response = await fetch('/api/quorum/custom/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: customQuorumPreset.value })
    });
    if (!response.ok) {
      throw new Error('Failed to delete custom quorum');
    }
    await fetchQuorumCatalog();
    customQuorumPreset.value = '';
    clearCustomForm();
    showToast('Custom quorum deleted');
  } catch (error) {
    showToast('Unable to delete custom quorum');
    console.error(error);
  }
};

const clearCustomForm = () => {
  customQuorumName.value = '';
  customQuorumPurpose.value = '';
  customQuorumDescription.value = '';
  customQuorumConsensus.value = 'majority_vote';
  customQuorumAgents.value = [];
  customQuorumLead.value = '';
  customQuorumVeto.value = '';
  customQuorumIsSwarm.value = false;
};

const toggleCustomAgent = (agentName) => {
  const current = new Set(customQuorumAgents.value);
  if (current.has(agentName)) {
    current.delete(agentName);
  } else {
    current.add(agentName);
  }
  customQuorumAgents.value = Array.from(current);
};

const applyCustomPreset = (preset) => {
  if (!preset) {
    clearCustomForm();
    return;
  }
  customQuorumName.value = preset.name || '';
  customQuorumPurpose.value = preset.purpose || '';
  customQuorumDescription.value = preset.description || '';
  customQuorumConsensus.value = preset.consensus || 'majority_vote';
  customQuorumAgents.value = Array.isArray(preset.agents) ? [...preset.agents] : [];
  customQuorumLead.value = preset.lead_agent || '';
  customQuorumVeto.value = preset.veto_agent || '';
  customQuorumIsSwarm.value = Boolean(preset.is_swarm);
};

watch([quorumAutoEnabled, swarmAutoEnabled], () => {
  if (!quorumSettingsReady.value) return;
  syncQuorumSettings();
});

watch(customQuorumAgents, (agents) => {
  if (!agents.includes(customQuorumLead.value)) {
    customQuorumLead.value = '';
  }
  if (!agents.includes(customQuorumVeto.value)) {
    customQuorumVeto.value = '';
  }
});

watch(customQuorumPreset, (value) => {
  const preset = customQuorums.value.find((item) => item.name === value);
  if (preset) {
    applyCustomPreset(preset);
  } else if (!value) {
    clearCustomForm();
  }
});

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
// VERA SwarmDrawer Premium Animation System
// Network constellation, orbital particles, energy flow
// Uses theme CSS variables for consistency
// ============================================

// Secondary accent for visual variety (purple/blue tones)
$secondary-accent: var(--vera-secondary);
$secondary-accent-soft: var(--vera-secondary-60);

.swarm-drawer {
  position: relative;
  height: 100%;
  padding: 20px 18px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  overflow-x: hidden;
  background: var(--vera-drawer-bg);

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

// Layer 1: SVG Constellation network
.bg-constellation {
  z-index: 1;
  opacity: 0.6;

  .constellation-svg {
    width: 100%;
    height: 100%;
  }

  .constellation-line {
    stroke: var(--vera-accent-soft);
    stroke-width: 1;
    stroke-dasharray: 8 4;
    animation: constellationPulse 4s ease-in-out infinite;

    @for $i from 1 through 12 {
      &:nth-child(#{$i + 1}) {
        animation-delay: ($i * 0.2) * 1s;
        opacity: 0.3 + ($i % 4) * 0.15;
      }
    }
  }

  .constellation-node {
    fill: var(--vera-accent);
    filter: drop-shadow(0 0 4px var(--vera-accent));
    animation: nodeGlow 3s ease-in-out infinite;
  }
}

// Layer 2: Network grid background
.bg-network-grid {
  z-index: 2;
  background:
    radial-gradient(circle, var(--vera-accent-soft) 0 1px, transparent 1px 100%),
    radial-gradient(circle at 30% 70%, var(--vera-secondary-08), transparent 50%);
  background-size: 32px 32px, 100% 100%;
  animation: networkDrift 24s linear infinite;
  opacity: 0.5;
}

// Layer 3: Energy flow particles
.bg-energy-flow {
  z-index: 3;

  .energy-particle {
    position: absolute;
    width: 6px;
    height: 6px;
    background: var(--vera-accent);
    border-radius: 50%;
    filter: blur(1px);
    animation: energyFlow 6s ease-in-out infinite;

    @for $i from 1 through 6 {
      &:nth-child(#{$i}) {
        left: (10 + ($i - 1) * 15) * 1%;
        top: (20 + (($i - 1) % 3) * 25) * 1%;
        animation-duration: (5 + ($i % 3)) * 1s;
      }
    }
  }
}

// Layer 4: Orbital particles around center
.bg-orbital {
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: center;

  .orbital-particle {
    position: absolute;
    width: 4px;
    height: 4px;
    background: $secondary-accent-soft;
    border-radius: 50%;
    animation: particleOrbit 12s linear infinite;

    @for $i from 1 through 4 {
      &:nth-child(#{$i}) {
        animation-duration: (10 + $i * 3) * 1s;
        width: (3 + $i) * 1px;
        height: (3 + $i) * 1px;
      }
    }
  }
}

// Layer 5: Expanding pulse rings
.bg-pulse-rings {
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: center;

  .pulse-ring {
    position: absolute;
    width: 120px;
    height: 120px;
    border: 1px solid var(--vera-accent-soft);
    border-radius: 50%;
    animation: pulseExpand 6s ease-out infinite;
    opacity: 0;
  }
}

// ============================================
// Content (above background layers)
// ============================================

.swarm-drawer > *:not(.bg-layer) {
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
  position: relative;

  // Animated underline
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
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-soft);
    box-shadow: 0 0 8px var(--vera-accent-soft);
    transform: scale(1.05);
  }
}

// ============================================
// Cards with staggered entry
// ============================================

.drawer-card {
  border: 1px solid var(--vera-border);
  border-radius: 14px;
  padding: 14px;
  background: var(--vera-drawer-card-bg);
  backdrop-filter: blur(16px);
  display: flex;
  flex-direction: column;
  gap: 12px;
  opacity: 0;
  animation: cardSlideIn 0.5s ease forwards;
  transition: all 0.3s ease;

  &:hover {
    border-color: var(--vera-accent-soft);
    box-shadow: 0 0 20px var(--vera-accent-10),
                inset 0 0 30px rgba(var(--vera-accent-rgb), 0.03);
    transform: translateY(-2px);
  }

  // Staggered animation
  @for $i from 1 through 5 {
    &:nth-of-type(#{$i}) {
      animation-delay: ($i * 0.1) * 1s;
    }
  }
}

// ============================================
// Hero Section
// ============================================

.swarm-hero {
  display: grid !important;
  grid-template-columns: 90px 1fr !important;
  flex-direction: unset !important;
  gap: 12px;
  align-items: start;
  position: relative;
  overflow: visible;

  // Subtle inner glow
  &::before {
    content: '';
    position: absolute;
    top: 50%;
    left: 45px;
    width: 80px;
    height: 80px;
    background: radial-gradient(circle, var(--vera-accent-soft), transparent 70%);
    transform: translate(-50%, -50%);
    animation: heroGlow 4s ease-in-out infinite;
    pointer-events: none;
  }
}

.hero-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 2;
  min-width: 90px;
  min-height: 90px;
  grid-row: 1 / 3; // Span both rows

  // Ensure SwarmIndicator is visible
  :deep(.swarm-indicator) {
    min-width: 78px;
    min-height: 78px;
    display: grid !important;
  }
}

.hero-meta {
  display: grid;
  gap: 6px;
  font-size: 0.75rem;
  color: var(--vera-text-muted);

  strong {
    color: var(--vera-text);
  }
}

.hero-summary {
  grid-column: span 2;
  font-size: 0.75rem;
  color: var(--vera-text);
  padding-top: 8px;
  border-top: 1px solid var(--vera-border);
  line-height: 1.5;
}

// ============================================
// Card Headers & Pills
// ============================================

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
  font-size: 0.6875rem;
  color: var(--vera-text);
  background: var(--vera-accent-15);
  border: 1px solid transparent;
  animation: pillGlow 4s ease-in-out infinite;

  &.warn {
    color: var(--vera-warning);
    background: var(--vera-warning-15);
    animation: pillWarnGlow 2s ease-in-out infinite;
  }
}

// ============================================
// Forms
// ============================================

.toggle-row {
  display: grid;
  gap: 6px;
}

.form-row {
  display: grid;
  gap: 6px;
  font-size: 0.75rem;
  color: var(--vera-text-muted);
}

.form-row input,
.form-row select,
.form-row textarea {
  background: color-mix(in srgb, var(--vera-panel) 60%, transparent);
  border: 1px solid var(--vera-border);
  border-radius: 10px;
  padding: 8px;
  color: var(--vera-text);
  transition: all 0.2s ease;

  &:focus {
    outline: none;
    border-color: var(--vera-accent-soft);
    box-shadow: 0 0 8px var(--vera-accent-soft);
  }
}

// ============================================
// Profile Card
// ============================================

.profile-card {
  border: 1px solid var(--vera-border);
  border-radius: 12px;
  padding: 10px;
  display: grid;
  gap: 6px;
  background: color-mix(in srgb, var(--vera-panel) 60%, transparent);
  position: relative;
  overflow: hidden;

  // Scan line effect
  &::after {
    content: '';
    position: absolute;
    width: 100%;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--vera-accent-soft), transparent);
    animation: profileScan 4s linear infinite;
    opacity: 0.5;
  }
}

.profile-title {
  font-weight: 600;
  color: var(--vera-accent);
}

.profile-meta,
.profile-agents {
  font-size: 0.75rem;
  color: var(--vera-text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

// ============================================
// Buttons
// ============================================

.button-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.primary-btn,
.secondary-btn,
.ghost-btn {
  border-radius: 10px;
  border: 1px solid var(--vera-border);
  padding: 8px 12px;
  font-size: 0.75rem;
  cursor: pointer;
  color: var(--vera-text);
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;

  // Shimmer effect on hover
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

  &:hover {
    box-shadow: 0 0 15px var(--vera-accent-soft);
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

.ghost-btn {
  background: transparent;

  &:hover {
    background: var(--vera-accent-05);
    border-color: var(--vera-accent-soft);
  }
}

.primary-btn.active,
.secondary-btn.active {
  box-shadow: 0 0 15px var(--vera-accent-soft),
              inset 0 0 10px var(--vera-accent-10);
  animation: activeGlow 2s ease-in-out infinite;
}

// ============================================
// Agent Grid
// ============================================

.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 8px;
}

.agent-chip {
  padding: 6px 8px;
  border-radius: 999px;
  border: 1px solid var(--vera-border);
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
  font-size: 0.6875rem;
  cursor: pointer;
  color: var(--vera-text-muted);
  transition: all 0.2s ease;
  position: relative;

  &:hover {
    border-color: var(--vera-accent-soft);
    color: var(--vera-text);
    transform: scale(1.02);
  }

  &.active {
    color: var(--vera-text);
    border-color: var(--vera-accent);
    background: var(--vera-accent-10);
    box-shadow: 0 0 12px var(--vera-accent-soft),
                inset 0 0 8px var(--vera-accent-10);
    animation: chipPulse 3s ease-in-out infinite;

    // Node indicator
    &::before {
      content: '';
      position: absolute;
      top: 50%;
      left: 6px;
      width: 4px;
      height: 4px;
      background: var(--vera-accent);
      border-radius: 50%;
      transform: translateY(-50%);
      animation: nodeGlow 2s ease-in-out infinite;
    }
  }
}

.helper-text {
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
}

// ============================================
// Keyframe Animations
// ============================================

@keyframes constellationPulse {
  0%, 100% { stroke-opacity: 0.3; stroke-dashoffset: 0; }
  50% { stroke-opacity: 0.7; stroke-dashoffset: 12; }
}

@keyframes nodeGlow {
  0%, 100% {
    filter: drop-shadow(0 0 3px var(--vera-accent-soft));
    r: 3;
  }
  50% {
    filter: drop-shadow(0 0 8px var(--vera-accent));
    r: 4;
  }
}

@keyframes networkDrift {
  0% { background-position: 0 0, 0 0; }
  100% { background-position: 200px 150px, 0 0; }
}

@keyframes energyFlow {
  0% {
    transform: translate(0, 0) scale(0.5);
    opacity: 0;
  }
  20% { opacity: 0.8; }
  50% {
    transform: translate(40px, -30px) scale(1);
    opacity: 0.6;
  }
  80% { opacity: 0.4; }
  100% {
    transform: translate(80px, -60px) scale(0.3);
    opacity: 0;
  }
}

@keyframes particleOrbit {
  0% { transform: rotate(0deg) translateX(60px) rotate(0deg); }
  100% { transform: rotate(360deg) translateX(60px) rotate(-360deg); }
}

@keyframes pulseExpand {
  0% {
    transform: scale(0.5);
    opacity: 0.6;
  }
  100% {
    transform: scale(3);
    opacity: 0;
  }
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

@keyframes headerGlow {
  0%, 100% { width: 60px; opacity: 0.6; }
  50% { width: 100px; opacity: 1; }
}

@keyframes heroGlow {
  0%, 100% { opacity: 0.3; transform: translate(-50%, -50%) scale(1); }
  50% { opacity: 0.6; transform: translate(-50%, -50%) scale(1.2); }
}

@keyframes pillGlow {
  0%, 100% { box-shadow: 0 0 4px transparent; }
  50% { box-shadow: 0 0 8px var(--vera-accent-soft); }
}

@keyframes pillWarnGlow {
  0%, 100% { box-shadow: 0 0 4px transparent; }
  50% { box-shadow: 0 0 8px var(--vera-warning-40); }
}

@keyframes profileScan {
  0% { top: -2px; }
  100% { top: calc(100% + 2px); }
}

@keyframes activeGlow {
  0%, 100% { box-shadow: 0 0 15px var(--vera-accent-soft); }
  50% { box-shadow: 0 0 25px var(--vera-accent); }
}

@keyframes chipPulse {
  0%, 100% { box-shadow: 0 0 10px var(--vera-accent-soft); }
  50% { box-shadow: 0 0 16px var(--vera-accent); }
}

// ============================================
// Reduced Motion
// ============================================

@media (prefers-reduced-motion: reduce) {
  .bg-layer,
  .drawer-card,
  .constellation-line,
  .constellation-node,
  .energy-particle,
  .orbital-particle,
  .pulse-ring,
  .pill,
  .agent-chip.active,
  .primary-btn.active,
  .secondary-btn.active {
    animation: none !important;
  }

  .drawer-card {
    opacity: 1;
  }
}
</style>
