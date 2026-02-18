<script setup>
import { onMounted, ref, nextTick, computed, watch } from 'vue';
import { Plus, Eraser, Download, Upload, MessageSquareX, Settings, Pencil, Database, Trash, MoreHorizontal, Github, MessageSquare, X, ChevronRight, GitFork, Bot } from 'lucide-vue-next';
import ToolTip from '../controls/ToolTip.vue';
import ConfirmationDialog from '../controls/ConfirmationDialog.vue';
import {
  conversations,
  selectedConversation,
  showConversationOptions,
  messages,
  lastLoadedConversationId,
  storedConversations,
  isSidebarOpen,
  isSmallScreen,
  showStoredFiles,
  selectedModel,
  conversationLoadTimestamp,
} from '@/libs/state-management/state';
import { deleteCurrentConversation, editConversationTitle, saveMessagesHandler } from '@/libs/conversation-management/useConversations';
import { showToast } from '@/libs/utils/general-utils';
import { clearPendingConfirmation, syncPendingConfirmations } from '@/libs/api-access/vera-confirmations';
import { selectConversation, generateConversationSummary, forkConversation } from '@/libs/conversation-management/conversations-management';

const props = defineProps({
  collapsed: {
    type: Boolean,
    default: false,
  },
});

// State
const loadedConversation = ref({});
let initialConversation = '';
const isCollapsed = ref(false);
const isPoweringDown = ref(false); // Nixie tube power-down animation state
const showPurgeConfirmation = ref(false);
const forkingConversationId = ref(null); // Track which conversation is being forked

// Emits
const emit = defineEmits(['import-conversations', 'export-conversations', 'fork-conversation', 'toggle-model-config', 'collapse-change']);

// Helper Functions
// Cache for conversation character counts to avoid recalculating
const conversationTokenCache = new Map();

function conversationCharacterCount(conversation) {
  // Return cached result if available and conversation hasn't changed
  const cacheKey = `${conversation.id}-${conversation.messageHistory.length}`;
  if (conversationTokenCache.has(cacheKey)) {
    return conversationTokenCache.get(cacheKey);
  }

  let totalTextLength = 0;

  // Optimize the loop by using a direct for loop instead of for...of
  const history = conversation.messageHistory;
  for (let i = 0; i < history.length; i++) {
    const message = history[i];
    if (Array.isArray(message.content)) {
      const content = message.content;
      for (let j = 0; j < content.length; j++) {
        const contentItem = content[j];
        if (contentItem.type === 'text' && contentItem.text) {
          totalTextLength += contentItem.text.length;
        }
      }
    } else if (message.content) {
      totalTextLength += String(message.content).length;
    }
  }

  const tokenCount = Math.ceil(totalTextLength / 4);

  // Cache the result
  conversationTokenCache.set(cacheKey, tokenCount);

  // Prevent unlimited cache growth by cleaning old entries when cache gets too large
  if (conversationTokenCache.size > 100) {
    const oldestKey = conversationTokenCache.keys().next().value;
    conversationTokenCache.delete(oldestKey);
  }

  return tokenCount;
}

// Format lastAccessed date for display
function formatLastAccessed(isoDate) {
  if (!isoDate) return '';

  const date = new Date(isoDate);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  // Less than 1 minute ago
  if (diffMins < 1) return 'Just now';

  // Less than 1 hour ago
  if (diffMins < 60) return `${diffMins}m ago`;

  // Less than 24 hours ago
  if (diffHours < 24) return `${diffHours}h ago`;

  // Less than 7 days ago
  if (diffDays < 7) return `${diffDays}d ago`;

  // Otherwise show date
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Sorted conversations - most recently accessed first
const sortedConversations = computed(() => {
  return [...conversations.value].sort((a, b) => {
    const dateA = a.lastAccessed ? new Date(a.lastAccessed) : new Date(0);
    const dateB = b.lastAccessed ? new Date(b.lastAccessed) : new Date(0);
    return dateB - dateA; // Descending order (newest first)
  });
});

// Lifecycle Hooks
onMounted(function () {
  // Parent is the source of truth for collapsed/expanded width state.
  isCollapsed.value = Boolean(props.collapsed);

  // Migrate existing conversations to have lastAccessed field
  let needsMigration = false;
  const migratedConversations = conversations.value.map((conv, index) => {
    if (!conv.lastAccessed) {
      needsMigration = true;
      // Assign lastAccessed based on position (older conversations get earlier dates)
      // This preserves relative order for existing conversations
      const daysAgo = (conversations.value.length - index) * 0.001; // Small offset to maintain order
      return {
        ...conv,
        lastAccessed: new Date(Date.now() - daysAgo * 86400000).toISOString(),
      };
    }
    return conv;
  });

  if (needsMigration) {
    conversations.value = migratedConversations;
    localStorage.setItem('gpt-conversations', JSON.stringify(migratedConversations));
  }

  const lastConversationId = parseInt(localStorage.getItem('lastConversationId')) || 0;
  const lastConversation = conversations.value.find(function (conversation) {
    return conversation.id === lastConversationId;
  });

  // Only set loadedConversation if the conversation exists
  if (lastConversation) {
    loadedConversation.value = lastConversation;
  } else {
    // Fallback if no matching conversation is found
    loadedConversation.value = {
      title: '',
      messageHistory: [],
      id: 0,
    };
  }
});

watch(
  () => props.collapsed,
  (collapsed) => {
    if (isCollapsed.value === Boolean(collapsed)) return;
    isCollapsed.value = Boolean(collapsed);
    if (!isCollapsed.value) {
      isPoweringDown.value = false;
    }
  },
  { immediate: true }
);

// Event Handlers
function toggleCollapse() {
  if (isPoweringDown.value) {
    return;
  }
  // If currently expanded, trigger power-down animation before collapsing
  if (!isCollapsed.value) {
    isPoweringDown.value = true;
    // Wait for power-down animation (400ms) then collapse
    setTimeout(() => {
      isCollapsed.value = true;
      isPoweringDown.value = false;
      localStorage.setItem('conversationsDialogCollapsed', 'true');
      emit('collapse-change', true);
      nextTick(() => {
        const event = new CustomEvent('conversations-collapse-toggle', {
          detail: { collapsed: true }
        });
        document.dispatchEvent(event);
      });
    }, 400);
  } else {
    // Expanding - just expand, power-up animation plays automatically
    isCollapsed.value = false;
    localStorage.setItem('conversationsDialogCollapsed', 'false');
    emit('collapse-change', false);
    nextTick(() => {
      const event = new CustomEvent('conversations-collapse-toggle', {
        detail: { collapsed: false }
      });
      document.dispatchEvent(event);
    });
  }
}

function onEditConversationTitle(conversation) {
  if (conversation.isEditing) {
    return;
  }

  conversation.isEditing = !conversation.isEditing;

  if (conversation.isEditing) {
    initialConversation = conversation;

    nextTick(function () {
      const messageContent = document.getElementById(`conversation-${conversations.value.indexOf(conversation)}`);
      if (messageContent) {
        messageContent.focus();
      }
    });
  }
}

function saveEditedConversationTitle(conversation, event) {
  conversation.isEditing = false;
  const updatedContent = event.target.innerText.trim();

  if (updatedContent !== initialConversation.title.trim()) {
    editConversationTitle(initialConversation, updatedContent);
  }
}

async function loadSelectedConversation(conversation) {
  const result = selectConversation(conversations.value, conversation.id, messages.value, lastLoadedConversationId.value, showToast);

  // Update conversations state with the updated lastAccessed timestamps
  if (result.conversations) {
    conversations.value = result.conversations;
  }

  loadedConversation.value = result.selectedConversation || conversation;
  selectedConversation.value = result.selectedConversation || conversation;
  messages.value = result.selectedConversation?.messageHistory || conversation.messageHistory;

  showConversationOptions.value = false;

  // Update the timestamp to trigger scrolling to bottom in MessagesList
  conversationLoadTimestamp.value = Date.now();
}

async function startNewConversation() {
  selectedConversation.value = null;
  messages.value = [];

  showConversationOptions.value = false;
  
  // Also trigger scrolling when starting a new conversation
  conversationLoadTimestamp.value = Date.now();

  showToast('Conversation Saved');
}

function importConversations() {
  emit('import-conversations');
}

function exportConversations() {
  emit('export-conversations');
}

function purgeConversations() {
  showPurgeConfirmation.value = true;
}

function confirmPurge() {
  localStorage.removeItem('conversations');
  storedConversations.value = [];
  conversations.value = [];
  messages.value = [];
  selectedConversation.value = null;
  lastLoadedConversationId.value = 0;
  syncPendingConfirmations([]);
  // Set a reasonable delay to allow the animation to complete
  setTimeout(() => {
    saveMessagesHandler();
  }, 300);

  showToast('All Conversations Purged');
}

function deleteConversation(conversationId) {
  const conversationIndex = conversations.value.findIndex(
    (conversation) => conversation.id === conversationId
  );

  if (conversationIndex !== -1) {
    const conversation = conversations.value[conversationIndex];
    conversation.deleting = true;

    // Delay actual deletion to allow for animation
    setTimeout(() => {
      conversations.value.splice(conversationIndex, 1);
      clearPendingConfirmation(conversationId);
      syncPendingConfirmations(conversations.value.map((convo) => convo.id));
      if (selectedConversation.value && selectedConversation.value.id === conversationId) {
        // Set selected conversation to the next one if available
        if (conversations.value.length > 0) {
          const nextIndex = Math.min(conversationIndex, conversations.value.length - 1);
          selectedConversation.value = conversations.value[nextIndex];
          messages.value = selectedConversation.value.messageHistory;
        } else {
          selectedConversation.value = null;
          messages.value = [];
        }

        if (conversations.value.length === 0) {
          messages.value = [];
          saveMessagesHandler();
          showToast('Conversation Deleted');
          return;
        }

        saveMessagesHandler();
        loadSelectedConversation(selectedConversation.value);
        showToast('Conversation Deleted');
      }
    }, 200); // Duration of the scaleDown animation
  }
}

// Fork a conversation
async function handleForkConversation(conversation) {
  if (forkingConversationId.value) {
    showToast('Already forking a conversation...');
    return;
  }

  forkingConversationId.value = conversation.id;
  showToast('Generating conversation summary...');

  try {
    // Generate summary
    const summary = await generateConversationSummary(conversation);

    if (!summary) {
      showToast('Failed to generate summary');
      forkingConversationId.value = null;
      return;
    }

    // Create the forked conversation - returns { conversation, continuationPrompt }
    const { conversation: forkedConv, continuationPrompt } = forkConversation(conversations.value, conversation, summary);

    // Add to conversations list
    conversations.value = [...conversations.value, forkedConv];
    localStorage.setItem('gpt-conversations', JSON.stringify(conversations.value));
    clearPendingConfirmation(forkedConv.id);
    syncPendingConfirmations(conversations.value.map((convo) => convo.id));

    // Select and load the new conversation (empty at first)
    selectedConversation.value = forkedConv;
    messages.value = forkedConv.messageHistory;
    lastLoadedConversationId.value = forkedConv.id;
    localStorage.setItem('lastConversationId', forkedConv.id);

    // Emit to trigger auto-send to agent with the continuation prompt
    emit('fork-conversation', { conversation: forkedConv, prompt: continuationPrompt });

    showToast(`Forked: ${forkedConv.title}`);
    showConversationOptions.value = false;
  } catch (error) {
    console.error('Failed to fork conversation:', error);
    showToast('Failed to fork conversation');
  } finally {
    forkingConversationId.value = null;
  }
}


// No longer needed as we've moved the menu options to direct buttons
// const contextMenuVisible = ref(false);
// function toggleContextMenu() {
//   if (contextMenuVisible.value) {
//     contextMenuVisible.value = false;
//     setTimeout(() => {
//       showContextMenu.value = false;
//     }, 200); // Duration of the closing animation
//   } else {
//     showContextMenu.value = true;
//     nextTick(() => {
//       contextMenuVisible.value = true;
//     });
//   }
// }

const modelTypes = [
  { name: 'claude', display: 'MinimalClaude' },
  { name: 'gpt', display: 'MinimalGPT' },
  { name: 'open-ai-format', display: 'VERA' },
  { name: 'web-llm', display: 'MinimalLocal' },
  { name: 'general', display: 'No Model Selected' },
];

const visibleModelLinks = computed(() => {
  return modelTypes.filter((modelType) => selectedModel.value.includes(modelType.name));
});

function toggleConversations() {
  showConversationOptions.value = !showConversationOptions.value;
}

// No longer needed, using native tooltips

</script>

<template>
  <div class="conversations-dialog" :class="{ 'collapsed': isCollapsed && !isSmallScreen }">
    <!-- Purge Confirmation Dialog -->
    <ConfirmationDialog
      v-model:visible="showPurgeConfirmation"
      title="Purge Conversations"
      message="Are you sure you want to delete all conversations? This action cannot be undone."
      confirmLabel="Delete All"
      cancelLabel="Cancel"
      :isWarning="true"
      @confirm="confirmPurge"
    />
    <!-- Header Bar -->
    <div class="dialog-header">
      <div class="header-left">
        <h2>
          <!-- Collapsed: single ">" Nixie icon button as expand trigger -->
          <button v-if="isCollapsed && !isSmallScreen"
                class="nixie-icon-btn nixie-expand-btn"
                @click="toggleCollapse"
                title="Expand">
            <ChevronRight :size="16" />
          </button>
          <!-- Expanded: Nixie tube display showing "CLOSE <" -->
          <span v-else-if="!isSmallScreen"
                class="nixie-display nixie-collapse-trigger"
                :class="{ 'powering-down': isPoweringDown }"
                @click="toggleCollapse"
                title="Collapse">
            <span class="nixie-glow"></span>
            <span class="nixie-tube" v-for="(char, index) in 'CLOSE <'" :key="index"
              :style="{ animationDelay: `${index * 60}ms` }">
              <span class="nixie-char">{{ char === ' ' ? '\u00A0' : char }}</span>
              <span class="nixie-filament"></span>
            </span>
          </span>
          <!-- Mobile: simple text -->
          <span v-else>Conversations</span>
        </h2>
      </div>
      
      <div class="header-actions">
        <!-- Desktop actions - Nixie styled icon buttons -->
        <div v-if="!isSmallScreen" class="desktop-actions">
          <button class="nixie-icon-btn" @click.stop="showStoredFiles = !showStoredFiles" id="stored-Files" title="Stored Files">
            <Database :size="16" />
          </button>
          <ToolTip :targetId="'stored-Files'">View Stored Files</ToolTip>

          <button class="nixie-icon-btn" @click="purgeConversations" id="purge-conversations" title="Purge Conversations">
            <Eraser :size="16" />
          </button>
          <ToolTip :targetId="'purge-conversations'">Purge Conversations</ToolTip>

          <button class="nixie-icon-btn" @click="$emit('toggle-model-config')" id="model-config" title="Model Configuration">
            <Bot :size="16" />
          </button>
          <ToolTip :targetId="'model-config'">Model Configuration</ToolTip>

          <button class="nixie-icon-btn" @click="() => isSidebarOpen = true" title="Settings">
            <Settings :size="16" />
          </button>
        </div>
        
        <!-- Mobile actions - simplified with direct buttons -->
        <div v-if="isSmallScreen" class="mobile-quick-actions">
          <button class="action-btn" @click="purgeConversations" title="Purge Conversations">
            <Eraser :size="20" />
          </button>
          
          <button class="action-btn" @click="() => isSidebarOpen = true" title="Settings">
            <Settings :size="20" />
          </button>
        </div>
      </div>
    </div>
    
    <!-- Conversations List -->
    <div class="conversations-container">
      <div class="conversations-list">
        <ul>
          <!-- Conversation Items -->
          <li v-for="(conversation, index) in sortedConversations"
              :key="conversation.id"
              :id="'conversation-' + index"
              :contenteditable="conversation.isEditing"
              @click="loadSelectedConversation(conversation)"
              @dblclick="onEditConversationTitle(conversation)"
              @blur="saveEditedConversationTitle(conversation, $event)"
              :class="{
                selected: selectedConversation && selectedConversation.id === conversation.id,
                deleting: conversation.deleting,
                editing: conversation.isEditing
              }">

            <!-- Conversation Content -->
            <div class="conversation-content" :title="isCollapsed && !isSmallScreen ? conversation.title : ''">
              <div class="conversation-title">
                <!-- Collapsed: Nixie tube styled icon -->
                <span v-if="isCollapsed && !isSmallScreen" class="nixie-icon-container">
                  <MessageSquare :size="14" />
                </span>
                <!-- Expanded: regular icon -->
                <MessageSquare v-else :size="16" class="conversation-icon" />
                <span v-if="!isCollapsed || isSmallScreen">{{ conversation.title }}</span>
              </div>

              <div class="conversation-actions" v-if="!isCollapsed || isSmallScreen">
                <div class="conversation-meta">
                  <span class="last-accessed" v-if="conversation.lastAccessed">
                    {{ formatLastAccessed(conversation.lastAccessed) }}
                  </span>
                  <span class="token-count">
                    {{ conversationCharacterCount(conversation) }} Tokens
                  </span>
                </div>

                <div class="action-icons">
                  <button class="icon-btn fork-btn" @click.stop="handleForkConversation(conversation)"
                    :disabled="forkingConversationId === conversation.id"
                    :title="forkingConversationId === conversation.id ? 'Forking...' : 'Fork Conversation'">
                    <GitFork :size="14" :class="{ 'spinning': forkingConversationId === conversation.id }" />
                  </button>
                  <button class="icon-btn edit-btn" @click.stop="onEditConversationTitle(conversation)"
                     title="Edit Title">
                    <Pencil :size="14" />
                  </button>
                  <button class="icon-btn delete-btn" @click.stop="deleteConversation(conversation.id)"
                    title="Delete Conversation">
                    <Trash :size="14" />
                  </button>
                </div>
              </div>
            </div>
          </li>
          
          <!-- New Conversation Button -->
          <li class="new-conversation-btn" @click="startNewConversation" title="New Conversation">
            <!-- Collapsed: Nixie tube styled icon -->
            <span v-if="isCollapsed && !isSmallScreen" class="nixie-icon-container nixie-new-btn">
              <Plus :size="14" />
            </span>
            <!-- Expanded: regular icon -->
            <Plus v-else :size="16" class="plus-icon" />
            <span v-if="!isCollapsed || isSmallScreen">New Conversation</span>
          </li>
        </ul>
      </div>
    </div>
    
    <!-- Mobile Bottom Panel -->
    <div v-if="isSmallScreen" class="mobile-bottom-panel">
      <button v-show="isSmallScreen" class="bottom-action-btn delete-conversation-btn" 
        @click="deleteCurrentConversation">
        <MessageSquareX :size="18" />
        <span>Delete Current</span>
      </button>
      
      <button v-show="showConversationOptions && isSmallScreen" 
        class="bottom-action-btn close-btn" @click="toggleConversations">
        <X :size="18" />
        <span>Close</span>
      </button>
    </div>
  </div>
</template>

<style lang="scss" scoped>
// Variables
$primary-color: var(--vera-accent);
$primary-light: var(--vera-accent-strong);
$primary-dark: var(--vera-accent-strong);
$bg-dark: var(--vera-surface);
$bg-darker: var(--vera-panel-muted);
$bg-lighter: var(--vera-panel);
$text-color: var(--vera-text);
$text-muted: var(--vera-text-muted);
$header-bg: var(--vera-header-bg);
$border-color: var(--vera-accent-soft);
$danger-color: var(--vera-danger);
$warning-color: var(--vera-warning);
$success-color: var(--vera-success);
$border-radius: 8px;
$transition-speed: 0.2s;

// Animations
@keyframes pulse {
  0% { box-shadow: 0 2px 8px var(--vera-accent-faint); }
  100% { box-shadow: 0 2px 16px var(--vera-accent-soft); }
}

@keyframes scaleDown {
  0% { transform: scale(1); opacity: 1; }
  100% { transform: scale(0); opacity: 0; }
}

@keyframes gentle-pulse {
  0% { box-shadow: 0 4px 12px var(--vera-accent-faint); }
  100% { box-shadow: 0 4px 15px var(--vera-accent-soft); }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

// Nixie tube animations
@keyframes nixie-power-up {
  0% {
    opacity: 0;
    transform: scale(0.6);
  }
  30% {
    opacity: 0.3;
    transform: scale(0.9);
  }
  60% {
    opacity: 0.8;
    transform: scale(1.05);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes nixie-power-down {
  0% {
    opacity: 1;
    transform: scale(1);
  }
  40% {
    opacity: 0.6;
    transform: scale(1.02);
  }
  100% {
    opacity: 0;
    transform: scale(0.7);
  }
}

@keyframes nixie-char-flicker {
  0%, 100% {
    opacity: 1;
    text-shadow:
      0 0 5px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1))),
      0 0 10px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1))),
      0 0 20px rgba(var(--vera-nixie-digit-rgb), 1),
      0 0 30px rgba(var(--vera-nixie-glow-rgb), calc(0.6 * var(--vera-nixie-intensity, 1)));
  }
  50% {
    opacity: 0.95;
    text-shadow:
      0 0 6px rgba(var(--vera-nixie-glow-rgb), calc(0.85 * var(--vera-nixie-intensity, 1))),
      0 0 12px rgba(var(--vera-nixie-glow-rgb), calc(0.85 * var(--vera-nixie-intensity, 1))),
      0 0 22px rgba(var(--vera-nixie-digit-rgb), 1),
      0 0 32px rgba(var(--vera-nixie-glow-rgb), calc(0.65 * var(--vera-nixie-intensity, 1)));
  }
  92% {
    opacity: 0.88;
    text-shadow:
      0 0 4px rgba(var(--vera-nixie-glow-rgb), calc(0.7 * var(--vera-nixie-intensity, 1))),
      0 0 8px rgba(var(--vera-nixie-glow-rgb), calc(0.7 * var(--vera-nixie-intensity, 1))),
      0 0 18px rgba(var(--vera-nixie-digit-rgb), 0.9),
      0 0 28px rgba(var(--vera-nixie-glow-rgb), calc(0.5 * var(--vera-nixie-intensity, 1)));
  }
}

@keyframes nixie-char-fadeout {
  0% {
    opacity: 1;
    text-shadow:
      0 0 5px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1))),
      0 0 10px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1))),
      0 0 20px rgba(var(--vera-nixie-digit-rgb), 1);
  }
  50% {
    opacity: 0.4;
    text-shadow:
      0 0 3px rgba(var(--vera-nixie-glow-rgb), calc(0.5 * var(--vera-nixie-intensity, 1))),
      0 0 6px rgba(var(--vera-nixie-digit-rgb), 0.8);
  }
  100% {
    opacity: 0;
    text-shadow: none;
  }
}

@keyframes nixie-ambient-glow {
  0% {
    opacity: 0.8;
  }
  100% {
    opacity: 1;
  }
}

@keyframes nixie-glow-fadeout {
  0% {
    opacity: 1;
  }
  100% {
    opacity: 0;
  }
}

// Main container
.conversations-dialog {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background-color: transparent;
  position: relative;
  margin: 0;
  padding: 0;
  font-family: var(--vera-font-sidebar);
  color: var(--vera-text-sidebar);
  transition: width 0.3s ease, min-width 0.3s ease, max-width 0.3s ease;
  
  @media (max-width: 600px) {
    height: 100vh;
    max-height: 100vh;
  }
  
  &.collapsed {
    width: 60px !important;
    min-width: 60px !important;
    max-width: 60px !important;
    resize: none !important;
    
    // In collapsed mode, we'll use a vertical layout with just icons
    display: flex;
    flex-direction: column;
    
    .dialog-header {
      padding: 14px 5px;
      flex-direction: column;
      justify-content: flex-start;
      align-items: center;
      height: auto;
      
      .header-left {
        display: flex;
        justify-content: center;
        width: 100%;
        margin-bottom: 15px;
        
        h2 {
          justify-content: center;
          margin: 0 auto;
        }
      }
      
      .header-actions {
        position: static; // Not absolute anymore
        flex-direction: column;
        align-items: center;
        background-color: transparent;
        border-bottom: none;
        margin-top: 0;
        width: 100%;
        
        .desktop-actions {
          flex-direction: column;
          gap: 15px;
          width: 100%;
          padding: 5px 0;
          
          .action-btn, .github-link {
            margin: 5px auto;
            padding: 6px;
            background: var(--vera-sidebar-btn-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--vera-btn-border);
            border-radius: 8px;

            &:hover {
              background: var(--vera-btn-bg-hover);
              border-color: var(--vera-accent-soft);
            }
          }
        }
        
        .mobile-quick-actions {
          display: none;
        }
      }
    }
    
    .conversations-container {
      margin-top: 10px;
      padding-top: 0;
    }
    
    .conversations-list {
      ul {
        padding-top: 5px;
      }

      li {
        position: relative;
        background: transparent !important;
        border: none !important;
        border-left: none !important;
        box-shadow: none !important;

        &:hover {
          z-index: 25;
          transform: none !important;
          background: transparent !important;
        }

        &.selected {
          background: transparent !important;
          border: none !important;

          .nixie-icon-container {
            box-shadow:
              inset 0 1px 3px var(--vera-black-50),
              0 0 15px var(--vera-nixie-color-soft),
              0 0 30px var(--vera-nixie-color-faint);
            border-color: var(--vera-nixie-color-soft);

            svg {
              filter: drop-shadow(0 0 4px rgba(var(--vera-nixie-glow-rgb), calc(0.9 * var(--vera-nixie-intensity, 1))))
                      drop-shadow(0 0 8px rgba(var(--vera-nixie-glow-rgb), calc(0.7 * var(--vera-nixie-intensity, 1))))
                      drop-shadow(0 0 14px rgba(var(--vera-nixie-glow-rgb), calc(0.5 * var(--vera-nixie-intensity, 1))));
            }
          }
        }

        .conversation-content {
          padding: 8px 5px;
          justify-content: center;
          text-align: center;
          display: flex;

          .conversation-title {
            justify-content: center;
            position: relative;
          }
        }

        &.new-conversation-btn {
          padding: 8px 5px;
          justify-content: center;
          display: flex;
          background: transparent !important;
          border: none !important;
        }
      }
    }
  }
}

// Header section

.dialog-header {

  background-color: $header-bg;

  backdrop-filter: blur(var(--vera-header-blur));

  display: flex;

  justify-content: space-between;

  align-items: center;

  padding: 14px 10px; /* Slightly reduced horizontal padding */

  border-bottom: 1px solid $border-color;

  position: sticky;

  top: 0;

  z-index: 10;

  box-shadow: 0 2px 10px var(--vera-black-15);

  transition: padding 0.3s ease, height 0.3s ease;

  gap: 4px; /* Reduced from 8px to give Nixie more room */



  .header-left {

    flex: 1 1 auto; /* Allow it to grow */

    min-width: 0;

    display: flex;

    align-items: center;



    h2 {

      margin: 0;

      font-size: 1rem;

      font-weight: 600;

      color: $text-color;

      display: flex;

      align-items: center;

      white-space: nowrap;

      /* Removed overflow: hidden to prevent clipping the Nixie glow */



      .icon-only {

        display: inline-flex;

        justify-content: center;

        align-items: center;

        color: $primary-color;

      }

      // Nixie expand button (collapsed state)
      .nixie-icon-btn.nixie-expand-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        padding: 0;
        background: linear-gradient(180deg,
          color-mix(in srgb, var(--vera-nixie-button-bg) 90%, transparent) 0%,
          color-mix(in srgb, var(--vera-nixie-button-bg) 95%, transparent) 50%,
          color-mix(in srgb, var(--vera-nixie-button-bg) 90%, transparent) 100%);
        border-radius: 6px;
        border: 1px solid var(--vera-nixie-color-soft);
        box-shadow:
          inset 0 1px 3px var(--vera-black-50),
          0 0 10px var(--vera-nixie-color-faint);
        cursor: pointer;
        transition: all 0.15s ease;

        svg {
          color: var(--vera-nixie-color);
          filter: drop-shadow(0 0 3px rgba(var(--vera-nixie-glow-rgb), calc(0.6 * var(--vera-nixie-intensity, 1))))
                  drop-shadow(0 0 6px rgba(var(--vera-nixie-glow-rgb), calc(0.4 * var(--vera-nixie-intensity, 1))));
          transition: filter 0.15s ease;
        }

        &:hover {
          transform: scale(1.05);
          box-shadow:
            inset 0 1px 3px var(--vera-black-50),
            0 0 15px var(--vera-nixie-color-soft),
            0 0 30px var(--vera-nixie-color-faint);

          svg {
            filter: drop-shadow(0 0 4px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1))))
                    drop-shadow(0 0 8px rgba(var(--vera-nixie-glow-rgb), calc(0.6 * var(--vera-nixie-intensity, 1))))
                    drop-shadow(0 0 12px rgba(var(--vera-nixie-glow-rgb), calc(0.4 * var(--vera-nixie-intensity, 1))));
          }
        }

        &:active {
          transform: scale(0.95);
        }
      }

            // Nixie Tube Display

            .nixie-display {

              display: inline-flex;

              align-items: center;

              gap: 1px;

              position: relative;

              padding: 3px 12px 3px 6px; /* Increased right padding to 12px */

              background: linear-gradient(180deg,
                color-mix(in srgb, var(--vera-nixie-button-bg) 90%, transparent) 0%,
                color-mix(in srgb, var(--vera-nixie-button-bg) 95%, transparent) 50%,
                color-mix(in srgb, var(--vera-nixie-button-bg) 90%, transparent) 100%);
        border-radius: 6px;
        border: 1px solid var(--vera-nixie-color-soft);
        box-shadow:
          inset 0 1px 3px var(--vera-black-50),
          0 0 20px var(--vera-nixie-color-faint),
          0 0 40px var(--vera-nixie-color-faint);

        // Ambient glow behind the display
        .nixie-glow {
          position: absolute;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          width: 120%;
          height: 200%;
          background: radial-gradient(ellipse, var(--vera-nixie-color-faint) 0%, transparent 70%);
          pointer-events: none;
          z-index: -1;
          animation: nixie-ambient-glow calc(2s / var(--vera-nixie-speed, 1)) ease-in-out infinite alternate;
        }

        // Individual tube container
        .nixie-tube {
          position: relative;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 13px; /* Adjusted from 15px */
          height: 22px; /* Adjusted from 26px */
          background: linear-gradient(180deg,
            color-mix(in srgb, var(--vera-nixie-button-bg) 80%, transparent) 0%,
            color-mix(in srgb, var(--vera-nixie-button-bg) 90%, transparent) 100%);
          border-radius: 4px;
          border: 1px solid var(--vera-nixie-color-faint);
          animation: nixie-power-up calc(0.4s / var(--vera-nixie-speed, 1)) ease-out forwards;
          opacity: 0;
          transform: scale(0.8);
          margin: 0 1px;

          // The glowing character
          .nixie-char {
            font-family: 'Courier New', monospace;
            font-size: 0.875rem; /* Adjusted from 18px */
            font-weight: 700;
            line-height: 1;
            color: var(--vera-nixie-color);
            text-shadow:
              0 0 5px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1))),
              0 0 10px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1))),
              0 0 20px rgba(var(--vera-nixie-digit-rgb), 1),
              0 0 30px rgba(var(--vera-nixie-glow-rgb), calc(0.6 * var(--vera-nixie-intensity, 1)));
            animation: nixie-char-flicker calc(3s / var(--vera-nixie-speed, 1)) ease-in-out infinite;
          }

          // Decorative filament wire
          .nixie-filament {
            position: absolute;
            bottom: 2px;
            left: 50%;
            transform: translateX(-50%);
            width: 6px;
            height: 1px;
            background: linear-gradient(90deg,
              transparent 0%,
              var(--vera-nixie-color-soft) 50%,
              transparent 100%);
            border-radius: 1px;
          }
        }

        // Power-down animation state
        &.powering-down {
          .nixie-tube {
            animation: nixie-power-down calc(0.35s / var(--vera-nixie-speed, 1)) ease-in forwards;

            .nixie-char {
              animation: nixie-char-fadeout calc(0.35s / var(--vera-nixie-speed, 1)) ease-in forwards;
            }
          }

          .nixie-glow {
            animation: nixie-glow-fadeout calc(0.4s / var(--vera-nixie-speed, 1)) ease-in forwards;
          }
        }

        // Clickable Nixie tube triggers
        &.nixie-collapse-trigger,
        &.nixie-expand-trigger {
          cursor: pointer;
          transition: transform 0.15s ease, box-shadow 0.15s ease;

          &:hover {
            transform: scale(1.05);
            box-shadow:
              inset 0 1px 3px var(--vera-black-50),
              0 0 25px var(--vera-nixie-color-soft),
              0 0 50px var(--vera-nixie-color-faint);

            .nixie-char {
              text-shadow:
                0 0 6px rgba(var(--vera-nixie-glow-rgb), calc(1.0 * var(--vera-nixie-intensity, 1))),
                0 0 14px rgba(var(--vera-nixie-glow-rgb), calc(1.0 * var(--vera-nixie-intensity, 1))),
                0 0 26px rgba(var(--vera-nixie-digit-rgb), 1),
                0 0 38px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1)));
            }
          }

          &:active {
            transform: scale(0.98);
          }
        }

        // Single character expand trigger
        &.nixie-expand-trigger {
          padding: 3px 6px;
        }
      }

      @media (max-width: 600px) {
        font-size: 1.0625rem;
      }
    }
  }
  
  .header-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    position: relative;
    flex-shrink: 0;

    .desktop-actions {
      display: flex;
      align-items: center;
      gap: 4px; /* Reduced from 6px */
      transition: flex-direction 0.3s ease, gap 0.3s ease;
    }
    
    .github-link {
      display: flex;
      align-items: center;
      justify-content: center;
      color: $text-muted;
      text-decoration: none;
      padding: 6px 4px; /* Reduced horizontal padding */
      border-radius: 6px;
      transition: all $transition-speed ease;
      
      &:hover {
        color: $text-color;
        background-color: rgba(var(--vera-accent-rgb), 0.15);
      }
    }
    
    // Nixie-styled icon buttons
    .nixie-icon-btn {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      padding: 0;
      background: linear-gradient(180deg,
        color-mix(in srgb, var(--vera-nixie-button-bg) 90%, transparent) 0%,
        color-mix(in srgb, var(--vera-nixie-button-bg) 95%, transparent) 50%,
        color-mix(in srgb, var(--vera-nixie-button-bg) 90%, transparent) 100%);
      border-radius: 6px;
      border: 1px solid var(--vera-nixie-color-soft);
      box-shadow:
        inset 0 1px 3px var(--vera-black-50),
        0 0 10px var(--vera-nixie-color-faint);
      cursor: pointer;
      transition: all 0.15s ease;

      svg {
        color: var(--vera-nixie-color);
        filter: drop-shadow(0 0 3px rgba(var(--vera-nixie-glow-rgb), calc(0.6 * var(--vera-nixie-intensity, 1))))
                drop-shadow(0 0 6px rgba(var(--vera-nixie-glow-rgb), calc(0.4 * var(--vera-nixie-intensity, 1))));
        transition: filter 0.15s ease;
      }

      &:hover {
        transform: scale(1.05);
        box-shadow:
          inset 0 1px 3px var(--vera-black-50),
          0 0 15px var(--vera-nixie-color-soft),
          0 0 30px var(--vera-nixie-color-faint);

        svg {
          filter: drop-shadow(0 0 4px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1))))
                  drop-shadow(0 0 8px rgba(var(--vera-nixie-glow-rgb), calc(0.6 * var(--vera-nixie-intensity, 1))))
                  drop-shadow(0 0 12px rgba(var(--vera-nixie-glow-rgb), calc(0.4 * var(--vera-nixie-intensity, 1))));
        }
      }

      &:active {
        transform: scale(0.95);
      }
    }

    .action-btn {
      background: var(--vera-action-btn-bg);
      border: 1px solid transparent;
      backdrop-filter: blur(8px);
      color: $text-muted;
      padding: 6px 4px; /* Reduced horizontal padding */
      border-radius: 6px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all $transition-speed ease;

      &:hover {
        background: var(--vera-btn-bg-hover);
        border-color: var(--vera-accent-soft);
        color: $text-color;
      }

      &:active {
        transform: scale(0.95);
      }
    }
    
    // Mobile quick actions
    .mobile-quick-actions {
      display: flex;
      align-items: center;
      gap: 8px;

      .action-btn {
        padding: 5px;
        background: var(--vera-action-btn-bg);
        border: 1px solid transparent;
        backdrop-filter: blur(8px);

        &:hover {
          background: var(--vera-btn-bg-hover);
          border-color: var(--vera-accent-soft);
        }
      }
    }
  }
}

// Removed custom tooltip

// Nixie icon container - used for conversation list items in collapsed mode
.nixie-icon-container {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: linear-gradient(180deg,
    color-mix(in srgb, var(--vera-nixie-button-bg) 90%, transparent) 0%,
    color-mix(in srgb, var(--vera-nixie-button-bg) 95%, transparent) 50%,
    color-mix(in srgb, var(--vera-nixie-button-bg) 90%, transparent) 100%);
  border-radius: 6px;
  border: 1px solid var(--vera-nixie-color-soft);
  box-shadow:
    inset 0 1px 3px var(--vera-black-50),
    0 0 10px var(--vera-nixie-color-faint);
  cursor: pointer;
  transition: all 0.15s ease;

  svg {
    color: var(--vera-nixie-color);
    filter: drop-shadow(0 0 3px rgba(var(--vera-nixie-glow-rgb), calc(0.6 * var(--vera-nixie-intensity, 1))))
            drop-shadow(0 0 6px rgba(var(--vera-nixie-glow-rgb), calc(0.4 * var(--vera-nixie-intensity, 1))));
    transition: filter 0.15s ease;
  }

  &:hover {
    transform: scale(1.05);
    box-shadow:
      inset 0 1px 3px var(--vera-black-50),
      0 0 15px var(--vera-nixie-color-soft),
      0 0 30px var(--vera-nixie-color-faint);

    svg {
      filter: drop-shadow(0 0 4px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1))))
              drop-shadow(0 0 8px rgba(var(--vera-nixie-glow-rgb), calc(0.6 * var(--vera-nixie-intensity, 1))))
              drop-shadow(0 0 12px rgba(var(--vera-nixie-glow-rgb), calc(0.4 * var(--vera-nixie-intensity, 1))));
    }
  }

  &:active {
    transform: scale(0.95);
  }

  // New conversation button - dashed border variant
  &.nixie-new-btn {
    border-style: dashed;

    &:hover {
      border-style: solid;
    }
  }
}

// Conversations list container
.conversations-container {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  scrollbar-width: thin;
  transition: padding-top 0.3s ease;
  
  &::-webkit-scrollbar {
    width: 6px;
    
    @media (max-width: 600px) {
      width: 5px;
    }
  }
  
  &::-webkit-scrollbar-track {
    background: var(--vera-black-15);
    border-radius: 10px;
  }
  
  &::-webkit-scrollbar-thumb {
    background-color: var(--vera-accent-soft);
    border-radius: 10px;
    
    &:hover {
      background-color: var(--vera-accent);
    }
  }
  
  // Conversations list
  .conversations-list {
    ul {
      list-style-type: none;
      padding: 0;
      margin: 0;
      
      // Conversation item (Chat History Card)
      li {
        border-radius: $border-radius;
        cursor: pointer;
        margin-bottom: 8px;
        transition: all $transition-speed ease;
        overflow: hidden;

        &.editing {
          outline: none;
          border: 2px solid var(--vera-accent);
          padding: 16px;
          border-radius: $border-radius;
          text-align: center;
          background: var(--vera-glass-strong);
          backdrop-filter: blur(12px);
        }

        &:not(.new-conversation-btn) {
          background: var(--vera-glass-bg);
          border: 1px solid var(--vera-btn-border);
          border-left: 3px solid transparent;
          backdrop-filter: blur(8px);

          &:hover {
            background: var(--vera-btn-bg-hover);
            border-color: var(--vera-accent-soft);
            transform: translateY(-2px);
            box-shadow: var(--vera-panel-shadow);
          }

          &.selected {
            background: var(--vera-btn-bg-active);
            border-color: var(--vera-accent-soft);
            border-left: 3px solid var(--vera-accent);
            box-shadow: var(--vera-btn-glow);

            &:hover {
              background: var(--vera-accent-soft);
            }
          }

          &.deleting {
            animation: scaleDown calc(#{$transition-speed} / var(--vera-anim-speed, 1)) linear forwards;
          }
        }
        
        // Conversation content
        .conversation-content {
          padding: 14px;
          
          .conversation-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 0.9375rem;
            word-break: break-word;
            
            .conversation-icon {
              color: $primary-color;
              opacity: 0.8;
              flex-shrink: 0;
            }
          }
          
          .conversation-actions {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 8px;

            .conversation-meta {
              display: flex;
              align-items: center;
              gap: 8px;

              .last-accessed {
                font-size: 0.6875rem;
                color: $text-muted;
                opacity: 0.7;
              }

              .token-count {
                font-size: 0.75rem;
                color: $text-muted;
                background-color: var(--vera-panel-muted);
                padding: 2px 8px;
                border-radius: 4px;
              }
            }
            
            .action-icons {
              display: flex;
              gap: 8px;

              .icon-btn {
                background: var(--vera-btn-bg);
                border: 1px solid transparent;
                backdrop-filter: blur(8px);
                color: $text-muted;
                padding: 5px;
                border-radius: 4px;
                cursor: pointer;
                display: flex;
                align-items: center;

                &.fork-btn:hover {
                  color: var(--vera-success);
                }

                &:disabled {
                  opacity: 0.5;
                  cursor: not-allowed;
                }

                .spinning {
                  animation: spin calc(1s / var(--vera-anim-speed, 1)) linear infinite;
                }
                justify-content: center;
                transition: all $transition-speed ease;

                &:hover {
                  background: var(--vera-btn-bg-hover);
                  border-color: var(--vera-accent-soft);

                  &.edit-btn {
                    color: $warning-color;
                    border-color: var(--vera-warning);
                  }

                  &.delete-btn {
                    color: $danger-color;
                    border-color: var(--vera-danger);
                  }
                }
              }
            }
          }
        }

        // New conversation button
        &.new-conversation-btn {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          background: var(--vera-glass-bg);
          backdrop-filter: blur(12px);
          padding: 14px;
          border: 1px dashed var(--vera-accent-soft);
          margin-top: 12px;
          margin-bottom: 24px;

          .plus-icon {
            color: var(--vera-accent);
          }

          span {
            font-weight: 500;
          }

          &:hover {
            background: var(--vera-btn-bg-active);
            border-style: solid;
            border-color: var(--vera-accent);
            transform: translateY(-2px);
            box-shadow: var(--vera-btn-glow);
          }

          &:active {
            transform: translateY(0);
            box-shadow: 0 2px 8px var(--vera-accent-faint);
          }
        }
      }
    }
  }
}

// Mobile bottom panel
.mobile-bottom-panel {
  display: flex;
  padding: 10px;
  background-color: $bg-darker;
  border-top: 1px solid rgba(var(--vera-accent-rgb), 0.2);
  gap: 10px;
  
  .bottom-action-btn {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    background-color: $bg-lighter;
    border: none;
    color: $text-color;
    padding: 12px;
    border-radius: $border-radius;
    cursor: pointer;
    font-size: 0.875rem;
    transition: all $transition-speed ease;
    
    svg {
      color: $text-muted;
    }
    
    &.delete-conversation-btn {
      background-color: rgba(var(--vera-error-rgb), 0.1);
      border: 1px solid rgba(var(--vera-error-rgb), 0.2);
      
      &:hover {
        background-color: rgba(var(--vera-error-rgb), 0.2);
        border-color: rgba(var(--vera-error-rgb), 0.3);
      }
      
      svg {
        color: rgba(var(--vera-error-rgb), 0.8);
      }
    }
    
    &.close-btn {
      background-color: rgba(var(--vera-accent-rgb), 0.1);
      border: 1px solid rgba(var(--vera-accent-rgb), 0.2);
      
      &:hover {
        background-color: rgba(var(--vera-accent-rgb), 0.2);
        border-color: rgba(var(--vera-accent-rgb), 0.3);
      }
      
      svg {
        color: rgba(var(--vera-accent-rgb), 0.8);
      }
    }
    
    &:hover {
      transform: translateY(-2px);
    }
    
    &:active {
      transform: translateY(0);
    }
  }
}

// Transitions
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity $transition-speed ease, transform $transition-speed ease;
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
