<!-- MessageItem.vue -->
<script setup>
import { computed, onMounted, ref, toRef } from 'vue';
import { RefreshCcw, Trash, Copy, Pencil, Link, Bot, Brain, Sparkles, User, ChevronDown } from 'lucide-vue-next';
import ToolTip from '@/components/controls/ToolTip.vue';
import { showToast } from '@/libs/utils/general-utils';
import {
    isLoading,
    messages,
    systemPrompt,
    selectedModel,
    sliderValue,
    localModelName,
    localSliderValue,
    localModelEndpoint,
    conversations,
    abortController,
    streamedMessageText,
    selectedConversation,
    modelDisplayName,
    higherContrastMessages,
    isAvatarEnabled,
    avatarUrl,
    userAvatarUrl,
    avatarShape,
    browserModelSelection,
    // Avatar customization
    showStatusIndicator,
    userStatus,
    aiAvatarPreset,
    userAvatarPreset,
    avatarDefaultStyle,
    avatarPosition,
} from '@/libs/state-management/state';
import {
    setSystemPrompt,
    regenerateMessageResponse,
    editPreviousMessage,
    deleteMessageFromHistory,
} from '@/libs/conversation-management/conversations-management';
import { updateUIWrapper } from '@/libs/utils/general-utils';
import { saveMessagesHandler } from '@/libs/conversation-management/useConversations';
import 'swiped-events';
import hljs from 'highlight.js/lib/core';
import { FileCheck2 } from 'lucide-vue-next';

import 'highlight.js/styles/github-dark.css';
import MarkdownIt from 'markdown-it';
import Avatar from 'primevue/avatar';

import c from 'highlight.js/lib/languages/c';
import javascript from 'highlight.js/lib/languages/javascript';
import python from 'highlight.js/lib/languages/python';
import java from 'highlight.js/lib/languages/java';
import cpp from 'highlight.js/lib/languages/cpp';
import csharp from 'highlight.js/lib/languages/csharp';
import php from 'highlight.js/lib/languages/php';
import ruby from 'highlight.js/lib/languages/ruby';
import swift from 'highlight.js/lib/languages/swift';
import go from 'highlight.js/lib/languages/go';
import rust from 'highlight.js/lib/languages/rust';
import typescript from 'highlight.js/lib/languages/typescript';
import kotlin from 'highlight.js/lib/languages/kotlin';
import scala from 'highlight.js/lib/languages/scala';
import html from 'highlight.js/lib/languages/xml';
import css from 'highlight.js/lib/languages/css';
import sql from 'highlight.js/lib/languages/sql';
import bash from 'highlight.js/lib/languages/bash';
import powershell from 'highlight.js/lib/languages/powershell';

hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('python', python);
hljs.registerLanguage('java', java);
hljs.registerLanguage('c', c);
hljs.registerLanguage('cpp', cpp);
hljs.registerLanguage('csharp', csharp);
hljs.registerLanguage('php', php);
hljs.registerLanguage('ruby', ruby);
hljs.registerLanguage('swift', swift);
hljs.registerLanguage('go', go);
hljs.registerLanguage('rust', rust);
hljs.registerLanguage('typescript', typescript);
hljs.registerLanguage('kotlin', kotlin);
hljs.registerLanguage('scala', scala);
hljs.registerLanguage('html', html);
hljs.registerLanguage('css', css);
hljs.registerLanguage('sql', sql);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('powershell', powershell);

// Props
const props = defineProps({
    item: {
        type: Object,
        required: true,
    },
    active: {
        type: Boolean,
        default: false,
    },
});

// Refs
const loadingIcon = ref(-1);
const imageTextRef = ref('');
const thinkingCollapsed = ref(true); // Start collapsed

// Check if message has thinking data
const hasThinking = computed(() => {
    return props.item?.thinking && props.item.thinking.length > 0;
});

// Get thinking event icon
function getThinkingIcon(eventType) {
    const iconMap = {
        analyzing: '\u{1F50D}',
        routing: '\u{1F500}',
        memory: '\u{1F4BE}',
        tool: '\u{1F527}',
        reasoning: '\u{1F4AD}',
        decision: '\u{2705}',
        quorum: '\u{1F465}',
        error: '\u{26A0}'
    };
    return iconMap[eventType] || '\u{2022}';
}

// Memoization function to avoid redundant calculations
const memoize = (fn) => {
    const cache = new Map();
    return (...args) => {
        const key = JSON.stringify(args);
        if (cache.has(key)) return cache.get(key);
        const result = fn(...args);
        cache.set(key, result);
        return result;
    };
};

// Optimized content checking functions
const checkForTextFile = memoize((content) => {
    if (!content || !Array.isArray(content)) return false;
    return content[0]?.text?.indexOf('#contextAdded:') !== -1;
});

const checkForImagePart = memoize((content) => {
    if (!content || !Array.isArray(content)) return false;
    for (let i = 0; i < content.length; i++) {
        if (content[i].type === 'image_url' && content[i].image_url) {
            return true;
        }
    }
    return false;
});

const checkForImageUrl = memoize((content) => {
    if (!content || !Array.isArray(content)) return false;
    for (let i = 0; i < content.length; i++) {
        if (content[i].type === 'image_url' && content[i].image_url && content[i].image_url.url) {
            return true;
        }
    }
    return false;
});

// Computed properties for file detection - now using memoized helper functions
const hasFile = computed(() => {
    // Only true if it's a non-image file (has #contextAdded and doesn't have image_url)
    if (!props.item?.content) return false;
    return checkForTextFile(props.item.content) && !checkForImagePart(props.item.content);
});

const hasImage = computed(() => {
    if (!props.item?.content) return false;
    return checkForImageUrl(props.item.content);
});

const hasImageName = computed(() => {
    if (!props.item?.content || !Array.isArray(props.item.content)) return false;
    const textContent = getTextContent(props.item.content);
    return textContent && textContent.match(/Image:\s*([^\n]+)/);
});

// Helper function to get text content from message
function getTextContent(content) {
    if (!Array.isArray(content)) return '';
    const textPart = content.find(part => part.type === 'text' && part.text);
    return textPart ? textPart.text : '';
}

// Utility functions
function messageClass(role) {
    higherContrastMessages.value = JSON.parse(localStorage.getItem("higherContrastMessages") || false);
    return role === 'user' ? 'user message' + (higherContrastMessages.value === true ? ' high-constrast-mode' : '') : 'gpt message' + (higherContrastMessages.value === true ? ' high-constrast-mode' : '');
}

function copyText(message) {
    let textToCopy = '';

    if (Array.isArray(message)) {
        textToCopy = message
            .filter(item => item.text)
            .map(item => item.text)
            .join(' ');
    } else {
        textToCopy = message || '';
    }

    navigator.clipboard
        .writeText(textToCopy)
        .then(() => {
            showToast('Copied text!');
            console.log('Content copied to clipboard');
        })
        .catch((error) => {
            console.error('Failed to copy content: ', error);
        });
}

function startLoading(id) {
    loadingIcon.value = id;
}

// Message editing
let initialMessage = '';
const isEditing = ref(false);
const emit = defineEmits(['update:isEditing']);

function editMessage(message) {
    if (message.role !== 'user' || isEditing.value) return;
    isEditing.value = true;
    initialMessage = message;
}

async function saveEditedMessage(message, event) {
    isEditing.value = false;
    message.isEditing = false;

    let parsedMessageText = '';

    if (Array.isArray(initialMessage.content)) {
        parsedMessageText = initialMessage.content
            .filter(item => item.text)
            .map(item => item.text)
            .join(' ');
    } else {
        parsedMessageText = message.text || '';
    }

    const updatedContent = event.target.innerText.trim();
    if (updatedContent !== parsedMessageText.trim()) {
        isLoading.value = true;
        setSystemPrompt(messages.value, systemPrompt.value);

        const result = await editPreviousMessage(
            conversations.value,
            messages,
            initialMessage,
            updatedContent,
            sliderValue.value,
            selectedModel.value,
            localSliderValue.value,
            localModelName.value,
            localModelEndpoint.value,
            updateUIWrapper,
            abortController,
            streamedMessageText
        );

        messages.value = result.baseMessages;
        selectedConversation.value.messageHistory = messages.value;
        isLoading.value = false;
        saveMessagesHandler();
    }
}

// Message actions
async function regenerateMessage(content) {
    isLoading.value = true;
    setSystemPrompt(messages.value, systemPrompt.value);

    const result = await regenerateMessageResponse(
        conversations.value,
        messages,
        content,
        sliderValue.value,
        selectedModel.value,
        localSliderValue.value,
        localModelName.value,
        localModelEndpoint.value,
        updateUIWrapper,
        abortController,
        streamedMessageText
    );

    isLoading.value = false;
    messages.value = result.baseMessages;
    selectedConversation.value.messageHistory = messages.value;
    saveMessagesHandler();
}

async function deleteMessage(content) {
    messages.value = deleteMessageFromHistory(messages.value, content);
    saveMessagesHandler();
}

const VIDEO_EXTENSIONS = new Set(['mp4', 'webm', 'mov', 'm4v', 'avi', 'mkv']);
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'avif']);
const VIDEO_URL_HINTS = [
    'vidgen.x.ai',
    '/xai-vidgen',
    'xai-video-',
    'grok-imagine-video',
    'generated video',
    'video url'
];
const IMAGE_URL_HINTS = [
    'imgen.x.ai',
    '/xai-imgen',
    'xai-tmp-imgen-',
    'grok-imagine-image',
    'generated image',
    'image url',
    'download image'
];
const URL_REGEX = /https?:\/\/[^\s<>()`"']+/gi;

const md = new MarkdownIt({
    breaks: true,
    linkify: true,
    highlight: (str, lang) => {
        if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(str, { language: lang }).value;
        }
        return hljs.highlightAuto(str).value;
    },
});

function escapeHtmlAttribute(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function escapeHtmlText(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function normalizeMediaUrl(url) {
    let normalized = String(url || '').trim();
    if (!normalized) return '';
    normalized = normalized.replace(/^`+|`+$/g, '');
    normalized = normalized.replace(/^[<([{"']+/, '');
    normalized = normalized.replace(/[>\])}"',.;:!?]+$/g, '');
    return normalized.trim();
}

function extractUrlsFromText(text) {
    if (!text || typeof text !== 'string') return [];
    const matches = text.match(URL_REGEX);
    if (!matches) return [];
    const unique = new Set();
    matches.forEach((entry) => {
        const normalized = normalizeMediaUrl(entry);
        if (normalized) unique.add(normalized);
    });
    return Array.from(unique);
}

function getPathnameFromUrl(url) {
    const normalizedUrl = normalizeMediaUrl(url);
    if (!normalizedUrl) return '';
    try {
        const parsed = new URL(normalizedUrl, window.location.origin);
        return parsed.pathname || '';
    } catch {
        return normalizedUrl;
    }
}

function getMediaTypeFromUrl(url, contextText = '') {
    const normalizedUrl = normalizeMediaUrl(url);
    if (!normalizedUrl) return null;

    const pathname = getPathnameFromUrl(url);
    const segment = pathname.split('/').pop() || '';
    const ext = segment.includes('.') ? segment.split('.').pop().toLowerCase() : '';
    if (VIDEO_EXTENSIONS.has(ext)) return 'video';
    if (IMAGE_EXTENSIONS.has(ext)) return 'image';

    const haystack = `${normalizedUrl} ${contextText || ''}`.toLowerCase();
    if (VIDEO_URL_HINTS.some((hint) => haystack.includes(hint))) return 'video';
    if (IMAGE_URL_HINTS.some((hint) => haystack.includes(hint))) return 'image';

    return null;
}

function getDownloadFileName(url, mediaType = 'media') {
    const normalizedUrl = normalizeMediaUrl(url);
    const pathname = getPathnameFromUrl(url);
    const segment = (pathname.split('/').pop() || '').trim();
    if (segment) {
        if (!segment.includes('.') && mediaType === 'video') {
            return `${segment}.mp4`;
        }
        if (!segment.includes('.') && mediaType === 'image') {
            return `${segment}.png`;
        }
        return segment;
    }
    if (normalizedUrl) {
        const fallbackId = normalizedUrl.split('/').pop() || '';
        if (fallbackId) return fallbackId;
    }
    return mediaType === 'video' ? 'generated-video.mp4' : 'generated-image.png';
}

function createMediaCardMarkup(url, mediaType, index = 1) {
    const normalizedUrl = normalizeMediaUrl(url);
    const escapedUrl = escapeHtmlAttribute(normalizedUrl);
    const escapedPath = escapeHtmlText(normalizedUrl);
    const fileName = escapeHtmlAttribute(getDownloadFileName(url, mediaType));
    const isVideo = mediaType === 'video';
    const label = isVideo ? 'Video' : 'Image';
    const mediaElement = isVideo
        ? `<video class="generated-media generated-video" controls preload="metadata" src="${escapedUrl}"></video>`
        : `<img class="generated-media generated-image" src="${escapedUrl}" alt="Generated ${label} ${index}" loading="lazy" decoding="async" />`;

    return `
        <div class="generated-media-card ${isVideo ? 'video-card' : 'image-card'}">
            ${mediaElement}
            <div class="generated-media-actions">
                <button type="button"
                    class="media-download-button"
                    data-download-url="${escapedUrl}"
                    data-download-filename="${fileName}"
                    data-media-type="${isVideo ? 'video' : 'image'}">
                    Download ${label}
                </button>
                <a class="media-open-link" href="${escapedUrl}" target="_blank" rel="noopener noreferrer">
                    Open
                </a>
            </div>
            <div class="generated-media-path">Download path: <span class="path-value">${escapedPath}</span></div>
        </div>
    `.trim();
}

function replaceNodeWithMediaCard(node, mediaUrl, mediaType, index, documentRef) {
    const wrapper = documentRef.createElement('div');
    wrapper.innerHTML = createMediaCardMarkup(mediaUrl, mediaType, index);
    const card = wrapper.firstElementChild;
    if (!card) return;

    const parent = node.parentElement;
    if (parent && parent.tagName.toLowerCase() === 'p' && parent.childNodes.length === 1) {
        parent.replaceWith(card);
    } else {
        node.replaceWith(card);
    }
}

function enhanceRenderedMedia(renderedHtml) {
    if (!renderedHtml || typeof window === 'undefined' || typeof DOMParser === 'undefined') {
        return renderedHtml;
    }

    const parser = new DOMParser();
    const documentRef = parser.parseFromString(`<div class="media-render-root">${renderedHtml}</div>`, 'text/html');
    const root = documentRef.body.firstElementChild;
    if (!root) return renderedHtml;

    let imageIndex = 0;
    let videoIndex = 0;

    const links = Array.from(root.querySelectorAll('a[href]'));
    links.forEach((link) => {
        if (link.closest('.generated-media-card')) return;
        const href = link.getAttribute('href') || '';
        const mediaType = getMediaTypeFromUrl(href, `${link.textContent || ''} ${link.getAttribute('title') || ''}`);
        if (!mediaType) return;

        if (mediaType === 'video') {
            videoIndex += 1;
            replaceNodeWithMediaCard(link, href, mediaType, videoIndex, documentRef);
            return;
        }

        imageIndex += 1;
        replaceNodeWithMediaCard(link, href, mediaType, imageIndex, documentRef);
    });

    const images = Array.from(root.querySelectorAll('img'));
    images.forEach((img) => {
        if (img.closest('.generated-media-card')) return;
        const src = img.getAttribute('src') || '';
        if (!src) return;
        imageIndex += 1;
        replaceNodeWithMediaCard(img, src, 'image', imageIndex, documentRef);
    });

    const codeBlocks = Array.from(root.querySelectorAll('code'));
    codeBlocks.forEach((codeBlock) => {
        if (codeBlock.closest('.generated-media-card')) return;
        const urls = extractUrlsFromText(codeBlock.textContent || '');
        if (urls.length === 0) return;

        const mediaUrl = urls[0];
        const mediaType = getMediaTypeFromUrl(mediaUrl, codeBlock.parentElement?.textContent || '');
        if (!mediaType) return;

        if (mediaType === 'video') {
            videoIndex += 1;
            replaceNodeWithMediaCard(codeBlock, mediaUrl, mediaType, videoIndex, documentRef);
        } else {
            imageIndex += 1;
            replaceNodeWithMediaCard(codeBlock, mediaUrl, mediaType, imageIndex, documentRef);
        }
    });

    const plainTextBlocks = Array.from(root.querySelectorAll('p, li'));
    plainTextBlocks.forEach((block) => {
        if (block.closest('.generated-media-card')) return;
        if (block.querySelector('a, img, video, code')) return;

        const rawText = block.textContent || '';
        const urls = extractUrlsFromText(rawText);
        if (urls.length === 0) return;

        const cards = [];
        urls.forEach((mediaUrl) => {
            const mediaType = getMediaTypeFromUrl(mediaUrl, rawText);
            if (!mediaType) return;
            if (mediaType === 'video') {
                videoIndex += 1;
                cards.push(createMediaCardMarkup(mediaUrl, mediaType, videoIndex));
            } else {
                imageIndex += 1;
                cards.push(createMediaCardMarkup(mediaUrl, mediaType, imageIndex));
            }
        });

        if (cards.length === 0) return;
        const wrapper = documentRef.createElement('div');
        wrapper.className = 'generated-media-stack';
        wrapper.innerHTML = cards.join('');
        block.after(wrapper);
    });

    return root.innerHTML;
}

function formatMessage(content) {
    let combinedContent = '';
    let imageUrl = null;

    if (Array.isArray(content)) {
        // First extract image URL and name if present
        for (const item of content) {
            if (item.type === 'image_url' && item.image_url && item.image_url.url) {
                imageUrl = item.image_url.url;
                
                // Extract image name if present in text part
                const textItem = content.find(i => i.type === 'text' && i.text);
                if (textItem && textItem.text) {
                    const imgMatch = textItem.text.match(/Image:\s*([^\n]+)/);
                    if (imgMatch && imgMatch[1]) {
                        // Store image file name for later reference
                        imageTextRef.value = imgMatch[1].trim();
                    }
                }
            }
        }
        
        // Then process text content, removing image filename references
        const textParts = content
            .filter(item => item.type === 'text' && item.text)
            .map(item => item.text.replace(/\n\nImage:\s*[^\n]+/g, ''))
            .join(' ').trim();
            
        // Then combine text with image markdown
        if (imageUrl) {
            combinedContent = textParts + `\n\n![image](${imageUrl})`;
        } else {
            combinedContent = textParts;
        }
    } else {
        combinedContent = content;
    }

    const rendered = md.render(combinedContent);
    return enhanceRenderedMedia(rendered);
}

async function downloadMediaAsset(mediaUrl, desiredFileName, mediaType = 'media') {
    const fileName = desiredFileName || getDownloadFileName(mediaUrl, mediaType);
    try {
        const response = await fetch(mediaUrl, { mode: 'cors' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = objectUrl;
        anchor.download = fileName;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(objectUrl);
        showToast(`${mediaType === 'video' ? 'Video' : 'Image'} downloaded.`);
        return;
    } catch (error) {
        console.warn('Direct media download failed; falling back to open link.', error);
    }

    const fallbackAnchor = document.createElement('a');
    fallbackAnchor.href = mediaUrl;
    fallbackAnchor.target = '_blank';
    fallbackAnchor.rel = 'noopener noreferrer';
    fallbackAnchor.download = fileName;
    document.body.appendChild(fallbackAnchor);
    fallbackAnchor.click();
    fallbackAnchor.remove();
    showToast('Opened media link. Use Save As if download is blocked.');
}

function handleMessageContentClick(event) {
    const target = event?.target?.closest?.('.media-download-button');
    if (!target) return;
    event.preventDefault();
    event.stopPropagation();

    const mediaUrl = target.getAttribute('data-download-url');
    if (!mediaUrl) {
        showToast('Missing media URL.');
        return;
    }

    const fileName = target.getAttribute('data-download-filename') || '';
    const mediaType = target.getAttribute('data-media-type') || 'media';
    void downloadMediaAsset(mediaUrl, fileName, mediaType);
}

const menu = ref(null);

// Extract file name from the message content
function extractFileName(text) {
    if (!text || typeof text !== 'string') return 'Unknown File';
    
    // Check if the message contains the contextAdded marker (for non-image files)
    if (text.indexOf('#contextAdded:') !== -1) {
        // Extract the filename between the marker and the pipe symbol
        const match = text.match(/#contextAdded:\s*(.*?)\s*\|/);
        return match && match[1] ? match[1].trim() : 'File';
    }
    
    // For image files, look for the Image: pattern
    const imgMatch = text.match(/Image:\s*([^\n]+)/);
    if (imgMatch && imgMatch[1]) {
        return imgMatch[1].trim();
    }
    
    return 'File';
}

const menuItems = computed(() => {
    if (!props.item) return [];

    return [
        {
            label: 'Regenerate',
            icon: 'pi pi-refresh',
            command: () => {
                regenerateMessage(props.item.content);
                startLoading(props.item.id);
            },
            visible: props.item.role === 'user'
        },
        {
            label: 'Edit',
            icon: 'pi pi-pencil',
            command: () => editMessage(props.item),
            visible: props.item.role === 'user'
        },
        {
            label: 'Copy',
            icon: 'pi pi-copy',
            command: () => copyText(props.item.content),
            visible: true
        },
        {
            label: 'Remove',
            icon: 'pi pi-trash',
            command: () => {
                deleteMessage(props.item.content);
                startLoading(props.item.id);
            },
            visible: props.item.role === 'user'
        }
    ];
});

</script>

<template>
    <transition 
        name="message-fade"
        appear
        v-bind="item.role === 'user' ? { 'enter-from-class': 'message-slide-right' } : { 'enter-from-class': 'message-slide-left' }"
    >
        <div v-ripple="{
            pt: {
                root: { style: 'background: var(--vera-accent-soft);' }
            }
        }" class="p-ripple box message-container" v-if="active" :class="[messageClass(item.role), `avatar-${avatarPosition}`]">
            <!-- Avatar for "beside" layout - placed outside header -->
            <div v-if="isAvatarEnabled && avatarPosition === 'beside'" class="avatar-wrapper avatar-beside" :class="avatarShape">
                <!-- User avatar with custom image -->
                <Avatar
                    v-if="item.role === 'user' && userAvatarUrl"
                    :image="userAvatarUrl"
                    :shape="avatarShape === 'circle' ? 'circle' : 'square'"
                    class="avatar-animate" />
                <!-- User avatar fallback preset icons -->
                <div v-else-if="item.role === 'user'" class="avatar-icon-fallback user-preset" :class="[avatarShape, userAvatarPreset]">
                    <Bot v-if="userAvatarPreset === 'robot'" :size="20" />
                    <Brain v-else-if="userAvatarPreset === 'brain'" :size="20" />
                    <Sparkles v-else-if="userAvatarPreset === 'spark'" :size="20" />
                    <User v-else :size="20" />
                </div>
                <!-- AI avatar with custom image -->
                <Avatar
                    v-else-if="avatarUrl"
                    :image="avatarUrl"
                    :shape="avatarShape === 'circle' ? 'circle' : 'square'"
                    class="avatar-animate" />
                <!-- AI avatar preset icons -->
                <div v-else class="avatar-icon-fallback ai-preset" :class="[avatarShape, aiAvatarPreset]">
                    <Bot v-if="aiAvatarPreset === 'robot'" :size="20" />
                    <Brain v-else-if="aiAvatarPreset === 'brain'" :size="20" />
                    <Sparkles v-else-if="aiAvatarPreset === 'spark'" :size="20" />
                    <Bot v-else :size="20" />
                </div>
                <span
                    v-if="showStatusIndicator && item.role === 'user'"
                    class="avatar-status"
                    :class="userStatus"
                ></span>
            </div>

            <div class="message-body">
                <div class="message-header">
                    <div class="message-header-content">
                        <!-- Avatar for "above" layout - inside header -->
                        <div v-if="isAvatarEnabled && avatarPosition === 'above'" class="avatar-wrapper" :class="avatarShape">
                            <!-- User avatar with custom image -->
                            <Avatar
                                v-if="item.role === 'user' && userAvatarUrl"
                                :image="userAvatarUrl"
                                :shape="avatarShape === 'circle' ? 'circle' : 'square'"
                                class="avatar-animate" />
                            <!-- User avatar fallback preset icons -->
                            <div v-else-if="item.role === 'user'" class="avatar-icon-fallback user-preset" :class="[avatarShape, userAvatarPreset]">
                                <Bot v-if="userAvatarPreset === 'robot'" :size="20" />
                                <Brain v-else-if="userAvatarPreset === 'brain'" :size="20" />
                                <Sparkles v-else-if="userAvatarPreset === 'spark'" :size="20" />
                                <User v-else :size="20" />
                            </div>
                            <!-- AI avatar with custom image -->
                            <Avatar
                                v-else-if="avatarUrl"
                                :image="avatarUrl"
                                :shape="avatarShape === 'circle' ? 'circle' : 'square'"
                                class="avatar-animate" />
                            <!-- AI avatar preset icons -->
                            <div v-else class="avatar-icon-fallback ai-preset" :class="[avatarShape, aiAvatarPreset]">
                                <Bot v-if="aiAvatarPreset === 'robot'" :size="20" />
                                <Brain v-else-if="aiAvatarPreset === 'brain'" :size="20" />
                                <Sparkles v-else-if="aiAvatarPreset === 'spark'" :size="20" />
                                <Bot v-else :size="20" />
                            </div>
                            <span
                                v-if="showStatusIndicator && item.role === 'user'"
                                class="avatar-status"
                                :class="userStatus"
                            ></span>
                        </div>

                        <div class="label" @click="copyText(item.content)" :id="'message-label-' + item.id">
                            {{ item.role === 'user' ? '' : selectedModel === 'web-llm' ? browserModelSelection.replaceAll('"', '') :
                            localModelName }}
                        </div>
                    </div>
                
                <div class="action-buttons-row" v-if="item.role === 'user'">
                    <button class="action-button" @click="editMessage(item)" title="Edit">
                        <Pencil size="16" />
                    </button>
                    <button class="action-button" @click="copyText(item.content)" title="Copy">
                        <Copy size="16" />
                    </button>
                    <button class="action-button" @click="regenerateMessage(item.content)" title="Regenerate">
                        <RefreshCcw size="16" />
                    </button>
                    <button class="action-button" @click="deleteMessage(item.content)" title="Delete">
                        <Trash size="16" />
                    </button>
                </div>
                <ContextMenu v-if="item" ref="menu" :model="menuItems" :id="'message-menu-' + item.id" />
                <ToolTip :targetId="'message-label-' + item.id">Copy message</ToolTip>
            </div>

            <!-- Thinking section for assistant messages -->
            <div v-if="hasThinking && item.role !== 'user'" class="thinking-section">
                <div class="thinking-header" @click="thinkingCollapsed = !thinkingCollapsed">
                    <div class="thinking-title">
                        <Brain :size="14" class="thinking-icon" />
                        <span>Thinking</span>
                        <span class="event-count">({{ item.thinking.length }})</span>
                    </div>
                    <ChevronDown :size="14" class="collapse-icon" :class="{ collapsed: thinkingCollapsed }" />
                </div>
                <transition name="thinking-expand">
                    <div v-show="!thinkingCollapsed" class="thinking-content">
                        <div v-for="(event, idx) in item.thinking" :key="idx" class="thinking-event" :class="'event-' + event.event_type">
                            <span class="event-icon">{{ getThinkingIcon(event.event_type) }}</span>
                            <span class="event-message">{{ event.message }}</span>
                        </div>
                    </div>
                </transition>
            </div>

            <!-- Regular text messages -->
            <div class="message-contents" :id="'message-' + item.id"
                v-show="!hasFile && !hasImage"
                :contenteditable="isEditing" @dblclick="editMessage(item)" @blur="saveEditedMessage(item, $event)"
                @click="handleMessageContentClick"
                v-html="formatMessage(item.content)">
            </div>
            
            <!-- Non-image file messages -->
            <div class="message-contents file-content" :id="'message-' + item.id"
                v-show="hasFile" :contenteditable="isEditing"
                @dblclick="editMessage(item)" @blur="saveEditedMessage(item, $event)" @click="handleMessageContentClick">
                <div class="file-info-display">
                    <Link class="file-icon" size="18" />
                    <span class="file-name">{{ extractFileName(item?.content[0]?.text) }}</span>
                </div>
            </div>
            
            <!-- Image messages -->
            <div class="message-contents" :id="'message-' + item.id"
                v-show="hasImage" :contenteditable="isEditing"
                @dblclick="editMessage(item)" @blur="saveEditedMessage(item, $event)" @click="handleMessageContentClick">
                <div class="file-info-display image-info" v-if="hasImageName">
                    <FileCheck2 class="file-icon" size="18" />
                    <span class="file-name">{{ extractFileName(getTextContent(item?.content)) }}</span>
                </div>
                <div class="image-container" v-html="formatMessage(item.content)"></div>
            </div>
            </div><!-- /.message-body -->
        </div>
    </transition>
</template>
<!-- MessageItem.vue -->
<style lang="scss">
.message-container {
    margin-top: 16px;
    margin-bottom: 16px;
}

/* Avatar "beside" layout - avatar on left, message body on right */
.message-container.avatar-beside {
    display: flex;
    flex-direction: row;
    align-items: flex-start;
    gap: 12px;

    .avatar-beside {
        flex-shrink: 0;
        margin-top: 4px;
    }

    .message-body {
        flex: 1;
        min-width: 0; /* Allow text to wrap properly */
    }

    /* Flip layout for user messages - avatar on right */
    &.user-role {
        flex-direction: row-reverse;
    }
}

/* Avatar "above" layout - default vertical stack */
.message-container.avatar-above {
    .message-body {
        width: 100%;
    }
}

/* Message entrance animations */
.message-fade-enter-active {
    transition: all var(--vera-message-motion-duration) cubic-bezier(0.22, 1, 0.36, 1);
}

.message-fade-leave-active {
    transition: all var(--vera-message-motion-leave) ease-in;
}

.message-fade-enter-from {
    opacity: 0;
    transform: translateY(var(--vera-message-motion-distance)) scale(0.98);
}

.message-slide-right {
    opacity: 0;
    transform: translateX(var(--vera-message-motion-slide-distance)) scale(0.98);
}

.message-slide-left {
    opacity: 0;
    transform: translateX(calc(var(--vera-message-motion-slide-distance) * -1)) scale(0.98);
}

.message-fade-leave-to {
    opacity: 0;
    transform: translateY(calc(var(--vera-message-motion-distance) * 0.5));
}

.avatar-animate {
    animation: avatarAppear calc(0.3s / var(--vera-anim-speed, 1)) cubic-bezier(0.22, 1, 0.36, 1) forwards;
}

@keyframes avatarAppear {
    0% {
        opacity: 0;
        transform: scale(0.7);
    }
    100% {
        opacity: 1;
        transform: scale(1);
    }
}

.avatar-wrapper {
    position: relative;
    width: var(--vera-avatar-size, 36px);
    height: var(--vera-avatar-size, 36px);
    flex-shrink: 0;
    margin-right: 8px;

    .p-avatar {
        width: 100% !important;
        height: 100% !important;
        border: var(--vera-avatar-border, none);
        border-image: var(--vera-avatar-border-image, none);
        box-shadow: var(--vera-avatar-glow, none);

        // Override PrimeVue shapes with custom shapes
        &.p-avatar-circle {
            border-radius: 50%;
        }
        &.p-avatar-square {
            border-radius: 4px;
        }
    }

    // Custom shape classes applied via data attribute or class
    &[data-shape="squircle"] .p-avatar,
    &.squircle .p-avatar {
        border-radius: 30% !important;
    }
    &[data-shape="oval-h"] .p-avatar,
    &.oval-h .p-avatar {
        border-radius: 50% / 35% !important;
    }
    &[data-shape="oval-v"] .p-avatar,
    &.oval-v .p-avatar {
        border-radius: 35% / 50% !important;
    }

    .avatar-icon-fallback {
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--vera-accent-soft);
        border: var(--vera-avatar-border, none);
        box-shadow: var(--vera-avatar-glow, none);
        color: var(--vera-accent);
        animation: avatarAppear calc(0.3s / var(--vera-anim-speed, 1)) cubic-bezier(0.22, 1, 0.36, 1) forwards;

        // Shape classes
        &.circle {
            border-radius: 50%;
        }
        &.square {
            border-radius: 4px;
        }
        &.squircle {
            border-radius: 30%;
        }
        &.oval-h {
            border-radius: 50% / 35%;
        }
        &.oval-v {
            border-radius: 35% / 50%;
        }

        // AI preset colors
        &.ai-preset {
            color: var(--vera-avatar-ai-color, var(--vera-accent));
            background: linear-gradient(135deg, var(--vera-accent-soft), var(--vera-panel));
        }

        // User preset colors
        &.user-preset {
            color: var(--vera-avatar-user-color, var(--vera-secondary));
            background: linear-gradient(135deg, var(--vera-accent-soft), var(--vera-panel));
        }
    }

    .avatar-status {
        position: absolute;
        bottom: 0;
        right: 0;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        border: 2px solid var(--vera-bg);
        z-index: 1;

        &.online {
            background-color: var(--vera-success);
        }

        &.away {
            background-color: var(--vera-warning);
        }

        &.busy {
            background-color: var(--vera-status-error);
        }

        &.offline {
            background-color: var(--vera-text-muted);
        }
    }
}

.scale-enter-from,
.scale-leave-to {
    transition: all 0.15s ease-out;
    transform: scale(0);
}

.scale-enter-to,
.scale-leave-from {
    transform: scale(1);
}

.p-menuitem {
    padding: 4px;

    span {
        gap: 3px;
    }

    .p-menuitem-text {
        margin-left: 6px;
    }
}

.message {
    position: relative;
    min-width: 10%;
    width: fit-content;
    clear: both;
    font-size: 1em;
    line-height: 1.5;
    max-width: 75vw;
    box-shadow: 0 10px 26px rgba(var(--vera-shadow-rgb), 0.28);
    transition: all 0.2s ease;
    font-family: var(--vera-font-messages);
    color: var(--vera-text-messages);

    &:hover {
        transform: translateY(calc(-1px * var(--vera-hover-lift)));
    }

    &::after {
        content: '';
        position: absolute;
        inset: 1px;
        border-radius: inherit;
        border: 1px solid var(--vera-message-edge);
        opacity: 0.9;
        pointer-events: none;
    }

    @media (max-width: 600px) {
        max-width: 85vw;
        margin: 16px 0;
    }

    &.user {
        margin-left: auto;
        margin-right: 32px;
        background: var(--vera-message-user-bg);
        border-radius: 16px 16px 4px 16px;
        max-width: 50%;
        padding: 6px;
        margin-top: 24px;
        border: 1px solid var(--vera-message-user-border);
        box-shadow: var(--vera-message-shadow), var(--vera-message-glow, var(--vera-glow-soft));
        transition: all 0.2s ease;

        @media (max-width: 600px) {
            max-width: 75%;
            margin-right: 16px;
            margin-top: 20px;
            padding: 4px 6px;
        }

        &:hover {
            box-shadow: var(--vera-glow-strong);
            transform: translateY(calc(-1px * var(--vera-hover-lift)));
        }

        &.high-constrast-mode {
            background: color-mix(in srgb, var(--vera-panel) 95%, transparent);
            border-radius: 14px;
            max-width: 50%;
            border: 1px solid var(--vera-accent-20);
        }

        .message-header {
            padding: 6px 8px 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(var(--vera-contrast-rgb), 0.03);
            margin-bottom: 2px;

            .message-header-content {
                display: flex;
                align-items: center;
                
                .p-avatar {
                    margin-right: 8px;
                    box-shadow: 0 1px 3px rgba(var(--vera-shadow-rgb), 0.2);
                }
            }

            .action-buttons-row {
                display: flex;
                gap: 4px;
                align-items: center;
                margin-left: 12px;
            }
        }

        .label:hover {
            background-color: var(--vera-accent-faint);
        }
    }

    &.gpt {
        margin-right: auto;
        margin-left: 32px;
        background: var(--vera-message-assistant-bg);
        border-radius: 16px 16px 16px 4px;
        max-width: 50%;
        margin-top: 24px;
        padding: 6px;
        border: 1px solid var(--vera-message-assistant-border);
        box-shadow: var(--vera-message-shadow), var(--vera-message-glow, var(--vera-glow-soft));

        @media (max-width: 600px) {
            max-width: 75%;
            margin-left: 16px;
            margin-top: 20px;
        }

        &.high-constrast-mode {
            background-color: color-mix(in srgb, var(--vera-panel) 95%, transparent);
            border-radius: 12px;
            max-width: 50%;
        }

        .message-header {
            padding: 6px 8px 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--vera-success-30);
            margin-bottom: 2px;

            .message-header-content {
                display: flex;
                align-items: center;
                
                .p-avatar {
                    margin-right: 8px;
                    box-shadow: 0 1px 3px rgba(var(--vera-shadow-rgb), 0.2);
                }
            }
        }

        .label:hover {
            background-color: var(--vera-accent-faint);
        }
    }

    .message-header {
        color: var(--vera-text);

        .label {
            color: var(--vera-text);
            font-weight: 500;
            font-size: 0.9rem;
            line-height: 1;
            opacity: 0.8;
            cursor: pointer;
            border-radius: 4px;
            padding: 4px 8px;
            transition: background-color 0.2s ease, opacity 0.2s ease;

            &:hover {
                opacity: 1;
            }
        }
    }

    .message-contents {
        padding: 12px 16px;
        display: block;
        overflow-wrap: break-word;
        font-size: 0.95rem;
        line-height: 1.6;
        letter-spacing: 0.01em;
        
        @media (max-width: 600px) {
            padding: 10px 12px;
        }

        pre {
            margin: 12px 0;
            border-radius: 8px;
            background-color: var(--vera-code-bg);
            border: 1px solid var(--vera-code-border);
            padding: 12px;
            font-size: 0.9rem;
            overflow-x: auto;
            box-shadow: inset 0 1px 3px rgba(var(--vera-shadow-rgb), 0.2);
        }

        code:not(pre code) {
            background-color: var(--vera-accent-faint);
            border-radius: 4px;
            padding: 2px 4px;
            font-family: var(--vera-font-mono);
            font-size: 0.85rem;
        }

        p {
            margin: 0.5em 0;
        }

        &[contenteditable='true'] {
            outline: none;
            outline: 2px solid var(--vera-accent);
            border-radius: 6px;
            text-align: left;
            box-shadow: 0 0 0 1px var(--vera-accent-faint),
                        0 0 8px var(--vera-accent-soft);
            padding: 14px 18px;
        }
    }
}

.action-button {
    background-color: rgba(var(--vera-contrast-rgb), 0.06);
    border: none;
    color: var(--vera-text-muted);
    cursor: pointer;
    border-radius: 4px;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
    padding: 0;
    position: relative;
    flex-shrink: 0;
    
    &:hover {
        background-color: rgba(var(--vera-contrast-rgb), 0.1);
        color: rgba(var(--vera-contrast-rgb), 0.95);
        transform: translateY(-1px);
    }
    
    &:active {
        transform: translateY(0);
        color: var(--vera-accent);
        background-color: var(--vera-accent-faint);
    }
}

.loading {
    animation: spin calc(1s / var(--vera-anim-speed, 1)) infinite linear;
}

@keyframes spin {
    0% {
        transform: rotate(0deg);
    }
    100% {
        transform: rotate(360deg);
    }
}

.file-content {
    .file-info-display {
        display: flex;
        align-items: center;
        background-color: var(--vera-panel-alt);
        border-radius: 8px;
        padding: 10px 15px;
        margin: 8px 0;
        
        .file-icon {
            color: var(--vera-success);
            margin-right: 10px;
        }
        
        .file-name {
            font-weight: 500;
            word-break: break-word;
        }
    }
}

.file-info-display {
    display: flex;
    align-items: center;
    background-color: var(--vera-panel-alt);
    border-radius: 8px;
    padding: 10px 15px;
    margin: 8px 0;
    transition: background-color 0.2s ease;
    
    &:hover {
        background-color: var(--vera-panel);
    }
    
    .file-icon {
        color: var(--vera-success);
        margin-right: 10px;
    }
    
    .file-name {
        font-weight: 500;
        word-break: break-word;
        font-size: 0.9rem;
    }
    
    &.image-info {
        margin-bottom: 12px;
        
        .file-icon {
            color: var(--vera-accent);
        }
    }
}

.image-container {
    img {
        max-width: 100%;
        border-radius: 8px;
        margin: 8px 0;
        display: block;
        transition: transform 0.2s ease;

        &:hover {
            transform: scale(1.01);
        }
    }
}

.generated-media-card {
    background: color-mix(in srgb, var(--vera-panel-alt) 85%, transparent);
    border: 1px solid color-mix(in srgb, var(--vera-accent) 20%, transparent);
    border-radius: 12px;
    padding: 10px;
    margin: 10px 0;
}

.generated-media {
    width: 100%;
    max-width: 100%;
    border-radius: 10px;
    display: block;
}

.generated-video {
    max-height: 460px;
    background: #000;
}

.generated-media-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 10px;
    align-items: center;
}

.media-download-button,
.media-open-link {
    font-size: 0.82rem;
    border-radius: 8px;
    padding: 6px 10px;
    border: 1px solid color-mix(in srgb, var(--vera-accent) 35%, transparent);
    background: color-mix(in srgb, var(--vera-accent) 12%, transparent);
    color: var(--vera-text);
    text-decoration: none;
    cursor: pointer;
    transition: background 0.15s ease, transform 0.12s ease;
}

.media-download-button:hover,
.media-open-link:hover {
    background: color-mix(in srgb, var(--vera-accent) 24%, transparent);
    transform: translateY(-1px);
}

.generated-media-path {
    margin-top: 8px;
    font-size: 0.76rem;
    color: var(--vera-text-muted);
    word-break: break-all;
}

.generated-media-path .path-value {
    color: var(--vera-text-soft, var(--vera-text));
}

// Inline Thinking Section Styles
.thinking-section {
    margin: 8px 12px;
    border-radius: 8px;
    background: var(--vera-glass-bg);
    border: 1px solid var(--vera-glass-border);
    backdrop-filter: blur(12px);
    overflow: hidden;
    font-size: 0.8rem;
}

.thinking-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    cursor: pointer;
    user-select: none;
    background: var(--vera-thinking-header-bg, var(--vera-glass-strong));
    border: 1px solid var(--vera-thinking-header-border, transparent);
    border-radius: 8px 8px 0 0;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    transition: background-color 0.15s ease, border-color 0.15s ease;

    &:hover {
        background: var(--vera-accent-faint);
    }
}

.thinking-title {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--vera-text-muted);
    font-weight: 500;
}

.thinking-icon {
    color: var(--vera-accent);
}

.event-count {
    font-size: 0.7rem;
    opacity: 0.7;
    margin-left: 2px;
}

.collapse-icon {
    color: var(--vera-text-muted);
    transition: transform 0.2s ease;

    &.collapsed {
        transform: rotate(-90deg);
    }
}

.thinking-content {
    padding: 6px 10px;
    max-height: 150px;
    overflow-y: auto;
    scrollbar-width: thin;
    background: var(--vera-thinking-content-bg, transparent);
    border-radius: 0 0 8px 8px;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);

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
    gap: 6px;
    padding: 4px 6px;
    border-radius: 4px;
    margin-bottom: 2px;
    transition: background-color 0.1s ease;

    &:last-child {
        margin-bottom: 0;
    }

    &:hover {
        background: var(--vera-accent-faint);
    }
}

.event-icon {
    font-size: 0.85rem;
    flex-shrink: 0;
    line-height: 1.3;
}

.event-message {
    color: var(--vera-text);
    line-height: 1.3;
    word-break: break-word;
}

// Event type specific colors - using theme variables
.event-analyzing .event-message { color: var(--vera-text); }
.event-routing .event-message { color: var(--vera-event-routing); }
.event-memory .event-message { color: var(--vera-event-memory); }
.event-tool .event-message { color: var(--vera-event-tool); }
.event-reasoning .event-message { color: var(--vera-text); }
.event-decision .event-message { color: var(--vera-event-decision); font-weight: 500; }
.event-quorum .event-message { color: var(--vera-event-quorum); }
.event-error .event-message { color: var(--vera-event-error); }

// Thinking expand/collapse animation
.thinking-expand-enter-active,
.thinking-expand-leave-active {
    transition: all 0.2s ease;
    max-height: 150px;
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
