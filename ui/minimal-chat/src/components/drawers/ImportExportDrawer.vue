<template>
  <div class="drawer transfer-drawer">
    <header class="drawer-header">
      <div class="drawer-title">
        <Download size="18" />
        <div>
          <div class="drawer-title-text">Import / Export</div>
          <div class="drawer-subtitle">Move conversation data safely</div>
        </div>
      </div>
      <button class="icon-btn" @click="$emit('close')" title="Close import/export">
        <X size="16" />
      </button>
    </header>

    <section class="drawer-card transfer-card">
      <div class="card-header">
        <span>Conversations</span>
        <span class="pill">JSON</span>
      </div>
      <div class="card-grid">
        <p>Export your current conversation history or import a saved backup.</p>
      </div>
      <div class="button-row">
        <button class="primary-btn" @click="$emit('export-conversations')">
          <Download size="14" />
          <span>Export Conversations</span>
        </button>
        <button class="secondary-btn" @click="$emit('import-conversations')">
          <Upload size="14" />
          <span>Import Conversations</span>
        </button>
      </div>
      <div class="helper-text">
        Imports replace or merge stored conversations based on file contents.
      </div>
    </section>
  </div>
</template>

<script setup>
import { Download, Upload, X } from 'lucide-vue-next';

defineEmits(['close', 'import-conversations', 'export-conversations']);
</script>

<style scoped lang="scss">
.transfer-drawer {
  position: relative;
  height: 100%;
  padding: 20px 18px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  background: var(--vera-drawer-bg);
}

.transfer-drawer::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    linear-gradient(120deg, rgba(var(--vera-accent-rgb), 0.14), transparent 40%),
    repeating-linear-gradient(90deg, var(--vera-accent-10) 0 1px, transparent 1px 16px);
  opacity: 0.7;
  animation: transferFlow 14s linear infinite;
  pointer-events: none;
}

.transfer-drawer::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 80% 20%, rgba(var(--vera-accent-rgb), 0.18), transparent 55%);
  animation: transferPulse 6s ease-in-out infinite;
  pointer-events: none;
}

.transfer-drawer > * {
  position: relative;
  z-index: 1;
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--vera-border);
  padding-bottom: 10px;
}

.drawer-title {
  display: flex;
  gap: 10px;
  align-items: center;
}

.drawer-title-text {
  font-size: 1rem;
  font-weight: 700;
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
}

.drawer-card {
  border: 1px solid var(--vera-border);
  border-radius: 14px;
  padding: 14px;
  background: color-mix(in srgb, var(--vera-panel) 62%, transparent);
  backdrop-filter: blur(12px);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.8125rem;
  font-weight: 600;
}

.card-grid {
  font-size: 0.75rem;
  color: var(--vera-text-muted);
}

.pill {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  background: rgba(var(--vera-accent-rgb), 0.4);
}

.button-row {
  display: grid;
  gap: 8px;
}

.primary-btn,
.secondary-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  justify-content: center;
  border-radius: 10px;
  border: 1px solid var(--vera-border);
  padding: 10px;
  font-size: 0.75rem;
  cursor: pointer;
  color: var(--vera-text);
}

.primary-btn {
  background: var(--vera-accent-faint);
}

.secondary-btn {
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
}

.helper-text {
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
}

@keyframes transferFlow {
  0% {
    background-position: 0 0, 0 0;
  }
  100% {
    background-position: 240px 120px, 180px 0;
  }
}

@keyframes transferPulse {
  0%, 100% {
    opacity: 0.6;
  }
  50% {
    opacity: 1;
  }
}
</style>
