<template>
  <div class="drawer canvas-drawer" ref="containerRef">
    <!-- Ambient glow background -->
    <div class="ambient-glow"></div>

    <!-- Layout Toggle Buttons -->
    <div class="layout-toggle" v-if="!collapsed">
      <button
        class="toggle-btn"
        :class="{ active: layoutMode === 'canvas-focus' }"
        @click="setLayoutMode('canvas-focus')"
        title="100% Canvas"
      >
        <PanelTop :size="14" />
      </button>
      <button
        class="toggle-btn"
        :class="{ active: layoutMode === 'split' }"
        @click="setLayoutMode('split')"
        title="65/35 Split (Draggable)"
      >
        <GripHorizontal :size="14" />
      </button>
      <button
        class="toggle-btn"
        :class="{ active: layoutMode === 'terminal-focus' }"
        @click="setLayoutMode('terminal-focus')"
        title="100% Terminal"
      >
        <PanelBottom :size="14" />
      </button>
    </div>

    <div class="canvas-main" :style="canvasMainStyle">
      <CodeEditor
        :collapsed="collapsed"
        :minimized="isCanvasMinimized"
        :working-directory="workingDirectory"
        @close="$emit('close')"
        @toggle-collapse="$emit('toggle-collapse')"
        @save-artifact="$emit('save-artifact', $event)"
        @directory-changed="workingDirectory = $event"
      />
    </div>

    <!-- Draggable Divider (only in split mode) -->
    <div
      v-if="showBottomPanel && !bottomPanelCollapsed && layoutMode === 'split'"
      class="split-divider"
      :class="{ dragging: isDragging }"
      @mousedown="startDrag"
    >
      <div class="divider-handle">
        <span class="handle-dots"></span>
      </div>
    </div>

    <BottomPanel
      v-if="showBottomPanel"
      v-model:collapsed="bottomPanelCollapsed"
      :working-directory="workingDirectory"
      :locked="true"
      :maximized="isTerminalMaximized"
      :style="terminalPanelStyle"
      :class="{ 'terminal-minimized': isTerminalMinimized }"
      @close="showBottomPanel = false; setLayoutMode('split')"
    >
      <template #terminal="{ workingDirectory: wd }">
        <TerminalPanel :working-directory="wd" />
      </template>
      <template #git="{ workingDirectory: wd }">
        <GitStatusPanel :working-directory="wd" />
      </template>
    </BottomPanel>

    <!-- Code rain effect - only shows when bottom panel is collapsed/hidden -->
    <div
      v-if="!showBottomPanel || bottomPanelCollapsed"
      class="code-rain-area"
      :class="{ 'full-width': !showBottomPanel }"
    >
      <span v-for="i in 12" :key="i" class="code-rain-char">{{ codeChars[(i - 1) % codeChars.length] }}</span>
    </div>

    <!-- Toggle button to show bottom panel when hidden -->
    <button
      v-if="!showBottomPanel && !collapsed"
      class="show-panel-btn"
      @click="showBottomPanel = true"
      title="Show Terminal/Git Panel"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="4 17 10 11 4 5"></polyline>
        <line x1="12" y1="19" x2="20" y2="19"></line>
      </svg>
      <span>Terminal</span>
    </button>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue';
import { PanelTop, GripHorizontal, PanelBottom } from 'lucide-vue-next';
import CodeEditor from '@/components/layout/CodeEditor.vue';
import BottomPanel from '@/components/layout/BottomPanel.vue';
import TerminalPanel from '@/components/layout/TerminalPanel.vue';
import GitStatusPanel from '@/components/layout/GitStatusPanel.vue';

defineProps({
  collapsed: {
    type: Boolean,
    default: false
  }
});

defineEmits(['close', 'save-artifact', 'toggle-collapse']);

const showBottomPanel = ref(true);
const bottomPanelCollapsed = ref(false);
const workingDirectory = ref('');

// Layout mode: 'split' | 'terminal-focus' | 'canvas-focus'
const layoutMode = ref('split');

// Split ratio (percentage for canvas, terminal gets the rest)
// Default: 65% canvas, 35% terminal
const splitRatio = ref(65);
const MIN_SPLIT = 20;
const MAX_SPLIT = 85;

// Drag state
const isDragging = ref(false);
const containerRef = ref(null);

// Computed states for layout mode
const isCanvasMinimized = computed(() => layoutMode.value === 'terminal-focus');
const isTerminalMaximized = computed(() => layoutMode.value === 'terminal-focus');
const isTerminalMinimized = computed(() => layoutMode.value === 'canvas-focus');

// Computed height for canvas-main based on layout mode
const canvasMainStyle = computed(() => {
  if (layoutMode.value === 'terminal-focus') {
    // Canvas minimized to 40px toolbar
    return { height: '40px', flex: 'none' };
  }
  if (layoutMode.value === 'canvas-focus') {
    // Canvas takes all space except 38px for terminal tab bar
    return { height: 'calc(100% - 44px)', flex: 'none' };
  }
  // Split mode - use split ratio
  if (showBottomPanel.value && !bottomPanelCollapsed.value) {
    return { height: `calc(${splitRatio.value}% - 6px)`, flex: 'none' };
  }
  return { height: '100%' };
});

// Computed height for terminal panel based on layout mode
const terminalPanelStyle = computed(() => {
  if (layoutMode.value === 'terminal-focus') {
    return { height: 'calc(100% - 46px)', flex: 'none' };
  }
  if (layoutMode.value === 'canvas-focus') {
    return { height: '38px', flex: 'none' };
  }
  // Split mode - terminal gets remaining space
  return { height: `calc(${100 - splitRatio.value}% - 6px)`, flex: 'none' };
});

// Code rain characters
const codeChars = ['<', '/>', '{', '}', ';', '()', '[]', '=>', '&&', '||', '!=', '++'];

// Drag handlers for resizable split
function startDrag(event) {
  if (layoutMode.value !== 'split') return;
  isDragging.value = true;
  document.addEventListener('mousemove', onDrag);
  document.addEventListener('mouseup', stopDrag);
  document.body.style.cursor = 'ns-resize';
  document.body.style.userSelect = 'none';
  event.preventDefault();
}

function onDrag(event) {
  if (!isDragging.value || !containerRef.value) return;
  const container = containerRef.value;
  const rect = container.getBoundingClientRect();
  const y = event.clientY - rect.top;
  const percentage = (y / rect.height) * 100;
  splitRatio.value = Math.max(MIN_SPLIT, Math.min(MAX_SPLIT, percentage));
}

function stopDrag() {
  isDragging.value = false;
  document.removeEventListener('mousemove', onDrag);
  document.removeEventListener('mouseup', stopDrag);
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
  // Save the ratio
  localStorage.setItem('vera-canvas-split-ratio', String(splitRatio.value));
}

// Load saved state
onMounted(() => {
  const savedShow = localStorage.getItem('vera-bottom-panel-show');
  if (savedShow !== null) {
    showBottomPanel.value = savedShow === 'true';
  }

  // Load layout mode
  const savedLayout = localStorage.getItem('vera-canvas-layout-mode');
  if (savedLayout && ['split', 'terminal-focus', 'canvas-focus'].includes(savedLayout)) {
    layoutMode.value = savedLayout;
  }

  // Load split ratio
  const savedRatio = localStorage.getItem('vera-canvas-split-ratio');
  if (savedRatio) {
    const ratio = parseFloat(savedRatio);
    if (!isNaN(ratio) && ratio >= MIN_SPLIT && ratio <= MAX_SPLIT) {
      splitRatio.value = ratio;
    }
  }
});

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onDrag);
  document.removeEventListener('mouseup', stopDrag);
});

// Save state when changed
watch(showBottomPanel, (val) => {
  localStorage.setItem('vera-bottom-panel-show', String(val));
});

watch(layoutMode, (val) => {
  localStorage.setItem('vera-canvas-layout-mode', val);
});

function setLayoutMode(mode) {
  layoutMode.value = mode;
  // Ensure bottom panel is visible when switching to a layout mode
  if (mode !== 'split' && !showBottomPanel.value) {
    showBottomPanel.value = true;
  }
  // When switching to split, reset to default 65/35 ratio
  if (mode === 'split') {
    splitRatio.value = 65;
    localStorage.setItem('vera-canvas-split-ratio', '65');
  }
}
</script>

<style scoped lang="scss">
// Canvas/Code Editor - Uses theme CSS variables
// Secondary accent colors are now driven by CSS variables

.canvas-drawer {
  position: relative;
  height: 100%;
  overflow: hidden;
  color: var(--vera-text);
  display: flex;
  flex-direction: column;
  background: var(--vera-drawer-bg);
}

// ============================================
// Ambient Glow Background
// ============================================

.ambient-glow {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 1;
  background:
    radial-gradient(ellipse at 10% 10%, var(--vera-accent-soft) 0%, transparent 40%),
    radial-gradient(ellipse at 90% 90%, var(--vera-secondary-15) 0%, transparent 40%),
    radial-gradient(ellipse at 50% 50%, var(--vera-secondary-08) 0%, transparent 50%);
  animation: ambientPulse 8s ease-in-out infinite;
}

// ============================================
// Code Rain Area (bottom panel collapsed state)
// ============================================

.code-rain-area {
  position: absolute;
  bottom: 6px;
  left: 6px;
  right: 6px;
  height: 80px;
  pointer-events: none;
  z-index: 5;
  overflow: hidden;
  background: linear-gradient(180deg, transparent 0%, var(--vera-panel-muted) 100%);
  border-radius: 0 0 var(--vera-radius-sm) var(--vera-radius-sm);

  &.full-width {
    height: 120px;
  }

  .code-rain-char {
    position: absolute;
    font-family: var(--vera-font-mono);
    font-size: 0.875rem;
    opacity: 0;
    text-shadow: 0 0 8px currentColor;
    animation: codeRainFall 4s linear infinite;

    @for $i from 1 through 12 {
      &:nth-child(#{$i}) {
        left: (5 + ($i - 1) * 8) * 1%;
        animation-delay: (($i - 1) * 0.3) * 1s;
        animation-duration: (3 + ($i % 3)) * 1s;

        @if $i % 3 == 1 {
          color: var(--vera-accent);
        } @else if $i % 3 == 2 {
          color: var(--vera-secondary);
        } @else {
          color: var(--vera-secondary-60);
        }
      }
    }
  }
}

// ============================================
// Layout Toggle
// ============================================

.layout-toggle {
  position: absolute;
  right: 16px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px;
  background: var(--vera-glass-strong);
  backdrop-filter: blur(12px);
  border: 1px solid var(--vera-glass-border);
  border-radius: var(--vera-radius-sm);
  box-shadow: var(--vera-glow-soft);
}

.toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--vera-text-muted);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s ease;

  &:hover {
    background: var(--vera-panel-alt);
    color: var(--vera-text);
  }

  &.active {
    background: var(--vera-accent-soft);
    color: var(--vera-accent);
    box-shadow: 0 0 8px var(--vera-accent-soft);
  }
}

// ============================================
// Draggable Split Divider
// ============================================

.split-divider {
  position: relative;
  z-index: 20;
  height: 12px;
  margin: 0 6px;
  cursor: ns-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease;

  &:hover,
  &.dragging {
    .divider-handle {
      background: var(--vera-accent-15);
      border-color: var(--vera-accent-40);

      .handle-dots {
        background: var(--vera-accent);
        box-shadow: 0 0 8px var(--vera-accent);
      }
    }
  }

  &.dragging {
    .divider-handle {
      background: var(--vera-accent-25);
    }
  }
}

.divider-handle {
  width: 60px;
  height: 6px;
  border-radius: 3px;
  background: var(--vera-accent-08);
  border: 1px solid var(--vera-accent-20);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.handle-dots {
  width: 24px;
  height: 2px;
  border-radius: 1px;
  background: var(--vera-accent-40);
  transition: all 0.2s ease;
}

// ============================================
// Main Content
// ============================================

.canvas-main {
  position: relative;
  z-index: 10;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  margin: 6px;
  transition: height 0.2s ease, flex 0.2s ease;
}

.canvas-drawer :deep(.code-editor-panel) {
  position: relative;
  z-index: 1;
  background: var(--vera-glass-strong);
  backdrop-filter: blur(16px);
  height: 100%;
  border: 1px solid var(--vera-glass-border);
  border-radius: var(--vera-radius-sm);
  box-shadow: var(--vera-glow-soft);

  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: 5%;
    right: 5%;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--vera-accent), transparent);
    animation: lineGlow 3s ease-in-out infinite;
  }
}

.canvas-drawer :deep(.bottom-panel) {
  position: relative;
  z-index: 15;
  flex-shrink: 0;
  background: var(--vera-glass-strong);
  margin: 0 6px 6px 6px;
  border-radius: var(--vera-radius-sm);
  border: 1px solid var(--vera-glass-border);
  transition: height 0.2s ease, flex 0.2s ease;

  &.terminal-minimized {
    height: 32px !important;
    min-height: 32px;
    max-height: 32px;
    flex: none;

    .panel-content {
      display: none;
    }
  }

  &.maximized {
    flex: 1;
    height: 100% !important;
  }
}

// ============================================
// Show Panel Button
// ============================================

.show-panel-btn {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border: 2px solid var(--vera-accent-soft);
  border-radius: var(--vera-radius-full);
  background: var(--vera-glass-strong);
  backdrop-filter: blur(12px);
  color: var(--vera-accent);
  font-size: 0.8125rem;
  font-family: var(--vera-font-mono);
  cursor: pointer;
  z-index: 20;
  transition: all 0.3s ease;
  overflow: hidden;
  box-shadow: var(--vera-glow-soft);

  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(90deg, transparent, var(--vera-accent-soft), transparent);
    transition: left 0.5s ease;
  }

  &:hover {
    background: var(--vera-panel);
    border-color: var(--vera-accent);
    box-shadow: var(--vera-glow-strong);
    transform: translateX(-50%) translateY(-2px);

    &::before {
      left: 100%;
    }

    svg {
      filter: drop-shadow(0 0 8px var(--vera-accent));
    }
  }

  svg {
    transition: filter 0.3s ease;
  }

  span {
    position: relative;
    z-index: 1;
  }
}

// ============================================
// Keyframes
// ============================================

@keyframes ambientPulse {
  0%, 100% {
    opacity: 0.6;
    transform: scale(1);
  }
  50% {
    opacity: 1;
    transform: scale(1.02);
  }
}

@keyframes codeRainFall {
  0% {
    top: -20px;
    opacity: 0;
  }
  10% {
    opacity: 0.9;
  }
  80% {
    opacity: 0.7;
  }
  100% {
    top: 100%;
    opacity: 0;
  }
}

@keyframes lineGlow {
  0%, 100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}

// ============================================
// Reduced Motion Support
// ============================================

@media (prefers-reduced-motion: reduce) {
  .ambient-glow,
  .code-rain-char,
  .canvas-drawer :deep(.code-editor-panel)::before,
  .canvas-drawer :deep(.bottom-panel)::before {
    animation: none !important;
  }

  .code-rain-char { opacity: 0; }
}
</style>
