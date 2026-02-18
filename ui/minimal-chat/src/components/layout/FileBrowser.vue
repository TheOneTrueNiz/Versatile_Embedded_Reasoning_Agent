<script setup>
import { ref, watch, computed, defineExpose } from 'vue';
import { showToast } from '@/libs/utils/general-utils';

const props = defineProps({
  workingDirectory: {
    type: String,
    default: ''
  },
  collapsed: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['file-selected', 'directory-changed', 'toggle-collapse']);

// State
const files = ref([]);
const currentPath = ref('');
const isLoading = ref(false);
const expandedFolders = ref(new Set());
const directoryInput = ref('');
const showDirectoryInput = ref(false);

// File type icons (using unicode for simplicity)
const getFileIcon = (file) => {
  if (file.type === 'directory') return '\u{1F4C1}'; // folder
  const ext = file.name.split('.').pop()?.toLowerCase();
  const iconMap = {
    'js': '\u{1F7E8}',    // yellow square
    'ts': '\u{1F7E6}',    // blue square
    'jsx': '\u{1F7E8}',
    'tsx': '\u{1F7E6}',
    'vue': '\u{1F7E2}',   // green circle
    'py': '\u{1F40D}',    // snake
    'json': '\u{1F4C4}',  // page
    'md': '\u{1F4DD}',    // memo
    'html': '\u{1F310}',  // globe
    'css': '\u{1F3A8}',   // palette
    'scss': '\u{1F3A8}',
    'yaml': '\u{2699}',   // gear
    'yml': '\u{2699}',
    'sh': '\u{1F4BB}',    // computer
    'bash': '\u{1F4BB}',
  };
  return iconMap[ext] || '\u{1F4C4}'; // default file
};

// Fetch files from backend
async function fetchFiles(path = '') {
  isLoading.value = true;
  try {
    const params = new URLSearchParams();
    if (path) params.set('path', path);

    const response = await fetch(`/api/editor/files?${params}`);
    if (!response.ok) {
      const error = await response.json();
      if (response.status === 400 && error.error?.includes('No working directory')) {
        files.value = [];
        return;
      }
      throw new Error(error.error || 'Failed to fetch files');
    }

    const data = await response.json();
    files.value = data.files || [];
    currentPath.value = data.path || '';
  } catch (error) {
    console.error('Failed to fetch files:', error);
    showToast(`Error: ${error.message}`, { duration: 3000 });
    files.value = [];
  } finally {
    isLoading.value = false;
  }
}

// Set working directory
async function setWorkingDirectory(path) {
  if (!path.trim()) return;

  isLoading.value = true;
  try {
    const response = await fetch('/api/editor/workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path.trim() })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || 'Failed to set directory');
    }

    emit('directory-changed', data.working_directory);
    files.value = data.files || [];
    currentPath.value = '';
    expandedFolders.value.clear();
    showDirectoryInput.value = false;
    showToast(`Workspace: ${data.working_directory.split('/').pop()}`);
  } catch (error) {
    showToast(`Error: ${error.message}`, { duration: 5000 });
    console.error('Failed to set working directory:', error);
  } finally {
    isLoading.value = false;
  }
}

// Handle file click
async function handleFileClick(file) {
  const filePath = currentPath.value ? `${currentPath.value}/${file.name}` : file.name;

  if (file.type === 'directory') {
    // Toggle folder expansion
    if (expandedFolders.value.has(filePath)) {
      expandedFolders.value.delete(filePath);
    } else {
      expandedFolders.value.add(filePath);
    }
  } else {
    // Open file in editor
    emit('file-selected', filePath);
  }
}

// Navigate to parent directory
function navigateUp() {
  if (!currentPath.value) return;
  const parts = currentPath.value.split('/');
  parts.pop();
  const parentPath = parts.join('/');
  fetchFiles(parentPath);
}

// Navigate into a directory
function navigateInto(dirName) {
  const newPath = currentPath.value ? `${currentPath.value}/${dirName}` : dirName;
  fetchFiles(newPath);
}

// Watch for working directory changes
watch(() => props.workingDirectory, (newDir) => {
  if (newDir) {
    directoryInput.value = newDir;
    fetchFiles();
  }
}, { immediate: true });

// Computed: breadcrumb path parts
const breadcrumbParts = computed(() => {
  if (!currentPath.value) return [];
  return currentPath.value.split('/');
});

// Show directory input
function showSetDirectory() {
  showDirectoryInput.value = true;
  directoryInput.value = props.workingDirectory || '';
}

function refreshFiles() {
  if (!props.workingDirectory) return;
  fetchFiles(currentPath.value);
}

defineExpose({ refreshFiles });
</script>

<template>
  <div class="file-browser" :class="{ collapsed: collapsed }">
    <!-- Header -->
    <div class="browser-header">
      <button class="collapse-btn" @click="$emit('toggle-collapse')" :title="collapsed ? 'Expand' : 'Collapse'">
        <svg v-if="collapsed" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="9 18 15 12 9 6"></polyline>
        </svg>
        <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
      </button>
      <span class="header-title" v-if="!collapsed">Files</span>
      <button v-if="!collapsed" class="set-dir-btn" @click="showSetDirectory" title="Set working directory">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
          <line x1="12" y1="11" x2="12" y2="17"></line>
          <line x1="9" y1="14" x2="15" y2="14"></line>
        </svg>
      </button>
    </div>

    <template v-if="!collapsed">
      <!-- Directory Input -->
      <div v-if="showDirectoryInput" class="directory-input-section">
        <input
          v-model="directoryInput"
          type="text"
          class="directory-input"
          placeholder="/path/to/project"
          @keyup.enter="setWorkingDirectory(directoryInput)"
          @keyup.esc="showDirectoryInput = false"
        />
        <div class="directory-input-actions">
          <button class="action-btn confirm" @click="setWorkingDirectory(directoryInput)">Set</button>
          <button class="action-btn cancel" @click="showDirectoryInput = false">Cancel</button>
        </div>
      </div>

      <!-- Working Directory Display -->
      <div v-if="workingDirectory && !showDirectoryInput" class="working-dir-display">
        <span class="dir-icon">\u{1F4C2}</span>
        <span class="dir-path" :title="workingDirectory">{{ workingDirectory.split('/').pop() }}</span>
      </div>

      <!-- No Directory Set -->
      <div v-if="!workingDirectory && !showDirectoryInput" class="no-directory">
        <p>No project selected</p>
        <button class="select-dir-btn" @click="showSetDirectory">Select Directory</button>
      </div>

      <!-- Breadcrumb Navigation -->
      <div v-if="workingDirectory && currentPath" class="breadcrumb">
        <button class="breadcrumb-item root" @click="fetchFiles('')" title="Go to root">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
          </svg>
        </button>
        <template v-for="(part, index) in breadcrumbParts" :key="index">
          <span class="breadcrumb-separator">/</span>
          <button
            class="breadcrumb-item"
            @click="fetchFiles(breadcrumbParts.slice(0, index + 1).join('/'))"
          >
            {{ part }}
          </button>
        </template>
      </div>

      <!-- Loading Indicator -->
      <div v-if="isLoading" class="loading">
        <div class="spinner"></div>
      </div>

      <!-- File List -->
      <div v-else-if="workingDirectory" class="file-list">
        <div v-if="files.length === 0" class="empty-dir">
          No files found
        </div>
        <div
          v-for="file in files"
          :key="file.name"
          class="file-item"
          :class="{ directory: file.type === 'directory' }"
          @click="handleFileClick(file)"
          @dblclick="file.type === 'directory' && navigateInto(file.name)"
        >
          <span class="file-icon">{{ getFileIcon(file) }}</span>
          <span class="file-name">{{ file.name }}</span>
          <span v-if="file.type === 'file' && file.size" class="file-size">
            {{ (file.size / 1024).toFixed(1) }}KB
          </span>
        </div>
      </div>
    </template>
  </div>
</template>

<style lang="scss" scoped>
// ============================================
// VERA File Browser - Premium Glass Card
// Matches the Canvas panel aesthetic
// ============================================

$vera-cyan: var(--vera-accent);
$vera-violet: var(--vera-secondary);

.file-browser {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--vera-file-browser-bg);
  border: 1px solid var(--vera-accent-10);
  border-radius: 12px;
  width: 200px;
  min-width: 200px;
  transition: all 0.2s ease;
  backdrop-filter: blur(8px);
  overflow: hidden;

  &.collapsed {
    width: 36px;
    min-width: 36px;
  }
}

.browser-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  background: var(--vera-glass-strong);
  border-bottom: 1px solid var(--vera-accent-08);
  min-height: 40px;
}

.header-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--vera-text);
  flex: 1;
  letter-spacing: 0.02em;
}

.collapse-btn, .set-dir-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid var(--vera-accent-10);
  background: var(--vera-glass-bg);
  color: var(--vera-text-muted);
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-30);
    background: var(--vera-accent-10);
    color: $vera-cyan;
    box-shadow: 0 0 8px var(--vera-accent-15);
  }
}

.directory-input-section {
  padding: 10px;
  background: var(--vera-glass-bg);
  border-bottom: 1px solid var(--vera-accent-08);
}

.directory-input {
  width: 100%;
  padding: 8px 10px;
  font-size: 0.6875rem;
  background: var(--vera-input-bg);
  border: 1px solid var(--vera-accent-12);
  border-radius: 8px;
  color: var(--vera-text);
  margin-bottom: 8px;
  font-family: 'JetBrains Mono', monospace;
  transition: all 0.2s ease;

  &:focus {
    outline: none;
    border-color: var(--vera-accent-40);
    box-shadow: 0 0 0 2px var(--vera-accent-08);
  }

  &::placeholder {
    color: var(--vera-text-muted);
  }
}

.directory-input-actions {
  display: flex;
  gap: 6px;
}

.action-btn {
  flex: 1;
  padding: 6px 10px;
  font-size: 0.6875rem;
  font-weight: 500;
  border: 1px solid transparent;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s ease;

  &.confirm {
    background: linear-gradient(135deg, var(--vera-accent-25), var(--vera-accent-10));
    border-color: var(--vera-accent-40);
    color: $vera-cyan;

    &:hover {
      box-shadow: 0 0 12px var(--vera-accent-20);
    }
  }

  &.cancel {
    background: var(--vera-glass-bg);
    border-color: var(--vera-accent-10);
    color: var(--vera-text-muted);

    &:hover {
      border-color: var(--vera-accent-20);
      color: var(--vera-text);
    }
  }
}

.working-dir-display {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  background: var(--vera-glass-bg);
  border-bottom: 1px solid var(--vera-accent-08);
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    background: var(--vera-accent-05);
    color: var(--vera-text);
  }
}

.dir-icon {
  font-size: 0.875rem;
  filter: drop-shadow(0 0 4px var(--vera-accent-30));
}

.dir-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.no-directory {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 30px 16px;
  text-align: center;

  p {
    font-size: 0.75rem;
    color: var(--vera-text-muted);
    margin: 0 0 16px 0;
  }
}

.select-dir-btn {
  padding: 10px 20px;
  font-size: 0.75rem;
  font-weight: 600;
  background: linear-gradient(135deg, var(--vera-accent-25), var(--vera-accent-10));
  border: 1px solid var(--vera-accent-40);
  color: $vera-cyan;
  border-radius: 20px;
  cursor: pointer;
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
    background: linear-gradient(90deg, transparent, var(--vera-accent-20), transparent);
    transition: left 0.4s ease;
  }

  &:hover {
    box-shadow: 0 0 20px var(--vera-accent-25);

    &::before {
      left: 100%;
    }
  }
}

.breadcrumb {
  display: flex;
  align-items: center;
  padding: 6px 10px;
  font-size: 0.625rem;
  color: var(--vera-text-muted);
  background: var(--vera-glass-bg);
  border-bottom: 1px solid var(--vera-accent-08);
  flex-wrap: wrap;
  gap: 2px;
}

.breadcrumb-item {
  padding: 3px 6px;
  background: transparent;
  border: 1px solid transparent;
  color: var(--vera-text-muted);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s ease;

  &:hover {
    background: var(--vera-accent-08);
    border-color: var(--vera-accent-15);
    color: $vera-cyan;
  }

  &.root {
    padding: 3px;
  }
}

.breadcrumb-separator {
  color: var(--vera-text-muted);
  opacity: 0.4;
}

.loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 30px;
}

.spinner {
  width: 22px;
  height: 22px;
  border: 2px solid var(--vera-accent-15);
  border-top-color: $vera-cyan;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  box-shadow: 0 0 10px var(--vera-accent-15);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.file-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;

  &::-webkit-scrollbar {
    width: 5px;
  }

  &::-webkit-scrollbar-track {
    background: var(--vera-accent-05);
    border-radius: 3px;
  }

  &::-webkit-scrollbar-thumb {
    background: var(--vera-accent-15);
    border-radius: 3px;

    &:hover {
      background: var(--vera-accent-25);
    }
  }
}

.empty-dir {
  padding: 20px;
  text-align: center;
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  border-radius: 8px;
  border: 1px solid transparent;
  transition: all 0.15s ease;
  margin-bottom: 2px;

  &:hover {
    background: var(--vera-accent-08);
    border-color: var(--vera-accent-10);
  }

  &.directory {
    font-weight: 500;

    &:hover {
      background: var(--vera-secondary-08);
      border-color: var(--vera-secondary-10);
    }
  }
}

.file-icon {
  font-size: 0.875rem;
  width: 20px;
  text-align: center;
}

.file-name {
  flex: 1;
  font-size: 0.6875rem;
  color: var(--vera-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  font-size: 0.625rem;
  color: var(--vera-text-muted);
  opacity: 0.6;
  padding: 1px 6px;
  background: var(--vera-accent-05);
  border-radius: 8px;
}
</style>
