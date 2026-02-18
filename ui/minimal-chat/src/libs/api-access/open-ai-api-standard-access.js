import { showToast, sleep, parseStreamResponseChunk } from '../utils/general-utils';
import { updateUI } from '../utils/general-utils';
import { messages, localModelKey, streamedMessageText } from '../state-management/state';
import { addMessage } from '../conversation-management/message-processing';

// Constants
const DEFAULT_MAX_TOKENS = 4096;
const DEFAULT_TEMPERATURE = 0.25;
const DEFAULT_TOP_P = 1.0;
const DEFAULT_FREQUENCY_PENALTY = 1.0;
const DEFAULT_PRESENCE_PENALTY = 0.0;
const MAX_RETRY_ATTEMPTS = 3;
const TITLE_MAX_TOKENS = 18;
const DEFAULT_IMAGE_COUNT = 2;
const DEFAULT_IMAGE_SIZE = '256x256';
const FALLBACK_MODELS = [
    { id: 'grok-4-1-fast-reasoning', name: 'grok-4-1-fast-reasoning' },
    { id: 'grok-4-1-fast', name: 'grok-4-1-fast' },
    { id: 'grok-code-fast-1', name: 'grok-code-fast-1' },
    { id: 'grok-3', name: 'grok-3' },
    { id: 'grok-imagine-image', name: 'grok-imagine-image' },
    { id: 'grok-imagine-video', name: 'grok-imagine-video' }
];

// Retry counters
const retryCounters = {
    stream: 0,
    vision: 0,
    imageGen: 0,
    videoGen: 0,
    title: 0
};

// Helper Functions
const createRequestHeaders = (apiKey = localStorage.getItem('localModelKey')) => {
    const headers = {
        'Content-Type': 'application/json'
    };
    if (apiKey) {
        headers.Authorization = `Bearer ${apiKey}`;
    }
    return headers;
};

const createMessagePayload = (messages, model, options = {}) => {
    const basePayload = {
        model,
        messages,
        stream: options.stream || false,
    };
    const extraPayload = options.extraPayload || {};

    const standardPayload = {
        ...basePayload,
        temperature: options.temperature ?? DEFAULT_TEMPERATURE,
        top_p: options.topP ?? parseFloat(localStorage.getItem('top_P') || DEFAULT_TOP_P),
        frequency_penalty: options.frequencyPenalty ?? parseFloat(localStorage.getItem('repetitionPenalty') || DEFAULT_FREQUENCY_PENALTY),
        presence_penalty: options.presencePenalty ?? parseFloat(localStorage.getItem('presencePenalty') || DEFAULT_PRESENCE_PENALTY),
        max_tokens: options.maxTokens ?? DEFAULT_MAX_TOKENS,
        ...extraPayload
    };

    const reasoningPayload = {
        ...basePayload,
        reasoning_effort: "high",
        ...extraPayload
    };

    return model.includes('o1') || model.includes('o3')
        ? reasoningPayload
        : standardPayload;
};

async function handleStreamResponse(response, updateUiFunction, autoScrollToBottom = true) {
    let decodedResult = '';
    const reader = await response.body.getReader();
    const decoder = new TextDecoder('utf-8');

    while (true) {
        const { done, value } = await reader.read();
        if (done) return decodedResult;

        const chunk = decoder.decode(value);
        const parsedLines = parseStreamResponseChunk(chunk);

        for (const { choices: [{ delta: { content } }] } of parsedLines) {
            if (content) {
                decodedResult += content;
                if (updateUiFunction) {
                    updateUI(content, messages.value, addMessage, autoScrollToBottom);
                }
            }
        }
    }
}

async function handleRetry(operation, retryCounter, errorMessage) {
    if (retryCounter < MAX_RETRY_ATTEMPTS) {
        retryCounter++;
        showToast(`${errorMessage} Retrying...Attempt #${retryCounter}`);
        await sleep(1000);
        return true;
    }
    return false;
}

function mergeModelLists(primary, fallback) {
    const entries = [...(primary || []), ...(fallback || [])];
    const seen = new Map();
    for (const model of entries) {
        if (!model || !model.id) {
            continue;
        }
        if (!seen.has(model.id)) {
            seen.set(model.id, { id: model.id, name: model.name || model.id });
        }
    }
    return Array.from(seen.values());
}

// Main Export Functions
export async function fetchLocalModelResponseStream(
    conversation,
    attitude,
    model,
    localModelEndpoint,
    updateUiFunction,
    abortController,
    streamedMessageTextParam,
    autoScrollToBottom = true,
    extraPayload = null
) {
    // Reset streamedMessageText at the start of streaming
    streamedMessageText.value = '';
    
    const tempMessages = conversation.map(({ role, content }) => ({ role, content }));
    const payloadExtra = extraPayload ? { ...extraPayload } : {};
    const isLocalEndpoint = localModelEndpoint === window.location.origin;
    const conversationId = localStorage.getItem('lastConversationId');
    if (isLocalEndpoint && conversationId !== null && payloadExtra.vera_conversation_id === undefined) {
        payloadExtra.vera_conversation_id = String(conversationId);
    }
    const payload = createMessagePayload(tempMessages, model, {
        stream: true,
        temperature: parseFloat(attitude),
        maxTokens: parseInt(localStorage.getItem('maxTokens') || DEFAULT_MAX_TOKENS),
        extraPayload: payloadExtra
    });

    try {
        const response = await fetch(`${localModelEndpoint}/v1/chat/completions`, {
            method: 'POST',
            headers: createRequestHeaders(),
            body: JSON.stringify(payload),
            signal: abortController.signal
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('Local model stream error:', response.status, errorText);
            showToast(`Model request failed (${response.status}).`);
            return;
        }

        const result = await handleStreamResponse(response, updateUiFunction, autoScrollToBottom);
        retryCounters.stream = 0;
        return result;
    } catch (error) {
        if (error.name === 'AbortError') {
            // Abort toast is handled by ChatInput.vue with personality message
            return;
        }
        console.error('Error fetching Custom Model response:', error);
        showToast('Stream Request Failed.');
    }
}

export async function fetchOpenAiLikeVisionResponse(visionMessages, apiKey, model, localModelEndpoint) {
    const payload = createMessagePayload(visionMessages, model);

    try {
        const response = await fetch(`${localModelEndpoint}/v1/chat/completions`, {
            method: 'POST',
            headers: createRequestHeaders(apiKey),
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        retryCounters.vision = 0;
        return data.choices[0].message.content;
    } catch (error) {
        if (await handleRetry(
            () => fetchOpenAiLikeVisionResponse(visionMessages, apiKey, model, localModelEndpoint),
            retryCounters.vision,
            'Failed fetchOpenAiLikeVisionResponse Request.'
        )) {
            return fetchOpenAiLikeVisionResponse(visionMessages, apiKey, model, localModelEndpoint);
        }
    }
}

export async function customModelImageGeneration(conversation, localModelEndpoint, model) {
    try {
        const isXai = localModelEndpoint.includes('api.x.ai') || localModelEndpoint === window.location.origin;
        const size = localStorage.getItem('selectedDallEImageResolution') || DEFAULT_IMAGE_SIZE;
        const n = isXai ? 1 : (parseInt(localStorage.getItem('selectedDallEImageCount')) || DEFAULT_IMAGE_COUNT);
        const payload = isXai ? {
            model,
            prompt: conversation,
            n
        } : {
            model,
            prompt: conversation,
            n,
            size
        };
        const response = await fetch(`${localModelEndpoint}/v1/images/generations`, {
            method: 'POST',
            headers: createRequestHeaders(),
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('Image generation error:', response.status, errorText);
            showToast(`Image generation failed (${response.status}).`);
            return `Image generation failed: ${errorText}`;
        }

        const result = await response.json();

        if (result.data?.length > 0) {
            retryCounters.videoGen = 0;
            return result;
        }
        return "I'm sorry, I couldn't generate an image. The prompt may not be allowed by the API.";
    } catch (error) {
        if (await handleRetry(
            () => customModelImageGeneration(conversation, localModelEndpoint, model),
            retryCounters.imageGen,
            'Failed customModelImageGeneration Request.'
        )) {
            return customModelImageGeneration(conversation, localModelEndpoint, model);
        }
        showToast('Retry Attempts Failed for customModelImageGeneration Request.');
        console.error('Error fetching image generation response:', error);
        return 'An error generating Custom Model Image.';
    }
}

export async function customModelVideoGeneration(conversation, localModelEndpoint, model) {
    try {
        const payload = {
            model,
            prompt: conversation,
            n: 1
        };
        const response = await fetch(`${localModelEndpoint}/v1/videos/generations`, {
            method: 'POST',
            headers: createRequestHeaders(),
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('Video generation error:', response.status, errorText);
            showToast(`Video generation failed (${response.status}).`);
            return `Video generation failed: ${errorText}`;
        }

        const result = await response.json();

        if (result.data?.length > 0) {
            retryCounters.imageGen = 0;
            return result;
        }
        return "I'm sorry, I couldn't generate a video. The prompt may not be allowed by the API.";
    } catch (error) {
        if (await handleRetry(
            () => customModelVideoGeneration(conversation, localModelEndpoint, model),
            retryCounters.videoGen,
            'Failed customModelVideoGeneration Request.'
        )) {
            return customModelVideoGeneration(conversation, localModelEndpoint, model);
        }
        showToast('Retry Attempts Failed for customModelVideoGeneration Request.');
        console.error('Error fetching video generation response:', error);
        return 'An error generating Custom Model Video.';
    }
}

export async function getConversationTitleFromLocalModel(messages, model, localModelEndpoint) {
    try {
        const tempMessages = [...messages, {
            role: 'user',
            content: 'Summarize my inital request or greeting in 5 words or less.'
        }];

        const payload = createMessagePayload(tempMessages, model, {
            stream: true,
            temperature: 0.25,
            maxTokens: TITLE_MAX_TOKENS
        });

        const response = await fetch(`${localModelEndpoint}/v1/chat/completions`, {
            method: 'POST',
            headers: createRequestHeaders(),
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('Local model title error:', response.status, errorText);
            showToast(`Title request failed (${response.status}).`);
            return '';
        }

        const result = await handleStreamResponse(response);
        retryCounters.title = 0;
        return result;
    } catch (error) {
        if (await handleRetry(
            () => getConversationTitleFromLocalModel(messages, model, localModelEndpoint),
            retryCounters.title,
            'Failed to generate conversation title.'
        )) {
            return getConversationTitleFromLocalModel(messages, model, localModelEndpoint);
        }
        console.error('Error fetching Local Model response:', error);
        return 'An error occurred while generating conversation title.';
    }
}

export async function getOpenAICompatibleAvailableModels(localModelEndpoint) {
    try {
        const response = await fetch(`${localModelEndpoint}/v1/models`, {
            method: 'GET',
            headers: createRequestHeaders(localModelKey.value)
        });

        const data = await response.json();

        if (data?.data || Array.isArray(data)) {
            const modelList = data.data || data;
            const mapped = modelList.map(model => ({
                name: model.name || model.id,
                id: model.id
            }));
            return mergeModelLists(mapped, FALLBACK_MODELS);
        }

        throw new Error('Invalid response format');
    } catch (error) {
        showToast('Error fetching models, double check the API endpoint configured');
        console.error('Error fetching available models:', error);
        return mergeModelLists([], FALLBACK_MODELS);
    }
}

/**
 * Non-streaming fetch for simple completions (used for summaries, etc.)
 * @param {Array} messages - The messages to send
 * @param {number} temperature - Temperature setting
 * @param {string} model - Model name
 * @param {string} endpoint - API endpoint
 * @returns {Promise<string>} The response text
 */
export async function fetchOpenAICompatibleResponse(messages, temperature, model, endpoint) {
    try {
        const payload = {
            model: model,
            messages: messages,
            temperature: temperature,
            max_tokens: 1024,
            stream: false
        };
        const isLocalEndpoint = endpoint === window.location.origin;
        const conversationId = localStorage.getItem('lastConversationId');
        if (isLocalEndpoint && conversationId !== null) {
            payload.vera_conversation_id = String(conversationId);
        }

        const response = await fetch(`${endpoint}/v1/chat/completions`, {
            method: 'POST',
            headers: createRequestHeaders(),
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('API error:', response.status, errorText);
            throw new Error(`API request failed: ${response.status}`);
        }

        const data = await response.json();
        return data.choices?.[0]?.message?.content || '';
    } catch (error) {
        console.error('Error in fetchOpenAICompatibleResponse:', error);
        throw error;
    }
}
