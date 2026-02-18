<template>
  <div class="drawer self-drawer">
    <!-- Premium animated background layers -->
    <div class="bg-layer bg-dna-helix">
      <svg class="dna-svg" viewBox="0 0 100 800" preserveAspectRatio="xMidYMid slice">
        <path class="dna-strand strand-1" d="M30,0 Q70,100 30,200 Q-10,300 30,400 Q70,500 30,600 Q-10,700 30,800" />
        <path class="dna-strand strand-2" d="M70,0 Q30,100 70,200 Q110,300 70,400 Q30,500 70,600 Q110,700 70,800" />
        <g class="dna-rungs">
          <line v-for="i in 20" :key="'rung-'+i" class="dna-rung"
            x1="35" :y1="i * 40" x2="65" :y2="i * 40" />
        </g>
      </svg>
    </div>
    <div class="bg-layer bg-evolution-particles">
      <span v-for="i in 12" :key="'evo-'+i" class="evo-particle" :style="{ animationDelay: `${i * 0.4}s` }"></span>
    </div>
    <div class="bg-layer bg-neural-web"></div>
    <div class="bg-layer bg-energy-rings">
      <span v-for="i in 3" :key="'ring-'+i" class="energy-ring" :style="{ animationDelay: `${i * 2}s` }"></span>
    </div>

    <header class="drawer-header">
      <div class="drawer-title">
        <Sparkles size="18" />
        <div>
          <div class="drawer-title-text">Self-Improvement</div>
          <div class="drawer-subtitle">Evolution controls & budgets</div>
        </div>
      </div>
      <button class="icon-btn" @click="$emit('close')" title="Close self-improvement">
        <X size="16" />
      </button>
    </header>

    <section class="drawer-card status-card">
      <div class="card-header">
        <span>Ops Status</span>
        <span :class="['pill', selfImproveStatusClass]">{{ selfImproveStatusLabel }}</span>
      </div>
      <div v-if="!selfImproveStatus" class="empty-state">Self-improvement status not loaded yet.</div>
      <div v-else class="card-grid">
        <div><strong>Running:</strong> {{ selfImproveStatus.running ? 'yes' : 'no' }}</div>
        <div><strong>Action:</strong> {{ selfImproveStatus.action || '—' }}</div>
        <div><strong>Started:</strong> {{ formatTimestamp(selfImproveStatus.started_at) }}</div>
        <div><strong>Finished:</strong> {{ formatTimestamp(selfImproveStatus.finished_at) }}</div>
        <div v-if="selfImproveStatus.last_error" class="error-text">
          <strong>Error:</strong> {{ selfImproveStatus.last_error }}
        </div>
      </div>
    </section>

    <section class="drawer-card actions-card">
      <div class="card-header">
        <span>Run Actions</span>
        <span class="pill">Budgeted</span>
      </div>
      <div class="action-grid">
        <button class="primary-btn" :disabled="selfImproveLocked" @click="runRedTeam">Run Red-Team</button>
        <button class="secondary-btn" :disabled="selfImproveLocked" @click="runArchitect">Run Architect</button>
        <button class="secondary-btn" :disabled="selfImproveLocked" @click="runMemvidExport">Export Memvid</button>
        <button class="secondary-btn" :disabled="selfImproveLocked" @click="runExportSpecialist">Export Specialist</button>
        <button class="secondary-btn" :disabled="selfImproveLocked" @click="runRegression">Run Regression</button>
        <button class="secondary-btn" :disabled="selfImproveLocked" @click="trainRewardModel">Train Reward Model</button>
      </div>
      <div class="action-row">
        <SliderCheckbox inputId="self-redteam-llm" labelText="Use LLM" v-model="selfImproveUseLlm" />
        <div class="input-group">
          <label for="self-regression-limit">Regression limit</label>
          <input id="self-regression-limit" v-model.number="selfImproveRegressionLimit" type="number" min="0" step="1" />
        </div>
        <div class="input-group">
          <label for="self-memvid-limit">Memvid limit</label>
          <input id="self-memvid-limit" v-model.number="selfImproveMemvidLimit" type="number" min="0" step="1" />
        </div>
      </div>
      <div class="helper-text">Budget caps apply to LLM-driven actions.</div>
    </section>

    <section class="drawer-card patch-card">
      <div class="card-header">
        <span>Simulate Patch</span>
      </div>
      <textarea
        v-model="selfImprovePatchText"
        rows="3"
        placeholder='[{"op":"replace","path":"/agent_profile/name","value":"Architect"}]'
      ></textarea>
      <button class="secondary-btn" :disabled="selfImproveLocked" @click="simulatePatch">Simulate Patch</button>
      <div v-if="selfImprovePatchResult" class="patch-result">
        <div><strong>Patch valid:</strong> {{ selfImprovePatchResult.valid ? 'yes' : 'no' }}</div>
        <div v-if="selfImprovePatchResult.errors?.length">
          <strong>Errors:</strong> {{ selfImprovePatchResult.errors.join('; ') }}
        </div>
      </div>
      <div v-if="selfImproveError" class="error-text">{{ selfImproveError }}</div>
    </section>

    <section class="drawer-card budget-card">
      <div class="card-header">
        <span>Budget</span>
        <span :class="['pill', selfBudgetStatusClass]">{{ selfBudgetStatusLabel }}</span>
      </div>
      <div v-if="!selfBudget" class="empty-state">Budget status not loaded yet.</div>
      <div v-else class="card-grid">
        <div><strong>Spent:</strong> {{ selfBudgetSpentLabel }}</div>
        <div><strong>Tokens:</strong> {{ selfBudgetTokenLabel }}</div>
        <div><strong>Calls:</strong> {{ selfBudgetCallLabel }}</div>
        <div><strong>Last update:</strong> {{ formatTimestamp(selfBudget.state?.updated_at) }}</div>
        <div><strong>Config source:</strong> {{ selfBudget.config_source || 'env' }}</div>
      </div>
      <div class="budget-form">
        <SliderCheckbox inputId="self-budget-enabled" labelText="Enabled" v-model="selfBudgetForm.enabled" />
        <div class="budget-grid">
          <div class="input-group">
            <label for="self-budget-usd">Daily USD cap</label>
            <input id="self-budget-usd" v-model.number="selfBudgetForm.daily_budget_usd" type="number" step="0.1" min="-1" />
          </div>
          <div class="input-group">
            <label for="self-budget-tokens">Daily token cap</label>
            <input id="self-budget-tokens" v-model.number="selfBudgetForm.daily_token_budget" type="number" step="100" min="-1" />
          </div>
          <div class="input-group">
            <label for="self-budget-calls">Daily call cap</label>
            <input id="self-budget-calls" v-model.number="selfBudgetForm.daily_call_budget" type="number" step="1" min="-1" />
          </div>
          <div class="input-group">
            <label for="self-budget-max-tokens">Max tokens per call</label>
            <input id="self-budget-max-tokens" v-model.number="selfBudgetForm.max_tokens_per_call" type="number" step="50" min="-1" />
          </div>
        </div>
        <div class="budget-actions">
          <button class="primary-btn" :disabled="!selfBudgetDirty || selfBudgetSaving" @click="saveSelfBudget">
            {{ selfBudgetSaving ? 'Saving...' : 'Apply Budget' }}
          </button>
          <span v-if="selfBudgetError" class="error-text">{{ selfBudgetError }}</span>
        </div>
      </div>
    </section>

    <section class="drawer-card log-card">
      <div class="card-header">
        <span>Live Log</span>
        <button class="ghost-btn" @click="refreshSelfImproveLogs">
          <RefreshCcw size="14" />
          <span>Refresh</span>
        </button>
      </div>
      <pre class="log-output">{{ selfImproveLogs || 'No log output yet.' }}</pre>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { RefreshCcw, Sparkles, X } from 'lucide-vue-next';
import SliderCheckbox from '@/components/controls/SliderCheckbox.vue';
import { showToast } from '@/libs/utils/general-utils';

defineEmits(['close']);

const selfImproveStatus = ref(null);
const selfImproveLogs = ref('');
const selfImproveBusy = ref(false);
const selfImproveError = ref('');
const selfImproveUseLlm = ref(true);
const selfImproveRegressionLimit = ref(0);
const selfImproveMemvidLimit = ref(0);
const selfImprovePatchText = ref('');
const selfImprovePatchResult = ref(null);
const logTimer = ref(null);

const selfBudget = ref(null);
const selfBudgetSaving = ref(false);
const selfBudgetDirty = ref(false);
const selfBudgetError = ref('');
const selfBudgetReady = ref(false);
const selfBudgetForm = reactive({
  enabled: true,
  daily_budget_usd: 1.0,
  daily_token_budget: 12000,
  daily_call_budget: 6,
  max_tokens_per_call: 2000
});

const selfImproveStatusLabel = computed(() => {
  if (!selfImproveStatus.value) return 'unknown';
  if (selfImproveStatus.value.running) return 'running';
  if (selfImproveStatus.value.last_error) return 'error';
  return 'idle';
});

const selfImproveStatusClass = computed(() => {
  if (!selfImproveStatus.value) return 'neutral';
  if (selfImproveStatus.value.running) return 'warn';
  if (selfImproveStatus.value.last_error) return 'danger';
  return 'ok';
});

const selfImproveLocked = computed(() => {
  return Boolean(selfImproveBusy.value || selfImproveStatus.value?.running);
});

const selfBudgetStatusLabel = computed(() => {
  if (!selfBudget.value) return 'unknown';
  if (!selfBudget.value.state?.enabled) return 'disabled';
  return 'enabled';
});

const selfBudgetStatusClass = computed(() => {
  if (!selfBudget.value) return 'neutral';
  if (!selfBudget.value.state?.enabled) return 'warn';
  return 'ok';
});

const selfBudgetSpentLabel = computed(() => {
  const spent = selfBudget.value?.state?.spent_usd;
  return spent !== undefined ? `$${spent.toFixed(2)}` : '—';
});

const selfBudgetTokenLabel = computed(() => {
  const spent = selfBudget.value?.state?.spent_tokens;
  return spent !== undefined ? `${spent}` : '—';
});

const selfBudgetCallLabel = computed(() => {
  const spent = selfBudget.value?.state?.spent_calls;
  return spent !== undefined ? `${spent}` : '—';
});

const formatTimestamp = (value) => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const fetchSelfImproveStatus = async () => {
  try {
    const response = await fetch('/api/self_improvement/status');
    if (!response.ok) {
      throw new Error('Failed to fetch self-improvement status');
    }
    selfImproveStatus.value = await response.json();
  } catch (error) {
    showToast('Unable to fetch self-improvement status');
    console.error(error);
  }
};

const fetchSelfImproveLogs = async () => {
  try {
    const response = await fetch('/api/self_improvement/logs?lines=200');
    if (!response.ok) {
      throw new Error('Failed to fetch self-improvement logs');
    }
    const data = await response.json();
    selfImproveLogs.value = data.log || '';
  } catch (error) {
    showToast('Unable to fetch self-improvement logs');
    console.error(error);
  }
};

const refreshSelfImproveLogs = async () => {
  await fetchSelfImproveLogs();
};

const runSelfImprove = async (action, payload = {}) => {
  if (selfImproveBusy.value) return;
  selfImproveBusy.value = true;
  selfImproveError.value = '';
  try {
    const response = await fetch('/api/self_improvement/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, payload })
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || 'Unable to start task');
    }
    selfImproveStatus.value = data.status || selfImproveStatus.value;
    await fetchSelfImproveLogs();
  } catch (error) {
    selfImproveError.value = error.message || 'Unable to start task';
    showToast(selfImproveError.value);
  } finally {
    selfImproveBusy.value = false;
  }
};

const runRedTeam = async () => runSelfImprove('red_team', { use_llm: Boolean(selfImproveUseLlm.value) });
const runArchitect = async () => runSelfImprove('architect');
const runRegression = async () => {
  const limit = Number(selfImproveRegressionLimit.value || 0);
  await runSelfImprove('regression', { limit });
};
const runMemvidExport = async () => {
  const limit = Number(selfImproveMemvidLimit.value || 0);
  await runSelfImprove('memvid_export', { limit });
};
const runExportSpecialist = async () => {
  const limit = Number(selfImproveMemvidLimit.value || 0);
  await runSelfImprove('export_specialist', { limit });
};
const trainRewardModel = async () => runSelfImprove('train_reward_model');

const simulatePatch = async () => {
  selfImprovePatchResult.value = null;
  selfImproveError.value = '';
  let patchOps = [];
  try {
    patchOps = JSON.parse(selfImprovePatchText.value || '[]');
  } catch (error) {
    selfImproveError.value = 'Patch JSON is invalid.';
    return;
  }
  try {
    const response = await fetch('/api/self_improvement/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patch: patchOps })
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || 'Simulation failed');
    }
    selfImprovePatchResult.value = data;
  } catch (error) {
    selfImproveError.value = error.message || 'Simulation failed';
  }
};

const fetchSelfBudget = async () => {
  try {
    const response = await fetch('/api/self_improvement/budget');
    if (!response.ok) {
      throw new Error('Failed to fetch self-improvement budget');
    }
    selfBudget.value = await response.json();
    if (selfBudget.value?.state) {
      selfBudgetForm.enabled = Boolean(selfBudget.value.state.enabled);
      selfBudgetForm.daily_budget_usd = selfBudget.value.state.daily_budget_usd ?? 1.0;
      selfBudgetForm.daily_token_budget = selfBudget.value.state.daily_token_budget ?? 12000;
      selfBudgetForm.daily_call_budget = selfBudget.value.state.daily_call_budget ?? 6;
      selfBudgetForm.max_tokens_per_call = selfBudget.value.state.max_tokens_per_call ?? 2000;
    }
    selfBudgetDirty.value = false;
    selfBudgetReady.value = true;
  } catch (error) {
    showToast('Unable to fetch self-improvement budget');
    console.error(error);
  }
};

const saveSelfBudget = async () => {
  selfBudgetSaving.value = true;
  selfBudgetError.value = '';
  try {
    const response = await fetch('/api/self_improvement/budget', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(selfBudgetForm)
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || 'Unable to save budget');
    }
    await fetchSelfBudget();
    showToast('Budget updated');
  } catch (error) {
    selfBudgetError.value = error.message || 'Unable to save budget';
  } finally {
    selfBudgetSaving.value = false;
  }
};

const startLogPolling = () => {
  if (logTimer.value) return;
  logTimer.value = setInterval(() => {
    fetchSelfImproveStatus();
    fetchSelfImproveLogs();
  }, 5000);
};

const stopLogPolling = () => {
  if (logTimer.value) {
    clearInterval(logTimer.value);
    logTimer.value = null;
  }
};

watch(selfBudgetForm, () => {
  if (!selfBudgetReady.value) return;
  selfBudgetDirty.value = true;
}, { deep: true });

onMounted(async () => {
  await Promise.all([fetchSelfImproveStatus(), fetchSelfImproveLogs(), fetchSelfBudget()]);
  startLogPolling();
});

onBeforeUnmount(() => {
  stopLogPolling();
});
</script>

<style scoped lang="scss">
// ============================================
// VERA SelfImproveDrawer Premium Animation System
// DNA helix, evolution particles, neural growth
// Uses theme CSS variables for consistency
// ============================================

// Secondary accent for visual variety (purple tones)
$secondary-accent-rgb: var(--vera-secondary-rgb);
$secondary-accent-soft: var(--vera-secondary-60);

.self-drawer {
  position: relative;
  height: 100%;
  padding: 20px 18px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  overflow-x: hidden;
  color: var(--vera-text);
  background: var(--vera-drawer-bg);

  &::-webkit-scrollbar {
    width: 6px;
  }
  &::-webkit-scrollbar-track {
    background: var(--vera-scrollbar-track);
    border-radius: 3px;
  }
  &::-webkit-scrollbar-thumb {
    background: var(--vera-scrollbar-thumb);
    border-radius: 3px;
    &:hover {
      background: var(--vera-scrollbar-thumb-hover);
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

// Layer 1: DNA Helix animation
.bg-dna-helix {
  z-index: 1;
  opacity: 0.4;
  right: 10px;
  left: auto;
  width: 80px;

  .dna-svg {
    width: 100%;
    height: 100%;
  }

  .dna-strand {
    fill: none;
    stroke: var(--vera-accent-soft);
    stroke-width: 2;
    stroke-linecap: round;
    animation: dnaRotate 12s linear infinite;

    &.strand-2 {
      animation-direction: reverse;
      stroke: $secondary-accent-soft;
    }
  }

  .dna-rung {
    stroke: var(--vera-accent-faint);
    stroke-width: 1;
    animation: rungPulse 4s ease-in-out infinite;

    @for $i from 1 through 20 {
      &:nth-child(#{$i}) {
        animation-delay: ($i * 0.2) * 1s;
      }
    }
  }
}

// Layer 2: Rising evolution particles
.bg-evolution-particles {
  z-index: 2;

  .evo-particle {
    position: absolute;
    width: 6px;
    height: 6px;
    background: var(--vera-accent);
    border-radius: 50%;
    filter: blur(1px);
    animation: evolveRise 6s ease-in-out infinite;
    opacity: 0;

    @for $i from 1 through 12 {
      &:nth-child(#{$i}) {
        left: (5 + ($i - 1) * 8) * 1%;
        bottom: 0;
        animation-duration: (5 + ($i % 4)) * 1s;
      }
    }
  }
}

// Layer 3: Neural web pattern
.bg-neural-web {
  z-index: 3;
  background:
    radial-gradient(circle at 25% 25%, var(--vera-accent-faint), transparent 30%),
    radial-gradient(circle at 75% 50%, rgba($secondary-accent-rgb, 0.06), transparent 35%),
    radial-gradient(circle at 40% 80%, var(--vera-accent-faint), transparent 30%);
  animation: neuralShift 10s ease-in-out infinite;
}

// Layer 4: Expanding energy rings
.bg-energy-rings {
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: center;

  .energy-ring {
    position: absolute;
    width: 100px;
    height: 100px;
    border: 1px solid var(--vera-accent-soft);
    border-radius: 50%;
    animation: ringExpand 6s ease-out infinite;
    opacity: 0;
  }
}

// ============================================
// Content (above background layers)
// ============================================

.self-drawer > *:not(.bg-layer) {
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

  &::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    width: 70px;
    height: 2px;
    background: linear-gradient(90deg, var(--vera-accent), $secondary-accent-soft, transparent);
    animation: headerGlow 4s ease-in-out infinite;
  }
}

.drawer-title {
  display: flex;
  gap: 10px;
  align-items: center;

  svg {
    color: var(--vera-accent);
    filter: drop-shadow(0 0 6px var(--vera-accent-soft));
    animation: sparkle 2s ease-in-out infinite;
  }
}

.drawer-title-text {
  font-size: 1rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--vera-text) 0%, var(--vera-accent) 50%, rgba($secondary-accent-rgb, 1) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  background-size: 200% 100%;
  animation: titleShimmer 6s linear infinite;
}

.drawer-subtitle {
  font-size: 0.75rem;
  color: var(--vera-text-muted);
}

.icon-btn {
  border: 1px solid var(--vera-border);
  background: var(--vera-glass-bg);
  color: var(--vera-text);
  width: 28px;
  height: 28px;
  border-radius: var(--vera-radius-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-soft);
    box-shadow: var(--vera-glow-soft);
    transform: scale(1.05);
  }
}

// ============================================
// Cards with staggered entry
// ============================================

.drawer-card {
  border: 1px solid var(--vera-border);
  border-radius: var(--vera-radius-md);
  padding: 14px;
  background: var(--vera-glass-strong);
  backdrop-filter: blur(16px);
  display: flex;
  flex-direction: column;
  gap: 12px;
  opacity: 0;
  animation: cardEvolve 0.6s ease forwards;
  transition: all 0.3s ease;
  position: relative;

  &:hover {
    border-color: var(--vera-accent-soft);
    box-shadow: var(--vera-glow-soft);
    transform: translateY(-2px);
  }

  // Evolution indicator line
  &::before {
    content: '';
    position: absolute;
    left: -1px;
    top: 10%;
    width: 3px;
    height: 0;
    background: linear-gradient(180deg, var(--vera-accent), $secondary-accent-soft);
    border-radius: 0 2px 2px 0;
    transition: height 0.4s ease;
  }

  &:hover::before {
    height: 80%;
  }

  @for $i from 1 through 6 {
    &:nth-of-type(#{$i}) {
      animation-delay: ($i * 0.12) * 1s;
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
  border-radius: var(--vera-radius-full);
  font-size: 0.6875rem;
  color: var(--vera-text);
  background: var(--vera-accent-faint);
  border: 1px solid transparent;
  transition: all 0.2s ease;

  &.ok {
    color: var(--vera-success);
    background: var(--vera-success-15);
    animation: pillOkGlow 3s ease-in-out infinite;
  }

  &.warn {
    color: var(--vera-warning);
    background: var(--vera-warning-15);
    animation: pillWarnGlow 2s ease-in-out infinite;
  }

  &.danger {
    color: var(--vera-danger);
    background: var(--vera-error-15);
    animation: pillDangerGlow 1.5s ease-in-out infinite;
  }

  &.neutral {
    color: var(--vera-text-muted);
  }
}

.card-grid {
  display: grid;
  gap: 6px;
  font-size: 0.75rem;
  color: var(--vera-text-muted);

  strong {
    color: var(--vera-text);
  }
}

// ============================================
// Actions
// ============================================

.action-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.action-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.primary-btn,
.secondary-btn,
.ghost-btn {
  border-radius: var(--vera-radius-sm);
  border: 1px solid var(--vera-border);
  padding: 8px 12px;
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

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    &:hover::before {
      left: -100%;
    }
  }
}

.primary-btn {
  background: linear-gradient(135deg, var(--vera-accent-soft), rgba($secondary-accent-rgb, 0.15));
  border-color: var(--vera-accent-soft);

  &:hover:not(:disabled) {
    box-shadow: var(--vera-glow-soft);
    transform: translateY(-1px);
  }
}

.secondary-btn {
  background: var(--vera-glass-bg);

  &:hover:not(:disabled) {
    border-color: var(--vera-accent-soft);
    box-shadow: var(--vera-glow-soft);
  }
}

.ghost-btn {
  background: transparent;
  display: inline-flex;
  align-items: center;
  gap: 4px;

  &:hover:not(:disabled) {
    background: var(--vera-accent-faint);
    border-color: var(--vera-accent-soft);
  }
}

// ============================================
// Inputs
// ============================================

.input-group {
  display: grid;
  gap: 4px;
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
}

.input-group input,
textarea {
  background: var(--vera-input-bg);
  border: 1px solid var(--vera-border);
  border-radius: var(--vera-radius-sm);
  padding: 8px;
  color: var(--vera-text);
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  transition: all 0.2s ease;

  &:focus {
    outline: none;
    border-color: var(--vera-accent-soft);
    box-shadow: var(--vera-glow-soft);
  }
}

.action-row .input-group {
  flex: 1 1 160px;
  min-width: 140px;
}

// ============================================
// Budget Section
// ============================================

.budget-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.budget-grid .input-group {
  min-width: 0;
}

.budget-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

// ============================================
// Log Output
// ============================================

.log-output {
  min-height: 160px;
  max-height: 240px;
  overflow-y: auto;
  background: var(--vera-code-bg);
  border-radius: var(--vera-radius-sm);
  padding: 10px;
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  font-family: var(--vera-font-mono);
  border: 1px solid var(--vera-border);
  position: relative;

  // Scan line effect
  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--vera-accent-soft), transparent);
    animation: logScan 3s linear infinite;
    opacity: 0.5;
  }

  &::-webkit-scrollbar {
    width: 4px;
  }
  &::-webkit-scrollbar-thumb {
    background: var(--vera-scrollbar-thumb);
    border-radius: 2px;
  }
}

// ============================================
// Misc
// ============================================

.patch-result {
  font-size: 0.75rem;
  color: var(--vera-text-muted);
  padding: 8px;
  background: var(--vera-glass-bg);
  border-radius: var(--vera-radius-sm);
}

.empty-state {
  font-size: 0.75rem;
  color: var(--vera-text-muted);
  font-style: italic;
}

.error-text {
  color: var(--vera-danger);
  font-size: 0.75rem;
}

.helper-text {
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
}

// ============================================
// Keyframe Animations
// ============================================

@keyframes dnaRotate {
  0% { stroke-dasharray: 0, 1000; stroke-dashoffset: 0; }
  50% { stroke-dasharray: 500, 500; }
  100% { stroke-dasharray: 1000, 0; stroke-dashoffset: -1000; }
}

@keyframes rungPulse {
  0%, 100% { stroke-opacity: 0.2; }
  50% { stroke-opacity: 0.6; }
}

@keyframes evolveRise {
  0% {
    transform: translateY(0) scale(0.5);
    opacity: 0;
  }
  20% { opacity: 0.8; }
  80% { opacity: 0.6; }
  100% {
    transform: translateY(-500px) scale(1.2);
    opacity: 0;
  }
}

@keyframes neuralShift {
  0%, 100% {
    opacity: 0.6;
    transform: scale(1);
  }
  50% {
    opacity: 0.9;
    transform: scale(1.05);
  }
}

@keyframes ringExpand {
  0% {
    transform: scale(0.5);
    opacity: 0.6;
  }
  100% {
    transform: scale(3);
    opacity: 0;
  }
}

@keyframes cardEvolve {
  0% {
    opacity: 0;
    transform: translateY(20px) scale(0.96);
  }
  60% {
    transform: translateY(-4px) scale(1.02);
  }
  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes headerGlow {
  0%, 100% { width: 70px; opacity: 0.6; }
  50% { width: 120px; opacity: 1; }
}

@keyframes sparkle {
  0%, 100% {
    transform: rotate(0deg) scale(1);
    filter: drop-shadow(0 0 4px var(--vera-accent-soft));
  }
  25% {
    transform: rotate(5deg) scale(1.1);
    filter: drop-shadow(0 0 8px var(--vera-accent));
  }
  50% {
    transform: rotate(-3deg) scale(1);
  }
  75% {
    transform: rotate(2deg) scale(1.05);
  }
}

@keyframes titleShimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

@keyframes pillOkGlow {
  0%, 100% { box-shadow: 0 0 4px transparent; }
  50% { box-shadow: 0 0 8px var(--vera-success-40); }
}

@keyframes pillWarnGlow {
  0%, 100% { box-shadow: 0 0 4px transparent; }
  50% { box-shadow: 0 0 8px var(--vera-warning-40); }
}

@keyframes pillDangerGlow {
  0%, 100% { box-shadow: 0 0 4px transparent; }
  50% { box-shadow: 0 0 10px var(--vera-error-50); }
}

@keyframes logScan {
  0% { top: 0; }
  100% { top: 100%; }
}

// ============================================
// Reduced Motion
// ============================================

@media (prefers-reduced-motion: reduce) {
  .bg-layer,
  .drawer-card,
  .dna-strand,
  .dna-rung,
  .evo-particle,
  .energy-ring,
  .drawer-title svg,
  .drawer-title-text,
  .pill,
  .log-output::before {
    animation: none !important;
  }

  .drawer-card {
    opacity: 1;
  }
}
</style>
