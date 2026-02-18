<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick, computed } from 'vue';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal as TerminalIcon } from 'lucide-vue-next';
import '@xterm/xterm/css/xterm.css';
import {
  uiTerminalBackground,
  uiTerminalForeground,
  uiTerminalCursor,
  uiTerminalSelection,
  uiTerminalBlack,
  uiTerminalRed,
  uiTerminalGreen,
  uiTerminalYellow,
  uiTerminalBlue,
  uiTerminalMagenta,
  uiTerminalCyan,
  uiTerminalWhite,
  uiAccentColor
} from '@/libs/state-management/state';

const props = defineProps({
  workingDirectory: {
    type: String,
    default: ''
  }
});

const terminalRef = ref(null);
const wsStatus = ref('disconnected');
const isExecuting = ref(false);
const currentCommand = ref('');
const commandHistory = ref([]);
const historyIndex = ref(-1);

let terminal = null;
let fitAddon = null;
let ws = null;
let resizeObserver = null;

const normalizeHex = (value) => {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  if (!trimmed.startsWith('#')) return '';
  if (trimmed.length === 4) {
    return `#${trimmed[1]}${trimmed[1]}${trimmed[2]}${trimmed[2]}${trimmed[3]}${trimmed[3]}`;
  }
  if (trimmed.length === 5) {
    return `#${trimmed[1]}${trimmed[1]}${trimmed[2]}${trimmed[2]}${trimmed[3]}${trimmed[3]}${trimmed[4]}${trimmed[4]}`;
  }
  if (trimmed.length === 7 || trimmed.length === 9) {
    return trimmed;
  }
  return '';
};

const hexToRgb = (hex) => {
  const normalized = normalizeHex(hex);
  if (!normalized) return null;
  const raw = normalized.slice(1, 7);
  const r = parseInt(raw.slice(0, 2), 16);
  const g = parseInt(raw.slice(2, 4), 16);
  const b = parseInt(raw.slice(4, 6), 16);
  return Number.isNaN(r) || Number.isNaN(g) || Number.isNaN(b) ? null : { r, g, b };
};

const rgbToHex = (rgb) => {
  const toHex = (channel) => channel.toString(16).padStart(2, '0');
  return `#${toHex(rgb.r)}${toHex(rgb.g)}${toHex(rgb.b)}`;
};

const brightenColor = (hex, amount = 0.25) => {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const mix = (value) => Math.round(value + (255 - value) * amount);
  return rgbToHex({ r: mix(rgb.r), g: mix(rgb.g), b: mix(rgb.b) });
};

const toRgba = (hex, alpha) => {
  const rgb = hexToRgb(hex);
  if (!rgb) return '';
  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
};

const readCssVar = (name) => {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
};

const formatAnsi = (hex, text) => {
  const rgb = hexToRgb(hex);
  if (!rgb) return text;
  return `\x1b[38;2;${rgb.r};${rgb.g};${rgb.b}m${text}\x1b[0m`;
};

// Terminal theme using reactive state values - customizable via Appearance settings
const getTerminalTheme = () => {
  const background = normalizeHex(uiTerminalBackground.value) || readCssVar('--vera-terminal-bg');
  const foreground = normalizeHex(uiTerminalForeground.value) || readCssVar('--vera-terminal-fg');
  const cursor = normalizeHex(uiTerminalCursor.value) || readCssVar('--vera-terminal-cursor');
  const selection = normalizeHex(uiTerminalSelection.value)
    || readCssVar('--vera-terminal-selection')
    || toRgba(normalizeHex(uiTerminalCyan.value), 0.25);
  const terminalBlack = normalizeHex(uiTerminalBlack.value) || readCssVar('--vera-terminal-black');
  const terminalRed = normalizeHex(uiTerminalRed.value) || readCssVar('--vera-terminal-red');
  const terminalGreen = normalizeHex(uiTerminalGreen.value) || readCssVar('--vera-terminal-green');
  const terminalYellow = normalizeHex(uiTerminalYellow.value) || readCssVar('--vera-terminal-yellow');
  const terminalBlue = normalizeHex(uiTerminalBlue.value) || readCssVar('--vera-terminal-blue');
  const terminalMagenta = normalizeHex(uiTerminalMagenta.value) || readCssVar('--vera-terminal-magenta');
  const terminalCyan = normalizeHex(uiTerminalCyan.value) || readCssVar('--vera-terminal-cyan');
  const terminalWhite = normalizeHex(uiTerminalWhite.value) || readCssVar('--vera-terminal-white');

  return {
    background,
    foreground,
    cursor,
    cursorAccent: background,
    selection,
    black: terminalBlack,
    red: terminalRed,
    green: terminalGreen,
    yellow: terminalYellow,
    blue: terminalBlue,
    magenta: terminalMagenta,
    cyan: terminalCyan,
    white: terminalWhite,
    brightBlack: brightenColor(terminalBlack, 0.35),
    brightRed: brightenColor(terminalRed, 0.3),
    brightGreen: brightenColor(terminalGreen, 0.3),
    brightYellow: brightenColor(terminalYellow, 0.25),
    brightBlue: brightenColor(terminalBlue, 0.25),
    brightMagenta: brightenColor(terminalMagenta, 0.25),
    brightCyan: brightenColor(terminalCyan, 0.25),
    brightWhite: brightenColor(terminalWhite, 0.12)
  };
};

const getPromptColor = () => normalizeHex(uiTerminalCyan.value)
  || normalizeHex(uiAccentColor.value)
  || readCssVar('--vera-accent');

const getHintColor = () => normalizeHex(uiTerminalForeground.value) || readCssVar('--vera-terminal-fg');

const writePrompt = () => {
  terminal.write(`${formatAnsi(getPromptColor(), '$')} `);
};

// Watch for terminal color changes and update the theme
const terminalColorRefs = [
  uiTerminalBackground, uiTerminalForeground, uiTerminalCursor, uiTerminalSelection,
  uiTerminalBlack, uiTerminalRed, uiTerminalGreen, uiTerminalYellow,
  uiTerminalBlue, uiTerminalMagenta, uiTerminalCyan, uiTerminalWhite
];

terminalColorRefs.forEach(colorRef => {
  watch(colorRef, () => {
    if (terminal) {
      terminal.options.theme = getTerminalTheme();
    }
  });
});

function initTerminal() {
  if (!terminalRef.value) return;

  terminal = new Terminal({
    theme: getTerminalTheme(),
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
    fontSize: 13,
    lineHeight: 1.2,
    cursorBlink: true,
    cursorStyle: 'bar',
    scrollback: 1000,
    convertEol: true
  });

  fitAddon = new FitAddon();
  terminal.loadAddon(fitAddon);
  terminal.open(terminalRef.value);

  // Fit terminal to container
  nextTick(() => {
    fitAddon.fit();
  });

  // Handle terminal input
  terminal.onData((data) => {
    if (isExecuting.value) {
      // Send input to running process
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }));
      }
    } else {
      handleInput(data);
    }
  });

  // Write welcome message with VERA cyan accent
  terminal.writeln(formatAnsi(getPromptColor(), ' VERA Terminal '));
  terminal.writeln(formatAnsi(getHintColor(), 'Type commands and press Enter to execute'));
  terminal.write('\r\n');
  writePrompt();

  // Setup resize observer
  resizeObserver = new ResizeObserver(() => {
    if (fitAddon) {
      fitAddon.fit();
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: 'resize',
          cols: terminal.cols,
          rows: terminal.rows
        }));
      }
    }
  });
  resizeObserver.observe(terminalRef.value);
}

function handleInput(data) {
  // Handle special keys
  if (data === '\r') {
    // Enter - execute command
    executeCommand();
  } else if (data === '\x7f' || data === '\b') {
    // Backspace
    if (currentCommand.value.length > 0) {
      currentCommand.value = currentCommand.value.slice(0, -1);
      terminal.write('\b \b');
    }
  } else if (data === '\x1b[A') {
    // Up arrow - history
    if (commandHistory.value.length > 0 && historyIndex.value < commandHistory.value.length - 1) {
      historyIndex.value++;
      setCommand(commandHistory.value[commandHistory.value.length - 1 - historyIndex.value]);
    }
  } else if (data === '\x1b[B') {
    // Down arrow - history
    if (historyIndex.value > 0) {
      historyIndex.value--;
      setCommand(commandHistory.value[commandHistory.value.length - 1 - historyIndex.value]);
    } else if (historyIndex.value === 0) {
      historyIndex.value = -1;
      clearLine();
      currentCommand.value = '';
    }
  } else if (data === '\x03') {
    // Ctrl+C
    if (isExecuting.value) {
      killProcess();
    } else {
      terminal.write('^C\r\n');
      writePrompt();
      currentCommand.value = '';
    }
  } else if (data >= ' ' || data === '\t') {
    // Regular character
    currentCommand.value += data;
    terminal.write(data);
  }
}

function setCommand(cmd) {
  clearLine();
  currentCommand.value = cmd;
  terminal.write(cmd);
}

function clearLine() {
  terminal.write('\x1b[2K\r');
  writePrompt();
}

function executeCommand() {
  const cmd = currentCommand.value.trim();
  terminal.write('\r\n');

  if (!cmd) {
    writePrompt();
    return;
  }

  // Add to history
  if (commandHistory.value[commandHistory.value.length - 1] !== cmd) {
    commandHistory.value.push(cmd);
    // Keep last 100 commands
    if (commandHistory.value.length > 100) {
      commandHistory.value.shift();
    }
  }
  historyIndex.value = -1;

  // Handle local commands
  if (cmd === 'clear' || cmd === 'cls') {
    terminal.clear();
    writePrompt();
    currentCommand.value = '';
    return;
  }

  // Send to backend
  if (ws && ws.readyState === WebSocket.OPEN) {
    isExecuting.value = true;
    ws.send(JSON.stringify({
      type: 'execute',
      command: cmd,
      cwd: props.workingDirectory
    }));
  } else {
    terminal.writeln('\x1b[31mNot connected to terminal service\x1b[0m');
    terminal.write('\x1b[38;2;16;210;255m$\x1b[0m');
  }

  currentCommand.value = '';
}

function killProcess() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'kill' }));
  }
}

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${protocol}://${window.location.host}/ws/terminal`;

  wsStatus.value = 'connecting';
  ws = new WebSocket(wsUrl);

  ws.addEventListener('open', () => {
    wsStatus.value = 'connected';
  });

  ws.addEventListener('message', (event) => {
    try {
      const data = JSON.parse(event.data);
      handleMessage(data);
    } catch (e) {
      console.error('Terminal message parse error:', e);
    }
  });

  ws.addEventListener('close', () => {
    wsStatus.value = 'disconnected';
    // Reconnect after 3 seconds
    setTimeout(connectWebSocket, 3000);
  });

  ws.addEventListener('error', () => {
    wsStatus.value = 'error';
  });
}

function handleMessage(data) {
  switch (data.type) {
    case 'connected':
      // Connection established
      break;
    case 'started':
      // Command started
      break;
    case 'output':
      // Write output to terminal
      terminal.write(data.data);
      break;
    case 'exit':
      // Command finished
      isExecuting.value = false;
      if (data.code !== 0) {
        terminal.writeln(`\x1b[31mExited with code ${data.code}\x1b[0m`);
      }
      terminal.write('\x1b[38;2;16;210;255m$\x1b[0m');
      break;
    case 'killed':
      isExecuting.value = false;
      terminal.writeln('\x1b[33m^C\x1b[0m');
      terminal.write('\x1b[38;2;16;210;255m$\x1b[0m');
      break;
    case 'error':
      isExecuting.value = false;
      terminal.writeln(`\x1b[31m${data.message}\x1b[0m`);
      terminal.write('\x1b[38;2;16;210;255m$\x1b[0m');
      break;
  }
}

onMounted(() => {
  initTerminal();
  connectWebSocket();
});

onBeforeUnmount(() => {
  if (resizeObserver) {
    resizeObserver.disconnect();
  }
  if (ws) {
    ws.close();
  }
  if (terminal) {
    terminal.dispose();
  }
});

// Focus terminal when working directory changes (user likely wants to type)
watch(() => props.workingDirectory, () => {
  if (terminal) {
    terminal.focus();
  }
});
</script>

<template>
  <div class="terminal-panel">
    <!-- Premium animated background layers (z-index 1-4, never over content) -->
    <div class="bg-layer bg-grid-dots"></div>
    <div class="bg-layer bg-floating-orbs">
      <span v-for="i in 5" :key="'orb-'+i" class="floating-orb" :class="'orb-' + i"></span>
    </div>
    <div class="bg-layer bg-stream-particles">
      <span v-for="i in 8" :key="'stream-'+i" class="stream-particle" :style="{ animationDelay: `${i * 0.7}s`, left: `${5 + i * 11}%` }"></span>
    </div>
    <div class="bg-layer bg-gradient-glow"></div>
    <div class="bg-layer bg-scan-lines"></div>

    <!-- Premium Header -->
    <div class="terminal-header">
      <div class="header-content">
        <div class="header-icon-wrapper">
          <TerminalIcon class="header-icon" :size="18" />
          <div class="icon-glow"></div>
        </div>
        <span class="header-title">Terminal</span>
      </div>
      <div class="header-status" :class="wsStatus">
        <span class="status-dot"></span>
        <span class="status-text">{{ wsStatus }}</span>
      </div>
    </div>

    <!-- Terminal content area with solid background for text clarity -->
    <div class="terminal-content-wrapper">
      <div ref="terminalRef" class="terminal-container"></div>
    </div>
  </div>
</template>

<style scoped lang="scss">
// ============================================
// VERA Terminal - Full Premium Treatment
// Floating orbs, rich glows, premium header
// Text areas have solid backgrounds for clarity
// ============================================

// VERA cool spectrum palette - using CSS variables
$vera-cyan: var(--vera-accent);
$vera-violet: var(--vera-secondary);
$vera-glass-bg: var(--vera-terminal-bg);
$vera-glass-border: var(--vera-accent-18);
$vera-text-primary: var(--vera-text);
$vera-text-muted: var(--vera-text-muted);

// ============================================
// Background Layers (z-index 1-4, NEVER over content)
// ============================================

.bg-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
  border-radius: 16px;
}

.bg-grid-dots {
  z-index: 1;
  background-image: radial-gradient(
    var(--vera-accent-06) 1px,
    transparent 1px
  );
  background-size: 24px 24px;
  animation: dotPulse 10s ease-in-out infinite;
}

// Floating orbs - large, slow-moving ambient elements
.bg-floating-orbs {
  z-index: 2;

  .floating-orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(40px);
    opacity: 0;
    animation: floatOrb 20s ease-in-out infinite;

    &.orb-1 {
      width: 120px;
      height: 120px;
      background: radial-gradient(circle, var(--vera-accent-25) 0%, transparent 70%);
      top: 10%;
      left: 5%;
      animation-delay: 0s;
    }

    &.orb-2 {
      width: 80px;
      height: 80px;
      background: radial-gradient(circle, var(--vera-secondary-20) 0%, transparent 70%);
      top: 60%;
      right: 10%;
      animation-delay: -5s;
    }

    &.orb-3 {
      width: 100px;
      height: 100px;
      background: radial-gradient(circle, var(--vera-accent-18) 0%, transparent 70%);
      bottom: 20%;
      left: 30%;
      animation-delay: -10s;
    }

    &.orb-4 {
      width: 60px;
      height: 60px;
      background: radial-gradient(circle, var(--vera-secondary-20) 0%, transparent 70%);
      top: 30%;
      right: 25%;
      animation-delay: -15s;
    }

    &.orb-5 {
      width: 90px;
      height: 90px;
      background: radial-gradient(circle, var(--vera-accent-15) 0%, transparent 70%);
      bottom: 40%;
      right: 5%;
      animation-delay: -8s;
    }
  }
}

// Stream particles - falling vertical lines
.bg-stream-particles {
  z-index: 3;

  .stream-particle {
    position: absolute;
    top: -50px;
    width: 2px;
    height: 35px;
    background: linear-gradient(180deg,
      var(--vera-accent-50) 0%,
      var(--vera-accent-20) 50%,
      transparent 100%);
    border-radius: 2px;
    animation: streamFall 6s linear infinite;
    opacity: 0;
  }
}

// Rich gradient glow - multiple overlapping radials
.bg-gradient-glow {
  z-index: 4;
  background:
    radial-gradient(ellipse 80% 50% at 10% 20%, var(--vera-accent-08) 0%, transparent 50%),
    radial-gradient(ellipse 60% 40% at 90% 80%, var(--vera-secondary-08) 0%, transparent 50%),
    radial-gradient(ellipse 50% 50% at 50% 50%, var(--vera-accent-03) 0%, transparent 60%),
    radial-gradient(ellipse 40% 30% at 70% 30%, var(--vera-secondary-05) 0%, transparent 50%);
  animation: glowShift 15s ease-in-out infinite alternate;
}

// Subtle scan lines
.bg-scan-lines {
  z-index: 5;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 3px,
    rgba(var(--vera-shadow-rgb), 0.02) 3px,
    rgba(var(--vera-shadow-rgb), 0.02) 6px
  );
  opacity: 0.6;
}

// ============================================
// Main Panel Container
// ============================================

.terminal-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: $vera-glass-bg;
  position: relative;
  border-radius: 16px;
  overflow: hidden;
  backdrop-filter: blur(24px);
  border: 1px solid $vera-glass-border;
}

// ============================================
// Premium Header
// ============================================

.terminal-header {
  position: relative;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: var(--vera-terminal-header-bg);
  border-bottom: 1px solid var(--vera-accent-10);
}

.header-content {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-icon-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: linear-gradient(135deg,
    var(--vera-accent-15) 0%,
    var(--vera-secondary-10) 100%);
  border: 1px solid var(--vera-accent-25);

  .header-icon {
    color: $vera-cyan;
    filter: drop-shadow(0 0 6px var(--vera-accent-60));
    animation: iconGlow 2s ease-in-out infinite;
  }

  .icon-glow {
    position: absolute;
    inset: -4px;
    border-radius: 14px;
    background: radial-gradient(circle, var(--vera-accent-20) 0%, transparent 70%);
    animation: iconPulse 3s ease-in-out infinite;
    pointer-events: none;
  }
}

.header-title {
  font-size: 0.875rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  background: linear-gradient(135deg, $vera-cyan 0%, $vera-violet 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  text-shadow: 0 0 30px var(--vera-accent-30);
}

// Header status badge
.header-status {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 0.625rem;
  background: var(--vera-glass-strong);
  border: 1px solid var(--vera-accent-15);
  transition: all 0.3s ease;

  &.connected {
    border-color: var(--vera-accent-35);
    box-shadow: 0 0 10px var(--vera-accent-15);

    .status-dot {
      background: $vera-cyan;
      box-shadow: 0 0 8px var(--vera-accent-80);
    }
    .status-text {
      color: var(--vera-accent-90);
    }
  }

  &.connecting {
    border-color: var(--vera-secondary-35);

    .status-dot {
      background: $vera-violet;
      box-shadow: 0 0 8px var(--vera-secondary-80);
      animation: statusPulse 1s ease-in-out infinite;
    }
    .status-text {
      color: var(--vera-secondary);
    }
  }

  &.disconnected,
  &.error {
    border-color: var(--vera-danger);

    .status-dot {
      background: var(--vera-danger);
      box-shadow: 0 0 8px var(--vera-danger);
    }
    .status-text {
      color: var(--vera-danger);
    }
  }

  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    transition: all 0.3s ease;
  }

  .status-text {
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: $vera-text-muted;
  }
}

// ============================================
// Terminal Content Wrapper (SOLID background for text clarity)
// ============================================

.terminal-content-wrapper {
  flex: 1;
  position: relative;
  z-index: 15;
  margin: 8px 10px 10px 10px;
  border-radius: 12px;
  overflow: hidden;
  // SOLID background ensures text is always readable
  background: var(--vera-panel-muted);
  border: 1px solid var(--vera-accent-12);
  box-shadow:
    inset 0 2px 8px var(--vera-shadow),
    0 0 20px var(--vera-accent-05);
}

.terminal-container {
  height: 100%;
  padding: 12px 14px;
  overflow: hidden;
}

.terminal-container :deep(.xterm) {
  height: 100%;
}

.terminal-container :deep(.xterm-viewport) {
  overflow-y: auto;

  // Premium scrollbar
  &::-webkit-scrollbar {
    width: 8px;
  }

  &::-webkit-scrollbar-track {
    background: var(--vera-accent-03);
    border-radius: 4px;
  }

  &::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg,
      var(--vera-accent-30) 0%,
      var(--vera-secondary-20) 100%);
    border-radius: 4px;
    border: 1px solid var(--vera-accent-10);
    transition: all 0.2s ease;

    &:hover {
      background: linear-gradient(180deg,
        var(--vera-accent-45) 0%,
        var(--vera-secondary-35) 100%);
    }
  }
}

// ============================================
// Keyframe Animations
// ============================================

@keyframes floatOrb {
  0%, 100% {
    opacity: 0.4;
    transform: translate(0, 0) scale(1);
  }
  25% {
    opacity: 0.6;
    transform: translate(10px, -15px) scale(1.1);
  }
  50% {
    opacity: 0.5;
    transform: translate(-5px, 10px) scale(0.95);
  }
  75% {
    opacity: 0.7;
    transform: translate(-10px, -5px) scale(1.05);
  }
}

@keyframes streamFall {
  0% {
    transform: translateY(0);
    opacity: 0;
  }
  5% {
    opacity: 0.5;
  }
  95% {
    opacity: 0.3;
  }
  100% {
    transform: translateY(calc(100% + 100px));
    opacity: 0;
  }
}

@keyframes dotPulse {
  0%, 100% {
    opacity: 0.5;
  }
  50% {
    opacity: 0.25;
  }
}

@keyframes glowShift {
  0% {
    opacity: 0.7;
    transform: scale(1);
  }
  100% {
    opacity: 1;
    transform: scale(1.08);
  }
}

@keyframes iconGlow {
  0%, 100% {
    filter: drop-shadow(0 0 4px var(--vera-accent-50));
  }
  50% {
    filter: drop-shadow(0 0 10px var(--vera-accent-80));
  }
}

@keyframes iconPulse {
  0%, 100% {
    opacity: 0.3;
    transform: scale(1);
  }
  50% {
    opacity: 0.6;
    transform: scale(1.15);
  }
}

@keyframes statusPulse {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.5;
    transform: scale(0.9);
  }
}
</style>
