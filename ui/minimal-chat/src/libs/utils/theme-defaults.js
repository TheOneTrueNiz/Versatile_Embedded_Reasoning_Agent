export const ACCENT_SWATCHES = [
  { label: 'Deep Blue', value: '#0099ff' },
  { label: 'Azure', value: '#36a3ff' },
  { label: 'Cyan', value: '#2ccad8' },
  { label: 'Amber', value: '#d28b2f' },
  { label: 'Slate', value: '#7f8ea3' }
];

export const SECONDARY_SWATCHES = [
  { label: 'Violet', value: '#a78bfa' },
  { label: 'Purple', value: '#8b5cf6' },
  { label: 'Magenta', value: '#d946ef' },
  { label: 'Rose', value: '#f43f5e' },
  { label: 'Teal', value: '#2dd4bf' }
];

export const DEFAULT_TOKEN_COLOR_FALLBACK = '#000000';
export const DEFAULT_SECONDARY_ACCENT = '#a78bfa';
export const DEFAULT_DRAWER_THEME = {
  backgroundColor: '#060c18',
  backgroundOpacity: 0.85,
  borderColor: '#10d2ff',
  borderOpacity: 0.12,
  cardBackgroundColor: '#0a1424',
  cardBackgroundOpacity: 0.6
};

export const DEFAULT_CODE_EDITOR_THEME = {
  backgroundColor: '#060c18',
  backgroundOpacity: 0.92
};

export const DEFAULT_TERMINAL_PANEL_THEME = {
  backgroundColor: '#060c18',
  backgroundOpacity: 0.85,
  headerBackgroundColor: '#081c1c',
  headerBackgroundOpacity: 0.7
};

export const DEFAULT_FILE_BROWSER_THEME = {
  backgroundColor: '#0a1424',
  backgroundOpacity: 0.6
};

export const DEFAULT_DIALOG_CONTENT_THEME = {
  backgroundColor: '#0a1424',
  backgroundOpacity: 0.5
};

export const DEFAULT_CARD_THEME = {
  backgroundColor: '#0a1424',
  backgroundOpacity: 0.6
};

export const DEFAULT_FILTER_BUTTON_THEME = {
  backgroundColor: '#0a1424',
  backgroundOpacity: 0.5,
  activeBackgroundColor: '#10d2ff',
  activeBackgroundOpacity: 0.15
};

export const DEFAULT_TERMINAL_COLORS = {
  background: '#060c18',
  foreground: '#c8d4e8',
  cursor: '#10d2ff',
  selection: '#10d2ff40',
  black: '#1a1e2e',
  red: '#ff6b6b',
  green: '#4ade80',
  yellow: '#fbbf24',
  blue: '#60a5fa',
  magenta: '#a78bfa',
  cyan: '#10d2ff',
  white: '#e2e8f0'
};

export const DEFAULT_STATUS_COLORS = {
  success: '#4ade80',
  warning: '#fbbf24',
  error: '#ff6b6b',
  info: '#60a5fa'
};

export const DEFAULT_EVENT_COLORS = {
  routing: '#a78bfa',
  memory: '#60a5fa',
  tool: '#4ade80',
  decision: 'var(--vera-status-success)',
  quorum: 'var(--vera-status-warning)',
  error: 'var(--vera-status-error)'
};

export const DEFAULT_GIT_COLORS = {
  added: '#4ade80',
  modified: '#fbbf24',
  deleted: '#f87171',
  untracked: '#94a3b8'
};

export const DEFAULT_THEME_RESET = {
  backgroundColor: '#0b0f14',
  backgroundGradientStart: '#0b0f14',
  backgroundGradientEnd: '#121a26',
  backgroundGradientAngle: 135,
  backgroundImageOpacity: 0.35,
  backgroundImageBlur: 8,
  sidebarBackgroundColor: '#101826',
  sidebarBackgroundGradientStart: '#0f1724',
  sidebarBackgroundGradientEnd: '#182230',
  sidebarBackgroundGradientAngle: 135,
  sidebarBackgroundImageOpacity: 0.25,
  sidebarBackgroundImageBlur: 6,
  inputBarBackgroundColor: '#0c1420',
  inputBarBackgroundOpacity: 0.62,
  inputBarBorderColor: '#78aaff',
  inputBarBorderOpacity: 0.2,
  inputBarGlow: 0.25,
  toolCardBackgroundColor: '#0c1420',
  toolCardBackgroundOpacity: 0.62,
  toolCardBorderColor: '#78aaff',
  toolCardBorderOpacity: 0.2,
  toolCardGlow: 0.25
};

export const DEFAULT_HEADER_THEME = {
  backgroundColor: '#101826',
  backgroundImageOpacity: 0.25,
  backgroundImageBlur: 6
};

export const DEFAULT_INPUT_BAR_THEME = {
  backgroundColor: '#0c1420',
  backgroundOpacity: 0.12,
  borderColor: '#78aaff',
  borderOpacity: 0.2,
  glow: 0.25
};

export const DEFAULT_USER_MESSAGE_THEME = {
  backgroundColor: '#0e1e34',
  backgroundOpacity: 0.88,
  borderColor: '#0099ff',
  borderOpacity: 0.2
};

export const DEFAULT_ASSISTANT_MESSAGE_THEME = {
  backgroundColor: '#0c121c',
  backgroundOpacity: 0.92,
  borderColor: '#78aaff',
  borderOpacity: 0.14
};

export const DEFAULT_TOOL_CARD_THEME = {
  backgroundColor: '#0c1420',
  backgroundOpacity: 0.12,
  borderColor: '#78aaff',
  borderOpacity: 0.2,
  glow: 0.25
};

export const DEFAULT_BUTTON_THEME = {
  backgroundColor: '#0c1420',
  backgroundOpacity: 0.6,
  borderColor: '#78aaff',
  borderOpacity: 0.2,
  glow: 0.25
};

export const DEFAULT_THINKING_DROPDOWN_THEME = {
  headerBackgroundColor: '#101826',
  headerBackgroundOpacity: 0.85,
  headerBorderColor: '#78aaff',
  headerBorderOpacity: 0.15,
  contentBackgroundColor: '#0c1420',
  contentBackgroundOpacity: 0.12
};

export const DEFAULT_VOICE_COLORS = {
  listening: '#7dcfff',
  speaking: '#d9ad64',
  processing: '#6ab4ff'
};

export const DEFAULT_NIXIE_THEME = {
  color: '#ff9040',
  glow: '#ff6020'
};

export const DEFAULT_EXIT_BUTTON_THEME = {
  color: '#e06464',
  glow: '#ff4444'
};

export const DEFAULT_NIXIE_BUTTON_THEME = {
  backgroundColor: '#1e160f'
};

export const DEFAULT_AVATAR_STYLE = {
  borderColor: '#0099ff',
  borderWidth: 2,
  glowColor: '#0099ff',
  glowIntensity: 0.5
};

export const DEFAULT_AVATAR_ICON_COLORS = {
  ai: '#10d2ff',
  user: 'var(--vera-secondary)'
};

// ============================================
// Global Theme Presets
// ============================================

export const GLOBAL_THEME_PRESETS = [
  {
    id: 'default',
    label: 'Default',
    description: 'VERA\'s signature deep space aesthetic.',
    preview: { bg: '#0b0f14', accent: '#0099ff', secondary: '#a78bfa' },
    nativeMode: 'dark',
    config: {
      // Accents
      accentColor: '#0099ff',
      secondaryAccent: '#a78bfa',
      // Background
      backgroundMode: 'preset',
      backgroundPreset: 'deep-space',
      backgroundColor: '#0b0f14',
      // Glass & Effects
      glassEnabled: true,
      glowEnabled: true,
      depthEnabled: true,
      scanlineEnabled: false,
      // Panel surfaces
      panelSurfacePreset: 'workstation',
      // Drawer and panel backgrounds
      drawerBackgroundColor: '#0c121c',
      drawerBackgroundOpacity: 0.88,
      drawerCardBackgroundColor: '#10182a',
      inputBarBackgroundColor: '#0a1020',
      toolCardBackgroundColor: '#0c121c',
      // Terminal
      terminalBackground: '#060c18',
      terminalForeground: '#c8d4e8',
      // Status colors
      statusSuccess: '#4ade80',
      statusWarning: '#fbbf24',
      statusError: '#ff6b6b',
      statusInfo: '#60a5fa',
      // Nixie tube colors
      nixieColor: '#ff9040',
      nixieGlowColor: '#ff6020',
      nixieButtonBackgroundColor: '#1e160f',
      nixieExitColor: '#e06464',
      nixieExitGlowColor: '#ff4444',
      // Message bubbles
      userMessageBackgroundColor: '#0e1e34',
      userMessageBackgroundOpacity: 0.88,
      userMessageBorderColor: '#0099ff',
      userMessageBorderOpacity: 0.2,
      userMessageBackgroundMode: 'glass',
      assistantMessageBackgroundColor: '#0c121c',
      assistantMessageBackgroundOpacity: 0.92,
      assistantMessageBorderColor: '#a78bfa',
      assistantMessageBorderOpacity: 0.14,
      assistantMessageBackgroundMode: 'glass',
      // Header
      headerBackgroundColor: '#101826',
      headerBackgroundMode: 'transparent',
      // Sidebar
      sidebarBackgroundMode: 'glass',
      // Dialog content
      dialogContentBackgroundColor: '#0c121c',
      dialogContentBackgroundOpacity: 0.92
    }
  },
  {
    id: 'cyberpunk',
    label: 'Cyberpunk',
    description: 'Noir black with neon purple, cyan, and pink. Heavy glass and glow.',
    preview: { bg: '#050508', accent: '#ff00ff', secondary: '#00ffff' },
    nativeMode: 'dark',
    config: {
      accentColor: '#ff00ff',
      secondaryAccent: '#00ffff',
      backgroundMode: 'gradient',
      backgroundPreset: 'orbital-dusk',
      backgroundColor: '#050508',
      backgroundGradientStart: '#050508',
      backgroundGradientEnd: '#0a0515',
      backgroundGradientAngle: 135,
      glassEnabled: true,
      glowEnabled: true,
      depthEnabled: true,
      scanlineEnabled: false,
      panelSurfacePreset: 'neon-drift',
      terminalBackground: '#050508',
      terminalForeground: '#e0e0ff',
      terminalCursor: '#ff00ff',
      statusSuccess: '#00ff88',
      statusWarning: '#ffff00',
      statusError: '#ff0055',
      statusInfo: '#00ffff',
      // Drawer and panel surfaces
      drawerBackgroundColor: '#080010',
      drawerBackgroundOpacity: 0.9,
      drawerCardBackgroundColor: '#0f0018',
      inputBarBackgroundColor: '#0a0012',
      toolCardBackgroundColor: '#080010',
      // Extra cyber styling
      inputBarBorderColor: '#ff00ff',
      toolCardBorderColor: '#00ffff',
      drawerBorderColor: '#ff00ff',
      // Nixie tube colors
      nixieColor: '#ff00ff',
      nixieGlowColor: '#cc00cc',
      nixieButtonBackgroundColor: '#150015',
      nixieExitColor: '#ff0055',
      nixieExitGlowColor: '#cc0044',
      // Message bubbles
      userMessageBackgroundColor: '#150020',
      userMessageBackgroundOpacity: 0.9,
      userMessageBorderColor: '#ff00ff',
      userMessageBorderOpacity: 0.3,
      userMessageBackgroundMode: 'glass',
      assistantMessageBackgroundColor: '#0a0015',
      assistantMessageBackgroundOpacity: 0.92,
      assistantMessageBorderColor: '#00ffff',
      assistantMessageBorderOpacity: 0.25,
      assistantMessageBackgroundMode: 'glass',
      // Header
      headerBackgroundColor: '#050508',
      headerBackgroundMode: 'transparent',
      // Sidebar
      sidebarBackgroundMode: 'glass',
      // Dialog content (cyberpunk dark magenta-black)
      dialogContentBackgroundColor: '#0a0015',
      dialogContentBackgroundOpacity: 0.92
    }
  },
  {
    id: 'glacial',
    label: 'Glacial',
    description: 'Cool grey and white gradients with cyan accents. Clean and crisp.',
    preview: { bg: '#e8eef5', accent: '#0891b2', secondary: '#6366f1' },
    nativeMode: 'light',
    config: {
      accentColor: '#0891b2',
      secondaryAccent: '#6366f1',
      backgroundMode: 'gradient',
      backgroundPreset: 'glacial',
      backgroundColor: '#e8eef5',
      backgroundGradientStart: '#e8eef5',
      backgroundGradientEnd: '#cdd5e0',
      backgroundGradientAngle: 180,
      glassEnabled: true,
      glowEnabled: false,
      depthEnabled: true,
      scanlineEnabled: false,
      panelSurfacePreset: 'minimal',
      terminalBackground: '#1e293b',
      terminalForeground: '#e2e8f0',
      terminalCursor: '#0891b2',
      statusSuccess: '#10b981',
      statusWarning: '#f59e0b',
      statusError: '#ef4444',
      statusInfo: '#0891b2',
      // Light theme surfaces
      drawerBackgroundColor: '#f1f5f9',
      drawerCardBackgroundColor: '#ffffff',
      dialogContentBackgroundColor: '#ffffff',
      inputBarBackgroundColor: '#ffffff',
      toolCardBackgroundColor: '#f8fafc',
      // Sidebar for light theme
      sidebarBackgroundColor: '#ffffff',
      sidebarBackgroundOpacity: 0.85,
      // Nixie tube colors
      nixieColor: '#0891b2',
      nixieGlowColor: '#066b8a',
      nixieButtonBackgroundColor: '#1e293b',
      nixieExitColor: '#ef4444',
      nixieExitGlowColor: '#dc2626',
      // Message bubbles (light theme)
      userMessageBackgroundColor: '#ffffff',
      userMessageBackgroundOpacity: 0.95,
      userMessageBorderColor: '#0891b2',
      userMessageBorderOpacity: 0.2,
      userMessageBackgroundMode: 'solid',
      assistantMessageBackgroundColor: '#f1f5f9',
      assistantMessageBackgroundOpacity: 0.95,
      assistantMessageBorderColor: '#6366f1',
      assistantMessageBorderOpacity: 0.15,
      assistantMessageBackgroundMode: 'solid',
      // Header
      headerBackgroundColor: '#ffffff',
      headerBackgroundMode: 'solid',
      // Sidebar
      sidebarBackgroundMode: 'solid'
    }
  },
  {
    id: 'dos-green',
    label: 'Classic DOS Green',
    description: 'Retro phosphor green on black with authentic scanlines.',
    preview: { bg: '#000000', accent: '#33ff33', secondary: '#00aa00' },
    nativeMode: 'dark',
    config: {
      accentColor: '#33ff33',
      secondaryAccent: '#00aa00',
      backgroundMode: 'color',
      backgroundPreset: 'dos-green',
      backgroundColor: '#000000',
      glassEnabled: false,
      glowEnabled: true,
      depthEnabled: false,
      scanlineEnabled: true,
      panelSurfacePreset: 'minimal',
      terminalBackground: '#000000',
      terminalForeground: '#33ff33',
      terminalCursor: '#33ff33',
      terminalBlack: '#001100',
      terminalGreen: '#33ff33',
      terminalCyan: '#00ffaa',
      terminalWhite: '#88ff88',
      statusSuccess: '#33ff33',
      statusWarning: '#aaff00',
      statusError: '#ff3333',
      statusInfo: '#33ffff',
      // Solid panels
      drawerBackgroundColor: '#001100',
      drawerBackgroundOpacity: 0.95,
      drawerCardBackgroundColor: '#002200',
      inputBarBackgroundColor: '#001100',
      inputBarBorderColor: '#33ff33',
      toolCardBackgroundColor: '#001100',
      toolCardBorderColor: '#33ff33',
      // Nixie tube colors
      nixieColor: '#33ff33',
      nixieGlowColor: '#00aa00',
      nixieButtonBackgroundColor: '#001100',
      nixieExitColor: '#ff3333',
      nixieExitGlowColor: '#cc0000',
      // Message bubbles
      userMessageBackgroundColor: '#001a00',
      userMessageBackgroundOpacity: 0.95,
      userMessageBorderColor: '#33ff33',
      userMessageBorderOpacity: 0.3,
      userMessageBackgroundMode: 'solid',
      assistantMessageBackgroundColor: '#001100',
      assistantMessageBackgroundOpacity: 0.95,
      assistantMessageBorderColor: '#00aa00',
      assistantMessageBorderOpacity: 0.25,
      assistantMessageBackgroundMode: 'solid',
      // Header
      headerBackgroundColor: '#000000',
      headerBackgroundMode: 'solid',
      // Sidebar
      sidebarBackgroundMode: 'solid',
      // Dialog content (DOS green dark)
      dialogContentBackgroundColor: '#002200',
      dialogContentBackgroundOpacity: 0.95
    }
  },
  {
    id: 'nixie-amber',
    label: 'Nixie Amber',
    description: 'Warm amber glow reminiscent of vintage nixie tubes.',
    preview: { bg: '#0a0604', accent: '#ff9040', secondary: '#ff6020' },
    nativeMode: 'dark',
    config: {
      accentColor: '#ff9040',
      secondaryAccent: '#ff6020',
      backgroundMode: 'color',
      backgroundPreset: 'nixie-amber',
      backgroundColor: '#0a0604',
      glassEnabled: false,
      glowEnabled: true,
      depthEnabled: true,
      scanlineEnabled: true,
      panelSurfacePreset: 'ember',
      terminalBackground: '#0a0604',
      terminalForeground: '#ffb060',
      terminalCursor: '#ff9040',
      terminalBlack: '#1a0a04',
      terminalRed: '#ff4020',
      terminalGreen: '#ff8020',
      terminalYellow: '#ffcc00',
      terminalWhite: '#ffe0a0',
      statusSuccess: '#ffaa00',
      statusWarning: '#ff8800',
      statusError: '#ff4400',
      statusInfo: '#ffcc44',
      drawerBackgroundColor: '#120a06',
      drawerBackgroundOpacity: 0.95,
      drawerCardBackgroundColor: '#1a0f08',
      inputBarBackgroundColor: '#100804',
      inputBarBorderColor: '#ff9040',
      toolCardBackgroundColor: '#120a06',
      toolCardBorderColor: '#ff9040',
      // Nixie tube colors
      nixieColor: '#ff9040',
      nixieGlowColor: '#ff6020',
      nixieButtonBackgroundColor: '#1e160f',
      nixieExitColor: '#ff4400',
      nixieExitGlowColor: '#cc3300',
      // Message bubbles
      userMessageBackgroundColor: '#1a0f08',
      userMessageBackgroundOpacity: 0.95,
      userMessageBorderColor: '#ff9040',
      userMessageBorderOpacity: 0.3,
      userMessageBackgroundMode: 'solid',
      assistantMessageBackgroundColor: '#120a06',
      assistantMessageBackgroundOpacity: 0.95,
      assistantMessageBorderColor: '#ff6020',
      assistantMessageBorderOpacity: 0.25,
      assistantMessageBackgroundMode: 'solid',
      // Header
      headerBackgroundColor: '#0a0604',
      headerBackgroundMode: 'solid',
      // Sidebar
      sidebarBackgroundMode: 'solid',
      // Dialog content (nixie amber dark)
      dialogContentBackgroundColor: '#1a0f08',
      dialogContentBackgroundOpacity: 0.95
    }
  },
  {
    id: 'industrial',
    label: 'Industrial',
    description: 'Solid utilitarian design. Yellows, golds, browns, and greys.',
    preview: { bg: '#1a1a18', accent: '#d4a84b', secondary: '#8b7355' },
    nativeMode: 'dark',
    config: {
      accentColor: '#d4a84b',
      secondaryAccent: '#8b7355',
      backgroundMode: 'color',
      backgroundPreset: 'industrial',
      backgroundColor: '#1a1a18',
      glassEnabled: false,
      glowEnabled: false,
      depthEnabled: true,
      scanlineEnabled: false,
      panelSurfacePreset: 'minimal',
      terminalBackground: '#141412',
      terminalForeground: '#c8c4b8',
      terminalCursor: '#d4a84b',
      statusSuccess: '#8faa4c',
      statusWarning: '#d4a84b',
      statusError: '#c45a4a',
      statusInfo: '#6a8fa8',
      drawerBackgroundColor: '#22221e',
      drawerBackgroundOpacity: 1.0,
      drawerCardBackgroundColor: '#2a2a26',
      drawerBorderColor: '#4a4a42',
      inputBarBackgroundColor: '#1e1e1a',
      inputBarBackgroundOpacity: 1.0,
      inputBarBorderColor: '#d4a84b',
      toolCardBackgroundColor: '#22221e',
      toolCardBackgroundOpacity: 1.0,
      toolCardBorderColor: '#4a4a42',
      // Nixie tube colors
      nixieColor: '#d4a84b',
      nixieGlowColor: '#8b7355',
      nixieButtonBackgroundColor: '#1a1a18',
      nixieExitColor: '#c45a4a',
      nixieExitGlowColor: '#a04030',
      // Message bubbles
      userMessageBackgroundColor: '#2a2a26',
      userMessageBackgroundOpacity: 1.0,
      userMessageBorderColor: '#d4a84b',
      userMessageBorderOpacity: 0.25,
      userMessageBackgroundMode: 'solid',
      assistantMessageBackgroundColor: '#22221e',
      assistantMessageBackgroundOpacity: 1.0,
      assistantMessageBorderColor: '#8b7355',
      assistantMessageBorderOpacity: 0.2,
      assistantMessageBackgroundMode: 'solid',
      // Header
      headerBackgroundColor: '#1a1a18',
      headerBackgroundMode: 'solid',
      // Sidebar
      sidebarBackgroundMode: 'solid',
      // Dialog content (industrial grey-brown)
      dialogContentBackgroundColor: '#2a2a26',
      dialogContentBackgroundOpacity: 1.0
    }
  },
  {
    id: 'azure',
    label: 'Azure',
    description: 'Clean, modern, professional. Blues, greys, and whites.',
    preview: { bg: '#f0f4f8', accent: '#2563eb', secondary: '#7c3aed' },
    nativeMode: 'light',
    config: {
      accentColor: '#2563eb',
      secondaryAccent: '#7c3aed',
      backgroundMode: 'gradient',
      backgroundPreset: 'azure',
      backgroundColor: '#f0f4f8',
      backgroundGradientStart: '#f0f4f8',
      backgroundGradientEnd: '#e2e8f0',
      backgroundGradientAngle: 180,
      glassEnabled: true,
      glowEnabled: false,
      depthEnabled: true,
      scanlineEnabled: false,
      panelSurfacePreset: 'minimal',
      terminalBackground: '#1e293b',
      terminalForeground: '#e2e8f0',
      terminalCursor: '#2563eb',
      statusSuccess: '#22c55e',
      statusWarning: '#eab308',
      statusError: '#ef4444',
      statusInfo: '#2563eb',
      drawerBackgroundColor: '#ffffff',
      drawerBackgroundOpacity: 0.95,
      drawerCardBackgroundColor: '#f8fafc',
      drawerBorderColor: '#e2e8f0',
      inputBarBackgroundColor: '#ffffff',
      inputBarBorderColor: '#2563eb',
      toolCardBackgroundColor: '#f8fafc',
      toolCardBorderColor: '#e2e8f0',
      // Sidebar for light theme
      sidebarBackgroundColor: '#ffffff',
      sidebarBackgroundOpacity: 0.85,
      // Nixie tube colors
      nixieColor: '#2563eb',
      nixieGlowColor: '#1d4ed8',
      nixieButtonBackgroundColor: '#1e293b',
      nixieExitColor: '#ef4444',
      nixieExitGlowColor: '#dc2626',
      // Message bubbles (light theme)
      userMessageBackgroundColor: '#ffffff',
      userMessageBackgroundOpacity: 0.95,
      userMessageBorderColor: '#2563eb',
      userMessageBorderOpacity: 0.2,
      userMessageBackgroundMode: 'solid',
      assistantMessageBackgroundColor: '#f8fafc',
      assistantMessageBackgroundOpacity: 0.95,
      assistantMessageBorderColor: '#7c3aed',
      assistantMessageBorderOpacity: 0.15,
      assistantMessageBackgroundMode: 'solid',
      // Header
      headerBackgroundColor: '#ffffff',
      headerBackgroundMode: 'solid',
      // Sidebar
      sidebarBackgroundMode: 'solid',
      // Dialog content (azure light)
      dialogContentBackgroundColor: '#f8fafc',
      dialogContentBackgroundOpacity: 0.98
    }
  },
  {
    id: 'deep-space',
    label: 'Deep Space',
    description: 'Vast darkness with silver, white, and blue-purple glows.',
    preview: { bg: '#030308', accent: '#6366f1', secondary: '#8b5cf6' },
    nativeMode: 'dark',
    config: {
      accentColor: '#6366f1',
      secondaryAccent: '#8b5cf6',
      backgroundMode: 'gradient',
      backgroundPreset: 'deep-space',
      backgroundColor: '#030308',
      backgroundGradientStart: '#030308',
      backgroundGradientEnd: '#0a0a15',
      backgroundGradientAngle: 135,
      glassEnabled: true,
      glowEnabled: true,
      depthEnabled: true,
      scanlineEnabled: false,
      panelSurfacePreset: 'neon-drift',
      terminalBackground: '#030308',
      terminalForeground: '#c8d4e8',
      terminalCursor: '#6366f1',
      statusSuccess: '#4ade80',
      statusWarning: '#fbbf24',
      statusError: '#f87171',
      statusInfo: '#6366f1',
      drawerBackgroundColor: '#080810',
      drawerBackgroundOpacity: 0.85,
      drawerCardBackgroundColor: '#10101a',
      drawerBorderColor: '#6366f1',
      inputBarBackgroundColor: '#060610',
      inputBarBorderColor: '#8b5cf6',
      toolCardBackgroundColor: '#08080f',
      toolCardBorderColor: '#6366f1',
      // Nixie tube colors
      nixieColor: '#6366f1',
      nixieGlowColor: '#4f46e5',
      nixieButtonBackgroundColor: '#080810',
      nixieExitColor: '#f87171',
      nixieExitGlowColor: '#ef4444',
      // Message bubbles
      userMessageBackgroundColor: '#10101a',
      userMessageBackgroundOpacity: 0.88,
      userMessageBorderColor: '#6366f1',
      userMessageBorderOpacity: 0.25,
      userMessageBackgroundMode: 'glass',
      assistantMessageBackgroundColor: '#08080f',
      assistantMessageBackgroundOpacity: 0.9,
      assistantMessageBorderColor: '#8b5cf6',
      assistantMessageBorderOpacity: 0.2,
      assistantMessageBackgroundMode: 'glass',
      // Header
      headerBackgroundColor: '#030308',
      headerBackgroundMode: 'transparent',
      // Sidebar
      sidebarBackgroundMode: 'glass',
      // Dialog content (deep space dark purple)
      dialogContentBackgroundColor: '#10101a',
      dialogContentBackgroundOpacity: 0.9
    }
  },
  {
    id: 'steel-veil',
    label: 'Steel Veil',
    description: 'Metallic shades of grey with a brushed steel aesthetic.',
    preview: { bg: '#1a1c20', accent: '#94a3b8', secondary: '#64748b' },
    nativeMode: 'dark',
    config: {
      accentColor: '#94a3b8',
      secondaryAccent: '#64748b',
      backgroundMode: 'gradient',
      backgroundPreset: 'steel-veil',
      backgroundColor: '#1a1c20',
      backgroundGradientStart: '#1a1c20',
      backgroundGradientEnd: '#2a2d33',
      backgroundGradientAngle: 145,
      glassEnabled: true,
      glowEnabled: false,
      depthEnabled: true,
      scanlineEnabled: false,
      panelSurfacePreset: 'minimal',
      terminalBackground: '#14161a',
      terminalForeground: '#cbd5e1',
      terminalCursor: '#94a3b8',
      statusSuccess: '#6ee7b7',
      statusWarning: '#fcd34d',
      statusError: '#fca5a5',
      statusInfo: '#93c5fd',
      drawerBackgroundColor: '#22252a',
      drawerBackgroundOpacity: 0.9,
      drawerCardBackgroundColor: '#2a2d33',
      drawerBorderColor: '#475569',
      inputBarBackgroundColor: '#1e2126',
      inputBarBorderColor: '#94a3b8',
      toolCardBackgroundColor: '#22252a',
      toolCardBorderColor: '#475569',
      // Nixie tube colors
      nixieColor: '#94a3b8',
      nixieGlowColor: '#64748b',
      nixieButtonBackgroundColor: '#1a1c20',
      nixieExitColor: '#fca5a5',
      nixieExitGlowColor: '#f87171',
      // Message bubbles
      userMessageBackgroundColor: '#2a2d33',
      userMessageBackgroundOpacity: 0.9,
      userMessageBorderColor: '#94a3b8',
      userMessageBorderOpacity: 0.2,
      userMessageBackgroundMode: 'glass',
      assistantMessageBackgroundColor: '#22252a',
      assistantMessageBackgroundOpacity: 0.9,
      assistantMessageBorderColor: '#64748b',
      assistantMessageBorderOpacity: 0.15,
      assistantMessageBackgroundMode: 'glass',
      // Header
      headerBackgroundColor: '#1a1c20',
      headerBackgroundMode: 'transparent',
      // Sidebar
      sidebarBackgroundMode: 'glass',
      // Dialog content (steel grey)
      dialogContentBackgroundColor: '#2a2d33',
      dialogContentBackgroundOpacity: 0.92
    }
  },
  {
    id: 'orbital-dusk',
    label: 'Orbital Dusk',
    description: 'Soft pastels like a breaking dawn. Gentle orange, red, and yellow glows.',
    preview: { bg: '#1a1520', accent: '#f97316', secondary: '#ec4899' },
    nativeMode: 'dark',
    config: {
      accentColor: '#f97316',
      secondaryAccent: '#ec4899',
      backgroundMode: 'gradient',
      backgroundPreset: 'orbital-dusk',
      backgroundColor: '#1a1520',
      backgroundGradientStart: '#1a1520',
      backgroundGradientEnd: '#201820',
      backgroundGradientAngle: 135,
      glassEnabled: true,
      glowEnabled: true,
      depthEnabled: true,
      scanlineEnabled: false,
      panelSurfacePreset: 'ember',
      terminalBackground: '#140f18',
      terminalForeground: '#e8dce8',
      terminalCursor: '#f97316',
      statusSuccess: '#a3e635',
      statusWarning: '#fbbf24',
      statusError: '#f87171',
      statusInfo: '#fb923c',
      drawerBackgroundColor: '#1e1820',
      drawerBackgroundOpacity: 0.85,
      drawerCardBackgroundColor: '#261e28',
      drawerBorderColor: '#f97316',
      inputBarBackgroundColor: '#1a1418',
      inputBarBorderColor: '#ec4899',
      toolCardBackgroundColor: '#1e1820',
      toolCardBorderColor: '#f97316',
      // Nixie tube colors
      nixieColor: '#f97316',
      nixieGlowColor: '#ea580c',
      nixieButtonBackgroundColor: '#1e1820',
      nixieExitColor: '#f87171',
      nixieExitGlowColor: '#ef4444',
      // Message bubbles
      userMessageBackgroundColor: '#261e28',
      userMessageBackgroundOpacity: 0.88,
      userMessageBorderColor: '#f97316',
      userMessageBorderOpacity: 0.25,
      userMessageBackgroundMode: 'glass',
      assistantMessageBackgroundColor: '#1e1820',
      assistantMessageBackgroundOpacity: 0.9,
      assistantMessageBorderColor: '#ec4899',
      assistantMessageBorderOpacity: 0.2,
      assistantMessageBackgroundMode: 'glass',
      // Header
      headerBackgroundColor: '#1a1520',
      headerBackgroundMode: 'transparent',
      // Sidebar
      sidebarBackgroundMode: 'glass',
      // Dialog content (orbital dusk dark pink)
      dialogContentBackgroundColor: '#261e28',
      dialogContentBackgroundOpacity: 0.9
    }
  },
  {
    id: 'minimal-solid',
    label: 'Minimal',
    description: 'Clean and understated. Gentle browns, greys, and soft whites.',
    preview: { bg: '#f5f3f0', accent: '#78716c', secondary: '#a8a29e' },
    nativeMode: 'light',
    config: {
      accentColor: '#78716c',
      secondaryAccent: '#a8a29e',
      backgroundMode: 'color',
      backgroundPreset: 'minimal',
      backgroundColor: '#f5f3f0',
      glassEnabled: false,
      glowEnabled: false,
      depthEnabled: true,
      scanlineEnabled: false,
      panelSurfacePreset: 'minimal',
      terminalBackground: '#292524',
      terminalForeground: '#e7e5e4',
      terminalCursor: '#78716c',
      statusSuccess: '#84cc16',
      statusWarning: '#ca8a04',
      statusError: '#dc2626',
      statusInfo: '#0284c7',
      drawerBackgroundColor: '#fafaf9',
      drawerBackgroundOpacity: 1.0,
      drawerCardBackgroundColor: '#ffffff',
      drawerBorderColor: '#d6d3d1',
      inputBarBackgroundColor: '#ffffff',
      inputBarBackgroundOpacity: 1.0,
      inputBarBorderColor: '#78716c',
      toolCardBackgroundColor: '#fafaf9',
      toolCardBackgroundOpacity: 1.0,
      toolCardBorderColor: '#d6d3d1',
      // Sidebar for light theme
      sidebarBackgroundColor: '#ffffff',
      sidebarBackgroundOpacity: 0.85,
      // Nixie tube colors
      nixieColor: '#78716c',
      nixieGlowColor: '#57534e',
      nixieButtonBackgroundColor: '#292524',
      nixieExitColor: '#dc2626',
      nixieExitGlowColor: '#b91c1c',
      // Message bubbles (light theme)
      userMessageBackgroundColor: '#ffffff',
      userMessageBackgroundOpacity: 1.0,
      userMessageBorderColor: '#78716c',
      userMessageBorderOpacity: 0.15,
      userMessageBackgroundMode: 'solid',
      assistantMessageBackgroundColor: '#fafaf9',
      assistantMessageBackgroundOpacity: 1.0,
      assistantMessageBorderColor: '#a8a29e',
      assistantMessageBorderOpacity: 0.12,
      assistantMessageBackgroundMode: 'solid',
      // Header
      headerBackgroundColor: '#ffffff',
      headerBackgroundMode: 'solid',
      // Sidebar
      sidebarBackgroundMode: 'solid',
      // Dialog content (minimal light)
      dialogContentBackgroundColor: '#ffffff',
      dialogContentBackgroundOpacity: 1.0
    }
  },
  {
    id: 'midnight',
    label: 'Midnight',
    description: 'Deep blues and purples of the night sky.',
    preview: { bg: '#0a0a1a', accent: '#3b82f6', secondary: '#a855f7' },
    nativeMode: 'dark',
    config: {
      accentColor: '#3b82f6',
      secondaryAccent: '#a855f7',
      backgroundMode: 'gradient',
      backgroundPreset: 'deep-space',
      backgroundColor: '#0a0a1a',
      backgroundGradientStart: '#0a0a1a',
      backgroundGradientEnd: '#141428',
      backgroundGradientAngle: 160,
      glassEnabled: true,
      glowEnabled: true,
      depthEnabled: true,
      scanlineEnabled: false,
      panelSurfacePreset: 'neon-drift',
      terminalBackground: '#080818',
      terminalForeground: '#c8d4f0',
      terminalCursor: '#3b82f6',
      statusSuccess: '#34d399',
      statusWarning: '#fbbf24',
      statusError: '#f87171',
      statusInfo: '#3b82f6',
      drawerBackgroundColor: '#0f0f20',
      drawerBackgroundOpacity: 0.88,
      drawerCardBackgroundColor: '#161628',
      drawerBorderColor: '#3b82f6',
      inputBarBackgroundColor: '#0c0c1a',
      inputBarBorderColor: '#a855f7',
      toolCardBackgroundColor: '#0f0f20',
      toolCardBorderColor: '#3b82f6',
      // Nixie tube colors
      nixieColor: '#3b82f6',
      nixieGlowColor: '#2563eb',
      nixieButtonBackgroundColor: '#0f0f20',
      nixieExitColor: '#f87171',
      nixieExitGlowColor: '#ef4444',
      // Message bubbles
      userMessageBackgroundColor: '#161628',
      userMessageBackgroundOpacity: 0.88,
      userMessageBorderColor: '#3b82f6',
      userMessageBorderOpacity: 0.25,
      userMessageBackgroundMode: 'glass',
      assistantMessageBackgroundColor: '#0f0f20',
      assistantMessageBackgroundOpacity: 0.9,
      assistantMessageBorderColor: '#a855f7',
      assistantMessageBorderOpacity: 0.2,
      assistantMessageBackgroundMode: 'glass',
      // Header
      headerBackgroundColor: '#0a0a1a',
      headerBackgroundMode: 'transparent',
      // Sidebar
      sidebarBackgroundMode: 'glass',
      // Dialog content (midnight dark blue)
      dialogContentBackgroundColor: '#161628',
      dialogContentBackgroundOpacity: 0.9
    }
  },
  {
    id: 'forest',
    label: 'Forest',
    description: 'Natural greens and earth tones of the deep woods.',
    preview: { bg: '#0f1a14', accent: '#22c55e', secondary: '#84cc16' },
    nativeMode: 'dark',
    config: {
      accentColor: '#22c55e',
      secondaryAccent: '#84cc16',
      backgroundMode: 'gradient',
      backgroundPreset: 'forest',
      backgroundColor: '#0f1a14',
      backgroundGradientStart: '#0f1a14',
      backgroundGradientEnd: '#1a2820',
      backgroundGradientAngle: 150,
      glassEnabled: true,
      glowEnabled: true,
      depthEnabled: true,
      scanlineEnabled: false,
      panelSurfacePreset: 'workstation',
      terminalBackground: '#0a1410',
      terminalForeground: '#d4e8d8',
      terminalCursor: '#22c55e',
      statusSuccess: '#22c55e',
      statusWarning: '#eab308',
      statusError: '#ef4444',
      statusInfo: '#06b6d4',
      drawerBackgroundColor: '#142018',
      drawerBackgroundOpacity: 0.85,
      drawerCardBackgroundColor: '#1a2820',
      drawerBorderColor: '#22c55e',
      inputBarBackgroundColor: '#101a14',
      inputBarBorderColor: '#84cc16',
      toolCardBackgroundColor: '#142018',
      toolCardBorderColor: '#22c55e',
      // Nixie tube colors
      nixieColor: '#22c55e',
      nixieGlowColor: '#16a34a',
      nixieButtonBackgroundColor: '#0a1410',
      nixieExitColor: '#ef4444',
      nixieExitGlowColor: '#dc2626',
      // Message bubbles
      userMessageBackgroundColor: '#1a2820',
      userMessageBackgroundOpacity: 0.88,
      userMessageBorderColor: '#22c55e',
      userMessageBorderOpacity: 0.25,
      userMessageBackgroundMode: 'glass',
      assistantMessageBackgroundColor: '#142018',
      assistantMessageBackgroundOpacity: 0.9,
      assistantMessageBorderColor: '#84cc16',
      assistantMessageBorderOpacity: 0.2,
      assistantMessageBackgroundMode: 'glass',
      // Header
      headerBackgroundColor: '#0f1a14',
      headerBackgroundMode: 'transparent',
      // Sidebar
      sidebarBackgroundMode: 'glass',
      // Dialog content (forest dark green)
      dialogContentBackgroundColor: '#1a2820',
      dialogContentBackgroundOpacity: 0.9
    }
  }
];

export const PANEL_SURFACE_PRESETS = [
  {
    id: 'workstation',
    label: 'Workstation',
    description: 'Crisp blue glass with balanced depth.',
    preview: {
      primary: DEFAULT_DRAWER_THEME.backgroundColor,
      secondary: DEFAULT_DRAWER_THEME.cardBackgroundColor,
      accent: DEFAULT_DRAWER_THEME.borderColor
    },
    values: {
      drawerBackgroundMode: 'glass',
      drawerBackgroundPreset: 'deep-space',
      drawerBackgroundColor: DEFAULT_DRAWER_THEME.backgroundColor,
      drawerBackgroundOpacity: DEFAULT_DRAWER_THEME.backgroundOpacity,
      drawerBorderColor: DEFAULT_DRAWER_THEME.borderColor,
      drawerBorderOpacity: DEFAULT_DRAWER_THEME.borderOpacity,
      drawerCardBackgroundMode: 'glass',
      drawerCardBackgroundColor: DEFAULT_DRAWER_THEME.cardBackgroundColor,
      drawerCardBackgroundOpacity: DEFAULT_DRAWER_THEME.cardBackgroundOpacity,
      codeEditorBackgroundColor: DEFAULT_CODE_EDITOR_THEME.backgroundColor,
      codeEditorBackgroundOpacity: DEFAULT_CODE_EDITOR_THEME.backgroundOpacity,
      terminalBackgroundColor: DEFAULT_TERMINAL_PANEL_THEME.backgroundColor,
      terminalBackgroundOpacity: DEFAULT_TERMINAL_PANEL_THEME.backgroundOpacity,
      terminalHeaderBackgroundColor: DEFAULT_TERMINAL_PANEL_THEME.headerBackgroundColor,
      terminalHeaderBackgroundOpacity: DEFAULT_TERMINAL_PANEL_THEME.headerBackgroundOpacity,
      fileBrowserBackgroundColor: DEFAULT_FILE_BROWSER_THEME.backgroundColor,
      fileBrowserBackgroundOpacity: DEFAULT_FILE_BROWSER_THEME.backgroundOpacity,
      dialogContentBackgroundColor: DEFAULT_DIALOG_CONTENT_THEME.backgroundColor,
      dialogContentBackgroundOpacity: DEFAULT_DIALOG_CONTENT_THEME.backgroundOpacity,
      cardBackgroundColor: DEFAULT_CARD_THEME.backgroundColor,
      cardBackgroundOpacity: DEFAULT_CARD_THEME.backgroundOpacity,
      filterButtonBackgroundColor: DEFAULT_FILTER_BUTTON_THEME.backgroundColor,
      filterButtonBackgroundOpacity: DEFAULT_FILTER_BUTTON_THEME.backgroundOpacity,
      filterButtonActiveBackgroundColor: DEFAULT_FILTER_BUTTON_THEME.activeBackgroundColor,
      filterButtonActiveBackgroundOpacity: DEFAULT_FILTER_BUTTON_THEME.activeBackgroundOpacity
    }
  },
  {
    id: 'minimal',
    label: 'Minimal',
    description: 'Low-contrast surfaces for focus.',
    preview: {
      primary: '#0f141d',
      secondary: '#121a24',
      accent: '#94a3b8'
    },
    values: {
      drawerBackgroundMode: 'glass',
      drawerBackgroundPreset: 'deep-space',
      drawerBackgroundColor: '#0f141d',
      drawerBackgroundOpacity: 0.6,
      drawerBorderColor: '#94a3b8',
      drawerBorderOpacity: 0.12,
      drawerCardBackgroundMode: 'glass',
      drawerCardBackgroundColor: '#121a24',
      drawerCardBackgroundOpacity: 0.45,
      codeEditorBackgroundColor: '#0c1119',
      codeEditorBackgroundOpacity: 0.9,
      terminalBackgroundColor: '#0b1018',
      terminalBackgroundOpacity: 0.7,
      terminalHeaderBackgroundColor: '#0e131a',
      terminalHeaderBackgroundOpacity: 0.6,
      fileBrowserBackgroundColor: '#121a24',
      fileBrowserBackgroundOpacity: 0.45,
      dialogContentBackgroundColor: '#121a24',
      dialogContentBackgroundOpacity: 0.4,
      cardBackgroundColor: '#121a24',
      cardBackgroundOpacity: 0.45,
      filterButtonBackgroundColor: '#121a24',
      filterButtonBackgroundOpacity: 0.35,
      filterButtonActiveBackgroundColor: '#94a3b8',
      filterButtonActiveBackgroundOpacity: 0.18
    }
  },
  {
    id: 'neon-drift',
    label: 'Neon Drift',
    description: 'Inky panels with teal energy.',
    preview: {
      primary: '#060814',
      secondary: '#10132a',
      accent: '#22d3ee'
    },
    values: {
      drawerBackgroundMode: 'glass-strong',
      drawerBackgroundPreset: 'orbital-dusk',
      drawerBackgroundColor: '#060814',
      drawerBackgroundOpacity: 0.8,
      drawerBorderColor: '#22d3ee',
      drawerBorderOpacity: 0.2,
      drawerCardBackgroundMode: 'glass',
      drawerCardBackgroundColor: '#10132a',
      drawerCardBackgroundOpacity: 0.55,
      codeEditorBackgroundColor: '#050712',
      codeEditorBackgroundOpacity: 0.92,
      terminalBackgroundColor: '#050812',
      terminalBackgroundOpacity: 0.85,
      terminalHeaderBackgroundColor: '#0b1230',
      terminalHeaderBackgroundOpacity: 0.7,
      fileBrowserBackgroundColor: '#10132a',
      fileBrowserBackgroundOpacity: 0.55,
      dialogContentBackgroundColor: '#10132a',
      dialogContentBackgroundOpacity: 0.5,
      cardBackgroundColor: '#10132a',
      cardBackgroundOpacity: 0.55,
      filterButtonBackgroundColor: '#10132a',
      filterButtonBackgroundOpacity: 0.45,
      filterButtonActiveBackgroundColor: '#22d3ee',
      filterButtonActiveBackgroundOpacity: 0.2
    }
  },
  {
    id: 'ember',
    label: 'Ember',
    description: 'Warm amber glow with soft depth.',
    preview: {
      primary: '#120a06',
      secondary: '#1a0f09',
      accent: '#f59e0b'
    },
    values: {
      drawerBackgroundMode: 'glass-strong',
      drawerBackgroundPreset: 'nixie-amber',
      drawerBackgroundColor: '#120a06',
      drawerBackgroundOpacity: 0.78,
      drawerBorderColor: '#f59e0b',
      drawerBorderOpacity: 0.2,
      drawerCardBackgroundMode: 'glass',
      drawerCardBackgroundColor: '#1a0f09',
      drawerCardBackgroundOpacity: 0.55,
      codeEditorBackgroundColor: '#0f0705',
      codeEditorBackgroundOpacity: 0.92,
      terminalBackgroundColor: '#100806',
      terminalBackgroundOpacity: 0.85,
      terminalHeaderBackgroundColor: '#1a0d08',
      terminalHeaderBackgroundOpacity: 0.7,
      fileBrowserBackgroundColor: '#1a0f09',
      fileBrowserBackgroundOpacity: 0.55,
      dialogContentBackgroundColor: '#1a0f09',
      dialogContentBackgroundOpacity: 0.5,
      cardBackgroundColor: '#1a0f09',
      cardBackgroundOpacity: 0.55,
      filterButtonBackgroundColor: '#1a0f09',
      filterButtonBackgroundOpacity: 0.45,
      filterButtonActiveBackgroundColor: '#f59e0b',
      filterButtonActiveBackgroundOpacity: 0.2
    }
  }
];
