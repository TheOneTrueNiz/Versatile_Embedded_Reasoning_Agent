<template>
  <div class="drawer innerlife-drawer">
    <div class="bg-layer bg-orbit">
      <span
        v-for="i in 6"
        :key="'orbit-'+i"
        class="orbit-dot"
        :style="{ animationDelay: `${i * 0.6}s` }"
      ></span>
    </div>
    <div class="bg-layer bg-halo"></div>
    <div class="bg-layer bg-grain"></div>

    <header class="drawer-header">
      <div class="drawer-title">
        <Brain size="18" />
        <div>
          <div class="drawer-title-text">Inner Life</div>
          <div class="drawer-subtitle">Mood, traits, and recent thoughts</div>
        </div>
      </div>
      <button class="icon-btn" @click="$emit('close')" title="Close inner life">
        <X size="16" />
      </button>
    </header>

    <section class="drawer-card status-card">
      <div class="card-header">
        <span>Status</span>
        <div class="card-actions">
          <button class="ghost-btn" @click="refreshInnerLife" :disabled="loading">
            <RefreshCcw size="14" />
            <span>Refresh</span>
          </button>
          <button class="primary-btn" @click="runReflection" :disabled="reflectDisabled">
            <Sparkles size="14" />
            <span>Reflect</span>
          </button>
        </div>
      </div>
      <div v-if="error" class="error-text">{{ error }}</div>
      <div v-else-if="!stats" class="empty-state">Inner life status not loaded yet.</div>
      <div v-else class="status-grid">
        <div class="mood-badge" :class="moodClass">{{ moodLabel }}</div>
        <div class="stat-item">
          <span>Enabled</span>
          <span class="pill" :class="stats.enabled ? 'ok' : 'warn'">{{ stats.enabled ? 'yes' : 'no' }}</span>
        </div>
        <div class="stat-item">
          <span>Active hours</span>
          <span>{{ stats.within_active_hours ? 'within' : 'outside' }}</span>
        </div>
        <div class="stat-item">
          <span>Reflections</span>
          <span>{{ stats.total_reflections }}</span>
        </div>
        <div class="stat-item">
          <span>Last reflection</span>
          <span>{{ formatTimestamp(stats.last_reflection) }}</span>
        </div>
        <div class="stat-item">
          <span>Personality v</span>
          <span>{{ stats.personality_version }}</span>
        </div>
      </div>
      <div v-if="interests.length" class="chip-row">
        <span class="chip" v-for="interest in interests" :key="interest">{{ interest }}</span>
      </div>
    </section>

    <section class="drawer-card traits-card">
      <div class="card-header">
        <span>Traits</span>
        <span class="pill neutral">Radar</span>
      </div>
      <div v-if="!radarTraits.length" class="empty-state">No trait data yet.</div>
      <div v-else class="traits-grid">
        <div class="radar-wrap">
          <svg :width="radarSize" :height="radarSize" :viewBox="`0 0 ${radarSize} ${radarSize}`">
            <g class="radar-grid">
              <polygon
                v-for="ring in radarRings"
                :key="`ring-${ring.level}`"
                :points="ring.points"
              />
              <line
                v-for="axis in radarAxes"
                :key="axis.name"
                :x1="radarCenter"
                :y1="radarCenter"
                :x2="axis.x"
                :y2="axis.y"
              />
            </g>
            <polygon class="radar-shape" :points="radarPoints" />
            <g class="radar-dots">
              <circle
                v-for="dot in radarDots"
                :key="`dot-${dot.name}`"
                :cx="dot.x"
                :cy="dot.y"
                r="3.5"
              />
            </g>
            <g class="radar-labels">
              <text
                v-for="label in radarLabels"
                :key="`label-${label.name}`"
                :x="label.x"
                :y="label.y"
                :text-anchor="label.anchor"
              >
                {{ label.name }}
              </text>
            </g>
          </svg>
        </div>
        <div class="traits-list">
          <div v-for="trait in sortedTraits" :key="trait.name" class="trait-row">
            <span class="trait-name">{{ trait.name }}</span>
            <div class="trait-meter">
              <div class="trait-fill" :style="{ width: `${trait.percent}%` }"></div>
            </div>
            <span class="trait-value">{{ trait.value.toFixed(2) }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="drawer-card goals-card">
      <div class="card-header">
        <span>Goals</span>
        <span class="pill neutral">{{ goals.length }} active</span>
      </div>
      <div v-if="!goals.length" class="empty-state">No active goals yet.</div>
      <div v-else class="goals-list">
        <div v-for="goal in goals" :key="goal.id" class="goal-item">
          <div class="goal-meta">
            <span class="intent-pill" :class="goalCategoryClass(goal.category)">{{ goal.category }}</span>
            <span class="priority-dots">{{ '\u25CF'.repeat(goal.priority) }}{{ '\u25CB'.repeat(5 - goal.priority) }}</span>
          </div>
          <div class="goal-text">{{ goal.description }}</div>
          <div v-if="goal.progress_notes?.length" class="goal-note">
            Latest: {{ goal.progress_notes[goal.progress_notes.length - 1].note }}
          </div>
        </div>
      </div>
    </section>

    <section class="drawer-card proactive-card" v-if="proactive">
      <div class="card-header">
        <span>Proactive Systems</span>
        <span class="pill" :class="proactiveActive ? 'ok' : 'neutral'">
          {{ proactiveActive ? 'active' : 'standby' }}
        </span>
      </div>
      <div class="status-grid">
        <div class="stat-item">
          <span>Calendar</span>
          <span class="pill" :class="proactive.calendar_enabled ? 'ok' : 'warn'">
            {{ proactive.calendar_enabled ? 'on' : 'off' }}
          </span>
        </div>
        <div class="stat-item" v-if="proactive.calendar_enabled">
          <span>Alerts today</span>
          <span>{{ proactive.calendar_alerts_today || 0 }}</span>
        </div>
        <div class="stat-item" v-if="proactive.calendar_enabled">
          <span>Last poll</span>
          <span>{{ formatTimestamp(proactive.calendar_last_poll) }}</span>
        </div>
        <div class="stat-item">
          <span>Auto-execute</span>
          <span class="pill" :class="proactive.proactive_execution_enabled ? 'ok' : 'warn'">
            {{ proactive.proactive_execution_enabled ? 'on' : 'off' }}
          </span>
        </div>
      </div>
    </section>

    <section class="drawer-card thoughts-card">
      <div class="card-header">
        <span>Recent Thoughts</span>
        <span class="pill neutral">{{ thoughts.length }} entries</span>
      </div>
      <div v-if="!thoughts.length" class="empty-state">No inner thoughts recorded yet.</div>
      <div v-else class="thoughts-list">
        <div v-for="entry in thoughts" :key="entry.timestamp + entry.intent" class="thought-item">
          <div class="thought-meta">
            <span class="intent-pill" :class="intentClass(entry.intent)">{{ entry.intent }}</span>
            <span class="thought-time">{{ formatTimestamp(entry.timestamp) }}</span>
          </div>
          <div class="thought-text">{{ entry.thought }}</div>
          <div v-if="entry.action_taken" class="thought-action">Action: {{ entry.action_taken }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { Brain, RefreshCcw, Sparkles, X } from 'lucide-vue-next';
import { showToast } from '@/libs/utils/general-utils';
import { addInnerLifeListener, ensureThinkingWebSocket } from '@/libs/api-access/thinking-websocket';

defineEmits(['close']);

const stats = ref(null);
const personality = ref(null);
const thoughts = ref([]);
const goals = ref([]);
const proactive = ref(null);
const loading = ref(false);
const error = ref('');
const reflectBusy = ref(false);
const refreshTimer = ref(null);
let innerLifeUnsub = null;
let refreshScheduled = false;

const radarSize = 220;
const radarRadius = 80;
const radarCenter = radarSize / 2;

const fetchInnerLife = async () => {
  loading.value = true;
  error.value = '';
  try {
    const response = await fetch('/api/innerlife/status?limit=12');
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || 'Failed to load inner life status.');
    }
    stats.value = payload.stats || null;
    personality.value = payload.personality || null;
    thoughts.value = payload.recent_thoughts || [];
    goals.value = payload.goals || [];
    proactive.value = payload.proactive || null;
  } catch (err) {
    error.value = err?.message || 'Failed to load inner life status.';
  } finally {
    loading.value = false;
  }
};

const refreshInnerLife = () => {
  fetchInnerLife();
};

const scheduleRefresh = () => {
  if (refreshScheduled) return;
  refreshScheduled = true;
  setTimeout(() => {
    refreshScheduled = false;
    fetchInnerLife();
  }, 500);
};

const runReflection = async () => {
  if (reflectBusy.value) return;
  if (stats.value && !stats.value.enabled) {
    showToast('Inner life engine is disabled.');
    return;
  }
  reflectBusy.value = true;
  try {
    const response = await fetch('/api/innerlife/reflect', { method: 'POST' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || 'Reflection request failed.');
    }
    showToast('Reflection scheduled.');
    setTimeout(fetchInnerLife, 1200);
  } catch (err) {
    showToast(err?.message || 'Reflection request failed.');
  } finally {
    reflectBusy.value = false;
  }
};

const reflectDisabled = computed(() => {
  return reflectBusy.value || (stats.value && !stats.value.enabled);
});

const moodLabel = computed(() => {
  return (
    personality.value?.current_mood ||
    stats.value?.current_mood ||
    'neutral'
  );
});

const moodClass = computed(() => {
  const mood = (moodLabel.value || '').toLowerCase();
  if (['happy', 'excited', 'uplifted', 'joyful', 'curious'].includes(mood)) return 'positive';
  if (['sad', 'tired', 'anxious', 'frustrated', 'angry'].includes(mood)) return 'negative';
  return 'neutral';
});

const interests = computed(() => {
  return personality.value?.interests || stats.value?.interests || [];
});

const proactiveActive = computed(() =>
  proactive.value?.calendar_enabled || proactive.value?.proactive_execution_enabled
);

const goalCategoryClass = (cat) => {
  const map = {
    self_improvement: 'intent-action',
    relationship: 'intent-reach',
    skill: 'intent-prompt',
    exploration: 'intent-internal'
  };
  return map[cat] || 'intent-internal';
};

const radarTraits = computed(() => {
  const traits = personality.value?.traits || {};
  return Object.entries(traits).map(([name, value]) => ({
    name,
    value: typeof value === 'number' ? value : 0
  }));
});

const sortedTraits = computed(() => {
  return [...radarTraits.value]
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
    .map((trait) => ({
      ...trait,
      percent: Math.round(((trait.value + 1) / 2) * 100)
    }));
});

const radarPoints = computed(() => {
  const items = radarTraits.value;
  const count = items.length;
  if (!count) return '';
  return items.map((trait, idx) => {
    const angle = (Math.PI * 2 * idx) / count - Math.PI / 2;
    const normalized = Math.max(0, Math.min(1, (trait.value + 1) / 2));
    const r = radarRadius * normalized;
    const x = radarCenter + r * Math.cos(angle);
    const y = radarCenter + r * Math.sin(angle);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
});

const radarRings = computed(() => {
  const items = radarTraits.value;
  const count = items.length;
  if (!count) return [];
  const levels = [0.25, 0.5, 0.75, 1];
  return levels.map((level) => {
    const points = items.map((_, idx) => {
      const angle = (Math.PI * 2 * idx) / count - Math.PI / 2;
      const r = radarRadius * level;
      const x = radarCenter + r * Math.cos(angle);
      const y = radarCenter + r * Math.sin(angle);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return { level, points };
  });
});

const radarAxes = computed(() => {
  const items = radarTraits.value;
  const count = items.length;
  if (!count) return [];
  return items.map((trait, idx) => {
    const angle = (Math.PI * 2 * idx) / count - Math.PI / 2;
    const x = radarCenter + radarRadius * Math.cos(angle);
    const y = radarCenter + radarRadius * Math.sin(angle);
    return { name: trait.name, x, y, angle };
  });
});

const radarDots = computed(() => {
  const items = radarTraits.value;
  const count = items.length;
  if (!count) return [];
  return items.map((trait, idx) => {
    const angle = (Math.PI * 2 * idx) / count - Math.PI / 2;
    const normalized = Math.max(0, Math.min(1, (trait.value + 1) / 2));
    const r = radarRadius * normalized;
    return {
      name: trait.name,
      x: radarCenter + r * Math.cos(angle),
      y: radarCenter + r * Math.sin(angle)
    };
  });
});

const radarLabels = computed(() => {
  return radarAxes.value.map((axis) => {
    const offset = 14;
    const x = axis.x + Math.cos(axis.angle) * offset;
    const y = axis.y + Math.sin(axis.angle) * offset;
    let anchor = 'middle';
    const cos = Math.cos(axis.angle);
    if (cos > 0.35) anchor = 'start';
    if (cos < -0.35) anchor = 'end';
    return { name: axis.name, x, y, anchor };
  });
});

const formatTimestamp = (value) => {
  if (!value || value === 'never') return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const intentClass = (intent) => {
  const key = (intent || '').toLowerCase();
  if (key === 'reach_out') return 'intent-reach';
  if (key === 'self_prompt') return 'intent-prompt';
  if (key === 'action') return 'intent-action';
  return 'intent-internal';
};

onMounted(() => {
  fetchInnerLife();
  refreshTimer.value = setInterval(fetchInnerLife, 15000);
  ensureThinkingWebSocket().catch(() => {});
  innerLifeUnsub = addInnerLifeListener(() => {
    scheduleRefresh();
  });
});

onBeforeUnmount(() => {
  if (refreshTimer.value) clearInterval(refreshTimer.value);
  if (innerLifeUnsub) innerLifeUnsub();
});
</script>

<style scoped>
.innerlife-drawer {
  position: relative;
  overflow: hidden;
  padding: 20px;
  color: var(--vera-text);
}

.innerlife-drawer > *:not(.bg-layer) {
  position: relative;
  z-index: 2;
}

.bg-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.5;
}

.bg-orbit {
  opacity: 0.35;
}

.orbit-dot {
  position: absolute;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(120, 210, 255, 0.45);
  box-shadow: 0 0 12px rgba(120, 210, 255, 0.35);
  animation: orbitPulse 6s ease-in-out infinite;
}

.orbit-dot:nth-child(1) { top: 12%; left: 18%; }
.orbit-dot:nth-child(2) { top: 28%; right: 12%; }
.orbit-dot:nth-child(3) { top: 52%; left: 8%; }
.orbit-dot:nth-child(4) { bottom: 20%; right: 18%; }
.orbit-dot:nth-child(5) { bottom: 8%; left: 45%; }
.orbit-dot:nth-child(6) { top: 8%; right: 42%; }

.bg-halo {
  background: radial-gradient(circle at top right, rgba(80, 160, 255, 0.22), transparent 55%),
              radial-gradient(circle at 30% 70%, rgba(120, 240, 200, 0.18), transparent 60%);
}

.bg-grain {
  background-image: radial-gradient(rgba(255, 255, 255, 0.08) 1px, transparent 0);
  background-size: 120px 120px;
  opacity: 0.15;
}

.drawer-card {
  position: relative;
  z-index: 1;
  border: 1px solid var(--vera-border);
  border-radius: var(--vera-radius-md);
  padding: 14px;
  background: var(--vera-glass-strong);
  backdrop-filter: blur(16px);
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: all 0.2s ease;
}

.drawer-card:hover {
  border-color: var(--vera-accent-soft);
  box-shadow: var(--vera-glow-soft);
  transform: translateY(-2px);
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--vera-border);
  padding-bottom: 10px;
  position: relative;
}

.drawer-header::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  width: 70px;
  height: 2px;
  background: linear-gradient(90deg, var(--vera-accent), rgba(120, 220, 255, 0.7), transparent);
}

.drawer-title {
  display: flex;
  gap: 10px;
  align-items: center;
}

.drawer-title svg {
  color: var(--vera-accent);
  filter: drop-shadow(0 0 6px var(--vera-accent-soft));
}

.drawer-title-text {
  font-size: 1rem;
  font-weight: 700;
  color: var(--vera-text);
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
}

.icon-btn:hover {
  border-color: var(--vera-accent-soft);
  box-shadow: var(--vera-glow-soft);
  transform: scale(1.05);
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
}

.pill.ok {
  color: var(--vera-success);
  background: var(--vera-success-15);
}

.pill.warn {
  color: var(--vera-warning);
  background: var(--vera-warning-15);
}

.pill.neutral {
  color: var(--vera-text-muted);
}

.ghost-btn,
.primary-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: var(--vera-radius-sm);
  font-size: 0.75rem;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.2s ease;
}

.ghost-btn {
  background: var(--vera-panel);
  color: var(--vera-text);
  border-color: var(--vera-border);
}

.ghost-btn:hover {
  border-color: var(--vera-accent-soft);
  box-shadow: var(--vera-glow-soft);
}

.primary-btn {
  background: var(--vera-accent);
  color: #0b1220;
}

.primary-btn:disabled,
.ghost-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.empty-state {
  font-size: 0.75rem;
  color: var(--vera-text-muted);
}

.error-text {
  font-size: 0.75rem;
  color: var(--vera-danger);
}

.card-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 10px;
}

.stat-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 12px;
  color: var(--vera-text-muted);
}

.mood-badge {
  grid-column: span 2;
  font-size: 14px;
  font-weight: 600;
  text-transform: capitalize;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(120, 120, 120, 0.2);
  color: var(--vera-text);
  border: 1px solid rgba(120, 120, 120, 0.35);
}

.mood-badge.positive {
  background: rgba(120, 230, 190, 0.2);
  border-color: rgba(120, 230, 190, 0.5);
  color: rgba(160, 255, 220, 0.95);
}

.mood-badge.negative {
  background: rgba(255, 120, 120, 0.18);
  border-color: rgba(255, 120, 120, 0.5);
  color: rgba(255, 190, 190, 0.95);
}

.mood-badge.neutral {
  background: rgba(120, 180, 255, 0.18);
  border-color: rgba(120, 180, 255, 0.45);
  color: rgba(180, 210, 255, 0.95);
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.chip {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  background: rgba(120, 180, 255, 0.15);
  color: var(--vera-text);
  border: 1px solid rgba(120, 180, 255, 0.35);
}

.traits-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.radar-wrap {
  display: flex;
  justify-content: center;
  align-items: center;
}

.radar-grid polygon,
.radar-grid line {
  fill: none;
  stroke: rgba(120, 180, 255, 0.2);
  stroke-width: 1;
}

.radar-shape {
  fill: rgba(120, 220, 255, 0.2);
  stroke: rgba(120, 220, 255, 0.7);
  stroke-width: 1.5;
}

.radar-dots circle {
  fill: rgba(120, 220, 255, 0.9);
  stroke: rgba(0, 0, 0, 0.2);
  stroke-width: 1;
}

.radar-labels text {
  font-size: 10px;
  fill: var(--vera-text-muted);
}

.traits-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.trait-row {
  display: grid;
  grid-template-columns: 1fr 1.5fr 48px;
  gap: 8px;
  align-items: center;
  font-size: 12px;
}

.trait-meter {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: rgba(120, 180, 255, 0.2);
  overflow: hidden;
}

.trait-fill {
  height: 100%;
  background: linear-gradient(90deg, rgba(120, 220, 255, 0.8), rgba(180, 255, 220, 0.8));
  border-radius: inherit;
}

.trait-value {
  text-align: right;
  color: var(--vera-text-muted);
}

.thoughts-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 280px;
  overflow: auto;
  padding-right: 4px;
}

.thought-item {
  background: rgba(20, 25, 35, 0.35);
  border: 1px solid rgba(120, 180, 255, 0.15);
  border-radius: 12px;
  padding: 10px 12px;
}

.thought-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 11px;
  color: var(--vera-text-muted);
}

.intent-pill {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 10px;
  border: 1px solid transparent;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.intent-internal {
  background: rgba(120, 180, 255, 0.2);
  border-color: rgba(120, 180, 255, 0.4);
}

.intent-reach {
  background: rgba(120, 240, 200, 0.22);
  border-color: rgba(120, 240, 200, 0.45);
}

.intent-prompt {
  background: rgba(255, 210, 120, 0.2);
  border-color: rgba(255, 210, 120, 0.45);
}

.intent-action {
  background: rgba(255, 130, 130, 0.2);
  border-color: rgba(255, 130, 130, 0.45);
}

.thought-text {
  font-size: 12px;
  line-height: 1.5;
  color: var(--vera-text);
}

.thought-action {
  margin-top: 6px;
  font-size: 11px;
  color: var(--vera-text-muted);
}

@media (max-width: 720px) {
  .status-grid {
    grid-template-columns: 1fr;
  }

  .mood-badge {
    grid-column: span 1;
  }
}

.goal-item { padding: 8px 0; border-bottom: 1px solid var(--vera-border); }
.goal-item:last-child { border-bottom: none; }
.goal-meta { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; }
.goal-text { font-size: 0.8125rem; color: var(--vera-text); }
.goal-note { font-size: 0.75rem; color: var(--vera-text-muted); margin-top: 4px; font-style: italic; }
.priority-dots { font-size: 0.625rem; color: var(--vera-accent); letter-spacing: 1px; }

@keyframes orbitPulse {
  0%, 100% {
    transform: scale(1);
    opacity: 0.5;
  }
  50% {
    transform: scale(1.6);
    opacity: 1;
  }
}
</style>
