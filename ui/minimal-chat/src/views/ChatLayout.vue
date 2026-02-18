// ChatLayout.vue

<script setup>
import { onMounted, onBeforeUnmount, ref, watch, computed, nextTick, defineAsyncComponent } from 'vue';
import { Activity, Brain, Code2, Network, Radio, Sparkles, Wrench, Power } from 'lucide-vue-next';
import { determineModelDisplayName, handleDoubleClick, removeAPIEndpoints, startResize, resize, stopResize, showToast } from '@/libs/utils/general-utils';
import { syncPendingConfirmations } from '@/libs/api-access/vera-confirmations';
import { handleExportConversations, createArtifact, deleteArtifact, getArtifacts } from '@/libs/conversation-management/conversations-management';
import { stageFileUpload, uploadFile, stageImageUpload } from '@/libs/file-processing/file-processing';
import messageItem from '@/components/controls/MessagesList.vue';
import chatInput from '@/components/layout/ChatInput.vue';
import chatHeader from '@/components/layout/ChatHeader.vue';
import ConfirmationDialog from '@/components/controls/ConfirmationDialog.vue';
const settingsDialog = defineAsyncComponent(() => import('@/components/dialogs/SettingsDialog.vue'));
const conversationsDialog = defineAsyncComponent(() => import('@/components/dialogs/ConversationsDialog.vue'));
const StoredFilesList = defineAsyncComponent(() => import('@/components/dialogs/StoredFilesDialog.vue'));
const CanvasDrawer = defineAsyncComponent(() => import('@/components/drawers/CanvasDrawer.vue'));
const DiagnosticsDrawer = defineAsyncComponent(() => import('@/components/drawers/DiagnosticsDrawer.vue'));
const ImportExportDrawer = defineAsyncComponent(() => import('@/components/drawers/ImportExportDrawer.vue'));
const SelfImproveDrawer = defineAsyncComponent(() => import('@/components/drawers/SelfImproveDrawer.vue'));
const SwarmDrawer = defineAsyncComponent(() => import('@/components/drawers/SwarmDrawer.vue'));
const ToolsDrawer = defineAsyncComponent(() => import('@/components/drawers/ToolsDrawer.vue'));
const ActivityDrawer = defineAsyncComponent(() => import('@/components/drawers/ActivityDrawer.vue'));
const ModelConfigDrawer = defineAsyncComponent(() => import('@/components/drawers/ModelConfigDrawer.vue'));
const InnerLifeDrawer = defineAsyncComponent(() => import('@/components/drawers/InnerLifeDrawer.vue'));
const ArtifactsList = defineAsyncComponent(() => import('@/components/controls/ArtifactsList.vue'));
import {
  userText,
  isLoading,
  selectedModel,
  isSidebarOpen,
  showConversationOptions,
  messages,
  modelDisplayName,
  localModelName,
  localModelEndpoint,
  imageInput,
  lastLoadedConversationId,
  conversations,
  higherContrastMessages,
  showStoredFiles,
  isSmallScreen,
  availableModels,
  uiEffectScanlines,
  uiEffectNoise,
  uiEffectGrid,
  uiEffectAurora,
  uiEffectVignette,
  uiLiteMode,
  a11yScreenReaderAnnounce,
  selectedConversation,
  currentArtifacts
} from '@/libs/state-management/state';
import { setupWatchers } from '@/libs/state-management/watchers';
import { applyTheme } from '@/libs/utils/theme-utils';
import { saveMessagesHandler, selectConversationHandler } from '@/libs/conversation-management/useConversations';
import { addMessage } from '@/libs/conversation-management/message-processing';
import { runTutortialForNewUser } from '@/libs/utils/tutorial-utils';
import "driver.js/dist/driver.css";
import "../assets/tutorial.css";
import { getOpenAICompatibleAvailableModels } from '@/libs/api-access/open-ai-api-standard-access';

const sidebarContentContainer = ref(null);
const drawerContainer = ref(null);
const chatInputRef = ref(null); // Ref to chatInput for programmatic sending
const initialWidth = ref(325);
const initialMouseX = ref(0);
const isCollapsed = ref(false);
const activeDrawer = ref(null);
const canvasCollapsed = ref(false);
const editorPollInterval = ref(null);
const readinessPollInterval = ref(null);
const conversationsStateObserver = ref(null);
const readinessState = ref({
  ready: false,
  phase: 'loading',
  message: 'Stand by please while my tools are loading.'
});
const hasShownReadyToast = ref(false);
const MIN_CHAT_WIDTH = 360;
const MIN_SIDEBAR_WIDTH = 60;
const DEFAULT_SIDEBAR_WIDTH = 325;
const DEFAULT_DRAWER_WIDTH = 360;
const MAX_SIDEBAR_WIDTH = 600;
const MAX_DRAWER_WIDTH = 860;
const CANVAS_DRAWER_MIN = 480;
const CANVAS_DRAWER_MAX = 860;
const CANVAS_DRAWER_RATIO = 0.55;
const CANVAS_COLLAPSED_WIDTH = 72;
const RIGHT_RAIL_WIDTH = 56;
const AUTO_COLLAPSE_WIDTH = 900;
const wasAutoCollapsed = ref(false);
const previousCollapsedState = ref(false);
const ACTIVITY_PING_MIN_MS = 30000;
const lastActivitySent = ref(0);

function sendActivityPing(trigger = 'interaction') {
  const now = Date.now();
  if (now - lastActivitySent.value < ACTIVITY_PING_MIN_MS) {
    return;
  }
  lastActivitySent.value = now;
  const conversationId = localStorage.getItem('lastConversationId') || 'default';
  fetch('/api/session/activity', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      conversation_id: conversationId,
      trigger
    })
  }).catch(() => {});
}

function handleUserActivity() {
  sendActivityPing('interaction');
}

function handleVisibilityChange() {
  if (!document.hidden) {
    sendActivityPing('visibility');
  }
}

// Sync sidebar refs with retry mechanism for transition timing
function syncSidebarRefs(retryCount = 0) {
  const maxRetries = 5;
  const retryDelay = 50; // ms

  let needsLeftSync = !sidebarContentContainer.value || !sidebarContentContainer.value.isConnected;
  let needsRightSync = !drawerContainer.value || !drawerContainer.value.isConnected;

  if (needsLeftSync) {
    sidebarContentContainer.value = document.querySelector('#conversations-dialog');
    needsLeftSync = !sidebarContentContainer.value;
  }
  if (needsRightSync) {
    drawerContainer.value = document.querySelector('#drawer-panel');
    needsRightSync = !drawerContainer.value;
  }

  // If still missing refs and haven't exhausted retries, try again after a delay
  // This handles cases where transitions haven't completed yet
  if ((needsLeftSync || needsRightSync) && retryCount < maxRetries) {
    setTimeout(() => syncSidebarRefs(retryCount + 1), retryDelay);
  }
}

// Called when left sidebar transition completes (element is now in DOM)
function onLeftSidebarEnter(el) {
  sidebarContentContainer.value = el;
  startConversationsStateObserver();
  nextTick(() => {
    syncCollapsedStateFromDom(true);
    applySidebarWidths();
  });
}

// Called when left sidebar is about to be removed
function onLeftSidebarLeave() {
  stopConversationsStateObserver();
  sidebarContentContainer.value = null;
}

function syncLeftModelDrawerWithCollapse() {
  if (!isSmallScreen.value && isCollapsed.value && activeDrawer.value === 'model-config') {
    activeDrawer.value = null;
  }
}

// Called when right drawer transition completes
function onRightSidebarEnter(el) {
  drawerContainer.value = el;
  nextTick(() => {
    applySidebarWidths();
  });
}

// Called when right drawer is about to be removed
function onRightSidebarLeave() {
  drawerContainer.value = null;
  updateChatContainerLayout();
}

watch(isCollapsed, (collapsed) => {
  try {
    localStorage.setItem('conversationsDialogCollapsed', collapsed ? 'true' : 'false');
  } catch (_error) {
    // Ignore storage write issues.
  }
  nextTick(() => {
    syncSidebarRefs();
    applySidebarWidths();
    requestAnimationFrame(() => {
      updateChatContainerLayout();
    });
  });
});

function getLeftSidebarWidth() {
  if (isSmallScreen.value) return 0;
  if (sidebarContentContainer.value && sidebarContentContainer.value.isConnected) {
    return sidebarContentContainer.value.offsetWidth;
  }
  return isCollapsed.value ? MIN_SIDEBAR_WIDTH : DEFAULT_SIDEBAR_WIDTH;
}

const showRightRail = computed(() => !isSmallScreen.value);
const drawerPanelClass = computed(() => ({
  'drawer-canvas': activeDrawer.value === 'canvas',
  'drawer-canvas-collapsed': activeDrawer.value === 'canvas' && canvasCollapsed.value
}));

function getRightRailWidth() {
  if (!showRightRail.value) return 0;
  return RIGHT_RAIL_WIDTH;
}

function getRightSidebarWidth() {
  return getDrawerWidth() + getRightRailWidth();
}

function getDesiredDrawerWidth() {
  // Model config drawer is on the left, not the right
  if (!activeDrawer.value || activeDrawer.value === 'model-config') return 0;
  if (activeDrawer.value === 'canvas') {
    if (canvasCollapsed.value) return CANVAS_COLLAPSED_WIDTH;
    const ideal = Math.round(window.innerWidth * CANVAS_DRAWER_RATIO);
    return Math.max(CANVAS_DRAWER_MIN, Math.min(CANVAS_DRAWER_MAX, ideal));
  }
  return DEFAULT_DRAWER_WIDTH;
}

function getDrawerWidth() {
  // Model config drawer is on the left, not the right, so don't count its width here
  if (isSmallScreen.value || !activeDrawer.value || activeDrawer.value === 'model-config') return 0;
  if (drawerContainer.value && drawerContainer.value.isConnected) {
    return drawerContainer.value.offsetWidth;
  }
  return getDesiredDrawerWidth();
}

function clampSidebarWidth(desiredWidth, otherWidth, maxWidthOverride = MAX_SIDEBAR_WIDTH) {
  if (!desiredWidth) return 0;
  const availableWidth = window.innerWidth - MIN_CHAT_WIDTH - otherWidth;
  const maxWidth = Math.max(MIN_SIDEBAR_WIDTH, Math.min(maxWidthOverride, availableWidth));
  return Math.max(MIN_SIDEBAR_WIDTH, Math.min(desiredWidth, maxWidth));
}

function setLeftSidebarWidth(width) {
  if (!sidebarContentContainer.value || !sidebarContentContainer.value.isConnected) return;
  const value = typeof width === 'number' ? `${width}px` : width;
  sidebarContentContainer.value.style.width = value;
  sidebarContentContainer.value.style.minWidth = value;
  sidebarContentContainer.value.style.maxWidth = value;
  const sidebarConversations = document.querySelector('.sidebar-conversations');
  if (sidebarConversations) {
    sidebarConversations.style.width = value;
    sidebarConversations.style.minWidth = value;
    sidebarConversations.style.maxWidth = value;
  }
}

function setRightSidebarWidth(width, offsetRight = 0) {
  if (!drawerContainer.value || !drawerContainer.value.isConnected) return;
  const value = typeof width === 'number' ? `${width}px` : width;
  drawerContainer.value.style.width = value;
  drawerContainer.value.style.minWidth = value;
  drawerContainer.value.style.maxWidth = value;
  drawerContainer.value.style.right = offsetRight ? `${offsetRight}px` : '0';
}

function applySidebarWidths() {
  syncSidebarRefs();
  if (!isSmallScreen.value && window.innerWidth <= AUTO_COLLAPSE_WIDTH) {
    if (!wasAutoCollapsed.value) {
      previousCollapsedState.value = isCollapsed.value;
      wasAutoCollapsed.value = true;
    }
    isCollapsed.value = true;
  } else if (wasAutoCollapsed.value && window.innerWidth > AUTO_COLLAPSE_WIDTH) {
    isCollapsed.value = previousCollapsedState.value;
    wasAutoCollapsed.value = false;
  }

  syncLeftModelDrawerWithCollapse();

  if (isSmallScreen.value) {
    resetSidebarForMobile();
    if (activeDrawer.value) {
      setRightSidebarWidth('100vw');
    }
    updateChatContainerLayout();
    return;
  }

  const desiredLeft = isCollapsed.value ? MIN_SIDEBAR_WIDTH : DEFAULT_SIDEBAR_WIDTH;
  const railWidth = getRightRailWidth();
  const desiredDrawer = activeDrawer.value ? getDesiredDrawerWidth() : 0;
  let drawerWidth = clampSidebarWidth(desiredDrawer, desiredLeft + railWidth, MAX_DRAWER_WIDTH);
  let leftWidth = clampSidebarWidth(desiredLeft, drawerWidth + railWidth);

  if (desiredDrawer) {
    drawerWidth = clampSidebarWidth(desiredDrawer, leftWidth + railWidth, MAX_DRAWER_WIDTH);
    setRightSidebarWidth(drawerWidth, railWidth);
  } else if (activeDrawer.value) {
    setRightSidebarWidth(0, railWidth);
  }

  setLeftSidebarWidth(leftWidth);
  updateChatContainerLayout();
}

function updateChatContainerLayout() {
  const chatContainer = document.querySelector('.chat-container');
  if (!chatContainer) return;
  const leftWidth = getLeftSidebarWidth();
  const rightWidth = getRightSidebarWidth();
  chatContainer.style.marginLeft = leftWidth ? `${leftWidth}px` : '0';
  chatContainer.style.marginRight = rightWidth ? `${rightWidth}px` : '0';
  if (leftWidth || rightWidth) {
    chatContainer.style.width = `calc(100% - ${leftWidth}px - ${rightWidth}px)`;
  } else {
    chatContainer.style.width = '100%';
  }
  chatContainer.style.transition = 'margin-left 0.3s ease, margin-right 0.3s ease, width 0.3s ease';
}

function startResizeHandler(event) {
  initialWidth.value = sidebarContentContainer.value.offsetWidth;
  initialMouseX.value = event.clientX;
  document.addEventListener('mousemove', resizeHandler);
  document.addEventListener('mouseup', stopResizeHandler);
}

function resizeHandler(event) {
  if (!sidebarContentContainer.value) return;
  const deltaX = event.clientX - initialMouseX.value;
  const rightWidth = getRightSidebarWidth();
  const maxWidth = clampSidebarWidth(MAX_SIDEBAR_WIDTH, rightWidth);
  const newWidth = Math.max(250, Math.min(maxWidth, initialWidth.value + deltaX));
  setLeftSidebarWidth(newWidth);
  
  // Update the chat container margin to match
  const chatContainer = document.querySelector('.chat-container');
  if (chatContainer) {
    chatContainer.style.marginLeft = `${newWidth}px`;
    chatContainer.style.width = `calc(100% - ${newWidth}px)`;
  }
  updateChatContainerLayout();
}

function stopResizeHandler() {
  document.removeEventListener('mousemove', resizeHandler);
  document.removeEventListener('mouseup', stopResizeHandler);
}

function resetSidebarForMobile() {
  if (!sidebarContentContainer.value) return;
  
  // Reset to 100vw for mobile
  sidebarContentContainer.value.style.width = '100vw';
  sidebarContentContainer.value.style.minWidth = '100vw';
  sidebarContentContainer.value.style.maxWidth = '100vw';
  
  // Reset the sidebar conversations element too
  const sidebarConversations = document.querySelector('.sidebar-conversations');
  if (sidebarConversations) {
    sidebarConversations.style.width = '100vw';
    sidebarConversations.style.minWidth = '100vw';
    sidebarConversations.style.maxWidth = '100vw';
  }
  
  updateChatContainerLayout();
}

function resetSidebarForDesktop() {
  syncSidebarRefs();
  if (!sidebarContentContainer.value || !sidebarContentContainer.value.isConnected) return;
  
  applySidebarWidths();
}

function handleWindowResize() {
  syncSidebarRefs();
  applySidebarWidths();
}

function handleConversationsCollapseToggle(event) {
  isCollapsed.value = Boolean(event?.detail?.collapsed);
  syncLeftModelDrawerWithCollapse();
  nextTick(() => {
    syncSidebarRefs();
    applySidebarWidths();
    requestAnimationFrame(() => {
      updateChatContainerLayout();
    });
  });
}

function stopConversationsStateObserver() {
  if (conversationsStateObserver.value) {
    conversationsStateObserver.value.disconnect();
    conversationsStateObserver.value = null;
  }
}

function syncCollapsedStateFromDom(force = false) {
  const innerDialog = sidebarContentContainer.value?.querySelector('.conversations-dialog');
  if (!innerDialog) return;
  const domCollapsed = innerDialog.classList.contains('collapsed');
  if (force || isCollapsed.value !== domCollapsed) {
    isCollapsed.value = domCollapsed;
  }
  try {
    localStorage.setItem('conversationsDialogCollapsed', domCollapsed ? 'true' : 'false');
  } catch (_error) {
    // Ignore storage write issues.
  }
  nextTick(() => {
    syncSidebarRefs();
    applySidebarWidths();
    requestAnimationFrame(() => {
      updateChatContainerLayout();
    });
  });
}

function startConversationsStateObserver() {
  stopConversationsStateObserver();
  const innerDialog = sidebarContentContainer.value?.querySelector('.conversations-dialog');
  if (!innerDialog) return;
  conversationsStateObserver.value = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
        syncCollapsedStateFromDom();
        break;
      }
    }
  });
  conversationsStateObserver.value.observe(innerDialog, {
    attributes: true,
    attributeFilter: ['class']
  });
  syncCollapsedStateFromDom(true);
}

//#region File/Upload Handling
function handleImportConversations() {
  openFileSelector();
}

function importFileClick() {
  document.getElementById('fileImportUpload').click();
}

function openFileSelector() {
  document.getElementById('fileUpload').click();
}

function showDrawer(name) {
  if (activeDrawer.value === name) return;
  activeDrawer.value = name;
  nextTick(() => {
    applySidebarWidths();
  });
}

function toggleDrawer(name) {
  activeDrawer.value = activeDrawer.value === name ? null : name;
  nextTick(() => {
    applySidebarWidths();
  });
}

function closeDrawer() {
  if (!activeDrawer.value) return;
  if (activeDrawer.value === 'canvas') {
    canvasCollapsed.value = false;
  }
  activeDrawer.value = null;
  nextTick(() => {
    applySidebarWidths();
  });
}

function openCanvasDrawer() {
  canvasCollapsed.value = false;
  showDrawer('canvas');
}

function toggleCanvasDrawer() {
  if (activeDrawer.value === 'canvas') {
    closeDrawer();
    return;
  }
  canvasCollapsed.value = false;
  showDrawer('canvas');
}

function toggleCanvasCollapse() {
  // Close the canvas drawer entirely instead of showing a collapsed panel
  // The canvas icon in the right rail remains available to reopen
  closeDrawer();
}

function toggleSwarmDrawer() {
  toggleDrawer('swarm');
}

function toggleToolsDrawer() {
  toggleDrawer('tools');
}

function toggleDiagnosticsDrawer() {
  toggleDrawer('diagnostics');
}

function toggleSelfImproveDrawer() {
  toggleDrawer('self');
}

function toggleInnerLifeDrawer() {
  toggleDrawer('innerlife');
}

function toggleTransferDrawer() {
  toggleDrawer('transfer');
}

function toggleActivityDrawer() {
  toggleDrawer('activity');
}

function toggleModelConfigDrawer() {
  toggleDrawer('model-config');
}

// Exit/Shutdown functionality
const showExitConfirm = ref(false);
const isShuttingDown = ref(false);
const shutdownStage = ref('idle');

async function requestShutdown() {
  if (isShuttingDown.value) return;
  showExitConfirm.value = false;
  isShuttingDown.value = true;
  shutdownStage.value = 'working';
  try {
    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), 1500);
    fetch('/api/exit', { method: 'POST', signal: controller.signal, keepalive: true })
      .catch((error) => {
        console.error('Shutdown request failed:', error);
      })
      .finally(() => {
        clearTimeout(abortTimer);
      });
  } catch (error) {
    console.error('Shutdown request failed:', error);
  }
  setTimeout(() => {
    shutdownStage.value = 'ready';
  }, 5000);
}

function promptShutdown() {
  if (isShuttingDown.value) return;
  showExitConfirm.value = true;
}

// Artifact management
function handleSaveArtifact(artifactData) {
  if (!selectedConversation.value) {
    showToast('No conversation selected. Start a conversation first.');
    return;
  }

  const artifact = createArtifact(selectedConversation.value, artifactData);
  currentArtifacts.value = getArtifacts(selectedConversation.value);
  saveMessagesHandler(); // Save to localStorage

  showToast(`Artifact "${artifact.title}" saved`);
}

function handleDeleteArtifact(artifact) {
  if (!selectedConversation.value) return;

  if (confirm(`Delete artifact "${artifact.title}"?`)) {
    deleteArtifact(selectedConversation.value, artifact.id);
    currentArtifacts.value = getArtifacts(selectedConversation.value);
    saveMessagesHandler();
    showToast('Artifact deleted');
  }
}

async function loadArtifactIntoCanvas(artifact) {
  try {
    // Open the canvas drawer if not already open
    if (activeDrawer.value !== 'canvas') {
      openCanvasDrawer();
    }

    // Push artifact content to backend editor state
    await fetch('/api/editor', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: artifact.content,
        language: artifact.language,
        file_path: artifact.file_path || '',
        is_open: true
      })
    });

    showToast(`Loaded: ${artifact.title}`);
  } catch (error) {
    console.error('Failed to load artifact:', error);
    showToast('Failed to load artifact');
  }
}

// Watch for conversation changes to load artifacts
watch(selectedConversation, (newConv) => {
  if (newConv) {
    currentArtifacts.value = getArtifacts(newConv);
  } else {
    currentArtifacts.value = [];
  }
}, { immediate: true });

// Handle forked conversation - auto-send the continuation prompt to the agent
async function handleForkConversation({ conversation, prompt }) {
  // Set the user text to the continuation prompt
  userText.value = prompt;

  // Wait for Vue to update the DOM
  await nextTick();

  // Trigger the send via the chatInput ref
  if (chatInputRef.value && typeof chatInputRef.value.sendNewMessage === 'function') {
    chatInputRef.value.sendNewMessage();
  } else {
    // Fallback: if ref isn't available, show a message
    showToast('Ready to continue - press Send');
  }
}

// Check if VERA wants to open the editor (polls when drawer is closed)
async function checkEditorOpenRequest() {
  if (activeDrawer.value === 'canvas') return; // Already open, no need to poll

  try {
    const response = await fetch('/api/editor');
    if (!response.ok) return;

    const state = await response.json();
    // If VERA has set is_open to true, open the editor panel
    if (state.is_open && activeDrawer.value !== 'canvas') {
      openCanvasDrawer();
      showToast('VERA opened the code editor');
    }
  } catch (error) {
    // Silently fail - editor service may not be running
  }
}

function startEditorPoll() {
  // Poll every 2 seconds when editor is closed
  if (!editorPollInterval.value) {
    editorPollInterval.value = setInterval(checkEditorOpenRequest, 2000);
  }
}

function stopEditorPoll() {
  if (editorPollInterval.value) {
    clearInterval(editorPollInterval.value);
    editorPollInterval.value = null;
  }
}

async function refreshReadiness() {
  try {
    const response = await fetch('/api/readiness', { cache: 'no-store' });
    if (!response.ok) return;
    const payload = await response.json();
    const wasReady = readinessState.value.ready;
    readinessState.value = {
      ready: Boolean(payload.ready),
      phase: payload.phase || (payload.ready ? 'ready' : 'loading'),
      message: payload.message || (payload.ready
        ? 'Tools have been fully loaded. Vera is online and ready.'
        : 'Stand by please while my tools are loading.')
    };

    if (!wasReady && readinessState.value.ready && !hasShownReadyToast.value) {
      showToast('Tools have been fully loaded · Vera is online and ready', { duration: 5000 });
      hasShownReadyToast.value = true;
    }
  } catch (_error) {
    // Keep existing readiness message on transient errors.
  }
}

function startReadinessPoll() {
  if (readinessPollInterval.value) return;
  refreshReadiness();
  readinessPollInterval.value = setInterval(refreshReadiness, 3000);
}

function stopReadinessPoll() {
  if (!readinessPollInterval.value) return;
  clearInterval(readinessPollInterval.value);
  readinessPollInterval.value = null;
}

async function imageInputChangedHandler(event) {
  stageImageUpload(event);
}
//#endregion

async function fetchAvailableModels() {
  try {
    if (localModelEndpoint.value.trim() !== '') {
      const models = await getOpenAICompatibleAvailableModels(removeAPIEndpoints(localModelEndpoint.value));
      availableModels.value = models;
    }
  } catch (error) {
    console.error('Error fetching available models:', error);
  }
}

//#region Lifecycle Hooks
onMounted(async () => {
  setupWatchers();
  sidebarContentContainer.value = document.querySelector('#conversations-dialog');
  drawerContainer.value = document.querySelector('#drawer-panel');
  startConversationsStateObserver();

  sendActivityPing('mount');
  window.addEventListener('mousemove', handleUserActivity);
  window.addEventListener('mousedown', handleUserActivity);
  window.addEventListener('keydown', handleUserActivity);
  window.addEventListener('touchstart', handleUserActivity, { passive: true });
  window.addEventListener('scroll', handleUserActivity, { passive: true });
  window.addEventListener('focus', handleUserActivity);
  document.addEventListener('visibilitychange', handleVisibilityChange);
  
  // Set initial collapsed state from localStorage
  isCollapsed.value = localStorage.getItem('conversationsDialogCollapsed') === 'true';
  
  if (sidebarContentContainer.value) {
    // Initialize with width based on collapsed state
    applySidebarWidths();
  }
  
  // Listen for collapse/expand events from ConversationsDialog
  document.addEventListener('conversations-collapse-toggle', handleConversationsCollapseToggle);
  
  // Watch for screen size changes to reset sidebar width on mobile
  watch(isSmallScreen, (newIsSmallScreen) => {
    if (newIsSmallScreen) {
      resetSidebarForMobile();
      applySidebarWidths();
      return;
    }
    nextTick(() => {
      syncSidebarRefs();
      resetSidebarForDesktop();
      applySidebarWidths();
    });
  });

  window.addEventListener('resize', handleWindowResize);

  selectedModel.value = localStorage.getItem('selectedModel') || 'open-ai-format';
  syncPendingConfirmations(conversations.value.map((conversation) => conversation.id));

  modelDisplayName.value = determineModelDisplayName(selectedModel.value);
  higherContrastMessages.value = localStorage.getItem('higherContrastMessages') || false;

  if (selectedModel.value === 'open-ai-format') {
    fetchAvailableModels();
  }

  // Always start with a fresh conversation
  messages.value = [];
  selectedConversation.value = null;
  lastLoadedConversationId.value = null;
  localStorage.removeItem('lastConversationId');

  document.addEventListener('swiped-left', function (e) {
    if (!e.detail.xStart || !(window.innerWidth - e.detail.xStart <= 100)) {
      console.log('Swipe did not start at the edge of the right side of the screen');
      showConversationOptions.value = false;
    }
  });

  document.addEventListener('swiped-right', function (e) {
    if (!e.detail.xStart || e.detail.xStart >= 100) {
      console.log('Swipe did not start at the edge of the left side of the screen');
      isSidebarOpen.value = false;
    }
  });

  await runTutortialForNewUser();

  // Start polling for VERA editor open requests
  startEditorPoll();
  startReadinessPoll();
});

onBeforeUnmount(() => {
  stopConversationsStateObserver();
  window.removeEventListener('resize', handleWindowResize);
  window.removeEventListener('mousemove', handleUserActivity);
  window.removeEventListener('mousedown', handleUserActivity);
  window.removeEventListener('keydown', handleUserActivity);
  window.removeEventListener('touchstart', handleUserActivity);
  window.removeEventListener('scroll', handleUserActivity);
  window.removeEventListener('focus', handleUserActivity);
  document.removeEventListener('visibilitychange', handleVisibilityChange);
  document.removeEventListener('conversations-collapse-toggle', handleConversationsCollapseToggle);
  stopEditorPoll();
  stopReadinessPoll();
});

watch(isSidebarOpen, (isOpen) => {
  if (!isOpen) {
    return;
  }
  nextTick(() => {
    applyTheme();
  });
});

// Note: Ref syncing is now handled by transition hooks (@after-enter, @before-leave)
// This watch is kept for immediate layout prep before transitions complete
watch(activeDrawer, (drawer) => {
  if (drawer !== 'canvas') {
    canvasCollapsed.value = false;
  }
  if (!drawer) {
    updateChatContainerLayout();
    return;
  }
  nextTick(() => {
    applyTheme();
    applySidebarWidths();
  });
});

function closeDialogs() {
  isSidebarOpen.value = false;
  showConversationOptions.value = false;
  showStoredFiles.value = false;
  closeDrawer();
}

//#endregion
</script>

<template>
  <!-- Skip link for keyboard navigation -->
  <a href="#user-input" class="skip-link">Skip to chat input</a>

  <!-- ARIA live region for screen reader announcements -->
  <div
    v-if="a11yScreenReaderAnnounce"
    class="aria-live-region"
    role="status"
    aria-live="polite"
    aria-atomic="true"
    id="aria-announcements"
  ></div>

  <div id="fileUploadDiv">
    <input type="file" id="fileUpload" style="display: none"
      @change="(event) => uploadFile(event, conversations, selectConversationHandler)" />
    <input type="file" id="fileImportUpload" style="display: none"
      @change="(event) => stageFileUpload(event)" />
    <div @click="openFileSelector" style="display: none">Upload File</div>
    <div @click="importFileClick" style="display: none">Import File</div>
    <input id="imageInput" ref="imageInput" @change="imageInputChangedHandler" style="display: none" type="file" accept="image/*" />
  </div>
  <div class="app-body" role="main" aria-label="Chat application">
    <!-- Effect overlays - only rendered when effects are enabled -->
    <div v-if="!uiLiteMode && uiEffectNoise" class="vera-noise-overlay"></div>
    <div v-if="!uiLiteMode && uiEffectGrid" class="vera-grid-overlay"></div>
    <!-- Aurora: each layer is a wrapper (cheap transforms) with ::before (cached blur+gradient) -->
    <div v-if="!uiLiteMode && uiEffectAurora" class="vera-aurora-overlay" aria-hidden="true">
      <div class="vera-aurora-layer vera-aurora-left"></div>
      <div class="vera-aurora-layer vera-aurora-right"></div>
      <div class="vera-aurora-layer vera-aurora-bottom"></div>
    </div>
    <div v-if="!uiLiteMode && uiEffectVignette" class="vera-vignette-overlay"></div>

    <div class="app-container" id="app-container">
      <transition name="fade">
        <div @click="closeDialogs" class="overlay" v-show="isSidebarOpen || showConversationOptions || showStoredFiles">
        </div>
      </transition>

      <Transition name="dialog-slide">
        <div class="sidebar-common" id="settings-dialog" v-if="isSidebarOpen">
          <settingsDialog />
        </div>
      </Transition>
      <Transition name="dialog-slide" @after-enter="onLeftSidebarEnter" @before-leave="onLeftSidebarLeave">
        <div class="sidebar-conversations" :class="{ 'is-collapsed': isCollapsed && !isSmallScreen }" id="conversations-dialog"
          v-if="showConversationOptions || !isSmallScreen">
          <conversationsDialog :collapsed="isCollapsed"
            @import-conversations="handleImportConversations"
            @export-conversations="handleExportConversations"
            @fork-conversation="handleForkConversation"
            @collapse-change="(collapsed) => handleConversationsCollapseToggle({ detail: { collapsed } })"
            @toggle-model-config="toggleModelConfigDrawer" />
          <div id="resize-handle" class="resize-handle"
               v-show="!isCollapsed"
               @mousedown="startResizeHandler"
               @dblclick="() => handleDoubleClick(sidebarContentContainer)">
          </div>
        </div>
      </Transition>
      <Transition name="dialog-slide">
        <StoredFilesList id="stored-files" v-if="showStoredFiles" />
      </Transition>
      <!-- Left-side drawer for Model Config -->
      <Transition name="dialog-slide">
        <div class="sidebar-drawer sidebar-left" id="model-config-panel"
          v-if="activeDrawer === 'model-config' && (!isCollapsed || isSmallScreen)">
          <ModelConfigDrawer @close="closeDrawer" />
        </div>
      </Transition>
      <!-- Right-side drawers -->
      <Transition name="dialog-slide" @after-enter="onRightSidebarEnter" @before-leave="onRightSidebarLeave">
        <div class="sidebar-drawer sidebar-right" :class="drawerPanelClass" id="drawer-panel" v-if="activeDrawer && activeDrawer !== 'model-config'">
          <CanvasDrawer
            v-if="activeDrawer === 'canvas'"
            :collapsed="canvasCollapsed"
            @close="closeDrawer"
            @save-artifact="handleSaveArtifact"
            @toggle-collapse="toggleCanvasCollapse"
          />
          <SwarmDrawer v-else-if="activeDrawer === 'swarm'" @close="closeDrawer" />
          <ToolsDrawer v-else-if="activeDrawer === 'tools'" @close="closeDrawer" />
          <DiagnosticsDrawer v-else-if="activeDrawer === 'diagnostics'" @close="closeDrawer" />
          <SelfImproveDrawer v-else-if="activeDrawer === 'self'" @close="closeDrawer" />
          <InnerLifeDrawer v-else-if="activeDrawer === 'innerlife'" @close="closeDrawer" />
          <ActivityDrawer v-else-if="activeDrawer === 'activity'" @close="closeDrawer" />
          <ImportExportDrawer
            v-else-if="activeDrawer === 'transfer'"
            @close="closeDrawer"
            @import-conversations="handleImportConversations"
            @export-conversations="handleExportConversations"
          />
        </div>
      </Transition>
      <div v-if="showRightRail" class="right-rail">
        <button
          class="rail-btn"
          :class="{ active: activeDrawer === 'canvas' }"
          title="Canvas"
          @click="toggleCanvasDrawer"
        >
          <Code2 size="18" />
        </button>
        <button
          class="rail-btn"
          :class="{ active: activeDrawer === 'swarm' }"
          title="Quorum/Swarm"
          @click="toggleSwarmDrawer"
        >
          <Network size="18" />
        </button>
        <button
          class="rail-btn"
          :class="{ active: activeDrawer === 'tools' }"
          title="Tools"
          @click="toggleToolsDrawer"
        >
          <Wrench size="18" />
        </button>
        <button
          class="rail-btn"
          :class="{ active: activeDrawer === 'diagnostics' }"
          title="Diagnostics"
          @click="toggleDiagnosticsDrawer"
        >
          <Activity size="18" />
        </button>
        <button
          class="rail-btn"
          :class="{ active: activeDrawer === 'self' }"
          title="Self-Improvement Dashboard"
          @click="toggleSelfImproveDrawer"
        >
          <Sparkles size="18" />
        </button>
        <button
          class="rail-btn"
          :class="{ active: activeDrawer === 'innerlife' }"
          title="Inner Life"
          @click="toggleInnerLifeDrawer"
        >
          <Brain size="18" />
        </button>
        <button
          class="rail-btn"
          :class="{ active: activeDrawer === 'activity' }"
          title="Activity Feed"
          @click="toggleActivityDrawer"
        >
          <Radio size="18" />
        </button>
        <button
          class="rail-btn transfer-btn"
          :class="{ active: activeDrawer === 'transfer' }"
          title="Import/Export"
          @click="toggleTransferDrawer"
        >
          <svg class="rail-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M7 3v10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            <path d="M4 10l3 3 3-3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M17 21V11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            <path d="M14 14l3-3 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
        <div class="rail-spacer"></div>
        <button
          class="rail-btn exit-btn"
          title="Exit VERA"
          @click="promptShutdown"
        >
          <Power size="18" />
        </button>
      </div>
      <div class="chat-container">
        <div class="container">
          <div class="chat">
            <div v-if="!readinessState.ready" class="readiness-banner" role="status" aria-live="polite">
              <span class="readiness-dot" aria-hidden="true"></span>
              <span>{{ readinessState.message }}</span>
            </div>
            <chatHeader :storedConversations="storedConversations"
                      />
            <div class="messages">
              <ArtifactsList
                v-if="currentArtifacts.length > 0"
                :artifacts="currentArtifacts"
                @load-artifact="loadArtifactIntoCanvas"
                @delete-artifact="handleDeleteArtifact"
                @create-artifact="openCanvasDrawer"
              />
              <messageItem />
            </div>
            <chatInput ref="chatInputRef" :userInput="userText" @abort-stream="abortStream" @upload-context="importFileClick"
              @update:userInput="updateUserText" />
          </div>
        </div>
      </div>
    </div>
    <Teleport to="body">
      <ConfirmationDialog
        v-model:visible="showExitConfirm"
        title="Exit VERA?"
        message="Exit Vera and shut down services?"
        confirmLabel="Exit"
        cancelLabel="Cancel"
        :isWarning="true"
        @confirm="requestShutdown"
      />
    </Teleport>
    <Teleport to="body">
      <div v-if="isShuttingDown" class="shutdown-overlay">
        <div class="shutdown-card">
          <div v-if="shutdownStage === 'working'" class="shutdown-stage">
            <div class="spinner"></div>
            <div class="shutdown-title">Shutting down</div>
            <div class="shutdown-subtitle">Cleaning up before exiting...</div>
          </div>
          <div v-else class="shutdown-stage">
            <div class="shutdown-title">Cleanup complete</div>
            <div class="shutdown-subtitle">You may now close this browser tab.</div>
            <div class="shutdown-actions">
              <button class="shutdown-btn" @click="isShuttingDown = false">Stay open</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style lang="scss">
$icon-color: var(--vera-icon);
$background-color: var(--vera-bg);
$container-bg-color: var(--vera-panel-muted);
$sidebar-bg-color: var(--vera-surface);
$scrollbar-track-color: var(--vera-scrollbar-track);
$scrollbar-thumb-color: var(--vera-scrollbar-thumb);
$scrollbar-thumb-hover-color: var(--vera-scrollbar-thumb-hover);
$border-color: var(--vera-border);
$hover-bg-color: var(--vera-panel-alt);
$button-bg-color: var(--vera-panel);
$button-hover-bg-color: var(--vera-panel-alt);
$font-color: var(--vera-text);
$overlay-bg-color: rgba(var(--vera-shadow-rgb), 0.6);

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.dialog-slide-enter-active {
  transition: all 0.35s cubic-bezier(0.25, 1.25, 0.5, 1);
  transform: translateY(0);
  opacity: 1;

  @media (max-width: 600px) {
    transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
    transform: scale(1);
    opacity: 1;
  }
}

.dialog-slide-leave-active {
  transition: all 0.25s cubic-bezier(0.55, 0.085, 0.68, 0.53);
  transform: translateY(-100%);
  opacity: 0;

  @media (max-width: 600px) {
    transition: all 0.25s cubic-bezier(0.55, 0.085, 0.68, 0.53);
    transform: scale(0.2);
    opacity: 0;
  }
}

.dialog-slide-enter-from {
  transform: translateY(-100%);
  opacity: 0;
  box-shadow: 0 0 0 rgba(var(--vera-shadow-rgb), 0);

  @media (max-width: 600px) {
    transform: scale(0.2);
    opacity: 0;
    box-shadow: 0 0 0 rgba(var(--vera-shadow-rgb), 0);
  }
}

.dialog-slide-leave-to {
  transform: translateY(-100%);
  opacity: 0;
  box-shadow: 0 0 0 rgba(var(--vera-shadow-rgb), 0);

  @media (max-width: 600px) {
    transform: scale(0.2);
    opacity: 0;
    box-shadow: 0 0 0 rgba(var(--vera-shadow-rgb), 0);
  }
}

@font-face {
  font-family: Roboto-Regular;
  src: url('/src/assets/webfonts/Roboto-Regular.ttf');
  font-weight: 400;
  font-style: normal;
}

body {
  font-family: var(--vera-font-sans);
  margin: 0;
  padding: 0;
  background: var(--vera-app-bg);
  color: $font-color;
}

a {
  color: var(--vera-text-muted);

  &:hover,
  &:focus,
  &:active,
  &:visited {
    color: $icon-color;
  }
}

.app-body {
  width: 100vw;
  height: 100dvh;
  min-height: 100dvh;
  position: relative;
  max-height: 100dvh;
  overflow: hidden;

  @media (max-width: 600px) {
    height: 100dvh;
    min-height: 100dvh;
    max-height: 100dvh;
    overflow: hidden;
  }
}

.container {
  display: flex;
  justify-content: flex-start;
  align-items: stretch;
  width: 100%;
  height: 100%;
}

.chat {
  width: 100%;
  background: transparent;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  margin-bottom: 0;
  position: relative; /* Added to establish positioning context */
  padding-bottom: env(safe-area-inset-bottom, 0px); /* iOS safe area support */
  overflow: hidden;
  border: 1px solid var(--vera-glass-border);
  backdrop-filter: blur(18px);

  /* Chat area background image layer */
  &::before {
    content: '';
    position: absolute;
    inset: 0;
    background-image: var(--vera-chat-image, none);
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    opacity: var(--vera-chat-image-opacity, 0.25);
    filter: blur(var(--vera-chat-image-blur, 6px));
    pointer-events: none;
    z-index: 0;
  }

  /* Ensure chat content sits above background */
  & > * {
    position: relative;
    z-index: 1;
  }

  @media (max-width: 600px) {
    width: 100%;
    height: 100%;
    margin: 0;
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }

  &.header {
    background-color: $border-color;
    padding: 10px;
    font-size: 18px;
    font-weight: bold;
    text-align: center;
  }

  &.api-key {
    display: flex;
  }
}

.readiness-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 12px 16px 0 16px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--vera-accent-20);
  background: rgba(var(--vera-accent-rgb), 0.12);
  color: var(--vera-text);
  font-size: 0.92rem;
  letter-spacing: 0.01em;
}

.readiness-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--vera-accent);
  box-shadow: 0 0 10px rgba(var(--vera-accent-rgb), 0.7);
  animation: readinessPulse 1.2s ease-in-out infinite;
}

@keyframes readinessPulse {
  0%, 100% {
    opacity: 0.6;
    transform: scale(1);
  }
  50% {
    opacity: 1;
    transform: scale(1.2);
  }
}

.messages {
  overflow-y: auto;
  overflow-x: hidden;
  flex: 1 1 auto;
  min-height: 0;
  scrollbar-width: none; // For Firefox
  -ms-overflow-style: none; // For Internet Explorer and Edge
  padding: 16px 16px 8px 16px;
  position: relative;

  @media (max-width: 600px) {
    width: 100%;
    padding: 8px 8px 4px 8px;
    flex: 1;
    margin-bottom: 0; /* Removed margin to maximize message space */
  }

  &::-webkit-scrollbar {
    display: none; // For Chrome, Safari, and Opera
  }
}

#user-search-input {
  flex-grow: 1;
  border: 1px solid $border-color;
  background-color: $background-color;
  font-size: 18px;
  color: $font-color;
  width: inherit;
  resize: vertical;
  overflow: auto;
  white-space: pre-wrap;
  min-height: 30px;
  border-radius: 30px;
  transition: 0.2s height ease-in-out;
  padding: 14px 14px 14px 20px;
}

button {
  border: 1px solid $border-color;
  background-color: $button-bg-color;
  color: $font-color;
  cursor: pointer;

  &:hover {
    background-color: $button-hover-bg-color;
  }
}

.hover-increase-size {
  transition:
    background-color 0.15s ease,
    transform 0.15s ease;

  &:hover {
    transform: scale(1.2);
  }
}

pre {
  background-color: var(--vera-panel-alt) !important;
  color: var(--vera-text) !important;
  padding: 10px;
  border-radius: 12px;
  max-width: 98vw;
  scrollbar-width: none;
  overflow: auto;

  code {
    max-width: 97vw;
  }
}

.app-container {
  display: flex;
  justify-content: flex-start;
  align-items: stretch;
  width: 100%;
  height: 100%;
  margin: 1px;
  border-radius: 8px;
}

.general-processing {
  display: contents;
}

::-webkit-scrollbar {
  width: 8px;
}

::-webkit-scrollbar-track {
  background: $scrollbar-track-color;
}

::-webkit-scrollbar-thumb {
  background: $scrollbar-thumb-color;

  &:hover {
    background: $scrollbar-thumb-hover-color;
  }
}

.resize-handle {
  position: absolute;
  top: 0;
  right: 0px;
  width: 8px;
  height: 100%;
  cursor: col-resize;
  background-color: var(--vera-panel);
  z-index: 1000;
  transition: background-color 0.2s ease;
  
  &:hover {
    background-color: var(--vera-accent);
  }
  
  &:active {
    background-color: var(--vera-accent-strong);
    width: 10px;
  }
}

.sidebar-conversations,
.sidebar-common,
.sidebar-drawer {
  background: var(--vera-sidebar-bg);
  background-image: var(--vera-sidebar-image);
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  backdrop-filter: blur(16px);
  border-color: var(--vera-glass-border);
  padding: 0;
  overflow-x: hidden;
  overflow-y: auto;
  z-index: 0;
  box-shadow: 0 12px 32px var(--vera-black-30);
  position: relative;

  @media (max-width: 600px) {
    position: fixed;
    width: 100vw;
  }
}

/* Left sidebar (conversations) uses independent left sidebar background */
.sidebar-conversations::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: var(--vera-left-sidebar-image, var(--vera-sidebar-image));
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  opacity: var(--vera-left-sidebar-image-opacity, var(--vera-sidebar-image-opacity));
  filter: blur(var(--vera-left-sidebar-image-blur, var(--vera-sidebar-image-blur)));
  pointer-events: none;
  z-index: 0;
}

/* Settings dialog uses shared sidebar background */
.sidebar-common::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: var(--vera-sidebar-image);
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  opacity: var(--vera-sidebar-image-opacity);
  filter: blur(var(--vera-sidebar-image-blur));
  pointer-events: none;
  z-index: 0;
}

/* Right sidebar (drawer) uses independent right sidebar background */
.sidebar-drawer::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: var(--vera-right-sidebar-image, var(--vera-sidebar-image));
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  opacity: var(--vera-right-sidebar-image-opacity, var(--vera-sidebar-image-opacity));
  filter: blur(var(--vera-right-sidebar-image-blur, var(--vera-sidebar-image-blur)));
  pointer-events: none;
  z-index: 0;
}

.sidebar-conversations > *,
.sidebar-common > *,
.sidebar-drawer > * {
  position: relative;
  z-index: 1;
}

.sidebar-drawer {
  position: fixed;
  top: 0;
  right: 0;
  height: 100vh;
  max-width: 360px;
  min-width: 360px;
  width: 360px;
  z-index: 2;
  margin: 0;
  padding-top: 0;
  border-left: 1px solid var(--vera-glass-border);

  @media (max-width: 600px) {
    width: 100vw;
    max-width: 100vw;
    min-width: 100vw;
    height: 101vh;
    right: 0;
    top: 0;
    border-left: 2px solid var(--vera-glass-border);
  }
}

.sidebar-drawer.drawer-canvas {
  width: min(860px, 58vw);
  max-width: min(860px, 58vw);
  min-width: 420px;
}

// Left-side drawer (for Model Config)
.sidebar-drawer.sidebar-left {
  right: auto;
  left: 0;
  border-left: none;
  border-right: 1px solid var(--vera-glass-border);

  @media (max-width: 600px) {
    left: 0;
    right: auto;
    border-left: none;
    border-right: 2px solid var(--vera-glass-border);
  }
}

.sidebar-conversations {
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  max-width: 325px;
  min-width: 325px;
  width: 325px;
  z-index: 2;
  margin: 0;
  padding-top: 0;
  border-right: 1px solid var(--vera-glass-border);

  @media (max-width: 600px) {
    position: fixed;
    border-right: 2px solid var(--vera-glass-border);
    z-index: 2;
    width: 100vw;
    max-width: 100vw;
    min-width: 100vw;
    height: 101vh;
    left: 0;
    top: 0;

    &.open {
      width: 100vw;
      height: 100vh;
    }
  }
}

.sidebar-conversations.is-collapsed {
  width: 60px !important;
  min-width: 60px !important;
  max-width: 60px !important;
}


.sidebar-common {
  min-width: 25vw;
  max-width: 100vw;
  position: fixed;
  top: 5%;
  padding: 0;
  border-right: 2px solid var(--vera-glass-border);
  z-index: 3;
  border-radius: 12px;
  border: 1px solid var(--vera-glass-border);
  box-shadow: 0 18px 40px var(--vera-black-30);
  width: 60vw;
  height: 85vh;
  font-size: 12px;

  @media (max-width: 600px) {
    width: 100vw;
    height: 100vh;
    top: 0;
    left: 0;
    right: 0;
    border-radius: 0;
    border: none;
    z-index: 3;
  }

  &.sidebar-right {
    right: 0;
    
    @media (max-width: 600px) {
      right: 0;
      left: 0;
    }
  }

  &.open {
    opacity: 1;
  }
}

.sidebar-left {
  left: 0;
}

.overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100vh;
  background-color: $overlay-bg-color;
  z-index: 1;
  transition: opacity 0.15s linear;
  display: block;

  @media (max-width: 600px) {
    /* Show overlay on mobile for better UI experience */
    display: block;
    z-index: 1;
  }

  &:not(:empty) {
    display: none;
  }
}

@keyframes delayZIndex {
  0% {
    z-index: -1;
  }

  100% {
    z-index: 9999;
  }
}


.chat-container {
  display: flex;
  flex-direction: column;
  flex-grow: 1;
  min-height: min(500px, 100%);
  min-width: min(350px, 100%);
  width: 100%;
  max-width: 100%;
  height: 100%;
  background: transparent;
  justify-content: space-between;
  position: relative;
  transition: margin-left 0.3s ease, width 0.3s ease;
  padding-bottom: 0;

  @media (min-width: 601px) {
    margin-left: 325px; /* Same as the width of sidebar-conversations */
    width: calc(100% - 325px);
  }
  
  @media (max-width: 600px) {
    min-height: 100%;
    height: 100vh;
    width: 100%;
    min-width: 100%;
    padding: 0;
    margin: 0;
  }
}

.right-rail {
  position: fixed;
  top: 0;
  right: 0;
  width: 56px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 12px 6px;
  background: var(--vera-sidebar-bg);
  border-left: 1px solid var(--vera-glass-border);
  box-shadow: 0 10px 26px var(--vera-black-30);
  backdrop-filter: blur(16px);
  z-index: 4;
  overflow-y: auto;
  scrollbar-width: none;

  @media (max-width: 600px) {
    display: none;
  }
}

.right-rail::-webkit-scrollbar {
  display: none;
}

// Nixie tube styled rail buttons
.rail-btn {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  border: 1px solid var(--vera-nixie-color-soft);
  background: var(--vera-nixie-button-bg);
  color: var(--vera-nixie-color);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow:
    inset 0 1px 3px var(--vera-black-50),
    0 0 10px var(--vera-nixie-color-faint);
  transition: transform 0.15s ease, box-shadow 0.15s ease;

  svg, .rail-icon {
    color: var(--vera-nixie-color);
    filter: drop-shadow(0 0 3px rgba(var(--vera-nixie-glow-rgb), calc(0.6 * var(--vera-nixie-intensity, 1))))
            drop-shadow(0 0 6px rgba(var(--vera-nixie-glow-rgb), calc(0.4 * var(--vera-nixie-intensity, 1))));
    transition: filter 0.15s ease;
  }
}

.rail-icon {
  width: 18px;
  height: 18px;
  display: block;
}

.rail-btn.active {
  box-shadow:
    inset 0 1px 3px var(--vera-black-50),
    0 0 15px var(--vera-nixie-color-soft),
    0 0 30px var(--vera-nixie-color-faint);
  border-color: var(--vera-nixie-color-soft);

  svg, .rail-icon {
    filter: drop-shadow(0 0 4px rgba(var(--vera-nixie-glow-rgb), calc(0.9 * var(--vera-nixie-intensity, 1))))
            drop-shadow(0 0 8px rgba(var(--vera-nixie-glow-rgb), calc(0.7 * var(--vera-nixie-intensity, 1))))
            drop-shadow(0 0 14px rgba(var(--vera-nixie-glow-rgb), calc(0.5 * var(--vera-nixie-intensity, 1))));
  }
}

.rail-btn:hover {
  transform: scale(1.05);
  box-shadow:
    inset 0 1px 3px var(--vera-black-50),
    0 0 15px var(--vera-nixie-color-soft),
    0 0 30px var(--vera-nixie-color-faint);

  svg, .rail-icon {
    filter: drop-shadow(0 0 4px rgba(var(--vera-nixie-glow-rgb), calc(0.8 * var(--vera-nixie-intensity, 1))))
            drop-shadow(0 0 8px rgba(var(--vera-nixie-glow-rgb), calc(0.6 * var(--vera-nixie-intensity, 1))))
            drop-shadow(0 0 12px rgba(var(--vera-nixie-glow-rgb), calc(0.4 * var(--vera-nixie-intensity, 1))));
  }
}

.rail-btn:active {
  transform: scale(0.95);
}

.rail-spacer {
  flex: 1;
  min-height: 20px;
}

// Exit button - themed Nixie styling
.rail-btn.exit-btn {
  margin-top: auto;
  border-color: var(--vera-nixie-exit-color-soft);

  svg {
    color: var(--vera-nixie-exit-color);
    filter: drop-shadow(0 0 3px rgba(var(--vera-nixie-exit-glow-rgb), calc(0.5 * var(--vera-nixie-exit-intensity, 1))))
            drop-shadow(0 0 6px rgba(var(--vera-nixie-exit-glow-rgb), calc(0.3 * var(--vera-nixie-exit-intensity, 1))));
  }

  &:hover {
    box-shadow:
      inset 0 1px 3px var(--vera-black-50),
      0 0 15px var(--vera-nixie-exit-color-soft),
      0 0 30px var(--vera-nixie-exit-color-faint);
    border-color: var(--vera-nixie-exit-color-soft);

    svg {
      filter: drop-shadow(0 0 4px rgba(var(--vera-nixie-exit-glow-rgb), calc(0.8 * var(--vera-nixie-exit-intensity, 1))))
              drop-shadow(0 0 8px rgba(var(--vera-nixie-exit-glow-rgb), calc(0.6 * var(--vera-nixie-exit-intensity, 1))))
              drop-shadow(0 0 14px rgba(var(--vera-nixie-exit-glow-rgb), calc(0.4 * var(--vera-nixie-exit-intensity, 1))));
      animation: powerPulse 0.6s ease-in-out infinite;
    }
  }
}

@keyframes powerPulse {
  0%, 100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.1);
    opacity: 0.8;
  }
}

// Shutdown overlay styles
.shutdown-overlay {
  position: fixed;
  inset: 0;
  background: var(--vera-black-50);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(4px);
}

.shutdown-card {
  background: var(--vera-glass-strong, rgba(10, 20, 36, 0.95));
  border: 1px solid var(--vera-border, var(--vera-accent-20));
  border-radius: 16px;
  padding: 32px 40px;
  min-width: 320px;
  text-align: center;
  box-shadow: 0 20px 50px var(--vera-black-50);
}

.shutdown-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.shutdown-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--vera-text);
}

.shutdown-subtitle {
  font-size: 14px;
  color: var(--vera-text-muted);
}

.shutdown-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 16px;
}

.shutdown-btn {
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  background: linear-gradient(135deg, var(--vera-accent-25), var(--vera-accent-10));
  border: 1px solid var(--vera-accent-40);
  color: var(--vera-text);

  &:hover {
    background: linear-gradient(135deg, var(--vera-accent-35), var(--vera-accent-15));
    box-shadow: 0 0 20px var(--vera-accent-20);
  }
}
</style>
