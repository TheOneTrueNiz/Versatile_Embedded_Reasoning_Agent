// watchers.js
import { watch } from 'vue';
import { unloadModel, removeAPIEndpoints, updateUIWrapper } from '@/libs/utils/general-utils';
import { applyTheme, setupThemeListener } from '@/libs/utils/theme-utils';
import { engine, loadNewModel } from '@/libs/api-access/web-llm-access';
import { modelSettings, MODEL_TYPES, defaultSettings } from '@/libs/utils/constants';
import {
  selectedModel,
  modelDisplayName,
  isLoading,
  browserModelSelection,
  localModelKey,
  systemPrompt,
  maxTokens,
  top_P,
  repetitionPenalty,
  presencePenalty,
  localModelName,
  localSliderValue,
  gptKey,
  sliderValue,
  claudeKey,
  claudeSliderValue,
  selectedDallEImageCount,
  selectedDallEImageResolution,
  selectedAutoSaveOption,
  localModelEndpoint,
  higherContrastMessages,
  pushToTalkMode,
  useWhisper,
  ttsModel,
  audioSpeed,
  whisperTemperature,
  ttsVoice,
  isAvatarEnabled,
  avatarUrl,
  userAvatarUrl,
  avatarShape,
  voiceAgentVoice,
  quorumAutoEnabled,
  swarmAutoEnabled,
  uiThemeMode,
  uiThemeNativeMode,
  uiAccentColor,
  uiSecondaryAccent,
  uiThemeOverrides,
  // Terminal colors
  uiTerminalBackground,
  uiTerminalForeground,
  uiTerminalCursor,
  uiTerminalSelection,
  uiTerminalBlack,
  uiTerminalRed,
  uiTerminalGreen,
  uiTerminalYellow,
  uiTerminalBlue,
  uiTerminalMagenta,
  uiTerminalCyan,
  uiTerminalWhite,
  // Status/Event colors
  uiStatusSuccess,
  uiStatusWarning,
  uiStatusError,
  uiStatusInfo,
  uiEventRouting,
  uiEventMemory,
  uiEventTool,
  uiEventDecision,
  uiEventQuorum,
  // Git status colors
  uiGitAdded,
  uiGitModified,
  uiGitDeleted,
  uiGitUntracked,
  uiThemePreset,
  uiBackgroundMode,
  uiBackgroundPreset,
  uiBackgroundColor,
  uiBackgroundGradientStart,
  uiBackgroundGradientEnd,
  uiBackgroundGradientAngle,
  uiBackgroundImage,
  uiBackgroundImageOpacity,
  uiBackgroundImageBlur,
  uiSidebarBackgroundMode,
  uiSidebarBackgroundPreset,
  uiSidebarBackgroundColor,
  uiSidebarBackgroundGradientStart,
  uiSidebarBackgroundGradientEnd,
  uiSidebarBackgroundGradientAngle,
  uiSidebarBackgroundImage,
  uiSidebarBackgroundImageOpacity,
  uiSidebarBackgroundImageBlur,
  uiBackgroundIndependent,
  uiLeftSidebarBackgroundImage,
  uiLeftSidebarBackgroundImageOpacity,
  uiLeftSidebarBackgroundImageBlur,
  uiRightSidebarBackgroundImage,
  uiRightSidebarBackgroundImageOpacity,
  uiRightSidebarBackgroundImageBlur,
  uiHeaderBackgroundMode,
  uiHeaderBackgroundPreset,
  uiHeaderBackgroundColor,
  uiHeaderBackgroundImage,
  uiHeaderBackgroundImageOpacity,
  uiHeaderBackgroundImageBlur,
  uiChatBackgroundImage,
  uiChatBackgroundImageOpacity,
  uiChatBackgroundImageBlur,
  uiInputBarBackgroundMode,
  uiInputBarBackgroundPreset,
  uiInputBarBackgroundColor,
  uiInputBarBackgroundOpacity,
  uiInputBarBorderColor,
  uiInputBarBorderOpacity,
  uiInputBarGlow,
  uiToolCardBackgroundMode,
  uiToolCardBackgroundPreset,
  uiToolCardBackgroundColor,
  uiToolCardBackgroundOpacity,
  uiToolCardBorderColor,
  uiToolCardBorderOpacity,
  uiToolCardGlow,
  uiUserMessageBackgroundMode,
  uiUserMessageBackgroundPreset,
  uiUserMessageBackgroundColor,
  uiUserMessageBackgroundOpacity,
  uiUserMessageBorderColor,
  uiUserMessageBorderOpacity,
  uiAssistantMessageBackgroundMode,
  uiAssistantMessageBackgroundPreset,
  uiAssistantMessageBackgroundColor,
  uiAssistantMessageBackgroundOpacity,
  uiAssistantMessageBorderColor,
  uiAssistantMessageBorderOpacity,
  uiSendButtonBackgroundColor,
  uiSendButtonTextColor,
  uiSendButtonGlow,
  // Button theming
  uiButtonBackgroundMode,
  uiButtonBackgroundPreset,
  uiButtonBackgroundColor,
  uiButtonBackgroundOpacity,
  uiButtonBorderColor,
  uiButtonBorderOpacity,
  uiButtonGlow,
  uiStopButtonBackgroundColor,
  // Panel surfaces
  uiDrawerBackgroundMode,
  uiDrawerBackgroundPreset,
  uiDrawerBackgroundColor,
  uiDrawerBackgroundOpacity,
  uiDrawerBorderColor,
  uiDrawerBorderOpacity,
  uiDrawerCardBackgroundMode,
  uiDrawerCardBackgroundColor,
  uiDrawerCardBackgroundOpacity,
  uiCodeEditorBackgroundColor,
  uiCodeEditorBackgroundOpacity,
  uiTerminalBackgroundColor,
  uiTerminalBackgroundOpacity,
  uiTerminalHeaderBackgroundColor,
  uiTerminalHeaderBackgroundOpacity,
  uiFileBrowserBackgroundColor,
  uiFileBrowserBackgroundOpacity,
  uiDialogContentBackgroundColor,
  uiDialogContentBackgroundOpacity,
  uiCardBackgroundColor,
  uiCardBackgroundOpacity,
  uiFilterButtonBackgroundColor,
  uiFilterButtonBackgroundOpacity,
  uiFilterButtonActiveBackgroundColor,
  uiFilterButtonActiveBackgroundOpacity,
  uiNixieButtonBackgroundColor,
  uiPanelSurfacePresets,
  // Thinking dropdown theming - header
  uiThinkingHeaderBackgroundMode,
  uiThinkingHeaderBackgroundPreset,
  uiThinkingHeaderBackgroundColor,
  uiThinkingHeaderBackgroundOpacity,
  uiThinkingHeaderBorderColor,
  uiThinkingHeaderBorderOpacity,
  // Thinking dropdown theming - content
  uiThinkingContentBackgroundMode,
  uiThinkingContentBackgroundPreset,
  uiThinkingContentBackgroundColor,
  uiThinkingContentBackgroundOpacity,
  // Thinking dropdown event colors
  uiEventColorRouting,
  uiEventColorMemory,
  uiEventColorTool,
  uiEventColorDecision,
  uiEventColorQuorum,
  uiEventColorError,
  // Voice mode colors
  uiVoiceListeningColor,
  uiVoiceSpeakingColor,
  uiVoiceProcessingColor,
  uiEffectScanlines,
  uiEffectScanlineOpacity,
  uiEffectNoise,
  uiEffectNoiseOpacity,
  uiEffectGlowPulse,
  uiEffectGlowPulseStrength,
  uiEffectGlowPulseSpeed,
  uiEffectGrid,
  uiEffectGridOpacity,
  uiEffectVignette,
  uiEffectVignetteStrength,
  uiEffectAurora,
  uiEffectAuroraOpacity,
  uiEffectAuroraSpeed,
  uiEffectHeaderShimmer,
  uiEffectHeaderShimmerStrength,
  uiEffectHeaderShimmerSpeed,
  uiLiteMode,
  uiPanelDepth,
  uiEffectMessageDepth,
  uiEffectMessageDepthStrength,
  uiEffectPanelEdge,
  uiEffectPanelEdgeStrength,
  uiEffectMessageEdge,
  uiEffectMessageEdgeStrength,
  uiEffectMessageEdgeTint,
  uiEffectPanelGlow,
  uiEffectPanelGlowStrength,
  uiEffectPanelBevel,
  uiEffectPanelBevelStrength,
  uiBackgroundBlur,
  uiHeaderBlur,
  uiAnimButtonRipple,
  uiAnimMessageMotion,
  uiAnimHoverLift,
  uiAnimBackgroundDrift,
  uiAnimBackgroundDriftSpeed,
  uiAnimButtonMotion,
  uiAnimButtonScale,
  uiAnimSpeed,
  uiFontScale,
  uiBorderRadius,
  uiCompactMode,
  // Nixie tube settings
  uiNixieColor,
  uiNixieGlowColor,
  uiNixieSpeed,
  uiNixieGlowIntensity,
  uiNixieFlicker,
  // Exit button Nixie settings
  uiNixieExitColor,
  uiNixieExitGlowColor,
  uiNixieExitGlowIntensity,
  uiFontFamilyGlobal,
  uiFontFamilyHeader,
  uiFontFamilySidebar,
  uiFontFamilyMessages,
  uiFontFamilyInput,
  uiFontFamilyCode,
  uiFontColorHeader,
  uiFontColorSidebar,
  uiFontColorMessages,
  uiFontColorInput,
  uiFontColorMuted,
  // Accessibility settings
  a11yReducedMotion,
  a11yHighContrast,
  a11yLargeText,
  a11yDyslexiaFont,
  a11yLineSpacing,
  a11yLetterSpacing,
  a11yFocusHighlight,
  a11yScreenReaderAnnounce,
  a11yMessageVerbosity,
  a11yKeyboardShortcuts,
  a11ySoundEffects,
  a11yAutoPlayMedia,
  // Enhanced Avatar settings
  avatarSize,
  avatarBorderStyle,
  avatarBorderColor,
  avatarBorderWidth,
  avatarGlow,
  avatarGlowColor,
  avatarGlowIntensity,
  avatarAnimation,
  avatarPosition,
  avatarDefaultStyle,
  userStatus,
  showStatusIndicator,
  aiAvatarPreset,
  userAvatarPreset,
  aiAvatarIconColor,
  userAvatarIconColor
} from '@/libs/state-management/state';

export function setupWatchers() {
  watch(selectedModel, (newValue) => {
    const settings = Object.keys(MODEL_TYPES).reduce((acc, key) => {
      if (newValue.includes(MODEL_TYPES[key])) {
        return modelSettings[MODEL_TYPES[key]];
      }
      return acc;
    }, defaultSettings);

    if (settings.modelDisplayName !== 'WebGPU Model') {
      unloadModel(engine);
    }
    try {
      localStorage.setItem('useLocalModel', settings.useLocalModel);
      localStorage.setItem('selectedModel', newValue);
      modelDisplayName.value = settings.modelDisplayName;
    } catch (error) {
      console.error('Error updating settings:', error);
    }
  });

  const watchAndStore = (ref, key, transform = (val) => val) => {
    watch(ref, (newValue) => {
      localStorage.setItem(key, transform(newValue));
    });
  };

  const refsToWatch = [
    { ref: localModelKey, key: 'localModelKey' },
    { ref: systemPrompt, key: 'systemPrompt' },
    { ref: maxTokens, key: 'maxTokens' },
    { ref: top_P, key: 'top_P' },
    { ref: repetitionPenalty, key: 'repetitionPenalty' },
    { ref: presencePenalty, key: 'presencePenalty' },
    { ref: localModelName, key: 'localModelName' },
    { ref: localSliderValue, key: 'local-attitude' },
    { ref: gptKey, key: 'gptKey' },
    { ref: sliderValue, key: 'gpt-attitude' },
    { ref: claudeKey, key: 'claudeKey' },
    { ref: claudeSliderValue, key: 'claude-attitude' },
    { ref: selectedDallEImageCount, key: 'selectedDallEImageCount' },
    { ref: selectedDallEImageResolution, key: 'selectedDallEImageResolution' },
    { ref: selectedAutoSaveOption, key: 'selectedAutoSaveOption' },
    { ref: higherContrastMessages, key: 'higherContrastMessages' },
    { ref: pushToTalkMode, key: 'use-push-to-talk' },
    { ref: useWhisper, key: 'use-whisper' },
    { ref: ttsModel, key: 'tts-model' },
    { ref: ttsVoice, key: 'tts-voice' },
    { ref: audioSpeed, key: 'audio-speed' },
    { ref: whisperTemperature, key: 'whisper-temperature' },
    { ref: avatarUrl, key: 'avatarUrl' },
    { ref: avatarShape, key: 'avatarShape' },
    { ref: userAvatarUrl, key: 'userAvatarUrl' },
    { ref: isAvatarEnabled, key: 'isAvatarEnabled' },
    { ref: voiceAgentVoice, key: 'voice-agent-voice' },
    { ref: quorumAutoEnabled, key: 'quorumAutoEnabled' },
    { ref: swarmAutoEnabled, key: 'swarmAutoEnabled' },
    { ref: uiThemeMode, key: 'uiThemeMode' },
    { ref: uiAccentColor, key: 'uiAccentColor' },
    { ref: uiSecondaryAccent, key: 'uiSecondaryAccent' },
    // Terminal colors
    { ref: uiTerminalBackground, key: 'uiTerminalBackground' },
    { ref: uiTerminalForeground, key: 'uiTerminalForeground' },
    { ref: uiTerminalCursor, key: 'uiTerminalCursor' },
    { ref: uiTerminalSelection, key: 'uiTerminalSelection' },
    { ref: uiTerminalBlack, key: 'uiTerminalBlack' },
    { ref: uiTerminalRed, key: 'uiTerminalRed' },
    { ref: uiTerminalGreen, key: 'uiTerminalGreen' },
    { ref: uiTerminalYellow, key: 'uiTerminalYellow' },
    { ref: uiTerminalBlue, key: 'uiTerminalBlue' },
    { ref: uiTerminalMagenta, key: 'uiTerminalMagenta' },
    { ref: uiTerminalCyan, key: 'uiTerminalCyan' },
    { ref: uiTerminalWhite, key: 'uiTerminalWhite' },
    // Status/Event colors
    { ref: uiStatusSuccess, key: 'uiStatusSuccess' },
    { ref: uiStatusWarning, key: 'uiStatusWarning' },
    { ref: uiStatusError, key: 'uiStatusError' },
    { ref: uiStatusInfo, key: 'uiStatusInfo' },
    { ref: uiEventRouting, key: 'uiEventRouting' },
    { ref: uiEventMemory, key: 'uiEventMemory' },
    { ref: uiEventTool, key: 'uiEventTool' },
    { ref: uiEventDecision, key: 'uiEventDecision' },
    { ref: uiEventQuorum, key: 'uiEventQuorum' },
    // Git status colors
    { ref: uiGitAdded, key: 'uiGitAdded' },
    { ref: uiGitModified, key: 'uiGitModified' },
    { ref: uiGitDeleted, key: 'uiGitDeleted' },
    { ref: uiGitUntracked, key: 'uiGitUntracked' },
    { ref: uiThemePreset, key: 'uiThemePreset' },
    { ref: uiBackgroundMode, key: 'uiBackgroundMode' },
    { ref: uiBackgroundPreset, key: 'uiBackgroundPreset' },
    { ref: uiBackgroundColor, key: 'uiBackgroundColor' },
    { ref: uiBackgroundGradientStart, key: 'uiBackgroundGradientStart' },
    { ref: uiBackgroundGradientEnd, key: 'uiBackgroundGradientEnd' },
    { ref: uiBackgroundGradientAngle, key: 'uiBackgroundGradientAngle' },
    { ref: uiBackgroundImage, key: 'uiBackgroundImage' },
    { ref: uiBackgroundImageOpacity, key: 'uiBackgroundImageOpacity' },
    { ref: uiBackgroundImageBlur, key: 'uiBackgroundImageBlur' },
    { ref: uiSidebarBackgroundMode, key: 'uiSidebarBackgroundMode' },
    { ref: uiSidebarBackgroundPreset, key: 'uiSidebarBackgroundPreset' },
    { ref: uiSidebarBackgroundColor, key: 'uiSidebarBackgroundColor' },
    { ref: uiSidebarBackgroundGradientStart, key: 'uiSidebarBackgroundGradientStart' },
    { ref: uiSidebarBackgroundGradientEnd, key: 'uiSidebarBackgroundGradientEnd' },
    { ref: uiSidebarBackgroundGradientAngle, key: 'uiSidebarBackgroundGradientAngle' },
    { ref: uiSidebarBackgroundImage, key: 'uiSidebarBackgroundImage' },
    { ref: uiSidebarBackgroundImageOpacity, key: 'uiSidebarBackgroundImageOpacity' },
    { ref: uiSidebarBackgroundImageBlur, key: 'uiSidebarBackgroundImageBlur' },
    { ref: uiBackgroundIndependent, key: 'uiBackgroundIndependent' },
    { ref: uiLeftSidebarBackgroundImage, key: 'uiLeftSidebarBackgroundImage' },
    { ref: uiLeftSidebarBackgroundImageOpacity, key: 'uiLeftSidebarBackgroundImageOpacity' },
    { ref: uiLeftSidebarBackgroundImageBlur, key: 'uiLeftSidebarBackgroundImageBlur' },
    { ref: uiRightSidebarBackgroundImage, key: 'uiRightSidebarBackgroundImage' },
    { ref: uiRightSidebarBackgroundImageOpacity, key: 'uiRightSidebarBackgroundImageOpacity' },
    { ref: uiRightSidebarBackgroundImageBlur, key: 'uiRightSidebarBackgroundImageBlur' },
    { ref: uiHeaderBackgroundMode, key: 'uiHeaderBackgroundMode' },
    { ref: uiHeaderBackgroundPreset, key: 'uiHeaderBackgroundPreset' },
    { ref: uiHeaderBackgroundColor, key: 'uiHeaderBackgroundColor' },
    { ref: uiHeaderBackgroundImage, key: 'uiHeaderBackgroundImage' },
    { ref: uiHeaderBackgroundImageOpacity, key: 'uiHeaderBackgroundImageOpacity' },
    { ref: uiHeaderBackgroundImageBlur, key: 'uiHeaderBackgroundImageBlur' },
    { ref: uiChatBackgroundImage, key: 'uiChatBackgroundImage' },
    { ref: uiChatBackgroundImageOpacity, key: 'uiChatBackgroundImageOpacity' },
    { ref: uiChatBackgroundImageBlur, key: 'uiChatBackgroundImageBlur' },
    { ref: uiInputBarBackgroundMode, key: 'uiInputBarBackgroundMode' },
    { ref: uiInputBarBackgroundPreset, key: 'uiInputBarBackgroundPreset' },
    { ref: uiInputBarBackgroundColor, key: 'uiInputBarBackgroundColor' },
    { ref: uiInputBarBackgroundOpacity, key: 'uiInputBarBackgroundOpacity' },
    { ref: uiInputBarBorderColor, key: 'uiInputBarBorderColor' },
    { ref: uiInputBarBorderOpacity, key: 'uiInputBarBorderOpacity' },
    { ref: uiInputBarGlow, key: 'uiInputBarGlow' },
    { ref: uiToolCardBackgroundMode, key: 'uiToolCardBackgroundMode' },
    { ref: uiToolCardBackgroundPreset, key: 'uiToolCardBackgroundPreset' },
    { ref: uiToolCardBackgroundColor, key: 'uiToolCardBackgroundColor' },
    { ref: uiToolCardBackgroundOpacity, key: 'uiToolCardBackgroundOpacity' },
    { ref: uiToolCardBorderColor, key: 'uiToolCardBorderColor' },
    { ref: uiToolCardBorderOpacity, key: 'uiToolCardBorderOpacity' },
    { ref: uiToolCardGlow, key: 'uiToolCardGlow' },
    { ref: uiUserMessageBackgroundMode, key: 'uiUserMessageBackgroundMode' },
    { ref: uiUserMessageBackgroundPreset, key: 'uiUserMessageBackgroundPreset' },
    { ref: uiUserMessageBackgroundColor, key: 'uiUserMessageBackgroundColor' },
    { ref: uiUserMessageBackgroundOpacity, key: 'uiUserMessageBackgroundOpacity' },
    { ref: uiUserMessageBorderColor, key: 'uiUserMessageBorderColor' },
    { ref: uiUserMessageBorderOpacity, key: 'uiUserMessageBorderOpacity' },
    { ref: uiAssistantMessageBackgroundMode, key: 'uiAssistantMessageBackgroundMode' },
    { ref: uiAssistantMessageBackgroundPreset, key: 'uiAssistantMessageBackgroundPreset' },
    { ref: uiAssistantMessageBackgroundColor, key: 'uiAssistantMessageBackgroundColor' },
    { ref: uiAssistantMessageBackgroundOpacity, key: 'uiAssistantMessageBackgroundOpacity' },
    { ref: uiAssistantMessageBorderColor, key: 'uiAssistantMessageBorderColor' },
    { ref: uiAssistantMessageBorderOpacity, key: 'uiAssistantMessageBorderOpacity' },
    { ref: uiSendButtonBackgroundColor, key: 'uiSendButtonBackgroundColor' },
    { ref: uiSendButtonTextColor, key: 'uiSendButtonTextColor' },
    { ref: uiSendButtonGlow, key: 'uiSendButtonGlow' },
    // Button theming
    { ref: uiButtonBackgroundMode, key: 'uiButtonBackgroundMode' },
    { ref: uiButtonBackgroundPreset, key: 'uiButtonBackgroundPreset' },
    { ref: uiButtonBackgroundColor, key: 'uiButtonBackgroundColor' },
    { ref: uiButtonBackgroundOpacity, key: 'uiButtonBackgroundOpacity' },
    { ref: uiButtonBorderColor, key: 'uiButtonBorderColor' },
    { ref: uiButtonBorderOpacity, key: 'uiButtonBorderOpacity' },
    { ref: uiButtonGlow, key: 'uiButtonGlow' },
    { ref: uiStopButtonBackgroundColor, key: 'uiStopButtonBackgroundColor' },
    // Panel surfaces
    { ref: uiDrawerBackgroundMode, key: 'uiDrawerBackgroundMode' },
    { ref: uiDrawerBackgroundPreset, key: 'uiDrawerBackgroundPreset' },
    { ref: uiDrawerBackgroundColor, key: 'uiDrawerBackgroundColor' },
    { ref: uiDrawerBackgroundOpacity, key: 'uiDrawerBackgroundOpacity' },
    { ref: uiDrawerBorderColor, key: 'uiDrawerBorderColor' },
    { ref: uiDrawerBorderOpacity, key: 'uiDrawerBorderOpacity' },
    { ref: uiDrawerCardBackgroundMode, key: 'uiDrawerCardBackgroundMode' },
    { ref: uiDrawerCardBackgroundColor, key: 'uiDrawerCardBackgroundColor' },
    { ref: uiDrawerCardBackgroundOpacity, key: 'uiDrawerCardBackgroundOpacity' },
    { ref: uiCodeEditorBackgroundColor, key: 'uiCodeEditorBackgroundColor' },
    { ref: uiCodeEditorBackgroundOpacity, key: 'uiCodeEditorBackgroundOpacity' },
    { ref: uiTerminalBackgroundColor, key: 'uiTerminalBackgroundColor' },
    { ref: uiTerminalBackgroundOpacity, key: 'uiTerminalBackgroundOpacity' },
    { ref: uiTerminalHeaderBackgroundColor, key: 'uiTerminalHeaderBackgroundColor' },
    { ref: uiTerminalHeaderBackgroundOpacity, key: 'uiTerminalHeaderBackgroundOpacity' },
    { ref: uiFileBrowserBackgroundColor, key: 'uiFileBrowserBackgroundColor' },
    { ref: uiFileBrowserBackgroundOpacity, key: 'uiFileBrowserBackgroundOpacity' },
    { ref: uiDialogContentBackgroundColor, key: 'uiDialogContentBackgroundColor' },
    { ref: uiDialogContentBackgroundOpacity, key: 'uiDialogContentBackgroundOpacity' },
    { ref: uiCardBackgroundColor, key: 'uiCardBackgroundColor' },
    { ref: uiCardBackgroundOpacity, key: 'uiCardBackgroundOpacity' },
    { ref: uiFilterButtonBackgroundColor, key: 'uiFilterButtonBackgroundColor' },
    { ref: uiFilterButtonBackgroundOpacity, key: 'uiFilterButtonBackgroundOpacity' },
    { ref: uiFilterButtonActiveBackgroundColor, key: 'uiFilterButtonActiveBackgroundColor' },
    { ref: uiFilterButtonActiveBackgroundOpacity, key: 'uiFilterButtonActiveBackgroundOpacity' },
    { ref: uiNixieButtonBackgroundColor, key: 'uiNixieButtonBackgroundColor' },
    // Thinking dropdown theming - header
    { ref: uiThinkingHeaderBackgroundMode, key: 'uiThinkingHeaderBackgroundMode' },
    { ref: uiThinkingHeaderBackgroundPreset, key: 'uiThinkingHeaderBackgroundPreset' },
    { ref: uiThinkingHeaderBackgroundColor, key: 'uiThinkingHeaderBackgroundColor' },
    { ref: uiThinkingHeaderBackgroundOpacity, key: 'uiThinkingHeaderBackgroundOpacity' },
    { ref: uiThinkingHeaderBorderColor, key: 'uiThinkingHeaderBorderColor' },
    { ref: uiThinkingHeaderBorderOpacity, key: 'uiThinkingHeaderBorderOpacity' },
    // Thinking dropdown theming - content
    { ref: uiThinkingContentBackgroundMode, key: 'uiThinkingContentBackgroundMode' },
    { ref: uiThinkingContentBackgroundPreset, key: 'uiThinkingContentBackgroundPreset' },
    { ref: uiThinkingContentBackgroundColor, key: 'uiThinkingContentBackgroundColor' },
    { ref: uiThinkingContentBackgroundOpacity, key: 'uiThinkingContentBackgroundOpacity' },
    // Thinking dropdown event colors
    { ref: uiEventColorRouting, key: 'uiEventColorRouting' },
    { ref: uiEventColorMemory, key: 'uiEventColorMemory' },
    { ref: uiEventColorTool, key: 'uiEventColorTool' },
    { ref: uiEventColorDecision, key: 'uiEventColorDecision' },
    { ref: uiEventColorQuorum, key: 'uiEventColorQuorum' },
    { ref: uiEventColorError, key: 'uiEventColorError' },
    // Voice mode colors
    { ref: uiVoiceListeningColor, key: 'uiVoiceListeningColor' },
    { ref: uiVoiceSpeakingColor, key: 'uiVoiceSpeakingColor' },
    { ref: uiVoiceProcessingColor, key: 'uiVoiceProcessingColor' },
    { ref: uiEffectScanlines, key: 'uiEffectScanlines' },
    { ref: uiEffectScanlineOpacity, key: 'uiEffectScanlineOpacity' },
    { ref: uiEffectNoise, key: 'uiEffectNoise' },
    { ref: uiEffectNoiseOpacity, key: 'uiEffectNoiseOpacity' },
    { ref: uiEffectGlowPulse, key: 'uiEffectGlowPulse' },
    { ref: uiEffectGlowPulseStrength, key: 'uiEffectGlowPulseStrength' },
    { ref: uiEffectGlowPulseSpeed, key: 'uiEffectGlowPulseSpeed' },
    { ref: uiEffectGrid, key: 'uiEffectGrid' },
    { ref: uiEffectGridOpacity, key: 'uiEffectGridOpacity' },
    { ref: uiEffectVignette, key: 'uiEffectVignette' },
    { ref: uiEffectVignetteStrength, key: 'uiEffectVignetteStrength' },
    { ref: uiEffectAurora, key: 'uiEffectAurora' },
    { ref: uiEffectAuroraOpacity, key: 'uiEffectAuroraOpacity' },
    { ref: uiEffectAuroraSpeed, key: 'uiEffectAuroraSpeed' },
    { ref: uiEffectHeaderShimmer, key: 'uiEffectHeaderShimmer' },
    { ref: uiEffectHeaderShimmerStrength, key: 'uiEffectHeaderShimmerStrength' },
    { ref: uiEffectHeaderShimmerSpeed, key: 'uiEffectHeaderShimmerSpeed' },
    { ref: uiLiteMode, key: 'uiLiteMode' },
    { ref: uiPanelDepth, key: 'uiPanelDepth' },
    { ref: uiEffectMessageDepth, key: 'uiEffectMessageDepth' },
    { ref: uiEffectMessageDepthStrength, key: 'uiEffectMessageDepthStrength' },
    { ref: uiEffectPanelEdge, key: 'uiEffectPanelEdge' },
    { ref: uiEffectPanelEdgeStrength, key: 'uiEffectPanelEdgeStrength' },
    { ref: uiEffectMessageEdge, key: 'uiEffectMessageEdge' },
    { ref: uiEffectMessageEdgeStrength, key: 'uiEffectMessageEdgeStrength' },
    { ref: uiEffectMessageEdgeTint, key: 'uiEffectMessageEdgeTint' },
    { ref: uiEffectPanelGlow, key: 'uiEffectPanelGlow' },
    { ref: uiEffectPanelGlowStrength, key: 'uiEffectPanelGlowStrength' },
    { ref: uiEffectPanelBevel, key: 'uiEffectPanelBevel' },
    { ref: uiEffectPanelBevelStrength, key: 'uiEffectPanelBevelStrength' },
    { ref: uiBackgroundBlur, key: 'uiBackgroundBlur' },
    { ref: uiHeaderBlur, key: 'uiHeaderBlur' },
    { ref: uiAnimButtonRipple, key: 'uiAnimButtonRipple' },
    { ref: uiAnimMessageMotion, key: 'uiAnimMessageMotion' },
    { ref: uiAnimHoverLift, key: 'uiAnimHoverLift' },
    { ref: uiAnimBackgroundDrift, key: 'uiAnimBackgroundDrift' },
    { ref: uiAnimBackgroundDriftSpeed, key: 'uiAnimBackgroundDriftSpeed' },
    { ref: uiAnimButtonMotion, key: 'uiAnimButtonMotion' },
    { ref: uiAnimButtonScale, key: 'uiAnimButtonScale' },
    { ref: uiFontFamilyGlobal, key: 'uiFontFamilyGlobal' },
    { ref: uiFontFamilyHeader, key: 'uiFontFamilyHeader' },
    { ref: uiFontFamilySidebar, key: 'uiFontFamilySidebar' },
    { ref: uiFontFamilyMessages, key: 'uiFontFamilyMessages' },
    { ref: uiFontFamilyInput, key: 'uiFontFamilyInput' },
    { ref: uiFontFamilyCode, key: 'uiFontFamilyCode' },
    { ref: uiFontColorHeader, key: 'uiFontColorHeader' },
    { ref: uiFontColorSidebar, key: 'uiFontColorSidebar' },
    { ref: uiFontColorMessages, key: 'uiFontColorMessages' },
    { ref: uiFontColorInput, key: 'uiFontColorInput' },
    { ref: uiFontColorMuted, key: 'uiFontColorMuted' },
    // Accessibility settings
    { ref: a11yReducedMotion, key: 'a11yReducedMotion' },
    { ref: a11yHighContrast, key: 'a11yHighContrast' },
    { ref: a11yLargeText, key: 'a11yLargeText' },
    { ref: a11yDyslexiaFont, key: 'a11yDyslexiaFont' },
    { ref: a11yLineSpacing, key: 'a11yLineSpacing' },
    { ref: a11yLetterSpacing, key: 'a11yLetterSpacing' },
    { ref: a11yFocusHighlight, key: 'a11yFocusHighlight' },
    { ref: a11yScreenReaderAnnounce, key: 'a11yScreenReaderAnnounce' },
    { ref: a11yMessageVerbosity, key: 'a11yMessageVerbosity' },
    { ref: a11yKeyboardShortcuts, key: 'a11yKeyboardShortcuts' },
    { ref: a11ySoundEffects, key: 'a11ySoundEffects' },
    { ref: a11yAutoPlayMedia, key: 'a11yAutoPlayMedia' },
    // Enhanced Avatar settings
    { ref: avatarSize, key: 'avatarSize' },
    { ref: avatarBorderStyle, key: 'avatarBorderStyle' },
    { ref: avatarBorderColor, key: 'avatarBorderColor' },
    { ref: avatarBorderWidth, key: 'avatarBorderWidth' },
    { ref: avatarGlow, key: 'avatarGlow' },
    { ref: avatarGlowColor, key: 'avatarGlowColor' },
    { ref: avatarGlowIntensity, key: 'avatarGlowIntensity' },
    { ref: avatarAnimation, key: 'avatarAnimation' },
    { ref: avatarPosition, key: 'avatarPosition' },
    { ref: avatarDefaultStyle, key: 'avatarDefaultStyle' },
    { ref: userStatus, key: 'userStatus' },
    { ref: showStatusIndicator, key: 'showStatusIndicator' },
    { ref: aiAvatarPreset, key: 'aiAvatarPreset' },
    { ref: userAvatarPreset, key: 'userAvatarPreset' },
    { ref: aiAvatarIconColor, key: 'aiAvatarIconColor' },
    { ref: userAvatarIconColor, key: 'userAvatarIconColor' },
  ];

  refsToWatch.forEach(({ ref, key }) => watchAndStore(ref, key));
  watchAndStore(uiPanelSurfacePresets, 'uiPanelSurfacePresets', (value) => JSON.stringify(value ?? []));

  watch(
    uiThemeOverrides,
    (newValue) => {
      const safeValue = newValue && typeof newValue === 'object' ? newValue : {};
      localStorage.setItem('uiThemeOverrides', JSON.stringify(safeValue));
      applyTheme();
    },
    { deep: true, immediate: true }
  );

  watchAndStore(localModelEndpoint, 'localModelEndpoint', removeAPIEndpoints);

  watch(browserModelSelection, async (newValue) => {
    if (browserModelSelection.value === undefined || !selectedModel.value.includes('web-llm')) {
      return;
    }

    localStorage.setItem('browserModelSelection', newValue);
    modelDisplayName.value = newValue;
    isLoading.value = true;
    await loadNewModel(newValue, updateUIWrapper);
    isLoading.value = false;
  });

  watch(uiThemeMode, () => applyTheme(), { immediate: true });
  watch(uiThemeNativeMode, (val) => { localStorage.setItem('uiThemeNativeMode', val); applyTheme(); }, { immediate: true });
  watch(uiAccentColor, () => applyTheme(), { immediate: true });
  watch(uiSecondaryAccent, () => applyTheme(), { immediate: true });
  // Terminal color watchers
  watch(uiTerminalBackground, () => applyTheme(), { immediate: true });
  watch(uiTerminalForeground, () => applyTheme(), { immediate: true });
  watch(uiTerminalCursor, () => applyTheme(), { immediate: true });
  watch(uiTerminalSelection, () => applyTheme(), { immediate: true });
  watch(uiTerminalBlack, () => applyTheme(), { immediate: true });
  watch(uiTerminalRed, () => applyTheme(), { immediate: true });
  watch(uiTerminalGreen, () => applyTheme(), { immediate: true });
  watch(uiTerminalYellow, () => applyTheme(), { immediate: true });
  watch(uiTerminalBlue, () => applyTheme(), { immediate: true });
  watch(uiTerminalMagenta, () => applyTheme(), { immediate: true });
  watch(uiTerminalCyan, () => applyTheme(), { immediate: true });
  watch(uiTerminalWhite, () => applyTheme(), { immediate: true });
  // Status/Event color watchers
  watch(uiStatusSuccess, () => applyTheme(), { immediate: true });
  watch(uiStatusWarning, () => applyTheme(), { immediate: true });
  watch(uiStatusError, () => applyTheme(), { immediate: true });
  watch(uiStatusInfo, () => applyTheme(), { immediate: true });
  watch(uiEventRouting, () => applyTheme(), { immediate: true });
  watch(uiEventMemory, () => applyTheme(), { immediate: true });
  watch(uiEventTool, () => applyTheme(), { immediate: true });
  watch(uiEventDecision, () => applyTheme(), { immediate: true });
  watch(uiEventQuorum, () => applyTheme(), { immediate: true });
  // Git status color watchers
  watch(uiGitAdded, () => applyTheme(), { immediate: true });
  watch(uiGitModified, () => applyTheme(), { immediate: true });
  watch(uiGitDeleted, () => applyTheme(), { immediate: true });
  watch(uiGitUntracked, () => applyTheme(), { immediate: true });
  watch(uiThemePreset, () => applyTheme(), { immediate: true });
  watch(uiBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiBackgroundGradientStart, () => applyTheme(), { immediate: true });
  watch(uiBackgroundGradientEnd, () => applyTheme(), { immediate: true });
  watch(uiBackgroundGradientAngle, () => applyTheme(), { immediate: true });
  watch(uiBackgroundImage, () => applyTheme(), { immediate: true });
  watch(uiBackgroundImageOpacity, () => applyTheme(), { immediate: true });
  watch(uiBackgroundImageBlur, () => applyTheme(), { immediate: true });
  watch(uiSidebarBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiSidebarBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiSidebarBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiSidebarBackgroundGradientStart, () => applyTheme(), { immediate: true });
  watch(uiSidebarBackgroundGradientEnd, () => applyTheme(), { immediate: true });
  watch(uiSidebarBackgroundGradientAngle, () => applyTheme(), { immediate: true });
  watch(uiSidebarBackgroundImage, () => applyTheme(), { immediate: true });
  watch(uiSidebarBackgroundImageOpacity, () => applyTheme(), { immediate: true });
  watch(uiSidebarBackgroundImageBlur, () => applyTheme(), { immediate: true });
  watch(uiBackgroundIndependent, () => applyTheme(), { immediate: true });
  watch(uiLeftSidebarBackgroundImage, () => applyTheme(), { immediate: true });
  watch(uiLeftSidebarBackgroundImageOpacity, () => applyTheme(), { immediate: true });
  watch(uiLeftSidebarBackgroundImageBlur, () => applyTheme(), { immediate: true });
  watch(uiRightSidebarBackgroundImage, () => applyTheme(), { immediate: true });
  watch(uiRightSidebarBackgroundImageOpacity, () => applyTheme(), { immediate: true });
  watch(uiRightSidebarBackgroundImageBlur, () => applyTheme(), { immediate: true });
  watch(uiHeaderBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiHeaderBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiHeaderBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiHeaderBackgroundImage, () => applyTheme(), { immediate: true });
  watch(uiHeaderBackgroundImageOpacity, () => applyTheme(), { immediate: true });
  watch(uiHeaderBackgroundImageBlur, () => applyTheme(), { immediate: true });
  watch(uiChatBackgroundImage, () => applyTheme(), { immediate: true });
  watch(uiChatBackgroundImageOpacity, () => applyTheme(), { immediate: true });
  watch(uiChatBackgroundImageBlur, () => applyTheme(), { immediate: true });
  watch(uiInputBarBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiInputBarBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiInputBarBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiInputBarBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiInputBarBorderColor, () => applyTheme(), { immediate: true });
  watch(uiInputBarBorderOpacity, () => applyTheme(), { immediate: true });
  watch(uiInputBarGlow, () => applyTheme(), { immediate: true });
  watch(uiToolCardBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiToolCardBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiToolCardBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiToolCardBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiToolCardBorderColor, () => applyTheme(), { immediate: true });
  watch(uiToolCardBorderOpacity, () => applyTheme(), { immediate: true });
  watch(uiToolCardGlow, () => applyTheme(), { immediate: true });
  watch(uiUserMessageBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiUserMessageBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiUserMessageBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiUserMessageBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiUserMessageBorderColor, () => applyTheme(), { immediate: true });
  watch(uiUserMessageBorderOpacity, () => applyTheme(), { immediate: true });
  watch(uiAssistantMessageBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiAssistantMessageBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiAssistantMessageBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiAssistantMessageBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiAssistantMessageBorderColor, () => applyTheme(), { immediate: true });
  watch(uiAssistantMessageBorderOpacity, () => applyTheme(), { immediate: true });
  watch(uiSendButtonBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiSendButtonTextColor, () => applyTheme(), { immediate: true });
  watch(uiSendButtonGlow, () => applyTheme(), { immediate: true });
  // Button theming watchers
  watch(uiButtonBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiButtonBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiButtonBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiButtonBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiButtonBorderColor, () => applyTheme(), { immediate: true });
  watch(uiButtonBorderOpacity, () => applyTheme(), { immediate: true });
  watch(uiButtonGlow, () => applyTheme(), { immediate: true });
  watch(uiStopButtonBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiDrawerBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiDrawerBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiDrawerBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiDrawerBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiDrawerBorderColor, () => applyTheme(), { immediate: true });
  watch(uiDrawerBorderOpacity, () => applyTheme(), { immediate: true });
  watch(uiDrawerCardBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiDrawerCardBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiDrawerCardBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiCodeEditorBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiCodeEditorBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiTerminalBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiTerminalBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiTerminalHeaderBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiTerminalHeaderBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiFileBrowserBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiFileBrowserBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiDialogContentBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiDialogContentBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiCardBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiCardBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiFilterButtonBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiFilterButtonBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiFilterButtonActiveBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiFilterButtonActiveBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiNixieButtonBackgroundColor, () => applyTheme(), { immediate: true });
  // Thinking dropdown theming watchers - header
  watch(uiThinkingHeaderBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiThinkingHeaderBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiThinkingHeaderBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiThinkingHeaderBackgroundOpacity, () => applyTheme(), { immediate: true });
  watch(uiThinkingHeaderBorderColor, () => applyTheme(), { immediate: true });
  watch(uiThinkingHeaderBorderOpacity, () => applyTheme(), { immediate: true });
  // Thinking dropdown theming watchers - content
  watch(uiThinkingContentBackgroundMode, () => applyTheme(), { immediate: true });
  watch(uiThinkingContentBackgroundPreset, () => applyTheme(), { immediate: true });
  watch(uiThinkingContentBackgroundColor, () => applyTheme(), { immediate: true });
  watch(uiThinkingContentBackgroundOpacity, () => applyTheme(), { immediate: true });
  // Thinking dropdown event colors watchers
  watch(uiEventColorRouting, () => applyTheme(), { immediate: true });
  watch(uiEventColorMemory, () => applyTheme(), { immediate: true });
  watch(uiEventColorTool, () => applyTheme(), { immediate: true });
  watch(uiEventColorDecision, () => applyTheme(), { immediate: true });
  watch(uiEventColorQuorum, () => applyTheme(), { immediate: true });
  watch(uiEventColorError, () => applyTheme(), { immediate: true });
  // Voice mode colors watchers
  watch(uiVoiceListeningColor, () => applyTheme(), { immediate: true });
  watch(uiVoiceSpeakingColor, () => applyTheme(), { immediate: true });
  watch(uiVoiceProcessingColor, () => applyTheme(), { immediate: true });
  watch(uiEffectScanlines, () => applyTheme(), { immediate: true });
  watch(uiEffectScanlineOpacity, () => applyTheme(), { immediate: true });
  watch(uiEffectNoise, () => applyTheme(), { immediate: true });
  watch(uiEffectNoiseOpacity, () => applyTheme(), { immediate: true });
  watch(uiEffectGlowPulse, () => applyTheme(), { immediate: true });
  watch(uiEffectGlowPulseStrength, () => applyTheme(), { immediate: true });
  watch(uiEffectGlowPulseSpeed, () => applyTheme(), { immediate: true });
  watch(uiEffectGrid, () => applyTheme(), { immediate: true });
  watch(uiEffectGridOpacity, () => applyTheme(), { immediate: true });
  watch(uiEffectVignette, () => applyTheme(), { immediate: true });
  watch(uiEffectVignetteStrength, () => applyTheme(), { immediate: true });
  watch(uiEffectAurora, () => applyTheme(), { immediate: true });
  watch(uiEffectAuroraOpacity, () => applyTheme(), { immediate: true });
  watch(uiEffectAuroraSpeed, () => applyTheme(), { immediate: true });
  watch(uiEffectHeaderShimmer, () => applyTheme(), { immediate: true });
  watch(uiEffectHeaderShimmerStrength, () => applyTheme(), { immediate: true });
  watch(uiEffectHeaderShimmerSpeed, () => applyTheme(), { immediate: true });
  watch(uiLiteMode, () => applyTheme(), { immediate: true });
  watch(uiPanelDepth, () => applyTheme(), { immediate: true });
  watch(uiEffectMessageDepth, () => applyTheme(), { immediate: true });
  watch(uiEffectMessageDepthStrength, () => applyTheme(), { immediate: true });
  watch(uiEffectPanelEdge, () => applyTheme(), { immediate: true });
  watch(uiEffectPanelEdgeStrength, () => applyTheme(), { immediate: true });
  watch(uiEffectMessageEdge, () => applyTheme(), { immediate: true });
  watch(uiEffectMessageEdgeStrength, () => applyTheme(), { immediate: true });
  watch(uiEffectMessageEdgeTint, () => applyTheme(), { immediate: true });
  watch(uiEffectPanelGlow, () => applyTheme(), { immediate: true });
  watch(uiEffectPanelGlowStrength, () => applyTheme(), { immediate: true });
  watch(uiEffectPanelBevel, () => applyTheme(), { immediate: true });
  watch(uiEffectPanelBevelStrength, () => applyTheme(), { immediate: true });
  watch(uiBackgroundBlur, () => applyTheme(), { immediate: true });
  watch(uiHeaderBlur, () => applyTheme(), { immediate: true });
  watch(uiAnimButtonRipple, () => applyTheme(), { immediate: true });
  watch(uiAnimMessageMotion, () => applyTheme(), { immediate: true });
  watch(uiAnimHoverLift, () => applyTheme(), { immediate: true });
  watch(uiAnimBackgroundDrift, () => applyTheme(), { immediate: true });
  watch(uiAnimBackgroundDriftSpeed, () => applyTheme(), { immediate: true });
  watch(uiAnimButtonMotion, () => applyTheme(), { immediate: true });
  watch(uiAnimButtonScale, () => applyTheme(), { immediate: true });
  watch(uiAnimSpeed, () => applyTheme(), { immediate: true });
  watch(uiFontScale, () => applyTheme(), { immediate: true });
  watch(uiBorderRadius, () => applyTheme(), { immediate: true });
  watch(uiCompactMode, () => applyTheme(), { immediate: true });
  // Nixie tube settings watchers
  watch(uiNixieColor, (val) => { localStorage.setItem('uiNixieColor', val); applyTheme(); }, { immediate: true });
  watch(uiNixieGlowColor, (val) => { localStorage.setItem('uiNixieGlowColor', val); applyTheme(); }, { immediate: true });
  watch(uiNixieSpeed, (val) => { localStorage.setItem('uiNixieSpeed', String(val)); applyTheme(); }, { immediate: true });
  watch(uiNixieGlowIntensity, (val) => { localStorage.setItem('uiNixieGlowIntensity', String(val)); applyTheme(); }, { immediate: true });
  watch(uiNixieFlicker, (val) => { localStorage.setItem('uiNixieFlicker', String(val)); applyTheme(); }, { immediate: true });
  // Exit button Nixie watchers
  watch(uiNixieExitColor, (val) => { localStorage.setItem('uiNixieExitColor', val); applyTheme(); }, { immediate: true });
  watch(uiNixieExitGlowColor, (val) => { localStorage.setItem('uiNixieExitGlowColor', val); applyTheme(); }, { immediate: true });
  watch(uiNixieExitGlowIntensity, (val) => { localStorage.setItem('uiNixieExitGlowIntensity', String(val)); applyTheme(); }, { immediate: true });
  watch(uiFontFamilyGlobal, () => applyTheme(), { immediate: true });
  watch(uiFontFamilyHeader, () => applyTheme(), { immediate: true });
  watch(uiFontFamilySidebar, () => applyTheme(), { immediate: true });
  watch(uiFontFamilyMessages, () => applyTheme(), { immediate: true });
  watch(uiFontFamilyInput, () => applyTheme(), { immediate: true });
  watch(uiFontFamilyCode, () => applyTheme(), { immediate: true });
  watch(uiFontColorHeader, () => applyTheme(), { immediate: true });
  watch(uiFontColorSidebar, () => applyTheme(), { immediate: true });
  watch(uiFontColorMessages, () => applyTheme(), { immediate: true });
  watch(uiFontColorInput, () => applyTheme(), { immediate: true });
  watch(uiFontColorMuted, () => applyTheme(), { immediate: true });
  // Accessibility watchers that affect visual styles
  watch(a11yReducedMotion, () => applyTheme(), { immediate: true });
  watch(a11yHighContrast, () => applyTheme(), { immediate: true });
  watch(a11yLargeText, () => applyTheme(), { immediate: true });
  watch(a11yDyslexiaFont, () => applyTheme(), { immediate: true });
  watch(a11yLineSpacing, () => applyTheme(), { immediate: true });
  watch(a11yLetterSpacing, () => applyTheme(), { immediate: true });
  watch(a11yFocusHighlight, () => applyTheme(), { immediate: true });
  // Avatar watchers that affect visual styles
  watch(avatarSize, () => applyTheme(), { immediate: true });
  watch(avatarBorderStyle, () => applyTheme(), { immediate: true });
  watch(avatarBorderColor, () => applyTheme(), { immediate: true });
  watch(avatarBorderWidth, () => applyTheme(), { immediate: true });
  watch(avatarGlow, () => applyTheme(), { immediate: true });
  watch(avatarGlowColor, () => applyTheme(), { immediate: true });
  watch(avatarGlowIntensity, () => applyTheme(), { immediate: true });
  watch(avatarAnimation, () => applyTheme(), { immediate: true });
  setupThemeListener();
}
