// state.js
import { ref, computed } from 'vue';
import { loadConversationTitles, loadStoredConversations } from '@/libs/api-access/gpt-api-access';
import { removeAPIEndpoints } from '@/libs/utils/general-utils';
import {
    DEFAULT_SECONDARY_ACCENT,
    DEFAULT_TERMINAL_COLORS,
    DEFAULT_STATUS_COLORS,
    DEFAULT_EVENT_COLORS,
    DEFAULT_GIT_COLORS,
    DEFAULT_DRAWER_THEME,
    DEFAULT_CODE_EDITOR_THEME,
    DEFAULT_TERMINAL_PANEL_THEME,
    DEFAULT_FILE_BROWSER_THEME,
    DEFAULT_DIALOG_CONTENT_THEME,
    DEFAULT_CARD_THEME,
    DEFAULT_FILTER_BUTTON_THEME,
    DEFAULT_THEME_RESET,
    DEFAULT_HEADER_THEME,
    DEFAULT_INPUT_BAR_THEME,
    DEFAULT_TOOL_CARD_THEME,
    DEFAULT_USER_MESSAGE_THEME,
    DEFAULT_ASSISTANT_MESSAGE_THEME,
    DEFAULT_BUTTON_THEME,
    DEFAULT_THINKING_DROPDOWN_THEME,
    DEFAULT_VOICE_COLORS,
    DEFAULT_NIXIE_THEME,
    DEFAULT_EXIT_BUTTON_THEME,
    DEFAULT_NIXIE_BUTTON_THEME,
    DEFAULT_AVATAR_STYLE,
    DEFAULT_AVATAR_ICON_COLORS
} from '@/libs/utils/theme-defaults';

const parseStoredJson = (key, fallback) => {
    try {
        const raw = localStorage.getItem(key);
        if (!raw) return fallback;
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : fallback;
    } catch (error) {
        return fallback;
    }
};

export const pushToTalkMode = ref((JSON.parse(localStorage.getItem("use-push-to-talk")) || false));
export const useWhisper = ref((JSON.parse(localStorage.getItem("use-whisper") || false)));
export const audioSpeed = ref((parseFloat(localStorage.getItem("audio-speed")) || 1.0));
export const ttsModel = ref((localStorage.getItem("tts-model") || 'tts-1'));
export const ttsVoice = ref((localStorage.getItem("tts-voice") || 'nova'));
export const whisperTemperature = ref(parseFloat(localStorage.getItem("whisper-temperature") || 0.35));
export const audioQueue = ref([]);
export const audioIsPlaying = ref(false);
export const availableModels = ref([
    { id: 'grok-4-1-fast-reasoning', name: 'grok-4-1-fast-reasoning' },
    { id: 'grok-4-1-fast', name: 'grok-4-1-fast' },
    { id: 'grok-code-fast-1', name: 'grok-code-fast-1' },
    { id: 'grok-3', name: 'grok-3' },
    { id: 'grok-imagine-image', name: 'grok-imagine-image' },
    { id: 'grok-imagine-video', name: 'grok-imagine-video' }
]);
export const showStoredFiles = ref(false);
export const conversationLoadTimestamp = ref(0);
export const scrollRequestTimestamp = ref(0);

export const isAvatarEnabled = ref((JSON.parse(localStorage.getItem("isAvatarEnabled")) || false));
export const avatarShape = ref(localStorage.getItem("avatarShape") || 'circle');
export const avatarUrl = ref((localStorage.getItem("avatarUrl") || ""));
export const userAvatarUrl = ref((localStorage.getItem("userAvatarUrl") || ""));

export const contextMenuOpened = ref(false);
export const shouldShowScrollButton = ref(false);
export const userText = ref('');
export const isLoading = ref(false);
export const hasFilterText = ref(false);
export const selectedModel = ref(localStorage.getItem('selectedModel') || 'open-ai-format');
export const isSidebarOpen = ref(false);
export const showConversationOptions = ref(false);
export const messages = ref([]);
export const streamedMessageText = ref('');
export const modelDisplayName = ref('Unknown');
export const higherContrastMessages = ref(localStorage.getItem("higherContrastMessages") || false);
export const isInteractModeOpen = ref(false);
export const isVoiceModeOpen = ref(false);
export const voiceAgentVoice = ref(localStorage.getItem('voice-agent-voice') || 'eve');
export const voiceModeStatus = ref('idle');
export const voiceModeLevel = ref(0);
export const quorumAutoEnabled = ref((JSON.parse(localStorage.getItem("quorumAutoEnabled")) || false));
export const swarmAutoEnabled = ref((JSON.parse(localStorage.getItem("swarmAutoEnabled")) || false));
export const pendingQuorumMode = ref(null);
export const pendingQuorumName = ref('');
export const quorumUiMode = ref(null);
export const quorumUiActive = ref(false);

export const localModelKey = ref(localStorage.getItem('localModelKey') || '');
export const localModelName = ref(localStorage.getItem('localModelName') || 'grok-4-1-fast-reasoning');
export const localModelEndpoint = ref(removeAPIEndpoints(localStorage.getItem('localModelEndpoint') || window.location.origin));
export const localSliderValue = ref(parseFloat(localStorage.getItem('local-attitude')) || 0.6);
export const gptKey = ref(localStorage.getItem('gptKey') || '');
export const sliderValue = ref(parseFloat(localStorage.getItem('gpt-attitude')) || 0.5);
export const claudeKey = ref(localStorage.getItem('claudeKey') || '');
export const claudeSliderValue = ref(parseFloat(localStorage.getItem('claude-attitude')) || 0.5);
export const selectedDallEImageCount = ref(parseInt(localStorage.getItem('selectedDallEImageCount')) || 1);
export const selectedDallEImageResolution = ref(localStorage.getItem('selectedDallEImageResolution') || '256x256');
export const selectedAutoSaveOption = ref(localStorage.getItem('selectedAutoSaveOption') || true);
export const uiThemeMode = ref(localStorage.getItem('uiThemeMode') || 'system');
export const uiThemeNativeMode = ref(localStorage.getItem('uiThemeNativeMode') || 'dark'); // Native mode of current theme preset
export const uiAccentColor = ref(localStorage.getItem('uiAccentColor') || '#0099ff');
export const uiSecondaryAccent = ref(localStorage.getItem('uiSecondaryAccent') || DEFAULT_SECONDARY_ACCENT);
export const uiThemeOverrides = ref(parseStoredJson('uiThemeOverrides', {}));

// Terminal colors
export const uiTerminalBackground = ref(localStorage.getItem('uiTerminalBackground') || DEFAULT_TERMINAL_COLORS.background);
export const uiTerminalForeground = ref(localStorage.getItem('uiTerminalForeground') || DEFAULT_TERMINAL_COLORS.foreground);
export const uiTerminalCursor = ref(localStorage.getItem('uiTerminalCursor') || DEFAULT_TERMINAL_COLORS.cursor);
export const uiTerminalSelection = ref(localStorage.getItem('uiTerminalSelection') || DEFAULT_TERMINAL_COLORS.selection);
export const uiTerminalBlack = ref(localStorage.getItem('uiTerminalBlack') || DEFAULT_TERMINAL_COLORS.black);
export const uiTerminalRed = ref(localStorage.getItem('uiTerminalRed') || DEFAULT_TERMINAL_COLORS.red);
export const uiTerminalGreen = ref(localStorage.getItem('uiTerminalGreen') || DEFAULT_TERMINAL_COLORS.green);
export const uiTerminalYellow = ref(localStorage.getItem('uiTerminalYellow') || DEFAULT_TERMINAL_COLORS.yellow);
export const uiTerminalBlue = ref(localStorage.getItem('uiTerminalBlue') || DEFAULT_TERMINAL_COLORS.blue);
export const uiTerminalMagenta = ref(localStorage.getItem('uiTerminalMagenta') || DEFAULT_TERMINAL_COLORS.magenta);
export const uiTerminalCyan = ref(localStorage.getItem('uiTerminalCyan') || DEFAULT_TERMINAL_COLORS.cyan);
export const uiTerminalWhite = ref(localStorage.getItem('uiTerminalWhite') || DEFAULT_TERMINAL_COLORS.white);

// Status/Event colors
export const uiStatusSuccess = ref(localStorage.getItem('uiStatusSuccess') || DEFAULT_STATUS_COLORS.success);
export const uiStatusWarning = ref(localStorage.getItem('uiStatusWarning') || DEFAULT_STATUS_COLORS.warning);
export const uiStatusError = ref(localStorage.getItem('uiStatusError') || DEFAULT_STATUS_COLORS.error);
export const uiStatusInfo = ref(localStorage.getItem('uiStatusInfo') || DEFAULT_STATUS_COLORS.info);

// Event type colors (thinking display, activity drawer)
export const uiEventRouting = ref(localStorage.getItem('uiEventRouting') || DEFAULT_EVENT_COLORS.routing);
export const uiEventMemory = ref(localStorage.getItem('uiEventMemory') || DEFAULT_EVENT_COLORS.memory);
export const uiEventTool = ref(localStorage.getItem('uiEventTool') || DEFAULT_EVENT_COLORS.tool);
export const uiEventDecision = ref(localStorage.getItem('uiEventDecision') || DEFAULT_EVENT_COLORS.decision);
export const uiEventQuorum = ref(localStorage.getItem('uiEventQuorum') || DEFAULT_EVENT_COLORS.quorum);

// Git status colors
export const uiGitAdded = ref(localStorage.getItem('uiGitAdded') || DEFAULT_GIT_COLORS.added);
export const uiGitModified = ref(localStorage.getItem('uiGitModified') || DEFAULT_GIT_COLORS.modified);
export const uiGitDeleted = ref(localStorage.getItem('uiGitDeleted') || DEFAULT_GIT_COLORS.deleted);
export const uiGitUntracked = ref(localStorage.getItem('uiGitUntracked') || DEFAULT_GIT_COLORS.untracked);

export const uiThemePreset = ref(localStorage.getItem('uiThemePreset') || 'deep-space');
export const uiBackgroundMode = ref(localStorage.getItem('uiBackgroundMode') || 'preset');
export const uiBackgroundPreset = ref(localStorage.getItem('uiBackgroundPreset') || 'deep-space');
export const uiBackgroundColor = ref(localStorage.getItem('uiBackgroundColor') || DEFAULT_THEME_RESET.backgroundColor);
export const uiBackgroundGradientStart = ref(localStorage.getItem('uiBackgroundGradientStart') || DEFAULT_THEME_RESET.backgroundGradientStart);
export const uiBackgroundGradientEnd = ref(localStorage.getItem('uiBackgroundGradientEnd') || DEFAULT_THEME_RESET.backgroundGradientEnd);
export const uiBackgroundGradientAngle = ref(parseInt(localStorage.getItem('uiBackgroundGradientAngle'), 10) || DEFAULT_THEME_RESET.backgroundGradientAngle);
export const uiBackgroundImage = ref(localStorage.getItem('uiBackgroundImage') || '');
export const uiBackgroundImageOpacity = ref(parseFloat(localStorage.getItem('uiBackgroundImageOpacity')) || DEFAULT_THEME_RESET.backgroundImageOpacity);
export const uiBackgroundImageBlur = ref(parseFloat(localStorage.getItem('uiBackgroundImageBlur')) || DEFAULT_THEME_RESET.backgroundImageBlur);
export const uiSidebarBackgroundMode = ref(localStorage.getItem('uiSidebarBackgroundMode') || 'glass');
export const uiSidebarBackgroundPreset = ref(localStorage.getItem('uiSidebarBackgroundPreset') || 'deep-space');
export const uiSidebarBackgroundColor = ref(localStorage.getItem('uiSidebarBackgroundColor') || DEFAULT_THEME_RESET.sidebarBackgroundColor);
export const uiSidebarBackgroundGradientStart = ref(localStorage.getItem('uiSidebarBackgroundGradientStart') || DEFAULT_THEME_RESET.sidebarBackgroundGradientStart);
export const uiSidebarBackgroundGradientEnd = ref(localStorage.getItem('uiSidebarBackgroundGradientEnd') || DEFAULT_THEME_RESET.sidebarBackgroundGradientEnd);
export const uiSidebarBackgroundGradientAngle = ref(parseInt(localStorage.getItem('uiSidebarBackgroundGradientAngle'), 10) || DEFAULT_THEME_RESET.sidebarBackgroundGradientAngle);
export const uiSidebarBackgroundImage = ref(localStorage.getItem('uiSidebarBackgroundImage') || '');
export const uiSidebarBackgroundImageOpacity = ref(parseFloat(localStorage.getItem('uiSidebarBackgroundImageOpacity')) || DEFAULT_THEME_RESET.sidebarBackgroundImageOpacity);
export const uiSidebarBackgroundImageBlur = ref(parseFloat(localStorage.getItem('uiSidebarBackgroundImageBlur')) || DEFAULT_THEME_RESET.sidebarBackgroundImageBlur);

// Independent background mode - when true, each area can have its own background
export const uiBackgroundIndependent = ref(localStorage.getItem('uiBackgroundIndependent') === 'true');

// Left sidebar independent background
export const uiLeftSidebarBackgroundImage = ref(localStorage.getItem('uiLeftSidebarBackgroundImage') || '');
export const uiLeftSidebarBackgroundImageOpacity = ref(parseFloat(localStorage.getItem('uiLeftSidebarBackgroundImageOpacity')) || 0.25);
export const uiLeftSidebarBackgroundImageBlur = ref(parseFloat(localStorage.getItem('uiLeftSidebarBackgroundImageBlur')) || 6);

// Right sidebar independent background
export const uiRightSidebarBackgroundImage = ref(localStorage.getItem('uiRightSidebarBackgroundImage') || '');
export const uiRightSidebarBackgroundImageOpacity = ref(parseFloat(localStorage.getItem('uiRightSidebarBackgroundImageOpacity')) || 0.25);
export const uiRightSidebarBackgroundImageBlur = ref(parseFloat(localStorage.getItem('uiRightSidebarBackgroundImageBlur')) || 6);

// Header background settings
export const uiHeaderBackgroundMode = ref(localStorage.getItem('uiHeaderBackgroundMode') || 'transparent');
export const uiHeaderBackgroundPreset = ref(localStorage.getItem('uiHeaderBackgroundPreset') || 'deep-space');
export const uiHeaderBackgroundColor = ref(localStorage.getItem('uiHeaderBackgroundColor') || DEFAULT_HEADER_THEME.backgroundColor);
export const uiHeaderBackgroundImage = ref(localStorage.getItem('uiHeaderBackgroundImage') || '');
export const uiHeaderBackgroundImageOpacity = ref(parseFloat(localStorage.getItem('uiHeaderBackgroundImageOpacity')) || DEFAULT_HEADER_THEME.backgroundImageOpacity);
export const uiHeaderBackgroundImageBlur = ref(parseFloat(localStorage.getItem('uiHeaderBackgroundImageBlur')) || DEFAULT_HEADER_THEME.backgroundImageBlur);

// Chat area independent background
export const uiChatBackgroundImage = ref(localStorage.getItem('uiChatBackgroundImage') || '');
export const uiChatBackgroundImageOpacity = ref(parseFloat(localStorage.getItem('uiChatBackgroundImageOpacity')) || 0.25);
export const uiChatBackgroundImageBlur = ref(parseFloat(localStorage.getItem('uiChatBackgroundImageBlur')) || 6);

// Input bar background settings
export const uiInputBarBackgroundMode = ref(localStorage.getItem('uiInputBarBackgroundMode') || 'glass');
export const uiInputBarBackgroundPreset = ref(localStorage.getItem('uiInputBarBackgroundPreset') || 'deep-space');
export const uiInputBarBackgroundColor = ref(localStorage.getItem('uiInputBarBackgroundColor') || DEFAULT_INPUT_BAR_THEME.backgroundColor);
export const uiInputBarBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiInputBarBackgroundOpacity')) || DEFAULT_INPUT_BAR_THEME.backgroundOpacity);
export const uiInputBarBorderColor = ref(localStorage.getItem('uiInputBarBorderColor') || DEFAULT_INPUT_BAR_THEME.borderColor);
export const uiInputBarBorderOpacity = ref(parseFloat(localStorage.getItem('uiInputBarBorderOpacity')) || DEFAULT_INPUT_BAR_THEME.borderOpacity);
export const uiInputBarGlow = ref(parseFloat(localStorage.getItem('uiInputBarGlow')) || DEFAULT_INPUT_BAR_THEME.glow);
export const uiToolCardBackgroundMode = ref(localStorage.getItem('uiToolCardBackgroundMode') || 'glass');
export const uiToolCardBackgroundPreset = ref(localStorage.getItem('uiToolCardBackgroundPreset') || 'deep-space');
export const uiToolCardBackgroundColor = ref(localStorage.getItem('uiToolCardBackgroundColor') || DEFAULT_TOOL_CARD_THEME.backgroundColor);
export const uiToolCardBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiToolCardBackgroundOpacity')) || DEFAULT_TOOL_CARD_THEME.backgroundOpacity);
export const uiToolCardBorderColor = ref(localStorage.getItem('uiToolCardBorderColor') || DEFAULT_TOOL_CARD_THEME.borderColor);
export const uiToolCardBorderOpacity = ref(parseFloat(localStorage.getItem('uiToolCardBorderOpacity')) || DEFAULT_TOOL_CARD_THEME.borderOpacity);
export const uiToolCardGlow = ref(parseFloat(localStorage.getItem('uiToolCardGlow')) || DEFAULT_TOOL_CARD_THEME.glow);

// Message bubble background settings - User messages
export const uiUserMessageBackgroundMode = ref(localStorage.getItem('uiUserMessageBackgroundMode') || 'glass');
export const uiUserMessageBackgroundPreset = ref(localStorage.getItem('uiUserMessageBackgroundPreset') || 'deep-space');
export const uiUserMessageBackgroundColor = ref(localStorage.getItem('uiUserMessageBackgroundColor') || DEFAULT_USER_MESSAGE_THEME.backgroundColor);
export const uiUserMessageBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiUserMessageBackgroundOpacity')) || DEFAULT_USER_MESSAGE_THEME.backgroundOpacity);
export const uiUserMessageBorderColor = ref(localStorage.getItem('uiUserMessageBorderColor') || DEFAULT_USER_MESSAGE_THEME.borderColor);
export const uiUserMessageBorderOpacity = ref(parseFloat(localStorage.getItem('uiUserMessageBorderOpacity')) || DEFAULT_USER_MESSAGE_THEME.borderOpacity);

// Message bubble background settings - Assistant messages
export const uiAssistantMessageBackgroundMode = ref(localStorage.getItem('uiAssistantMessageBackgroundMode') || 'glass');
export const uiAssistantMessageBackgroundPreset = ref(localStorage.getItem('uiAssistantMessageBackgroundPreset') || 'steel-veil');
export const uiAssistantMessageBackgroundColor = ref(localStorage.getItem('uiAssistantMessageBackgroundColor') || DEFAULT_ASSISTANT_MESSAGE_THEME.backgroundColor);
export const uiAssistantMessageBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiAssistantMessageBackgroundOpacity')) || DEFAULT_ASSISTANT_MESSAGE_THEME.backgroundOpacity);
export const uiAssistantMessageBorderColor = ref(localStorage.getItem('uiAssistantMessageBorderColor') || DEFAULT_ASSISTANT_MESSAGE_THEME.borderColor);
export const uiAssistantMessageBorderOpacity = ref(parseFloat(localStorage.getItem('uiAssistantMessageBorderOpacity')) || DEFAULT_ASSISTANT_MESSAGE_THEME.borderOpacity);

// Send button theming
export const uiSendButtonBackgroundColor = ref(localStorage.getItem('uiSendButtonBackgroundColor') || '');
export const uiSendButtonTextColor = ref(localStorage.getItem('uiSendButtonTextColor') || '');
export const uiSendButtonGlow = ref(parseFloat(localStorage.getItem('uiSendButtonGlow')) || 0);

// Button theming (rail buttons, action buttons, sidebar buttons)
export const uiButtonBackgroundMode = ref(localStorage.getItem('uiButtonBackgroundMode') || 'glass');
export const uiButtonBackgroundPreset = ref(localStorage.getItem('uiButtonBackgroundPreset') || 'deep-space');
export const uiButtonBackgroundColor = ref(localStorage.getItem('uiButtonBackgroundColor') || DEFAULT_BUTTON_THEME.backgroundColor);
export const uiButtonBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiButtonBackgroundOpacity')) || DEFAULT_BUTTON_THEME.backgroundOpacity);
export const uiButtonBorderColor = ref(localStorage.getItem('uiButtonBorderColor') || DEFAULT_BUTTON_THEME.borderColor);
export const uiButtonBorderOpacity = ref(parseFloat(localStorage.getItem('uiButtonBorderOpacity')) || DEFAULT_BUTTON_THEME.borderOpacity);
export const uiButtonGlow = ref(parseFloat(localStorage.getItem('uiButtonGlow')) || DEFAULT_BUTTON_THEME.glow);

// Stop button theming
export const uiStopButtonBackgroundColor = ref(localStorage.getItem('uiStopButtonBackgroundColor') || '');

// Thinking dropdown theming - header (idle/collapsed state)
export const uiThinkingHeaderBackgroundMode = ref(localStorage.getItem('uiThinkingHeaderBackgroundMode') || 'glass');
export const uiThinkingHeaderBackgroundPreset = ref(localStorage.getItem('uiThinkingHeaderBackgroundPreset') || 'steel-veil');
export const uiThinkingHeaderBackgroundColor = ref(localStorage.getItem('uiThinkingHeaderBackgroundColor') || DEFAULT_THINKING_DROPDOWN_THEME.headerBackgroundColor);
export const uiThinkingHeaderBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiThinkingHeaderBackgroundOpacity')) || DEFAULT_THINKING_DROPDOWN_THEME.headerBackgroundOpacity);
export const uiThinkingHeaderBorderColor = ref(localStorage.getItem('uiThinkingHeaderBorderColor') || DEFAULT_THINKING_DROPDOWN_THEME.headerBorderColor);
export const uiThinkingHeaderBorderOpacity = ref(parseFloat(localStorage.getItem('uiThinkingHeaderBorderOpacity')) || DEFAULT_THINKING_DROPDOWN_THEME.headerBorderOpacity);

// Thinking dropdown theming - content (expanded dropdown)
export const uiThinkingContentBackgroundMode = ref(localStorage.getItem('uiThinkingContentBackgroundMode') || 'glass');
export const uiThinkingContentBackgroundPreset = ref(localStorage.getItem('uiThinkingContentBackgroundPreset') || 'deep-space');
export const uiThinkingContentBackgroundColor = ref(localStorage.getItem('uiThinkingContentBackgroundColor') || DEFAULT_THINKING_DROPDOWN_THEME.contentBackgroundColor);
export const uiThinkingContentBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiThinkingContentBackgroundOpacity')) || DEFAULT_THINKING_DROPDOWN_THEME.contentBackgroundOpacity);

// Thinking dropdown event colors
export const uiEventColorRouting = ref(localStorage.getItem('uiEventColorRouting') || DEFAULT_EVENT_COLORS.routing);
export const uiEventColorMemory = ref(localStorage.getItem('uiEventColorMemory') || DEFAULT_EVENT_COLORS.memory);
export const uiEventColorTool = ref(localStorage.getItem('uiEventColorTool') || DEFAULT_EVENT_COLORS.tool);
export const uiEventColorDecision = ref(localStorage.getItem('uiEventColorDecision') || DEFAULT_EVENT_COLORS.decision);
export const uiEventColorQuorum = ref(localStorage.getItem('uiEventColorQuorum') || DEFAULT_EVENT_COLORS.quorum);
export const uiEventColorError = ref(localStorage.getItem('uiEventColorError') || DEFAULT_EVENT_COLORS.error);

// Voice mode colors
export const uiVoiceListeningColor = ref(localStorage.getItem('uiVoiceListeningColor') || DEFAULT_VOICE_COLORS.listening);
export const uiVoiceSpeakingColor = ref(localStorage.getItem('uiVoiceSpeakingColor') || DEFAULT_VOICE_COLORS.speaking);
export const uiVoiceProcessingColor = ref(localStorage.getItem('uiVoiceProcessingColor') || DEFAULT_VOICE_COLORS.processing);

// Drawer theming (right sidebar drawers)
export const uiDrawerBackgroundMode = ref(localStorage.getItem('uiDrawerBackgroundMode') || 'glass');
export const uiDrawerBackgroundPreset = ref(localStorage.getItem('uiDrawerBackgroundPreset') || 'deep-space');
export const uiDrawerBackgroundColor = ref(localStorage.getItem('uiDrawerBackgroundColor') || DEFAULT_DRAWER_THEME.backgroundColor);
export const uiDrawerBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiDrawerBackgroundOpacity')) || DEFAULT_DRAWER_THEME.backgroundOpacity);
export const uiDrawerBorderColor = ref(localStorage.getItem('uiDrawerBorderColor') || DEFAULT_DRAWER_THEME.borderColor);
export const uiDrawerBorderOpacity = ref(parseFloat(localStorage.getItem('uiDrawerBorderOpacity')) || DEFAULT_DRAWER_THEME.borderOpacity);

// Drawer card backgrounds (cards within drawers)
export const uiDrawerCardBackgroundMode = ref(localStorage.getItem('uiDrawerCardBackgroundMode') || 'glass');
export const uiDrawerCardBackgroundColor = ref(localStorage.getItem('uiDrawerCardBackgroundColor') || DEFAULT_DRAWER_THEME.cardBackgroundColor);
export const uiDrawerCardBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiDrawerCardBackgroundOpacity')) || DEFAULT_DRAWER_THEME.cardBackgroundOpacity);

// Code Editor panel
export const uiCodeEditorBackgroundColor = ref(localStorage.getItem('uiCodeEditorBackgroundColor') || DEFAULT_CODE_EDITOR_THEME.backgroundColor);
export const uiCodeEditorBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiCodeEditorBackgroundOpacity')) || DEFAULT_CODE_EDITOR_THEME.backgroundOpacity);

// Terminal panel
export const uiTerminalBackgroundColor = ref(localStorage.getItem('uiTerminalBackgroundColor') || DEFAULT_TERMINAL_PANEL_THEME.backgroundColor);
export const uiTerminalBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiTerminalBackgroundOpacity')) || DEFAULT_TERMINAL_PANEL_THEME.backgroundOpacity);
export const uiTerminalHeaderBackgroundColor = ref(localStorage.getItem('uiTerminalHeaderBackgroundColor') || DEFAULT_TERMINAL_PANEL_THEME.headerBackgroundColor);
export const uiTerminalHeaderBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiTerminalHeaderBackgroundOpacity')) || DEFAULT_TERMINAL_PANEL_THEME.headerBackgroundOpacity);

// File Browser panel
export const uiFileBrowserBackgroundColor = ref(localStorage.getItem('uiFileBrowserBackgroundColor') || DEFAULT_FILE_BROWSER_THEME.backgroundColor);
export const uiFileBrowserBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiFileBrowserBackgroundOpacity')) || DEFAULT_FILE_BROWSER_THEME.backgroundOpacity);

// Dialog content areas
export const uiDialogContentBackgroundColor = ref(localStorage.getItem('uiDialogContentBackgroundColor') || DEFAULT_DIALOG_CONTENT_THEME.backgroundColor);
export const uiDialogContentBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiDialogContentBackgroundOpacity')) || DEFAULT_DIALOG_CONTENT_THEME.backgroundOpacity);

// Card/Stat components (MCP servers, metrics, etc.)
export const uiCardBackgroundColor = ref(localStorage.getItem('uiCardBackgroundColor') || DEFAULT_CARD_THEME.backgroundColor);
export const uiCardBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiCardBackgroundOpacity')) || DEFAULT_CARD_THEME.backgroundOpacity);

// Filter button groups
export const uiFilterButtonBackgroundColor = ref(localStorage.getItem('uiFilterButtonBackgroundColor') || DEFAULT_FILTER_BUTTON_THEME.backgroundColor);
export const uiFilterButtonBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiFilterButtonBackgroundOpacity')) || DEFAULT_FILTER_BUTTON_THEME.backgroundOpacity);
export const uiFilterButtonActiveBackgroundColor = ref(localStorage.getItem('uiFilterButtonActiveBackgroundColor') || DEFAULT_FILTER_BUTTON_THEME.activeBackgroundColor);
export const uiFilterButtonActiveBackgroundOpacity = ref(parseFloat(localStorage.getItem('uiFilterButtonActiveBackgroundOpacity')) || DEFAULT_FILTER_BUTTON_THEME.activeBackgroundOpacity);

export const uiPanelSurfacePresets = ref(parseStoredJson('uiPanelSurfacePresets', []));

export const uiEffectScanlines = ref(localStorage.getItem('uiEffectScanlines') === 'true');
export const uiEffectScanlineOpacity = ref(parseFloat(localStorage.getItem('uiEffectScanlineOpacity')) || 0.12);
export const uiEffectNoise = ref(localStorage.getItem('uiEffectNoise') === 'true');
export const uiEffectNoiseOpacity = ref(parseFloat(localStorage.getItem('uiEffectNoiseOpacity')) || 0.08);
export const uiEffectGlowPulse = ref(localStorage.getItem('uiEffectGlowPulse') === 'true');
export const uiEffectGlowPulseStrength = ref(parseFloat(localStorage.getItem('uiEffectGlowPulseStrength')) || 0.35);
export const uiEffectGlowPulseSpeed = ref(parseFloat(localStorage.getItem('uiEffectGlowPulseSpeed')) || 6);
export const uiEffectGrid = ref(localStorage.getItem('uiEffectGrid') === 'true');
export const uiEffectGridOpacity = ref(parseFloat(localStorage.getItem('uiEffectGridOpacity')) || 0.12);
export const uiEffectVignette = ref(localStorage.getItem('uiEffectVignette') === 'true');
export const uiEffectVignetteStrength = ref(parseFloat(localStorage.getItem('uiEffectVignetteStrength')) || 0.2);
export const uiEffectAurora = ref(localStorage.getItem('uiEffectAurora') === 'true');
export const uiEffectAuroraOpacity = ref(parseFloat(localStorage.getItem('uiEffectAuroraOpacity')) || 0.18);
export const uiEffectAuroraSpeed = ref(parseFloat(localStorage.getItem('uiEffectAuroraSpeed')) || 60);
export const uiEffectHeaderShimmer = ref(localStorage.getItem('uiEffectHeaderShimmer') === 'true');
export const uiEffectHeaderShimmerStrength = ref(parseFloat(localStorage.getItem('uiEffectHeaderShimmerStrength')) || 0.18);
export const uiEffectHeaderShimmerSpeed = ref(parseFloat(localStorage.getItem('uiEffectHeaderShimmerSpeed')) || 12);
export const uiLiteMode = ref(localStorage.getItem('uiLiteMode') === 'true');
export const uiPanelDepth = ref(parseFloat(localStorage.getItem('uiPanelDepth')) || 0.22);
export const uiEffectMessageDepth = ref(localStorage.getItem('uiEffectMessageDepth') !== 'false');
export const uiEffectMessageDepthStrength = ref(parseFloat(localStorage.getItem('uiEffectMessageDepthStrength')) || 0.22);
export const uiEffectPanelEdge = ref(localStorage.getItem('uiEffectPanelEdge') === 'true');
export const uiEffectPanelEdgeStrength = ref(parseFloat(localStorage.getItem('uiEffectPanelEdgeStrength')) || 0.2);
export const uiEffectMessageEdge = ref(localStorage.getItem('uiEffectMessageEdge') === 'true');
export const uiEffectMessageEdgeStrength = ref(parseFloat(localStorage.getItem('uiEffectMessageEdgeStrength')) || 0.18);
export const uiEffectMessageEdgeTint = ref(localStorage.getItem('uiEffectMessageEdgeTint') || 'neutral');
export const uiEffectPanelGlow = ref(localStorage.getItem('uiEffectPanelGlow') === 'true');
export const uiEffectPanelGlowStrength = ref(parseFloat(localStorage.getItem('uiEffectPanelGlowStrength')) || 0.2);
export const uiEffectPanelBevel = ref(localStorage.getItem('uiEffectPanelBevel') === 'true');
export const uiEffectPanelBevelStrength = ref(parseFloat(localStorage.getItem('uiEffectPanelBevelStrength')) || 0.12);
export const uiBackgroundBlur = ref(parseFloat(localStorage.getItem('uiBackgroundBlur')) || 0);
export const uiHeaderBlur = ref(parseFloat(localStorage.getItem('uiHeaderBlur')) || 18);
export const uiAnimButtonRipple = ref(localStorage.getItem('uiAnimButtonRipple') === 'true');
export const uiAnimMessageMotion = ref(localStorage.getItem('uiAnimMessageMotion') !== 'false');
export const uiAnimHoverLift = ref(localStorage.getItem('uiAnimHoverLift') !== 'false');
export const uiAnimBackgroundDrift = ref(localStorage.getItem('uiAnimBackgroundDrift') === 'true');
export const uiAnimBackgroundDriftSpeed = ref(parseFloat(localStorage.getItem('uiAnimBackgroundDriftSpeed')) || 45);
export const uiAnimButtonMotion = ref(localStorage.getItem('uiAnimButtonMotion') !== 'false');
export const uiAnimButtonScale = ref(parseFloat(localStorage.getItem('uiAnimButtonScale')) || 1.02);
export const uiAnimSpeed = ref(parseFloat(localStorage.getItem('uiAnimSpeed')) || 1.0);
export const uiFontScale = ref(parseFloat(localStorage.getItem('uiFontScale')) || 1.0);
export const uiBorderRadius = ref(localStorage.getItem('uiBorderRadius') || 'normal');
export const uiCompactMode = ref(localStorage.getItem('uiCompactMode') === 'true');

// Nixie tube display settings
export const uiNixieColor = ref(localStorage.getItem('uiNixieColor') || DEFAULT_NIXIE_THEME.color);
export const uiNixieGlowColor = ref(localStorage.getItem('uiNixieGlowColor') || DEFAULT_NIXIE_THEME.glow);
export const uiNixieSpeed = ref(parseFloat(localStorage.getItem('uiNixieSpeed')) || 1.0);
export const uiNixieGlowIntensity = ref(parseFloat(localStorage.getItem('uiNixieGlowIntensity')) || 1.0);
export const uiNixieFlicker = ref(localStorage.getItem('uiNixieFlicker') !== 'false');

// Exit button Nixie settings (separate from main Nixie theme)
export const uiNixieExitColor = ref(localStorage.getItem('uiNixieExitColor') || DEFAULT_EXIT_BUTTON_THEME.color);
export const uiNixieExitGlowColor = ref(localStorage.getItem('uiNixieExitGlowColor') || DEFAULT_EXIT_BUTTON_THEME.glow);
export const uiNixieExitGlowIntensity = ref(parseFloat(localStorage.getItem('uiNixieExitGlowIntensity')) || 1.0);

// Nixie button backgrounds (rail buttons)
export const uiNixieButtonBackgroundColor = ref(localStorage.getItem('uiNixieButtonBackgroundColor') || DEFAULT_NIXIE_BUTTON_THEME.backgroundColor);

// Font customization - per component
export const uiFontFamilyGlobal = ref(localStorage.getItem('uiFontFamilyGlobal') || 'default');
export const uiFontFamilyHeader = ref(localStorage.getItem('uiFontFamilyHeader') || 'inherit');
export const uiFontFamilySidebar = ref(localStorage.getItem('uiFontFamilySidebar') || 'inherit');
export const uiFontFamilyMessages = ref(localStorage.getItem('uiFontFamilyMessages') || 'inherit');
export const uiFontFamilyInput = ref(localStorage.getItem('uiFontFamilyInput') || 'inherit');
export const uiFontFamilyCode = ref(localStorage.getItem('uiFontFamilyCode') || 'default');

// Font colors - per component (empty string means use theme default)
export const uiFontColorHeader = ref(localStorage.getItem('uiFontColorHeader') || '');
export const uiFontColorSidebar = ref(localStorage.getItem('uiFontColorSidebar') || '');
export const uiFontColorMessages = ref(localStorage.getItem('uiFontColorMessages') || '');
export const uiFontColorInput = ref(localStorage.getItem('uiFontColorInput') || '');
export const uiFontColorMuted = ref(localStorage.getItem('uiFontColorMuted') || '');

// Accessibility settings
export const a11yReducedMotion = ref(localStorage.getItem('a11yReducedMotion') || 'system');
export const a11yHighContrast = ref(localStorage.getItem('a11yHighContrast') === 'true');
export const a11yLargeText = ref(localStorage.getItem('a11yLargeText') === 'true');
export const a11yDyslexiaFont = ref(localStorage.getItem('a11yDyslexiaFont') === 'true');
export const a11yLineSpacing = ref(localStorage.getItem('a11yLineSpacing') || 'normal');
export const a11yLetterSpacing = ref(localStorage.getItem('a11yLetterSpacing') || 'normal');
export const a11yFocusHighlight = ref(localStorage.getItem('a11yFocusHighlight') || 'normal');
export const a11yScreenReaderAnnounce = ref(localStorage.getItem('a11yScreenReaderAnnounce') !== 'false');
export const a11yMessageVerbosity = ref(localStorage.getItem('a11yMessageVerbosity') || 'normal');
export const a11yKeyboardShortcuts = ref(localStorage.getItem('a11yKeyboardShortcuts') !== 'false');
export const a11ySoundEffects = ref(localStorage.getItem('a11ySoundEffects') === 'true');
export const a11yAutoPlayMedia = ref(localStorage.getItem('a11yAutoPlayMedia') === 'true');

// Enhanced Avatar settings
export const avatarSize = ref(localStorage.getItem('avatarSize') || 'medium');
export const avatarBorderStyle = ref(localStorage.getItem('avatarBorderStyle') || 'none');
export const avatarBorderColor = ref(localStorage.getItem('avatarBorderColor') || DEFAULT_AVATAR_STYLE.borderColor);
export const avatarBorderWidth = ref(parseInt(localStorage.getItem('avatarBorderWidth')) || DEFAULT_AVATAR_STYLE.borderWidth);
export const avatarGlow = ref(localStorage.getItem('avatarGlow') === 'true');
export const avatarGlowColor = ref(localStorage.getItem('avatarGlowColor') || DEFAULT_AVATAR_STYLE.glowColor);
export const avatarGlowIntensity = ref(parseFloat(localStorage.getItem('avatarGlowIntensity')) || DEFAULT_AVATAR_STYLE.glowIntensity);
export const avatarAnimation = ref(localStorage.getItem('avatarAnimation') || 'none');
export const avatarPosition = ref(localStorage.getItem('avatarPosition') || 'beside');
export const avatarDefaultStyle = ref(localStorage.getItem('avatarDefaultStyle') || 'initials');
export const userStatus = ref(localStorage.getItem('userStatus') || 'online');
export const showStatusIndicator = ref(localStorage.getItem('showStatusIndicator') !== 'false');
export const aiAvatarPreset = ref(localStorage.getItem('aiAvatarPreset') || 'default');
export const userAvatarPreset = ref(localStorage.getItem('userAvatarPreset') || 'default');
export const aiAvatarIconColor = ref(localStorage.getItem('aiAvatarIconColor') || DEFAULT_AVATAR_ICON_COLORS.ai);
export const userAvatarIconColor = ref(localStorage.getItem('userAvatarIconColor') || DEFAULT_AVATAR_ICON_COLORS.user);

export const browserModelSelection = ref(localStorage.getItem('browserModelSelection') || undefined);

export const maxTokens = ref(parseInt(localStorage.getItem('maxTokens')) || 4096);
export const top_P = ref(parseFloat(localStorage.getItem('top_P')) || 1.0);
export const repetitionPenalty = ref(parseFloat(localStorage.getItem('repetitionPenalty')) || 1.0);
export const presencePenalty = ref(parseFloat(localStorage.getItem('presencePenalty')) || 0.0);

export const systemPrompt = ref(localStorage.getItem('systemPrompt') || '');

export const conversations = ref(loadConversationTitles());
export const storedConversations = ref(loadStoredConversations());
export const lastLoadedConversationId = ref(parseInt(localStorage.getItem('lastConversationId')) || 0);
export const selectedConversation = ref(conversations.value[0]);
export const abortController = ref(null);

// Artifacts state - code/content artifacts associated with conversations
export const currentArtifacts = ref([]);

// Thinking/reasoning events state (similar to Google Gemini "Show thinking")
export const thinkingEvents = ref([]);
export const isThinkingVisible = ref(true); // User preference for showing thinking
export const thinkingCollapsed = ref(false); // Whether the thinking section is collapsed
export const imageInput = ref(null);
export const pendingImageFile = ref(null);
export const pendingUpload = ref(null);

export const isSmallScreen = ref(window.innerWidth <= 600);
export const isSidebarVisible = ref(false);


window.addEventListener('resize', () => {
    isSmallScreen.value = window.innerWidth <= 600;
});
