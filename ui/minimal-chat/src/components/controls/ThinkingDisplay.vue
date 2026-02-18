<template>
  <!-- Floating thinking display (currently unused - inline display in MessageItem.vue is preferred) -->
  <div v-if="thinkingEvents.length > 0" class="thinking-container">
    <div class="thinking-header" @click="toggleCollapsed">
      <div class="thinking-title">
        <Brain :size="16" class="thinking-icon" :class="{ spinning: isLoading }" />
        <span>Thinking</span>
        <span class="event-count">({{ thinkingEvents.length }})</span>
      </div>
      <button class="collapse-btn" :class="{ collapsed: thinkingCollapsed }">
        <ChevronDown :size="16" />
      </button>
    </div>

    <transition name="thinking-expand">
      <div v-show="!thinkingCollapsed" class="thinking-content">
        <div
          v-for="(event, index) in thinkingEvents"
          :key="index"
          class="thinking-event"
          :class="getEventClass(event.event_type)"
        >
          <span class="event-icon">{{ getEventIcon(event.event_type) }}</span>
          <span class="event-message">{{ event.message }}</span>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { Brain, ChevronDown } from 'lucide-vue-next';
import { thinkingEvents, isThinkingVisible, thinkingCollapsed, isLoading } from '@/libs/state-management/state';

function toggleCollapsed() {
  thinkingCollapsed.value = !thinkingCollapsed.value;
}

function getEventClass(eventType) {
  const classMap = {
    analyzing: 'event-analyzing',
    routing: 'event-routing',
    memory: 'event-memory',
    tool: 'event-tool',
    reasoning: 'event-reasoning',
    decision: 'event-decision',
    quorum: 'event-quorum',
    error: 'event-error'
  };
  return classMap[eventType] || 'event-default';
}

function getEventIcon(eventType) {
  const iconMap = {
    analyzing: '\u{1F50D}',  // magnifying glass
    routing: '\u{1F500}',    // shuffle arrows
    memory: '\u{1F4BE}',     // floppy disk
    tool: '\u{1F527}',       // wrench
    reasoning: '\u{1F4AD}',  // thought bubble
    decision: '\u{2705}',    // check mark
    quorum: '\u{1F465}',     // people silhouette
    error: '\u{26A0}'        // warning
  };
  return iconMap[eventType] || '\u{2022}'; // bullet point default
}
</script>

<style lang="scss" scoped>
.thinking-container {
  position: absolute;
  bottom: 70px;
  left: 24px;
  right: 24px;
  max-width: 600px;
  border-radius: 12px;
  background: var(--vera-panel-alt);
  border: 1px solid var(--vera-glass-border);
  overflow: hidden;
  font-size: 0.85rem;
  z-index: 10;
  box-shadow: 0 4px 20px rgba(var(--vera-shadow-rgb), 0.3);
  backdrop-filter: blur(12px);

  @media (max-width: 600px) {
    left: 12px;
    right: 12px;
    bottom: 60px;
  }
}

.thinking-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  background: var(--vera-panel);
  border-bottom: 1px solid var(--vera-glass-border);
  transition: background-color 0.2s ease;

  &:hover {
    background: var(--vera-panel-alt);
  }
}

.thinking-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--vera-text-muted);
  font-weight: 500;
}

.thinking-icon {
  color: var(--vera-accent);

  &.spinning {
    animation: spin calc(2s / var(--vera-anim-speed, 1)) linear infinite;
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.event-count {
  font-size: 0.75rem;
  opacity: 0.7;
}

.collapse-btn {
  background: transparent;
  border: none;
  color: var(--vera-text-muted);
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s ease;

  &.collapsed {
    transform: rotate(-90deg);
  }
}

.thinking-content {
  padding: 8px 12px;
  max-height: 200px;
  overflow-y: auto;
  scrollbar-width: thin;

  &::-webkit-scrollbar {
    width: 4px;
  }

  &::-webkit-scrollbar-thumb {
    background: var(--vera-scrollbar-thumb);
    border-radius: 2px;
  }
}

.thinking-event {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  margin-bottom: 4px;
  background: transparent;
  transition: background-color 0.15s ease;

  &:last-child {
    margin-bottom: 0;
  }

  &:hover {
    background: var(--vera-accent-faint);
  }
}

.event-icon {
  font-size: 0.9rem;
  flex-shrink: 0;
  line-height: 1.4;
}

.event-message {
  color: var(--vera-text);
  line-height: 1.4;
  word-break: break-word;
}

// Event type specific colors
.event-analyzing {
  .event-message { color: var(--vera-text); }
}

.event-routing {
  .event-message { color: var(--vera-event-routing); }
}

.event-memory {
  .event-message { color: var(--vera-event-memory); }
}

.event-tool {
  .event-message { color: var(--vera-event-tool); }
}

.event-reasoning {
  .event-message { color: var(--vera-text); }
}

.event-decision {
  .event-message {
    color: var(--vera-event-decision);
    font-weight: 500;
  }
}

.event-quorum {
  .event-message { color: var(--vera-event-quorum); }
}

.event-error {
  .event-message { color: var(--vera-status-error); }
}

// Transitions
.thinking-expand-enter-active,
.thinking-expand-leave-active {
  transition: all 0.25s ease;
  max-height: 200px;
  overflow: hidden;
}

.thinking-expand-enter-from,
.thinking-expand-leave-to {
  max-height: 0;
  opacity: 0;
  padding-top: 0;
  padding-bottom: 0;
}
</style>
