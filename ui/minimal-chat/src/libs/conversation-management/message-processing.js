// message-processing.js

import { streamClaudeResponse } from '@/libs/api-access/claude-api-access';
import { showToast } from '@/libs/utils/general-utils';
import { sendBrowserLoadedModelMessage } from '@/libs/api-access/web-llm-access';
import { fetchLocalModelResponseStream, customModelImageGeneration, customModelVideoGeneration } from '../api-access/open-ai-api-standard-access';
import { fetchGPTResponseStream, generateDALLEImage } from '../api-access/gpt-api-access';
import { setSystemPrompt } from './conversations-management';
import {
    systemPrompt,
    messages,
    gptKey,
    pendingQuorumMode,
    pendingQuorumName,
    quorumAutoEnabled,
    swarmAutoEnabled,
    quorumUiMode,
    quorumUiActive,
    thinkingEvents,
    abortController,
    isLoading
} from '../state-management/state';
import { connectThinkingWebSocket, disconnectThinkingWebSocket, clearThinkingEvents } from '../api-access/thinking-websocket';

// Constants for special message prefixes
const IMAGE_PROMPT_PREFIX = 'image::';
const VIDEO_PROMPT_PREFIX = 'video::';
const ADD_IMAGE_TO_CONVERSATION_PREFIX = 'add image to conversation:: done';
const IMAGE_TRIGGER_REGEX = /(create|generate|make|design|draw|render|produce|illustrate)\s+(?:an?\s+)?(image|picture|illustration|artwork|art|logo|icon|poster|banner|cover)\b/i;
const VIDEO_TRIGGER_REGEX = /(create|generate|make|render|produce|animate)\s+(?:an?\s+)?(video|clip|animation|motion|cinematic)\b/i;

const extractMediaPrompt = (messageText) => {
    const trimmed = messageText.trim();
    if (!trimmed) return null;
    if (trimmed.toLowerCase().startsWith(IMAGE_PROMPT_PREFIX)) {
        const prompt = trimmed.slice(IMAGE_PROMPT_PREFIX.length).trim();
        return { prompt, target: 'image' };
    }
    if (trimmed.toLowerCase().startsWith(VIDEO_PROMPT_PREFIX)) {
        const prompt = trimmed.slice(VIDEO_PROMPT_PREFIX.length).trim();
        return { prompt, target: 'video' };
    }
    const match = trimmed.match(IMAGE_TRIGGER_REGEX);
    const videoMatch = match ? null : trimmed.match(VIDEO_TRIGGER_REGEX);
    if (!match && !videoMatch) return null;
    const target = match ? (match[2] || 'image').toLowerCase() : 'video';
    const trigger = match || videoMatch;
    const matchIndex = trigger.index ?? 0;
    const matchLength = trigger[0]?.length || 0;
    const startIndex = matchIndex + matchLength;
    let remainder = trimmed.slice(startIndex).replace(/^(\s*(of|for|showing|that shows|with)\s+)/i, '').trim();
    if (!remainder) {
        return { prompt: '', target };
    }
    if (['logo', 'icon', 'poster', 'banner', 'cover'].includes(target)) {
        remainder = `${target} ${remainder}`.trim();
    }
    return { prompt: remainder, target };
};

/**
 * Sends a message to the selected model and updates the UI.
 *
 * @param {Event} event - The event that triggered the message send (optional).
 * @param {string} userText - The text entered by the user.
 * @param {Array} messages - The array of messages in the conversation.
 * @param {string} selectedModel - The identifier of the selected model.
 * @param {number} claudeSliderValue - The value of the Claude slider (if applicable).
 * @param {number} sliderValue - The value of the general slider (if applicable).
 * @param {string} localModelName - The name of the local model (if applicable).
 * @param {number} localSliderValue - The value of the local model slider (if applicable).
 * @param {string} localModelEndpoint - The endpoint of the local model (if applicable).
 * @param {function} updateUI - A function to update the UI with new messages.
 * @param {function} addMessage - A function to add a new message to the conversation.
 * @param {function} saveMessagesHandler - A function to save the conversation messages.
 * @param {HTMLInputElement} imageInputElement - The file input element for image uploads.
 */
export async function sendMessage(
    event,
    userText,
    messages,
    selectedModel,
    claudeSliderValue,
    sliderValue,
    localModelName,
    localSliderValue,
    localModelEndpoint,
    updateUI,
    addMessage,
    saveMessagesHandler,
    imageInputElement,
    messageContentOverride = null
) {
    try {
        const messageText = userText.trim();

        if (messageText.length === 0) {
            showToast('Please Enter a Prompt First');
            return;
        }

        let manualMode = pendingQuorumMode.value;
        const manualQuorumName = pendingQuorumName.value;
        const supportsQuorum = selectedModel.includes('open-ai-format') || selectedModel.startsWith('grok-');
        if (manualMode && !supportsQuorum) {
            showToast('Quorum/Swarm requires the VERA backend (OpenAI-compatible).');
            manualMode = null;
        }

        const autoMode = swarmAutoEnabled.value
            ? 'swarm'
            : quorumAutoEnabled.value
              ? 'quorum'
              : null;
        const uiMode = supportsQuorum ? manualMode || autoMode : null;
        quorumUiMode.value = uiMode;
        quorumUiActive.value = Boolean(uiMode);

        pendingQuorumMode.value = null;
        pendingQuorumName.value = '';

        const content = messageContentOverride || [{ type: 'text', text: messageText }];
        addMessage('user', content);

        // Reset userText (assuming it's bound to an input field)
        userText = '';

        if (isLoading.value) {
            return;
        }

        isLoading.value = true;

        const mediaPrompt = extractMediaPrompt(messageText);
        if (mediaPrompt) {
            await handleImagePrompt(mediaPrompt.prompt, addMessage, selectedModel, localModelEndpoint, mediaPrompt.target);
            return;
        }

        if (messageText.toLowerCase().startsWith(ADD_IMAGE_TO_CONVERSATION_PREFIX)) {
            await handleVisionPrompt(imageInputElement);
            return;
        }

        if (selectedModel.includes('claude')) {
            await handleClaudeMessage(messageText, messages, selectedModel, claudeSliderValue, updateUI, imageInputElement);
            return;
        }

        if (selectedModel.includes('web-llm')) {
            await handleBrowserModelMessage(messages, updateUI);
            return;
        }

        await handleGPTMessage(
            messages,
            selectedModel,
            sliderValue,
            localModelName,
            localSliderValue,
            localModelEndpoint,
            updateUI,
            manualMode,
            manualQuorumName
        );
    } finally {
        await saveMessagesHandler();
        isLoading.value = false;
        quorumUiActive.value = false;
        quorumUiMode.value = null;
    }
}

/**
 * Handles sending a message to a Claude model.
 *
 * @param {string} messageText - The text of the message.
 * @param {Array} messages - The array of messages in the conversation.
 * @param {string} selectedModel - The identifier of the selected Claude model.
 * @param {number} claudeSliderValue - The value of the Claude slider.
 * @param {function} updateUI - A function to update the UI with new messages.
 * @param {HTMLInputElement} imageInputElement - The file input element for image uploads.
 */
async function handleClaudeMessage(messageText, messages, selectedModel, claudeSliderValue, updateUI, imageInputElement) {
    if (messageText.toLowerCase().startsWith(ADD_IMAGE_TO_CONVERSATION_PREFIX)) {
        isLoading.value = true;
        await handleVisionPrompt(imageInputElement);
        isLoading.value = false;
        return;
    }

    abortController.value = new AbortController();
    await streamClaudeResponse(messages, selectedModel, claudeSliderValue, updateUI, abortController.value);
}

/**
 * Handles sending a message to a GPT model (either OpenAI or local).
 *
 * @param {Array} messages - The array of messages in the conversation.
 * @param {string} selectedModel - The identifier of the selected GPT model.
 * @param {number} sliderValue - The value of the general slider.
 * @param {string} localModelName - The name of the local model (if applicable).
 * @param {number} localSliderValue - The value of the local model slider (if applicable).
 * @param {string} localModelEndpoint - The endpoint of the local model (if applicable).
 * @param {function} updateUI - A function to update the UI with new messages.
 */
async function handleGPTMessage(
    messages,
    selectedModel,
    sliderValue,
    localModelName,
    localSliderValue,
    localModelEndpoint,
    updateUI,
    manualMode,
    manualQuorumName
) {
    try {
        abortController.value = new AbortController();

        const storedModelName = localStorage.getItem('localModelName');
        const fallbackModelName = storedModelName || localModelName || 'grok-4.20-experimental-beta-0304-reasoning';
        const hasOpenAiKey = Boolean(gptKey.value || localStorage.getItem('gptKey'));
        const endpoint = localModelEndpoint || window.location.origin;
        const isOpenAiFormat = selectedModel.includes('open-ai-format');
        const isGrokModel = selectedModel.startsWith('grok-');
        const useLocalBackend = isOpenAiFormat || isGrokModel || (!hasOpenAiKey && endpoint === window.location.origin);
        const effectiveLocalModel = isOpenAiFormat ? fallbackModelName : (isGrokModel ? selectedModel : fallbackModelName);

        if (useLocalBackend) {
            // Prefer stored settings, but fall back to in-memory defaults when storage is empty.
            const storedEndpoint = localStorage.getItem('localModelEndpoint');
            const storedSlider = localStorage.getItem('local-attitude');

            localModelName = effectiveLocalModel;
            localSliderValue = storedSlider ? parseFloat(storedSlider) : (localSliderValue ?? 0.6);
            localModelEndpoint = storedEndpoint || localModelEndpoint || window.location.origin;

            const extraPayload = manualMode === 'quorum'
                ? (manualQuorumName
                    ? { vera_quorum: { quorum_name: manualQuorumName } }
                    : { vera_quorum: true })
                : manualMode === 'swarm'
                    ? (manualQuorumName
                        ? { vera_swarm: { quorum_name: manualQuorumName } }
                        : { vera_swarm: true })
                    : null;

            // Connect to WebSocket for thinking events (VERA backend)
            clearThinkingEvents();
            try {
                await connectThinkingWebSocket();
            } catch (wsError) {
                // WebSocket connection failed, continuing without thinking display
            }

            await fetchLocalModelResponseStream(
                messages,
                localSliderValue,
                localModelName,
                localModelEndpoint,
                updateUI,
                abortController.value,
                null,
                true,
                extraPayload
            );

            // Attach any accumulated thinking events to the last assistant message
            // (fixes race condition where events arrive after first streaming chunk)
            if (thinkingEvents.value.length > 0) {
                const lastMsg = messages.value[messages.value.length - 1];
                if (lastMsg && lastMsg.role === 'assistant') {
                    lastMsg.thinking = [...thinkingEvents.value];
                    clearThinkingEvents();
                }
            }

            // Disconnect WebSocket after response
            disconnectThinkingWebSocket();
        } else {
            await fetchGPTResponseStream(messages, sliderValue, selectedModel, updateUI, abortController.value);
        }
    } catch (error) {
        console.error('Error sending message:', error);
        // Dispatch error event for wing animation
        window.dispatchEvent(new CustomEvent('vera-error', {
            detail: { type: 'api_error', message: error.message }
        }));
        // Clean up WebSocket on error
        disconnectThinkingWebSocket();
    }
}

/**
 * Handles sending a message to a browser-based model.
 *
 * @param {Array} messages - The array of messages in the conversation.
 * @param {function} updateUI - A function to update the UI with new messages.
 */
async function handleBrowserModelMessage(messages, updateUI) {
    await sendBrowserLoadedModelMessage(messages, updateUI);
}

/**
 * Adds a new message to the conversation.
 *
 * @param {string} role - The role of the message sender ('user' or 'assistant').
 * @param {string|Array} content - The content of the message (either a string or an array of content objects).
 * @param {Array} thinkingData - Optional thinking events to attach to the message.
 */
export async function addMessage(role, content, thinkingData = null) {
    setSystemPrompt(messages.value, systemPrompt.value);

    const maxId = messages.value.reduce((max, message) => Math.max(max, message.id), 0);
    const newMessageId = maxId + 1;

    const newMessage = {
        id: newMessageId,
        role,
        content: Array.isArray(content) ? content : [{ type: 'text', text: content }],
    };

    // Attach thinking events to assistant messages
    if (role === 'assistant' && thinkingEvents.value.length > 0) {
        newMessage.thinking = [...thinkingEvents.value];
        clearThinkingEvents();
    } else if (thinkingData) {
        newMessage.thinking = thinkingData;
    }

    messages.value.push(newMessage);
}

/**
 * Triggers a click event on the image input element to open the file selection dialog.
 *
 * @param {HTMLInputElement} imageInputElement - The file input element.
 */
async function handleVisionPrompt(imageInputElement) {
    imageInputElement.click();
}

/**
 * Generates an image using the DALL-E API based on the user's prompt.
 *
 * @param {string} imagePrompt - The prompt for the image generation.
 * @param {function} addMessage - A function to add the generated image URL to the conversation.
 */
async function handleImagePrompt(imagePrompt, addMessage, selectedModel, localModelEndpoint, target = 'image') {
    const promptText = (imagePrompt || '').trim();
    if (!promptText) {
        showToast(`Please add a ${target} description.`);
        return;
    }
    const endpoint = (localModelEndpoint || window.location.origin).trim();
    const useCustom = selectedModel.includes('open-ai-format') || endpoint.includes('api.x.ai') || endpoint === window.location.origin;

    if (target === 'video') {
        if (!useCustom) {
            addMessage('assistant', 'Video generation requires the VERA backend.');
            return;
        }
        const response = await customModelVideoGeneration(
            promptText,
            endpoint,
            localStorage.getItem('video-model') || 'grok-imagine-video'
        );

        if (!response || typeof response === 'string') {
            addMessage('assistant', response || 'Video generation failed.');
            return;
        }
        if (!response.data || response.data.length === 0) {
            addMessage('assistant', 'Video generation returned no results.');
            return;
        }

        let videoURLStrings = `Prompt: ${promptText}\n\n`;
        response.data.forEach((video, idx) => {
            if (!video.url) return;
            videoURLStrings += `[Generated Video ${idx + 1}](${video.url})\n\n`;
            videoURLStrings += `Download path ${idx + 1}: ${video.url}\n\n`;
        });
        addMessage('assistant', videoURLStrings);
        return;
    }

    const response = useCustom
        ? await customModelImageGeneration(
            promptText,
            endpoint,
            localStorage.getItem('image-model') || 'grok-imagine-image'
        )
        : await generateDALLEImage(promptText);

    if (!response || typeof response === 'string') {
        addMessage('assistant', response || 'Image generation failed.');
        return;
    }
    if (!response.data || response.data.length === 0) {
        addMessage('assistant', 'Image generation returned no results.');
        return;
    }

    let imageURLStrings = `Prompt: ${promptText}\n\n`;
    let imageIndex = 0;
    for (const image of response.data) {
        if (!image.url) continue;
        imageIndex += 1;
        imageURLStrings += `![${promptText}](${image.url})\n\n`;
        imageURLStrings += `[Download Image ${imageIndex}](${image.url})\n\n`;
        imageURLStrings += `Download path ${imageIndex}: ${image.url}\n\n`;
    }

    addMessage('assistant', imageURLStrings);
}

/**
 * Handles the click event for uploading a vision image.
 *
 * @param {ref<string>} userText - A Vue ref containing the user's text input.
 * @param {ref<Array>} messages - A Vue ref containing the conversation messages.
 * @param {ref<string>} selectedModel - A Vue ref containing the selected model.
 * @param {ref<number>} claudeSliderValue - A Vue ref containing the Claude slider value.
 * @param {ref<number>} sliderValue - A Vue ref containing the general slider value.
 * @param {ref<string>} localModelName - A Vue ref containing the local model name.
 * @param {ref<number>} localSliderValue - A Vue ref containing the local slider value.
 * @param {ref<string>} localModelEndpoint - A Vue ref containing the local model endpoint.
 * @param {function} updateUIWrapper - A function to update the UI.
 * @param {function} addMessage - A function to add a message to the conversation.
 * @param {function} saveMessagesHandler - A function to save the conversation messages.
 * @param {ref<HTMLInputElement>} imageInput - A Vue ref containing the image input element.
 */
export async function visionimageUploadClick(
    userText,
    messages,
    selectedModel,
    claudeSliderValue,
    sliderValue,
    localModelName,
    localSliderValue,
    localModelEndpoint,
    updateUIWrapper,
    addMessage,
    saveMessagesHandler,
    imageInput
) {
    userText.value = `${ADD_IMAGE_TO_CONVERSATION_PREFIX} ${userText.value}`;
    await sendMessage(
        null,
        userText.value,
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
}
