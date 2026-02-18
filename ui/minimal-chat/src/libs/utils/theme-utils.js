import {
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
  // Drawer theming
  uiDrawerBackgroundMode,
  uiDrawerBackgroundPreset,
  uiDrawerBackgroundColor,
  uiDrawerBackgroundOpacity,
  uiDrawerBorderColor,
  uiDrawerBorderOpacity,
  uiDrawerCardBackgroundMode,
  uiDrawerCardBackgroundColor,
  uiDrawerCardBackgroundOpacity,
  // Code Editor, Terminal, Files
  uiCodeEditorBackgroundColor,
  uiCodeEditorBackgroundOpacity,
  uiTerminalBackgroundColor,
  uiTerminalBackgroundOpacity,
  uiTerminalHeaderBackgroundColor,
  uiTerminalHeaderBackgroundOpacity,
  uiFileBrowserBackgroundColor,
  uiFileBrowserBackgroundOpacity,
  // Dialog content areas
  uiDialogContentBackgroundColor,
  uiDialogContentBackgroundOpacity,
  // Cards and filter buttons
  uiCardBackgroundColor,
  uiCardBackgroundOpacity,
  uiFilterButtonBackgroundColor,
  uiFilterButtonBackgroundOpacity,
  uiFilterButtonActiveBackgroundColor,
  uiFilterButtonActiveBackgroundOpacity,
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
  uiNixieButtonBackgroundColor,
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
  // Avatar settings
  avatarSize,
  avatarBorderStyle,
  avatarBorderColor,
  avatarBorderWidth,
  avatarGlow,
  avatarGlowColor,
  avatarGlowIntensity,
  avatarAnimation,
  aiAvatarIconColor,
  userAvatarIconColor
} from '@/libs/state-management/state';
import {
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
  DEFAULT_THINKING_DROPDOWN_THEME,
  DEFAULT_VOICE_COLORS,
  DEFAULT_NIXIE_THEME,
  DEFAULT_EXIT_BUTTON_THEME,
  DEFAULT_NIXIE_BUTTON_THEME
} from '@/libs/utils/theme-defaults';

let glowPulseFlip = false;

export const DEFAULT_ACCENT_COLOR = '#0099ff';
export const DEFAULT_THEME_PRESET = 'deep-space';
export const DEFAULT_BACKGROUND_PRESET = 'deep-space';
export const DEFAULT_SIDEBAR_BACKGROUND_PRESET = 'deep-space';

// Font family presets - maps selection values to CSS font-family stacks
export const FONT_FAMILIES = {
  default: '"Exo 2", "Segoe UI", "Helvetica Neue", sans-serif',
  inherit: 'inherit',
  system: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  inter: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  roboto: '"Roboto", "Helvetica Neue", Arial, sans-serif',
  'open-sans': '"Open Sans", "Helvetica Neue", Arial, sans-serif',
  lato: '"Lato", "Helvetica Neue", Arial, sans-serif',
  montserrat: '"Montserrat", "Helvetica Neue", Arial, sans-serif',
  poppins: '"Poppins", "Helvetica Neue", Arial, sans-serif',
  'source-sans': '"Source Sans Pro", "Helvetica Neue", Arial, sans-serif',
  nunito: '"Nunito", "Helvetica Neue", Arial, sans-serif',
  raleway: '"Raleway", "Helvetica Neue", Arial, sans-serif',
  ubuntu: '"Ubuntu", "Helvetica Neue", Arial, sans-serif',
  'fira-sans': '"Fira Sans", "Helvetica Neue", Arial, sans-serif',
  'ibm-plex': '"IBM Plex Sans", "Helvetica Neue", Arial, sans-serif',
  'dm-sans': '"DM Sans", "Helvetica Neue", Arial, sans-serif',
  'space-grotesk': '"Space Grotesk", "Helvetica Neue", Arial, sans-serif',
  'jetbrains-mono': '"JetBrains Mono", "Fira Code", "Consolas", monospace',
  'fira-code': '"Fira Code", "JetBrains Mono", "Consolas", monospace',
  'source-code': '"Source Code Pro", "Consolas", monospace',
  // Dyslexia-friendly fonts
  'opendyslexic': '"OpenDyslexic", "Comic Sans MS", "Arial", sans-serif',
  'lexie-readable': '"Lexie Readable", "Comic Sans MS", "Arial", sans-serif',
  'atkinson': '"Atkinson Hyperlegible", "Arial", sans-serif',
};

export const FONT_FAMILY_OPTIONS = [
  { label: 'Default (Exo 2)', value: 'default' },
  { label: 'Inherit from Parent', value: 'inherit' },
  { label: 'System UI', value: 'system' },
  { label: 'Inter', value: 'inter' },
  { label: 'Roboto', value: 'roboto' },
  { label: 'Open Sans', value: 'open-sans' },
  { label: 'Lato', value: 'lato' },
  { label: 'Montserrat', value: 'montserrat' },
  { label: 'Poppins', value: 'poppins' },
  { label: 'Source Sans Pro', value: 'source-sans' },
  { label: 'Nunito', value: 'nunito' },
  { label: 'Raleway', value: 'raleway' },
  { label: 'Ubuntu', value: 'ubuntu' },
  { label: 'Fira Sans', value: 'fira-sans' },
  { label: 'IBM Plex Sans', value: 'ibm-plex' },
  { label: 'DM Sans', value: 'dm-sans' },
  { label: 'Space Grotesk', value: 'space-grotesk' },
];

export const CODE_FONT_OPTIONS = [
  { label: 'Default (JetBrains Mono)', value: 'default' },
  { label: 'JetBrains Mono', value: 'jetbrains-mono' },
  { label: 'Fira Code', value: 'fira-code' },
  { label: 'Source Code Pro', value: 'source-code' },
];

const resolveFontFamily = (value, isCode = false) => {
  if (!value || value === 'default') {
    return isCode
      ? FONT_FAMILIES['jetbrains-mono']
      : FONT_FAMILIES.default;
  }
  if (value === 'inherit') {
    return 'inherit';
  }
  return FONT_FAMILIES[value] || FONT_FAMILIES.default;
};

const THEME_PRESETS = {
  'deep-space': {
    label: 'Deep Space',
    modes: {
      dark: {},
      light: {}
    }
  },
  quorum: {
    label: 'Quorum',
    modes: {
      dark: {
        '--vera-bg': '#0a1018',
        '--vera-surface': '#121c2a',
        '--vera-panel': '#1a2436',
        '--vera-panel-alt': '#1f2c42',
        '--vera-panel-muted': '#0d1420',
        '--vera-text': '#d8e4ef',
        '--vera-text-muted': '#93a6ba',
        '--vera-border': 'rgba(120, 170, 255, 0.2)',
        '--vera-glass-bg': 'rgba(10, 18, 28, 0.72)',
        '--vera-glass-strong': 'rgba(12, 20, 32, 0.92)',
        '--vera-glass-border': 'rgba(120, 170, 255, 0.3)',
        '--vera-glow-soft': '0 0 20px rgba(0, 153, 255, 0.3)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(26, 36, 52, 0.96), rgba(12, 18, 28, 0.96))',
        '--vera-app-bg': 'radial-gradient(1100px circle at 18% -10%, rgba(0, 153, 255, 0.2), transparent 45%), radial-gradient(900px circle at 80% 0%, rgba(0, 90, 160, 0.14), transparent 52%), #0a1018'
      },
      light: {
        '--vera-bg': '#f2f6fb',
        '--vera-surface': '#ffffff',
        '--vera-panel': '#eaf1f9',
        '--vera-panel-alt': '#e0e9f3',
        '--vera-panel-muted': '#d8e3ef',
        '--vera-text': '#1d2b3a',
        '--vera-text-muted': '#586b7c',
        '--vera-border': 'rgba(15, 28, 45, 0.18)',
        '--vera-glass-bg': 'rgba(255, 255, 255, 0.84)',
        '--vera-glass-strong': 'rgba(255, 255, 255, 0.94)',
        '--vera-glass-border': 'rgba(15, 110, 168, 0.22)',
        '--vera-glow-soft': '0 0 20px rgba(15, 110, 168, 0.22)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(224, 235, 246, 0.96))',
        '--vera-app-bg': 'radial-gradient(1200px circle at 20% -10%, rgba(15, 110, 168, 0.12), transparent 45%), radial-gradient(900px circle at 80% 0%, rgba(15, 110, 168, 0.1), transparent 55%), #f2f6fb'
      }
    }
  },
  swarm: {
    label: 'Swarm',
    modes: {
      dark: {
        '--vera-bg': '#070b10',
        '--vera-surface': '#0f1724',
        '--vera-panel': '#162131',
        '--vera-panel-alt': '#1b2a3d',
        '--vera-panel-muted': '#0b121c',
        '--vera-text': '#d2dee9',
        '--vera-text-muted': '#8ea2b8',
        '--vera-border': 'rgba(0, 153, 255, 0.2)',
        '--vera-glass-bg': 'rgba(9, 16, 26, 0.7)',
        '--vera-glass-strong': 'rgba(11, 18, 30, 0.92)',
        '--vera-glass-border': 'rgba(0, 153, 255, 0.28)',
        '--vera-glow-soft': '0 0 22px rgba(0, 153, 255, 0.34)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(22, 33, 49, 0.96), rgba(9, 15, 24, 0.96))',
        '--vera-app-bg': 'radial-gradient(1200px circle at 15% -10%, rgba(0, 153, 255, 0.22), transparent 45%), radial-gradient(900px circle at 85% 0%, rgba(0, 90, 160, 0.18), transparent 52%), #070b10'
      },
      light: {
        '--vera-bg': '#f1f5fa',
        '--vera-surface': '#ffffff',
        '--vera-panel': '#e6edf6',
        '--vera-panel-alt': '#dde7f1',
        '--vera-panel-muted': '#d4dfeb',
        '--vera-text': '#1c2a38',
        '--vera-text-muted': '#57687a',
        '--vera-border': 'rgba(15, 28, 45, 0.2)',
        '--vera-glass-bg': 'rgba(255, 255, 255, 0.86)',
        '--vera-glass-strong': 'rgba(255, 255, 255, 0.95)',
        '--vera-glass-border': 'rgba(15, 110, 168, 0.24)',
        '--vera-glow-soft': '0 0 20px rgba(15, 110, 168, 0.22)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(223, 233, 244, 0.96))',
        '--vera-app-bg': 'radial-gradient(1200px circle at 20% -10%, rgba(15, 110, 168, 0.14), transparent 45%), radial-gradient(900px circle at 80% 0%, rgba(15, 110, 168, 0.1), transparent 55%), #f1f5fa'
      }
    }
  },
  transparent: {
    label: 'Transparent',
    modes: {
      dark: {
        '--vera-panel': 'transparent',
        '--vera-panel-alt': 'rgba(255, 255, 255, 0.03)',
        '--vera-panel-muted': 'transparent',
        '--vera-glass-bg': 'rgba(0, 0, 0, 0.2)',
        '--vera-glass-strong': 'rgba(0, 0, 0, 0.4)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(0, 0, 0, 0.15), rgba(0, 0, 0, 0.25))'
      },
      light: {
        '--vera-panel': 'transparent',
        '--vera-panel-alt': 'rgba(0, 0, 0, 0.03)',
        '--vera-panel-muted': 'transparent',
        '--vera-glass-bg': 'rgba(255, 255, 255, 0.2)',
        '--vera-glass-strong': 'rgba(255, 255, 255, 0.4)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(255, 255, 255, 0.15), rgba(255, 255, 255, 0.25))'
      }
    }
  },
  'glass-lite': {
    label: 'Glass (Lite)',
    modes: {
      dark: {
        '--vera-panel': 'rgba(15, 20, 30, 0.5)',
        '--vera-panel-alt': 'rgba(20, 28, 40, 0.55)',
        '--vera-panel-muted': 'rgba(10, 15, 22, 0.45)',
        '--vera-glass-bg': 'rgba(15, 22, 35, 0.5)',
        '--vera-glass-strong': 'rgba(18, 26, 40, 0.7)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(20, 30, 45, 0.55), rgba(12, 18, 28, 0.6))'
      },
      light: {
        '--vera-panel': 'rgba(255, 255, 255, 0.5)',
        '--vera-panel-alt': 'rgba(245, 248, 252, 0.55)',
        '--vera-panel-muted': 'rgba(240, 244, 250, 0.45)',
        '--vera-glass-bg': 'rgba(255, 255, 255, 0.55)',
        '--vera-glass-strong': 'rgba(255, 255, 255, 0.7)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(255, 255, 255, 0.6), rgba(240, 245, 252, 0.55))'
      }
    }
  },
  'glass-strong': {
    label: 'Glass (Strong)',
    modes: {
      dark: {
        '--vera-panel': 'rgba(12, 18, 28, 0.88)',
        '--vera-panel-alt': 'rgba(16, 24, 36, 0.9)',
        '--vera-panel-muted': 'rgba(8, 12, 20, 0.85)',
        '--vera-glass-bg': 'rgba(10, 16, 26, 0.85)',
        '--vera-glass-strong': 'rgba(12, 18, 28, 0.95)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(18, 28, 42, 0.92), rgba(10, 16, 26, 0.95))'
      },
      light: {
        '--vera-panel': 'rgba(255, 255, 255, 0.9)',
        '--vera-panel-alt': 'rgba(248, 250, 254, 0.92)',
        '--vera-panel-muted': 'rgba(244, 248, 252, 0.88)',
        '--vera-glass-bg': 'rgba(255, 255, 255, 0.88)',
        '--vera-glass-strong': 'rgba(255, 255, 255, 0.96)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(255, 255, 255, 0.94), rgba(245, 250, 255, 0.92))'
      }
    }
  },
  'steel-veil': {
    label: 'Steel Veil',
    modes: {
      dark: {
        '--vera-bg': '#1a1c20',
        '--vera-surface': '#22252a',
        '--vera-panel': '#22252a',
        '--vera-panel-alt': '#2a2d33',
        '--vera-panel-muted': '#1e2024',
        '--vera-text': '#cbd5e1',
        '--vera-text-muted': '#94a3b8',
        '--vera-border': 'rgba(148, 163, 184, 0.2)',
        '--vera-glass-bg': 'rgba(34, 37, 42, 0.85)',
        '--vera-glass-strong': 'rgba(42, 45, 51, 0.92)',
        '--vera-glass-border': 'rgba(148, 163, 184, 0.25)',
        '--vera-glow-soft': '0 0 20px rgba(148, 163, 184, 0.2)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(42, 45, 51, 0.96), rgba(30, 32, 36, 0.96))'
      },
      light: {
        '--vera-bg': '#e2e8f0',
        '--vera-surface': '#f1f5f9',
        '--vera-panel': '#f1f5f9',
        '--vera-panel-alt': '#f8fafc',
        '--vera-panel-muted': '#e8ecf2',
        '--vera-text': '#1e293b',
        '--vera-text-muted': '#475569',
        '--vera-border': 'rgba(71, 85, 105, 0.2)',
        '--vera-glass-bg': 'rgba(241, 245, 249, 0.9)',
        '--vera-glass-strong': 'rgba(248, 250, 252, 0.95)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(248, 250, 252, 0.96), rgba(226, 232, 240, 0.96))'
      }
    }
  },
  'orbital-dusk': {
    label: 'Orbital Dusk',
    modes: {
      dark: {
        '--vera-bg': '#1a1520',
        '--vera-surface': '#1e1820',
        '--vera-panel': '#1e1820',
        '--vera-panel-alt': '#261e28',
        '--vera-panel-muted': '#161218',
        '--vera-text': '#e8dce8',
        '--vera-text-muted': '#b8a8b8',
        '--vera-border': 'rgba(249, 115, 22, 0.25)',
        '--vera-glass-bg': 'rgba(30, 24, 32, 0.85)',
        '--vera-glass-strong': 'rgba(38, 30, 40, 0.92)',
        '--vera-glass-border': 'rgba(249, 115, 22, 0.3)',
        '--vera-glow-soft': '0 0 20px rgba(249, 115, 22, 0.25)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(38, 30, 40, 0.96), rgba(26, 21, 32, 0.96))'
      },
      light: {
        '--vera-bg': '#fef3e8',
        '--vera-surface': '#fff8f2',
        '--vera-panel': '#fff8f2',
        '--vera-panel-alt': '#ffffff',
        '--vera-panel-muted': '#fef0e4',
        '--vera-text': '#44302a',
        '--vera-text-muted': '#7a5a4a',
        '--vera-border': 'rgba(249, 115, 22, 0.2)',
        '--vera-glass-bg': 'rgba(255, 248, 242, 0.9)',
        '--vera-glass-strong': 'rgba(255, 255, 255, 0.95)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(254, 243, 232, 0.96))'
      }
    }
  },
  glacier: {
    label: 'Glacier',
    modes: {
      dark: {
        '--vera-bg': '#0a1520',
        '--vera-surface': '#10202e',
        '--vera-panel': '#10202e',
        '--vera-panel-alt': '#162838',
        '--vera-panel-muted': '#0c1822',
        '--vera-text': '#e2eef8',
        '--vera-text-muted': '#8ab4d4',
        '--vera-border': 'rgba(8, 145, 178, 0.25)',
        '--vera-glass-bg': 'rgba(16, 32, 46, 0.85)',
        '--vera-glass-strong': 'rgba(22, 40, 56, 0.92)',
        '--vera-glass-border': 'rgba(8, 145, 178, 0.3)',
        '--vera-glow-soft': '0 0 20px rgba(8, 145, 178, 0.3)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(22, 40, 56, 0.96), rgba(10, 21, 32, 0.96))'
      },
      light: {
        '--vera-bg': '#e8eef5',
        '--vera-surface': '#f1f5f9',
        '--vera-panel': '#f1f5f9',
        '--vera-panel-alt': '#ffffff',
        '--vera-panel-muted': '#e0e9f3',
        '--vera-text': '#1e293b',
        '--vera-text-muted': '#0e7490',
        '--vera-border': 'rgba(8, 145, 178, 0.2)',
        '--vera-glass-bg': 'rgba(241, 245, 249, 0.9)',
        '--vera-glass-strong': 'rgba(255, 255, 255, 0.95)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(232, 238, 245, 0.96))'
      }
    }
  },
  'nixie-amber': {
    label: 'Nixie Amber',
    modes: {
      dark: {
        '--vera-bg': '#0a0604',
        '--vera-surface': '#120a06',
        '--vera-panel': '#120a06',
        '--vera-panel-alt': '#1a0f08',
        '--vera-panel-muted': '#0e0804',
        '--vera-text': '#ffb060',
        '--vera-text-muted': '#c08040',
        '--vera-border': 'rgba(255, 144, 64, 0.3)',
        '--vera-glass-bg': 'rgba(18, 10, 6, 0.88)',
        '--vera-glass-strong': 'rgba(26, 15, 8, 0.94)',
        '--vera-glass-border': 'rgba(255, 144, 64, 0.35)',
        '--vera-glow-soft': '0 0 20px rgba(255, 144, 64, 0.35)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(26, 15, 8, 0.96), rgba(10, 6, 4, 0.96))'
      },
      light: {
        '--vera-bg': '#fef6e8',
        '--vera-surface': '#fff8f0',
        '--vera-panel': '#fff8f0',
        '--vera-panel-alt': '#ffffff',
        '--vera-panel-muted': '#fef2dc',
        '--vera-text': '#5a3a1a',
        '--vera-text-muted': '#8a6030',
        '--vera-border': 'rgba(255, 144, 64, 0.25)',
        '--vera-glass-bg': 'rgba(255, 248, 240, 0.9)',
        '--vera-glass-strong': 'rgba(255, 255, 255, 0.95)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(254, 246, 232, 0.96))'
      }
    }
  },
  'dos-green': {
    label: 'DOS Green',
    modes: {
      dark: {
        '--vera-bg': '#000000',
        '--vera-surface': '#001100',
        '--vera-panel': '#001100',
        '--vera-panel-alt': '#002200',
        '--vera-panel-muted': '#000800',
        '--vera-text': '#33ff33',
        '--vera-text-muted': '#22aa22',
        '--vera-border': 'rgba(51, 255, 51, 0.3)',
        '--vera-glass-bg': 'rgba(0, 17, 0, 0.9)',
        '--vera-glass-strong': 'rgba(0, 34, 0, 0.95)',
        '--vera-glass-border': 'rgba(51, 255, 51, 0.35)',
        '--vera-glow-soft': '0 0 20px rgba(51, 255, 51, 0.35)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(0, 34, 0, 0.96), rgba(0, 8, 0, 0.96))'
      },
      light: {
        '--vera-bg': '#e8f5e8',
        '--vera-surface': '#f0faf0',
        '--vera-panel': '#f0faf0',
        '--vera-panel-alt': '#f8fff8',
        '--vera-panel-muted': '#e0f0e0',
        '--vera-text': '#0a4a0a',
        '--vera-text-muted': '#1a6a1a',
        '--vera-border': 'rgba(34, 170, 34, 0.25)',
        '--vera-glass-bg': 'rgba(240, 250, 240, 0.9)',
        '--vera-glass-strong': 'rgba(248, 255, 248, 0.95)',
        '--vera-panel-gradient': 'linear-gradient(145deg, rgba(248, 255, 248, 0.96), rgba(232, 245, 232, 0.96))'
      }
    }
  }
};

export const THEME_PRESET_OPTIONS = Object.entries(THEME_PRESETS).map(([value, preset]) => ({
  label: preset.label,
  value
}));

export const BACKGROUND_PRESETS = {
  'transparent': {
    label: 'Transparent',
    value: 'transparent'
  },
  'glass-light': {
    label: 'Glass Light',
    value: 'var(--vera-glass-bg)'
  },
  'glass-dark': {
    label: 'Glass Dark',
    value: 'var(--vera-glass-strong)'
  },
  'solid-color': {
    label: 'Solid Color',
    value: 'var(--vera-panel)'
  },
  'deep-space': {
    label: 'Deep Space',
    value: 'radial-gradient(1100px circle at 18% -10%, rgba(0, 153, 255, 0.14), transparent 45%), radial-gradient(900px circle at 80% 0%, rgba(0, 90, 160, 0.12), transparent 52%), #0b0f14'
  },
  'steel-veil': {
    label: 'Steel Veil',
    value: 'linear-gradient(135deg, rgba(12, 18, 28, 0.96), rgba(20, 28, 40, 0.96))'
  },
  'orbital-dusk': {
    label: 'Orbital Dusk',
    value: 'radial-gradient(1000px circle at 12% 0%, rgba(120, 170, 255, 0.2), transparent 50%), radial-gradient(900px circle at 85% 10%, rgba(0, 90, 160, 0.16), transparent 55%), #0a1118'
  },
  'glacier': {
    label: 'Glacier',
    value: 'linear-gradient(160deg, rgba(14, 22, 34, 0.96), rgba(22, 34, 48, 0.96))'
  },
  'dos-green': {
    label: 'DOS Green',
    value: 'radial-gradient(900px circle at 16% -12%, rgba(0, 255, 140, 0.18), transparent 55%), #06140d'
  },
  'nixie-amber': {
    label: 'Nixie Amber',
    value: 'radial-gradient(900px circle at 16% -12%, rgba(255, 168, 96, 0.2), transparent 55%), #140b06'
  }
};

export const BACKGROUND_PRESET_OPTIONS = Object.entries(BACKGROUND_PRESETS).map(([value, preset]) => ({
  label: preset.label,
  value
}));

const PRESET_KEYS = Object.values(THEME_PRESETS).reduce((keys, preset) => {
  const modeKeys = Object.values(preset.modes || {}).flatMap((modeVars) => Object.keys(modeVars || {}));
  modeKeys.forEach((key) => keys.add(key));
  return keys;
}, new Set());

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const normalizeHex = (value) => {
  if (!value || typeof value !== 'string') {
    return '';
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return '';
  }
  if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(trimmed)) {
    if (trimmed.length === 4) {
      const [r, g, b] = trimmed.slice(1).split('');
      return `#${r}${r}${g}${g}${b}${b}`.toLowerCase();
    }
    return trimmed.toLowerCase();
  }
  return '';
};

const hexToRgb = (hex) => {
  const normalized = normalizeHex(hex);
  if (!normalized) {
    return null;
  }
  const value = normalized.replace('#', '');
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  if (Number.isNaN(r) || Number.isNaN(g) || Number.isNaN(b)) {
    return null;
  }
  return { r, g, b };
};

const rgbToHex = ({ r, g, b }) =>
  `#${[r, g, b].map((value) => clamp(Math.round(value), 0, 255).toString(16).padStart(2, '0')).join('')}`;

// Extract hex color from various CSS color formats (hex, rgba, rgb)
const extractHexColor = (value) => {
  if (!value || typeof value !== 'string') return '';
  const trimmed = value.trim();

  // Already a hex color
  const hexNormalized = normalizeHex(trimmed);
  if (hexNormalized) return hexNormalized;

  // Try to parse rgba(r, g, b, a) or rgb(r, g, b)
  const rgbaMatch = trimmed.match(/rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
  if (rgbaMatch) {
    const r = parseInt(rgbaMatch[1], 10);
    const g = parseInt(rgbaMatch[2], 10);
    const b = parseInt(rgbaMatch[3], 10);
    if (!Number.isNaN(r) && !Number.isNaN(g) && !Number.isNaN(b)) {
      return rgbToHex({ r, g, b });
    }
  }

  return '';
};

const parseRgbChannels = (value) => {
  if (!value || typeof value !== 'string') {
    return null;
  }
  const match = value.match(/^\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})/);
  if (!match) {
    return null;
  }
  return {
    r: clamp(Number(match[1]), 0, 255),
    g: clamp(Number(match[2]), 0, 255),
    b: clamp(Number(match[3]), 0, 255)
  };
};

const parseCssColor = (value) => {
  if (!value || typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const normalized = normalizeHex(trimmed);
  if (normalized) {
    const rgb = hexToRgb(normalized);
    return rgb ? { hex: normalized, rgb } : null;
  }
  const rgbMatch = trimmed.match(/rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*[\d.]+\s*)?\)/i);
  if (!rgbMatch) {
    return null;
  }
  const rgb = {
    r: clamp(Number(rgbMatch[1]), 0, 255),
    g: clamp(Number(rgbMatch[2]), 0, 255),
    b: clamp(Number(rgbMatch[3]), 0, 255)
  };
  return { hex: rgbToHex(rgb), rgb };
};

const adjustColor = (hex, amount) => {
  const rgb = hexToRgb(hex);
  if (!rgb) {
    return hex;
  }
  const mix = (channel) => clamp(Math.round(channel + (255 - channel) * amount), 0, 255);
  const r = amount >= 0 ? mix(rgb.r) : clamp(Math.round(rgb.r * (1 + amount)), 0, 255);
  const g = amount >= 0 ? mix(rgb.g) : clamp(Math.round(rgb.g * (1 + amount)), 0, 255);
  const b = amount >= 0 ? mix(rgb.b) : clamp(Math.round(rgb.b * (1 + amount)), 0, 255);
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`;
};

// Calculate relative luminance (0-1) per WCAG formula
const getLuminance = (rgb) => {
  if (!rgb) return 0.5;
  const toLinear = (c) => {
    const sRGB = c / 255;
    return sRGB <= 0.03928 ? sRGB / 12.92 : Math.pow((sRGB + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * toLinear(rgb.r) + 0.7152 * toLinear(rgb.g) + 0.0722 * toLinear(rgb.b);
};

// Check if a color is "light" (should have dark text on it)
const isLightColor = (hex) => {
  const rgb = hexToRgb(hex);
  return getLuminance(rgb) > 0.4;
};

const toRgba = (hex, alpha) => {
  const rgb = hexToRgb(hex);
  if (!rgb) {
    return hex;
  }
  const safeAlpha = clamp(alpha, 0, 1);
  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${safeAlpha})`;
};

const colorWithOpacity = (hex, alpha, fallback) => {
  const normalized = normalizeHex(hex);
  if (!normalized) {
    return fallback;
  }
  return toRgba(normalized, alpha);
};

const resolveThemeMode = (mode) => {
  if (mode === 'light' || mode === 'dark' || mode === 'custom') {
    return mode;
  }
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return 'dark';
};

// Get the effective color mode for calculations (custom mode needs a base)
const getEffectiveColorMode = (resolvedMode) => {
  if (resolvedMode === 'custom') {
    // For custom mode, use the theme's native mode or fall back to dark
    return uiThemeNativeMode?.value || 'dark';
  }
  return resolvedMode;
};

const getThemeOverrides = () => {
  const overrides = uiThemeOverrides.value;
  return overrides && typeof overrides === 'object' ? overrides : {};
};

const getOverrideValue = (overrides, key) => {
  if (!overrides || typeof overrides !== 'object') {
    return '';
  }
  const value = overrides[key];
  if (value === null || value === undefined) {
    return '';
  }
  return typeof value === 'string' ? value.trim() : String(value);
};

const getOverrideColor = (overrides, key) => {
  const rawValue = getOverrideValue(overrides, key);
  return rawValue ? parseCssColor(rawValue) : null;
};

export const applyTheme = () => {
  if (typeof document === 'undefined') {
    return;
  }
  const mode = uiThemeMode.value || 'system';
  const resolvedMode = resolveThemeMode(mode);
  const root = document.documentElement;

  // Get effective color mode for calculations (custom uses theme's native mode)
  const effectiveMode = getEffectiveColorMode(resolvedMode);

  // Set data-theme for CSS base variables:
  // - 'custom' mode uses the theme's native mode so CSS provides correct base
  //   (surfaces, text, glass, buttons, scrollbars, etc.)
  //   JS-set overrides (sidebar, drawer, nixie, etc.) take priority as inline styles
  // - Other modes use their resolved value directly
  root.dataset.theme = effectiveMode;

  const overrides = getThemeOverrides();
  const accentOverride = getOverrideColor(overrides, '--vera-accent');
  const accent = accentOverride?.hex || normalizeHex(uiAccentColor.value) || DEFAULT_ACCENT_COLOR;
  const accentRgb = accentOverride?.rgb || hexToRgb(accent) || { r: 0, g: 153, b: 255 };
  const strongShift = effectiveMode === 'light' ? -0.12 : 0.12;
  const softAlpha = effectiveMode === 'light' ? 0.18 : 0.2;
  const faintAlpha = effectiveMode === 'light' ? 0.1 : 0.12;

  root.style.setProperty('--vera-accent', accent);
  root.style.setProperty('--vera-accent-strong', adjustColor(accent, strongShift));
  root.style.setProperty('--vera-accent-soft', toRgba(accent, softAlpha));
  root.style.setProperty('--vera-accent-faint', toRgba(accent, faintAlpha));

  // Secondary accent color
  const secondaryOverride = getOverrideColor(overrides, '--vera-secondary');
  const secondaryAccent = secondaryOverride?.hex || normalizeHex(uiSecondaryAccent.value) || '#a78bfa';
  const secondaryRgb = secondaryOverride?.rgb || hexToRgb(secondaryAccent) || { r: 167, g: 139, b: 250 };
  root.style.setProperty('--vera-secondary', secondaryAccent);
  root.style.setProperty('--vera-secondary-soft', toRgba(secondaryAccent, softAlpha));
  root.style.setProperty('--vera-secondary-faint', toRgba(secondaryAccent, faintAlpha));

  // Accent RGB values for use in rgba() - allows components to use opacity variants
  root.style.setProperty('--vera-accent-rgb', `${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}`);
  root.style.setProperty('--vera-secondary-rgb', `${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}`);

  // Accent opacity variants (05 = 5%, 10 = 10%, etc.)
  root.style.setProperty('--vera-accent-05', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.05)`);
  root.style.setProperty('--vera-accent-02', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.02)`);
  root.style.setProperty('--vera-accent-03', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.03)`);
  root.style.setProperty('--vera-accent-04', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.04)`);
  root.style.setProperty('--vera-accent-06', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.06)`);
  root.style.setProperty('--vera-accent-08', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.08)`);
  root.style.setProperty('--vera-accent-10', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.10)`);
  root.style.setProperty('--vera-accent-12', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.12)`);
  root.style.setProperty('--vera-accent-15', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.15)`);
  root.style.setProperty('--vera-accent-18', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.18)`);
  root.style.setProperty('--vera-accent-20', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.20)`);
  root.style.setProperty('--vera-accent-25', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.25)`);
  root.style.setProperty('--vera-accent-30', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.30)`);
  root.style.setProperty('--vera-accent-35', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.35)`);
  root.style.setProperty('--vera-accent-40', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.40)`);
  root.style.setProperty('--vera-accent-45', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.45)`);
  root.style.setProperty('--vera-accent-50', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.50)`);
  root.style.setProperty('--vera-accent-60', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.60)`);
  root.style.setProperty('--vera-accent-70', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.70)`);
  root.style.setProperty('--vera-accent-80', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.80)`);
  root.style.setProperty('--vera-accent-85', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.85)`);
  root.style.setProperty('--vera-accent-90', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.90)`);

  // Secondary accent opacity variants
  root.style.setProperty('--vera-secondary-02', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.02)`);
  root.style.setProperty('--vera-secondary-05', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.05)`);
  root.style.setProperty('--vera-secondary-08', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.08)`);
  root.style.setProperty('--vera-secondary-10', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.10)`);
  root.style.setProperty('--vera-secondary-15', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.15)`);
  root.style.setProperty('--vera-secondary-20', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.20)`);
  root.style.setProperty('--vera-secondary-25', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.25)`);
  root.style.setProperty('--vera-secondary-30', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.30)`);
  root.style.setProperty('--vera-secondary-35', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.35)`);
  root.style.setProperty('--vera-secondary-40', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.40)`);
  root.style.setProperty('--vera-secondary-50', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.50)`);
  root.style.setProperty('--vera-secondary-60', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.60)`);
  root.style.setProperty('--vera-secondary-80', `rgba(${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}, 0.80)`);

  // Terminal colors
  root.style.setProperty('--vera-terminal-bg', uiTerminalBackground.value || DEFAULT_TERMINAL_COLORS.background);
  root.style.setProperty('--vera-terminal-fg', uiTerminalForeground.value || DEFAULT_TERMINAL_COLORS.foreground);
  root.style.setProperty('--vera-terminal-cursor', uiTerminalCursor.value || DEFAULT_TERMINAL_COLORS.cursor);
  root.style.setProperty('--vera-terminal-selection', uiTerminalSelection.value || DEFAULT_TERMINAL_COLORS.selection);
  root.style.setProperty('--vera-terminal-black', uiTerminalBlack.value || DEFAULT_TERMINAL_COLORS.black);
  root.style.setProperty('--vera-terminal-red', uiTerminalRed.value || DEFAULT_TERMINAL_COLORS.red);
  root.style.setProperty('--vera-terminal-green', uiTerminalGreen.value || DEFAULT_TERMINAL_COLORS.green);
  root.style.setProperty('--vera-terminal-yellow', uiTerminalYellow.value || DEFAULT_TERMINAL_COLORS.yellow);
  root.style.setProperty('--vera-terminal-blue', uiTerminalBlue.value || DEFAULT_TERMINAL_COLORS.blue);
  root.style.setProperty('--vera-terminal-magenta', uiTerminalMagenta.value || DEFAULT_TERMINAL_COLORS.magenta);
  root.style.setProperty('--vera-terminal-cyan', uiTerminalCyan.value || DEFAULT_TERMINAL_COLORS.cyan);
  root.style.setProperty('--vera-terminal-white', uiTerminalWhite.value || DEFAULT_TERMINAL_COLORS.white);

  // Status colors
  const successOverride = getOverrideColor(overrides, '--vera-success') || getOverrideColor(overrides, '--vera-status-success');
  const warningOverride = getOverrideColor(overrides, '--vera-warning') || getOverrideColor(overrides, '--vera-status-warning');
  const errorOverride = getOverrideColor(overrides, '--vera-danger') || getOverrideColor(overrides, '--vera-status-error');
  const infoOverride = getOverrideColor(overrides, '--vera-info') || getOverrideColor(overrides, '--vera-status-info');
  const statusSuccess = successOverride?.hex || normalizeHex(uiStatusSuccess.value) || DEFAULT_STATUS_COLORS.success;
  const statusWarning = warningOverride?.hex || normalizeHex(uiStatusWarning.value) || DEFAULT_STATUS_COLORS.warning;
  const statusError = errorOverride?.hex || normalizeHex(uiStatusError.value) || DEFAULT_STATUS_COLORS.error;
  const statusInfo = infoOverride?.hex || normalizeHex(uiStatusInfo.value) || DEFAULT_STATUS_COLORS.info;
  const successRgb = successOverride?.rgb || hexToRgb(statusSuccess) || hexToRgb(DEFAULT_STATUS_COLORS.success) || { r: 74, g: 222, b: 128 };
  const warningRgb = warningOverride?.rgb || hexToRgb(statusWarning) || hexToRgb(DEFAULT_STATUS_COLORS.warning) || { r: 251, g: 191, b: 36 };
  const errorRgb = errorOverride?.rgb || hexToRgb(statusError) || hexToRgb(DEFAULT_STATUS_COLORS.error) || { r: 255, g: 107, b: 107 };
  const infoRgb = infoOverride?.rgb || hexToRgb(statusInfo) || hexToRgb(DEFAULT_STATUS_COLORS.info) || { r: 96, g: 165, b: 250 };

  root.style.setProperty('--vera-status-success', statusSuccess);
  root.style.setProperty('--vera-status-warning', statusWarning);
  root.style.setProperty('--vera-status-error', statusError);
  root.style.setProperty('--vera-status-info', statusInfo);
  root.style.setProperty('--vera-success', statusSuccess);
  root.style.setProperty('--vera-warning', statusWarning);
  root.style.setProperty('--vera-danger', statusError);
  root.style.setProperty('--vera-info', statusInfo);

  // Status color RGB values for use in rgba()
  root.style.setProperty('--vera-success-rgb', `${successRgb.r}, ${successRgb.g}, ${successRgb.b}`);
  root.style.setProperty('--vera-warning-rgb', `${warningRgb.r}, ${warningRgb.g}, ${warningRgb.b}`);
  root.style.setProperty('--vera-error-rgb', `${errorRgb.r}, ${errorRgb.g}, ${errorRgb.b}`);
  root.style.setProperty('--vera-info-rgb', `${infoRgb.r}, ${infoRgb.g}, ${infoRgb.b}`);

  // Status color opacity variants
  root.style.setProperty('--vera-success-05', `rgba(${successRgb.r}, ${successRgb.g}, ${successRgb.b}, 0.05)`);
  root.style.setProperty('--vera-success-10', `rgba(${successRgb.r}, ${successRgb.g}, ${successRgb.b}, 0.10)`);
  root.style.setProperty('--vera-success-15', `rgba(${successRgb.r}, ${successRgb.g}, ${successRgb.b}, 0.15)`);
  root.style.setProperty('--vera-success-20', `rgba(${successRgb.r}, ${successRgb.g}, ${successRgb.b}, 0.20)`);
  root.style.setProperty('--vera-success-30', `rgba(${successRgb.r}, ${successRgb.g}, ${successRgb.b}, 0.30)`);
  root.style.setProperty('--vera-success-40', `rgba(${successRgb.r}, ${successRgb.g}, ${successRgb.b}, 0.40)`);
  root.style.setProperty('--vera-success-50', `rgba(${successRgb.r}, ${successRgb.g}, ${successRgb.b}, 0.50)`);
  root.style.setProperty('--vera-success-60', `rgba(${successRgb.r}, ${successRgb.g}, ${successRgb.b}, 0.60)`);

  root.style.setProperty('--vera-warning-05', `rgba(${warningRgb.r}, ${warningRgb.g}, ${warningRgb.b}, 0.05)`);
  root.style.setProperty('--vera-warning-10', `rgba(${warningRgb.r}, ${warningRgb.g}, ${warningRgb.b}, 0.10)`);
  root.style.setProperty('--vera-warning-15', `rgba(${warningRgb.r}, ${warningRgb.g}, ${warningRgb.b}, 0.15)`);
  root.style.setProperty('--vera-warning-20', `rgba(${warningRgb.r}, ${warningRgb.g}, ${warningRgb.b}, 0.20)`);
  root.style.setProperty('--vera-warning-30', `rgba(${warningRgb.r}, ${warningRgb.g}, ${warningRgb.b}, 0.30)`);
  root.style.setProperty('--vera-warning-40', `rgba(${warningRgb.r}, ${warningRgb.g}, ${warningRgb.b}, 0.40)`);
  root.style.setProperty('--vera-warning-50', `rgba(${warningRgb.r}, ${warningRgb.g}, ${warningRgb.b}, 0.50)`);
  root.style.setProperty('--vera-warning-60', `rgba(${warningRgb.r}, ${warningRgb.g}, ${warningRgb.b}, 0.60)`);

  root.style.setProperty('--vera-error-05', `rgba(${errorRgb.r}, ${errorRgb.g}, ${errorRgb.b}, 0.05)`);
  root.style.setProperty('--vera-error-10', `rgba(${errorRgb.r}, ${errorRgb.g}, ${errorRgb.b}, 0.10)`);
  root.style.setProperty('--vera-error-15', `rgba(${errorRgb.r}, ${errorRgb.g}, ${errorRgb.b}, 0.15)`);
  root.style.setProperty('--vera-error-20', `rgba(${errorRgb.r}, ${errorRgb.g}, ${errorRgb.b}, 0.20)`);
  root.style.setProperty('--vera-error-30', `rgba(${errorRgb.r}, ${errorRgb.g}, ${errorRgb.b}, 0.30)`);
  root.style.setProperty('--vera-error-40', `rgba(${errorRgb.r}, ${errorRgb.g}, ${errorRgb.b}, 0.40)`);
  root.style.setProperty('--vera-error-50', `rgba(${errorRgb.r}, ${errorRgb.g}, ${errorRgb.b}, 0.50)`);
  root.style.setProperty('--vera-error-60', `rgba(${errorRgb.r}, ${errorRgb.g}, ${errorRgb.b}, 0.60)`);

  root.style.setProperty('--vera-info-05', `rgba(${infoRgb.r}, ${infoRgb.g}, ${infoRgb.b}, 0.05)`);
  root.style.setProperty('--vera-info-10', `rgba(${infoRgb.r}, ${infoRgb.g}, ${infoRgb.b}, 0.10)`);
  root.style.setProperty('--vera-info-15', `rgba(${infoRgb.r}, ${infoRgb.g}, ${infoRgb.b}, 0.15)`);
  root.style.setProperty('--vera-info-20', `rgba(${infoRgb.r}, ${infoRgb.g}, ${infoRgb.b}, 0.20)`);
  root.style.setProperty('--vera-info-30', `rgba(${infoRgb.r}, ${infoRgb.g}, ${infoRgb.b}, 0.30)`);
  root.style.setProperty('--vera-info-40', `rgba(${infoRgb.r}, ${infoRgb.g}, ${infoRgb.b}, 0.40)`);
  root.style.setProperty('--vera-info-50', `rgba(${infoRgb.r}, ${infoRgb.g}, ${infoRgb.b}, 0.50)`);
  root.style.setProperty('--vera-info-60', `rgba(${infoRgb.r}, ${infoRgb.g}, ${infoRgb.b}, 0.60)`);

  // Shadow variables (themed black shadows for consistency)
  const computedShadow = typeof window !== 'undefined'
    ? getComputedStyle(root).getPropertyValue('--vera-shadow')
    : '';
  const computedShadowRgb = typeof window !== 'undefined'
    ? getComputedStyle(root).getPropertyValue('--vera-shadow-rgb')
    : '';
  const shadowRgbOverrideValue = getOverrideValue(overrides, '--vera-shadow-rgb');
  const shadowRgbOverride = parseRgbChannels(shadowRgbOverrideValue) || parseCssColor(shadowRgbOverrideValue)?.rgb;
  const shadowOverride = getOverrideColor(overrides, '--vera-shadow');
  const shadowRgb = shadowRgbOverride
    || shadowOverride?.rgb
    || parseRgbChannels(computedShadowRgb)
    || parseCssColor(computedShadow)?.rgb
    || { r: 0, g: 0, b: 0 };
  const shadowBase = `${shadowRgb.r}, ${shadowRgb.g}, ${shadowRgb.b}`;
  root.style.setProperty('--vera-shadow-rgb', shadowBase);
  root.style.setProperty('--vera-shadow-color', shadowBase);
  root.style.setProperty('--vera-shadow-xs', `0 1px 2px rgba(${shadowBase}, 0.1)`);
  root.style.setProperty('--vera-shadow-sm', `0 2px 4px rgba(${shadowBase}, 0.15)`);
  root.style.setProperty('--vera-shadow-md', `0 4px 8px rgba(${shadowBase}, 0.2)`);
  root.style.setProperty('--vera-shadow-lg', `0 8px 16px rgba(${shadowBase}, 0.25)`);
  root.style.setProperty('--vera-shadow-xl', `0 12px 24px rgba(${shadowBase}, 0.3)`);
  root.style.setProperty('--vera-shadow-2xl', `0 16px 32px rgba(${shadowBase}, 0.35)`);
  root.style.setProperty('--vera-shadow-3xl', `0 20px 40px rgba(${shadowBase}, 0.4)`);
  root.style.setProperty('--vera-shadow-inner', `inset 0 2px 4px rgba(${shadowBase}, 0.15)`);

  // White overlay/gradient colors for glass effects
  root.style.setProperty('--vera-white-05', 'rgba(255, 255, 255, 0.05)');
  root.style.setProperty('--vera-white-03', 'rgba(255, 255, 255, 0.03)');
  root.style.setProperty('--vera-white-08', 'rgba(255, 255, 255, 0.08)');
  root.style.setProperty('--vera-white-10', 'rgba(255, 255, 255, 0.10)');
  root.style.setProperty('--vera-white-15', 'rgba(255, 255, 255, 0.15)');
  root.style.setProperty('--vera-white-20', 'rgba(255, 255, 255, 0.20)');
  root.style.setProperty('--vera-white-30', 'rgba(255, 255, 255, 0.30)');
  root.style.setProperty('--vera-white-60', 'rgba(255, 255, 255, 0.60)');
  root.style.setProperty('--vera-white-95', 'rgba(255, 255, 255, 0.95)');
  root.style.setProperty('--vera-white-98', 'rgba(255, 255, 255, 0.98)');
  root.style.setProperty('--vera-black-05', 'rgba(0, 0, 0, 0.05)');
  root.style.setProperty('--vera-black-10', 'rgba(0, 0, 0, 0.10)');
  root.style.setProperty('--vera-black-15', 'rgba(0, 0, 0, 0.15)');
  root.style.setProperty('--vera-black-20', 'rgba(0, 0, 0, 0.20)');
  root.style.setProperty('--vera-black-30', 'rgba(0, 0, 0, 0.30)');
  root.style.setProperty('--vera-black-40', 'rgba(0, 0, 0, 0.40)');
  root.style.setProperty('--vera-black-50', 'rgba(0, 0, 0, 0.50)');
  root.style.setProperty('--vera-black-60', 'rgba(0, 0, 0, 0.60)');
  root.style.setProperty('--vera-black-70', 'rgba(0, 0, 0, 0.70)');
  root.style.setProperty('--vera-black-80', 'rgba(0, 0, 0, 0.80)');
  root.style.setProperty('--vera-black-90', 'rgba(0, 0, 0, 0.90)');
  root.style.setProperty('--vera-black-95', 'rgba(0, 0, 0, 0.95)');

  // Event type colors
  root.style.setProperty('--vera-event-routing', uiEventRouting.value || DEFAULT_EVENT_COLORS.routing);
  root.style.setProperty('--vera-event-memory', uiEventMemory.value || DEFAULT_EVENT_COLORS.memory);
  root.style.setProperty('--vera-event-tool', uiEventTool.value || DEFAULT_EVENT_COLORS.tool);
  root.style.setProperty('--vera-event-decision', uiEventDecision.value || DEFAULT_EVENT_COLORS.decision);
  root.style.setProperty('--vera-event-quorum', uiEventQuorum.value || DEFAULT_EVENT_COLORS.quorum);

  // Git status colors
  root.style.setProperty('--vera-git-added', uiGitAdded.value || DEFAULT_GIT_COLORS.added);
  root.style.setProperty('--vera-git-modified', uiGitModified.value || DEFAULT_GIT_COLORS.modified);
  root.style.setProperty('--vera-git-deleted', uiGitDeleted.value || DEFAULT_GIT_COLORS.deleted);
  root.style.setProperty('--vera-git-untracked', uiGitUntracked.value || DEFAULT_GIT_COLORS.untracked);

  const presetKey = uiThemePreset.value || DEFAULT_THEME_PRESET;
  const preset = THEME_PRESETS[presetKey] || THEME_PRESETS[DEFAULT_THEME_PRESET];
  const presetVars = preset?.modes?.[effectiveMode] || {};
  PRESET_KEYS.forEach((key) => {
    root.style.removeProperty(key);
  });
  Object.entries(presetVars).forEach(([key, value]) => {
    root.style.setProperty(key, value);
  });

  const bgMode = uiBackgroundMode.value || 'preset';
  const bgPresetKey = uiBackgroundPreset.value || DEFAULT_BACKGROUND_PRESET;
  const bgPreset = BACKGROUND_PRESETS[bgPresetKey] || BACKGROUND_PRESETS[DEFAULT_BACKGROUND_PRESET];
  let appBgValue = bgPreset.value;

  if (bgMode === 'color') {
    appBgValue = uiBackgroundColor.value || '#0b0f14';
  } else if (bgMode === 'gradient') {
    const angle = Number.isFinite(uiBackgroundGradientAngle.value)
      ? uiBackgroundGradientAngle.value
      : 135;
    const start = uiBackgroundGradientStart.value || '#0b0f14';
    const end = uiBackgroundGradientEnd.value || '#121a26';
    appBgValue = `linear-gradient(${angle}deg, ${start}, ${end})`;
  } else if (bgMode === 'preset') {
    appBgValue = bgPreset.value;
  }
  root.style.setProperty('--vera-app-bg', appBgValue);

  if (bgMode === 'image' && uiBackgroundImage.value) {
    root.style.setProperty('--vera-bg-image', `url("${uiBackgroundImage.value}")`);
  } else {
    root.style.setProperty('--vera-bg-image', 'none');
  }

  root.style.setProperty('--vera-bg-image-opacity', String(uiBackgroundImageOpacity.value ?? 0.35));
  root.style.setProperty('--vera-bg-image-blur', `${uiBackgroundImageBlur.value ?? 8}px`);

  const sidebarMode = uiSidebarBackgroundMode.value || 'glass';
  const sidebarPresetKey = uiSidebarBackgroundPreset.value || DEFAULT_SIDEBAR_BACKGROUND_PRESET;
  const sidebarPreset = BACKGROUND_PRESETS[sidebarPresetKey] || BACKGROUND_PRESETS[DEFAULT_SIDEBAR_BACKGROUND_PRESET];

  if (sidebarMode === 'inherit') {
    root.style.setProperty('--vera-sidebar-bg', 'var(--vera-app-bg)');
  } else if (sidebarMode === 'color') {
    root.style.setProperty('--vera-sidebar-bg', uiSidebarBackgroundColor.value || '#101826');
  } else if (sidebarMode === 'gradient') {
    const angle = Number.isFinite(uiSidebarBackgroundGradientAngle.value)
      ? uiSidebarBackgroundGradientAngle.value
      : 135;
    const start = uiSidebarBackgroundGradientStart.value || '#0f1724';
    const end = uiSidebarBackgroundGradientEnd.value || '#182230';
    root.style.setProperty('--vera-sidebar-bg', `linear-gradient(${angle}deg, ${start}, ${end})`);
  } else if (sidebarMode === 'preset') {
    root.style.setProperty('--vera-sidebar-bg', sidebarPreset.value);
  } else {
    root.style.setProperty('--vera-sidebar-bg', 'var(--vera-glass-strong)');
  }

  if (sidebarMode === 'image' && uiSidebarBackgroundImage.value) {
    const overlay = Math.max(0, 1 - (uiSidebarBackgroundImageOpacity.value ?? 0.25));
    root.style.setProperty(
      '--vera-sidebar-image',
      `linear-gradient(rgba(0, 0, 0, ${overlay}), rgba(0, 0, 0, ${overlay})), url("${uiSidebarBackgroundImage.value}")`
    );
  } else {
    root.style.setProperty('--vera-sidebar-image', 'none');
  }
  root.style.setProperty('--vera-sidebar-image-opacity', String(uiSidebarBackgroundImageOpacity.value ?? 0.25));
  root.style.setProperty('--vera-sidebar-image-blur', `${uiSidebarBackgroundImageBlur.value ?? 6}px`);

  // Independent background mode - apply separate backgrounds for each area
  const isIndependent = uiBackgroundIndependent.value;

  // Left sidebar independent background
  if (isIndependent && uiLeftSidebarBackgroundImage.value) {
    const overlay = Math.max(0, 1 - (uiLeftSidebarBackgroundImageOpacity.value ?? 0.25));
    root.style.setProperty(
      '--vera-left-sidebar-image',
      `linear-gradient(rgba(0, 0, 0, ${overlay}), rgba(0, 0, 0, ${overlay})), url("${uiLeftSidebarBackgroundImage.value}")`
    );
  } else {
    root.style.setProperty('--vera-left-sidebar-image', 'var(--vera-sidebar-image)');
  }
  root.style.setProperty('--vera-left-sidebar-image-opacity', String(isIndependent ? (uiLeftSidebarBackgroundImageOpacity.value ?? 0.25) : (uiSidebarBackgroundImageOpacity.value ?? 0.25)));
  root.style.setProperty('--vera-left-sidebar-image-blur', `${isIndependent ? (uiLeftSidebarBackgroundImageBlur.value ?? 6) : (uiSidebarBackgroundImageBlur.value ?? 6)}px`);

  // Right sidebar independent background
  if (isIndependent && uiRightSidebarBackgroundImage.value) {
    const overlay = Math.max(0, 1 - (uiRightSidebarBackgroundImageOpacity.value ?? 0.25));
    root.style.setProperty(
      '--vera-right-sidebar-image',
      `linear-gradient(rgba(0, 0, 0, ${overlay}), rgba(0, 0, 0, ${overlay})), url("${uiRightSidebarBackgroundImage.value}")`
    );
  } else {
    root.style.setProperty('--vera-right-sidebar-image', 'var(--vera-sidebar-image)');
  }
  root.style.setProperty('--vera-right-sidebar-image-opacity', String(isIndependent ? (uiRightSidebarBackgroundImageOpacity.value ?? 0.25) : (uiSidebarBackgroundImageOpacity.value ?? 0.25)));
  root.style.setProperty('--vera-right-sidebar-image-blur', `${isIndependent ? (uiRightSidebarBackgroundImageBlur.value ?? 6) : (uiSidebarBackgroundImageBlur.value ?? 6)}px`);

  // Header background with mode support
  const headerMode = uiHeaderBackgroundMode.value || 'transparent';
  const headerPresetKey = uiHeaderBackgroundPreset.value || 'deep-space';
  const headerPreset = BACKGROUND_PRESETS[headerPresetKey] || BACKGROUND_PRESETS['deep-space'];
  let headerBg;
  if (headerMode === 'transparent') {
    headerBg = 'transparent';
  } else if (headerMode === 'glass') {
    headerBg = 'var(--vera-glass-bg)';
  } else if (headerMode === 'glass-strong') {
    headerBg = 'var(--vera-glass-strong)';
  } else if (headerMode === 'preset') {
    headerBg = headerPreset.value;
  } else if (headerMode === 'solid') {
    headerBg = uiHeaderBackgroundColor.value || '#101826';
  } else if (headerMode === 'image') {
    headerBg = 'transparent';
  } else {
    headerBg = 'transparent';
  }
  root.style.setProperty('--vera-header-bg', headerBg);

  // Header image (used when mode is 'image' or independent backgrounds are on)
  if ((headerMode === 'image' || isIndependent) && uiHeaderBackgroundImage.value) {
    const overlay = Math.max(0, 1 - (uiHeaderBackgroundImageOpacity.value ?? 0.25));
    root.style.setProperty(
      '--vera-header-image',
      `linear-gradient(rgba(0, 0, 0, ${overlay}), rgba(0, 0, 0, ${overlay})), url("${uiHeaderBackgroundImage.value}")`
    );
  } else {
    root.style.setProperty('--vera-header-image', 'none');
  }
  root.style.setProperty('--vera-header-image-opacity', String(uiHeaderBackgroundImageOpacity.value ?? 0.25));
  root.style.setProperty('--vera-header-image-blur', `${uiHeaderBackgroundImageBlur.value ?? 6}px`);

  // Chat area independent background
  if (isIndependent && uiChatBackgroundImage.value) {
    const overlay = Math.max(0, 1 - (uiChatBackgroundImageOpacity.value ?? 0.25));
    root.style.setProperty(
      '--vera-chat-image',
      `linear-gradient(rgba(0, 0, 0, ${overlay}), rgba(0, 0, 0, ${overlay})), url("${uiChatBackgroundImage.value}")`
    );
  } else {
    root.style.setProperty('--vera-chat-image', 'none');
  }
  root.style.setProperty('--vera-chat-image-opacity', String(uiChatBackgroundImageOpacity.value ?? 0.25));
  root.style.setProperty('--vera-chat-image-blur', `${uiChatBackgroundImageBlur.value ?? 6}px`);

  // Input bar background with mode support
  const inputBarMode = uiInputBarBackgroundMode.value || 'glass';
  const inputBarPresetKey = uiInputBarBackgroundPreset.value || 'deep-space';
  const inputBarPreset = BACKGROUND_PRESETS[inputBarPresetKey] || BACKGROUND_PRESETS['deep-space'];
  let inputBarBg;
  if (inputBarMode === 'transparent') {
    inputBarBg = 'transparent';
  } else if (inputBarMode === 'glass') {
    inputBarBg = 'var(--vera-glass-bg)';
  } else if (inputBarMode === 'glass-strong') {
    inputBarBg = 'var(--vera-glass-strong)';
  } else if (inputBarMode === 'preset') {
    inputBarBg = inputBarPreset.value;
  } else if (inputBarMode === 'solid') {
    inputBarBg = uiInputBarBackgroundColor.value || '#0c1420';
  } else if (inputBarMode === 'custom') {
    inputBarBg = colorWithOpacity(
      uiInputBarBackgroundColor.value,
      uiInputBarBackgroundOpacity.value ?? 0.12,
      'var(--vera-glass-bg)'
    );
  } else {
    inputBarBg = 'var(--vera-glass-bg)';
  }
  const inputBarBorder = colorWithOpacity(
    uiInputBarBorderColor.value,
    uiInputBarBorderOpacity.value ?? 0.2,
    'var(--vera-glass-border)'
  );
  root.style.setProperty('--vera-input-bar-bg', inputBarBg);
  root.style.setProperty('--vera-input-bar-border', inputBarBorder);
  const inputGlowStrength = clamp(uiInputBarGlow.value ?? 0.25, 0, 1);
  root.style.setProperty(
    '--vera-input-bar-glow',
    `0 0 16px rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, ${inputGlowStrength})`
  );

  // Tool card background with mode support
  const toolCardMode = uiToolCardBackgroundMode.value || 'glass';
  const toolCardPresetKey = uiToolCardBackgroundPreset.value || 'deep-space';
  const toolCardPreset = BACKGROUND_PRESETS[toolCardPresetKey] || BACKGROUND_PRESETS['deep-space'];
  let toolCardBg;
  if (toolCardMode === 'transparent') {
    toolCardBg = 'transparent';
  } else if (toolCardMode === 'glass') {
    toolCardBg = 'var(--vera-glass-bg)';
  } else if (toolCardMode === 'glass-strong') {
    toolCardBg = 'var(--vera-glass-strong)';
  } else if (toolCardMode === 'preset') {
    toolCardBg = toolCardPreset.value;
  } else if (toolCardMode === 'solid') {
    toolCardBg = uiToolCardBackgroundColor.value || '#0c1420';
  } else if (toolCardMode === 'custom') {
    toolCardBg = colorWithOpacity(
      uiToolCardBackgroundColor.value,
      uiToolCardBackgroundOpacity.value ?? 0.12,
      'var(--vera-glass-bg)'
    );
  } else {
    toolCardBg = 'var(--vera-glass-bg)';
  }
  const toolCardBorder = colorWithOpacity(
    uiToolCardBorderColor.value,
    uiToolCardBorderOpacity.value ?? 0.2,
    'var(--vera-glass-border)'
  );
  root.style.setProperty('--vera-tool-card-bg', toolCardBg);
  root.style.setProperty('--vera-tool-card-border', toolCardBorder);
  const toolGlowStrength = clamp(uiToolCardGlow.value ?? 0.25, 0, 1);
  root.style.setProperty(
    '--vera-tool-card-glow',
    `0 0 16px rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, ${toolGlowStrength})`
  );

  // User message background with mode support
  const userMessageMode = uiUserMessageBackgroundMode.value || 'glass';
  const userMessagePresetKey = uiUserMessageBackgroundPreset.value || 'deep-space';
  const userMessagePreset = BACKGROUND_PRESETS[userMessagePresetKey] || BACKGROUND_PRESETS['deep-space'];
  let userMessageBg;
  if (userMessageMode === 'transparent') {
    userMessageBg = 'transparent';
  } else if (userMessageMode === 'glass') {
    userMessageBg = 'var(--vera-glass-bg)';
  } else if (userMessageMode === 'glass-strong') {
    userMessageBg = 'var(--vera-glass-strong)';
  } else if (userMessageMode === 'preset') {
    userMessageBg = userMessagePreset.value;
  } else if (userMessageMode === 'solid') {
    userMessageBg = uiUserMessageBackgroundColor.value || '#0e1e34';
  } else if (userMessageMode === 'custom') {
    userMessageBg = colorWithOpacity(
      uiUserMessageBackgroundColor.value,
      uiUserMessageBackgroundOpacity.value ?? 0.88,
      'rgba(14, 30, 52, 0.88)'
    );
  } else {
    userMessageBg = 'var(--vera-glass-bg)';
  }
  const userMessageBorder = colorWithOpacity(
    uiUserMessageBorderColor.value,
    uiUserMessageBorderOpacity.value ?? 0.2,
    'rgba(0, 153, 255, 0.2)'
  );
  root.style.setProperty('--vera-message-user-bg', userMessageBg);
  root.style.setProperty('--vera-message-user-border', userMessageBorder);

  // Assistant message background with mode support
  const assistantMessageMode = uiAssistantMessageBackgroundMode.value || 'glass';
  const assistantMessagePresetKey = uiAssistantMessageBackgroundPreset.value || 'steel-veil';
  const assistantMessagePreset = BACKGROUND_PRESETS[assistantMessagePresetKey] || BACKGROUND_PRESETS['steel-veil'];
  let assistantMessageBg;
  if (assistantMessageMode === 'transparent') {
    assistantMessageBg = 'transparent';
  } else if (assistantMessageMode === 'glass') {
    assistantMessageBg = 'var(--vera-glass-bg)';
  } else if (assistantMessageMode === 'glass-strong') {
    assistantMessageBg = 'var(--vera-glass-strong)';
  } else if (assistantMessageMode === 'preset') {
    assistantMessageBg = assistantMessagePreset.value;
  } else if (assistantMessageMode === 'solid') {
    assistantMessageBg = uiAssistantMessageBackgroundColor.value || '#0c121c';
  } else if (assistantMessageMode === 'custom') {
    assistantMessageBg = colorWithOpacity(
      uiAssistantMessageBackgroundColor.value,
      uiAssistantMessageBackgroundOpacity.value ?? 0.92,
      'rgba(12, 18, 28, 0.92)'
    );
  } else {
    assistantMessageBg = 'var(--vera-glass-bg)';
  }
  const assistantMessageBorder = colorWithOpacity(
    uiAssistantMessageBorderColor.value,
    uiAssistantMessageBorderOpacity.value ?? 0.14,
    'rgba(120, 170, 255, 0.14)'
  );
  root.style.setProperty('--vera-message-assistant-bg', assistantMessageBg);
  root.style.setProperty('--vera-message-assistant-border', assistantMessageBorder);

  // Send button theming
  if (uiSendButtonBackgroundColor.value) {
    root.style.setProperty('--vera-send-button-bg', uiSendButtonBackgroundColor.value);
  } else {
    root.style.removeProperty('--vera-send-button-bg');
  }
  if (uiSendButtonTextColor.value) {
    root.style.setProperty('--vera-send-button-text', uiSendButtonTextColor.value);
  } else {
    root.style.removeProperty('--vera-send-button-text');
  }
  const sendButtonGlow = clamp(uiSendButtonGlow.value ?? 0, 0, 1);
  if (sendButtonGlow > 0) {
    root.style.setProperty(
      '--vera-send-button-glow',
      `0 0 16px rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, ${sendButtonGlow})`
    );
  } else {
    root.style.removeProperty('--vera-send-button-glow');
  }

  // Button theming (rail buttons, action buttons, sidebar buttons)
  const btnMode = uiButtonBackgroundMode.value ?? 'glass';
  const btnPresetKey = uiButtonBackgroundPreset.value || 'deep-space';
  const btnPreset = BACKGROUND_PRESETS[btnPresetKey] || BACKGROUND_PRESETS['deep-space'];
  const btnColor = normalizeHex(uiButtonBackgroundColor.value) || '#0c1420';
  const btnColorRgb = hexToRgb(btnColor);
  const btnOpacity = clamp(uiButtonBackgroundOpacity.value ?? 0.6, 0, 1);
  const btnBorderColor = normalizeHex(uiButtonBorderColor.value) || '#78aaff';
  const btnBorderColorRgb = hexToRgb(btnBorderColor);
  const btnBorderOpacity = clamp(uiButtonBorderOpacity.value ?? 0.2, 0, 1);
  const btnGlowVal = clamp(uiButtonGlow.value ?? 0.25, 0, 1);

  let btnBg;
  if (btnMode === 'preset') {
    btnBg = btnPreset.value;
  } else if (btnMode === 'glass') {
    btnBg = `rgba(${btnColorRgb.r}, ${btnColorRgb.g}, ${btnColorRgb.b}, ${btnOpacity * 0.5})`;
  } else if (btnMode === 'glass-strong') {
    btnBg = `rgba(${btnColorRgb.r}, ${btnColorRgb.g}, ${btnColorRgb.b}, ${btnOpacity * 0.8})`;
  } else if (btnMode === 'solid') {
    btnBg = btnColor;
  } else {
    btnBg = `rgba(${btnColorRgb.r}, ${btnColorRgb.g}, ${btnColorRgb.b}, ${btnOpacity})`;
  }
  const btnBorder = `rgba(${btnBorderColorRgb.r}, ${btnBorderColorRgb.g}, ${btnBorderColorRgb.b}, ${btnBorderOpacity})`;
  const btnGlow = btnGlowVal > 0 ? `0 0 12px rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, ${btnGlowVal})` : 'none';

  root.style.setProperty('--vera-btn-bg', btnBg);
  root.style.setProperty('--vera-btn-border', btnBorder);
  root.style.setProperty('--vera-btn-glow', btnGlow);
  root.style.setProperty('--vera-rail-btn-bg', btnBg);
  root.style.setProperty('--vera-action-btn-bg', btnBg);
  root.style.setProperty('--vera-sidebar-btn-bg', btnBg);

  // Stop button theming
  if (uiStopButtonBackgroundColor.value) {
    root.style.setProperty('--vera-stop-btn-bg', uiStopButtonBackgroundColor.value);
  } else {
    root.style.removeProperty('--vera-stop-btn-bg');
  }

  // Thinking dropdown theming - header (idle/collapsed state)
  const thinkingHeaderMode = uiThinkingHeaderBackgroundMode.value ?? 'glass';
  const thinkingHeaderPresetKey = uiThinkingHeaderBackgroundPreset.value || 'steel-veil';
  const thinkingHeaderPreset = BACKGROUND_PRESETS[thinkingHeaderPresetKey] || BACKGROUND_PRESETS['steel-veil'];
  const thinkingHeaderColor = normalizeHex(uiThinkingHeaderBackgroundColor.value) || DEFAULT_THINKING_DROPDOWN_THEME.headerBackgroundColor;
  const thinkingHeaderColorRgb = hexToRgb(thinkingHeaderColor);
  const thinkingHeaderOpacity = clamp(
    uiThinkingHeaderBackgroundOpacity.value ?? DEFAULT_THINKING_DROPDOWN_THEME.headerBackgroundOpacity,
    0,
    1
  );
  const thinkingHeaderBorderColor = normalizeHex(uiThinkingHeaderBorderColor.value) || DEFAULT_THINKING_DROPDOWN_THEME.headerBorderColor;
  const thinkingHeaderBorderRgb = hexToRgb(thinkingHeaderBorderColor);
  const thinkingHeaderBorderOpacity = clamp(
    uiThinkingHeaderBorderOpacity.value ?? DEFAULT_THINKING_DROPDOWN_THEME.headerBorderOpacity,
    0,
    1
  );

  let thinkingHeaderBg;
  if (thinkingHeaderMode === 'preset') {
    thinkingHeaderBg = thinkingHeaderPreset.value;
  } else if (thinkingHeaderMode === 'glass') {
    thinkingHeaderBg = `rgba(${thinkingHeaderColorRgb.r}, ${thinkingHeaderColorRgb.g}, ${thinkingHeaderColorRgb.b}, ${thinkingHeaderOpacity * 0.5})`;
  } else if (thinkingHeaderMode === 'glass-strong') {
    thinkingHeaderBg = `rgba(${thinkingHeaderColorRgb.r}, ${thinkingHeaderColorRgb.g}, ${thinkingHeaderColorRgb.b}, ${thinkingHeaderOpacity * 0.8})`;
  } else if (thinkingHeaderMode === 'solid') {
    thinkingHeaderBg = thinkingHeaderColor;
  } else {
    thinkingHeaderBg = `rgba(${thinkingHeaderColorRgb.r}, ${thinkingHeaderColorRgb.g}, ${thinkingHeaderColorRgb.b}, ${thinkingHeaderOpacity})`;
  }
  const thinkingHeaderBorder = `rgba(${thinkingHeaderBorderRgb.r}, ${thinkingHeaderBorderRgb.g}, ${thinkingHeaderBorderRgb.b}, ${thinkingHeaderBorderOpacity})`;

  root.style.setProperty('--vera-thinking-header-bg', thinkingHeaderBg);
  root.style.setProperty('--vera-thinking-header-border', thinkingHeaderBorder);

  // Thinking dropdown theming - content (expanded dropdown)
  const thinkingContentMode = uiThinkingContentBackgroundMode.value ?? 'glass';
  const thinkingContentPresetKey = uiThinkingContentBackgroundPreset.value || 'deep-space';
  const thinkingContentPreset = BACKGROUND_PRESETS[thinkingContentPresetKey] || BACKGROUND_PRESETS['deep-space'];
  const thinkingContentColor = normalizeHex(uiThinkingContentBackgroundColor.value) || DEFAULT_THINKING_DROPDOWN_THEME.contentBackgroundColor;
  const thinkingContentColorRgb = hexToRgb(thinkingContentColor);
  const thinkingContentOpacity = clamp(
    uiThinkingContentBackgroundOpacity.value ?? DEFAULT_THINKING_DROPDOWN_THEME.contentBackgroundOpacity,
    0,
    1
  );

  let thinkingContentBg;
  if (thinkingContentMode === 'preset') {
    thinkingContentBg = thinkingContentPreset.value;
  } else if (thinkingContentMode === 'glass') {
    thinkingContentBg = `rgba(${thinkingContentColorRgb.r}, ${thinkingContentColorRgb.g}, ${thinkingContentColorRgb.b}, ${thinkingContentOpacity * 0.5})`;
  } else if (thinkingContentMode === 'glass-strong') {
    thinkingContentBg = `rgba(${thinkingContentColorRgb.r}, ${thinkingContentColorRgb.g}, ${thinkingContentColorRgb.b}, ${thinkingContentOpacity * 0.8})`;
  } else if (thinkingContentMode === 'solid') {
    thinkingContentBg = thinkingContentColor;
  } else {
    thinkingContentBg = `rgba(${thinkingContentColorRgb.r}, ${thinkingContentColorRgb.g}, ${thinkingContentColorRgb.b}, ${thinkingContentOpacity})`;
  }

  root.style.setProperty('--vera-thinking-content-bg', thinkingContentBg);

  // Thinking dropdown event colors
  root.style.setProperty('--vera-event-routing', uiEventColorRouting.value || DEFAULT_EVENT_COLORS.routing);
  root.style.setProperty('--vera-event-memory', uiEventColorMemory.value || DEFAULT_EVENT_COLORS.memory);
  root.style.setProperty('--vera-event-tool', uiEventColorTool.value || DEFAULT_EVENT_COLORS.tool);
  root.style.setProperty('--vera-event-decision', uiEventColorDecision.value || DEFAULT_EVENT_COLORS.decision);
  root.style.setProperty('--vera-event-quorum', uiEventColorQuorum.value || DEFAULT_EVENT_COLORS.quorum);
  root.style.setProperty('--vera-event-error', uiEventColorError.value || DEFAULT_EVENT_COLORS.error);

  // Voice mode colors
  const voiceListeningColor = normalizeHex(uiVoiceListeningColor.value) || DEFAULT_VOICE_COLORS.listening;
  const voiceSpeakingColor = normalizeHex(uiVoiceSpeakingColor.value) || DEFAULT_VOICE_COLORS.speaking;
  const voiceProcessingColor = normalizeHex(uiVoiceProcessingColor.value) || DEFAULT_VOICE_COLORS.processing;
  const voiceListeningRgb = hexToRgb(voiceListeningColor);
  const voiceSpeakingRgb = hexToRgb(voiceSpeakingColor);
  const voiceProcessingRgb = hexToRgb(voiceProcessingColor);

  root.style.setProperty('--vera-voice-listening', `rgba(${voiceListeningRgb.r}, ${voiceListeningRgb.g}, ${voiceListeningRgb.b}, 0.9)`);
  root.style.setProperty('--vera-voice-listening-glow', `rgba(${voiceListeningRgb.r}, ${voiceListeningRgb.g}, ${voiceListeningRgb.b}, 0.6)`);
  root.style.setProperty('--vera-voice-listening-text', voiceListeningColor);
  root.style.setProperty('--vera-voice-speaking', `rgba(${voiceSpeakingRgb.r}, ${voiceSpeakingRgb.g}, ${voiceSpeakingRgb.b}, 0.85)`);
  root.style.setProperty('--vera-voice-speaking-glow', `rgba(${voiceSpeakingRgb.r}, ${voiceSpeakingRgb.g}, ${voiceSpeakingRgb.b}, 0.5)`);
  root.style.setProperty('--vera-voice-speaking-text', voiceSpeakingColor);
  root.style.setProperty('--vera-voice-processing', `rgba(${voiceProcessingRgb.r}, ${voiceProcessingRgb.g}, ${voiceProcessingRgb.b}, 0.85)`);
  root.style.setProperty('--vera-voice-processing-glow', `rgba(${voiceProcessingRgb.r}, ${voiceProcessingRgb.g}, ${voiceProcessingRgb.b}, 0.7)`);

  // Drawer theming (right sidebar drawers: Tools, Diagnostics, Activity, etc.)
  const drawerMode = uiDrawerBackgroundMode.value ?? 'glass';
  const drawerPresetKey = uiDrawerBackgroundPreset.value || 'deep-space';
  const drawerPreset = BACKGROUND_PRESETS[drawerPresetKey] || BACKGROUND_PRESETS['deep-space'];
  // Use preset's surface/panel color as base if available, otherwise use user's Surface Color setting
  const presetSurfaceColor = presetVars['--vera-surface'] || presetVars['--vera-panel'];
  const drawerColor = extractHexColor(presetSurfaceColor) || normalizeHex(uiDrawerBackgroundColor.value) || '#060c18';
  const drawerColorRgb = hexToRgb(drawerColor);
  const drawerOpacity = clamp(uiDrawerBackgroundOpacity.value ?? DEFAULT_DRAWER_THEME.backgroundOpacity, 0, 1);
  const drawerBorderColor = normalizeHex(uiDrawerBorderColor.value) || DEFAULT_DRAWER_THEME.borderColor;
  const drawerBorderRgb = hexToRgb(drawerBorderColor);
  const drawerBorderOpacity = clamp(uiDrawerBorderOpacity.value ?? DEFAULT_DRAWER_THEME.borderOpacity, 0, 1);

  let drawerBg;
  if (drawerMode === 'preset') {
    drawerBg = drawerPreset.value;
  } else if (drawerMode === 'glass') {
    drawerBg = `rgba(${drawerColorRgb.r}, ${drawerColorRgb.g}, ${drawerColorRgb.b}, ${drawerOpacity * 0.5})`;
  } else if (drawerMode === 'glass-strong') {
    drawerBg = `rgba(${drawerColorRgb.r}, ${drawerColorRgb.g}, ${drawerColorRgb.b}, ${drawerOpacity * 0.8})`;
  } else if (drawerMode === 'solid') {
    drawerBg = drawerColor;
  } else if (drawerMode === 'transparent') {
    drawerBg = 'transparent';
  } else {
    drawerBg = `rgba(${drawerColorRgb.r}, ${drawerColorRgb.g}, ${drawerColorRgb.b}, ${drawerOpacity})`;
  }
  const drawerBorder = `rgba(${drawerBorderRgb.r}, ${drawerBorderRgb.g}, ${drawerBorderRgb.b}, ${drawerBorderOpacity})`;

  root.style.setProperty('--vera-drawer-bg', drawerBg);
  root.style.setProperty('--vera-drawer-border', drawerBorder);

  // Drawer card backgrounds
  const drawerCardMode = uiDrawerCardBackgroundMode.value ?? 'glass';
  // Use preset's panel-alt color as base if available
  const presetCardColor = presetVars['--vera-panel-alt'] || presetVars['--vera-panel'];
  const drawerCardColor = extractHexColor(presetCardColor) || normalizeHex(uiDrawerCardBackgroundColor.value) || DEFAULT_DRAWER_THEME.cardBackgroundColor;
  const drawerCardColorRgb = hexToRgb(drawerCardColor);
  const drawerCardOpacity = clamp(uiDrawerCardBackgroundOpacity.value ?? DEFAULT_DRAWER_THEME.cardBackgroundOpacity, 0, 1);

  let drawerCardBg;
  if (drawerCardMode === 'glass') {
    drawerCardBg = `rgba(${drawerCardColorRgb.r}, ${drawerCardColorRgb.g}, ${drawerCardColorRgb.b}, ${drawerCardOpacity * 0.5})`;
  } else if (drawerCardMode === 'glass-strong') {
    drawerCardBg = `rgba(${drawerCardColorRgb.r}, ${drawerCardColorRgb.g}, ${drawerCardColorRgb.b}, ${drawerCardOpacity * 0.8})`;
  } else if (drawerCardMode === 'solid') {
    drawerCardBg = drawerCardColor;
  } else if (drawerCardMode === 'transparent') {
    drawerCardBg = 'transparent';
  } else {
    drawerCardBg = `rgba(${drawerCardColorRgb.r}, ${drawerCardColorRgb.g}, ${drawerCardColorRgb.b}, ${drawerCardOpacity})`;
  }

  root.style.setProperty('--vera-drawer-card-bg', drawerCardBg);

  // Set core surface variables that components use
  // These derive from the drawer/card colors so themes affect all components
  root.style.setProperty('--vera-panel', drawerColor);
  root.style.setProperty('--vera-panel-alt', drawerCardColor);
  root.style.setProperty('--vera-panel-muted', adjustColor(drawerColor, effectiveMode === 'light' ? 0.05 : -0.03));
  root.style.setProperty('--vera-surface', drawerColor);
  root.style.setProperty('--vera-bg', uiBackgroundColor.value || (effectiveMode === 'light' ? '#f0f4f8' : '#0b0f14'));

  // Surface text colors - contrast with the drawer/panel background
  const surfaceIsLight = isLightColor(drawerColor);
  root.style.setProperty('--vera-surface-text', surfaceIsLight ? '#1d2b3a' : '#e6edf7');
  root.style.setProperty('--vera-surface-text-muted', surfaceIsLight ? '#586b7c' : '#9eb0c4');

  // Glass effects - computed from drawer color with appropriate opacity
  const glassBaseRgb = drawerColorRgb;
  root.style.setProperty('--vera-glass-bg', `rgba(${glassBaseRgb.r}, ${glassBaseRgb.g}, ${glassBaseRgb.b}, 0.72)`);
  root.style.setProperty('--vera-glass-strong', `rgba(${glassBaseRgb.r}, ${glassBaseRgb.g}, ${glassBaseRgb.b}, 0.92)`);
  root.style.setProperty('--vera-glass-border', drawerBorder);

  // Panel gradient - dynamic from drawer colors (overrides static preset values)
  const panelGradientStart = effectiveMode === 'light'
    ? `rgba(${Math.min(255, drawerColorRgb.r + 10)}, ${Math.min(255, drawerColorRgb.g + 10)}, ${Math.min(255, drawerColorRgb.b + 10)}, 0.96)`
    : `rgba(${Math.min(255, drawerColorRgb.r + 8)}, ${Math.min(255, drawerColorRgb.g + 8)}, ${Math.min(255, drawerColorRgb.b + 8)}, 0.96)`;
  const panelGradientEnd = effectiveMode === 'light'
    ? `rgba(${Math.max(0, drawerColorRgb.r - 15)}, ${Math.max(0, drawerColorRgb.g - 15)}, ${Math.max(0, drawerColorRgb.b - 15)}, 0.96)`
    : `rgba(${Math.max(0, drawerColorRgb.r - 6)}, ${Math.max(0, drawerColorRgb.g - 6)}, ${Math.max(0, drawerColorRgb.b - 6)}, 0.96)`;
  root.style.setProperty('--vera-panel-gradient', `linear-gradient(145deg, ${panelGradientStart}, ${panelGradientEnd})`);

  // Glow effects based on accent
  root.style.setProperty('--vera-glow-soft', `0 0 20px rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.3)`);
  root.style.setProperty('--vera-glow-strong', `0 0 30px rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.5)`);

  // Input field backgrounds - used by form inputs across the UI
  root.style.setProperty('--vera-input-bg', drawerCardColor);
  root.style.setProperty('--vera-input-text', effectiveMode === 'light' ? '#1d2b3a' : '#e6edf7');

  // Text colors - ensure they match the theme mode
  root.style.setProperty('--vera-text', effectiveMode === 'light' ? '#1d2b3a' : '#d4dee7');
  root.style.setProperty('--vera-text-muted', effectiveMode === 'light' ? '#586b7c' : '#8ea0b4');

  // Border color - derived from accent with appropriate opacity
  root.style.setProperty('--vera-border', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, ${effectiveMode === 'light' ? 0.18 : 0.14})`);

  // Code Editor panel
  const codeEditorColor = normalizeHex(uiCodeEditorBackgroundColor.value) || DEFAULT_CODE_EDITOR_THEME.backgroundColor;
  const codeEditorRgb = hexToRgb(codeEditorColor);
  const codeEditorOpacity = clamp(uiCodeEditorBackgroundOpacity.value ?? DEFAULT_CODE_EDITOR_THEME.backgroundOpacity, 0, 1);
  const codeEditorBg = `rgba(${codeEditorRgb.r}, ${codeEditorRgb.g}, ${codeEditorRgb.b}, ${codeEditorOpacity})`;
  root.style.setProperty('--vera-code-editor-bg', codeEditorBg);

  // Terminal panel
  const terminalColor = normalizeHex(uiTerminalBackgroundColor.value) || DEFAULT_TERMINAL_PANEL_THEME.backgroundColor;
  const terminalRgb = hexToRgb(terminalColor);
  const terminalOpacity = clamp(uiTerminalBackgroundOpacity.value ?? DEFAULT_TERMINAL_PANEL_THEME.backgroundOpacity, 0, 1);
  const terminalBg = `rgba(${terminalRgb.r}, ${terminalRgb.g}, ${terminalRgb.b}, ${terminalOpacity})`;
  root.style.setProperty('--vera-terminal-bg', terminalBg);

  const terminalHeaderColor = normalizeHex(uiTerminalHeaderBackgroundColor.value) || DEFAULT_TERMINAL_PANEL_THEME.headerBackgroundColor;
  const terminalHeaderRgb = hexToRgb(terminalHeaderColor);
  const terminalHeaderOpacity = clamp(uiTerminalHeaderBackgroundOpacity.value ?? DEFAULT_TERMINAL_PANEL_THEME.headerBackgroundOpacity, 0, 1);
  const terminalHeaderBg = `rgba(${terminalHeaderRgb.r}, ${terminalHeaderRgb.g}, ${terminalHeaderRgb.b}, ${terminalHeaderOpacity})`;
  root.style.setProperty('--vera-terminal-header-bg', terminalHeaderBg);

  // File Browser panel
  const fileBrowserColor = normalizeHex(uiFileBrowserBackgroundColor.value) || DEFAULT_FILE_BROWSER_THEME.backgroundColor;
  const fileBrowserRgb = hexToRgb(fileBrowserColor);
  const fileBrowserOpacity = clamp(uiFileBrowserBackgroundOpacity.value ?? DEFAULT_FILE_BROWSER_THEME.backgroundOpacity, 0, 1);
  const fileBrowserBg = `rgba(${fileBrowserRgb.r}, ${fileBrowserRgb.g}, ${fileBrowserRgb.b}, ${fileBrowserOpacity})`;
  root.style.setProperty('--vera-file-browser-bg', fileBrowserBg);

  // Dialog content areas - ALWAYS derive from drawer color for unified theming
  // This ensures Surface Color affects all dialog/panel areas consistently
  const dialogContentRgb = drawerColorRgb; // Use drawer color directly
  const dialogContentOpacity = clamp(uiDialogContentBackgroundOpacity.value ?? DEFAULT_DIALOG_CONTENT_THEME.backgroundOpacity, 0, 1);
  const dialogContentBg = `rgba(${dialogContentRgb.r}, ${dialogContentRgb.g}, ${dialogContentRgb.b}, ${dialogContentOpacity})`;
  root.style.setProperty('--vera-dialog-content-bg', dialogContentBg);

  // Card/Stat components
  const cardColor = normalizeHex(uiCardBackgroundColor.value) || DEFAULT_CARD_THEME.backgroundColor;
  const cardRgb = hexToRgb(cardColor);
  const cardOpacity = clamp(uiCardBackgroundOpacity.value ?? DEFAULT_CARD_THEME.backgroundOpacity, 0, 1);
  const cardBg = `rgba(${cardRgb.r}, ${cardRgb.g}, ${cardRgb.b}, ${cardOpacity})`;
  root.style.setProperty('--vera-card-bg', cardBg);

  // Filter button groups
  const filterButtonColor = normalizeHex(uiFilterButtonBackgroundColor.value) || DEFAULT_FILTER_BUTTON_THEME.backgroundColor;
  const filterButtonRgb = hexToRgb(filterButtonColor);
  const filterButtonOpacity = clamp(uiFilterButtonBackgroundOpacity.value ?? DEFAULT_FILTER_BUTTON_THEME.backgroundOpacity, 0, 1);
  const filterButtonBg = `rgba(${filterButtonRgb.r}, ${filterButtonRgb.g}, ${filterButtonRgb.b}, ${filterButtonOpacity})`;
  root.style.setProperty('--vera-filter-button-bg', filterButtonBg);

  const filterButtonActiveColor = normalizeHex(uiFilterButtonActiveBackgroundColor.value) || DEFAULT_FILTER_BUTTON_THEME.activeBackgroundColor;
  const filterButtonActiveRgb = hexToRgb(filterButtonActiveColor);
  const filterButtonActiveOpacity = clamp(uiFilterButtonActiveBackgroundOpacity.value ?? DEFAULT_FILTER_BUTTON_THEME.activeBackgroundOpacity, 0, 1);
  const filterButtonActiveBg = `rgba(${filterButtonActiveRgb.r}, ${filterButtonActiveRgb.g}, ${filterButtonActiveRgb.b}, ${filterButtonActiveOpacity})`;
  root.style.setProperty('--vera-filter-button-active-bg', filterButtonActiveBg);

  const isLiteMode = uiLiteMode.value === true;
  const scanlineOpacity = !isLiteMode && uiEffectScanlines.value
    ? clamp(uiEffectScanlineOpacity.value ?? 0.15, 0, 0.5)
    : 0;
  const noiseOpacity = !isLiteMode && uiEffectNoise.value
    ? clamp(uiEffectNoiseOpacity.value ?? 0.12, 0, 0.4)
    : 0;
  const gridOpacity = !isLiteMode && uiEffectGrid.value
    ? clamp(uiEffectGridOpacity.value ?? 0.2, 0, 0.6)
    : 0;
  const vignetteStrength = !isLiteMode && uiEffectVignette.value
    ? clamp(uiEffectVignetteStrength.value ?? 0.35, 0, 0.8)
    : 0;
  const auroraOpacity = !isLiteMode && uiEffectAurora.value
    ? clamp(uiEffectAuroraOpacity.value ?? 0.25, 0, 0.6)
    : 0;
  const animSpeed = clamp(uiAnimSpeed.value ?? 1.0, 0.5, 2.0);
  const auroraSpeed = clamp(uiEffectAuroraSpeed.value ?? 60, 0.5, 160) / animSpeed;
  root.style.setProperty('--vera-effect-scanline-opacity', String(scanlineOpacity));
  root.style.setProperty('--vera-effect-noise-opacity', String(noiseOpacity));
  root.style.setProperty('--vera-effect-grid-opacity', String(gridOpacity));
  root.style.setProperty('--vera-effect-vignette-strength', String(vignetteStrength));
  root.style.setProperty('--vera-effect-aurora-opacity', String(auroraOpacity));
  root.style.setProperty('--vera-effect-aurora-speed', `${auroraSpeed}s`);

  const glowStrength = !isLiteMode && uiEffectGlowPulse.value
    ? clamp(uiEffectGlowPulseStrength.value ?? 0.35, 0, 1)
    : 0;
  const glowSpeed = clamp(uiEffectGlowPulseSpeed.value ?? 6, 2, 20) / animSpeed;
  root.style.setProperty('--vera-effect-glow-color', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, ${glowStrength})`);
  if (glowStrength > 0) {
    glowPulseFlip = !glowPulseFlip;
  }
  const glowPulseName = glowPulseFlip ? 'veraGlowPulse' : 'veraGlowPulseAlt';
  root.style.setProperty(
    '--vera-glow-animation',
    glowStrength > 0 ? `${glowPulseName} ${glowSpeed}s ease-in-out infinite` : 'none'
  );
  const nowSeconds = (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000;
  const glowPhase = glowSpeed > 0 ? (nowSeconds % glowSpeed) : 0;
  root.style.setProperty('--vera-glow-delay', glowStrength > 0 ? `-${glowPhase.toFixed(3)}s` : '0s');

  const useMotion = !isLiteMode && uiAnimMessageMotion.value;
  const motionDuration = useMotion ? (0.3 / animSpeed).toFixed(2) : 0;
  const leaveDuration = useMotion ? (0.2 / animSpeed).toFixed(2) : 0;
  root.style.setProperty('--vera-message-motion-duration', `${motionDuration}s`);
  root.style.setProperty('--vera-message-motion-leave', `${leaveDuration}s`);
  root.style.setProperty('--vera-message-motion-distance', useMotion ? '16px' : '0px');
  root.style.setProperty('--vera-message-motion-slide-distance', useMotion ? '32px' : '0px');
  root.style.setProperty('--vera-hover-lift', !isLiteMode && uiAnimHoverLift.value ? '1' : '0');

  const hoverScale = !isLiteMode && uiAnimButtonMotion.value
    ? clamp(uiAnimButtonScale.value ?? 1.02, 1, 1.06)
    : 1;
  const activeScale = clamp(1 - (hoverScale - 1) * 0.8, 0.94, 1);
  root.style.setProperty('--vera-button-hover-scale', String(hoverScale));
  root.style.setProperty('--vera-button-active-scale', String(activeScale));
  root.dataset.animButtons = !isLiteMode && uiAnimButtonMotion.value ? 'on' : 'off';

  const shimmerStrength = !isLiteMode && uiEffectHeaderShimmer.value
    ? clamp(uiEffectHeaderShimmerStrength.value ?? 0.35, 0, 0.6)
    : 0;
  const shimmerSpeed = clamp(uiEffectHeaderShimmerSpeed.value ?? 12, 6, 30) / animSpeed;
  root.style.setProperty('--vera-header-shimmer-opacity', String(shimmerStrength));
  root.style.setProperty('--vera-header-shimmer-speed', `${shimmerSpeed}s`);
  root.dataset.headerShimmer = shimmerStrength > 0 ? 'on' : 'off';
  root.dataset.aurora = auroraOpacity > 0 ? 'on' : 'off';

  const driftSpeed = clamp(uiAnimBackgroundDriftSpeed.value ?? 45, 20, 120) / animSpeed;
  root.style.setProperty('--vera-anim-bg-drift-speed', `${driftSpeed}s`);
  root.dataset.animBgDrift = !isLiteMode && uiAnimBackgroundDrift.value ? 'on' : 'off';
  root.dataset.liteMode = isLiteMode ? 'on' : 'off';

  // Nixie tube settings
  const nixieColor = normalizeHex(uiNixieColor.value) || DEFAULT_NIXIE_THEME.color;
  const nixieGlowColor = normalizeHex(uiNixieGlowColor.value) || DEFAULT_NIXIE_THEME.glow;
    const nixieRgb = hexToRgb(nixieColor);
    const nixieGlowRgb = hexToRgb(nixieGlowColor);
    const nixieSpeed = clamp(uiNixieSpeed.value ?? 1.0, 0.25, 3.0);
    const nixieIntensity = clamp(uiNixieGlowIntensity.value ?? 1.0, 0.0, 2.0);
    const nixieFlicker = uiNixieFlicker.value !== false;
  
      root.style.setProperty('--vera-nixie-color', nixieColor);
      root.style.setProperty('--vera-nixie-glow', nixieGlowColor);
      
      // Export raw RGB triplets for CSS rgba() usage
      root.style.setProperty('--vera-nixie-digit-rgb', `${nixieRgb.r}, ${nixieRgb.g}, ${nixieRgb.b}`);
      root.style.setProperty('--vera-nixie-glow-rgb', `${nixieGlowRgb.r}, ${nixieGlowRgb.g}, ${nixieGlowRgb.b}`);
    
      // Scale alpha values based on intensity for soft/faint glows
      root.style.setProperty('--vera-nixie-color-glow', `rgba(${nixieGlowRgb.r}, ${nixieGlowRgb.g}, ${nixieGlowRgb.b}, ${0.8 * nixieIntensity})`);    root.style.setProperty('--vera-nixie-color-soft', `rgba(${nixieGlowRgb.r}, ${nixieGlowRgb.g}, ${nixieGlowRgb.b}, ${0.4 * nixieIntensity})`);
    root.style.setProperty('--vera-nixie-color-faint', `rgba(${nixieGlowRgb.r}, ${nixieGlowRgb.g}, ${nixieGlowRgb.b}, ${0.12 * nixieIntensity})`);
    root.style.setProperty('--vera-nixie-speed', String(nixieSpeed));
    root.style.setProperty('--vera-nixie-intensity', String(nixieIntensity));
    root.style.setProperty('--vera-nixie-flicker', nixieFlicker ? '1' : '0');

  // Exit button Nixie settings
  const nixieExitColor = normalizeHex(uiNixieExitColor.value) || DEFAULT_EXIT_BUTTON_THEME.color;
  const nixieExitGlowColor = normalizeHex(uiNixieExitGlowColor.value) || DEFAULT_EXIT_BUTTON_THEME.glow;
  const nixieExitRgb = hexToRgb(nixieExitColor);
  const nixieExitGlowRgb = hexToRgb(nixieExitGlowColor);
  const nixieExitIntensity = clamp(uiNixieExitGlowIntensity.value ?? 1.0, 0.0, 2.0);

  root.style.setProperty('--vera-nixie-exit-color', nixieExitColor);
  root.style.setProperty('--vera-nixie-exit-glow', nixieExitGlowColor);
  root.style.setProperty('--vera-nixie-exit-rgb', `${nixieExitRgb.r}, ${nixieExitRgb.g}, ${nixieExitRgb.b}`);
  root.style.setProperty('--vera-nixie-exit-glow-rgb', `${nixieExitGlowRgb.r}, ${nixieExitGlowRgb.g}, ${nixieExitGlowRgb.b}`);
  root.style.setProperty('--vera-nixie-exit-intensity', String(nixieExitIntensity));
  root.style.setProperty('--vera-nixie-exit-color-soft', `rgba(${nixieExitGlowRgb.r}, ${nixieExitGlowRgb.g}, ${nixieExitGlowRgb.b}, ${0.4 * nixieExitIntensity})`);
  root.style.setProperty('--vera-nixie-exit-color-faint', `rgba(${nixieExitGlowRgb.r}, ${nixieExitGlowRgb.g}, ${nixieExitGlowRgb.b}, ${0.15 * nixieExitIntensity})`);

  // Nixie button backgrounds
  const nixieButtonBg = normalizeHex(uiNixieButtonBackgroundColor.value) || DEFAULT_NIXIE_BUTTON_THEME.backgroundColor;
  root.style.setProperty('--vera-nixie-button-bg', nixieButtonBg);

  const depthValue = clamp(uiPanelDepth.value ?? 0.22, 0, 0.6);
  const depthAlpha = effectiveMode === 'light' ? depthValue * 0.18 : depthValue * 0.32;
  root.style.setProperty('--vera-panel-shadow', `0 10px 26px rgba(0, 0, 0, ${depthAlpha})`);

  const messageDepth = !isLiteMode && uiEffectMessageDepth.value
    ? clamp(uiEffectMessageDepthStrength.value ?? 0.22, 0, 0.6)
    : 0;
  const messageAlpha = effectiveMode === 'light' ? messageDepth * 0.16 : messageDepth * 0.34;
  root.style.setProperty(
    '--vera-message-shadow',
    messageAlpha > 0 ? `0 12px 30px rgba(0, 0, 0, ${messageAlpha})` : 'none'
  );
  const messageGlow = !isLiteMode ? clamp(inputGlowStrength * 0.85, 0, 0.6) : 0;
  root.style.setProperty(
    '--vera-message-glow',
    `0 0 18px rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, ${messageGlow})`
  );

  const edgeStrength = !isLiteMode && uiEffectPanelEdge.value
    ? clamp(uiEffectPanelEdgeStrength.value ?? 0.35, 0, 0.8)
    : 0;
  const edgeAlpha = effectiveMode === 'light' ? edgeStrength * 0.6 : edgeStrength;
  root.style.setProperty('--vera-panel-edge', edgeAlpha > 0 ? `rgba(255, 255, 255, ${edgeAlpha})` : 'transparent');

  const messageEdgeStrength = !isLiteMode && uiEffectMessageEdge.value
    ? clamp(uiEffectMessageEdgeStrength.value ?? 0.25, 0, 0.8)
    : 0;
  const messageEdgeAlpha = effectiveMode === 'light' ? messageEdgeStrength * 0.45 : messageEdgeStrength;
  const messageEdgeTint = uiEffectMessageEdgeTint.value === 'accent'
    ? `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, ${messageEdgeAlpha})`
    : `rgba(255, 255, 255, ${messageEdgeAlpha})`;
  root.style.setProperty('--vera-message-edge', messageEdgeAlpha > 0 ? messageEdgeTint : 'transparent');

  const panelGlowStrength = !isLiteMode && uiEffectPanelGlow.value
    ? clamp(uiEffectPanelGlowStrength.value ?? 0.35, 0, 0.8)
    : 0;
  const panelGlowAlpha = effectiveMode === 'light' ? panelGlowStrength * 0.4 : panelGlowStrength;
  root.style.setProperty(
    '--vera-panel-inner-glow',
    panelGlowAlpha > 0 ? `inset 0 0 32px rgba(255, 255, 255, ${panelGlowAlpha})` : 'none'
  );

  const bevelStrength = !isLiteMode && uiEffectPanelBevel.value
    ? clamp(uiEffectPanelBevelStrength.value ?? 0.2, 0, 0.5)
    : 0;
  const bevelTop = effectiveMode === 'light' ? bevelStrength * 0.4 : bevelStrength;
  const bevelBottom = effectiveMode === 'light' ? bevelStrength * 0.3 : bevelStrength * 0.6;
  root.style.setProperty(
    '--vera-panel-bevel',
    bevelStrength > 0
      ? `inset 0 1px 0 rgba(255, 255, 255, ${bevelTop}), inset 0 -1px 0 rgba(0, 0, 0, ${bevelBottom})`
      : 'none'
  );

  const appBlur = clamp(uiBackgroundBlur.value ?? 0, 0, 20);
  const imageBlur = bgMode === 'image' ? clamp(uiBackgroundImageBlur.value ?? 8, 0, 24) : 0;
  root.style.setProperty('--vera-bg-layer-blur', `${appBlur + imageBlur}px`);

  const headerBlur = clamp(uiHeaderBlur.value ?? 18, 0, 30);
  root.style.setProperty('--vera-header-blur', `${headerBlur}px`);
  root.style.setProperty('--vera-ripple-color', `rgba(${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}, 0.25)`);
  root.dataset.buttonRipple = !isLiteMode && uiAnimButtonRipple.value ? 'on' : 'off';

  // Font scale
  const fontScale = clamp(uiFontScale.value ?? 1.0, 0.85, 1.5);
  root.style.setProperty('--vera-font-scale', String(fontScale));
  root.style.fontSize = `${fontScale * 100}%`;

  // Animation speed multiplier (animSpeed already computed above for motion duration)
  root.style.setProperty('--vera-anim-speed', String(animSpeed));

  // Border radius mode
  const radiusMode = uiBorderRadius.value || 'normal';
  const radiusMultiplier = radiusMode === 'sharp' ? 0.25 : radiusMode === 'rounded' ? 1.5 : 1;
  root.style.setProperty('--vera-radius-sm', `${Math.round(4 * radiusMultiplier)}px`);
  root.style.setProperty('--vera-radius-md', `${Math.round(8 * radiusMultiplier)}px`);
  root.style.setProperty('--vera-radius-lg', `${Math.round(12 * radiusMultiplier)}px`);
  root.style.setProperty('--vera-radius-xl', `${Math.round(16 * radiusMultiplier)}px`);
  root.dataset.radiusMode = radiusMode;

  // Compact mode (spacing scale)
  const isCompact = uiCompactMode.value === true;
  const spacingScale = isCompact ? 0.8 : 1;
  root.style.setProperty('--vera-spacing-scale', String(spacingScale));
  root.dataset.compactMode = isCompact ? 'on' : 'off';

  // Font families per component
  const globalFont = resolveFontFamily(uiFontFamilyGlobal.value);
  root.style.setProperty('--vera-font-sans', globalFont);

  const headerFont = uiFontFamilyHeader.value === 'inherit'
    ? 'var(--vera-font-sans)'
    : resolveFontFamily(uiFontFamilyHeader.value);
  root.style.setProperty('--vera-font-header', headerFont);

  const sidebarFont = uiFontFamilySidebar.value === 'inherit'
    ? 'var(--vera-font-sans)'
    : resolveFontFamily(uiFontFamilySidebar.value);
  root.style.setProperty('--vera-font-sidebar', sidebarFont);

  const messagesFont = uiFontFamilyMessages.value === 'inherit'
    ? 'var(--vera-font-sans)'
    : resolveFontFamily(uiFontFamilyMessages.value);
  root.style.setProperty('--vera-font-messages', messagesFont);

  const inputFont = uiFontFamilyInput.value === 'inherit'
    ? 'var(--vera-font-sans)'
    : resolveFontFamily(uiFontFamilyInput.value);
  root.style.setProperty('--vera-font-input', inputFont);

  const codeFont = resolveFontFamily(uiFontFamilyCode.value, true);
  root.style.setProperty('--vera-font-mono', codeFont);

  // Font colors per component (empty means use surface-aware default)
  const headerColor = uiFontColorHeader.value || '';
  root.style.setProperty('--vera-text-header', headerColor || 'var(--vera-surface-text)');

  const sidebarColor = uiFontColorSidebar.value || '';
  root.style.setProperty('--vera-text-sidebar', sidebarColor || 'var(--vera-surface-text)');

  const messagesColor = uiFontColorMessages.value || '';
  root.style.setProperty('--vera-text-messages', messagesColor || 'var(--vera-text)');

  const inputColor = uiFontColorInput.value || '';
  root.style.setProperty('--vera-text-input', inputColor || 'var(--vera-surface-text)');

  const mutedColor = uiFontColorMuted.value || '';
  root.style.setProperty('--vera-text-muted-custom', mutedColor || 'var(--vera-surface-text-muted)');

  // Accessibility settings
  const reducedMotion = a11yReducedMotion.value || 'system';
  const prefersReducedMotion = typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false;
  const shouldReduceMotion = reducedMotion === 'on' || (reducedMotion === 'system' && prefersReducedMotion);
  root.dataset.reducedMotion = shouldReduceMotion ? 'on' : 'off';

  // High contrast mode
  const highContrast = a11yHighContrast.value === true;
  root.dataset.highContrast = highContrast ? 'on' : 'off';
  if (highContrast) {
    root.style.setProperty('--vera-text', effectiveMode === 'light' ? '#000000' : '#ffffff');
    root.style.setProperty('--vera-text-muted', effectiveMode === 'light' ? '#333333' : '#cccccc');
    root.style.setProperty('--vera-border', effectiveMode === 'light' ? 'rgba(0, 0, 0, 0.5)' : 'rgba(255, 255, 255, 0.5)');
  }

  // Large text mode
  const largeText = a11yLargeText.value === true;
  if (largeText) {
    const baseScale = clamp(uiFontScale.value ?? 1.0, 0.85, 1.5);
    root.style.setProperty('--vera-font-scale', String(baseScale * 1.25));
    root.style.fontSize = `${baseScale * 125}%`;
  }
  root.dataset.largeText = largeText ? 'on' : 'off';

  // Dyslexia-friendly font
  const dyslexiaFont = a11yDyslexiaFont.value === true;
  if (dyslexiaFont) {
    root.style.setProperty('--vera-font-sans', FONT_FAMILIES['atkinson']);
    root.style.setProperty('--vera-font-header', FONT_FAMILIES['atkinson']);
    root.style.setProperty('--vera-font-sidebar', FONT_FAMILIES['atkinson']);
    root.style.setProperty('--vera-font-messages', FONT_FAMILIES['atkinson']);
    root.style.setProperty('--vera-font-input', FONT_FAMILIES['atkinson']);
  }
  root.dataset.dyslexiaFont = dyslexiaFont ? 'on' : 'off';

  // Line spacing
  const lineSpacing = a11yLineSpacing.value || 'normal';
  const lineHeightMap = { tight: 1.3, normal: 1.6, relaxed: 1.9, loose: 2.2 };
  root.style.setProperty('--vera-line-height', String(lineHeightMap[lineSpacing] || 1.6));
  root.dataset.lineSpacing = lineSpacing;

  // Letter spacing
  const letterSpacing = a11yLetterSpacing.value || 'normal';
  const letterSpacingMap = { tight: '-0.02em', normal: '0', relaxed: '0.03em', loose: '0.06em' };
  root.style.setProperty('--vera-letter-spacing', letterSpacingMap[letterSpacing] || '0');
  root.dataset.letterSpacing = letterSpacing;

  // Focus highlight
  const focusHighlight = a11yFocusHighlight.value || 'normal';
  const focusOutlineMap = {
    subtle: `2px solid ${toRgba(accent, 0.4)}`,
    normal: `2px solid ${accent}`,
    strong: `3px solid ${accent}`,
    high: `4px dashed ${accent}`
  };
  root.style.setProperty('--vera-focus-outline', focusOutlineMap[focusHighlight] || focusOutlineMap.normal);
  root.dataset.focusHighlight = focusHighlight;

  // Avatar styling
  const avatarSizeValue = avatarSize.value || 'medium';
  const avatarSizeMap = { small: '28px', medium: '36px', large: '44px', xlarge: '56px' };
  root.style.setProperty('--vera-avatar-size', avatarSizeMap[avatarSizeValue] || '36px');
  root.dataset.avatarSize = avatarSizeValue;

  const avatarBorderStyleValue = avatarBorderStyle.value || 'none';
  const avatarBorderColorValue = avatarBorderColor.value || accent;
  const avatarBorderWidthValue = avatarBorderWidth.value || 2;
  const avatarBorderMap = {
    none: 'none',
    solid: `${avatarBorderWidthValue}px solid ${avatarBorderColorValue}`,
    dashed: `${avatarBorderWidthValue}px dashed ${avatarBorderColorValue}`,
    double: `${avatarBorderWidthValue * 2}px double ${avatarBorderColorValue}`,
    gradient: `${avatarBorderWidthValue}px solid transparent`
  };
  root.style.setProperty('--vera-avatar-border', avatarBorderMap[avatarBorderStyleValue] || 'none');
  if (avatarBorderStyleValue === 'gradient') {
    root.style.setProperty('--vera-avatar-border-image', `linear-gradient(135deg, ${avatarBorderColorValue}, ${adjustColor(avatarBorderColorValue, 0.3)}) 1`);
  } else {
    root.style.setProperty('--vera-avatar-border-image', 'none');
  }

  // Avatar glow
  const avatarGlowEnabled = avatarGlow.value === true;
  const avatarGlowColorValue = avatarGlowColor.value || accent;
  const avatarGlowIntensityValue = clamp(avatarGlowIntensity.value ?? 0.5, 0, 1);
  const avatarGlowRgb = hexToRgb(avatarGlowColorValue) || { r: 0, g: 153, b: 255 };
  root.style.setProperty(
    '--vera-avatar-glow',
    avatarGlowEnabled
      ? `0 0 ${12 * avatarGlowIntensityValue}px rgba(${avatarGlowRgb.r}, ${avatarGlowRgb.g}, ${avatarGlowRgb.b}, ${0.6 * avatarGlowIntensityValue})`
      : 'none'
  );

  // Avatar animation
  const avatarAnimationValue = avatarAnimation.value || 'none';
  root.dataset.avatarAnimation = avatarAnimationValue;

  // Avatar icon colors
  root.style.setProperty('--vera-avatar-ai-color', aiAvatarIconColor.value || '#10d2ff');
  root.style.setProperty('--vera-avatar-user-color', userAvatarIconColor.value || 'var(--vera-secondary)');

  // Theme overrides applied last so they win over presets and computed tokens.
  const nextOverrideKeys = new Set();
  Object.entries(overrides).forEach(([key, rawValue]) => {
    if (!key || typeof key !== 'string' || !key.startsWith('--')) {
      return;
    }
    if (rawValue === null || rawValue === undefined) {
      return;
    }
    let value = '';
    if (typeof rawValue === 'string') {
      value = rawValue.trim();
    } else if (typeof rawValue === 'number' || typeof rawValue === 'boolean') {
      value = String(rawValue);
    }
    if (!value) {
      return;
    }
    root.style.setProperty(key, value);
    nextOverrideKeys.add(key);
  });
  previousOverrideKeys.forEach((key) => {
    if (!nextOverrideKeys.has(key)) {
      root.style.removeProperty(key);
    }
  });
  previousOverrideKeys = nextOverrideKeys;

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('vera-theme-updated'));
  }
};

let previousOverrideKeys = new Set();
let mediaQuery = null;
let mediaHandler = null;

export const setupThemeListener = () => {
  if (typeof window === 'undefined' || !window.matchMedia) {
    return;
  }
  if (mediaQuery) {
    return;
  }
  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
  mediaHandler = () => {
    if (uiThemeMode.value === 'system') {
      applyTheme();
    }
  };
  if (mediaQuery.addEventListener) {
    mediaQuery.addEventListener('change', mediaHandler);
  } else if (mediaQuery.addListener) {
    mediaQuery.addListener(mediaHandler);
  }
};
