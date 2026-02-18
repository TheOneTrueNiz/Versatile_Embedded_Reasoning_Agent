<script setup>
import { ref, defineEmits, defineExpose, watch, onBeforeUnmount, computed } from 'vue';
import { SquareArrowUp, ImageUp, CircleStop, Upload, Mic, ArrowDown } from 'lucide-vue-next';
import ToolTip from '@/components/controls/ToolTip.vue';
import VoiceRealtime from '@/components/controls/VoiceRealtime.vue';
import 'swiped-events';
import { swipedLeft, swipedRight, updateUI, showToast, compressImageForUpload } from '@/libs/utils/general-utils';
import {
  isLoading,
  messages,
  selectedModel,
  userText,
  claudeSliderValue,
  sliderValue,
  localModelName,
  localSliderValue,
  localModelEndpoint,
  imageInput,
  pendingImageFile,
  pendingUpload,
  pendingQuorumMode,
  pendingQuorumName,
  abortController,
  isVoiceModeOpen,
  voiceModeStatus,
  voiceModeLevel,
  scrollRequestTimestamp
} from '@/libs/state-management/state';
import { sendMessage, addMessage } from '@/libs/conversation-management/message-processing';
import { disconnectThinkingWebSocket } from '@/libs/api-access/thinking-websocket';
import { extractFileContents } from '@/libs/file-processing/file-processing';
import { saveMessagesHandler } from '@/libs/conversation-management/useConversations';

// Define emits
const emit = defineEmits(['update:userInput', 'abort-stream', 'send-message', 'swipe-left', 'swipe-right', 'vision-prompt', 'upload-context']);
// Local reactive state
const userInputRef = ref(null);
const pendingImagePreviewUrl = ref('');
const voiceLevelStyle = computed(() => {
  const level = Math.min(1, Math.max(0, voiceModeLevel.value || 0));
  return {
    '--voice-level': level.toFixed(3)
  };
});
const pendingQuorumLabel = computed(() => {
  if (pendingQuorumMode.value === 'swarm') {
    return pendingQuorumName.value ? `Swarm · ${pendingQuorumName.value}` : 'Swarm';
  }
  if (pendingQuorumMode.value === 'quorum') {
    return pendingQuorumName.value ? `Quorum · ${pendingQuorumName.value}` : 'Quorum';
  }
  return '';
});
const clearPendingQuorum = () => {
  pendingQuorumMode.value = null;
  pendingQuorumName.value = '';
};
const inputStatusClass = computed(() => {
  if (isLoading.value) {
    return 'loading-border';
  }
  if (voiceModeStatus.value === 'listening') {
    return 'voice-listening-border';
  }
  if (voiceModeStatus.value === 'speaking') {
    return 'voice-speaking-border';
  }
  if (voiceModeStatus.value === 'processing') {
    return 'voice-processing-border';
  }
  if (voiceModeStatus.value === 'connecting') {
    return 'voice-connecting-border';
  }
  return '';
});
const readFileAsDataUrl = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = reject;
  reader.readAsDataURL(file);
});

watch(
  () => pendingImageFile.value,
  (file) => {
    if (pendingImagePreviewUrl.value) {
      URL.revokeObjectURL(pendingImagePreviewUrl.value);
      pendingImagePreviewUrl.value = '';
    }
    if (file) {
      pendingImagePreviewUrl.value = URL.createObjectURL(file);
    }
  }
);

onBeforeUnmount(() => {
  if (pendingImagePreviewUrl.value) {
    URL.revokeObjectURL(pendingImagePreviewUrl.value);
  }
});

// Methods for message handling
async function sendNewMessage() {
  // Note: isLoading is set by message-processing.js sendMessage(), not here
  const messagePrompt = userText.value;
  const trimmedPrompt = messagePrompt.trim();
  userText.value = '';
  autoResize();

  if (pendingImageFile.value) {
    if (!trimmedPrompt) {
      showToast('Add a prompt for the image, then press Send.');
      userText.value = messagePrompt;
      autoResize();
      isLoading.value = false;
      return;
    }
    const stagedImage = pendingImageFile.value;
    let imageUrl = '';
    try {
      imageUrl = await compressImageForUpload(stagedImage);
    } catch (error) {
      console.error('Failed to compress staged image:', error);
      showToast('Failed to process image. Try again.');
      isLoading.value = false;
      return;
    }
    const messageContent = [
      { type: 'image_url', image_url: { url: imageUrl, detail: 'high' } },
      { type: 'text', text: `${trimmedPrompt}\n\nImage: ${stagedImage.name}` }
    ];
    pendingImageFile.value = null;
    await sendMessage(
      event,
      trimmedPrompt,
      messages.value,
      selectedModel.value,
      claudeSliderValue.value,
      sliderValue.value,
      localModelName.value,
      localSliderValue.value,
      localModelEndpoint.value,
      updateUIWrapper,
      addMessage,
      saveMessagesHandler,
      imageInput.value,
      messageContent
    );
    isLoading.value = false;
    return;
  }

  if (pendingUpload.value) {
    if (!trimmedPrompt) {
      showToast('Add a prompt for the upload, then press Send.');
      userText.value = messagePrompt;
      autoResize();
      isLoading.value = false;
      return;
    }
    const stagedFile = pendingUpload.value;
    let contents = '';
    try {
      contents = await extractFileContents(stagedFile.file);
    } catch (error) {
      console.error('Failed to read staged file:', error);
      showToast('Failed to read staged file. Try again.');
      isLoading.value = false;
      return;
    }
    const contextHeader = `#contextAdded: ${stagedFile.name} | `;
    const combinedPrompt = `${trimmedPrompt}\n\n${contextHeader}${contents}`;
    pendingUpload.value = null;
    await sendMessage(
      event,
      combinedPrompt,
      messages.value,
      selectedModel.value,
      claudeSliderValue.value,
      sliderValue.value,
      localModelName.value,
      localSliderValue.value,
      localModelEndpoint.value,
      updateUIWrapper,
      addMessage,
      saveMessagesHandler,
      imageInput.value
    );
    isLoading.value = false;
    return;
  }

  await sendMessage(
    event,
    messagePrompt,
    messages.value,
    selectedModel.value,
    claudeSliderValue.value,
    sliderValue.value,
    localModelName.value,
    localSliderValue.value,
    localModelEndpoint.value,
    updateUIWrapper,
    addMessage,
    saveMessagesHandler,
    imageInput.value
  );

  isLoading.value = false;
}

const clearPendingImage = () => {
  pendingImageFile.value = null;
};

const clearPendingUpload = () => {
  pendingUpload.value = null;
};

function updateUIWrapper(content, autoScrollBottom = true, appendTextValue = true) {
  updateUI(content, messages.value, addMessage, autoScrollBottom, appendTextValue);
}

// Methods for UI interactions
function autoResize() {
  if (!userInputRef.value) return;
  
  if (!userText.value || userText.value.trim() === '') {
    userInputRef.value.style.height = '56px'; // Match the min-height defined in CSS
    return;
  }

  // Temporarily shrink the textarea to get an accurate scrollHeight measurement
  userInputRef.value.style.height = 'auto';
  
  // Set the height based on content with a small padding
  const newHeight = Math.min(userInputRef.value.scrollHeight, 300); // Limit max height to 300px
  userInputRef.value.style.height = `${newHeight}px`;
}

function handleKeyDown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    if (event.ctrlKey) {
      event.preventDefault();
      const cursorPosition = userInputRef.value.selectionStart;
      const text = userText.value;
      userText.value = text.slice(0, cursorPosition) + '\n' + text.slice(cursorPosition);
      userInputRef.value.selectionStart = userInputRef.value.selectionEnd = cursorPosition + 1;
      autoResize();
    } else {
      event.preventDefault(); // Prevent the default Enter behavior
      sendNewMessage();
    }
  }
}

// Methods for handling uploads and aborting streams
async function visionImageUploadClickHandler() {
  const input = imageInput.value || document.getElementById('imageInput');
  if (!input) {
    showToast('Image upload is not ready yet.');
    return;
  }
  input.click();
}

function importFileUploadClick() {
  const input = document.getElementById('fileImportUpload');
  if (input) {
    input.click();
  } else {
    emit('upload-context');
  }
  userText.value = '';
}

// VERA's personality-driven interruption responses
const interruptionResponses = [
  "Oh! Beg your pardon, you had something to add? I'll wait while you gather your thoughts.",
  "Say no more! I'll pause here. What's on your mind?",
  "Stopping mid-thought... I'm all ears now.",
  "Consider me paused. The floor is yours.",
  "Noted! Sometimes less is more. What would you like instead?",
  "Halting my ramble. What did I miss?",
  "Of course! I was getting carried away there, wasn't I?",
  "Pausing... Your turn to steer this ship.",
  "Message received! Taking a breath now.",
  "Understood. I'll stop here and let you redirect.",
  "Interruption acknowledged! What's the new plan?",
  "Holding that thought... What do you need?",
  "Stopped! I appreciate the course correction.",
  "No problem at all. What should we focus on instead?",
  "Taking five. Let me know when you're ready."
];

function getRandomInterruptionResponse() {
  return interruptionResponses[Math.floor(Math.random() * interruptionResponses.length)];
}

async function abortStream() {
  // if (engine !== undefined && selectedModel.value.includes('web-llm')) {
  //   engine.interruptGenerate();
  //   showToast('Aborted response stream');
  //   return;
  // }

  if (abortController.value) {
    // Abort the fetch request
    abortController.value.abort();
    abortController.value = null;

    // Disconnect thinking WebSocket
    disconnectThinkingWebSocket();

    // Reset loading state
    isLoading.value = false;

    // Show VERA's personality-driven interruption message
    showToast(getRandomInterruptionResponse());
  }
}

const toggleVoiceMode = () => {
  isVoiceModeOpen.value = !isVoiceModeOpen.value;
};

const handleCloseVoiceMode = () => {
  isVoiceModeOpen.value = false;
};

const requestScrollToBottom = () => {
  scrollRequestTimestamp.value = Date.now();
};

// Expose sendNewMessage for programmatic triggering (e.g., conversation forking)
defineExpose({
  sendNewMessage
});
</script>

<template>
  <form @submit.prevent="sendNewMessage" id="chat-form" @swiped-left="swipedLeft" @swiped-right="swipedRight"
    data-swipe-threshold="15" data-swipe-unit="vw" data-swipe-timeout="250">
    <div v-if="pendingImageFile || pendingUpload || pendingQuorumMode" class="pending-attachments">
      <div v-if="pendingQuorumMode" class="pending-chip pending-quorum">
        <span class="pending-name">Next message: {{ pendingQuorumLabel }}</span>
        <button class="pending-clear" type="button" @click="clearPendingQuorum">x</button>
      </div>
      <div v-if="pendingImageFile" class="pending-chip">
        <img v-if="pendingImagePreviewUrl" :src="pendingImagePreviewUrl" class="pending-thumb" alt="Staged image preview" />
        <span class="pending-name">{{ pendingImageFile.name }}</span>
        <button class="pending-clear" type="button" @click="clearPendingImage">x</button>
      </div>
      <div v-if="pendingUpload" class="pending-chip">
        <Upload size="14" />
        <span class="pending-name">{{ pendingUpload.name }}</span>
        <button class="pending-clear" type="button" @click="clearPendingUpload">x</button>
      </div>
    </div>
    <div class="input-row">
      <div class="input-container">
        <textarea 
          class="user-input-text" 
          id="user-input" 
          rows="1" 
          v-model="userText" 
          ref="userInputRef"
          :class="inputStatusClass" 
          @input="autoResize" 
          @focus="autoResize" 
          @blur="autoResize"
          @keydown="handleKeyDown" 
          placeholder="Enter a message..."
        ></textarea>
        <div class="icons">
          <ToolTip :targetId="'imageButton'">Upload image for vision processing</ToolTip>
          <div class="image-button" id="imageButton" @click="visionImageUploadClickHandler">
            <ImageUp size="18" />
          </div>
          <ToolTip :targetId="'uploadButton'">Upload file to add contents to conversation</ToolTip>
          <div class="upload-button" id="uploadButton" @click="importFileUploadClick">
            <Upload size="18" />
          </div>
          <div class="send-button" @click="isLoading ? abortStream() : sendNewMessage()">
            <CircleStop class="stop-button" size="18" v-if="isLoading" />
            <SquareArrowUp size="18" v-if="!isLoading" />
          </div>
        </div>
      </div>
      
      <div class="interact-mode-container-group">
        <div class="interact-mode-container scroll-container">
          <ToolTip :targetId="'scrollBottomButton'">Scroll to bottom</ToolTip>
          <div
            class="interact-button"
            id="scrollBottomButton"
            @click="requestScrollToBottom"
          >
            <ArrowDown size="20" />
          </div>
        </div>

        <div class="interact-mode-container voice-container">
          <ToolTip :targetId="'voiceToggleButton'">Voice mode (Grok realtime)</ToolTip>
          <div
            class="interact-button"
            id="voiceToggleButton"
            :class="{
              'voice-active': voiceModeStatus !== 'idle',
              'voice-listening': voiceModeStatus === 'listening',
              'voice-speaking': voiceModeStatus === 'speaking',
              'voice-connecting': voiceModeStatus === 'connecting',
              'voice-processing': voiceModeStatus === 'processing'
            }"
            :style="voiceLevelStyle"
            @click="toggleVoiceMode"
          >
            <Mic size="20" />
          </div>
        </div>
      </div>
    </div>

    <VoiceRealtime v-if="isVoiceModeOpen" @close-voice-mode="handleCloseVoiceMode" />
  </form>

</template>

<style lang="scss" scoped>
$icon-color: var(--vera-icon);
$primary-color: var(--vera-accent);
$primary-hover: var(--vera-accent-strong);
$background-color: var(--vera-input-bar-bg);
$border-color: var(--vera-input-bar-border);

#chat-form {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: min(800px, 80%);
  max-width: 800px;
  margin: 0 auto 16px;
  padding-bottom: calc(6px + env(safe-area-inset-bottom, 0px));
  z-index: 1;
  flex-shrink: 0;
  
  /* For desktop screens */
  @media (min-width: 601px) {
    width: min(800px, 70%);
  }
  
  @media (max-width: 600px) {
    max-width: calc(100% - 16px);
    width: calc(100% - 16px);
    margin: 0 auto 12px;
    padding-bottom: calc(8px + env(safe-area-inset-bottom, 0px));
    gap: 6px;
  }

  .input-row {
    display: flex;
    gap: 10px;
    align-items: center;
    width: 100%;
  }

  .input-container {
    display: flex;
    flex: auto;
    flex-shrink: 2;
    align-items: center;
    position: relative;
    width: 100%;
    border-radius: 14px;
    transition: all 0.2s ease;
    background: var(--vera-input-bar-bg);
    border: 1px solid var(--vera-input-bar-border);
    box-shadow: var(--vera-input-bar-glow);
    --vera-glow-base: var(--vera-input-bar-glow);
    --vera-glow-peak: 0 0 22px var(--vera-effect-glow-color);
    animation: var(--vera-glow-animation);
    animation-delay: var(--vera-glow-delay, 0s);
    backdrop-filter: blur(18px);

    @media (max-width: 600px) {
      width: calc(100% - 110px - 0.5rem);
    }
  }

  .pending-attachments {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 0 12px 6px;
    width: 100%;
    flex-wrap: wrap;
  }

  .pending-chip {
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--vera-panel-alt);
    border: 1px solid var(--vera-glass-border);
    border-radius: 10px;
    padding: 6px 8px;
    font-size: 0.75rem;
    color: var(--vera-text);
    max-width: 100%;
  }

  .pending-quorum {
    border-color: var(--vera-accent-soft);
    box-shadow: var(--vera-glow-soft);
  }

  .pending-thumb {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    object-fit: cover;
  }

  .pending-name {
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .pending-clear {
    background: transparent;
    border: none;
    color: var(--vera-text-muted);
    cursor: pointer;
    font-size: 0.75rem;
    padding: 2px 4px;
  }

  .pending-clear:hover {
    color: var(--vera-text);
  }

  .icons {
    display: flex;
    gap: 10px;
    align-items: center;
    position: absolute;
    right: 16px;
    height: 100%;
    padding-right: 4px;
    z-index: 1;
  }

  .image-button,
  .upload-button,
  .send-button,
  .stop-button,
  .interact-button,
  .voice-button {
    background: var(--vera-btn-bg);
    border: 1px solid transparent;
    backdrop-filter: blur(8px);
    cursor: pointer;
    outline: none;
    color: $icon-color;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    width: 38px;
    height: 38px;
    transition:
      background-color 0.15s ease,
      transform 0.2s ease,
      color 0.2s ease,
      border-color 0.15s ease;

    &:hover {
      transform: scale(1.1);
      color: var(--vera-text);
      background: var(--vera-btn-bg-hover);
      border-color: var(--vera-accent-soft);
    }

    &:active {
      transform: scale(0.95);
    }
  }

  .send-button {
    background-color: var(--vera-send-button-bg, var(--vera-accent));
    color: var(--vera-send-button-text, var(--primary-color-text));
    box-shadow: var(--vera-send-button-glow, none);

    &:hover {
      background-color: var(--vera-send-button-bg, var(--vera-accent-strong));
      color: var(--vera-send-button-text, var(--primary-color-text));
      filter: brightness(1.1);
    }
  }

  .stop-button {
    background: var(--vera-stop-btn-bg);
    color: var(--vera-stop-btn-text);
    border-color: transparent;

    &:hover {
      background: var(--vera-danger);
      filter: brightness(1.15);
      box-shadow: 0 0 12px rgba(var(--vera-error-rgb), 0.4);
    }
  }

  .interact-button {
    position: relative;
    margin-left: unset;
    --voice-level: 0;
  }

  .interact-button::before {
    content: '';
    position: absolute;
    inset: -6px;
    border-radius: 50%;
    border: 1px solid transparent;
    box-shadow: none;
    opacity: 0;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
    pointer-events: none;
  }

  .interact-button.voice-active::before {
    border: 1px solid var(--vera-voice-processing);
    box-shadow: 0 0 calc(6px + var(--voice-level) * 12px) var(--vera-voice-processing-glow);
    opacity: 0.9;
  }

  .interact-button.voice-listening::before {
    animation: voice-wave calc(1.2s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    border-color: var(--vera-voice-listening);
    box-shadow: 0 0 calc(8px + var(--voice-level) * 14px) var(--vera-voice-listening-glow);
    opacity: 1;
  }

  .interact-button.voice-processing::before {
    --voice-pulse-color: var(--vera-voice-processing);
    animation: voice-glow-pulse calc(1.6s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    border-color: var(--vera-voice-processing);
    box-shadow: 0 0 calc(8px + var(--voice-level) * 10px) var(--vera-voice-processing-glow);
    opacity: 1;
  }

  .interact-button.voice-connecting::before {
    --voice-pulse-color: var(--vera-voice-connecting);
    animation: voice-glow-pulse calc(1.6s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    border-color: var(--vera-voice-connecting);
    box-shadow: 0 0 calc(8px + var(--voice-level) * 10px) var(--vera-voice-connecting);
    opacity: 1;
  }

  .interact-button.voice-speaking::before {
    --voice-pulse-color: var(--vera-voice-speaking);
    animation: voice-glow-pulse calc(1.3s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    border-color: var(--vera-voice-speaking);
    box-shadow: 0 0 calc(8px + var(--voice-level) * 10px) var(--vera-voice-speaking-glow);
    opacity: 1;
  }

  .interact-button.voice-listening {
    color: var(--vera-voice-listening-text);
  }

  .interact-button.voice-speaking {
    color: var(--vera-voice-speaking-text);
  }

  .interact-button.voice-connecting,
  .interact-button.voice-processing {
    color: var(--vera-text-muted);
  }

  #user-input {
    flex-grow: 1;
    border: 1px solid $border-color;
    outline: none;
    background: transparent;
    border-radius: 14px;
    font-size: 1.125rem;
    color: var(--vera-text-input);
    font-family: var(--vera-font-input);
    resize: none;
    overflow: hidden;
    white-space: pre-wrap;
    min-height: 56px;
    transition: all 0.25s cubic-bezier(0.25, 1, 0.5, 1);
    transform: translateY(0);
    padding-right: 200px;
    padding-top: 16px;
    padding-left: 20px;
    box-shadow: none;
    
    &:focus {
      border-color: var(--vera-accent);
      box-shadow: 0 0 0 2px var(--vera-accent-faint), var(--vera-input-bar-glow);
      transform: translateY(-2px);
      transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
    }

    &::placeholder {
      color: var(--vera-text-muted);
    }
  }

  textarea {
    transition: 0.2s height ease-in-out;
    font-family: var(--vera-font-input);
    line-height: 1.4;
  }

  .loading-border {
    animation: colorful-pulse calc(4s / var(--vera-anim-speed, 1)) linear infinite;
  }

  .voice-listening-border,
  .voice-speaking-border,
  .voice-processing-border,
  .voice-connecting-border {
    animation: voice-glow calc(2.2s / var(--vera-anim-speed, 1)) ease-in-out infinite;
  }

  .voice-listening-border {
    --voice-glow-color: var(--vera-voice-listening-glow, var(--vera-info-60));
    border-color: var(--voice-glow-color);
    box-shadow: 0 0 8px var(--voice-glow-color);
  }

  .voice-speaking-border {
    --voice-glow-color: var(--vera-voice-speaking-glow, var(--vera-warning-60));
    border-color: var(--voice-glow-color);
    box-shadow: 0 0 8px var(--voice-glow-color);
  }

  .voice-processing-border {
    --voice-glow-color: var(--vera-voice-processing-glow, var(--vera-accent-60));
    border-color: var(--voice-glow-color);
    box-shadow: 0 0 8px var(--voice-glow-color);
  }

  .voice-connecting-border {
    --voice-glow-color: var(--vera-voice-connecting, var(--vera-secondary-60));
    border-color: var(--voice-glow-color);
    box-shadow: 0 0 8px var(--voice-glow-color);
  }

  @keyframes colorful-pulse {
    0% {
      border-color: rgba(var(--vera-accent-rgb), 0.6);
      box-shadow: 0 0 6px rgba(var(--vera-accent-rgb), 0.35);
    }

    20% {
      border-color: rgba(var(--vera-accent-rgb), 0.75);
      box-shadow: 0 0 8px rgba(var(--vera-accent-rgb), 0.5);
    }

    40% {
      border-color: rgba(var(--vera-accent-rgb), 0.9);
      box-shadow: 0 0 10px rgba(var(--vera-accent-rgb), 0.6);
    }

    60% {
      border-color: rgba(var(--vera-accent-rgb), 0.8);
      box-shadow: 0 0 10px rgba(var(--vera-accent-rgb), 0.55);
    }

    80% {
      border-color: rgba(var(--vera-accent-rgb), 0.7);
      box-shadow: 0 0 8px rgba(var(--vera-accent-rgb), 0.45);
    }

    100% {
      border-color: rgba(var(--vera-accent-rgb), 0.6);
      box-shadow: 0 0 6px rgba(var(--vera-accent-rgb), 0.35);
    }
  }

  @keyframes voice-glow {
    0% {
      box-shadow: 0 0 6px var(--voice-glow-color);
    }
    50% {
      box-shadow: 0 0 14px var(--voice-glow-color);
    }
    100% {
      box-shadow: 0 0 6px var(--voice-glow-color);
    }
  }

  @keyframes voice-wave {
    0% {
      border-radius: 50%;
      transform: rotate(0deg) scale(calc(1 + var(--voice-level) * 0.18));
    }
    25% {
      border-radius: 60% 40% 55% 45% / 55% 45% 60% 40%;
      transform: rotate(90deg) scale(calc(1.03 + var(--voice-level) * 0.2));
    }
    50% {
      border-radius: 45% 55% 40% 60% / 60% 40% 55% 45%;
      transform: rotate(180deg) scale(calc(1.06 + var(--voice-level) * 0.22));
    }
    75% {
      border-radius: 55% 45% 60% 40% / 45% 55% 40% 60%;
      transform: rotate(270deg) scale(calc(1.03 + var(--voice-level) * 0.2));
    }
    100% {
      border-radius: 50%;
      transform: rotate(360deg) scale(calc(1 + var(--voice-level) * 0.18));
    }
  }

  @keyframes voice-glow-pulse {
    0% {
      box-shadow: 0 0 6px color-mix(in srgb, var(--voice-pulse-color, var(--vera-accent)) 45%, transparent);
      opacity: 0.8;
    }
    50% {
      box-shadow: 0 0 14px color-mix(in srgb, var(--voice-pulse-color, var(--vera-accent)) 80%, transparent);
      opacity: 1;
    }
    100% {
      box-shadow: 0 0 6px color-mix(in srgb, var(--voice-pulse-color, var(--vera-accent)) 45%, transparent);
      opacity: 0.8;
    }
  }
}

.interact-mode-container-group {
  display: flex;
  gap: 10px;
  flex-shrink: 0;

  @media (max-width: 600px) {
    gap: 6px;
  }
}

.interact-mode-container {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  height: 56px;
  width: 56px;
  border: 1px solid var(--vera-glass-border);
  background: var(--vera-glass-bg);
  box-shadow: var(--vera-glow-soft);
  backdrop-filter: blur(18px);
  transition: all 0.2s ease;
  
  &:hover {
    border-color: rgba(var(--vera-accent-rgb), 0.6);
    box-shadow: 0 4px 16px rgba(var(--vera-shadow-rgb), 0.3);
  }

  @media (max-width: 600px) {
    width: 44px;
    height: 44px;
    border-radius: 12px;
  }
}

.interact-toggle-button {
  position: fixed;
  bottom: 10px;
  right: 10px;
  z-index: 1;
  padding: 10px 20px;
  background-color: $primary-color;
  color: var(--primary-color-text);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(var(--vera-shadow-rgb), 0.3);
  transition: all 0.2s ease;
  
  &:hover {
    background-color: $primary-hover;
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(var(--vera-shadow-rgb), 0.4);
  }
  
  &:active {
    transform: translateY(0);
  }
}
</style>
