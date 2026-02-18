<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue';
import { RefreshCw, GitBranch, ChevronRight, ChevronDown, FileText, Plus, Edit3, Trash2 } from 'lucide-vue-next';

const props = defineProps({
  workingDirectory: {
    type: String,
    default: ''
  }
});

const isLoading = ref(false);
const error = ref('');
const repoStatus = ref(null);
const files = ref([]);
const expandedSections = ref({
  staged: true,
  modified: true,
  untracked: false
});

let refreshInterval = null;

async function fetchStatus() {
  if (isLoading.value) return;
  isLoading.value = true;
  error.value = '';

  try {
    const params = props.workingDirectory ? `?path=${encodeURIComponent(props.workingDirectory)}` : '';
    const [statusRes, filesRes] = await Promise.all([
      fetch(`/api/git/status${params}`),
      fetch(`/api/git/files${params}`)
    ]);

    if (!statusRes.ok) throw new Error('Failed to fetch git status');
    if (!filesRes.ok) throw new Error('Failed to fetch git files');

    repoStatus.value = await statusRes.json();
    const filesData = await filesRes.json();
    files.value = filesData.files || [];
  } catch (e) {
    error.value = e.message;
    console.error('Git status error:', e);
  } finally {
    isLoading.value = false;
  }
}

function toggleSection(section) {
  expandedSections.value[section] = !expandedSections.value[section];
}

function getStatusIcon(status) {
  switch (status) {
    case 'staged':
    case 'added':
      return Plus;
    case 'modified':
      return Edit3;
    case 'deleted':
      return Trash2;
    default:
      return FileText;
  }
}

function getStatusColor(status) {
  switch (status) {
    case 'staged':
    case 'added':
      return 'var(--vera-success)';
    case 'modified':
      return 'var(--vera-warning)';
    case 'deleted':
      return 'var(--vera-danger)';
    case 'untracked':
      return 'var(--vera-text-muted)';
    default:
      return 'var(--vera-text-muted)';
  }
}

// Computed file lists
function getStagedFiles() {
  return files.value.filter(f => f.staged);
}

function getModifiedFiles() {
  return files.value.filter(f => f.is_dirty && !f.staged && f.status !== 'untracked');
}

function getUntrackedFiles() {
  return files.value.filter(f => f.status === 'untracked');
}

onMounted(() => {
  fetchStatus();
  // Refresh every 10 seconds
  refreshInterval = setInterval(fetchStatus, 10000);
});

onBeforeUnmount(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval);
  }
});

// Refresh when working directory changes
watch(() => props.workingDirectory, () => {
  fetchStatus();
});
</script>

<template>
  <div class="git-status-panel">
    <!-- Header -->
    <div class="panel-header">
      <div class="branch-info" v-if="repoStatus?.is_repo">
        <GitBranch size="14" />
        <span class="branch-name">{{ repoStatus.branch }}</span>
        <span v-if="repoStatus.ahead" class="sync-badge ahead">{{ repoStatus.ahead }}</span>
        <span v-if="repoStatus.behind" class="sync-badge behind">{{ repoStatus.behind }}</span>
      </div>
      <div v-else class="no-repo">Not a git repository</div>
      <button class="refresh-btn" @click="fetchStatus" :disabled="isLoading" title="Refresh">
        <RefreshCw size="14" :class="{ spinning: isLoading }" />
      </button>
    </div>

    <!-- Error state -->
    <div v-if="error" class="error-message">{{ error }}</div>

    <!-- Not a repo -->
    <div v-else-if="repoStatus && !repoStatus.is_repo" class="empty-state">
      <p>This directory is not a git repository.</p>
    </div>

    <!-- Clean repo -->
    <div v-else-if="repoStatus?.is_clean" class="clean-state">
      <span class="clean-badge">Clean</span>
      <span class="clean-text">No uncommitted changes</span>
    </div>

    <!-- Files list -->
    <div v-else class="files-container">
      <!-- Staged files -->
      <div v-if="getStagedFiles().length > 0" class="file-section">
        <div class="section-header" @click="toggleSection('staged')">
          <component :is="expandedSections.staged ? ChevronDown : ChevronRight" size="14" />
          <span>Staged</span>
          <span class="count staged">{{ getStagedFiles().length }}</span>
        </div>
        <div v-if="expandedSections.staged" class="file-list">
          <div v-for="file in getStagedFiles()" :key="file.path" class="file-item">
            <component :is="getStatusIcon(file.status)" size="12" :style="{ color: getStatusColor('staged') }" />
            <span class="file-path">{{ file.path }}</span>
          </div>
        </div>
      </div>

      <!-- Modified files -->
      <div v-if="getModifiedFiles().length > 0" class="file-section">
        <div class="section-header" @click="toggleSection('modified')">
          <component :is="expandedSections.modified ? ChevronDown : ChevronRight" size="14" />
          <span>Modified</span>
          <span class="count modified">{{ getModifiedFiles().length }}</span>
        </div>
        <div v-if="expandedSections.modified" class="file-list">
          <div v-for="file in getModifiedFiles()" :key="file.path" class="file-item">
            <component :is="getStatusIcon(file.status)" size="12" :style="{ color: getStatusColor(file.status) }" />
            <span class="file-path">{{ file.path }}</span>
          </div>
        </div>
      </div>

      <!-- Untracked files -->
      <div v-if="getUntrackedFiles().length > 0" class="file-section">
        <div class="section-header" @click="toggleSection('untracked')">
          <component :is="expandedSections.untracked ? ChevronDown : ChevronRight" size="14" />
          <span>Untracked</span>
          <span class="count untracked">{{ getUntrackedFiles().length }}</span>
        </div>
        <div v-if="expandedSections.untracked" class="file-list">
          <div v-for="file in getUntrackedFiles()" :key="file.path" class="file-item">
            <FileText size="12" :style="{ color: getStatusColor('untracked') }" />
            <span class="file-path">{{ file.path }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Last commit -->
    <div v-if="repoStatus?.last_commit" class="last-commit">
      <span class="commit-hash">{{ repoStatus.last_commit.short_hash }}</span>
      <span class="commit-message">{{ repoStatus.last_commit.message }}</span>
    </div>
  </div>
</template>

<style scoped lang="scss">
.git-status-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  color: var(--vera-text);
  font-size: 0.75rem;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--vera-border);
  background: var(--vera-panel-alt);
}

.branch-info {
  display: flex;
  align-items: center;
  gap: 6px;
}

.branch-name {
  font-weight: 600;
  color: var(--vera-accent);
}

.sync-badge {
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 0.625rem;
  font-weight: 600;

  &.ahead {
    background: color-mix(in srgb, var(--vera-git-added) 20%, transparent);
    color: var(--vera-git-added);
  }

  &.behind {
    background: color-mix(in srgb, var(--vera-git-modified) 20%, transparent);
    color: var(--vera-git-modified);
  }
}

.no-repo {
  color: var(--vera-text-muted);
}

.refresh-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--vera-text-muted);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s ease;

  &:hover {
    background: rgba(var(--vera-contrast-rgb), 0.1);
    color: var(--vera-text);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .spinning {
    animation: spin 1s linear infinite;
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.error-message {
  padding: 12px;
  color: var(--vera-git-deleted);
  background: color-mix(in srgb, var(--vera-git-deleted) 10%, transparent);
}

.empty-state,
.clean-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  color: var(--vera-text-muted);
}

.clean-badge {
  padding: 2px 8px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--vera-git-added) 20%, transparent);
  color: var(--vera-git-added);
  font-size: 0.6875rem;
  font-weight: 600;
}

.files-container {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.file-section {
  margin-bottom: 4px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  cursor: pointer;
  color: var(--vera-text-muted);
  transition: background 0.15s ease;

  &:hover {
    background: rgba(var(--vera-contrast-rgb), 0.05);
  }
}

.count {
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 0.625rem;
  font-weight: 600;
  margin-left: auto;

  &.staged {
    background: color-mix(in srgb, var(--vera-git-added) 20%, transparent);
    color: var(--vera-git-added);
  }

  &.modified {
    background: color-mix(in srgb, var(--vera-git-modified) 20%, transparent);
    color: var(--vera-git-modified);
  }

  &.untracked {
    background: color-mix(in srgb, var(--vera-git-untracked) 15%, transparent);
    color: var(--vera-git-untracked);
  }
}

.file-list {
  padding: 0 8px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  border-radius: 4px;
  transition: background 0.15s ease;

  &:hover {
    background: rgba(var(--vera-contrast-rgb), 0.05);
  }
}

.file-path {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--vera-text);
}

.last-commit {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid var(--vera-border);
  background: var(--vera-panel-alt);
  color: var(--vera-text-muted);
  font-size: 0.6875rem;
}

.commit-hash {
  font-family: monospace;
  color: var(--vera-accent);
}

.commit-message {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
