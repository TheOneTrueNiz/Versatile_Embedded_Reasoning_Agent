<script setup>
import { ref, computed } from 'vue';
import { Code, FileCode, Trash2, Play, Copy, Check, ChevronDown, ChevronUp } from 'lucide-vue-next';

const props = defineProps({
  artifact: {
    type: Object,
    required: true
  }
});

const emit = defineEmits(['load', 'delete', 'copy']);

const isExpanded = ref(false);
const isCopied = ref(false);

// Language display names
const languageLabels = {
  javascript: 'JavaScript',
  typescript: 'TypeScript',
  python: 'Python',
  json: 'JSON',
  html: 'HTML',
  css: 'CSS',
  markdown: 'Markdown',
  yaml: 'YAML',
  shell: 'Shell',
  sql: 'SQL',
  xml: 'XML',
  rust: 'Rust',
  go: 'Go',
  java: 'Java',
  cpp: 'C++',
  c: 'C',
  plaintext: 'Text'
};

const languageLabel = computed(() => {
  return languageLabels[props.artifact.language] || props.artifact.language || 'Text';
});

const previewLines = computed(() => {
  const lines = props.artifact.content.split('\n');
  return lines.slice(0, 5).join('\n');
});

const hasMoreContent = computed(() => {
  return props.artifact.content.split('\n').length > 5;
});

const formatDate = (isoDate) => {
  if (!isoDate) return '';
  const date = new Date(isoDate);
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
};

async function copyToClipboard() {
  try {
    await navigator.clipboard.writeText(props.artifact.content);
    isCopied.value = true;
    setTimeout(() => {
      isCopied.value = false;
    }, 2000);
    emit('copy', props.artifact);
  } catch (err) {
    console.error('Failed to copy:', err);
  }
}

function loadIntoCanvas() {
  emit('load', props.artifact);
}

function deleteArtifact() {
  emit('delete', props.artifact);
}
</script>

<template>
  <div class="artifact-card" :class="{ expanded: isExpanded }">
    <!-- Header -->
    <div class="artifact-header" @click="isExpanded = !isExpanded">
      <div class="artifact-icon">
        <FileCode :size="18" />
      </div>
      <div class="artifact-info">
        <span class="artifact-title">{{ artifact.title }}</span>
        <span class="artifact-meta">
          <span class="language-badge">{{ languageLabel }}</span>
          <span class="artifact-date" v-if="artifact.updated_at">
            {{ formatDate(artifact.updated_at) }}
          </span>
          <span class="artifact-creator" v-if="artifact.created_by === 'vera'">
            by VERA
          </span>
        </span>
      </div>
      <div class="artifact-actions">
        <button class="action-btn copy-btn" @click.stop="copyToClipboard" title="Copy to clipboard">
          <Check v-if="isCopied" :size="14" />
          <Copy v-else :size="14" />
        </button>
        <button class="action-btn load-btn" @click.stop="loadIntoCanvas" title="Load into Canvas">
          <Play :size="14" />
        </button>
        <button class="action-btn delete-btn" @click.stop="deleteArtifact" title="Delete artifact">
          <Trash2 :size="14" />
        </button>
        <button class="action-btn expand-btn" @click.stop="isExpanded = !isExpanded">
          <ChevronUp v-if="isExpanded" :size="14" />
          <ChevronDown v-else :size="14" />
        </button>
      </div>
    </div>

    <!-- Preview / Content -->
    <div class="artifact-content" v-if="isExpanded || hasMoreContent">
      <pre class="code-preview"><code>{{ isExpanded ? artifact.content : previewLines }}</code></pre>
      <div class="expand-hint" v-if="!isExpanded && hasMoreContent">
        Click to expand...
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.artifact-card {
  background: var(--vera-panel-alt);
  border: 1px solid var(--vera-border);
  border-radius: 8px;
  margin: 8px 0;
  overflow: hidden;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-soft);
    box-shadow: 0 2px 8px rgba(var(--vera-shadow-rgb), 0.15);
  }

  &.expanded {
    border-color: var(--vera-accent);
  }
}

.artifact-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  cursor: pointer;
  transition: background 0.15s ease;

  &:hover {
    background: var(--vera-panel);
  }
}

.artifact-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: var(--vera-accent-faint);
  border-radius: 6px;
  color: var(--vera-accent);
  flex-shrink: 0;
}

.artifact-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.artifact-title {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--vera-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.artifact-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
}

.language-badge {
  background: var(--vera-accent-faint);
  color: var(--vera-accent);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.625rem;
  font-weight: 500;
}

.artifact-creator {
  font-style: italic;
  color: var(--vera-accent);
}

.artifact-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  background: transparent;
  color: var(--vera-text-muted);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s ease;

  &:hover {
    background: var(--vera-panel);
    color: var(--vera-text);
  }

  &.load-btn:hover {
    background: var(--vera-accent-faint);
    color: var(--vera-accent);
  }

  &.delete-btn:hover {
    background: var(--vera-error-15);
    color: var(--vera-danger);
  }

  &.copy-btn:hover {
    background: var(--vera-accent-faint);
    color: var(--vera-accent);
  }
}

.artifact-content {
  border-top: 1px solid var(--vera-border);
  padding: 8px 12px;
  background: var(--vera-surface);
}

.code-preview {
  margin: 0;
  padding: 8px;
  background: var(--vera-panel-muted);
  border-radius: 4px;
  overflow-x: auto;
  max-height: 300px;
  overflow-y: auto;

  code {
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 0.75rem;
    line-height: 1.5;
    color: var(--vera-text);
    white-space: pre;
  }
}

.expand-hint {
  text-align: center;
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  padding: 4px;
  cursor: pointer;

  &:hover {
    color: var(--vera-accent);
  }
}
</style>
