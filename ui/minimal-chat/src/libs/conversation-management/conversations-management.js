import { fetchGPTResponseStream } from '../api-access/gpt-api-access';
import { fetchLocalModelResponseStream, getConversationTitleFromLocalModel, fetchOpenAICompatibleResponse } from '../api-access/open-ai-api-standard-access';
import { streamClaudeResponse, fetchClaudeConversationTitle } from '../api-access/claude-api-access';
import { sendBrowserLoadedModelMessage, getBrowserLoadedModelConversationTitle } from '../api-access/web-llm-access';
import { getConversationTitleFromGPT, removeAPIEndpoints } from '@/libs/utils/general-utils';
import { conversations, messages, selectedConversation, lastLoadedConversationId, selectedModel, localModelName, localModelEndpoint } from '../state-management/state';

const MIN_NEW_CONVERSATION_TOKENS = (() => {
  const raw = localStorage.getItem('minConversationTokens');
  const parsed = parseInt(raw || '40', 10);
  return Number.isNaN(parsed) ? 40 : parsed;
})();

const estimateTokenCount = (messageList) => {
  if (!Array.isArray(messageList)) {
    return 0;
  }
  let totalChars = 0;
  for (const message of messageList) {
    if (!message) continue;
    const content = message.content;
    if (Array.isArray(content)) {
      for (const item of content) {
        if (item?.type === 'text' && item.text) {
          totalChars += String(item.text).length;
        }
      }
    } else if (typeof content === 'string') {
      totalChars += content.length;
    }
  }
  return Math.ceil(totalChars / 4);
};

const extractMessageText = (message) => {
  if (!message) {
    return '';
  }
  if (Array.isArray(message.content)) {
    return message.content
      .map((item) => (item?.type === 'text' ? item.text : ''))
      .join(' ')
      .trim();
  }
  return typeof message.content === 'string' ? message.content.trim() : '';
};

const sanitizeTitle = (title, fallback) => {
  const raw = typeof title === 'string' ? title : '';
  const cleaned = raw.replace(/\s+/g, ' ').trim();
  if (!cleaned) {
    return fallback;
  }
  const unquoted = cleaned.replace(/^["']|["']$/g, '');
  const dePrefixed = unquoted.replace(/^(summary|title)\s*[:\-]\s*/i, '');
  const words = dePrefixed.split(' ').filter(Boolean);
  const snippet = words.slice(0, 10).join(' ');
  if (!snippet) {
    return fallback;
  }
  const maxChars = 80;
  const trimmed = snippet.length > maxChars ? snippet.slice(0, maxChars).trim() : snippet;
  return dePrefixed.length > trimmed.length ? `${trimmed}...` : trimmed;
};

const getQuickTitle = (messages) => {
  const firstUser = messages.find((msg) => msg.role === 'user');
  const raw = extractMessageText(firstUser);
  if (!raw) {
    return 'New Conversation';
  }
  const cleaned = raw.replace(/\s+/g, ' ').trim();
  const words = cleaned.split(' ');
  const snippet = words.slice(0, 8).join(' ');
  const candidate = cleaned.length > snippet.length ? `${snippet}...` : snippet;
  return sanitizeTitle(candidate, 'New Conversation');
};

// Helper function to determine the appropriate API call based on the selected model
const getConversationTitle = async (selectedModel, messages, localModelName, localModelEndpoint, sliderValue) => {
  if (selectedModel.includes('claude')) {
    return fetchClaudeConversationTitle(messages);
  }

  if (selectedModel.includes('open-ai-format')) {
    return getConversationTitleFromLocalModel(messages, localModelName, localModelEndpoint);
  }

  if (selectedModel.includes('gpt')) {
    return getConversationTitleFromGPT(messages, selectedModel, sliderValue);
  }

  if (selectedModel.includes('web-llm')) {
    return getBrowserLoadedModelConversationTitle(messages);
  }

  return 'Error Generating Title';
};

// Function to create a new conversation
export const createConversation = (conversations, title, messages) => {
  const newId = conversations.length > 0 ? Math.max(...conversations.map((c) => c.id)) + 1 : 1;

  const newConversation = {
    title: title,
    id: newId,
    messageHistory: messages,
    lastAccessed: new Date().toISOString(),
  };

  return [...conversations, newConversation];
};

// Function to update an existing conversation
export const updateConversation = (conversations, id, updatedConversation) => {
  return conversations.map((conversation) =>
    conversation.id === id ? { ...conversation, ...updatedConversation } : conversation
  );
};

// Function to delete a conversation
export const deleteConversation = (conversations, id) => {
  return conversations.filter((conversation) => conversation.id !== id);
};

// Function to save messages to local storage and update conversations
export const saveMessages = async () => {
  const updatedConversation = selectedConversation.value;

  // If there is no selected conversation, create a new one
  if (!updatedConversation) {
    const tokenEstimate = estimateTokenCount(messages.value);
    // If there are no messages, just save the empty conversations array and return
    if (messages.value.length === 0 || tokenEstimate < MIN_NEW_CONVERSATION_TOKENS) {
      localStorage.setItem('gpt-conversations', JSON.stringify(conversations.value));
      selectedConversation.value = null;
      return;
    }

    const newId = conversations.value.length > 0
      ? Math.max(...conversations.value.map((c) => c.id)) + 1
      : 1;

    // Ensure all messages have unique IDs
    const uniqueMessages = createUniqueMessagesWithIds(messages.value);
    const quickTitle = getQuickTitle(uniqueMessages);

    const newConversation = {
      title: sanitizeTitle(quickTitle, 'New Conversation'),
      id: newId,
      messageHistory: uniqueMessages,
      lastAccessed: new Date().toISOString(),
    };

    // Update the state immediately with a fast title
    messages.value = uniqueMessages;
    conversations.value = [...conversations.value, newConversation];
    lastLoadedConversationId.value = newId;
    selectedConversation.value = newConversation;

    localStorage.setItem('lastConversationId', newId);
    localStorage.setItem('gpt-conversations', JSON.stringify(conversations.value));

    // Kick off the slower model-generated title update asynchronously
    getConversationTitle(
      selectedModel.value || 'open-ai-format',
      messages.value,
      localStorage.getItem('localModelName') || localModelName.value || 'grok-4-1-fast-reasoning',
      localStorage.getItem('localModelEndpoint') || localModelEndpoint.value || window.location.origin,
      localStorage.getItem('gpt-attitude') || 50
    )
      .then((title) => {
        const sanitized = sanitizeTitle(title, quickTitle);
        if (!sanitized || sanitized === quickTitle) {
          return;
        }
        const updatedList = conversations.value.map((conversation) =>
          conversation.id === newId ? { ...conversation, title: sanitized } : conversation
        );
        conversations.value = updatedList;
        localStorage.setItem('gpt-conversations', JSON.stringify(conversations.value));
        if (selectedConversation.value?.id === newId) {
          selectedConversation.value = updatedList.find((conversation) => conversation.id === newId) || null;
        }
      })
      .catch((error) => console.error('Failed to update conversation title:', error));

    return;
  }

  // Update the message history of the selected conversation
  updatedConversation.messageHistory = messages.value;

  // Update the conversation in the conversations array
  const updatedConversations = updateConversation(conversations.value, updatedConversation.id, updatedConversation);

  // Update the state
  conversations.value = updatedConversations;

  // Save to local storage
  localStorage.setItem('gpt-conversations', JSON.stringify(conversations.value));
  // Keep the current selected conversation instead of always selecting the last one
  const currentConversation = conversations.value.find(c => c.id === updatedConversation.id);
  selectedConversation.value = currentConversation || null;
};

// Function to select a conversation and load its messages
export const selectConversation = (conversations, conversationId, messages, lastLoadedConversationId, showToast) => {
  if (!conversations.length) {
    return { conversations, messages, selectedConversation: null, lastLoadedConversationId };
  }

  const conversationIndex = conversations.findIndex((c) => c.id === conversationId);

  if (conversationIndex === -1) {
    showToast('Conversations ID not found');
    console.error('Conversation with ID ' + conversationId + ' not found.');
    return { conversations, messages, selectedConversation: null, lastLoadedConversationId };
  }

  // Update lastAccessed timestamp
  const updatedConversation = {
    ...conversations[conversationIndex],
    lastAccessed: new Date().toISOString(),
  };

  // Update the conversation in the array
  const updatedConversations = [...conversations];
  updatedConversations[conversationIndex] = updatedConversation;

  // Save to localStorage
  localStorage.setItem('gpt-conversations', JSON.stringify(updatedConversations));

  lastLoadedConversationId = conversationId;
  localStorage.setItem('lastConversationId', lastLoadedConversationId);

  // Ensure all messages have unique IDs
  const processedMessages = createUniqueMessagesWithIds(updatedConversation.messageHistory);

  messages = processedMessages;

  return { conversations: updatedConversations, messages, selectedConversation: updatedConversation, lastLoadedConversationId, showConversationOptions: false };
};

// Helper function to fetch the response stream based on the selected model
const fetchResponseStream = async (
  selectedModel,
  regenMessages,
  sliderValue,
  localSliderValue,
  localModelName,
  localModelEndpoint,
  claudeSliderValue,
  updateUI,
  abortController,
  streamedMessageText,
  autoScrollToBottom
) => {
  if (selectedModel.includes('gpt')) {
    return fetchGPTResponseStream(regenMessages, sliderValue, selectedModel, updateUI, abortController, streamedMessageText, autoScrollToBottom);
  }

  if (selectedModel.includes('web-llm')) {
    return sendBrowserLoadedModelMessage(regenMessages, updateUI);
  }

  if (selectedModel.includes('claude')) {
    return streamClaudeResponse(
      regenMessages,
      selectedModel,
      claudeSliderValue,
      updateUI,
      abortController,
      streamedMessageText,
      autoScrollToBottom
    );
  }

  return fetchLocalModelResponseStream(
    regenMessages,
    localSliderValue,
    localModelName,
    localModelEndpoint,
    updateUI,
    abortController,
    streamedMessageText,
    autoScrollToBottom
  );
};

// Function to regenerate a message response
export const regenerateMessageResponse = async (
  conversations,
  messages,
  content,
  sliderValue,
  selectedModel,
  localSliderValue,
  localModelName,
  localModelEndpoint,
  claudeSliderValue,
  updateUI,
  abortController,
  streamedMessageText
) => {
  const messageIndex = messages.value.findIndex((message) => message.content === content && message.role === 'user');

  if (messageIndex === -1) {
    return { conversations, baseMessages: messages.value };
  }

  const regenMessages = messages.value.slice(0, messageIndex + 1);
  const messagesAfter = messages.value.slice(messageIndex + 2);

  abortController.value = new AbortController();

  messages.value = regenMessages;

  // Fetch the response stream
  await fetchResponseStream(
    selectedModel,
    regenMessages,
    sliderValue,
    localSliderValue,
    localModelName,
    localModelEndpoint,
    claudeSliderValue,
    updateUI,
    abortController.value,
    streamedMessageText,
    false
  );

  // Combine the messages and ensure unique IDs
  const baseMessages = createUniqueMessagesWithIds([...regenMessages, ...messagesAfter]);

  return { conversations, baseMessages };
};

// Function to edit a previous message
export const editPreviousMessage = async (
  conversations,
  messages,
  oldContent,
  newContent,
  sliderValue,
  selectedModel,
  localSliderValue,
  localModelName,
  localModelEndpoint,
  claudeSliderValue,
  updateUI,
  abortController,
  streamedMessageText
) => {
  const messageIndex = messages.value.findIndex((message) => message.content === oldContent.content && message.role === 'user');

  if (messageIndex === -1) {
    return { conversations, baseMessages: messages.value };
  }

  const regenMessages = messages.value.slice(0, messageIndex + 1);
  const messagesAfter = messages.value.slice(messageIndex + 2);

  abortController.value = new AbortController();

  regenMessages[regenMessages.length - 1].content = newContent;

  messages.value = regenMessages;

  // Fetch the response stream
  await fetchResponseStream(
    selectedModel,
    regenMessages,
    sliderValue,
    localSliderValue,
    localModelName,
    localModelEndpoint,
    claudeSliderValue,
    updateUI,
    abortController.value,
    streamedMessageText,
    false
  );

  const baseMessages = createUniqueMessagesWithIds([...regenMessages, ...messagesAfter]);

  return { conversations, baseMessages };
};

// Function to edit a conversation title
export const editConversationTitle = async (conversations, oldConversation, newConversationTitle) => {
  const updatedConversation = {
    ...oldConversation,
    title: newConversationTitle,
  };

  const updatedConversationsList = updateConversation(conversations, oldConversation.id, updatedConversation);

  return updatedConversationsList;
};

// Function to handle exporting conversations
export const handleExportConversations = () => {
  const filename = 'conversations.json';
  const text = localStorage.getItem('gpt-conversations');

  const element = document.createElement('a');

  element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(text));
  element.setAttribute('download', filename);
  element.style.display = 'none';
  document.body.appendChild(element);

  element.click();

  document.body.removeChild(element);
};

// Function to set the system prompt
export const setSystemPrompt = (messages, prompt) => {
  const systemPromptIndex = messages.findIndex((message) => message.role === 'system');

  if (systemPromptIndex === 0) {
    const trimmedPrompt = prompt.trim();
    if (trimmedPrompt === '') {
      messages.shift();
    } else {
      messages[0].content = prompt;
    }
    return;
  }

  const trimmedPrompt = prompt.trim();
  if (trimmedPrompt === '') {
    return;
  }

  messages.unshift({
    role: 'system',
    content: prompt,
  });
};

// Function to delete a message from history
export const deleteMessageFromHistory = (messages, content) => {
  const messageIndex = messages.findIndex((message) => message.content === content && message.role === 'user');

  if (messageIndex === -1) {
    return messages;
  }

  return [...messages.slice(0, messageIndex), ...messages.slice(messageIndex + 2)];
};

// Function to create unique message IDs
export const createUniqueMessagesWithIds = (messages) => {
  let maxId = messages.reduce((max, message) => (message.id ? Math.max(max, message.id) : max), 0);

  return messages.map((message) => {
    if (!message.id) {
      maxId++;
      return { ...message, id: maxId };
    }
    return message;
  });
};

// ============================================
// Artifact Management Functions
// ============================================

/**
 * Create a new artifact for a conversation
 * @param {Object} conversation - The conversation to add the artifact to
 * @param {Object} artifact - The artifact data { content, language, file_path, title }
 * @returns {Object} The created artifact with id and timestamps
 */
export const createArtifact = (conversation, artifact) => {
  if (!conversation.artifacts) {
    conversation.artifacts = [];
  }

  const maxId = conversation.artifacts.reduce((max, a) => Math.max(max, a.id || 0), 0);

  const newArtifact = {
    id: maxId + 1,
    title: artifact.title || artifact.file_path?.split('/').pop() || `Artifact ${maxId + 1}`,
    content: artifact.content || '',
    language: artifact.language || 'plaintext',
    file_path: artifact.file_path || '',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    created_by: artifact.created_by || 'user',
  };

  conversation.artifacts.push(newArtifact);
  return newArtifact;
};

/**
 * Update an existing artifact
 * @param {Object} conversation - The conversation containing the artifact
 * @param {number} artifactId - The ID of the artifact to update
 * @param {Object} updates - The updates to apply { content, language, title, file_path }
 * @returns {Object|null} The updated artifact or null if not found
 */
export const updateArtifact = (conversation, artifactId, updates) => {
  if (!conversation.artifacts) return null;

  const index = conversation.artifacts.findIndex(a => a.id === artifactId);
  if (index === -1) return null;

  const artifact = conversation.artifacts[index];
  const updatedArtifact = {
    ...artifact,
    ...updates,
    updated_at: new Date().toISOString(),
  };

  conversation.artifacts[index] = updatedArtifact;
  return updatedArtifact;
};

/**
 * Delete an artifact from a conversation
 * @param {Object} conversation - The conversation containing the artifact
 * @param {number} artifactId - The ID of the artifact to delete
 * @returns {boolean} True if deleted, false if not found
 */
export const deleteArtifact = (conversation, artifactId) => {
  if (!conversation.artifacts) return false;

  const index = conversation.artifacts.findIndex(a => a.id === artifactId);
  if (index === -1) return false;

  conversation.artifacts.splice(index, 1);
  return true;
};

/**
 * Get all artifacts for a conversation
 * @param {Object} conversation - The conversation
 * @returns {Array} Array of artifacts
 */
export const getArtifacts = (conversation) => {
  return conversation?.artifacts || [];
};

/**
 * Find an artifact by ID
 * @param {Object} conversation - The conversation
 * @param {number} artifactId - The artifact ID
 * @returns {Object|null} The artifact or null
 */
export const findArtifact = (conversation, artifactId) => {
  if (!conversation?.artifacts) return null;
  return conversation.artifacts.find(a => a.id === artifactId) || null;
};

// ============================================
// Conversation Forking Functions
// ============================================

/**
 * Generate a summary of a conversation for forking
 * @param {Object} conversation - The conversation to summarize
 * @returns {Promise<string>} The summary text
 */
export const generateConversationSummary = async (conversation) => {
  if (!conversation?.messageHistory || conversation.messageHistory.length === 0) {
    return '';
  }

  // Build a condensed version of the conversation for summarization
  const messageTexts = conversation.messageHistory
    .filter(msg => msg.role !== 'system')
    .map(msg => {
      const text = extractMessageText(msg);
      const truncated = text.length > 500 ? text.substring(0, 500) + '...' : text;
      return `${msg.role.toUpperCase()}: ${truncated}`;
    })
    .join('\n\n');

  // Create a summarization prompt
  const summaryPrompt = `Please provide a concise summary of this conversation that captures:
1. The main topics discussed
2. Key decisions or conclusions reached
3. Any ongoing tasks or questions
4. Important context needed to continue this conversation

Keep the summary under 500 words but ensure it captures the essential context.

CONVERSATION:
${messageTexts}

SUMMARY:`;

  try {
    const endpoint = removeAPIEndpoints(localStorage.getItem('localModelEndpoint') || window.location.origin);
    const modelName = localStorage.getItem('localModelName') || 'grok-4-1-fast-reasoning';

    const response = await fetchOpenAICompatibleResponse(
      [{ role: 'user', content: summaryPrompt }],
      0.3, // Low temperature for consistent summaries
      modelName,
      endpoint
    );

    return response || '';
  } catch (error) {
    console.error('Failed to generate summary:', error);
    // Fallback: create a simple summary from the conversation title and message count
    return `Continuing from "${conversation.title}" (${conversation.messageHistory.length} messages). Please continue where we left off.`;
  }
};

/**
 * Fork a conversation - create a new conversation with summary context
 * @param {Array} conversationsList - The current list of conversations
 * @param {Object} sourceConversation - The conversation to fork from
 * @param {string} summary - The summary to use as initial context
 * @returns {Object} The new forked conversation
 */
export const forkConversation = (conversationsList, sourceConversation, summary) => {
  const newId = conversationsList.length > 0
    ? Math.max(...conversationsList.map((c) => c.id)) + 1
    : 1;

  const forkTitle = `Fork: ${sourceConversation.title}`.substring(0, 80);

  // Create the continuation prompt that will be sent to the agent
  const continuationPrompt = `[CONVERSATION CONTINUATION]

This is a fork of a previous conversation. Here's the context summary:

${summary}

---

Please acknowledge this context and let me know you're ready to continue. If there were any pending tasks or questions, please summarize them.`;

  const newConversation = {
    title: forkTitle,
    id: newId,
    messageHistory: [], // Empty - ChatLayout will send the continuation prompt via sendMessage
    lastAccessed: new Date().toISOString(),
    forkedFrom: {
      id: sourceConversation.id,
      title: sourceConversation.title,
      forkedAt: new Date().toISOString()
    },
    artifacts: [] // Start with empty artifacts, could optionally copy from source
  };

  // Return both the conversation and the prompt so ChatLayout can trigger the send
  return { conversation: newConversation, continuationPrompt };
};

/**
 * Get fork metadata if conversation was forked
 * @param {Object} conversation - The conversation
 * @returns {Object|null} Fork metadata or null
 */
export const getForkInfo = (conversation) => {
  return conversation?.forkedFrom || null;
};
