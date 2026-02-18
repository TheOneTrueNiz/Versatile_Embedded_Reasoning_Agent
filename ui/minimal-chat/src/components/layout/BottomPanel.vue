<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue';
import { Terminal as TerminalIcon, GitBranch, ChevronDown, ChevronUp, X } from 'lucide-vue-next';

const props = defineProps({
  workingDirectory: {
    type: String,
    default: ''
  },
  collapsed: {
    type: Boolean,
    default: false
  },
  locked: {
    type: Boolean,
    default: false
  },
  maximized: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['update:collapsed', 'close', 'resize']);

const activeTab = ref('terminal');
const panelHeight = ref(200);
const isResizing = ref(false);
const startY = ref(0);
const startHeight = ref(0);

const MIN_HEIGHT = 100;
const MAX_HEIGHT = 400;
const DEFAULT_HEIGHT = 200;

// Load saved state from localStorage
onMounted(() => {
  const savedTab = localStorage.getItem('vera-bottom-panel-tab');
  if (savedTab) activeTab.value = savedTab;

  const savedHeight = localStorage.getItem('vera-bottom-panel-height');
  if (savedHeight) panelHeight.value = parseInt(savedHeight, 10);
});

// Save state changes
watch(activeTab, (val) => {
  localStorage.setItem('vera-bottom-panel-tab', val);
});

watch(panelHeight, (val) => {
  localStorage.setItem('vera-bottom-panel-height', String(val));
  emit('resize', val);
});

function setTab(tab) {
  activeTab.value = tab;
}

function toggleCollapse() {
  emit('update:collapsed', !props.collapsed);
}

function closePanel() {
  emit('close');
}

// Resize handling
function startResize(event) {
  isResizing.value = true;
  startY.value = event.clientY;
  startHeight.value = panelHeight.value;
  document.addEventListener('mousemove', onResize);
  document.addEventListener('mouseup', stopResize);
  document.body.style.cursor = 'ns-resize';
  document.body.style.userSelect = 'none';
}

function onResize(event) {
  if (!isResizing.value) return;
  // Dragging up increases height, dragging down decreases
  const delta = startY.value - event.clientY;
  const newHeight = Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, startHeight.value + delta));
  panelHeight.value = newHeight;
}

function stopResize() {
  isResizing.value = false;
  document.removeEventListener('mousemove', onResize);
  document.removeEventListener('mouseup', stopResize);
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
}

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onResize);
  document.removeEventListener('mouseup', stopResize);
});

const panelStyle = computed(() => {
  if (props.maximized) {
    return { height: '100%', flex: '1' };
  }
  return { height: props.collapsed ? '32px' : `${panelHeight.value}px` };
});
</script>

<template>
  <div class="bottom-panel" :class="{ collapsed: collapsed, maximized: maximized }" :style="panelStyle">
    <!-- Resize handle -->
    <div
      v-if="!collapsed && !locked"
      class="resize-handle"
      @mousedown="startResize"
    ></div>

    <!-- Tab bar -->
    <div class="tab-bar">
      <div class="tabs">
        <button
          class="tab"
          :class="{ active: activeTab === 'terminal' }"
          @click="setTab('terminal')"
        >
          <TerminalIcon size="14" />
          <span>Terminal</span>
        </button>
        <button
          class="tab"
          :class="{ active: activeTab === 'git' }"
          @click="setTab('git')"
        >
          <GitBranch size="14" />
          <span>Git</span>
        </button>
      </div>
      <div class="tab-actions">
        <button v-if="!locked" class="action-btn" @click="toggleCollapse" :title="collapsed ? 'Expand' : 'Collapse'">
          <ChevronUp v-if="!collapsed" size="14" />
          <ChevronDown v-else size="14" />
        </button>
        <button v-if="!locked" class="action-btn close-btn" @click="closePanel" title="Close panel">
          <X size="14" />
        </button>
      </div>
    </div>

    <!-- Panel content -->
    <div v-if="!collapsed" class="panel-content">
      <slot :name="activeTab" :working-directory="workingDirectory"></slot>
    </div>
  </div>
</template>

<style scoped lang="scss">
// ============================================
// VERA Bottom Panel - Cool Spectrum Glass
// Cyan/violet accents, glass background
// ============================================

// VERA cool spectrum palette - using CSS variables
$vera-cyan: var(--vera-accent);
$vera-violet: var(--vera-secondary);
$vera-glass-bg: var(--vera-glass-strong);
$vera-glass-border: var(--vera-accent-12);

.bottom-panel {
  display: flex;
  flex-direction: column;
  background: $vera-glass-bg;
  border-top: 1px solid $vera-glass-border;
  position: relative;
  transition: height 0.2s ease;
  overflow: hidden;
  border-radius: 16px;
  backdrop-filter: blur(16px);

  // Top glow line
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
      var(--vera-accent-50),
      var(--vera-accent-30),
      transparent);
    box-shadow: 0 0 8px var(--vera-accent-20);
    z-index: 100;
  }

  &.collapsed {
    .panel-content {
      display: none;
    }
  }

  &.maximized {
    height: 100% !important;
    flex: 1;
  }
}

.resize-handle {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 6px;
  cursor: ns-resize;
  background: transparent;
  z-index: 10;
  transition: all 0.2s ease;

  &:hover {
    background: linear-gradient(180deg,
      var(--vera-accent-30) 0%,
      transparent 100%);
    box-shadow: 0 2px 8px var(--vera-accent-15);
  }
}

.tab-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px;
  height: 36px;
  min-height: 36px;
  background: var(--vera-glass-bg);
  border-bottom: 1px solid $vera-glass-border;
}

.tabs {
  display: flex;
  gap: 4px;
}

.tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--vera-text-muted);
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s ease;

  svg {
    opacity: 0.7;
    transition: all 0.2s ease;
  }

  &:hover {
    color: var(--vera-text);
    background: var(--vera-accent-08);
    border-color: var(--vera-accent-15);

    svg {
      opacity: 0.9;
      color: $vera-cyan;
    }
  }

  &.active {
    color: $vera-cyan;
    background: linear-gradient(180deg,
      var(--vera-accent-12) 0%,
      var(--vera-accent-06) 100%);
    border-color: var(--vera-accent-25);
    box-shadow:
      0 0 12px var(--vera-accent-10),
      inset 0 1px 0 var(--vera-accent-05);

    svg {
      opacity: 1;
      color: $vera-cyan;
      filter: drop-shadow(0 0 4px var(--vera-accent-50));
    }
  }
}

.tab-actions {
  display: flex;
  gap: 4px;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid $vera-glass-border;
  background: var(--vera-glass-bg);
  color: var(--vera-text-muted);
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-25);
    background: var(--vera-accent-10);
    color: $vera-cyan;
    box-shadow: 0 0 8px var(--vera-accent-10);
  }
}

.close-btn:hover {
  border-color: var(--vera-danger);
  background: var(--vera-danger);
  color: var(--vera-danger);
  box-shadow: 0 0 8px var(--vera-danger);
}

.panel-content {
  flex: 1;
  overflow: hidden;
  position: relative;
  margin: 6px;
  border-radius: 12px;
}
</style>
