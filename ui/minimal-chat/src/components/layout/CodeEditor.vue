<script setup>
import { ref, watch, onMounted, onBeforeUnmount, computed, nextTick } from 'vue';
import { VueMonacoEditor } from '@guolao/vue-monaco-editor';
import { showToast } from '@/libs/utils/general-utils';
import FileBrowser from './FileBrowser.vue';

const props = defineProps({
  collapsed: {
    type: Boolean,
    default: false
  },
  minimized: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['close', 'toggle-collapse', 'file-saved', 'save-artifact', 'directory-changed']);

// Editor state
const editorRef = ref(null);
const code = ref('// Welcome to VERA Code Editor\n// Start coding or open a file...\n\nconsole.log("Hello, VERA!");');
const language = ref('javascript');
const currentFilePath = ref('');
const isModified = ref(false);
const isSaving = ref(false);
const isLoading = ref(false);

// Backend sync state
const syncIntervalId = ref(null);
const lastBackendContent = ref('');
const isSyncingFromBackend = ref(false);
const veraIsActive = ref(false);
const SYNC_INTERVAL_MS = 1500; // Poll every 1.5 seconds

// File browser state
const workingDirectory = ref('');
const showFileBrowser = ref(true);
const fileBrowserCollapsed = ref(false);
const fileBrowserRef = ref(null);

// Path prompt state
const showPathPrompt = ref(false);
const pathPromptValue = ref('');
const pathPromptMode = ref('save');
const pathPromptError = ref('');
const pathPromptInputRef = ref(null);

// Available languages
const languages = [
  { value: 'javascript', label: 'JavaScript' },
  { value: 'typescript', label: 'TypeScript' },
  { value: 'python', label: 'Python' },
  { value: 'json', label: 'JSON' },
  { value: 'html', label: 'HTML' },
  { value: 'css', label: 'CSS' },
  { value: 'markdown', label: 'Markdown' },
  { value: 'yaml', label: 'YAML' },
  { value: 'shell', label: 'Shell' },
  { value: 'sql', label: 'SQL' },
  { value: 'xml', label: 'XML' },
  { value: 'rust', label: 'Rust' },
  { value: 'go', label: 'Go' },
  { value: 'java', label: 'Java' },
  { value: 'cpp', label: 'C++' },
  { value: 'c', label: 'C' }
];

// Editor options
const editorOptions = {
  theme: 'vs-dark',
  fontSize: 14,
  fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
  minimap: { enabled: true },
  scrollBeyondLastLine: false,
  wordWrap: 'on',
  automaticLayout: true,
  tabSize: 2,
  insertSpaces: true,
  formatOnPaste: true,
  formatOnType: true,
  renderWhitespace: 'selection',
  lineNumbers: 'on',
  glyphMargin: true,
  folding: true,
  bracketPairColorization: { enabled: true }
};

const MONACO_THEME_NAME = 'vera-theme';
let monacoThemeRaf = null;

const readToken = (token, fallback = '') => {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return value || fallback;
};

const applyMonacoTheme = () => {
  if (typeof window === 'undefined' || !window.monaco || !editorRef.value) {
    return;
  }
  const monaco = window.monaco;
  const background = readToken('--vera-code-editor-bg', readToken('--vera-panel', '#1e1e1e'));
  const foreground = readToken('--vera-text', '#ffffff');
  const muted = readToken('--vera-text-muted', '#8ea0b4');
  const accent = readToken('--vera-accent', '#0099ff');
  const accentSoft = readToken('--vera-accent-20', readToken('--vera-accent-soft', 'rgba(0, 153, 255, 0.2)'));
  const accentFaint = readToken('--vera-accent-10', readToken('--vera-accent-faint', 'rgba(0, 153, 255, 0.12)'));
  const panelAlt = readToken('--vera-panel-alt', readToken('--vera-panel', '#1a2230'));
  const border = readToken('--vera-border', 'rgba(255, 255, 255, 0.12)');

  monaco.editor.defineTheme(MONACO_THEME_NAME, {
    base: 'vs-dark',
    inherit: true,
    rules: [],
    colors: {
      'editor.background': background,
      'editor.foreground': foreground,
      'editorLineNumber.foreground': muted,
      'editorLineNumber.activeForeground': foreground,
      'editorCursor.foreground': accent,
      'editor.selectionBackground': accentSoft,
      'editor.inactiveSelectionBackground': accentFaint,
      'editor.lineHighlightBackground': panelAlt,
      'editor.lineHighlightBorder': border,
      'editorIndentGuide.background': border,
      'editorIndentGuide.activeBackground': accentSoft,
      'editorWhitespace.foreground': border,
      'editorGutter.background': background,
      'editorWidget.background': panelAlt,
      'editorWidget.border': border,
      'editorSuggestWidget.background': panelAlt,
      'editorSuggestWidget.foreground': foreground,
      'editorSuggestWidget.selectedBackground': accentFaint,
      'editorSuggestWidget.border': border,
      'list.activeSelectionBackground': accentFaint,
      'list.activeSelectionForeground': foreground,
      'list.hoverBackground': accentFaint,
      'list.hoverForeground': foreground,
      'peekViewEditor.background': panelAlt,
      'peekViewResult.background': panelAlt,
      'peekViewBorder': border,
      'scrollbar.shadow': 'transparent'
    }
  });
  monaco.editor.setTheme(MONACO_THEME_NAME);
};

const scheduleMonacoThemeUpdate = () => {
  if (typeof window === 'undefined') return;
  if (monacoThemeRaf) {
    window.cancelAnimationFrame(monacoThemeRaf);
  }
  monacoThemeRaf = window.requestAnimationFrame(() => {
    monacoThemeRaf = null;
    applyMonacoTheme();
  });
};

// File extension to language mapping
const extensionToLanguage = {
  '.js': 'javascript',
  '.jsx': 'javascript',
  '.ts': 'typescript',
  '.tsx': 'typescript',
  '.py': 'python',
  '.json': 'json',
  '.html': 'html',
  '.htm': 'html',
  '.css': 'css',
  '.scss': 'css',
  '.md': 'markdown',
  '.yaml': 'yaml',
  '.yml': 'yaml',
  '.sh': 'shell',
  '.bash': 'shell',
  '.sql': 'sql',
  '.xml': 'xml',
  '.rs': 'rust',
  '.go': 'go',
  '.java': 'java',
  '.cpp': 'cpp',
  '.c': 'c',
  '.h': 'c',
  '.vue': 'html'
};

function detectLanguage(filePath) {
  if (!filePath) return 'javascript';
  const ext = filePath.substring(filePath.lastIndexOf('.')).toLowerCase();
  return extensionToLanguage[ext] || 'plaintext';
}

function normalizePath(path) {
  if (!path) return '';
  const trimmed = path.trim();
  if (!trimmed) return '';
  if (workingDirectory.value && !trimmed.startsWith('/') && !trimmed.startsWith('~')) {
    const base = workingDirectory.value.replace(/\/+$/, '');
    return `${base}/${trimmed}`;
  }
  return trimmed;
}

function openPathPrompt(mode) {
  pathPromptMode.value = mode;
  pathPromptError.value = '';
  const baseDir = workingDirectory.value
    ? `${workingDirectory.value.replace(/\/+$/, '')}/`
    : '/';
  pathPromptValue.value = currentFilePath.value || baseDir;
  showPathPrompt.value = true;
  nextTick(() => {
    if (pathPromptInputRef.value) {
      pathPromptInputRef.value.focus();
      if (pathPromptInputRef.value.select) {
        pathPromptInputRef.value.select();
      }
    }
  });
}

function closePathPrompt() {
  showPathPrompt.value = false;
  pathPromptError.value = '';
}

async function confirmPathPrompt() {
  const resolvedPath = normalizePath(pathPromptValue.value);
  if (!resolvedPath) {
    pathPromptError.value = 'Path is required';
    return;
  }
  if (resolvedPath.endsWith('/')) {
    pathPromptError.value = 'Provide a file name';
    return;
  }

  showPathPrompt.value = false;
  pathPromptError.value = '';

  if (pathPromptMode.value === 'new') {
    code.value = '';
    isModified.value = false;
  }

  currentFilePath.value = resolvedPath;
  language.value = detectLanguage(resolvedPath);

  await saveFile();
}

// Backend sync functions
async function fetchEditorState() {
  try {
    const response = await fetch('/api/editor');
    if (!response.ok) return;

    const state = await response.json();

    // Update working directory if changed
    if (state.working_directory && state.working_directory !== workingDirectory.value) {
      workingDirectory.value = state.working_directory;
      emit('directory-changed', state.working_directory);
    }

    // Check if VERA has written new content
    if (state.content !== lastBackendContent.value && state.content !== code.value) {
      isSyncingFromBackend.value = true;
      code.value = state.content;
      lastBackendContent.value = state.content;

      if (state.file_path) {
        currentFilePath.value = state.file_path;
      }
      if (state.language && state.language !== language.value) {
        language.value = state.language;
      }

      // Show notification that VERA updated the editor
      veraIsActive.value = true;
      showToast('VERA updated the editor');
      setTimeout(() => {
        veraIsActive.value = false;
      }, 2000);

      isSyncingFromBackend.value = false;
    } else if (state.language && state.language !== language.value) {
      // VERA changed language only
      language.value = state.language;
    }
  } catch (error) {
    console.error('Failed to fetch editor state:', error);
  }
}

async function pushStateToBackend() {
  if (isSyncingFromBackend.value) return; // Don't push if we're syncing from backend

  try {
    await fetch('/api/editor', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: code.value,
        file_path: currentFilePath.value,
        language: language.value,
        is_open: true
      })
    });
    lastBackendContent.value = code.value;
  } catch (error) {
    console.error('Failed to push editor state:', error);
  }
}

// Debounced push to backend
let pushDebounceTimer = null;
function debouncedPushToBackend() {
  if (pushDebounceTimer) clearTimeout(pushDebounceTimer);
  pushDebounceTimer = setTimeout(pushStateToBackend, 500);
}

function startSync() {
  // Initial fetch
  fetchEditorState();
  // Push initial state
  pushStateToBackend();
  // Start polling
  syncIntervalId.value = setInterval(fetchEditorState, SYNC_INTERVAL_MS);
}

function stopSync() {
  if (syncIntervalId.value) {
    clearInterval(syncIntervalId.value);
    syncIntervalId.value = null;
  }
  // Notify backend that editor is closed
  fetch('/api/editor', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_open: false })
  }).catch(() => {});
}

// Handle editor mount
function handleEditorMount(editor) {
  editorRef.value = editor;
  scheduleMonacoThemeUpdate();

  // Add keyboard shortcuts
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
    saveFile();
  });

  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyO, () => {
    openFileDialog();
  });
}

// Track modifications and sync to backend
watch(code, (newVal, oldVal) => {
  if (oldVal !== undefined && newVal !== oldVal) {
    isModified.value = true;
    // Push changes to backend (debounced) so VERA can see them
    if (!isSyncingFromBackend.value) {
      debouncedPushToBackend();
    }
  }
});

// Lifecycle hooks for sync
onMounted(() => {
  startSync();
  if (typeof window !== 'undefined') {
    window.addEventListener('vera-theme-updated', scheduleMonacoThemeUpdate);
  }
});

onBeforeUnmount(() => {
  stopSync();
  if (pushDebounceTimer) clearTimeout(pushDebounceTimer);
  if (typeof window !== 'undefined') {
    window.removeEventListener('vera-theme-updated', scheduleMonacoThemeUpdate);
    if (monacoThemeRaf) window.cancelAnimationFrame(monacoThemeRaf);
  }
});

// Open file dialog
async function openFileDialog() {
  const path = prompt('Enter file path to open:', currentFilePath.value || '/');
  if (!path) return;
  await openFile(path);
}

// Open file from path
async function openFile(filePath) {
  isLoading.value = true;
  try {
    const response = await fetch('/api/file/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Failed to open file');
    }

    const data = await response.json();
    code.value = data.content;
    currentFilePath.value = filePath;
    language.value = detectLanguage(filePath);
    isModified.value = false;
    showToast(`Opened: ${filePath.split('/').pop()}`);
  } catch (error) {
    showToast(`Error: ${error.message}`, { duration: 5000 });
    console.error('Failed to open file:', error);
  } finally {
    isLoading.value = false;
  }
}

// Save file
async function saveFile() {
  if (!currentFilePath.value) {
    openPathPrompt('save');
    return;
  }

  isSaving.value = true;
  try {
    const response = await fetch('/api/file/write', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: currentFilePath.value,
        content: code.value
      })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Failed to save file');
    }

    isModified.value = false;
    showToast(`Saved: ${currentFilePath.value.split('/').pop()}`);
    emit('file-saved', currentFilePath.value);
    if (fileBrowserRef.value?.refreshFiles) {
      fileBrowserRef.value.refreshFiles();
    }
  } catch (error) {
    showToast(`Error: ${error.message}`, { duration: 5000 });
    console.error('Failed to save file:', error);
  } finally {
    isSaving.value = false;
  }
}

// Save file as new path
async function saveFileAs() {
  openPathPrompt('save');
}

// New file
function newFile() {
  if (isModified.value) {
    if (!confirm('You have unsaved changes. Create new file anyway?')) {
      return;
    }
  }
  openPathPrompt('new');
}

// Format document
function formatDocument() {
  if (editorRef.value) {
    editorRef.value.getAction('editor.action.formatDocument')?.run();
  }
}

// Save as artifact
function saveAsArtifact() {
  if (!code.value.trim()) {
    showToast('Nothing to save as artifact');
    return;
  }

  const title = prompt('Enter artifact title:', currentFilePath.value?.split('/').pop() || 'Untitled');
  if (title === null) return; // Cancelled

  emit('save-artifact', {
    title: title || 'Untitled',
    content: code.value,
    language: language.value,
    file_path: currentFilePath.value,
    created_by: 'user'
  });

  showToast('Saved as artifact');
}

// Undo from backend history (undoes VERA's changes)
const isUndoing = ref(false);
async function undoFromBackend() {
  if (isUndoing.value) return;

  isUndoing.value = true;
  try {
    const response = await fetch('/api/editor/undo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });

    const data = await response.json();

    if (!data.success) {
      showToast(data.error || 'Nothing to undo');
      return;
    }

    // Update local state from response
    isSyncingFromBackend.value = true;
    if (data.state) {
      code.value = data.state.content;
      currentFilePath.value = data.state.file_path || '';
      language.value = data.state.language || 'javascript';
      lastBackendContent.value = data.state.content;
    }
    isSyncingFromBackend.value = false;

    const remaining = data.undo_remaining || 0;
    showToast(`Undo successful (${remaining} more available)`);
  } catch (error) {
    console.error('Undo failed:', error);
    showToast('Undo failed: ' + error.message, { duration: 3000 });
  } finally {
    isUndoing.value = false;
  }
}

// Computed for display
const fileName = computed(() => {
  if (!currentFilePath.value) return 'Untitled';
  return currentFilePath.value.split('/').pop();
});

const displayTitle = computed(() => {
  return isModified.value ? `${fileName.value} *` : fileName.value;
});

// Handle file selected from browser
async function handleFileSelected(filePath) {
  isLoading.value = true;
  try {
    const response = await fetch('/api/editor/file/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Failed to open file');
    }

    const data = await response.json();
    // State will be updated via the sync mechanism
    showToast(`Opened: ${filePath.split('/').pop()}`);
    isModified.value = false;
  } catch (error) {
    showToast(`Error: ${error.message}`, { duration: 5000 });
    console.error('Failed to open file:', error);
  } finally {
    isLoading.value = false;
  }
}

// Handle working directory changed
function handleDirectoryChanged(newDir) {
  workingDirectory.value = newDir;
  emit('directory-changed', newDir);
}

// Watch language changes to push to backend
watch(language, (newLang, oldLang) => {
  if (oldLang !== undefined && newLang !== oldLang && !isSyncingFromBackend.value) {
    // Push language change to backend
    fetch('/api/editor', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: newLang })
    }).catch(err => console.error('Failed to sync language:', err));
  }
});
</script>

<template>
  <div class="code-editor-panel" :class="{ collapsed: collapsed, minimized: minimized }">
    <!-- Premium animated background layers -->
    <div class="bg-layer bg-grid-dots"></div>
    <div class="bg-layer bg-code-rain">
      <span v-for="i in 8" :key="'rain-'+i" class="code-particle" :style="{ animationDelay: `${i * 0.6}s` }"></span>
    </div>
    <div class="bg-layer bg-gradient-glow"></div>
    <div class="bg-layer bg-scan-lines"></div>

    <!-- Header -->
    <div class="editor-header">
      <div class="header-left">
        <button class="icon-btn" @click="$emit('toggle-collapse')" :title="collapsed ? 'Expand' : 'Collapse'">
          <svg v-if="collapsed" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="15 18 9 12 15 6"></polyline>
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="9 18 15 12 9 6"></polyline>
          </svg>
        </button>
        <span class="editor-title" v-if="!collapsed">{{ displayTitle }}</span>
      </div>

      <div class="header-actions" v-if="!collapsed">
        <button class="action-btn" @click="newFile" title="New File (Ctrl+N)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="12" y1="18" x2="12" y2="12"></line>
            <line x1="9" y1="15" x2="15" y2="15"></line>
          </svg>
        </button>
        <button class="action-btn" @click="openFileDialog" title="Open File (Ctrl+O)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
          </svg>
        </button>
        <button class="action-btn" @click="saveFile" :disabled="isSaving" title="Save (Ctrl+S)">
          <svg v-if="!isSaving" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
            <polyline points="17 21 17 13 7 13 7 21"></polyline>
            <polyline points="7 3 7 8 15 8"></polyline>
          </svg>
          <span v-else class="spinner-small"></span>
        </button>
        <button class="action-btn" @click="saveFileAs" title="Save As...">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>
          </svg>
        </button>
        <button class="action-btn" @click="formatDocument" title="Format Document">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="21" y1="10" x2="3" y2="10"></line>
            <line x1="21" y1="6" x2="3" y2="6"></line>
            <line x1="21" y1="14" x2="3" y2="14"></line>
            <line x1="21" y1="18" x2="3" y2="18"></line>
          </svg>
        </button>
        <button class="action-btn undo-btn" @click="undoFromBackend" :disabled="isUndoing" title="Undo VERA's Changes">
          <svg v-if="!isUndoing" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 7v6h6"></path>
            <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"></path>
          </svg>
          <span v-else class="spinner-small"></span>
        </button>
        <button class="action-btn artifact-btn labeled-btn" @click="saveAsArtifact" title="Save as Artifact">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <path d="M12 18v-6"></path>
            <path d="M9 15l3 3 3-3"></path>
          </svg>
          <span class="btn-label">Artifact</span>
        </button>

        <select v-model="language" class="language-select" title="Language">
          <option v-for="lang in languages" :key="lang.value" :value="lang.value">
            {{ lang.label }}
          </option>
        </select>

        <button class="icon-btn close-btn" @click="$emit('close')" title="Close Editor">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
    </div>

    <!-- Editor Body -->
    <div class="editor-body" v-if="!collapsed && !minimized">
      <!-- File Browser -->
      <FileBrowser
        v-if="showFileBrowser"
        :working-directory="workingDirectory"
        :collapsed="fileBrowserCollapsed"
        ref="fileBrowserRef"
        @file-selected="handleFileSelected"
        @directory-changed="handleDirectoryChanged"
        @toggle-collapse="fileBrowserCollapsed = !fileBrowserCollapsed"
      />

      <!-- Editor -->
      <div class="editor-container">
        <div v-if="isLoading" class="loading-overlay">
          <div class="spinner"></div>
          <span>Loading...</span>
        </div>
        <VueMonacoEditor
          v-model:value="code"
          :language="language"
          :options="editorOptions"
          @mount="handleEditorMount"
          class="monaco-editor-instance"
        />
      </div>
    </div>

    <div v-if="showPathPrompt" class="path-prompt-overlay" @click.self="closePathPrompt">
      <div class="path-prompt-card">
        <h4>{{ pathPromptMode === 'new' ? 'Create new file' : 'Save file as' }}</h4>
        <p class="path-prompt-hint" v-if="workingDirectory">
          Workspace: {{ workingDirectory }}
        </p>
        <input
          ref="pathPromptInputRef"
          v-model="pathPromptValue"
          type="text"
          class="path-prompt-input"
          placeholder="/path/to/file"
          @keyup.enter="confirmPathPrompt"
          @keyup.esc="closePathPrompt"
        />
        <p v-if="pathPromptError" class="path-prompt-error">{{ pathPromptError }}</p>
        <div class="path-prompt-actions">
          <button class="action-btn cancel" @click="closePathPrompt">Cancel</button>
          <button class="action-btn confirm" @click="confirmPathPrompt">
            {{ pathPromptMode === 'new' ? 'Create' : 'Save' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Status Bar -->
    <div class="status-bar" v-if="!collapsed && !minimized">
      <span class="status-item vera-indicator" v-if="veraIsActive">
        <span class="vera-dot"></span>
        VERA Active
      </span>
      <span class="status-item">{{ language }}</span>
      <span class="status-item" v-if="currentFilePath">{{ currentFilePath }}</span>
      <span class="status-item" v-if="isModified">Modified</span>
      <span class="status-item sync-status">Synced</span>
    </div>
  </div>
</template>

<style lang="scss" scoped>
// ============================================
// VERA Code Editor - Premium Glass Panel
// Matches ActivityDrawer/ToolsDrawer aesthetic
// Animated background layers, glass cards, glowing accents
// ============================================

// VERA cool spectrum palette
$vera-cyan: var(--vera-accent);
$vera-violet: var(--vera-secondary);
$vera-glass-bg: var(--vera-code-editor-bg);
$vera-glass-border: var(--vera-accent-12);

.code-editor-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--vera-code-editor-bg);
  border-radius: 16px;
  border: 1px solid $vera-glass-border;
  position: relative;
  transition: all 0.2s ease;
  overflow: hidden;

  // Outer glow
  box-shadow:
    0 0 60px var(--vera-accent-08),
    0 0 100px rgba(var(--vera-secondary-rgb), 0.04),
    inset 0 1px 0 rgba(var(--vera-contrast-rgb), 0.04);

  &.collapsed {
    width: 40px;
    min-width: 40px;
    max-width: 40px;
  }

  &.minimized {
    height: 40px !important;
    min-height: 40px;
    max-height: 40px;
    flex: none;
  }
}

// ============================================
// Background Layers (z-index 1-4)
// ============================================

.bg-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

// Layer 1: Subtle grid dots
.bg-grid-dots {
  z-index: 1;
  background-image: radial-gradient(var(--vera-accent-08) 1px, transparent 1px);
  background-size: 20px 20px;
  opacity: 0.5;
}

// Layer 2: Code rain particles
.bg-code-rain {
  z-index: 2;

  .code-particle {
    position: absolute;
    width: 2px;
    height: 30px;
    background: linear-gradient(180deg, $vera-cyan, transparent);
    border-radius: 2px;
    animation: codeRain 6s linear infinite;
    opacity: 0;

    @for $i from 1 through 8 {
      &:nth-child(#{$i}) {
        left: (8 + ($i - 1) * 12) * 1%;
        animation-duration: (5 + ($i % 3)) * 1s;
      }
    }
  }
}

// Layer 3: Gradient glow spots
.bg-gradient-glow {
  z-index: 3;
  background:
    radial-gradient(ellipse at 15% 20%, var(--vera-accent-10) 0%, transparent 50%),
    radial-gradient(ellipse at 85% 80%, rgba(var(--vera-secondary-rgb), 0.08) 0%, transparent 45%);
  animation: glowShift 10s ease-in-out infinite;
}

// Layer 4: Scan lines
.bg-scan-lines {
  z-index: 4;
  background: repeating-linear-gradient(
    0deg,
    var(--vera-accent-02) 0 1px,
    transparent 1px 4px
  );
  opacity: 0.6;
}

// ============================================
// Header (z-index: 10)
// ============================================

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  height: 44px;
  min-height: 44px;
  background: color-mix(in srgb, var(--vera-panel) 70%, transparent);
  border-bottom: 1px solid var(--vera-accent-10);
  position: relative;
  z-index: 10;

  // Glowing accent line
  &::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    width: 80px;
    height: 2px;
    background: linear-gradient(90deg, $vera-cyan, transparent);
    animation: headerGlow 4s ease-in-out infinite;
  }
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.editor-title {
  font-size: 0.875rem;
  font-weight: 600;
  background: linear-gradient(135deg, var(--vera-text) 0%, $vera-cyan 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

// ============================================
// Buttons - Rounded pills with glow
// ============================================

.icon-btn, .action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--vera-accent-10);
  background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
  color: var(--vera-text-muted);
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;

  // Sweep effect
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

  &:hover {
    border-color: var(--vera-accent-30);
    background: var(--vera-accent-10);
    color: $vera-cyan;
    box-shadow: 0 0 12px var(--vera-accent-15);
    transform: translateY(-1px);

    &::before {
      left: 100%;
    }
  }

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    transform: none;
  }
}

.close-btn:hover {
  border-color: var(--vera-error-30);
  background: var(--vera-error-10);
  color: var(--vera-danger);
  box-shadow: 0 0 12px var(--vera-error-15);
}

.undo-btn {
  color: $vera-cyan;
  border-color: var(--vera-accent-15);

  &:hover {
    background: var(--vera-accent-15);
    box-shadow: 0 0 15px var(--vera-accent-20);
  }
}

.artifact-btn {
  color: var(--vera-success);
  border-color: var(--vera-success-20);

  &:hover {
    border-color: var(--vera-success-40);
    background: var(--vera-success-10);
    box-shadow: 0 0 12px var(--vera-success-20);
  }
}

.labeled-btn {
  width: auto;
  padding: 6px 12px;
  gap: 6px;
  border: 1px solid var(--vera-success-30);
  border-radius: 20px;
  background: var(--vera-success-10);
  color: var(--vera-success);
  animation: artifactGlow 3s ease-in-out infinite;

  &:hover {
    animation: none;
    box-shadow: 0 0 18px var(--vera-success-20);
  }
}

.btn-label {
  font-size: 0.6875rem;
  font-weight: 600;
  white-space: nowrap;
  letter-spacing: 0.02em;
}

.language-select {
  background: var(--vera-accent-08);
  color: var(--vera-text);
  border: 1px solid var(--vera-accent-15);
  border-radius: 20px;
  padding: 5px 12px;
  font-size: 0.6875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-30);
    box-shadow: 0 0 10px var(--vera-accent-10);
  }

  &:focus {
    outline: none;
    border-color: var(--vera-accent-50);
    box-shadow: 0 0 0 2px var(--vera-accent-10);
  }

  option {
    background: var(--vera-code-bg);
    color: var(--vera-text);
  }
}

// ============================================
// Editor Body (z-index: 10)
// ============================================

.editor-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  position: relative;
  z-index: 10;
  margin: 8px;
  gap: 8px;
}

.editor-container {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: color-mix(in srgb, var(--vera-panel-muted) 60%, transparent);
  border: 1px solid var(--vera-accent-08);
  border-radius: 12px;
  backdrop-filter: blur(8px);
}

.monaco-editor-instance {
  width: 100%;
  height: 100%;

  :deep(.monaco-editor),
  :deep(.monaco-editor .margin),
  :deep(.monaco-editor .monaco-editor-background) {
    background-color: var(--vera-code-editor-bg) !important;
  }
}

// ============================================
// Loading & Prompts (z-index: 20+)
// ============================================

.loading-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--vera-panel) 85%, transparent);
  backdrop-filter: blur(12px);
  z-index: 15;
  gap: 12px;
  color: var(--vera-text);
  border-radius: 12px;
}

.path-prompt-overlay {
  position: absolute;
  inset: 0;
  background: color-mix(in srgb, var(--vera-panel) 80%, transparent);
  backdrop-filter: blur(16px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 25;
  padding: 16px;
}

.path-prompt-card {
  width: min(440px, 100%);
  background: color-mix(in srgb, var(--vera-panel) 95%, transparent);
  border: 1px solid var(--vera-accent-15);
  border-radius: 16px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  color: var(--vera-text);
  box-shadow:
    0 8px 32px rgba(var(--vera-shadow-rgb), 0.4),
    0 0 60px var(--vera-accent-08);

  h4 {
    margin: 0;
    font-size: 1rem;
    font-weight: 700;
    background: linear-gradient(135deg, var(--vera-text) 0%, $vera-cyan 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
}

.path-prompt-hint {
  margin: 0;
  font-size: 0.75rem;
  color: var(--vera-text-muted);
}

.path-prompt-input {
  width: 100%;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--vera-accent-15);
  background: color-mix(in srgb, var(--vera-panel) 70%, transparent);
  color: var(--vera-text);
  font-size: 0.8125rem;
  font-family: 'JetBrains Mono', monospace;
  transition: all 0.2s ease;

  &:focus {
    outline: none;
    border-color: var(--vera-accent-50);
    box-shadow: 0 0 0 3px var(--vera-accent-10);
  }

  &::placeholder {
    color: var(--vera-text-muted);
  }
}

.path-prompt-error {
  margin: 0;
  font-size: 0.75rem;
  color: var(--vera-danger);
}

.path-prompt-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 4px;

  .action-btn {
    padding: 10px 20px;
    min-width: 80px;
    border-radius: 20px;
    border: 1px solid var(--vera-accent-15);
    background: var(--vera-accent-08);
    color: var(--vera-text);
    font-size: 0.75rem;
    font-weight: 600;
    transition: all 0.2s ease;
    width: auto;
    height: auto;

    &:hover {
      border-color: var(--vera-accent-30);
      background: var(--vera-accent-12);
      box-shadow: 0 0 15px var(--vera-accent-10);
    }
  }

  .action-btn.confirm {
    background: linear-gradient(135deg, var(--vera-accent-25), var(--vera-accent-10));
    border-color: var(--vera-accent-50);
    color: $vera-cyan;

    &:hover {
      background: linear-gradient(135deg, rgba(var(--vera-accent-rgb), 0.35), var(--vera-accent-15));
      box-shadow: 0 0 20px var(--vera-accent-25);
    }
  }
}

// ============================================
// Spinners
// ============================================

.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid var(--vera-accent-15);
  border-top-color: $vera-cyan;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  box-shadow: 0 0 15px var(--vera-accent-20);
}

.spinner-small {
  width: 14px;
  height: 14px;
  border: 2px solid var(--vera-accent-15);
  border-top-color: $vera-cyan;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

// ============================================
// Status Bar (z-index: 10)
// ============================================

.status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 6px 14px;
  background: color-mix(in srgb, var(--vera-panel) 60%, transparent);
  border-top: 1px solid var(--vera-accent-08);
  font-size: 0.6875rem;
  color: var(--vera-text-muted);
  position: relative;
  z-index: 10;
}

.status-item {
  white-space: nowrap;
  padding: 2px 8px;
  background: var(--vera-accent-05);
  border-radius: 10px;
  border: 1px solid transparent;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--vera-accent-15);
  }
}

.vera-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  color: $vera-cyan;
  font-weight: 600;
  padding: 3px 10px;
  background: var(--vera-accent-10);
  border: 1px solid var(--vera-accent-25);
  border-radius: 20px;
  animation: veraActive 2s ease-in-out infinite;
}

.vera-dot {
  width: 6px;
  height: 6px;
  background: $vera-cyan;
  border-radius: 50%;
  box-shadow: 0 0 8px $vera-cyan;
  animation: dotPulse 1.5s ease-in-out infinite;
}

.sync-status {
  margin-left: auto;
  color: var(--vera-text-muted);
  opacity: 0.7;
}

// ============================================
// Keyframe Animations
// ============================================

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes codeRain {
  0% {
    top: -40px;
    opacity: 0;
  }
  10% { opacity: 0.5; }
  90% { opacity: 0.5; }
  100% {
    top: 100%;
    opacity: 0;
  }
}

@keyframes glowShift {
  0%, 100% {
    opacity: 0.6;
    transform: scale(1);
  }
  50% {
    opacity: 0.9;
    transform: scale(1.03);
  }
}

@keyframes headerGlow {
  0%, 100% { width: 80px; opacity: 0.6; }
  50% { width: 140px; opacity: 1; }
}

@keyframes artifactGlow {
  0%, 100% { box-shadow: 0 0 8px var(--vera-success-15); }
  50% { box-shadow: 0 0 16px var(--vera-success-20); }
}

@keyframes dotPulse {
  0%, 100% {
    transform: scale(1);
    box-shadow: 0 0 6px $vera-cyan;
  }
  50% {
    transform: scale(1.2);
    box-shadow: 0 0 12px $vera-cyan;
  }
}

@keyframes veraActive {
  0%, 100% {
    box-shadow: 0 0 8px var(--vera-accent-20);
  }
  50% {
    box-shadow: 0 0 16px rgba(var(--vera-accent-rgb), 0.35);
  }
}

// ============================================
// Reduced Motion
// ============================================

@media (prefers-reduced-motion: reduce) {
  .bg-layer,
  .code-particle,
  .vera-dot,
  .vera-indicator,
  .labeled-btn,
  .editor-header::after {
    animation: none !important;
  }
}
</style>
