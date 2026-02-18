<template>
    <div>
        <div class="system-prompt-card tool-keys-card">
            <div class="prompt-header">
                <KeyRound size="18" class="section-icon" />
                <h3>VERA Tool Keys</h3>
                <div class="auth-status" :class="[googleAuthClass, googleAuthReasonLabel ? 'has-reason' : '']" :title="googleAuthTooltip">
                    <span class="auth-dot" :class="googleAuthClass"></span>
                    <div class="auth-text">
                        <span>Google: {{ googleAuthLabel }}</span>
                        <span v-if="googleAuthReasonLabel" class="auth-reason">{{ googleAuthReasonLabel }}</span>
                    </div>
                </div>
            </div>
            <div class="prompt-content">
                <p class="prompt-description">
                    Set API keys and endpoints for tool integrations. Values are applied to the running VERA process and cleared from the form after submission.
                </p>
                <div class="tool-keys-list">
                    <details class="tool-key-group" open>
                        <summary>
                            <span>Core providers</span>
                            <span class="tool-key-meta">XAI · Brave · GitHub</span>
                        </summary>
                        <div class="tool-key-group-body">
                            <InputField labelText="XAI_API_KEY" inputId="vera-xai-key" :value="toolKeys.XAI_API_KEY"
                                @update:value="toolKeys.XAI_API_KEY = $event" :isSecret="true" />
                            <InputField labelText="BRAVE_API_KEY" inputId="vera-brave-key" :value="toolKeys.BRAVE_API_KEY"
                                @update:value="toolKeys.BRAVE_API_KEY = $event" :isSecret="true" />
                            <InputField labelText="GITHUB_PERSONAL_ACCESS_TOKEN" inputId="vera-github-key"
                                :value="toolKeys.GITHUB_PERSONAL_ACCESS_TOKEN"
                                @update:value="toolKeys.GITHUB_PERSONAL_ACCESS_TOKEN = $event" :isSecret="true" />
                        </div>
                    </details>
                    <details class="tool-key-group" open>
                        <summary>
                            <span>Google Workspace</span>
                            <span class="tool-key-meta">OAuth + user</span>
                        </summary>
                        <div class="tool-key-group-body">
                            <InputField labelText="GOOGLE_CLIENT_ID" inputId="vera-google-client-id"
                                :value="toolKeys.GOOGLE_CLIENT_ID"
                                @update:value="toolKeys.GOOGLE_CLIENT_ID = $event" :isSecret="true" />
                            <InputField labelText="GOOGLE_CLIENT_SECRET" inputId="vera-google-client-secret"
                                :value="toolKeys.GOOGLE_CLIENT_SECRET"
                                @update:value="toolKeys.GOOGLE_CLIENT_SECRET = $event" :isSecret="true" />
                            <InputField labelText="GOOGLE_REDIRECT_URI" inputId="vera-google-redirect"
                                :value="toolKeys.GOOGLE_REDIRECT_URI"
                                @update:value="toolKeys.GOOGLE_REDIRECT_URI = $event" :isSecret="false" />
                            <InputField labelText="GOOGLE_WORKSPACE_USER_EMAIL" inputId="vera-google-user-email"
                                :value="toolKeys.GOOGLE_WORKSPACE_USER_EMAIL"
                                @update:value="toolKeys.GOOGLE_WORKSPACE_USER_EMAIL = $event" :isSecret="false" />
                        </div>
                    </details>
                    <details class="tool-key-group">
                        <summary>
                            <span>Searxng</span>
                            <span class="tool-key-meta">Search endpoint</span>
                        </summary>
                        <div class="tool-key-group-body">
                            <InputField labelText="SEARXNG_BASE_URL" inputId="vera-searxng"
                                :value="toolKeys.SEARXNG_BASE_URL"
                                @update:value="toolKeys.SEARXNG_BASE_URL = $event" :isSecret="false" />
                        </div>
                    </details>
                    <details class="tool-key-group">
                        <summary>
                            <span>Notes & Hub</span>
                            <span class="tool-key-meta">Obsidian · Composio</span>
                        </summary>
                        <div class="tool-key-group-body">
                            <InputField labelText="OBSIDIAN_VAULT_PATH" inputId="vera-obsidian-path"
                                :value="toolKeys.OBSIDIAN_VAULT_PATH"
                                @update:value="toolKeys.OBSIDIAN_VAULT_PATH = $event" :isSecret="false" />
                            <InputField labelText="MCP_HUB_COMMAND" inputId="vera-hub-command"
                                :value="toolKeys.MCP_HUB_COMMAND"
                                @update:value="toolKeys.MCP_HUB_COMMAND = $event" :isSecret="false" />
                            <InputField labelText="MCP_HUB_ARGS" inputId="vera-hub-args"
                                :value="toolKeys.MCP_HUB_ARGS"
                                @update:value="toolKeys.MCP_HUB_ARGS = $event" :isSecret="false" />
                            <InputField labelText="COMPOSIO_API_KEY (optional)" inputId="vera-composio-key"
                                :value="toolKeys.COMPOSIO_API_KEY"
                                @update:value="toolKeys.COMPOSIO_API_KEY = $event" :isSecret="true" />
                        </div>
                    </details>
                </div>
                <div class="prompt-actions">
                    <button class="save-prompt-button" @click="submitToolKeys">
                        <Save size="16" />
                        <span>Apply Keys</span>
                    </button>
                    <button class="save-prompt-button" :disabled="googleAuthStartDisabled" @click="startGoogleOAuth">
                        <KeyRound size="16" />
                        <span>Start OAuth</span>
                    </button>
                    <button class="clear-prompt-button" @click="refreshToolStatus">
                        <RefreshCcw size="16" />
                        <span>Refresh Status</span>
                    </button>
                </div>
                <div v-if="toolStatus" class="tool-status">
                    <div class="tool-status-header">
                        <span>Tool Status</span>
                        <span>{{ toolStatus.mcp.total_running }} running</span>
                    </div>
                    <ul>
                        <li v-for="(server, name) in toolStatus.mcp.servers" :key="name">
                            <span class="tool-name">{{ name }}</span>
                            <span class="tool-state" :class="server.running ? 'ok' : 'warn'">
                                {{ server.running ? 'running' : 'stopped' }}
                            </span>
                            <span v-if="server.health" class="tool-health" :class="server.health === 'healthy' ? 'ok' : 'warn'">
                                {{ server.health }}
                            </span>
                            <span v-if="server.missing_env && server.missing_env.length" class="tool-missing">
                                missing: {{ server.missing_env.join(', ') }}
                            </span>
                        </li>
                    </ul>
                    <div class="tool-actions">
                        <button class="save-prompt-button" @click="startStoppedTools">
                            <Play size="16" />
                            <span>Start Stopped</span>
                        </button>
                        <button class="clear-prompt-button" @click="restartUnhealthyTools">
                            <RefreshCcw size="16" />
                            <span>Restart Unhealthy</span>
                        </button>
                        <button class="clear-prompt-button" @click="fetchToolInventory">
                            <List size="16" />
                            <span>Refresh Inventory</span>
                        </button>
                    </div>
                </div>
                <div v-if="toolInventory" class="tool-inventory">
                    <div class="tool-status-header">
                        <span>Tool Inventory</span>
                        <span>{{ inventoryCount }} tools</span>
                    </div>
                    <div class="tool-inventory-list">
                        <details v-for="(tools, name) in toolInventory.tools" :key="name">
                            <summary>{{ name }} ({{ tools.length }})</summary>
                            <div class="tool-list">
                                {{ tools.length ? tools.join(', ') : 'No tools reported.' }}
                            </div>
                        </details>
                    </div>
                </div>
            </div>
        </div>
        <div class="system-prompt-card channels-card">
            <div class="prompt-header">
                <Plug size="18" class="section-icon" />
                <h3>Channels</h3>
                <div class="auth-status" :class="[channelsStatusClass, channelsStatusDetail ? 'has-reason' : '']">
                    <span class="auth-dot" :class="channelsStatusClass"></span>
                    <div class="auth-text">
                        <span>{{ channelsStatusLabel }}</span>
                        <span v-if="channelsStatusDetail" class="auth-reason">{{ channelsStatusDetail }}</span>
                    </div>
                </div>
            </div>
            <div class="prompt-content">
                <p class="prompt-description">
                    Configure messaging adapters via <code>config/channels.json</code> or <code>VERA_CHANNELS</code>.
                </p>
                <div class="channel-meta">
                    <div class="channel-meta-row">
                        <span>Config source</span>
                        <span class="channel-meta-value">{{ channelsConfigSource }}</span>
                    </div>
                    <div class="channel-meta-row">
                        <span>Config path</span>
                        <span class="channel-meta-value">{{ channelsConfigPath }}</span>
                    </div>
                </div>
                <div v-if="channelsConfiguredSpecs.length" class="channel-configs">
                    <span v-for="(spec, index) in channelsConfiguredSpecs" :key="`${spec.type}-${index}`"
                        class="channel-config-chip" :class="spec.enabled ? 'enabled' : 'disabled'">
                        {{ spec.type }}<span v-if="spec.module"> · custom</span>
                    </span>
                </div>
                <div v-if="channelsStatus" class="tool-status channel-status">
                    <div class="tool-status-header">
                        <span>Active Adapters</span>
                        <span>{{ channelsActiveCount }} active</span>
                    </div>
                    <ul v-if="channelsStatus.active?.length">
                        <li v-for="channel in channelsStatus.active" :key="channel.id">
                            <span class="tool-name">{{ channel.label }}</span>
                            <span class="tool-state ok">{{ channel.id }}</span>
                            <span v-if="channel.capabilities?.media" class="tool-health ok">media</span>
                            <span v-if="channel.capabilities?.threads" class="tool-health ok">threads</span>
                            <span v-if="channel.capabilities?.reactions" class="tool-health ok">reactions</span>
                        </li>
                    </ul>
                    <div v-else class="tool-status-empty">No channels registered yet.</div>
                </div>
                <div class="prompt-actions">
                    <button class="save-prompt-button" @click="openChannelsConfig">
                        <FolderOpen size="16" />
                        <span>{{ channelsConfigExists ? 'Open channels.json' : 'Open example' }}</span>
                    </button>
                    <button v-if="!channelsConfigExists" class="clear-prompt-button" @click="createChannelsConfig" :disabled="channelsCreating">
                        <FilePlus size="16" />
                        <span>Create channels.json</span>
                    </button>
                    <button class="clear-prompt-button" @click="fetchChannelsStatus" :disabled="channelsLoading">
                        <RefreshCcw size="16" />
                        <span>Refresh</span>
                    </button>
                </div>
                <div class="channel-hint">
                    <span>Quick add:</span>
                    <code>VERA_CHANNELS=api,discord</code>
                </div>
            </div>
        </div>
        <div class="system-prompt-card notifications-card">
            <div class="prompt-header">
                <Bell size="18" class="section-icon" />
                <h3>Notifications</h3>
                <div class="auth-status" :class="[pushStatusClass, pushStatusDetail ? 'has-reason' : '']">
                    <span class="auth-dot" :class="pushStatusClass"></span>
                    <div class="auth-text">
                        <span>{{ pushStatusLabel }}</span>
                        <span v-if="pushStatusDetail" class="auth-reason">{{ pushStatusDetail }}</span>
                    </div>
                </div>
            </div>
            <div class="prompt-content">
                <p class="prompt-description">
                    Enable Web Push for Inner Life reach-outs and system alerts.
                </p>
                <div class="channel-meta">
                    <div class="channel-meta-row">
                        <span>Support</span>
                        <span class="channel-meta-value">{{ pushSupportLabel }}</span>
                    </div>
                    <div class="channel-meta-row">
                        <span>Permission</span>
                        <span class="channel-meta-value">{{ pushPermissionLabel }}</span>
                    </div>
                    <div class="channel-meta-row">
                        <span>Subscription</span>
                        <span class="channel-meta-value">{{ pushSubscribed ? 'Active' : 'Inactive' }}</span>
                    </div>
                </div>
                <div class="prompt-actions">
                    <button class="save-prompt-button" @click="enablePush" :disabled="pushWorking || !pushEnabled">
                        <Bell size="16" />
                        <span>{{ pushSubscribed ? 'Re-subscribe' : 'Enable Push' }}</span>
                    </button>
                    <button class="clear-prompt-button" @click="disablePush" :disabled="pushWorking || !pushSubscribed">
                        <X size="16" />
                        <span>Disable</span>
                    </button>
                    <button class="clear-prompt-button" @click="sendPushTest" :disabled="pushWorking || !pushSubscribed">
                        <MessageSquare size="16" />
                        <span>Send Test</span>
                    </button>
                </div>
                <div v-if="pushConfigHint" class="channel-hint">
                    <span>{{ pushConfigHint }}</span>
                </div>
            </div>
        </div>
        <div class="system-prompt-card">
            <div class="prompt-header">
                <MessageSquare size="18" class="section-icon" />
                <h3>System Prompt</h3>
            </div>
            <div class="prompt-content">
                <p class="prompt-description">
                    Guide the AI's behavior and knowledge with a system prompt. This acts as context or instructions for the AI to follow during the conversation.
                </p>
                <InputField labelText="" inputId="system-prompt" :value="systemPrompt"
                    @update:value="handleUpdate('systemPrompt', $event)" :isSecret="false" :isMultiline="true"
                    :placeholderText="'You are a helpful AI assistant. You are friendly, kind, and accurate. You provide concise answers unless asked for more detail.'" />
                <div class="prompt-actions">
                    <button 
                        v-if="systemPrompt && systemPrompt.trim().length > 0" 
                        class="save-prompt-button" 
                        @click="handleSaveSystemPrompt(systemPrompt)"
                        title="Save current prompt to your collection">
                        <Save size="16" />
                        <span>Save Prompt</span>
                    </button>
                    <button 
                        v-if="systemPrompt && systemPrompt.trim().length > 0" 
                        class="clear-prompt-button" 
                        @click="handleUpdate('systemPrompt', '')"
                        title="Clear the current prompt">
                        <X size="16" />
                        <span>Clear</span>
                    </button>
                </div>
            </div>
        </div>
        <div class="saved-system-prompts-section">
            <div class="section-header" @click="isSavedPromptsOpen = !isSavedPromptsOpen">
                <h4>
                    <Save size="16" class="section-icon" />
                    Saved System Prompts
                </h4>
                <ChevronDown v-if="isSavedPromptsOpen" class="indicator" size="20" />
                <ChevronRight v-else class="indicator" size="20" />
            </div>
            <transition name="slide-fade">
                <div v-show="isSavedPromptsOpen" class="saved-system-prompts">
                    <div v-if="systemPrompts.length" class="prompts-container">
                        <ul>
                            <li v-for="(prompt, index) in systemPrompts" :key="index"
                                :class="{ selected: index === selectedSystemPromptIndex }"
                                @click="handleSelectSystemPrompt(index)">
                                <div class="prompt-item-content">
                                    <div class="prompt-text">{{ prompt }}</div>
                                    <button class="delete-prompt-btn" @click.stop="handleDeleteSystemPrompt(index)">
                                        <Trash2 size="18" />
                                    </button>
                                </div>
                            </li>
                        </ul>
                    </div>
                    <div v-else class="no-prompts">
                        <MessageSquare size="24" />
                        <p>No saved prompts yet. Enter a system prompt and it will appear here.</p>
                    </div>
                </div>
            </transition>
        </div>
    </div>
</template>


<script setup>
import InputField from '@/components/controls/InputField.vue';
import { Bell, ChevronDown, ChevronRight, Trash2, Save, MessageSquare, X, KeyRound, RefreshCcw, Play, List, Plug, FolderOpen, FilePlus } from 'lucide-vue-next';
import { systemPrompt } from '@/libs/state-management/state';
import { handleUpdate, handleDeleteSystemPrompt, handleSelectSystemPrompt, selectedSystemPromptIndex, systemPrompts, handleSaveSystemPrompt } from '@/libs/utils/settings-utils';
import { computed, onMounted, reactive, ref } from 'vue';
import { showToast } from '@/libs/utils/general-utils';

const toolStatus = ref(null);
const toolInventory = ref(null);
const googleAuthStatus = ref({ status: 'unknown', reason: '' });
const channelsStatus = ref(null);
const channelsLoading = ref(false);
const channelsCreating = ref(false);
const pushConfig = ref({ enabled: false, reason: '', public_key: '' });
const pushSubscribed = ref(false);
const pushPermission = ref(typeof Notification !== 'undefined' ? Notification.permission : 'default');
const pushWorking = ref(false);
const toolKeys = reactive({
    XAI_API_KEY: '',
    BRAVE_API_KEY: '',
    GITHUB_PERSONAL_ACCESS_TOKEN: '',
    GOOGLE_CLIENT_ID: '',
    GOOGLE_CLIENT_SECRET: '',
    GOOGLE_REDIRECT_URI: '',
    GOOGLE_WORKSPACE_USER_EMAIL: '',
    SEARXNG_BASE_URL: '',
    OBSIDIAN_VAULT_PATH: '',
    MCP_HUB_COMMAND: '',
    MCP_HUB_ARGS: '',
    COMPOSIO_API_KEY: ''
});

const isSavedPromptsOpen = ref(false);

const fetchToolStatus = async () => {
    try {
        const response = await fetch('/api/tools');
        if (!response.ok) {
            throw new Error('Failed to fetch tool status');
        }
        toolStatus.value = await response.json();
    } catch (error) {
        showToast('Unable to fetch tool status');
        console.error(error);
    }
};

const fetchGoogleAuthStatus = async (options = {}) => {
    const { silent = false } = options;
    try {
        const response = await fetch('/api/google/auth/status');
        if (!response.ok) {
            throw new Error('Failed to fetch auth status');
        }
        googleAuthStatus.value = await response.json();
    } catch (error) {
        if (!silent) {
            showToast('Unable to fetch Google auth status');
        }
        console.error(error);
    }
};

const waitForGoogleAuth = async (timeoutMs = 90000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        await fetchGoogleAuthStatus({ silent: true });
        if (googleAuthStatus.value?.status === 'authorized') {
            return true;
        }
    }
    return false;
};

const refreshToolStatus = async () => {
    await fetchToolStatus();
    await fetchGoogleAuthStatus();
};

const fetchChannelsStatus = async () => {
    channelsLoading.value = true;
    try {
        const response = await fetch('/api/channels/status');
        if (!response.ok) {
            throw new Error('Failed to fetch channels status');
        }
        channelsStatus.value = await response.json();
    } catch (error) {
        showToast('Unable to fetch channels status');
        console.error(error);
    } finally {
        channelsLoading.value = false;
    }
};

const openChannelsConfig = async () => {
    const configPath = channelsConfigPath.value;
    const configuredRelative = channelsStatus.value?.configured?.config_path_relative;
    let targetPath = channelsConfigExists.value
        ? (configuredRelative || configPath)
        : 'config/channels.example.json';
    if (!configuredRelative && typeof configPath === 'string' && configPath.startsWith('/')) {
        targetPath = 'config/channels.example.json';
        showToast('Config path is outside the workspace; opening example instead');
    }
    try {
        const response = await fetch('/api/editor/file/open', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: targetPath })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || 'Failed to open channels config');
        }
        showToast(channelsConfigExists.value ? 'Opened channels config' : 'Opened channels example');
    } catch (error) {
        showToast(error?.message || 'Unable to open channels config');
        console.error(error);
    }
};

const createChannelsConfig = async () => {
    if (channelsConfigExists.value) {
        showToast('channels.json already exists');
        return;
    }
    channelsCreating.value = true;
    try {
        const exampleResponse = await fetch('/api/file/read', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: 'config/channels.example.json' })
        });
        const exampleData = await exampleResponse.json().catch(() => ({}));
        if (!exampleResponse.ok) {
            throw new Error(exampleData.error || 'Failed to read channels example');
        }

        const writeResponse = await fetch('/api/file/write', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: channelsConfigPath.value, content: exampleData.content || '' })
        });
        const writeData = await writeResponse.json().catch(() => ({}));
        if (!writeResponse.ok) {
            throw new Error(writeData.error || 'Failed to create channels config');
        }
        showToast('Created channels config');
        await fetchChannelsStatus();
    } catch (error) {
        showToast(error?.message || 'Unable to create channels config');
        console.error(error);
    } finally {
        channelsCreating.value = false;
    }
};

const fetchPushConfig = async () => {
    try {
        const response = await fetch('/api/push/vapid');
        if (!response.ok) {
            throw new Error('Failed to fetch push config');
        }
        pushConfig.value = await response.json();
    } catch (error) {
        pushConfig.value = { enabled: false, reason: 'unavailable', public_key: '' };
    }
};

const urlBase64ToUint8Array = (base64String) => {
    if (!base64String) return null;
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(base64);
    const outputArray = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) {
        outputArray[i] = raw.charCodeAt(i);
    }
    return outputArray;
};

const ensureServiceWorker = async () => {
    if (!('serviceWorker' in navigator)) {
        return null;
    }
    const existing = await navigator.serviceWorker.getRegistration();
    if (existing) {
        return existing;
    }
    try {
        return await navigator.serviceWorker.register('/sw.js');
    } catch (error) {
        console.error(error);
        return null;
    }
};

const refreshPushSubscription = async () => {
    if (!('Notification' in window)) {
        pushPermission.value = 'unsupported';
        pushSubscribed.value = false;
        return;
    }
    pushPermission.value = Notification.permission;
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        pushSubscribed.value = false;
        return;
    }
    try {
        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription();
        pushSubscribed.value = Boolean(subscription);
    } catch (error) {
        pushSubscribed.value = false;
    }
};

const enablePush = async () => {
    if (pushWorking.value) return;
    pushWorking.value = true;
    try {
        await fetchPushConfig();
        if (!pushConfig.value?.enabled) {
            showToast('Push not configured. Add VAPID keys first.');
            return;
        }
        if (!('Notification' in window)) {
            showToast('Push notifications are not supported in this browser.');
            return;
        }
        if (Notification.permission === 'denied') {
            showToast('Notifications are blocked in this browser.');
            return;
        }
        const permission = await Notification.requestPermission();
        pushPermission.value = permission;
        if (permission !== 'granted') {
            showToast('Notification permission not granted.');
            return;
        }
        const registration = await ensureServiceWorker();
        if (!registration) {
            showToast('Unable to register service worker.');
            return;
        }
        const serverKey = urlBase64ToUint8Array(pushConfig.value.public_key);
        if (!serverKey) {
            showToast('Invalid VAPID key.');
            return;
        }
        const subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: serverKey,
        });
        const response = await fetch('/api/push/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subscription: subscription.toJSON() }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || 'Failed to register subscription');
        }
        pushSubscribed.value = true;
        showToast('Push notifications enabled.');
    } catch (error) {
        showToast(error?.message || 'Failed to enable push notifications');
        console.error(error);
    } finally {
        pushWorking.value = false;
    }
};

const disablePush = async () => {
    if (pushWorking.value) return;
    pushWorking.value = true;
    try {
        if (!('serviceWorker' in navigator)) {
            pushSubscribed.value = false;
            return;
        }
        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription();
        if (subscription) {
            await subscription.unsubscribe();
            await fetch('/api/push/unsubscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ endpoint: subscription.endpoint }),
            });
        }
        pushSubscribed.value = false;
        showToast('Push notifications disabled.');
    } catch (error) {
        showToast('Failed to disable push notifications');
        console.error(error);
    } finally {
        pushWorking.value = false;
    }
};

const sendPushTest = async () => {
    if (pushWorking.value) return;
    pushWorking.value = true;
    try {
        const response = await fetch('/api/push/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: 'VERA', body: 'Push notifications are active.' }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data?.ok === false) {
            throw new Error(data.error || 'Failed to send test notification');
        }
        showToast('Test notification queued.');
    } catch (error) {
        showToast(error?.message || 'Unable to send test notification');
        console.error(error);
    } finally {
        pushWorking.value = false;
    }
};

const fetchToolInventory = async () => {
    try {
        const response = await fetch('/api/tools/list');
        if (!response.ok) {
            throw new Error('Failed to fetch tool inventory');
        }
        toolInventory.value = await response.json();
    } catch (error) {
        showToast('Unable to fetch tool inventory');
        console.error(error);
    }
};

const startStoppedTools = async () => {
    if (!toolStatus.value) {
        await fetchToolStatus();
    }
    const servers = Object.entries(toolStatus.value?.mcp?.servers || {})
        .filter(([, server]) => !server.running && (!server.missing_env || server.missing_env.length === 0))
        .map(([name]) => name);

    if (!servers.length) {
        showToast('No stopped MCP servers without missing credentials');
        return;
    }
    try {
        const response = await fetch('/api/tools/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ servers })
        });
        if (!response.ok) {
            throw new Error('Failed to start tools');
        }
        await fetchToolStatus();
        await fetchToolInventory();
        showToast('Started stopped MCP servers');
    } catch (error) {
        showToast('Unable to start tools');
        console.error(error);
    }
};

const restartUnhealthyTools = async () => {
    if (!toolStatus.value) {
        await fetchToolStatus();
    }
    const servers = Object.entries(toolStatus.value?.mcp?.servers || {})
        .filter(([, server]) => server.running && server.health && server.health !== 'healthy')
        .map(([name]) => name);

    if (!servers.length) {
        showToast('No unhealthy MCP servers to restart');
        return;
    }
    try {
        const response = await fetch('/api/tools/restart', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ servers })
        });
        if (!response.ok) {
            throw new Error('Failed to restart tools');
        }
        await fetchToolStatus();
        await fetchToolInventory();
        showToast('Restarted unhealthy MCP servers');
    } catch (error) {
        showToast('Unable to restart tools');
        console.error(error);
    }
};

const inventoryCount = computed(() => {
    if (!toolInventory.value?.tools) {
        return 0;
    }
    return Object.values(toolInventory.value.tools).reduce((sum, tools) => sum + tools.length, 0);
});

const googleAuthLabel = computed(() => {
    const status = googleAuthStatus.value?.status;
    if (status === 'authorized') return 'Authorized';
    if (status === 'unauthorized') return 'Unauthorized';
    return 'Unknown';
});

const channelsActiveCount = computed(() => channelsStatus.value?.active?.length || 0);
const channelsConfiguredCount = computed(() => channelsStatus.value?.configured?.specs?.length || 0);
const channelsConfiguredSpecs = computed(() => channelsStatus.value?.configured?.specs || []);

const channelsConfigPath = computed(() => {
    return channelsStatus.value?.configured?.config_path_relative
        || channelsStatus.value?.configured?.config_path
        || 'config/channels.json';
});

const channelsConfigExists = computed(() => {
    return Boolean(channelsStatus.value?.configured?.config_exists);
});

const channelsConfigSource = computed(() => {
    const source = channelsStatus.value?.configured?.source;
    if (source === 'file') return 'channels.json';
    if (source === 'env') return 'VERA_CHANNELS';
    if (source === 'default') return 'default';
    if (source === 'unknown') return 'unknown';
    return 'default';
});

const channelsStatusLabel = computed(() => {
    if (channelsLoading.value) return 'Loading';
    const active = channelsActiveCount.value;
    if (active > 0) return `${active} active`;
    if (channelsStatus.value) return 'No channels';
    return 'Unknown';
});

const channelsStatusDetail = computed(() => {
    if (!channelsStatus.value) return '';
    const configured = channelsConfiguredCount.value;
    const source = channelsStatus.value?.configured?.source;
    if (source === 'env') return `Configured via VERA_CHANNELS (${configured})`;
    if (source === 'file') return `Configured via channels.json (${configured})`;
    if (source === 'default') return 'Using defaults';
    return '';
});

const channelsStatusClass = computed(() => {
    if (channelsLoading.value) return 'unknown';
    if (!channelsStatus.value) return 'unknown';
    if (channelsActiveCount.value > 0) return 'ok';
    return 'warn';
});

const pushSupported = computed(() => {
    if (typeof window === 'undefined') return false;
    return 'Notification' in window && 'serviceWorker' in navigator && 'PushManager' in window;
});

const pushEnabled = computed(() => {
    return pushSupported.value && Boolean(pushConfig.value?.enabled);
});

const pushStatusLabel = computed(() => {
    if (pushWorking.value) return 'Working';
    if (!pushSupported.value) return 'Unsupported';
    if (!pushConfig.value?.enabled) return 'Not configured';
    if (pushSubscribed.value) return 'Subscribed';
    return 'Ready';
});

const pushStatusDetail = computed(() => {
    if (!pushSupported.value) return 'Web Push unavailable in this browser';
    if (pushConfig.value?.enabled === false && pushConfig.value?.reason) {
        return pushConfig.value.reason.replace(/_/g, ' ');
    }
    if (pushPermission.value === 'denied') return 'Permission blocked';
    return '';
});

const pushStatusClass = computed(() => {
    if (!pushSupported.value) return 'unknown';
    if (pushSubscribed.value) return 'ok';
    if (!pushConfig.value?.enabled || pushPermission.value === 'denied') return 'warn';
    return 'unknown';
});

const pushSupportLabel = computed(() => {
    return pushSupported.value ? 'Supported' : 'Unavailable';
});

const pushPermissionLabel = computed(() => {
    if (pushPermission.value === 'granted') return 'Granted';
    if (pushPermission.value === 'denied') return 'Blocked';
    if (pushPermission.value === 'unsupported') return 'Unsupported';
    return 'Ask';
});

const pushConfigHint = computed(() => {
    if (!pushSupported.value) {
        return 'Web Push is not supported in this browser.';
    }
    if (!pushConfig.value?.enabled) {
        if (pushConfig.value?.reason === 'missing_vapid' || pushConfig.value?.reason === 'vapid_not_configured') {
            return 'Add VAPID keys in config/vapid.json or set VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY.';
        }
        if (pushConfig.value?.reason) {
            return `Push disabled: ${pushConfig.value.reason.replace(/_/g, ' ')}`;
        }
        return 'Configure VAPID keys to enable push notifications.';
    }
    if (pushPermission.value === 'denied') {
        return 'Notifications are blocked for this site. Update browser settings to enable.';
    }
    return '';
});

const googleAuthReasonLabel = computed(() => {
    const reason = googleAuthStatus.value?.reason || '';
    if (!reason) return '';
    if (reason === 'missing_user_email') return 'missing user email';
    if (reason === 'missing_oauth_env') return 'missing OAuth env';
    if (reason === 'missing_oauth_client') return 'missing OAuth client';
    if (reason === 'missing_redirect_uri') return 'missing redirect uri';
    if (reason === 'missing_credentials_file') return 'missing credentials';
    return reason.replace(/_/g, ' ');
});

const googleAuthTooltip = computed(() => {
    const status = googleAuthStatus.value || {};
    const lines = [];
    if (status.user_email) {
        lines.push(`User: ${status.user_email}`);
    }
    if (status.credentials_file) {
        lines.push(`Credentials: ${status.credentials_file}`);
    } else if (status.credentials_dir) {
        lines.push(`Credentials dir: ${status.credentials_dir}`);
    }
    if (status.oauth_client_secret_path) {
        lines.push(`Client secrets: ${status.oauth_client_secret_path}`);
    }
    if (status.oauth_redirect_uri) {
        lines.push(`Redirect: ${status.oauth_redirect_uri}`);
    }
    if (status.missing_env && status.missing_env.length) {
        lines.push(`Missing env: ${status.missing_env.join(', ')}`);
    }
    if (typeof status.server_running === 'boolean') {
        lines.push(`MCP running: ${status.server_running ? 'yes' : 'no'}`);
    }
    if (status.server_health) {
        lines.push(`MCP health: ${status.server_health}`);
    }
    if (status.checked_at) {
        const date = new Date(status.checked_at);
        const formatted = Number.isNaN(date.getTime()) ? status.checked_at : date.toLocaleString();
        lines.push(`Last check: ${formatted}`);
    }
    if (status.reason) {
        lines.push(`Reason: ${googleAuthReasonLabel.value}`);
    }
    return lines.join('\n');
});

const googleAuthClass = computed(() => {
    const status = googleAuthStatus.value?.status;
    if (status === 'authorized') return 'ok';
    if (status === 'unauthorized') return 'warn';
    return 'unknown';
});

const googleAuthStartDisabled = computed(() => {
    if (googleAuthStatus.value?.status === 'authorized') {
        return true;
    }
    if (googleAuthStatus.value && googleAuthStatus.value.oauth_ready === false) {
        return true;
    }
    if (googleAuthStatus.value?.missing_env?.length) {
        return true;
    }
    const email = googleAuthStatus.value?.user_email || toolKeys.GOOGLE_WORKSPACE_USER_EMAIL;
    return !(email && email.trim());
});

const startGoogleOAuth = async () => {
    try {
        const email = (googleAuthStatus.value?.user_email || toolKeys.GOOGLE_WORKSPACE_USER_EMAIL || '').trim();
        if (!email) {
            showToast('Set GOOGLE_WORKSPACE_USER_EMAIL first');
            return;
        }
        const response = await fetch('/api/google/auth/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_google_email: email, service_name: 'Gmail' })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || 'Failed to start OAuth');
        }
        if (data.auth_url) {
            window.open(data.auth_url, '_blank', 'noopener,noreferrer');
            showToast(`OAuth URL: ${data.auth_url}`);
        }
        showToast('OAuth flow started. Complete authorization in the new tab.');
        await fetchGoogleAuthStatus({ silent: true });
        const confirmed = await waitForGoogleAuth();
        if (confirmed) {
            showToast('OAuth complete. Google is authorized.');
        }
    } catch (error) {
        showToast(error?.message || 'Failed to start OAuth');
        console.error(error);
    }
};

const submitToolKeys = async () => {
    try {
        const payloadKeys = Object.fromEntries(
            Object.entries(toolKeys).map(([key, value]) => {
                let trimmed = typeof value === 'string' ? value.trim() : value;
                if (key === 'SEARXNG_BASE_URL' && trimmed && !/^https?:\/\//i.test(trimmed)) {
                    trimmed = `http://${trimmed}`;
                }
                return [key, trimmed];
            })
        );
        const response = await fetch('/api/keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keys: payloadKeys, restart: true })
        });
        if (!response.ok) {
            throw new Error('Failed to apply keys');
        }
        Object.keys(toolKeys).forEach((key) => {
            toolKeys[key] = '';
        });
        await refreshToolStatus();
        showToast('Keys applied to VERA');
    } catch (error) {
        showToast('Failed to apply keys');
        console.error(error);
    }
};

onMounted(fetchToolStatus);
onMounted(fetchGoogleAuthStatus);
onMounted(fetchToolInventory);
onMounted(fetchChannelsStatus);
onMounted(fetchPushConfig);
onMounted(refreshPushSubscription);
</script>

<style lang="scss">
// ============================================
// VERA GeneralConfigSection Premium Styling
// Premium glass morphism, sophisticated controls
// Matches ToolsDrawer/SwarmDrawer aesthetic
// ============================================

// Animations
.slide-fade-enter-active,
.slide-fade-leave-active {
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    max-height: 90vh;
}

.slide-fade-enter-from,
.slide-fade-leave-to {
    max-height: 0;
    opacity: 0;
    transform: translateY(-10px);
}

// ============================================
// PREMIUM BUTTON - Global Reset/Action Button
// Glass morphism with subtle glow effects
// ============================================
.clear-prompt-button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    background: rgba(var(--vera-shadow-rgb), 0.6);
    border: 1px solid var(--vera-accent-15);
    border-radius: 8px;
    color: var(--vera-text);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
    backdrop-filter: blur(8px);

    svg {
        width: 14px;
        height: 14px;
        color: var(--vera-accent);
        transition: all 0.3s ease;
    }

    // Shimmer effect on hover
    &::before {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(90deg, transparent, var(--vera-accent-08), transparent);
        transition: left 0.5s ease;
    }

    &:hover {
        border-color: var(--vera-accent-35);
        background: var(--vera-accent-08);
        box-shadow: 0 0 16px var(--vera-accent-12);
        transform: translateY(-1px);

        &::before {
            left: 100%;
        }

        svg {
            filter: drop-shadow(0 0 4px var(--vera-accent));
        }
    }

    &:active {
        transform: translateY(0);
        box-shadow: 0 0 8px var(--vera-accent-10);
    }
}

.p-header {
    padding: 6px;
}

// ============================================
// Tool Keys Card
// ============================================

.tool-keys-card {
    margin-bottom: 18px;
}

.tool-keys-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 14px;
}

.tool-key-group {
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    background: rgba(var(--vera-shadow-rgb), 0.5);
    overflow: hidden;
    transition: all 0.25s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
        box-shadow: 0 0 12px var(--vera-accent-08);
    }

    summary {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 12px 14px;
        font-weight: 600;
        font-size: 0.8125rem;
        cursor: pointer;
        list-style: none;
        color: var(--vera-text);
        background: linear-gradient(135deg, var(--vera-accent-08) 0%, var(--vera-accent-05) 100%);
        transition: all 0.2s ease;
        position: relative;

        &::after {
            content: '▾';
            font-size: 0.6875rem;
            opacity: 0.6;
            transition: transform 0.25s ease;
            color: var(--vera-accent);
        }

        &:hover {
            background: linear-gradient(135deg, var(--vera-accent-10) 0%, var(--vera-accent-05) 100%);
        }
    }

    summary::marker {
        content: '';
    }

    &[open] summary::after {
        transform: rotate(180deg);
    }

    &[open] {
        border-color: var(--vera-accent-soft);
    }
}

.tool-key-meta {
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
    font-weight: 500;
    white-space: nowrap;
    padding: 2px 8px;
    background: var(--vera-accent-10);
    border-radius: 999px;
}

.tool-key-group-body {
    padding: 14px 14px 8px;
    display: grid;
    gap: 12px;
    background: rgba(var(--vera-shadow-rgb), 0.3);
}

// ============================================
// Tool Status Section
// ============================================

.tool-status {
    margin-top: 14px;
    padding: 14px;
    border-radius: 12px;
    background: rgba(var(--vera-shadow-rgb), 0.5);
    border: 1px solid var(--vera-border);
    backdrop-filter: blur(8px);
    transition: all 0.25s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
    }
}

.tool-status-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 600;
    font-size: 0.8125rem;
    margin-bottom: 12px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--vera-border);

    span:first-child {
        background: linear-gradient(135deg, var(--vera-text) 0%, var(--vera-accent) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }

    span:last-child {
        font-size: 0.6875rem;
        padding: 3px 10px;
        background: linear-gradient(135deg, var(--vera-accent-15), var(--vera-accent-05));
        border: 1px solid var(--vera-accent-soft);
        border-radius: 999px;
        color: var(--vera-text);
    }
}

.tool-status ul {
    list-style: none;
    padding: 0;
    margin: 0;
}

.tool-status li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    margin-bottom: 6px;
    border-radius: 8px;
    background: var(--vera-black-40);
    border-left: 3px solid transparent;
    transition: all 0.2s ease;

    &:hover {
        background: var(--vera-accent-05);
        border-left-color: var(--vera-accent);
    }

    &:last-child {
        margin-bottom: 0;
    }
}

.tool-status-empty {
    font-size: 0.7rem;
    color: var(--vera-text-muted);
    padding: 6px 2px 2px;
}

.channel-meta {
    display: grid;
    gap: 6px;
    margin-bottom: 12px;
    font-size: 0.72rem;
    color: var(--vera-text-muted);
}

.channel-meta-row {
    display: flex;
    justify-content: space-between;
    gap: 10px;
}

.channel-meta-value {
    font-weight: 600;
    color: var(--vera-text);
    text-align: right;
    word-break: break-word;
}

.channel-configs {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 12px;
}

.channel-config-chip {
    font-size: 0.68rem;
    padding: 4px 8px;
    border-radius: 999px;
    border: 1px solid var(--vera-border);
    background: rgba(var(--vera-shadow-rgb), 0.4);
    color: var(--vera-text);
}

.channel-config-chip.enabled {
    border-color: var(--vera-success-50);
    color: var(--vera-success);
    background: var(--vera-success-10);
}

.channel-config-chip.disabled {
    border-color: var(--vera-warning-40);
    color: var(--vera-warning);
    background: var(--vera-warning-10);
}

.channels-card .prompt-description code,
.channel-hint code {
    font-family: var(--vera-font-mono);
    font-size: 0.68rem;
    padding: 2px 6px;
    border-radius: 6px;
    background: rgba(var(--vera-shadow-rgb), 0.35);
    border: 1px solid var(--vera-border);
}

.channel-hint {
    margin-top: 10px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    font-size: 0.7rem;
    color: var(--vera-text-muted);
}

.tool-name {
    font-weight: 600;
    font-size: 0.75rem;
}

.tool-health {
    font-size: 0.6875rem;
    text-transform: capitalize;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid transparent;
}

.tool-state {
    font-size: 0.6875rem;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid transparent;

    &.ok {
        color: var(--vera-success);
        background: var(--vera-success-15);
        border-color: var(--vera-success-40);
    }

    &.warn {
        color: var(--vera-warning);
        background: var(--vera-warning-15);
        border-color: var(--vera-warning-40);
    }
}

.tool-health.ok {
    color: var(--vera-success);
    background: var(--vera-success-15);
    border-color: var(--vera-success-40);
}

.tool-health.warn {
    color: var(--vera-warning);
    background: var(--vera-warning-15);
    border-color: var(--vera-warning-40);
}

.tool-missing {
    color: var(--vera-danger);
    font-size: 0.6875rem;
    background: var(--vera-error-10);
    padding: 2px 8px;
    border-radius: 999px;
}

.tool-actions {
    display: flex;
    gap: 6px;
    margin-top: 14px;
    padding: 6px;
    background: rgba(var(--vera-shadow-rgb), 0.6);
    border: 1px solid var(--vera-border);
    border-radius: 10px;

    button {
        flex: 1;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        padding: 8px 10px;
        font-size: 0.6875rem;
        font-weight: 500;
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        color: var(--vera-text-muted);
        cursor: pointer;
        transition: all 0.25s ease;
        white-space: nowrap;

        svg {
            flex-shrink: 0;
            opacity: 0.7;
        }

        &:hover {
            background: var(--vera-accent-10);
            border-color: var(--vera-accent-25);
            color: var(--vera-text);

            svg {
                opacity: 1;
                color: var(--vera-accent);
            }
        }

        // Override the save/clear button styles within tool-actions
        &.save-prompt-button,
        &.clear-prompt-button {
            background: transparent;
            border: 1px solid transparent;
            padding: 8px 10px;

            &:hover {
                background: var(--vera-accent-10);
                border-color: var(--vera-accent-25);
                box-shadow: none;
            }
        }
    }
}

// ============================================
// Tool Inventory Section
// ============================================

.tool-inventory {
    margin-top: 14px;
    padding: 14px;
    border-radius: 12px;
    border: 1px solid var(--vera-border);
    background: rgba(var(--vera-shadow-rgb), 0.5);
    backdrop-filter: blur(8px);
    transition: all 0.25s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
    }
}

.tool-inventory-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 10px;

    details {
        background: var(--vera-black-40);
        border-radius: 8px;
        padding: 0;
        transition: all 0.2s ease;

        &:hover {
            background: var(--vera-accent-05);
        }

        &[open] {
            background: var(--vera-accent-05);
            border: 1px solid var(--vera-accent-soft);
        }
    }

    summary {
        cursor: pointer;
        font-weight: 600;
        font-size: 0.75rem;
        padding: 10px 12px;
        transition: all 0.2s ease;

        &:hover {
            color: var(--vera-accent);
        }
    }
}

.tool-list {
    margin: 0;
    padding: 0 12px 12px;
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
    line-height: 1.5;
}

// ============================================
// Config Section (Voice & Audio, Accessibility)
// ============================================

.config-section {
    margin-bottom: 18px;
    border-radius: 14px;
    overflow: hidden;
    background: rgba(var(--vera-shadow-rgb), 0.72);
    backdrop-filter: blur(16px);
    border: 1px solid var(--vera-border);
    position: relative;
    opacity: 0;
    animation: cardSlideIn 0.5s ease forwards;
    animation-delay: 0.1s;
    transition: all 0.3s ease;

    // Corner accent
    &::before {
        content: '';
        position: absolute;
        top: -1px;
        left: -1px;
        width: 24px;
        height: 24px;
        border-top: 2px solid var(--vera-accent-soft);
        border-left: 2px solid var(--vera-accent-soft);
        border-radius: 14px 0 0 0;
        opacity: 0;
        transition: opacity 0.3s ease;
        z-index: 1;
    }

    &:hover {
        border-color: var(--vera-accent-soft);
        box-shadow:
            0 0 20px var(--vera-accent-10),
            inset 0 0 30px var(--vera-accent-03);
        transform: translateY(-2px);

        &::before {
            opacity: 1;
        }
    }

    @media (max-width: 600px) {
        margin-bottom: 14px;
    }

    .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 14px 16px;
        cursor: pointer;
        background: linear-gradient(135deg, var(--vera-accent-08) 0%, var(--vera-accent-05) 100%);
        transition: all 0.25s ease;
        position: relative;

        // Animated underline
        &::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 16px;
            width: 40px;
            height: 2px;
            background: linear-gradient(90deg, var(--vera-accent), transparent);
            transition: width 0.3s ease;
        }

        @media (max-width: 600px) {
            padding: 12px 14px;
        }

        &:hover {
            background: linear-gradient(135deg, var(--vera-accent-12) 0%, var(--vera-accent-05) 100%);

            &::after {
                width: 60px;
            }
        }

        h3 {
            margin: 0;
            display: flex;
            align-items: center;
            font-size: 0.875rem;
            font-weight: 600;
            background: linear-gradient(135deg, var(--vera-text) 0%, var(--vera-accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;

            .section-icon {
                margin-right: 10px;
                color: var(--vera-accent);
                filter: drop-shadow(0 0 4px var(--vera-accent-soft));
                // Reset the gradient text for icon
                -webkit-text-fill-color: initial;
            }

            @media (max-width: 600px) {
                font-size: 0.8125rem;
            }
        }

        .indicator {
            color: var(--vera-accent);
            transition: transform 0.25s ease;
        }
    }

    .avatar-content,
    .accessibility-content,
    .voice-content,
    .theme-content {
        padding: 16px;
        background: var(--vera-black-40);

        .enable-avatars {
            margin-bottom: 20px;

            @media (max-width: 600px) {
                margin-bottom: 24px;
            }
        }

        @media (max-width: 600px) {
            padding: 14px;
        }
    }
}

@keyframes cardSlideIn {
    0% {
        opacity: 0;
        transform: translateY(15px) scale(0.98);
    }
    60% {
        transform: translateY(-3px) scale(1.01);
    }
    100% {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}

.avatar-settings {
    display: flex;
    flex-direction: column;
    gap: 20px;
    
    @media (max-width: 600px) {
        gap: 24px;
    }
    
    .settings-selector {
        h4 {
            margin: 0 0 10px 0;
            font-size: 1rem;
            font-weight: 500;
            color: var(--vera-text);
            
            @media (max-width: 600px) {
                margin-bottom: 12px;
            }
        }
    }
    
    .avatar-selector {
        width: 100%;
        
        @media (max-width: 600px) {
            display: flex;
            
            .p-button {
                flex: 1;
            }
        }
    }
    
    .avatar-url-field {
        margin-bottom: 10px;
    }
    
    .avatar-upload-section {
        background-color: var(--vera-accent-faint);
        border-radius: 8px;
        padding: 16px;
        margin-top: 10px;
        
        h4 {
            margin: 0 0 14px 0;
            font-size: 1rem;
            font-weight: 500;
            color: var(--vera-text);
        }
        
        .avatar-list-container {
            margin-top: 14px;
            max-height: 300px;
            
            @media (max-width: 600px) {
                max-height: 200px;
            }
        }
    }
}

.voice-content,
.theme-content {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.voice-selector,
.theme-selector {
    width: 100%;
}

.theme-preset-controls {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
}

.range-slider {
    accent-color: var(--vera-accent);
    width: min(240px, 100%);
}

.theme-value {
    font-size: 0.75rem;
    color: var(--vera-text-muted);
}

.file-input {
    color: var(--vera-text-muted);
    font-size: 0.75rem;
}

.voice-row,
.theme-row {
    display: flex;
    flex-direction: column;
    gap: 8px;

    h4 {
        margin: 0;
        font-size: 1rem;
        font-weight: 600;
        color: var(--vera-text);
    }
}

.voice-hint,
.theme-hint {
    margin: 4px 0 0;
    font-size: 0.8125rem;
    color: var(--vera-text-muted);
}

.voice-status {
    background: rgba(var(--vera-shadow-rgb), 0.5);
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    padding: 14px;
    font-size: 0.75rem;
    color: var(--vera-text);
    display: flex;
    flex-direction: column;
    gap: 8px;
    transition: all 0.2s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
    }

    div {
        display: flex;
        gap: 8px;

        strong {
            color: var(--vera-text-muted);
            min-width: 70px;
        }
    }
}

.voice-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding-top: 8px;
}

.accent-controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
}

.accent-picker {
    width: 44px;
    height: 34px;
    border: 1px solid var(--vera-border);
    background: transparent;
    border-radius: 8px;
    padding: 2px;
    cursor: pointer;
}

.accent-swatches {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

.accent-swatch {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    border: 1px solid var(--vera-border);
    background: transparent;
    padding: 2px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;

    span {
        width: 100%;
        height: 100%;
        border-radius: 50%;
        display: block;
    }

    &.active {
        border-color: var(--vera-accent);
        box-shadow: 0 0 0 2px var(--vera-accent-faint);
    }
}

.avatar-option {
    display: flex;
    align-items: center;
    padding: 8px 0;
    
    .avatar-filename {
        margin-left: 10px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
}

.empty-list {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 20px;
    text-align: center;
    color: var(--vera-text-muted);
    
    p {
        margin-top: 12px;
        font-size: 0.875rem;
    }
}

// ============================================
// PREMIUM SELECTBUTTON - Glass Morphism Design
// Replaces the ugly basic bordered buttons
// ============================================
.p-selectbutton {
    display: inline-flex;
    gap: 2px;
    padding: 3px;
    background: rgba(var(--vera-shadow-rgb), 0.7);
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    backdrop-filter: blur(8px);

    .p-button {
        background: transparent;
        border: none;
        border-radius: 8px;
        color: var(--vera-text-muted);
        padding: 10px 16px;
        font-size: 0.75rem;
        font-weight: 500;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;

        // Shimmer on hover
        &::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, var(--vera-white-05), transparent);
            transition: left 0.4s ease;
        }

        &:hover::before {
            left: 100%;
        }

        &.p-highlight {
            background: linear-gradient(135deg, var(--vera-accent-25), var(--vera-accent-10));
            color: var(--vera-text);
            box-shadow:
                0 0 16px var(--vera-accent-20),
                inset 0 1px 0 var(--vera-white-08);
        }

        &:not(.p-highlight):hover {
            background: var(--vera-accent-08);
            color: var(--vera-text);
        }

        @media (max-width: 600px) {
            padding: 12px 14px;
        }
    }
}

.custom-upload-button {
    border: 1px solid var(--vera-accent);
    color: var(--vera-accent);
    background-color: transparent;
    transition: all 0.2s ease;
    width: 100%;
    display: flex;
    justify-content: center;
    padding: 10px;
    border-radius: 4px;
    cursor: pointer;
    
    @media (max-width: 600px) {
        padding: 12px;
    }

    &:hover {
        background-color: var(--vera-accent-faint);
        border-color: var(--vera-accent-strong);
    }
    
    &:active {
        transform: translateY(1px);
    }
}

.avatar-listbox {
    border: 1px solid var(--vera-accent-soft);
    border-radius: 6px;
    
    &:deep(.p-listbox-header) {
        background-color: var(--vera-accent-faint);
        border-bottom: 1px solid var(--vera-accent-soft);
    }
    
    &:deep(.p-listbox-filter-container) {
        padding: 12px;
        
        .p-inputtext {
            background-color: var(--vera-input-bg);
            border: 1px solid var(--vera-border);
            color: var(--vera-text);
            border-radius: 4px;
            padding: 8px 12px;
            width: 100%;
            
            &:focus {
                border-color: var(--vera-accent);
                box-shadow: 0 0 0 2px var(--vera-accent-faint);
            }
        }
    }
    
    &:deep(.p-listbox-list) {
        padding: 8px;
    }
    
    &:deep(.p-listbox-item) {
        border-radius: 4px;
        margin-bottom: 4px;
        transition: background-color 0.2s ease;
        
        &:hover {
            background-color: var(--vera-accent-faint);
        }
        
        &.p-highlight {
            background-color: var(--vera-accent-soft);
        }
    }
}

.flex {
    display: flex;
}

.align-items-center {
    align-items: center;
}

.ml-2 {
    margin-left: 0.5rem;
}

.slide-fade-enter-active,
.slide-fade-leave-active {
    transition: all 0.15s linear;
    max-height: 90vh;
}

.slide-fade-enter-from,
.slide-fade-leave-to {
    max-height: 0;
    opacity: 0;
    transform: translateY(-20px);
}


.avatar-url-container {
    margin-top: 10px;
}

.p-dropdown {
    background-color: transparent;
    border-bottom: 2px solid var(--vera-accent);
    border-top: none;
    border-left: none;
    border-right: none;
    width: auto;
    max-width: 80%;
    cursor: pointer;
    font-size: 1rem;

    &:hover {
        background-color: var(--vera-panel-alt);
    }

    &:focus {
        outline: none;
    }
}

.p-listbox {

    .p-icon {
        color: var(--vera-accent);
        right: 14px;
        top: 11px;
    }
}

// ============================================
// System Prompt Card - Premium Styling
// ============================================

.system-prompt-card {
    margin-bottom: 18px;
    background: rgba(var(--vera-shadow-rgb), 0.72);
    backdrop-filter: blur(16px);
    border: 1px solid var(--vera-border);
    border-radius: 14px;
    overflow: hidden;
    position: relative;
    opacity: 0;
    animation: cardSlideIn 0.5s ease forwards;
    transition: all 0.3s ease;

    // Corner accent
    &::before {
        content: '';
        position: absolute;
        top: -1px;
        left: -1px;
        width: 24px;
        height: 24px;
        border-top: 2px solid var(--vera-accent-soft);
        border-left: 2px solid var(--vera-accent-soft);
        border-radius: 14px 0 0 0;
        opacity: 0;
        transition: opacity 0.3s ease;
        z-index: 1;
    }

    &:hover {
        border-color: var(--vera-accent-soft);
        box-shadow:
            0 0 20px var(--vera-accent-10),
            inset 0 0 30px var(--vera-accent-03);
        transform: translateY(-2px);

        &::before {
            opacity: 1;
        }
    }

    @media (max-width: 600px) {
        margin-bottom: 14px;
    }

    .prompt-header {
        display: flex;
        align-items: center;
        padding: 14px 16px;
        background: linear-gradient(135deg, var(--vera-accent-08) 0%, var(--vera-accent-05) 100%);
        position: relative;

        // Animated underline
        &::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 16px;
            width: 40px;
            height: 2px;
            background: linear-gradient(90deg, var(--vera-accent), transparent);
        }

        h3 {
            margin: 0;
            font-size: 0.875rem;
            font-weight: 600;
            margin-left: 10px;
            background: linear-gradient(135deg, var(--vera-text) 0%, var(--vera-accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .section-icon {
            color: var(--vera-accent);
            filter: drop-shadow(0 0 4px var(--vera-accent-soft));
        }

        .auth-status {
            margin-left: auto;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 999px;
            border: 1px solid var(--vera-border);
            font-size: 0.6875rem;
            font-weight: 600;
            color: var(--vera-text-muted);
            background: rgba(var(--vera-shadow-rgb), 0.6);
            backdrop-filter: blur(8px);
            transition: all 0.2s ease;
        }

        .auth-status.ok {
            color: var(--vera-success);
            border-color: var(--vera-success-50);
            background: var(--vera-success-10);
            box-shadow: 0 0 10px var(--vera-success-15);
        }

        .auth-status.warn {
            color: var(--vera-warning);
            border-color: var(--vera-warning-50);
            background: var(--vera-warning-10);
        }

        .auth-status.unknown {
            color: var(--vera-text-muted);
            border-color: var(--vera-border);
            background: rgba(var(--vera-shadow-rgb), 0.5);
        }

        .auth-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: currentColor;
            animation: statusPulse 2s ease-in-out infinite;
        }

        .auth-status.has-reason {
            padding-top: 6px;
            padding-bottom: 6px;
        }

        .auth-text {
            display: flex;
            flex-direction: column;
            line-height: 1.2;
        }

        .auth-reason {
            font-size: 0.625rem;
            font-weight: 500;
            opacity: 0.8;
        }
    }

    .prompt-content {
        padding: 16px;
        background: var(--vera-black-40);

        .prompt-description {
            margin: 0 0 14px 0;
            font-size: 0.75rem;
            line-height: 1.6;
            color: var(--vera-text-muted);
        }

        .prompt-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 14px;

            button {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 6px;
                padding: 10px 14px;
                border-radius: 10px;
                cursor: pointer;
                font-size: 0.75rem;
                font-weight: 500;
                border: 1px solid var(--vera-border);
                transition: all 0.25s ease;
                position: relative;
                overflow: hidden;

                // Shimmer effect
                &::before {
                    content: '';
                    position: absolute;
                    top: 0;
                    left: -100%;
                    width: 100%;
                    height: 100%;
                    background: linear-gradient(90deg, transparent, var(--vera-white-10), transparent);
                    transition: left 0.4s ease;
                }

                &:hover::before {
                    left: 100%;
                }

                svg {
                    transition: transform 0.2s ease;
                }

                &:hover svg {
                    transform: translateY(-1px);
                }

                &:active {
                    transform: translateY(1px);
                }

                &:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                    &:hover {
                        transform: none;
                    }
                    &::before {
                        display: none;
                    }
                }
            }

            .save-prompt-button {
                background: linear-gradient(135deg, var(--vera-accent-20), var(--vera-accent-10));
                border-color: var(--vera-accent-soft);
                color: var(--vera-text);
                box-shadow: 0 0 10px var(--vera-accent-15);

                svg {
                    color: var(--vera-accent);
                }

                &:hover {
                    box-shadow: 0 0 16px var(--vera-accent-25);
                    transform: translateY(-1px);
                }
            }

            .clear-prompt-button {
                background: rgba(var(--vera-shadow-rgb), 0.5);
                border-color: var(--vera-border);
                color: var(--vera-text);

                svg {
                    color: var(--vera-text-muted);
                }

                &:hover {
                    border-color: var(--vera-accent-soft);
                    box-shadow: 0 0 10px var(--vera-accent-10);
                }
            }
        }
    }
}

@keyframes statusPulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
}

// ============================================
// Saved System Prompts Section - Premium Styling
// ============================================

.saved-system-prompts-section {
    margin-bottom: 18px;
    border-radius: 14px;
    overflow: hidden;
    background: rgba(var(--vera-shadow-rgb), 0.72);
    backdrop-filter: blur(16px);
    border: 1px solid var(--vera-border);
    position: relative;
    opacity: 0;
    animation: cardSlideIn 0.5s ease forwards;
    animation-delay: 0.05s;
    transition: all 0.3s ease;

    // Corner accent
    &::before {
        content: '';
        position: absolute;
        top: -1px;
        left: -1px;
        width: 24px;
        height: 24px;
        border-top: 2px solid var(--vera-accent-soft);
        border-left: 2px solid var(--vera-accent-soft);
        border-radius: 14px 0 0 0;
        opacity: 0;
        transition: opacity 0.3s ease;
        z-index: 1;
    }

    &:hover {
        border-color: var(--vera-accent-soft);
        box-shadow:
            0 0 20px var(--vera-accent-10),
            inset 0 0 30px var(--vera-accent-03);

        &::before {
            opacity: 1;
        }
    }

    @media (max-width: 600px) {
        margin-bottom: 14px;
    }

    .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 14px 16px;
        cursor: pointer;
        background: linear-gradient(135deg, var(--vera-accent-08) 0%, var(--vera-accent-05) 100%);
        transition: all 0.25s ease;
        position: relative;

        // Animated underline
        &::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 16px;
            width: 40px;
            height: 2px;
            background: linear-gradient(90deg, var(--vera-accent), transparent);
            transition: width 0.3s ease;
        }

        @media (max-width: 600px) {
            padding: 12px 14px;
        }

        &:hover {
            background: linear-gradient(135deg, var(--vera-accent-12) 0%, var(--vera-accent-05) 100%);

            &::after {
                width: 60px;
            }
        }

        h4 {
            margin: 0;
            display: flex;
            align-items: center;
            font-size: 0.8125rem;
            font-weight: 600;
            background: linear-gradient(135deg, var(--vera-text) 0%, var(--vera-accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;

            .section-icon {
                margin-right: 10px;
                color: var(--vera-accent);
                filter: drop-shadow(0 0 4px var(--vera-accent-soft));
                -webkit-text-fill-color: initial;
            }

            @media (max-width: 600px) {
                font-size: 0.75rem;
            }
        }

        .indicator {
            color: var(--vera-accent);
            transition: transform 0.25s ease;
        }
    }
}

.saved-system-prompts {
    padding: 14px 16px;
    background: var(--vera-black-40);

    @media (max-width: 600px) {
        padding: 12px 14px;
    }

    .no-prompts {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 28px 20px;
        background: rgba(var(--vera-shadow-rgb), 0.5);
        border-radius: 10px;
        text-align: center;
        color: var(--vera-text-muted);
        border: 1px dashed var(--vera-border);
        transition: all 0.2s ease;

        svg {
            opacity: 0.5;
            color: var(--vera-accent);
        }

        @media (max-width: 600px) {
            padding: 20px 16px;
        }

        p {
            margin-top: 12px;
            font-size: 0.75rem;
            line-height: 1.5;
        }

        &:hover {
            border-color: var(--vera-accent-soft);
            background: var(--vera-accent-03);
        }
    }

    .prompts-container {
        ul {
            list-style-type: none;
            padding: 0;
            margin: 0;
            max-height: 180px;
            overflow-y: auto;
            scrollbar-width: thin;

            // Custom scrollbar
            &::-webkit-scrollbar {
                width: 5px;
            }
            &::-webkit-scrollbar-track {
                background: var(--vera-black-20);
                border-radius: 3px;
            }
            &::-webkit-scrollbar-thumb {
                background: var(--vera-accent-soft);
                border-radius: 3px;
                &:hover {
                    background: var(--vera-accent);
                }
            }

            @media (max-width: 600px) {
                max-height: 200px;
            }

            li {
                padding: 0;
                background: rgba(var(--vera-shadow-rgb), 0.5);
                border-radius: 8px;
                margin-bottom: 6px;
                overflow: hidden;
                text-align: left;
                cursor: pointer;
                transition: all 0.2s ease;
                border-left: 3px solid transparent;
                border: 1px solid transparent;

                &:hover {
                    background: var(--vera-accent-05);
                    border-color: var(--vera-border);
                    border-left-color: var(--vera-accent);
                }

                &.selected {
                    background: linear-gradient(135deg, var(--vera-accent-15) 0%, var(--vera-accent-05) 100%);
                    border-left: 3px solid var(--vera-accent);
                    border-color: var(--vera-accent-soft);
                    box-shadow: inset 0 0 20px var(--vera-accent-05);
                }

                .prompt-item-content {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 12px;

                    @media (max-width: 600px) {
                        padding: 10px;
                    }

                    .prompt-text {
                        flex: 1;
                        overflow: hidden;
                        text-overflow: ellipsis;
                        white-space: nowrap;
                        padding-right: 10px;
                        font-size: 0.75rem;
                    }

                    .delete-prompt-btn {
                        background: transparent;
                        border: 1px solid transparent;
                        color: var(--vera-text-muted);
                        cursor: pointer;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        padding: 6px;
                        border-radius: 6px;
                        transition: all 0.2s ease;

                        &:hover {
                            background: var(--vera-error-15);
                            border-color: var(--vera-error-40);
                            color: var(--vera-danger);
                        }
                    }
                }
            }
        }
    }
}

// ============================================
// Control Checkbox - Premium Styling
// ============================================

.control-checkbox {
    display: flex;
    align-items: center;
    width: 100%;
    padding: 14px 16px;
    background: rgba(var(--vera-shadow-rgb), 0.5);
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    margin-bottom: 0;
    transition: all 0.2s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
        background: var(--vera-accent-03);
    }

    @media (max-width: 600px) {
        padding: 12px 14px;
    }

    label {
        display: flex;
        align-items: center;
        justify-content: space-between;
        cursor: pointer;
        font-size: 0.8125rem;
        color: var(--vera-text);
        position: relative;
        width: 100%;
        user-select: none;

        @media (max-width: 600px) {
            font-size: 0.75rem;
        }

        input[type="checkbox"] {
            opacity: 0;
            width: 0;
            height: 0;

            &:checked+.slider:before {
                transform: translateX(22px);
            }

            &:checked+.slider {
                background: linear-gradient(135deg, var(--vera-accent), var(--vera-accent-70));
                border-color: var(--vera-accent);
                box-shadow: 0 0 12px var(--vera-accent-30);
            }
        }

        .slider {
            width: 44px;
            height: 22px;
            background: rgba(var(--vera-shadow-rgb), 0.6);
            border: 1px solid var(--vera-border);
            border-radius: 999px;
            transition: all 0.25s ease;
            position: relative;
            margin-left: 12px;

            @media (max-width: 600px) {
                width: 48px;
                height: 24px;
            }

            &:before {
                position: absolute;
                content: "";
                height: 16px;
                width: 16px;
                left: 2px;
                bottom: 2px;
                background: var(--vera-text);
                border-radius: 50%;
                transition: all 0.25s ease;
                box-shadow: 0 2px 4px var(--vera-black-30);

                @media (max-width: 600px) {
                    height: 18px;
                    width: 18px;
                }
            }
        }
    }
}

.select-dropdown select {
    appearance: none;
    background-color: var(--vera-panel-alt);
    color: var(--vera-text);
    max-width: 65vw;
    height: 40px;
    width: 100%;
    padding-left: 6px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 1rem;

    &:hover {
        background-color: var(--vera-panel);
    }

    &:focus {
        outline: none;
    }
}

.select-dropdown option {
    background-color: var(--vera-panel-muted);
    color: var(--vera-text);
}

// ============================================
// Reduced Motion Support
// ============================================

@media (prefers-reduced-motion: reduce) {
    .system-prompt-card,
    .saved-system-prompts-section,
    .config-section,
    .auth-dot {
        animation: none !important;
    }

    .system-prompt-card,
    .saved-system-prompts-section,
    .config-section {
        opacity: 1;
    }

    .slide-fade-enter-active,
    .slide-fade-leave-active {
        transition-duration: 0.01s;
    }
}

</style>
