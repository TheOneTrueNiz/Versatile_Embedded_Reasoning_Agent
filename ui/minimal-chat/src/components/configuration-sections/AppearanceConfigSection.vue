<template>
    <div class="appearance-panel">
        <!-- Premium Tab Bar with Floating Indicator -->
        <div class="appearance-tabs-container">
            <div class="appearance-tabs" ref="tabsRef">
                <button
                    :class="{ active: activeTab === 'theme' }"
                    @click="activeTab = 'theme'"
                    data-tab="theme"
                >
                    <Palette size="14" />
                    <span>Theme</span>
                </button>
                <button
                    :class="{ active: activeTab === 'typography' }"
                    @click="activeTab = 'typography'"
                    data-tab="typography"
                >
                    <Type size="14" />
                    <span>Type</span>
                </button>
                <button
                    :class="{ active: activeTab === 'effects' }"
                    @click="activeTab = 'effects'"
                    data-tab="effects"
                >
                    <Sparkles size="14" />
                    <span>Effects</span>
                </button>
                <button
                    :class="{ active: activeTab === 'animations' }"
                    @click="activeTab = 'animations'"
                    data-tab="animations"
                >
                    <Activity size="14" />
                    <span>Motion</span>
                </button>
                <button
                    :class="{ active: activeTab === 'avatar' }"
                    @click="activeTab = 'avatar'"
                    data-tab="avatar"
                >
                    <User size="14" />
                    <span>Avatar</span>
                </button>
                <!-- Floating indicator that slides to active tab -->
                <div class="tab-indicator" :style="tabIndicatorStyle"></div>
            </div>
        </div>
        <div v-show="activeTab === 'theme'" class="appearance-section">
        <div class="config-section" :class="{ show: isThemeConfigOpen }">
            <div class="section-header" @click="isThemeConfigOpen = !isThemeConfigOpen">
                <h3>
                    <Palette size="20" class="section-icon" />
                    UI Theme
                </h3>
                <ChevronDown v-if="isThemeConfigOpen" class="indicator" size="20" />
                <ChevronRight v-else class="indicator" size="20" />
            </div>
            <transition name="slide-fade">
                                <div v-show="isThemeConfigOpen" class="theme-content">
                    <div class="theme-subtabs-container">
                        <div class="theme-subtabs" ref="themeTabsRef">
                            <button
                                :class="{ active: activeThemeTab === 'foundations' }"
                                @click="activeThemeTab = 'foundations'"
                                data-tab="foundations"
                            >
                                <span>Foundations</span>
                            </button>
                            <button
                                :class="{ active: activeThemeTab === 'backgrounds' }"
                                @click="activeThemeTab = 'backgrounds'"
                                data-tab="backgrounds"
                            >
                                <span>Backgrounds</span>
                            </button>
                            <button
                                :class="{ active: activeThemeTab === 'chat' }"
                                @click="activeThemeTab = 'chat'"
                                data-tab="chat"
                            >
                                <span>Chat UI</span>
                            </button>
                            <button
                                :class="{ active: activeThemeTab === 'panels' }"
                                @click="activeThemeTab = 'panels'"
                                data-tab="panels"
                            >
                                <span>Panels</span>
                            </button>
                            <button
                                :class="{ active: activeThemeTab === 'signals' }"
                                @click="activeThemeTab = 'signals'"
                                data-tab="signals"
                            >
                                <span>Signals</span>
                            </button>
                            <button
                                :class="{ active: activeThemeTab === 'advanced' }"
                                @click="activeThemeTab = 'advanced'"
                                data-tab="advanced"
                            >
                                <span>Advanced</span>
                            </button>
                            <div class="tab-indicator" :style="themeTabIndicatorStyle"></div>
                        </div>
                    </div>

                    <div v-show="activeThemeTab === 'foundations'" class="theme-tab-panel">
                        <div class="theme-group global-theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Quick Theme</div>
                                <p class="theme-hint">One-click complete theme transformation.</p>
                            </div>
                            <div class="global-theme-selector">
                                <div class="global-theme-dropdown">
                                    <select
                                        v-model="selectedGlobalTheme"
                                        class="global-theme-select"
                                        @change="applyGlobalThemePreset"
                                    >
                                        <option value="">Select a theme...</option>
                                        <option
                                            v-for="preset in globalThemePresets"
                                            :key="preset.id"
                                            :value="preset.id"
                                        >
                                            {{ preset.label }}
                                        </option>
                                    </select>
                                </div>
                                <p v-if="selectedGlobalThemePreset" class="global-theme-description">
                                    {{ selectedGlobalThemePreset.description }}
                                </p>
                            </div>
                            <div class="global-theme-grid">
                                <button
                                    v-for="preset in globalThemePresets"
                                    :key="preset.id"
                                    type="button"
                                    class="global-theme-card"
                                    :class="{ active: selectedGlobalTheme === preset.id }"
                                    @click="selectAndApplyGlobalTheme(preset.id)"
                                >
                                    <div class="global-theme-preview">
                                        <div class="preview-bg" :style="{ background: preset.preview.bg }"></div>
                                        <div class="preview-accent" :style="{ background: preset.preview.accent }"></div>
                                        <div class="preview-secondary" :style="{ background: preset.preview.secondary }"></div>
                                    </div>
                                    <div class="global-theme-label">{{ preset.label }}</div>
                                </button>
                            </div>
                        </div>

                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Theme Core</div>
                                <p class="theme-hint">Base palette, density, and rounding.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Mode</h4>
                                <SelectButton
                                    v-model="uiThemeMode"
                                    :options="themeModeOptions"
                                    optionLabel="label"
                                    optionValue="value"
                                    class="theme-selector"
                                    @update:modelValue="handleThemeModeChange"
                                />
                                <p class="theme-hint">System follows your OS preference. Custom applies theme colors directly.</p>
                            </div>
                            <!-- Custom Mode Controls - panel surfaces that shift during dark/light -->
                            <div v-if="uiThemeMode === 'custom'" class="theme-custom-panel">
                                <div class="theme-row">
                                    <h4>Panel Surfaces</h4>
                                    <select
                                        :value="activePanelPresetId"
                                        class="global-theme-select"
                                        @change="e => { const p = panelSurfacePresets.find(ps => ps.id === e.target.value); if (p) applyPanelSurfacePreset(p); }"
                                    >
                                        <option value="" disabled>Select a preset…</option>
                                        <option v-for="ps in panelSurfacePresets" :key="ps.id" :value="ps.id">
                                            {{ ps.label }}
                                        </option>
                                    </select>
                                    <p class="theme-hint">Preset for drawer, card, and dialog surfaces.</p>
                                </div>
                                <div class="theme-row">
                                    <h4>Surface Color</h4>
                                    <div class="accent-controls">
                                        <input
                                            v-model="uiDrawerBackgroundColor"
                                            type="color"
                                            class="accent-picker"
                                            aria-label="Surface color"
                                        />
                                        <span class="theme-value">{{ uiDrawerBackgroundColor }}</span>
                                    </div>
                                    <p class="theme-hint">Primary color for panels, drawers, and dialogs.</p>
                                </div>
                            </div>
                            <div class="theme-row">
                                <h4>Preset</h4>
                                <div class="theme-preset-controls">
                                    <SelectButton
                                        v-model="uiThemePreset"
                                        :options="themePresetOptions"
                                        optionLabel="label"
                                        optionValue="value"
                                        class="theme-selector"
                                    />
                                    <button class="clear-prompt-button" @click="resetThemePreset">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <p class="theme-hint">Switches the base palette without affecting your accent color.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Reset Theme</h4>
                                <button class="clear-prompt-button" @click="resetAllTheme">
                                    <RotateCcw size="16" />
                                    <span>Reset All</span>
                                </button>
                                <p class="theme-hint">Restores mode, preset, and accent to defaults.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Corner Roundness</h4>
                                <SelectButton
                                    v-model="uiBorderRadius"
                                    :options="borderRadiusOptions"
                                    optionLabel="label"
                                    optionValue="value"
                                    class="theme-selector"
                                />
                                <p class="theme-hint">Controls corner rounding across the interface.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Compact Mode</h4>
                                <SliderCheckbox inputId="compact-mode" labelText="Reduce spacing for information density"
                                    v-model="uiCompactMode" />
                            </div>
                        </div>
                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Accents</div>
                                <p class="theme-hint">Primary and secondary accents across the UI.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Accent Color</h4>
                                <div class="accent-controls">
                                    <input
                                        v-model="uiAccentColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Accent color"
                                    />
                                    <div class="accent-swatches">
                                        <button
                                            v-for="swatch in accentSwatches"
                                            :key="swatch.value"
                                            class="accent-swatch"
                                            :class="{ active: uiAccentColor === swatch.value }"
                                            :title="swatch.label"
                                            @click="setAccentColor(swatch.value)"
                                        >
                                            <span :style="{ backgroundColor: swatch.value }"></span>
                                        </button>
                                    </div>
                                    <button class="clear-prompt-button" @click="resetAccentColor">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <p class="theme-hint">Applies instantly across the interface.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Secondary Accent</h4>
                                <div class="accent-controls">
                                    <input
                                        v-model="uiSecondaryAccent"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Secondary accent color"
                                    />
                                    <div class="accent-swatches">
                                        <button
                                            v-for="swatch in secondarySwatches"
                                            :key="swatch.value"
                                            class="accent-swatch"
                                            :class="{ active: uiSecondaryAccent === swatch.value }"
                                            :title="swatch.label"
                                            @click="uiSecondaryAccent = swatch.value"
                                        >
                                            <span :style="{ backgroundColor: swatch.value }"></span>
                                        </button>
                                    </div>
                                    <button class="clear-prompt-button" @click="uiSecondaryAccent = DEFAULT_SECONDARY_ACCENT">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <p class="theme-hint">Used for highlights, routing events, and violet accents.</p>
                            </div>
                        </div>
                    </div>

                    <div v-show="activeThemeTab === 'backgrounds'" class="theme-tab-panel">
                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">App Background</div>
                                <p class="theme-hint">Backdrop for the main chat area.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Background</h4>
                                <SelectButton
                                    v-model="uiBackgroundMode"
                                    :options="backgroundModeOptions"
                                    optionLabel="label"
                                    optionValue="value"
                                    class="theme-selector"
                                />
                                <p class="theme-hint">Choose a preset, color, gradient, or image.</p>
                            </div>
                            <div v-if="uiBackgroundMode === 'preset'" class="theme-row">
                                <h4>Background Preset</h4>
                                <SelectButton
                                    v-model="uiBackgroundPreset"
                                    :options="backgroundPresetOptions"
                                    optionLabel="label"
                                    optionValue="value"
                                    class="theme-selector"
                                />
                                <p class="theme-hint">Quickly swap the app backdrop.</p>
                            </div>
                            <div v-if="uiBackgroundMode === 'color'" class="theme-row">
                                <h4>Background Color</h4>
                                <div class="accent-controls">
                                    <input
                                        v-model="uiBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Background color"
                                    />
                                    <button class="clear-prompt-button" @click="uiBackgroundColor = DEFAULT_THEME_RESET.backgroundColor">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <p class="theme-hint">Sets a flat backdrop for the app.</p>
                            </div>
                            <div v-if="uiBackgroundMode === 'gradient'" class="theme-row">
                                <h4>Gradient</h4>
                                <div class="theme-preset-controls">
                                    <input
                                        v-model="uiBackgroundGradientStart"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Gradient start color"
                                    />
                                    <input
                                        v-model="uiBackgroundGradientEnd"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Gradient end color"
                                    />
                                    <button class="clear-prompt-button" @click="uiBackgroundGradientAngle = 135">
                                        <RotateCcw size="16" />
                                        <span>Angle</span>
                                    </button>
                                </div>
                                <div class="theme-preset-controls">
                                    <input
                                        v-model.number="uiBackgroundGradientAngle"
                                        type="range"
                                        min="0"
                                        max="360"
                                        class="range-slider"
                                        aria-label="Gradient angle"
                                    />
                                    <span class="theme-value">{{ uiBackgroundGradientAngle }}°</span>
                                </div>
                                <p class="theme-hint">Custom linear gradient for the app.</p>
                            </div>
                            <div v-if="uiBackgroundMode === 'image'" class="theme-row">
                                <h4>Background Image</h4>
                                <div class="theme-preset-controls">
                                    <input
                                        type="file"
                                        accept="image/*"
                                        @change="handleBackgroundImage"
                                        class="file-input"
                                    />
                                    <button class="clear-prompt-button" :disabled="!uiBackgroundImage" @click="clearBackgroundImage">
                                        <RotateCcw size="16" />
                                        <span>Remove</span>
                                    </button>
                                </div>
                                <div class="theme-preset-controls">
                                    <input
                                        v-model.number="uiBackgroundImageOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Background image opacity"
                                    />
                                    <span class="theme-value">{{ uiBackgroundImageOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <input
                                        v-model.number="uiBackgroundImageBlur"
                                        type="range"
                                        min="0"
                                        max="20"
                                        step="1"
                                        class="range-slider"
                                        aria-label="Background image blur"
                                    />
                                    <span class="theme-value">{{ uiBackgroundImageBlur }}px</span>
                                </div>
                                <p class="theme-hint">Images are stored locally in your browser.</p>
                            </div>
                        </div>
                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Sidebar Backgrounds</div>
                                <p class="theme-hint">Style left and right rails.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Sidebar Background</h4>
                                <SelectButton
                                    v-model="uiSidebarBackgroundMode"
                                    :options="sidebarBackgroundModeOptions"
                                    optionLabel="label"
                                    optionValue="value"
                                    class="theme-selector"
                                />
                                <p class="theme-hint">Choose how sidebars are rendered.</p>
                            </div>
                            <div v-if="uiSidebarBackgroundMode === 'preset'" class="theme-row">
                                <h4>Sidebar Preset</h4>
                                <SelectButton
                                    v-model="uiSidebarBackgroundPreset"
                                    :options="backgroundPresetOptions"
                                    optionLabel="label"
                                    optionValue="value"
                                    class="theme-selector"
                                />
                                <p class="theme-hint">Uses the same preset library as the app.</p>
                            </div>
                            <div v-if="uiSidebarBackgroundMode === 'color'" class="theme-row">
                                <h4>Sidebar Color</h4>
                                <div class="accent-controls">
                                    <input
                                        v-model="uiSidebarBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Sidebar background color"
                                    />
                                    <button class="clear-prompt-button" @click="uiSidebarBackgroundColor = DEFAULT_THEME_RESET.sidebarBackgroundColor">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                            </div>
                            <div v-if="uiSidebarBackgroundMode === 'gradient'" class="theme-row">
                                <h4>Sidebar Gradient</h4>
                                <div class="theme-preset-controls">
                                    <input
                                        v-model="uiSidebarBackgroundGradientStart"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Sidebar gradient start color"
                                    />
                                    <input
                                        v-model="uiSidebarBackgroundGradientEnd"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Sidebar gradient end color"
                                    />
                                    <button class="clear-prompt-button" @click="uiSidebarBackgroundGradientAngle = 135">
                                        <RotateCcw size="16" />
                                        <span>Angle</span>
                                    </button>
                                </div>
                                <div class="theme-preset-controls">
                                    <input
                                        v-model.number="uiSidebarBackgroundGradientAngle"
                                        type="range"
                                        min="0"
                                        max="360"
                                        class="range-slider"
                                        aria-label="Sidebar gradient angle"
                                    />
                                    <span class="theme-value">{{ uiSidebarBackgroundGradientAngle }}°</span>
                                </div>
                            </div>
                            <div v-if="uiSidebarBackgroundMode === 'image'" class="theme-row">
                                <h4>Sidebar Image</h4>
                                <div class="theme-preset-controls">
                                    <input
                                        type="file"
                                        accept="image/*"
                                        @change="handleSidebarBackgroundImage"
                                        class="file-input"
                                    />
                                    <button class="clear-prompt-button" :disabled="!uiSidebarBackgroundImage" @click="clearSidebarBackgroundImage">
                                        <RotateCcw size="16" />
                                        <span>Remove</span>
                                    </button>
                                </div>
                                <div class="theme-preset-controls">
                                    <input
                                        v-model.number="uiSidebarBackgroundImageOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Sidebar image opacity"
                                    />
                                    <span class="theme-value">{{ uiSidebarBackgroundImageOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <input
                                        v-model.number="uiSidebarBackgroundImageBlur"
                                        type="range"
                                        min="0"
                                        max="20"
                                        step="1"
                                        class="range-slider"
                                        aria-label="Sidebar image blur"
                                    />
                                    <span class="theme-value">{{ uiSidebarBackgroundImageBlur }}px</span>
                                </div>
                                <p class="theme-hint">Sidebar images are stored locally.</p>
                            </div>
                        </div>
                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Independent Images</div>
                                <p class="theme-hint">Set unique images per area.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Independent Backgrounds</h4>
                                <SliderCheckbox inputId="background-independent" labelText="Enable per-area backgrounds"
                                    v-model="uiBackgroundIndependent" />
                                <p class="theme-hint">Set different images for each area instead of global sidebar image.</p>
                            </div>
                            <div v-if="uiBackgroundIndependent" class="theme-row independent-bg-section">
                                <h4>Left Sidebar Image</h4>
                                <div class="theme-preset-controls">
                                    <input
                                        type="file"
                                        accept="image/*"
                                        @change="handleLeftSidebarBackgroundImage"
                                        class="file-input"
                                    />
                                    <button class="clear-prompt-button" :disabled="!uiLeftSidebarBackgroundImage" @click="clearLeftSidebarBackgroundImage">
                                        <RotateCcw size="16" />
                                    </button>
                                </div>
                                <div class="theme-preset-controls">
                                    <input v-model.number="uiLeftSidebarBackgroundImageOpacity" type="range" min="0" max="1" step="0.05" class="range-slider" />
                                    <span class="theme-value">{{ uiLeftSidebarBackgroundImageOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <input v-model.number="uiLeftSidebarBackgroundImageBlur" type="range" min="0" max="20" step="1" class="range-slider" />
                                    <span class="theme-value">{{ uiLeftSidebarBackgroundImageBlur }}px</span>
                                </div>
                            </div>
                            <div v-if="uiBackgroundIndependent" class="theme-row independent-bg-section">
                                <h4>Right Sidebar Image</h4>
                                <div class="theme-preset-controls">
                                    <input
                                        type="file"
                                        accept="image/*"
                                        @change="handleRightSidebarBackgroundImage"
                                        class="file-input"
                                    />
                                    <button class="clear-prompt-button" :disabled="!uiRightSidebarBackgroundImage" @click="clearRightSidebarBackgroundImage">
                                        <RotateCcw size="16" />
                                    </button>
                                </div>
                                <div class="theme-preset-controls">
                                    <input v-model.number="uiRightSidebarBackgroundImageOpacity" type="range" min="0" max="1" step="0.05" class="range-slider" />
                                    <span class="theme-value">{{ uiRightSidebarBackgroundImageOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <input v-model.number="uiRightSidebarBackgroundImageBlur" type="range" min="0" max="20" step="1" class="range-slider" />
                                    <span class="theme-value">{{ uiRightSidebarBackgroundImageBlur }}px</span>
                                </div>
                            </div>
                            <div v-if="uiBackgroundIndependent" class="theme-row independent-bg-section">
                                <h4>Header Image</h4>
                                <div class="theme-preset-controls">
                                    <input
                                        type="file"
                                        accept="image/*"
                                        @change="handleHeaderBackgroundImage"
                                        class="file-input"
                                    />
                                    <button class="clear-prompt-button" :disabled="!uiHeaderBackgroundImage" @click="clearHeaderBackgroundImage">
                                        <RotateCcw size="16" />
                                    </button>
                                </div>
                                <div class="theme-preset-controls">
                                    <input v-model.number="uiHeaderBackgroundImageOpacity" type="range" min="0" max="1" step="0.05" class="range-slider" />
                                    <span class="theme-value">{{ uiHeaderBackgroundImageOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <input v-model.number="uiHeaderBackgroundImageBlur" type="range" min="0" max="20" step="1" class="range-slider" />
                                    <span class="theme-value">{{ uiHeaderBackgroundImageBlur }}px</span>
                                </div>
                            </div>
                            <div v-if="uiBackgroundIndependent" class="theme-row independent-bg-section">
                                <h4>Chat Area Image</h4>
                                <div class="theme-preset-controls">
                                    <input
                                        type="file"
                                        accept="image/*"
                                        @change="handleChatBackgroundImage"
                                        class="file-input"
                                    />
                                    <button class="clear-prompt-button" :disabled="!uiChatBackgroundImage" @click="clearChatBackgroundImage">
                                        <RotateCcw size="16" />
                                    </button>
                                </div>
                                <div class="theme-preset-controls">
                                    <input v-model.number="uiChatBackgroundImageOpacity" type="range" min="0" max="1" step="0.05" class="range-slider" />
                                    <span class="theme-value">{{ uiChatBackgroundImageOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <input v-model.number="uiChatBackgroundImageBlur" type="range" min="0" max="20" step="1" class="range-slider" />
                                    <span class="theme-value">{{ uiChatBackgroundImageBlur }}px</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div v-show="activeThemeTab === 'chat'" class="theme-tab-panel">
                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Header & Input</div>
                            </div>
                            <div class="theme-row">
                                <h4>Header</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <select v-model="uiHeaderBackgroundMode" class="theme-select">
                                        <option value="transparent">Transparent</option>
                                        <option value="glass">Glass (Light)</option>
                                        <option value="glass-strong">Glass (Strong)</option>
                                        <option value="preset">Preset</option>
                                        <option value="solid">Solid Color</option>
                                        <option value="image">Image</option>
                                    </select>
                                    <button class="clear-prompt-button" @click="resetHeaderTheme">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <div v-if="uiHeaderBackgroundMode === 'preset'" class="theme-preset-controls">
                                    <label class="theme-label">Preset</label>
                                    <select v-model="uiHeaderBackgroundPreset" class="theme-select">
                                        <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                    </select>
                                </div>
                                <div v-if="uiHeaderBackgroundMode === 'solid'" class="theme-preset-controls">
                                    <label class="theme-label">Color</label>
                                    <input
                                        v-model="uiHeaderBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Header background color"
                                    />
                                </div>
                                <div v-if="uiHeaderBackgroundMode === 'image'" class="theme-preset-controls">
                                    <label class="theme-label">Image</label>
                                    <input
                                        type="file"
                                        accept="image/*"
                                        @change="handleHeaderBackgroundImage"
                                        class="file-input"
                                    />
                                    <button class="clear-prompt-button" :disabled="!uiHeaderBackgroundImage" @click="clearHeaderBackgroundImage">
                                        <RotateCcw size="16" />
                                    </button>
                                </div>
                                <div v-if="uiHeaderBackgroundMode === 'image' && uiHeaderBackgroundImage" class="theme-preset-controls">
                                    <label class="theme-label">Opacity</label>
                                    <input v-model.number="uiHeaderBackgroundImageOpacity" type="range" min="0" max="1" step="0.05" class="range-slider" />
                                    <span class="theme-value">{{ uiHeaderBackgroundImageOpacity.toFixed(2) }}</span>
                                </div>
                                <div v-if="uiHeaderBackgroundMode === 'image' && uiHeaderBackgroundImage" class="theme-preset-controls">
                                    <label class="theme-label">Blur</label>
                                    <input v-model.number="uiHeaderBackgroundImageBlur" type="range" min="0" max="20" step="1" class="range-slider" />
                                    <span class="theme-value">{{ uiHeaderBackgroundImageBlur }}px</span>
                                </div>
                            </div>

                            <div class="theme-row">
                                <h4>Input Bar</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <select v-model="uiInputBarBackgroundMode" class="theme-select">
                                        <option value="transparent">Transparent</option>
                                        <option value="glass">Glass (Light)</option>
                                        <option value="glass-strong">Glass (Strong)</option>
                                        <option value="preset">Preset</option>
                                        <option value="solid">Solid Color</option>
                                        <option value="custom">Custom Opacity</option>
                                    </select>
                                    <button class="clear-prompt-button" @click="resetInputBarTheme">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <div v-if="uiInputBarBackgroundMode === 'preset'" class="theme-preset-controls">
                                    <label class="theme-label">Preset</label>
                                    <select v-model="uiInputBarBackgroundPreset" class="theme-select">
                                        <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                    </select>
                                </div>
                                <div v-if="uiInputBarBackgroundMode === 'solid' || uiInputBarBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Colors</label>
                                    <input
                                        v-model="uiInputBarBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Input bar background color"
                                    />
                                    <input
                                        v-model="uiInputBarBorderColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Input bar border color"
                                    />
                                </div>
                                <div v-if="uiInputBarBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Opacity</label>
                                    <input
                                        v-model.number="uiInputBarBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Input bar background opacity"
                                    />
                                    <span class="theme-value">{{ uiInputBarBackgroundOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Border</label>
                                    <input
                                        v-model="uiInputBarBorderColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Input bar border color"
                                    />
                                    <input
                                        v-model.number="uiInputBarBorderOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Input bar border opacity"
                                    />
                                    <span class="theme-value">{{ uiInputBarBorderOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Glow</label>
                                    <input
                                        v-model.number="uiInputBarGlow"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Input bar glow intensity"
                                    />
                                    <span class="theme-value">{{ uiInputBarGlow.toFixed(2) }}</span>
                                </div>
                            </div>
                        </div>

                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Messages</div>
                            </div>
                            <div class="theme-row">
                                <h4>User Messages</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <select v-model="uiUserMessageBackgroundMode" class="theme-select">
                                        <option value="transparent">Transparent</option>
                                        <option value="glass">Glass (Light)</option>
                                        <option value="glass-strong">Glass (Strong)</option>
                                        <option value="preset">Preset</option>
                                        <option value="solid">Solid Color</option>
                                        <option value="custom">Custom Opacity</option>
                                    </select>
                                    <button class="clear-prompt-button" @click="resetUserMessageTheme">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <div v-if="uiUserMessageBackgroundMode === 'preset'" class="theme-preset-controls">
                                    <label class="theme-label">Preset</label>
                                    <select v-model="uiUserMessageBackgroundPreset" class="theme-select">
                                        <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                    </select>
                                </div>
                                <div v-if="uiUserMessageBackgroundMode === 'solid' || uiUserMessageBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Color</label>
                                    <input
                                        v-model="uiUserMessageBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="User message background color"
                                    />
                                </div>
                                <div v-if="uiUserMessageBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Opacity</label>
                                    <input
                                        v-model.number="uiUserMessageBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="User message background opacity"
                                    />
                                    <span class="theme-value">{{ uiUserMessageBackgroundOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Border</label>
                                    <input
                                        v-model="uiUserMessageBorderColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="User message border color"
                                    />
                                    <input
                                        v-model.number="uiUserMessageBorderOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="User message border opacity"
                                    />
                                    <span class="theme-value">{{ uiUserMessageBorderOpacity.toFixed(2) }}</span>
                                </div>
                            </div>

                            <div class="theme-row">
                                <h4>Assistant Messages</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <select v-model="uiAssistantMessageBackgroundMode" class="theme-select">
                                        <option value="transparent">Transparent</option>
                                        <option value="glass">Glass (Light)</option>
                                        <option value="glass-strong">Glass (Strong)</option>
                                        <option value="preset">Preset</option>
                                        <option value="solid">Solid Color</option>
                                        <option value="custom">Custom Opacity</option>
                                    </select>
                                    <button class="clear-prompt-button" @click="resetAssistantMessageTheme">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <div v-if="uiAssistantMessageBackgroundMode === 'preset'" class="theme-preset-controls">
                                    <label class="theme-label">Preset</label>
                                    <select v-model="uiAssistantMessageBackgroundPreset" class="theme-select">
                                        <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                    </select>
                                </div>
                                <div v-if="uiAssistantMessageBackgroundMode === 'solid' || uiAssistantMessageBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Color</label>
                                    <input
                                        v-model="uiAssistantMessageBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Assistant message background color"
                                    />
                                </div>
                                <div v-if="uiAssistantMessageBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Opacity</label>
                                    <input
                                        v-model.number="uiAssistantMessageBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Assistant message background opacity"
                                    />
                                    <span class="theme-value">{{ uiAssistantMessageBackgroundOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Border</label>
                                    <input
                                        v-model="uiAssistantMessageBorderColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Assistant message border color"
                                    />
                                    <input
                                        v-model.number="uiAssistantMessageBorderOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Assistant message border opacity"
                                    />
                                    <span class="theme-value">{{ uiAssistantMessageBorderOpacity.toFixed(2) }}</span>
                                </div>
                            </div>
                        </div>

                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Send Button</div>
                            </div>
                            <div class="theme-row">
                                <h4>Send Button</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Colors</label>
                                    <input
                                        v-model="uiSendButtonBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Send button background color"
                                    />
                                    <input
                                        v-model="uiSendButtonTextColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Send button text color"
                                    />
                                    <button class="clear-prompt-button" @click="resetSendButtonTheme">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Glow</label>
                                    <input
                                        v-model.number="uiSendButtonGlow"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Send button glow intensity"
                                    />
                                    <span class="theme-value">{{ uiSendButtonGlow.toFixed(2) }}</span>
                                </div>
                            </div>
                        </div>

                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Thinking Dropdown</div>
                            </div>
                            <div class="theme-row">
                                <h4>Thinking Events</h4>
                                <p class="theme-hint">Colors for different event types in the thinking dropdown.</p>
                                <div class="event-colors-grid">
                                    <div class="event-color-item">
                                        <input
                                            v-model="uiEventColorRouting"
                                            type="color"
                                            class="event-color-picker"
                                            aria-label="Routing event color"
                                        />
                                        <span class="event-color-label">Routing</span>
                                    </div>
                                    <div class="event-color-item">
                                        <input
                                            v-model="uiEventColorMemory"
                                            type="color"
                                            class="event-color-picker"
                                            aria-label="Memory event color"
                                        />
                                        <span class="event-color-label">Memory</span>
                                    </div>
                                    <div class="event-color-item">
                                        <input
                                            v-model="uiEventColorTool"
                                            type="color"
                                            class="event-color-picker"
                                            aria-label="Tool event color"
                                        />
                                        <span class="event-color-label">Tool</span>
                                    </div>
                                    <div class="event-color-item">
                                        <input
                                            v-model="uiEventColorDecision"
                                            type="color"
                                            class="event-color-picker"
                                            aria-label="Decision event color"
                                        />
                                        <span class="event-color-label">Decision</span>
                                    </div>
                                    <div class="event-color-item">
                                        <input
                                            v-model="uiEventColorQuorum"
                                            type="color"
                                            class="event-color-picker"
                                            aria-label="Quorum event color"
                                        />
                                        <span class="event-color-label">Quorum</span>
                                    </div>
                                    <div class="event-color-item">
                                        <input
                                            v-model="uiEventColorError"
                                            type="color"
                                            class="event-color-picker"
                                            aria-label="Error event color"
                                        />
                                        <span class="event-color-label">Error</span>
                                    </div>
                                </div>
                                <button class="clear-prompt-button" @click="resetEventColors" style="margin-top: 12px;">
                                    <RotateCcw size="16" />
                                    <span>Reset All</span>
                                </button>
                            </div>

                            <div class="theme-row">
                                <h4>Thinking Dropdown</h4>
                                <p class="theme-hint">Style the thinking dropdown header and expanded content.</p>

                                <div class="subsection-header">Header (Idle State)</div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <select v-model="uiThinkingHeaderBackgroundMode" class="theme-select">
                                        <option value="glass">Glass (Light)</option>
                                        <option value="glass-strong">Glass (Strong)</option>
                                        <option value="preset">Preset</option>
                                        <option value="solid">Solid Color</option>
                                        <option value="custom">Custom Opacity</option>
                                    </select>
                                    <button class="clear-prompt-button" @click="resetThinkingDropdownTheme">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <div v-if="uiThinkingHeaderBackgroundMode === 'preset'" class="theme-preset-controls">
                                    <label class="theme-label">Preset</label>
                                    <select v-model="uiThinkingHeaderBackgroundPreset" class="theme-select">
                                        <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                    </select>
                                </div>
                                <div v-if="uiThinkingHeaderBackgroundMode === 'solid' || uiThinkingHeaderBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Color</label>
                                    <input
                                        v-model="uiThinkingHeaderBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Thinking header background color"
                                    />
                                </div>
                                <div v-if="uiThinkingHeaderBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Opacity</label>
                                    <input
                                        v-model.number="uiThinkingHeaderBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Thinking header background opacity"
                                    />
                                    <span class="theme-value">{{ uiThinkingHeaderBackgroundOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Border</label>
                                    <input
                                        v-model="uiThinkingHeaderBorderColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Thinking header border color"
                                    />
                                    <input
                                        v-model.number="uiThinkingHeaderBorderOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Thinking header border opacity"
                                    />
                                    <span class="theme-value">{{ uiThinkingHeaderBorderOpacity.toFixed(2) }}</span>
                                </div>

                                <div class="subsection-header">Content (Expanded)</div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <select v-model="uiThinkingContentBackgroundMode" class="theme-select">
                                        <option value="glass">Glass (Light)</option>
                                        <option value="glass-strong">Glass (Strong)</option>
                                        <option value="preset">Preset</option>
                                        <option value="solid">Solid Color</option>
                                        <option value="custom">Custom Opacity</option>
                                    </select>
                                </div>
                                <div v-if="uiThinkingContentBackgroundMode === 'preset'" class="theme-preset-controls">
                                    <label class="theme-label">Preset</label>
                                    <select v-model="uiThinkingContentBackgroundPreset" class="theme-select">
                                        <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                    </select>
                                </div>
                                <div v-if="uiThinkingContentBackgroundMode === 'solid' || uiThinkingContentBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Color</label>
                                    <input
                                        v-model="uiThinkingContentBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Thinking content background color"
                                    />
                                </div>
                                <div v-if="uiThinkingContentBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Opacity</label>
                                    <input
                                        v-model.number="uiThinkingContentBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Thinking content background opacity"
                                    />
                                    <span class="theme-value">{{ uiThinkingContentBackgroundOpacity.toFixed(2) }}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div v-show="activeThemeTab === 'panels'" class="theme-tab-panel">
                        <div class="theme-subtabs-container">
                            <div class="theme-subtabs theme-subtabs--compact" ref="panelTabsRef">
                                <button
                                    :class="{ active: activePanelTab === 'shared' }"
                                    @click="activePanelTab = 'shared'"
                                    data-tab="shared"
                                >
                                    <span>Shared</span>
                                </button>
                                <button
                                    :class="{ active: activePanelTab === 'canvas' }"
                                    @click="activePanelTab = 'canvas'"
                                    data-tab="canvas"
                                >
                                    <span>Canvas & Terminal</span>
                                </button>
                                <button
                                    :class="{ active: activePanelTab === 'tools' }"
                                    @click="activePanelTab = 'tools'"
                                    data-tab="tools"
                                >
                                    <span>Tools Panel</span>
                                </button>
                                <button
                                    :class="{ active: activePanelTab === 'config' }"
                                    @click="activePanelTab = 'config'"
                                    data-tab="config"
                                >
                                    <span>Configuration</span>
                                </button>
                                <button
                                    :class="{ active: activePanelTab === 'files' }"
                                    @click="activePanelTab = 'files'"
                                    data-tab="files"
                                >
                                    <span>File Browser</span>
                                </button>
                                <div class="tab-indicator" :style="panelTabIndicatorStyle"></div>
                            </div>
                        </div>

                        <div v-show="activePanelTab === 'shared'" class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Shared Surfaces</div>
                                <p class="theme-hint">Tune surface backgrounds for drawers, panels, and utility cards.</p>
                            </div>
                            <div class="theme-row">
                                <div class="subsection-header">Panel Presets</div>
                                <div class="panel-presets-grid">
                                    <button
                                        v-for="preset in panelSurfacePresets"
                                        :key="preset.id"
                                        type="button"
                                        class="panel-preset-card"
                                        :class="{ active: activePanelPresetId === preset.id }"
                                        @click="applyPanelSurfacePreset(preset)"
                                    >
                                        <div class="panel-preset-preview" :style="panelPresetPreviewStyle(preset)"></div>
                                        <div class="panel-preset-meta">
                                            <span class="panel-preset-label">{{ preset.label }}</span>
                                            <span v-if="activePanelPresetId === preset.id" class="panel-preset-tag">Active</span>
                                            <span class="panel-preset-desc">{{ preset.description }}</span>
                                        </div>
                                        <div v-if="isCustomPanelPreset(preset)" class="panel-preset-actions">
                                            <button class="panel-preset-action" type="button" @click.stop="startPanelPresetRename(preset)">
                                                Rename
                                            </button>
                                            <button class="panel-preset-action danger" type="button" @click.stop="deleteCustomPanelPreset(preset)">
                                                Delete
                                            </button>
                                        </div>
                                    </button>
                                </div>
                                <p class="theme-hint">Active preset: {{ activePanelPresetLabel }}</p>

                                <div class="panel-preset-tools">
                                    <div class="theme-preset-controls panel-preset-actions">
                                        <label class="theme-label">Preset Name</label>
                                        <input
                                            v-model="panelPresetName"
                                            type="text"
                                            class="panel-preset-input"
                                            placeholder="Custom panel preset"
                                            aria-label="Panel preset name"
                                        />
                                        <button class="clear-prompt-button" @click="exportPanelPreset">
                                            <RotateCcw size="16" />
                                            <span>Copy JSON</span>
                                        </button>
                                        <button class="clear-prompt-button" @click="savePanelPreset">
                                            <RotateCcw size="16" />
                                            <span>{{ panelPresetSaveLabel }}</span>
                                        </button>
                                        <button
                                            v-if="isPanelPresetEditing"
                                            class="clear-prompt-button"
                                            @click="cancelPanelPresetEdit"
                                        >
                                            <RotateCcw size="16" />
                                            <span>Cancel</span>
                                        </button>
                                        <button class="clear-prompt-button" @click="downloadPanelPreset">
                                            <RotateCcw size="16" />
                                            <span>Download</span>
                                        </button>
                                    </div>
                                    <p v-if="isPanelPresetEditing" class="theme-hint">Editing preset: {{ panelPresetEditingLabel }}</p>
                                    <div class="theme-preset-controls panel-preset-json">
                                        <label class="theme-label">Preset JSON</label>
                                        <textarea
                                            v-model="panelPresetJson"
                                            class="panel-preset-textarea"
                                            rows="5"
                                            placeholder="Paste panel preset JSON here"
                                            aria-label="Panel preset JSON"
                                        ></textarea>
                                        <button class="clear-prompt-button" @click="importPanelPreset">
                                            <RotateCcw size="16" />
                                            <span>Import</span>
                                        </button>
                                    </div>
                                    <div class="panel-preset-drop">
                                        <div
                                            class="drop-zone panel-preset-dropzone"
                                            :class="{ 'drag-over': isPanelPresetDragging }"
                                            @dragover.prevent="isPanelPresetDragging = true"
                                            @dragleave="isPanelPresetDragging = false"
                                            @drop.prevent="handlePanelPresetFileDrop"
                                            @click="triggerPanelPresetFileInput"
                                        >
                                            <div class="drop-zone-content">
                                                <div class="drop-icon">
                                                    <Palette size="26" />
                                                </div>
                                                <span class="drop-text">Drop preset JSON here or click to browse</span>
                                                <span class="drop-hint">.json files supported</span>
                                            </div>
                                            <input
                                                type="file"
                                                ref="panelPresetFileInput"
                                                style="display: none"
                                                @change="handlePanelPresetFileInput"
                                                accept="application/json,.json"
                                            />
                                        </div>
                                    </div>
                                    <div class="panel-preset-diff">
                                        <div class="panel-preset-diff-header">
                                            <span>Differences from {{ panelPresetBaselineLabel }}</span>
                                            <button
                                                class="panel-preset-reset"
                                                type="button"
                                                @click="resetPanelPresetBaseline"
                                                :disabled="!panelPresetBaseline"
                                            >
                                                Reset
                                            </button>
                                        </div>
                                        <div v-if="panelPresetDiffs.length" class="panel-preset-diff-list">
                                            <div v-for="diff in panelPresetDiffs" :key="diff.key" class="panel-preset-diff-item">
                                                <span class="panel-preset-diff-label">{{ diff.label }}</span>
                                                <span class="panel-preset-diff-values">
                                                    <span class="panel-preset-diff-current">{{ diff.current }}</span>
                                                    <span class="panel-preset-diff-arrow">→</span>
                                                    <span class="panel-preset-diff-baseline">{{ diff.baseline }}</span>
                                                </span>
                                            </div>
                                        </div>
                                        <p v-else class="theme-hint">No differences from the baseline preset.</p>
                                    </div>
                                </div>

                                <div class="subsection-header">Drawers</div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <select v-model="uiDrawerBackgroundMode" class="theme-select">
                                        <option value="transparent">Transparent</option>
                                        <option value="glass">Glass (Light)</option>
                                        <option value="glass-strong">Glass (Strong)</option>
                                        <option value="preset">Preset</option>
                                        <option value="solid">Solid Color</option>
                                        <option value="custom">Custom Opacity</option>
                                    </select>
                                    <button class="clear-prompt-button" @click="resetPanelSurfaces">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                    <div
                                        class="surface-preview"
                                        :style="{ background: 'var(--vera-drawer-bg)', borderColor: 'var(--vera-drawer-border)' }"
                                        title="Drawer background preview"
                                    ></div>
                                </div>
                                <div v-if="uiDrawerBackgroundMode === 'preset'" class="theme-preset-controls">
                                    <label class="theme-label">Preset</label>
                                    <select v-model="uiDrawerBackgroundPreset" class="theme-select">
                                        <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                    </select>
                                </div>
                                <div v-if="uiDrawerBackgroundMode === 'solid' || uiDrawerBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Color</label>
                                    <input
                                        v-model="uiDrawerBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Drawer background color"
                                    />
                                </div>
                                <div v-if="uiDrawerBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Opacity</label>
                                    <input
                                        v-model.number="uiDrawerBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Drawer background opacity"
                                    />
                                    <span class="theme-value">{{ uiDrawerBackgroundOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Border</label>
                                    <input
                                        v-model="uiDrawerBorderColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Drawer border color"
                                    />
                                    <input
                                        v-model.number="uiDrawerBorderOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Drawer border opacity"
                                    />
                                    <span class="theme-value">{{ uiDrawerBorderOpacity.toFixed(2) }}</span>
                                </div>

                                <div class="subsection-header">Drawer Cards</div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <select v-model="uiDrawerCardBackgroundMode" class="theme-select">
                                        <option value="transparent">Transparent</option>
                                        <option value="glass">Glass (Light)</option>
                                        <option value="glass-strong">Glass (Strong)</option>
                                        <option value="solid">Solid Color</option>
                                        <option value="custom">Custom Opacity</option>
                                    </select>
                                    <div
                                        class="surface-preview"
                                        :style="{ background: 'var(--vera-drawer-card-bg)' }"
                                        title="Drawer card preview"
                                    ></div>
                                </div>
                                <div v-if="uiDrawerCardBackgroundMode === 'solid' || uiDrawerCardBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Color</label>
                                    <input
                                        v-model="uiDrawerCardBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Drawer card background color"
                                    />
                                </div>
                                <div v-if="uiDrawerCardBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Opacity</label>
                                    <input
                                        v-model.number="uiDrawerCardBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Drawer card background opacity"
                                    />
                                    <span class="theme-value">{{ uiDrawerCardBackgroundOpacity.toFixed(2) }}</span>
                                </div>
                            </div>
                        </div>

                        <div v-show="activePanelTab === 'canvas'" class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Canvas & Terminal</div>
                                <p class="theme-hint">Code editor and terminal panel surfaces.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Canvas / Code Editor</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <input
                                        v-model="uiCodeEditorBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Code editor background color"
                                    />
                                    <input
                                        v-model.number="uiCodeEditorBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Code editor background opacity"
                                    />
                                    <span class="theme-value">{{ uiCodeEditorBackgroundOpacity.toFixed(2) }}</span>
                                    <div
                                        class="surface-preview"
                                        :style="{ background: 'var(--vera-code-editor-bg)' }"
                                        title="Code editor preview"
                                    ></div>
                                </div>
                            </div>
                            <div class="theme-row">
                                <h4>Terminal Panel</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <input
                                        v-model="uiTerminalBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Terminal panel background color"
                                    />
                                    <input
                                        v-model.number="uiTerminalBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Terminal panel background opacity"
                                    />
                                    <span class="theme-value">{{ uiTerminalBackgroundOpacity.toFixed(2) }}</span>
                                    <div
                                        class="surface-preview"
                                        :style="{ background: 'var(--vera-terminal-bg)' }"
                                        title="Terminal panel preview"
                                    ></div>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Header</label>
                                    <input
                                        v-model="uiTerminalHeaderBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Terminal header background color"
                                    />
                                    <input
                                        v-model.number="uiTerminalHeaderBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Terminal header background opacity"
                                    />
                                    <span class="theme-value">{{ uiTerminalHeaderBackgroundOpacity.toFixed(2) }}</span>
                                    <div
                                        class="surface-preview"
                                        :style="{ background: 'var(--vera-terminal-header-bg)' }"
                                        title="Terminal header preview"
                                    ></div>
                                </div>
                            </div>
                            <div class="theme-row">
                                <h4>Base Colors</h4>
                                <div class="color-grid">
                                    <div class="color-item">
                                        <label>Background</label>
                                        <input v-model="uiTerminalBackground" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Foreground</label>
                                        <input v-model="uiTerminalForeground" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Cursor</label>
                                        <input v-model="uiTerminalCursor" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Selection</label>
                                        <input v-model="uiTerminalSelection" type="color" class="accent-picker" />
                                    </div>
                                </div>
                            </div>
                            <div class="theme-row">
                                <h4>ANSI Colors</h4>
                                <div class="color-grid">
                                    <div class="color-item">
                                        <label>Black</label>
                                        <input v-model="uiTerminalBlack" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Red</label>
                                        <input v-model="uiTerminalRed" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Green</label>
                                        <input v-model="uiTerminalGreen" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Yellow</label>
                                        <input v-model="uiTerminalYellow" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Blue</label>
                                        <input v-model="uiTerminalBlue" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Magenta</label>
                                        <input v-model="uiTerminalMagenta" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Cyan</label>
                                        <input v-model="uiTerminalCyan" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>White</label>
                                        <input v-model="uiTerminalWhite" type="color" class="accent-picker" />
                                    </div>
                                </div>
                                <div class="theme-preset-controls" style="margin-top: 12px;">
                                    <button class="clear-prompt-button" @click="resetTerminalColors">
                                        <RotateCcw size="16" />
                                        <span>Reset All</span>
                                    </button>
                                </div>
                            </div>
                        </div>

                        <div v-show="activePanelTab === 'tools'" class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Tools Panel</div>
                                <p class="theme-hint">Cards, buttons, and filters used in tools drawers.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Tool Cards</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <select v-model="uiToolCardBackgroundMode" class="theme-select">
                                        <option value="transparent">Transparent</option>
                                        <option value="glass">Glass (Light)</option>
                                        <option value="glass-strong">Glass (Strong)</option>
                                        <option value="preset">Preset</option>
                                        <option value="solid">Solid Color</option>
                                        <option value="custom">Custom Opacity</option>
                                    </select>
                                    <button class="clear-prompt-button" @click="resetToolCardTheme">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <div v-if="uiToolCardBackgroundMode === 'preset'" class="theme-preset-controls">
                                    <label class="theme-label">Preset</label>
                                    <select v-model="uiToolCardBackgroundPreset" class="theme-select">
                                        <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                    </select>
                                </div>
                                <div v-if="uiToolCardBackgroundMode === 'solid' || uiToolCardBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Color</label>
                                    <input
                                        v-model="uiToolCardBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Tool card background color"
                                    />
                                </div>
                                <div v-if="uiToolCardBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Opacity</label>
                                    <input
                                        v-model.number="uiToolCardBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Tool card background opacity"
                                    />
                                    <span class="theme-value">{{ uiToolCardBackgroundOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Border</label>
                                    <input
                                        v-model="uiToolCardBorderColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Tool card border color"
                                    />
                                    <input
                                        v-model.number="uiToolCardBorderOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Tool card border opacity"
                                    />
                                    <span class="theme-value">{{ uiToolCardBorderOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Glow</label>
                                    <input
                                        v-model.number="uiToolCardGlow"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Tool card glow intensity"
                                    />
                                    <span class="theme-value">{{ uiToolCardGlow.toFixed(2) }}</span>
                                </div>
                            </div>

                            <div class="theme-row">
                                <h4>Buttons</h4>
                                <p class="theme-hint">Applies to rail buttons, action buttons, and sidebar buttons.</p>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <select v-model="uiButtonBackgroundMode" class="theme-select">
                                        <option value="glass">Glass (Light)</option>
                                        <option value="glass-strong">Glass (Strong)</option>
                                        <option value="preset">Preset</option>
                                        <option value="solid">Solid Color</option>
                                        <option value="custom">Custom Opacity</option>
                                    </select>
                                    <button class="clear-prompt-button" @click="resetButtonTheme">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                                <div v-if="uiButtonBackgroundMode === 'preset'" class="theme-preset-controls">
                                    <label class="theme-label">Preset</label>
                                    <select v-model="uiButtonBackgroundPreset" class="theme-select">
                                        <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                    </select>
                                </div>
                                <div v-if="uiButtonBackgroundMode === 'solid' || uiButtonBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Color</label>
                                    <input
                                        v-model="uiButtonBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Button background color"
                                    />
                                </div>
                                <div v-if="uiButtonBackgroundMode === 'custom'" class="theme-preset-controls">
                                    <label class="theme-label">Opacity</label>
                                    <input
                                        v-model.number="uiButtonBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Button background opacity"
                                    />
                                    <span class="theme-value">{{ uiButtonBackgroundOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Border</label>
                                    <input
                                        v-model="uiButtonBorderColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Button border color"
                                    />
                                    <input
                                        v-model.number="uiButtonBorderOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Button border opacity"
                                    />
                                    <span class="theme-value">{{ uiButtonBorderOpacity.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Glow</label>
                                    <input
                                        v-model.number="uiButtonGlow"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Button glow intensity"
                                    />
                                    <span class="theme-value">{{ uiButtonGlow.toFixed(2) }}</span>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Stop Button</label>
                                    <input
                                        v-model="uiStopButtonBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Stop button background color"
                                    />
                                    <button class="clear-prompt-button" @click="uiStopButtonBackgroundColor = ''">
                                        <RotateCcw size="16" />
                                        <span>Reset</span>
                                    </button>
                                </div>
                            </div>

                            <div class="theme-row">
                                <h4>Filter Buttons</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <input
                                        v-model="uiFilterButtonBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Filter button background color"
                                    />
                                    <input
                                        v-model.number="uiFilterButtonBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Filter button background opacity"
                                    />
                                    <span class="theme-value">{{ uiFilterButtonBackgroundOpacity.toFixed(2) }}</span>
                                    <div
                                        class="surface-preview"
                                        :style="{ background: 'var(--vera-filter-button-bg)' }"
                                        title="Filter button preview"
                                    ></div>
                                </div>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Active</label>
                                    <input
                                        v-model="uiFilterButtonActiveBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Filter button active background color"
                                    />
                                    <input
                                        v-model.number="uiFilterButtonActiveBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Filter button active background opacity"
                                    />
                                    <span class="theme-value">{{ uiFilterButtonActiveBackgroundOpacity.toFixed(2) }}</span>
                                    <div
                                        class="surface-preview"
                                        :style="{ background: 'var(--vera-filter-button-active-bg)' }"
                                        title="Filter button active preview"
                                    ></div>
                                </div>
                            </div>
                        </div>

                        <div v-show="activePanelTab === 'config'" class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Configuration Panel</div>
                                <p class="theme-hint">Settings dialogs and configuration surfaces.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Dialog Content</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <input
                                        v-model="uiDialogContentBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Dialog content background color"
                                    />
                                    <input
                                        v-model.number="uiDialogContentBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Dialog content background opacity"
                                    />
                                    <span class="theme-value">{{ uiDialogContentBackgroundOpacity.toFixed(2) }}</span>
                                    <div
                                        class="surface-preview"
                                        :style="{ background: 'var(--vera-dialog-content-bg)' }"
                                        title="Dialog content preview"
                                    ></div>
                                </div>
                            </div>
                            <div class="theme-row">
                                <h4>Cards</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <input
                                        v-model="uiCardBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Card background color"
                                    />
                                    <input
                                        v-model.number="uiCardBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="Card background opacity"
                                    />
                                    <span class="theme-value">{{ uiCardBackgroundOpacity.toFixed(2) }}</span>
                                    <div
                                        class="surface-preview"
                                        :style="{ background: 'var(--vera-card-bg)' }"
                                        title="Card preview"
                                    ></div>
                                </div>
                            </div>
                        </div>

                        <div v-show="activePanelTab === 'files'" class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">File Browser</div>
                                <p class="theme-hint">Background for file lists and trees.</p>
                            </div>
                            <div class="theme-row">
                                <h4>File Browser</h4>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Background</label>
                                    <input
                                        v-model="uiFileBrowserBackgroundColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="File browser background color"
                                    />
                                    <input
                                        v-model.number="uiFileBrowserBackgroundOpacity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.05"
                                        class="range-slider"
                                        aria-label="File browser background opacity"
                                    />
                                    <span class="theme-value">{{ uiFileBrowserBackgroundOpacity.toFixed(2) }}</span>
                                    <div
                                        class="surface-preview"
                                        :style="{ background: 'var(--vera-file-browser-bg)' }"
                                        title="File browser preview"
                                    ></div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div v-show="activeThemeTab === 'signals'" class="theme-tab-panel">
                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Status Colors</div>
                            </div>
                            <div class="theme-row">
                                <h4>System Status</h4>
                                <div class="color-grid">
                                    <div class="color-item">
                                        <label>Success</label>
                                        <input v-model="uiStatusSuccess" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Warning</label>
                                        <input v-model="uiStatusWarning" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Error</label>
                                        <input v-model="uiStatusError" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Info</label>
                                        <input v-model="uiStatusInfo" type="color" class="accent-picker" />
                                    </div>
                                </div>
                                <p class="theme-hint">Colors for alerts, notifications, and status indicators.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Event Types</h4>
                                <div class="color-grid">
                                    <div class="color-item">
                                        <label>Routing</label>
                                        <input v-model="uiEventRouting" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Memory</label>
                                        <input v-model="uiEventMemory" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Tool</label>
                                        <input v-model="uiEventTool" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Decision</label>
                                        <input v-model="uiEventDecision" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Quorum</label>
                                        <input v-model="uiEventQuorum" type="color" class="accent-picker" />
                                    </div>
                                </div>
                                <p class="theme-hint">Colors for thinking display and activity events.</p>
                            </div>
                            <div class="theme-row">
                                <h4>Git Status</h4>
                                <div class="color-grid">
                                    <div class="color-item">
                                        <label>Added</label>
                                        <input v-model="uiGitAdded" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Modified</label>
                                        <input v-model="uiGitModified" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Deleted</label>
                                        <input v-model="uiGitDeleted" type="color" class="accent-picker" />
                                    </div>
                                    <div class="color-item">
                                        <label>Untracked</label>
                                        <input v-model="uiGitUntracked" type="color" class="accent-picker" />
                                    </div>
                                </div>
                                <p class="theme-hint">Colors for Git file status indicators.</p>
                            </div>
                            <div class="theme-row">
                                <div class="theme-preset-controls">
                                    <button class="clear-prompt-button" @click="resetStatusColors">
                                        <RotateCcw size="16" />
                                        <span>Reset All</span>
                                    </button>
                                </div>
                            </div>
                        </div>

                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Voice Mode</div>
                            </div>
                            <div class="theme-row">
                                <h4>Voice Mode</h4>
                                <p class="theme-hint">Colors for voice mode states.</p>
                                <div class="theme-preset-controls">
                                    <label class="theme-label">Listening</label>
                                    <input
                                        v-model="uiVoiceListeningColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Voice listening color"
                                    />
                                    <label class="theme-label">Speaking</label>
                                    <input
                                        v-model="uiVoiceSpeakingColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Voice speaking color"
                                    />
                                    <label class="theme-label">Processing</label>
                                    <input
                                        v-model="uiVoiceProcessingColor"
                                        type="color"
                                        class="accent-picker"
                                        aria-label="Voice processing color"
                                    />
                                </div>
                                <div class="theme-preset-controls">
                                    <button class="clear-prompt-button" @click="resetVoiceColors">
                                        <RotateCcw size="16" />
                                        <span>Reset All</span>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div v-show="activeThemeTab === 'advanced'" class="theme-tab-panel">
                        <div class="theme-group">
                            <div class="theme-group-header">
                                <div class="theme-group-title">Token Overrides</div>
                            </div>
                            <div class="theme-group-body theme-overrides">
                                <p class="theme-hint">
                                    Advanced: override any CSS token directly. Leave blank to use the computed theme value.
                                </p>
                                <div class="accordion-controls">
                                    <button class="accordion-control-btn" @click="expandAllSections">
                                        <ChevronDown size="14" />
                                        <span>Expand All</span>
                                    </button>
                                    <button class="accordion-control-btn" @click="collapseAllSections">
                                        <ChevronRight size="14" />
                                        <span>Collapse All</span>
                                    </button>
                                </div>

                                <!-- Recursive accordion tree -->
                                <div class="token-accordion-tree">
                                    <template v-for="region in advancedTokenTree" :key="region.id">
                                        <div class="accordion-region" :class="{ expanded: isSectionExpanded(region.id) }">
                                            <button
                                                class="accordion-header accordion-header--region"
                                                @click="toggleSection(region.id)"
                                                :aria-expanded="isSectionExpanded(region.id)"
                                            >
                                                <component :is="isSectionExpanded(region.id) ? ChevronDown : ChevronRight" size="16" class="accordion-chevron" />
                                                <span class="accordion-label">{{ region.label }}</span>
                                                <span class="accordion-count">{{ countSectionTokens(region) }}</span>
                                            </button>
                                            <p v-if="region.description" class="accordion-description">{{ region.description }}</p>

                                            <transition name="accordion-slide">
                                                <div v-show="isSectionExpanded(region.id)" class="accordion-content">
                                                    <!-- Region's direct tokens (if any) -->
                                                    <div v-if="region.tokens && region.tokens.length" class="token-accordion-tokens">
                                                        <div class="theme-token-grid">
                                                            <div
                                                                v-for="token in region.tokens"
                                                                :key="`${region.id}-${token.key}`"
                                                                class="theme-token-row"
                                                                @mouseenter="highlightTokenTargets(token.key)"
                                                                @mouseleave="clearTokenHighlight"
                                                                @focusin="highlightTokenTargets(token.key)"
                                                                @focusout="clearTokenHighlight"
                                                            >
                                                                <div class="token-meta">
                                                                    <span class="token-label">{{ token.label }}</span>
                                                                    <span class="token-key">{{ token.key }}</span>
                                                                </div>
                                                                <div class="token-controls">
                                                                    <input
                                                                        v-if="token.type === 'color'"
                                                                        type="color"
                                                                        class="accent-picker token-color"
                                                                        :value="getTokenColorValue(token.key)"
                                                                        :aria-label="`${token.label} color override`"
                                                                        @input="setOverrideValue(token.key, $event.target.value)"
                                                                    />
                                                                    <input
                                                                        class="token-input"
                                                                        type="text"
                                                                        :value="getOverrideValue(token.key)"
                                                                        :placeholder="getComputedTokenValue(token.key) || 'inherit'"
                                                                        :aria-label="`${token.label} override`"
                                                                        @input="setOverrideValue(token.key, $event.target.value)"
                                                                    />
                                                                    <div v-if="token.type === 'color' && isBackgroundToken(token)" class="token-background-tools">
                                                                        <div class="token-background-row">
                                                                            <label class="token-bg-label">Mode</label>
                                                                            <select v-model="getTokenBackgroundSettings(token.key).mode" class="token-mode-select" @change="applyTokenBackgroundSettings(token.key)">
                                                                                <option value="solid">Solid</option>
                                                                                <option value="transparent">Transparent</option>
                                                                                <option value="glass-light">Glass Light</option>
                                                                                <option value="glass-strong">Glass Strong</option>
                                                                                <option value="preset">Preset</option>
                                                                                <option value="gradient">Gradient</option>
                                                                            </select>
                                                                        </div>
                                                                        <div v-if="getTokenBackgroundSettings(token.key).mode === 'solid'" class="token-background-row">
                                                                            <label class="token-bg-label">Color</label>
                                                                            <input v-model="getTokenBackgroundSettings(token.key).color" type="color" class="accent-picker token-color" aria-label="Background color" @input="applyTokenBackgroundSettings(token.key)" />
                                                                            <label class="token-bg-label">Opacity</label>
                                                                            <input v-model.number="getTokenBackgroundSettings(token.key).opacity" type="range" min="0" max="1" step="0.05" class="token-range" aria-label="Background opacity" @input="applyTokenBackgroundSettings(token.key)" />
                                                                            <span class="token-range-value">{{ getTokenBackgroundSettings(token.key).opacity.toFixed(2) }}</span>
                                                                        </div>
                                                                        <div v-if="getTokenBackgroundSettings(token.key).mode === 'preset'" class="token-background-row">
                                                                            <label class="token-bg-label">Preset</label>
                                                                            <select v-model="getTokenBackgroundSettings(token.key).preset" class="token-mode-select" @change="applyTokenBackgroundSettings(token.key)">
                                                                                <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                                                            </select>
                                                                        </div>
                                                                        <div v-if="getTokenBackgroundSettings(token.key).mode === 'gradient'" class="token-background-row">
                                                                            <label class="token-bg-label">Start</label>
                                                                            <input v-model="getTokenBackgroundSettings(token.key).gradientStart" type="color" class="accent-picker token-color" aria-label="Gradient start color" @input="applyTokenBackgroundSettings(token.key)" />
                                                                            <label class="token-bg-label">End</label>
                                                                            <input v-model="getTokenBackgroundSettings(token.key).gradientEnd" type="color" class="accent-picker token-color" aria-label="Gradient end color" @input="applyTokenBackgroundSettings(token.key)" />
                                                                            <label class="token-bg-label">Angle</label>
                                                                            <input v-model.number="getTokenBackgroundSettings(token.key).gradientAngle" type="range" min="0" max="360" class="token-range" aria-label="Gradient angle" @input="applyTokenBackgroundSettings(token.key)" />
                                                                            <span class="token-range-value">{{ getTokenBackgroundSettings(token.key).gradientAngle }}°</span>
                                                                        </div>
                                                                    </div>
                                                                    <button class="token-reset" @click="resetOverrideValue(token.key)">Reset</button>
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </div>

                                                    <!-- Child sections (level 2 - panels/components) -->
                                                    <template v-if="region.children && region.children.length">
                                                        <div v-for="panel in region.children" :key="panel.id" class="accordion-panel" :class="{ expanded: isSectionExpanded(panel.id) }">
                                                            <button
                                                                class="accordion-header accordion-header--panel"
                                                                @click="toggleSection(panel.id)"
                                                                :aria-expanded="isSectionExpanded(panel.id)"
                                                            >
                                                                <component :is="isSectionExpanded(panel.id) ? ChevronDown : ChevronRight" size="14" class="accordion-chevron" />
                                                                <span class="accordion-label">{{ panel.label }}</span>
                                                                <span class="accordion-count">{{ countSectionTokens(panel) }}</span>
                                                            </button>
                                                            <p v-if="panel.description" class="accordion-description accordion-description--panel">{{ panel.description }}</p>

                                                            <transition name="accordion-slide">
                                                                <div v-show="isSectionExpanded(panel.id)" class="accordion-content accordion-content--panel">
                                                                    <!-- Panel's direct tokens -->
                                                                    <div v-if="panel.tokens && panel.tokens.length" class="token-accordion-tokens">
                                                                        <div class="theme-token-grid">
                                                                            <div
                                                                                v-for="token in panel.tokens"
                                                                                :key="`${panel.id}-${token.key}`"
                                                                                class="theme-token-row"
                                                                                @mouseenter="highlightTokenTargets(token.key)"
                                                                                @mouseleave="clearTokenHighlight"
                                                                                @focusin="highlightTokenTargets(token.key)"
                                                                                @focusout="clearTokenHighlight"
                                                                            >
                                                                                <div class="token-meta">
                                                                                    <span class="token-label">{{ token.label }}</span>
                                                                                    <span class="token-key">{{ token.key }}</span>
                                                                                </div>
                                                                                <div class="token-controls">
                                                                                    <input v-if="token.type === 'color'" type="color" class="accent-picker token-color" :value="getTokenColorValue(token.key)" :aria-label="`${token.label} color override`" @input="setOverrideValue(token.key, $event.target.value)" />
                                                                                    <input class="token-input" type="text" :value="getOverrideValue(token.key)" :placeholder="getComputedTokenValue(token.key) || 'inherit'" :aria-label="`${token.label} override`" @input="setOverrideValue(token.key, $event.target.value)" />
                                                                                    <div v-if="token.type === 'color' && isBackgroundToken(token)" class="token-background-tools">
                                                                                        <div class="token-background-row">
                                                                                            <label class="token-bg-label">Mode</label>
                                                                                            <select v-model="getTokenBackgroundSettings(token.key).mode" class="token-mode-select" @change="applyTokenBackgroundSettings(token.key)">
                                                                                                <option value="solid">Solid</option>
                                                                                                <option value="transparent">Transparent</option>
                                                                                                <option value="glass-light">Glass Light</option>
                                                                                                <option value="glass-strong">Glass Strong</option>
                                                                                                <option value="preset">Preset</option>
                                                                                                <option value="gradient">Gradient</option>
                                                                                            </select>
                                                                                        </div>
                                                                                        <div v-if="getTokenBackgroundSettings(token.key).mode === 'solid'" class="token-background-row">
                                                                                            <label class="token-bg-label">Color</label>
                                                                                            <input v-model="getTokenBackgroundSettings(token.key).color" type="color" class="accent-picker token-color" aria-label="Background color" @input="applyTokenBackgroundSettings(token.key)" />
                                                                                            <label class="token-bg-label">Opacity</label>
                                                                                            <input v-model.number="getTokenBackgroundSettings(token.key).opacity" type="range" min="0" max="1" step="0.05" class="token-range" aria-label="Background opacity" @input="applyTokenBackgroundSettings(token.key)" />
                                                                                            <span class="token-range-value">{{ getTokenBackgroundSettings(token.key).opacity.toFixed(2) }}</span>
                                                                                        </div>
                                                                                        <div v-if="getTokenBackgroundSettings(token.key).mode === 'preset'" class="token-background-row">
                                                                                            <label class="token-bg-label">Preset</label>
                                                                                            <select v-model="getTokenBackgroundSettings(token.key).preset" class="token-mode-select" @change="applyTokenBackgroundSettings(token.key)">
                                                                                                <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                                                                            </select>
                                                                                        </div>
                                                                                        <div v-if="getTokenBackgroundSettings(token.key).mode === 'gradient'" class="token-background-row">
                                                                                            <label class="token-bg-label">Start</label>
                                                                                            <input v-model="getTokenBackgroundSettings(token.key).gradientStart" type="color" class="accent-picker token-color" aria-label="Gradient start color" @input="applyTokenBackgroundSettings(token.key)" />
                                                                                            <label class="token-bg-label">End</label>
                                                                                            <input v-model="getTokenBackgroundSettings(token.key).gradientEnd" type="color" class="accent-picker token-color" aria-label="Gradient end color" @input="applyTokenBackgroundSettings(token.key)" />
                                                                                            <label class="token-bg-label">Angle</label>
                                                                                            <input v-model.number="getTokenBackgroundSettings(token.key).gradientAngle" type="range" min="0" max="360" class="token-range" aria-label="Gradient angle" @input="applyTokenBackgroundSettings(token.key)" />
                                                                                            <span class="token-range-value">{{ getTokenBackgroundSettings(token.key).gradientAngle }}°</span>
                                                                                        </div>
                                                                                    </div>
                                                                                    <button class="token-reset" @click="resetOverrideValue(token.key)">Reset</button>
                                                                                </div>
                                                                            </div>
                                                                        </div>
                                                                    </div>

                                                                    <!-- Grandchild sections (level 3 - specific parts) -->
                                                                    <template v-if="panel.children && panel.children.length">
                                                                        <div v-for="part in panel.children" :key="part.id" class="accordion-part" :class="{ expanded: isSectionExpanded(part.id) }">
                                                                            <button
                                                                                class="accordion-header accordion-header--part"
                                                                                @click="toggleSection(part.id)"
                                                                                :aria-expanded="isSectionExpanded(part.id)"
                                                                            >
                                                                                <component :is="isSectionExpanded(part.id) ? ChevronDown : ChevronRight" size="12" class="accordion-chevron" />
                                                                                <span class="accordion-label">{{ part.label }}</span>
                                                                                <span class="accordion-count">{{ countSectionTokens(part) }}</span>
                                                                            </button>

                                                                            <transition name="accordion-slide">
                                                                                <div v-show="isSectionExpanded(part.id)" class="accordion-content accordion-content--part">
                                                                                    <div v-if="part.tokens && part.tokens.length" class="token-accordion-tokens">
                                                                                        <div class="theme-token-grid">
                                                                                            <div
                                                                                                v-for="token in part.tokens"
                                                                                                :key="`${part.id}-${token.key}`"
                                                                                                class="theme-token-row"
                                                                                                @mouseenter="highlightTokenTargets(token.key)"
                                                                                                @mouseleave="clearTokenHighlight"
                                                                                                @focusin="highlightTokenTargets(token.key)"
                                                                                                @focusout="clearTokenHighlight"
                                                                                            >
                                                                                                <div class="token-meta">
                                                                                                    <span class="token-label">{{ token.label }}</span>
                                                                                                    <span class="token-key">{{ token.key }}</span>
                                                                                                </div>
                                                                                                <div class="token-controls">
                                                                                                    <input v-if="token.type === 'color'" type="color" class="accent-picker token-color" :value="getTokenColorValue(token.key)" :aria-label="`${token.label} color override`" @input="setOverrideValue(token.key, $event.target.value)" />
                                                                                                    <input class="token-input" type="text" :value="getOverrideValue(token.key)" :placeholder="getComputedTokenValue(token.key) || 'inherit'" :aria-label="`${token.label} override`" @input="setOverrideValue(token.key, $event.target.value)" />
                                                                                                    <div v-if="token.type === 'color' && isBackgroundToken(token)" class="token-background-tools">
                                                                                                        <div class="token-background-row">
                                                                                                            <label class="token-bg-label">Mode</label>
                                                                                                            <select v-model="getTokenBackgroundSettings(token.key).mode" class="token-mode-select" @change="applyTokenBackgroundSettings(token.key)">
                                                                                                                <option value="solid">Solid</option>
                                                                                                                <option value="transparent">Transparent</option>
                                                                                                                <option value="glass-light">Glass Light</option>
                                                                                                                <option value="glass-strong">Glass Strong</option>
                                                                                                                <option value="preset">Preset</option>
                                                                                                                <option value="gradient">Gradient</option>
                                                                                                            </select>
                                                                                                        </div>
                                                                                                        <div v-if="getTokenBackgroundSettings(token.key).mode === 'solid'" class="token-background-row">
                                                                                                            <label class="token-bg-label">Color</label>
                                                                                                            <input v-model="getTokenBackgroundSettings(token.key).color" type="color" class="accent-picker token-color" aria-label="Background color" @input="applyTokenBackgroundSettings(token.key)" />
                                                                                                            <label class="token-bg-label">Opacity</label>
                                                                                                            <input v-model.number="getTokenBackgroundSettings(token.key).opacity" type="range" min="0" max="1" step="0.05" class="token-range" aria-label="Background opacity" @input="applyTokenBackgroundSettings(token.key)" />
                                                                                                            <span class="token-range-value">{{ getTokenBackgroundSettings(token.key).opacity.toFixed(2) }}</span>
                                                                                                        </div>
                                                                                                        <div v-if="getTokenBackgroundSettings(token.key).mode === 'preset'" class="token-background-row">
                                                                                                            <label class="token-bg-label">Preset</label>
                                                                                                            <select v-model="getTokenBackgroundSettings(token.key).preset" class="token-mode-select" @change="applyTokenBackgroundSettings(token.key)">
                                                                                                                <option v-for="opt in backgroundPresetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                                                                                                            </select>
                                                                                                        </div>
                                                                                                        <div v-if="getTokenBackgroundSettings(token.key).mode === 'gradient'" class="token-background-row">
                                                                                                            <label class="token-bg-label">Start</label>
                                                                                                            <input v-model="getTokenBackgroundSettings(token.key).gradientStart" type="color" class="accent-picker token-color" aria-label="Gradient start color" @input="applyTokenBackgroundSettings(token.key)" />
                                                                                                            <label class="token-bg-label">End</label>
                                                                                                            <input v-model="getTokenBackgroundSettings(token.key).gradientEnd" type="color" class="accent-picker token-color" aria-label="Gradient end color" @input="applyTokenBackgroundSettings(token.key)" />
                                                                                                            <label class="token-bg-label">Angle</label>
                                                                                                            <input v-model.number="getTokenBackgroundSettings(token.key).gradientAngle" type="range" min="0" max="360" class="token-range" aria-label="Gradient angle" @input="applyTokenBackgroundSettings(token.key)" />
                                                                                                            <span class="token-range-value">{{ getTokenBackgroundSettings(token.key).gradientAngle }}°</span>
                                                                                                        </div>
                                                                                                    </div>
                                                                                                    <button class="token-reset" @click="resetOverrideValue(token.key)">Reset</button>
                                                                                                </div>
                                                                                            </div>
                                                                                        </div>
                                                                                    </div>

                                                                                    <!-- Level 4 children (if any) -->
                                                                                    <template v-if="part.children && part.children.length">
                                                                                        <div v-for="subpart in part.children" :key="subpart.id" class="accordion-subpart">
                                                                                            <div class="accordion-subpart-header">
                                                                                                <span class="accordion-label">{{ subpart.label }}</span>
                                                                                                <span class="accordion-count">{{ countSectionTokens(subpart) }}</span>
                                                                                            </div>
                                                                                            <div v-if="subpart.tokens && subpart.tokens.length" class="token-accordion-tokens">
                                                                                                <div class="theme-token-grid">
                                                                                                    <div
                                                                                                        v-for="token in subpart.tokens"
                                                                                                        :key="`${subpart.id}-${token.key}`"
                                                                                                        class="theme-token-row"
                                                                                                        @mouseenter="highlightTokenTargets(token.key)"
                                                                                                        @mouseleave="clearTokenHighlight"
                                                                                                        @focusin="highlightTokenTargets(token.key)"
                                                                                                        @focusout="clearTokenHighlight"
                                                                                                    >
                                                                                                        <div class="token-meta">
                                                                                                            <span class="token-label">{{ token.label }}</span>
                                                                                                            <span class="token-key">{{ token.key }}</span>
                                                                                                        </div>
                                                                                                        <div class="token-controls">
                                                                                                            <input v-if="token.type === 'color'" type="color" class="accent-picker token-color" :value="getTokenColorValue(token.key)" :aria-label="`${token.label} color override`" @input="setOverrideValue(token.key, $event.target.value)" />
                                                                                                            <input class="token-input" type="text" :value="getOverrideValue(token.key)" :placeholder="getComputedTokenValue(token.key) || 'inherit'" :aria-label="`${token.label} override`" @input="setOverrideValue(token.key, $event.target.value)" />
                                                                                                            <button class="token-reset" @click="resetOverrideValue(token.key)">Reset</button>
                                                                                                        </div>
                                                                                                    </div>
                                                                                                </div>
                                                                                            </div>
                                                                                        </div>
                                                                                    </template>
                                                                                </div>
                                                                            </transition>
                                                                        </div>
                                                                    </template>
                                                                </div>
                                                            </transition>
                                                        </div>
                                                    </template>
                                                </div>
                                            </transition>
                                        </div>
                                    </template>
                                </div>

                                <div class="theme-row">
                                    <button class="clear-prompt-button" @click="resetAllOverrides">
                                        <RotateCcw size="16" />
                                        <span>Reset Overrides</span>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </transition>
        </div>

        </div>
        <div v-show="activeTab === 'typography'" class="appearance-section">
            <div class="config-section show">
                <div class="section-header static">
                    <h3>
                        <Type size="20" class="section-icon" />
                        Font Families
                    </h3>
                </div>
                <div class="theme-content">
                    <div class="theme-row">
                        <h4>Font Scale</h4>
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiFontScale"
                                type="range"
                                min="0.85"
                                max="1.5"
                                step="0.01"
                                class="range-slider"
                                aria-label="Font scale"
                            />
                            <span class="theme-value">{{ (uiFontScale * 100).toFixed(0) }}%</span>
                            <button class="clear-prompt-button" @click="uiFontScale = 1.0">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                        <p class="theme-hint">Adjust overall UI text size.</p>
                    </div>
                    <div class="theme-row">
                        <h4>Global Font</h4>
                        <div class="select-dropdown">
                            <select v-model="uiFontFamilyGlobal" aria-label="Global font family">
                                <option v-for="opt in fontFamilyOptions" :key="opt.value" :value="opt.value">
                                    {{ opt.label }}
                                </option>
                            </select>
                        </div>
                        <p class="theme-hint">Default font for all UI elements.</p>
                    </div>
                    <div class="theme-row">
                        <h4>Header Font</h4>
                        <div class="select-dropdown">
                            <select v-model="uiFontFamilyHeader" aria-label="Header font family">
                                <option v-for="opt in fontFamilyOptions" :key="opt.value" :value="opt.value">
                                    {{ opt.label }}
                                </option>
                            </select>
                        </div>
                        <p class="theme-hint">Font for app header and titles.</p>
                    </div>
                    <div class="theme-row">
                        <h4>Sidebar Font</h4>
                        <div class="select-dropdown">
                            <select v-model="uiFontFamilySidebar" aria-label="Sidebar font family">
                                <option v-for="opt in fontFamilyOptions" :key="opt.value" :value="opt.value">
                                    {{ opt.label }}
                                </option>
                            </select>
                        </div>
                        <p class="theme-hint">Font for sidebars and menus.</p>
                    </div>
                    <div class="theme-row">
                        <h4>Messages Font</h4>
                        <div class="select-dropdown">
                            <select v-model="uiFontFamilyMessages" aria-label="Messages font family">
                                <option v-for="opt in fontFamilyOptions" :key="opt.value" :value="opt.value">
                                    {{ opt.label }}
                                </option>
                            </select>
                        </div>
                        <p class="theme-hint">Font for chat messages.</p>
                    </div>
                    <div class="theme-row">
                        <h4>Input Font</h4>
                        <div class="select-dropdown">
                            <select v-model="uiFontFamilyInput" aria-label="Input font family">
                                <option v-for="opt in fontFamilyOptions" :key="opt.value" :value="opt.value">
                                    {{ opt.label }}
                                </option>
                            </select>
                        </div>
                        <p class="theme-hint">Font for text input areas.</p>
                    </div>
                    <div class="theme-row">
                        <h4>Code Font</h4>
                        <div class="select-dropdown">
                            <select v-model="uiFontFamilyCode" aria-label="Code font family">
                                <option v-for="opt in codeFontOptions" :key="opt.value" :value="opt.value">
                                    {{ opt.label }}
                                </option>
                            </select>
                        </div>
                        <p class="theme-hint">Monospace font for code blocks.</p>
                    </div>
                    <div class="theme-row">
                        <h4>Reset Fonts</h4>
                        <button class="clear-prompt-button" @click="resetAllFonts">
                            <RotateCcw size="16" />
                            <span>Reset All Fonts</span>
                        </button>
                    </div>
                </div>
            </div>
            <div class="config-section show">
                <div class="section-header static">
                    <h3>
                        <Palette size="20" class="section-icon" />
                        Text Colors
                    </h3>
                </div>
                <div class="theme-content">
                    <p class="theme-hint" style="margin-bottom: 12px;">Leave empty to use theme defaults. Pick a color to override.</p>
                    <div class="theme-row">
                        <h4>Header Text</h4>
                        <div class="theme-preset-controls">
                            <input
                                v-model="uiFontColorHeader"
                                type="color"
                                class="accent-picker"
                                aria-label="Header text color"
                            />
                            <button class="clear-prompt-button" @click="uiFontColorHeader = ''">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                    </div>
                    <div class="theme-row">
                        <h4>Sidebar Text</h4>
                        <div class="theme-preset-controls">
                            <input
                                v-model="uiFontColorSidebar"
                                type="color"
                                class="accent-picker"
                                aria-label="Sidebar text color"
                            />
                            <button class="clear-prompt-button" @click="uiFontColorSidebar = ''">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                    </div>
                    <div class="theme-row">
                        <h4>Messages Text</h4>
                        <div class="theme-preset-controls">
                            <input
                                v-model="uiFontColorMessages"
                                type="color"
                                class="accent-picker"
                                aria-label="Messages text color"
                            />
                            <button class="clear-prompt-button" @click="uiFontColorMessages = ''">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                    </div>
                    <div class="theme-row">
                        <h4>Input Text</h4>
                        <div class="theme-preset-controls">
                            <input
                                v-model="uiFontColorInput"
                                type="color"
                                class="accent-picker"
                                aria-label="Input text color"
                            />
                            <button class="clear-prompt-button" @click="uiFontColorInput = ''">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                    </div>
                    <div class="theme-row">
                        <h4>Muted/Secondary Text</h4>
                        <div class="theme-preset-controls">
                            <input
                                v-model="uiFontColorMuted"
                                type="color"
                                class="accent-picker"
                                aria-label="Muted text color"
                            />
                            <button class="clear-prompt-button" @click="uiFontColorMuted = ''">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                    </div>
                    <div class="theme-row">
                        <h4>Reset Colors</h4>
                        <button class="clear-prompt-button" @click="resetAllFontColors">
                            <RotateCcw size="16" />
                            <span>Reset All Colors</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
        <div v-show="activeTab === 'effects'" class="appearance-section">
            <div class="config-section show">
                <div class="section-header static">
                    <h3>
                        <Sparkles size="20" class="section-icon" />
                        Ambient Effects
                    </h3>
                </div>
                <div class="theme-content">
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Scanlines</h4>
                        <SliderCheckbox inputId="effect-scanlines" labelText="Enable scanline overlay"
                            v-model="uiEffectScanlines" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectScanlineOpacity"
                                type="range"
                                min="0"
                                max="0.4"
                                step="0.02"
                                class="range-slider"
                                aria-label="Scanline opacity"
                                :disabled="uiLiteMode || !uiEffectScanlines"
                            />
                            <span class="theme-value">{{ uiEffectScanlineOpacity.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Film Grain</h4>
                        <SliderCheckbox inputId="effect-noise" labelText="Enable film grain"
                            v-model="uiEffectNoise" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectNoiseOpacity"
                                type="range"
                                min="0"
                                max="0.3"
                                step="0.02"
                                class="range-slider"
                                aria-label="Noise opacity"
                                :disabled="uiLiteMode || !uiEffectNoise"
                            />
                            <span class="theme-value">{{ uiEffectNoiseOpacity.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Accent Glow Pulse</h4>
                        <SliderCheckbox inputId="effect-glow-pulse" labelText="Pulse panel glow"
                            v-model="uiEffectGlowPulse" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectGlowPulseStrength"
                                type="range"
                                min="0"
                                max="1"
                                step="0.05"
                                class="range-slider"
                                aria-label="Glow intensity"
                                :disabled="uiLiteMode || !uiEffectGlowPulse"
                            />
                            <span class="theme-value">{{ uiEffectGlowPulseStrength.toFixed(2) }}</span>
                        </div>
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectGlowPulseSpeed"
                                type="range"
                                min="2"
                                max="20"
                                step="1"
                                class="range-slider"
                                aria-label="Glow pulse speed"
                                :disabled="uiLiteMode || !uiEffectGlowPulse"
                            />
                            <span class="theme-value">{{ uiEffectGlowPulseSpeed }}s</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Grid Overlay</h4>
                        <SliderCheckbox inputId="effect-grid" labelText="Enable grid overlay"
                            v-model="uiEffectGrid" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectGridOpacity"
                                type="range"
                                min="0"
                                max="0.4"
                                step="0.02"
                                class="range-slider"
                                aria-label="Grid opacity"
                                :disabled="uiLiteMode || !uiEffectGrid"
                            />
                            <span class="theme-value">{{ uiEffectGridOpacity.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Vignette</h4>
                        <SliderCheckbox inputId="effect-vignette" labelText="Darken edges for depth"
                            v-model="uiEffectVignette" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectVignetteStrength"
                                type="range"
                                min="0"
                                max="0.6"
                                step="0.02"
                                class="range-slider"
                                aria-label="Vignette strength"
                                :disabled="uiLiteMode || !uiEffectVignette"
                            />
                            <span class="theme-value">{{ uiEffectVignetteStrength.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Aurora Overlay</h4>
                        <SliderCheckbox inputId="effect-aurora" labelText="Enable aurora wash"
                            v-model="uiEffectAurora" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectAuroraOpacity"
                                type="range"
                                min="0"
                                max="0.4"
                                step="0.02"
                                class="range-slider"
                                aria-label="Aurora opacity"
                                :disabled="uiLiteMode || !uiEffectAurora"
                            />
                            <span class="theme-value">{{ uiEffectAuroraOpacity.toFixed(2) }}</span>
                        </div>
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectAuroraSpeed"
                                type="range"
                                min="0.5"
                                max="160"
                                step="0.5"
                                class="range-slider"
                                aria-label="Aurora drift speed"
                                :disabled="uiLiteMode || !uiEffectAurora"
                            />
                            <span class="theme-value">{{ uiEffectAuroraSpeed.toFixed(1) }}s</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Header Shimmer</h4>
                        <SliderCheckbox inputId="effect-header-shimmer" labelText="Shimmer top bars"
                            v-model="uiEffectHeaderShimmer" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectHeaderShimmerStrength"
                                type="range"
                                min="0"
                                max="0.4"
                                step="0.02"
                                class="range-slider"
                                aria-label="Header shimmer strength"
                                :disabled="uiLiteMode || !uiEffectHeaderShimmer"
                            />
                            <span class="theme-value">{{ uiEffectHeaderShimmerStrength.toFixed(2) }}</span>
                        </div>
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectHeaderShimmerSpeed"
                                type="range"
                                min="6"
                                max="30"
                                step="1"
                                class="range-slider"
                                aria-label="Header shimmer speed"
                                :disabled="uiLiteMode || !uiEffectHeaderShimmer"
                            />
                            <span class="theme-value">{{ uiEffectHeaderShimmerSpeed }}s</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Panel Depth</h4>
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiPanelDepth"
                                type="range"
                                min="0"
                                max="0.6"
                                step="0.02"
                                class="range-slider"
                                aria-label="Panel depth"
                                :disabled="uiLiteMode"
                            />
                            <span class="theme-value">{{ uiPanelDepth.toFixed(2) }}</span>
                            <button class="clear-prompt-button" @click="resetPanelDepth" :disabled="uiLiteMode">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                        <p class="theme-hint">Controls shadow depth on panels and cards.</p>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Message Depth</h4>
                        <SliderCheckbox inputId="effect-message-depth" labelText="Depth shadow for bubbles"
                            v-model="uiEffectMessageDepth" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectMessageDepthStrength"
                                type="range"
                                min="0"
                                max="0.6"
                                step="0.02"
                                class="range-slider"
                                aria-label="Message depth"
                                :disabled="uiLiteMode || !uiEffectMessageDepth"
                            />
                            <span class="theme-value">{{ uiEffectMessageDepthStrength.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Message Edge Highlight</h4>
                        <SliderCheckbox inputId="effect-message-edge" labelText="Subtle rim highlight"
                            v-model="uiEffectMessageEdge" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectMessageEdgeStrength"
                                type="range"
                                min="0"
                                max="0.6"
                                step="0.02"
                                class="range-slider"
                                aria-label="Message edge highlight"
                                :disabled="uiLiteMode || !uiEffectMessageEdge"
                            />
                            <span class="theme-value">{{ uiEffectMessageEdgeStrength.toFixed(2) }}</span>
                        </div>
                        <div class="theme-preset-controls">
                            <SelectButton
                                v-model="uiEffectMessageEdgeTint"
                                :options="messageEdgeTintOptions"
                                optionLabel="label"
                                optionValue="value"
                                class="theme-selector"
                                :disabled="uiLiteMode || !uiEffectMessageEdge"
                            />
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Glass Edge Highlight</h4>
                        <SliderCheckbox inputId="effect-panel-edge" labelText="Highlight panel edges"
                            v-model="uiEffectPanelEdge" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectPanelEdgeStrength"
                                type="range"
                                min="0"
                                max="0.6"
                                step="0.02"
                                class="range-slider"
                                aria-label="Panel edge highlight"
                                :disabled="uiLiteMode || !uiEffectPanelEdge"
                            />
                            <span class="theme-value">{{ uiEffectPanelEdgeStrength.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Glass Inner Glow</h4>
                        <SliderCheckbox inputId="effect-panel-glow" labelText="Inner glow falloff"
                            v-model="uiEffectPanelGlow" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectPanelGlowStrength"
                                type="range"
                                min="0"
                                max="0.6"
                                step="0.02"
                                class="range-slider"
                                aria-label="Panel inner glow"
                                :disabled="uiLiteMode || !uiEffectPanelGlow"
                            />
                            <span class="theme-value">{{ uiEffectPanelGlowStrength.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Panel Bevel</h4>
                        <SliderCheckbox inputId="effect-panel-bevel" labelText="Subtle top/bottom bevel"
                            v-model="uiEffectPanelBevel" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiEffectPanelBevelStrength"
                                type="range"
                                min="0"
                                max="0.4"
                                step="0.02"
                                class="range-slider"
                                aria-label="Panel bevel"
                                :disabled="uiLiteMode || !uiEffectPanelBevel"
                            />
                            <span class="theme-value">{{ uiEffectPanelBevelStrength.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="theme-row">
                        <h4>Background Blur</h4>
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiBackgroundBlur"
                                type="range"
                                min="0"
                                max="20"
                                step="1"
                                class="range-slider"
                                aria-label="Background blur"
                            />
                            <span class="theme-value">{{ uiBackgroundBlur }}px</span>
                        </div>
                        <p class="theme-hint">Blur amount for gradient or image backdrops.</p>
                    </div>
                    <div class="theme-row">
                        <h4>Header Blur</h4>
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiHeaderBlur"
                                type="range"
                                min="0"
                                max="30"
                                step="1"
                                class="range-slider"
                                aria-label="Header blur"
                            />
                            <span class="theme-value">{{ uiHeaderBlur }}px</span>
                        </div>
                        <p class="theme-hint">Controls glass blur on header bars.</p>
                    </div>
                    <div class="theme-row">
                        <h4>Nixie Tube Display</h4>
                        <p class="theme-hint">Customize the retro Nixie tube display in the sidebar header.</p>
                        <div class="theme-preset-controls">
                            <label class="color-label">Digit Color</label>
                            <input
                                v-model="uiNixieColor"
                                type="color"
                                class="color-input nixie-color"
                                aria-label="Nixie tube digit color"
                            />
                            <span class="theme-value">{{ uiNixieColor }}</span>
                        </div>
                        <div class="theme-preset-controls">
                            <label class="color-label">Glow Color</label>
                            <input
                                v-model="uiNixieGlowColor"
                                type="color"
                                class="color-input nixie-color"
                                aria-label="Nixie tube glow color"
                            />
                            <span class="theme-value">{{ uiNixieGlowColor }}</span>
                        </div>
                        <div class="theme-preset-controls">
                            <label class="color-label">Glow Intensity</label>
                            <input
                                v-model.number="uiNixieGlowIntensity"
                                type="range"
                                min="0.0"
                                max="2.0"
                                step="0.1"
                                class="range-slider"
                                aria-label="Nixie tube glow intensity"
                            />
                            <span class="theme-value">{{ (uiNixieGlowIntensity || 1.0).toFixed(1) }}</span>
                        </div>
                        <div class="theme-preset-controls">
                            <label class="color-label">Speed</label>
                            <input
                                v-model.number="uiNixieSpeed"
                                type="range"
                                min="0.25"
                                max="3"
                                step="0.25"
                                class="range-slider"
                                aria-label="Nixie tube animation speed"
                            />
                            <span class="theme-value">{{ uiNixieSpeed.toFixed(2) }}x</span>
                        </div>
                        <SliderCheckbox inputId="nixie-flicker" labelText="Enable subtle flicker"
                            v-model="uiNixieFlicker" />
                        <div class="theme-preset-controls">
                            <button class="clear-prompt-button" @click="resetNixieTube">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                    </div>
                    <div class="theme-row">
                        <h4>Exit Button</h4>
                        <p class="theme-hint">Customize the Exit VERA button appearance (separate from main Nixie theme).</p>
                        <div class="theme-preset-controls">
                            <label class="color-label">Icon Color</label>
                            <input
                                v-model="uiNixieExitColor"
                                type="color"
                                class="color-input nixie-color"
                                aria-label="Exit button icon color"
                            />
                            <span class="theme-value">{{ uiNixieExitColor }}</span>
                        </div>
                        <div class="theme-preset-controls">
                            <label class="color-label">Glow Color</label>
                            <input
                                v-model="uiNixieExitGlowColor"
                                type="color"
                                class="color-input nixie-color"
                                aria-label="Exit button glow color"
                            />
                            <span class="theme-value">{{ uiNixieExitGlowColor }}</span>
                        </div>
                        <div class="theme-preset-controls">
                            <label class="color-label">Glow Intensity</label>
                            <input
                                v-model.number="uiNixieExitGlowIntensity"
                                type="range"
                                min="0.0"
                                max="2.0"
                                step="0.1"
                                class="range-slider"
                                aria-label="Exit button glow intensity"
                            />
                            <span class="theme-value">{{ (uiNixieExitGlowIntensity || 1.0).toFixed(1) }}</span>
                        </div>
                        <div class="theme-preset-controls">
                            <button class="clear-prompt-button" @click="resetExitButton">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                    </div>
                    <div class="theme-row">
                        <h4>Nixie Buttons</h4>
                        <p class="theme-hint">Background color for Nixie-styled rail buttons.</p>
                        <div class="theme-preset-controls">
                            <label class="color-label">Background</label>
                            <input
                                v-model="uiNixieButtonBackgroundColor"
                                type="color"
                                class="color-input nixie-color"
                                aria-label="Nixie button background color"
                            />
                            <span class="theme-value">{{ uiNixieButtonBackgroundColor }}</span>
                            <button class="clear-prompt-button" @click="resetNixieButton">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                    </div>
                    <div class="theme-row">
                        <h4>Reset Effects</h4>
                        <button class="clear-prompt-button" @click="resetEffects">
                            <RotateCcw size="16" />
                            <span>Reset Effects</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
        <div v-show="activeTab === 'animations'" class="appearance-section">
            <div class="config-section show">
                <div class="section-header static">
                    <h3>
                        <Activity size="20" class="section-icon" />
                        Motion & Transitions
                    </h3>
                </div>
                <div class="theme-content">
                    <div class="theme-row">
                        <h4>Lite Mode</h4>
                        <SliderCheckbox inputId="lite-mode" labelText="Disable effects + animations"
                            v-model="uiLiteMode" />
                        <p class="theme-hint">Instantly disables polish layers for maximum performance.</p>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Animation Speed</h4>
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiAnimSpeed"
                                type="range"
                                min="0.5"
                                max="2.0"
                                step="0.1"
                                class="range-slider"
                                aria-label="Animation speed"
                                :disabled="uiLiteMode"
                            />
                            <span class="theme-value">{{ uiAnimSpeed.toFixed(1) }}x</span>
                            <button class="clear-prompt-button" @click="uiAnimSpeed = 1.0" :disabled="uiLiteMode">
                                <RotateCcw size="16" />
                                <span>Reset</span>
                            </button>
                        </div>
                        <p class="theme-hint">Slow down or speed up all UI animations.</p>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Message Entry</h4>
                        <SliderCheckbox inputId="anim-message-motion" labelText="Animate new messages"
                            v-model="uiAnimMessageMotion" :disabled="uiLiteMode" />
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Hover Lift</h4>
                        <SliderCheckbox inputId="anim-hover-lift" labelText="Lift cards on hover"
                            v-model="uiAnimHoverLift" :disabled="uiLiteMode" />
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Background Drift</h4>
                        <SliderCheckbox inputId="anim-bg-drift" labelText="Slow gradient drift"
                            v-model="uiAnimBackgroundDrift" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiAnimBackgroundDriftSpeed"
                                type="range"
                                min="20"
                                max="120"
                                step="5"
                                class="range-slider"
                                aria-label="Background drift speed"
                                :disabled="uiLiteMode || !uiAnimBackgroundDrift"
                            />
                            <span class="theme-value">{{ uiAnimBackgroundDriftSpeed }}s</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Button Micro-Interactions</h4>
                        <SliderCheckbox inputId="anim-button-motion" labelText="Enable button lift + scale"
                            v-model="uiAnimButtonMotion" :disabled="uiLiteMode" />
                        <div class="theme-preset-controls">
                            <input
                                v-model.number="uiAnimButtonScale"
                                type="range"
                                min="1"
                                max="1.06"
                                step="0.01"
                                class="range-slider"
                                aria-label="Button hover scale"
                                :disabled="uiLiteMode || !uiAnimButtonMotion"
                            />
                            <span class="theme-value">{{ uiAnimButtonScale.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="theme-row" :class="{ disabled: uiLiteMode }">
                        <h4>Button Ripple</h4>
                        <SliderCheckbox inputId="anim-button-ripple" labelText="Click ripple"
                            v-model="uiAnimButtonRipple" :disabled="uiLiteMode" />
                    </div>
                    <div class="theme-row">
                        <h4>Reset Animations</h4>
                        <button class="clear-prompt-button" @click="resetAnimations">
                            <RotateCcw size="16" />
                            <span>Reset Animations</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- ============================================ -->
        <!-- AVATAR TAB - Premium Redesign -->
        <!-- ============================================ -->
        <div v-show="activeTab === 'avatar'" class="appearance-section avatar-tab">
            <!-- Hero Preview Section -->
            <div class="avatar-hero-section">
                <div class="avatar-preview-showcase">
                    <!-- Large animated avatar preview -->
                    <div
                        class="avatar-preview-large"
                        :class="[
                            `shape-${avatarShape}`,
                            `size-${avatarSize}`,
                            avatarAnimation !== 'none' ? `anim-${avatarAnimation}` : '',
                            { 'has-glow': avatarGlow, 'has-border': avatarBorderStyle !== 'none' }
                        ]"
                        :style="{
                            '--avatar-border-color': avatarBorderColor,
                            '--avatar-border-width': avatarBorderWidth + 'px',
                            '--avatar-glow-color': avatarGlowColor,
                            '--avatar-glow-intensity': avatarGlowIntensity
                        }"
                    >
                        <img
                            v-if="currentPreviewImage"
                            :src="currentPreviewImage"
                            alt="Avatar preview"
                            class="preview-image"
                        />
                        <div v-else class="preview-placeholder">
                            <User size="48" />
                        </div>
                        <!-- Status indicator -->
                        <div v-if="showStatusIndicator" class="status-dot" :class="userStatus"></div>
                    </div>
                    <div class="preview-label">
                        <span class="preview-type">{{ avatarType.name }} Avatar</span>
                        <span class="preview-hint">Preview updates in real-time</span>
                    </div>
                </div>
                <!-- Quick toggle -->
                <div class="avatar-master-toggle">
                    <label class="premium-toggle">
                        <input type="checkbox" v-model="isAvatarEnabled" />
                        <span class="toggle-track">
                            <span class="toggle-thumb"></span>
                        </span>
                        <span class="toggle-label">Enable Avatars</span>
                    </label>
                </div>
            </div>

            <!-- Avatar Type Selector - Premium Cards -->
            <div class="avatar-type-selector">
                <h3 class="section-title">
                    <User size="18" />
                    Configure Avatar
                </h3>
                <div class="type-cards">
                    <button
                        class="type-card"
                        :class="{ active: avatarType.value === 'ai' }"
                        @click="avatarType = avatarOptions.find(o => o.value === 'ai'); handleAvatarTypeChange()"
                    >
                        <div class="card-icon ai-icon">
                            <Sparkles size="24" />
                        </div>
                        <span class="card-label">AI Assistant</span>
                        <span class="card-hint">Vera's avatar</span>
                    </button>
                    <button
                        class="type-card"
                        :class="{ active: avatarType.value === 'user' }"
                        @click="avatarType = avatarOptions.find(o => o.value === 'user'); handleAvatarTypeChange()"
                    >
                        <div class="card-icon user-icon">
                            <User size="24" />
                        </div>
                        <span class="card-label">Your Avatar</span>
                        <span class="card-hint">Your profile image</span>
                    </button>
                </div>
            </div>

            <!-- Preset Gallery -->
            <div class="avatar-presets-section">
                <h3 class="section-title">
                    <Image size="18" />
                    {{ avatarType.name }} Style Presets
                </h3>
                <div class="presets-grid">
                    <button
                        v-for="preset in avatarPresetOptions"
                        :key="preset.value"
                        class="preset-card"
                        :class="{ active: currentAvatarPresetValue === preset.value }"
                        @click="handleAvatarPresetChange(preset.value)"
                    >
                        <div
                            class="preset-icon"
                            :style="{ color: currentAvatarIconColor }"
                        >
                            <component :is="getPresetIcon(preset.value)" size="28" />
                        </div>
                        <span class="preset-label">{{ preset.label }}</span>
                    </button>
                </div>

                <!-- Icon Color Customization -->
                <div class="icon-color-section">
                    <div class="icon-color-row">
                        <span class="icon-color-label">{{ avatarType.name }} Icon Color</span>
                        <div class="icon-color-controls">
                            <input
                                :value="currentAvatarIconColor"
                                @input="handleAvatarIconColorChange($event.target.value)"
                                type="color"
                                class="icon-color-picker"
                                :aria-label="`${avatarType.name} icon color`"
                            />
                            <span class="icon-color-value">{{ currentAvatarIconColor }}</span>
                            <button
                                class="icon-color-reset"
                                @click="resetAvatarIconColor"
                                title="Reset to default"
                            >
                                <RotateCcw size="14" />
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Custom Image Section -->
            <div class="avatar-custom-section">
                <h3 class="section-title">
                    <Image size="18" />
                    Custom Image
                </h3>
                <div class="custom-upload-area">
                    <!-- Drag & Drop Zone -->
                    <div
                        class="drop-zone"
                        :class="{ 'drag-over': isDraggingFile }"
                        @dragover.prevent="isDraggingFile = true"
                        @dragleave="isDraggingFile = false"
                        @drop.prevent="handleFileDrop"
                        @click="triggerFileInput"
                    >
                        <div class="drop-zone-content">
                            <div class="drop-icon">
                                <Image size="32" />
                            </div>
                            <span class="drop-text">Drop image here or click to browse</span>
                            <span class="drop-hint">PNG, JPG, GIF up to 5MB</span>
                        </div>
                        <input
                            type="file"
                            ref="fileInput"
                            style="display: none"
                            @change="uploadFile"
                            accept="image/*"
                        />
                    </div>

                    <!-- URL Input -->
                    <div class="url-input-row">
                        <InputField
                            :labelText="`${avatarType.name} Image URL:`"
                            inputId="avatar-url"
                            :value="avatarType.value === 'ai' ? avatarUrl : userAvatarUrl"
                            @update:value="handleAvatarUrlUpdate"
                            :isSecret="false"
                            :isMultiline="false"
                            :placeholderText="`Paste image URL...`"
                        />
                    </div>

                    <!-- Stored Images Gallery -->
                    <div v-if="storedFiles.length > 0" class="stored-images-gallery">
                        <h4>Your Uploaded Images</h4>
                        <div class="images-grid">
                            <button
                                v-for="file in storedFiles"
                                :key="file.fileName"
                                class="stored-image-card"
                                :class="{ active: selectedFile?.fileName === file.fileName || (!selectedFile && currentPreviewImage && file.fileData === currentPreviewImage) }"
                                @click="selectStoredImage(file)"
                            >
                                <img :src="file.fileData" :alt="file.fileName" />
                                <span class="image-name">{{ file.fileName }}</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Appearance Settings -->
            <div class="avatar-appearance-settings">
                <h3 class="section-title">
                    <Palette size="18" />
                    Appearance
                </h3>

                <div class="settings-grid">
                    <!-- Shape -->
                    <div class="setting-group">
                        <label class="setting-label">Shape</label>
                        <div class="premium-segmented">
                            <button
                                v-for="shape in avatarShapes"
                                :key="shape.value"
                                :class="{ active: avatarShape === shape.value }"
                                @click="avatarShape = shape.value; handleAvatarShapeChange()"
                            >
                                {{ shape.name }}
                            </button>
                        </div>
                    </div>

                    <!-- Size -->
                    <div class="setting-group">
                        <label class="setting-label">Size</label>
                        <div class="premium-segmented">
                            <button
                                v-for="size in avatarSizeOptions"
                                :key="size.value"
                                :class="{ active: avatarSize === size.value }"
                                @click="avatarSize = size.value"
                            >
                                {{ size.label }}
                            </button>
                        </div>
                    </div>

                    <!-- Position -->
                    <div class="setting-group">
                        <label class="setting-label">Position</label>
                        <div class="premium-segmented">
                            <button
                                v-for="pos in avatarPositionOptions"
                                :key="pos.value"
                                :class="{ active: avatarPosition === pos.value }"
                                @click="avatarPosition = pos.value"
                            >
                                {{ pos.label }}
                            </button>
                        </div>
                    </div>

                    <!-- Animation -->
                    <div class="setting-group">
                        <label class="setting-label">Animation</label>
                        <div class="premium-segmented">
                            <button
                                v-for="anim in avatarAnimationOptions"
                                :key="anim.value"
                                :class="{ active: avatarAnimation === anim.value }"
                                @click="avatarAnimation = anim.value"
                            >
                                {{ anim.label }}
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Effects Settings -->
            <div class="avatar-effects-settings">
                <h3 class="section-title">
                    <Sparkles size="18" />
                    Effects
                </h3>

                <div class="effects-grid">
                    <!-- Border -->
                    <div class="effect-card">
                        <div class="effect-header">
                            <span class="effect-title">Border</span>
                            <div class="premium-segmented compact">
                                <button
                                    v-for="style in avatarBorderStyleOptions"
                                    :key="style.value"
                                    :class="{ active: avatarBorderStyle === style.value }"
                                    @click="avatarBorderStyle = style.value"
                                >
                                    {{ style.label }}
                                </button>
                            </div>
                        </div>
                        <div v-if="avatarBorderStyle !== 'none'" class="effect-controls">
                            <div class="control-row">
                                <label>Color</label>
                                <input
                                    v-model="avatarBorderColor"
                                    type="color"
                                    class="premium-color-picker"
                                />
                            </div>
                            <div class="control-row">
                                <label>Width</label>
                                <div class="premium-slider-container">
                                    <input
                                        v-model.number="avatarBorderWidth"
                                        type="range"
                                        min="1"
                                        max="6"
                                        step="1"
                                        class="premium-slider"
                                    />
                                    <span class="slider-value">{{ avatarBorderWidth }}px</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Glow -->
                    <div class="effect-card">
                        <div class="effect-header">
                            <span class="effect-title">Glow</span>
                            <label class="premium-toggle compact">
                                <input type="checkbox" v-model="avatarGlow" />
                                <span class="toggle-track">
                                    <span class="toggle-thumb"></span>
                                </span>
                            </label>
                        </div>
                        <div v-if="avatarGlow" class="effect-controls">
                            <div class="control-row">
                                <label>Color</label>
                                <input
                                    v-model="avatarGlowColor"
                                    type="color"
                                    class="premium-color-picker"
                                />
                            </div>
                            <div class="control-row">
                                <label>Intensity</label>
                                <div class="premium-slider-container">
                                    <input
                                        v-model.number="avatarGlowIntensity"
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.1"
                                        class="premium-slider"
                                    />
                                    <span class="slider-value">{{ avatarGlowIntensity.toFixed(1) }}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Status Indicator -->
                    <div class="effect-card">
                        <div class="effect-header">
                            <span class="effect-title">Status Indicator</span>
                            <label class="premium-toggle compact">
                                <input type="checkbox" v-model="showStatusIndicator" />
                                <span class="toggle-track">
                                    <span class="toggle-thumb"></span>
                                </span>
                            </label>
                        </div>
                        <div v-if="showStatusIndicator" class="effect-controls">
                            <div class="premium-segmented">
                                <button
                                    v-for="status in userStatusOptions"
                                    :key="status.value"
                                    :class="{ active: userStatus === status.value }"
                                    @click="userStatus = status.value"
                                >
                                    <span class="status-preview" :class="status.value"></span>
                                    {{ status.label }}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Reset Button -->
            <div class="avatar-reset-section">
                <button class="premium-reset-button" @click="resetAvatarStyling">
                    <RotateCcw size="16" />
                    <span>Reset All Avatar Settings</span>
                </button>
            </div>
        </div>
    </div>
</template>

<script setup>
import InputField from '@/components/controls/InputField.vue';
import SliderCheckbox from '../controls/SliderCheckbox.vue';
import { ChevronDown, ChevronRight, User, Image, ImagePlus, Palette, RotateCcw, Sparkles, Activity, Type, Bot, Brain, Cpu, UserCircle, Hexagon, AtSign } from 'lucide-vue-next';
import { onBeforeMount, onBeforeUnmount, ref, computed, watch, nextTick, onMounted, reactive } from 'vue';
import { storeFileData } from '@/libs/file-processing/image-analysis';
import { showToast } from '@/libs/utils/general-utils';
import { fetchStoredImageFiles } from '@/libs/utils/indexed-db-utils';
import { handleUpdate } from '@/libs/utils/settings-utils';
import {
    avatarShape,
    userAvatarUrl,
    isAvatarEnabled,
    avatarUrl,
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
    uiInputBarBackgroundColor,
    uiInputBarBackgroundOpacity,
    uiInputBarBackgroundMode,
    uiInputBarBackgroundPreset,
    uiInputBarBorderColor,
    uiInputBarBorderOpacity,
    uiInputBarGlow,
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
    uiToolCardBackgroundMode,
    uiToolCardBackgroundPreset,
    uiToolCardBackgroundColor,
    uiToolCardBackgroundOpacity,
    uiToolCardBorderColor,
    uiToolCardBorderOpacity,
    uiToolCardGlow,
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
    uiNixieExitColor,
    uiNixieExitGlowColor,
    uiNixieExitGlowIntensity,
    uiNixieButtonBackgroundColor,
    uiPanelSurfacePresets,
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
import {
    DEFAULT_ACCENT_COLOR,
    DEFAULT_THEME_PRESET,
    DEFAULT_BACKGROUND_PRESET,
    DEFAULT_SIDEBAR_BACKGROUND_PRESET,
    THEME_PRESET_OPTIONS,
    BACKGROUND_PRESETS,
    BACKGROUND_PRESET_OPTIONS,
    FONT_FAMILY_OPTIONS,
    CODE_FONT_OPTIONS
} from '@/libs/utils/theme-utils';
import {
    ACCENT_SWATCHES,
    SECONDARY_SWATCHES,
    DEFAULT_TOKEN_COLOR_FALLBACK,
    DEFAULT_SECONDARY_ACCENT,
    DEFAULT_TERMINAL_COLORS,
    DEFAULT_STATUS_COLORS,
    DEFAULT_EVENT_COLORS,
    DEFAULT_GIT_COLORS,
    DEFAULT_THEME_RESET,
    DEFAULT_HEADER_THEME,
    DEFAULT_INPUT_BAR_THEME,
    DEFAULT_USER_MESSAGE_THEME,
    DEFAULT_ASSISTANT_MESSAGE_THEME,
    DEFAULT_TOOL_CARD_THEME,
    DEFAULT_BUTTON_THEME,
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
    DEFAULT_NIXIE_BUTTON_THEME,
    DEFAULT_AVATAR_STYLE,
    DEFAULT_AVATAR_ICON_COLORS,
    PANEL_SURFACE_PRESETS,
    GLOBAL_THEME_PRESETS
} from '@/libs/utils/theme-defaults';
import { THEME_TOKEN_GROUPS, THEME_TOKEN_INDEX } from '@/libs/utils/theme-tokens';

const storedFiles = ref([]);
const selectedFile = ref(null);
const fileInput = ref(null);
const isAvatarSectionOpen = ref(false);
const isThemeConfigOpen = ref(true);
const activeTab = ref('theme');
const activeThemeTab = ref('foundations');
const activePanelTab = ref('shared');

// Global theme presets
const globalThemePresets = GLOBAL_THEME_PRESETS;
const selectedGlobalTheme = ref(localStorage.getItem('selectedGlobalTheme') || '');

const selectedGlobalThemePreset = computed(() => {
    if (!selectedGlobalTheme.value) return null;
    return globalThemePresets.find(p => p.id === selectedGlobalTheme.value) || null;
});

const selectAndApplyGlobalTheme = (presetId) => {
    selectedGlobalTheme.value = presetId;
    applyGlobalThemePreset();
};

const applyGlobalThemePreset = () => {
    const preset = selectedGlobalThemePreset.value;
    if (!preset) return;

    const config = preset.config;

    // Save selection
    localStorage.setItem('selectedGlobalTheme', preset.id);

    // Set the theme's native mode (light/dark) for proper calculation adjustments
    const nativeMode = preset.nativeMode || 'dark';
    uiThemeNativeMode.value = nativeMode;
    localStorage.setItem('uiThemeNativeMode', nativeMode);

    // Switch to 'custom' mode to bypass CSS [data-theme] overrides
    // This ensures theme preset values take full precedence
    uiThemeMode.value = 'custom';
    localStorage.setItem('uiThemeMode', 'custom');

    // Apply accent colors
    if (config.accentColor) uiAccentColor.value = config.accentColor;
    if (config.secondaryAccent) uiSecondaryAccent.value = config.secondaryAccent;

    // Apply background settings
    if (config.backgroundMode) uiBackgroundMode.value = config.backgroundMode;
    if (config.backgroundPreset) uiBackgroundPreset.value = config.backgroundPreset;
    if (config.backgroundColor) uiBackgroundColor.value = config.backgroundColor;
    if (config.backgroundGradientStart) uiBackgroundGradientStart.value = config.backgroundGradientStart;
    if (config.backgroundGradientEnd) uiBackgroundGradientEnd.value = config.backgroundGradientEnd;
    if (config.backgroundGradientAngle !== undefined) uiBackgroundGradientAngle.value = config.backgroundGradientAngle;

    // Apply effects
    if (config.glassEnabled !== undefined) {
        // Glass is achieved via backdrop blur and transparent backgrounds
        uiBackgroundBlur.value = config.glassEnabled ? 12 : 0;
        uiHeaderBlur.value = config.glassEnabled ? 8 : 0;
    }
    if (config.glowEnabled !== undefined) {
        uiEffectGlowPulse.value = config.glowEnabled;
        uiEffectPanelGlow.value = config.glowEnabled;
    }
    if (config.depthEnabled !== undefined) {
        uiPanelDepth.value = config.depthEnabled ? 0.22 : 0;
        uiEffectMessageDepth.value = config.depthEnabled;
        uiEffectPanelEdge.value = config.depthEnabled;
        uiEffectPanelBevel.value = config.depthEnabled;
    }
    if (config.scanlineEnabled !== undefined) {
        uiEffectScanlines.value = config.scanlineEnabled;
        if (config.scanlineEnabled) uiEffectScanlineOpacity.value = 0.15;
    }

    // Apply panel surface preset
    if (config.panelSurfacePreset) {
        const panelPreset = panelSurfacePresets.find(p => p.id === config.panelSurfacePreset);
        if (panelPreset) applyPanelSurfacePreset(panelPreset);
    }

    // Apply terminal colors
    if (config.terminalBackground) uiTerminalBackground.value = config.terminalBackground;
    if (config.terminalForeground) uiTerminalForeground.value = config.terminalForeground;
    if (config.terminalCursor) uiTerminalCursor.value = config.terminalCursor;
    if (config.terminalBlack) uiTerminalBlack.value = config.terminalBlack;
    if (config.terminalRed) uiTerminalRed.value = config.terminalRed;
    if (config.terminalGreen) uiTerminalGreen.value = config.terminalGreen;
    if (config.terminalYellow) uiTerminalYellow.value = config.terminalYellow;
    if (config.terminalWhite) uiTerminalWhite.value = config.terminalWhite;
    if (config.terminalCyan) uiTerminalCyan.value = config.terminalCyan;

    // Apply status colors
    if (config.statusSuccess) uiStatusSuccess.value = config.statusSuccess;
    if (config.statusWarning) uiStatusWarning.value = config.statusWarning;
    if (config.statusError) uiStatusError.value = config.statusError;
    if (config.statusInfo) uiStatusInfo.value = config.statusInfo;

    // Apply drawer/panel overrides from config
    if (config.drawerBackgroundColor) uiDrawerBackgroundColor.value = config.drawerBackgroundColor;
    if (config.drawerBackgroundOpacity !== undefined) uiDrawerBackgroundOpacity.value = config.drawerBackgroundOpacity;
    if (config.drawerCardBackgroundColor) uiDrawerCardBackgroundColor.value = config.drawerCardBackgroundColor;
    if (config.drawerBorderColor) uiDrawerBorderColor.value = config.drawerBorderColor;
    if (config.dialogContentBackgroundColor) uiDialogContentBackgroundColor.value = config.dialogContentBackgroundColor;
    if (config.dialogContentBackgroundOpacity !== undefined) uiDialogContentBackgroundOpacity.value = config.dialogContentBackgroundOpacity;

    // Apply input bar settings
    if (config.inputBarBackgroundColor) uiInputBarBackgroundColor.value = config.inputBarBackgroundColor;
    if (config.inputBarBackgroundOpacity !== undefined) uiInputBarBackgroundOpacity.value = config.inputBarBackgroundOpacity;
    if (config.inputBarBorderColor) uiInputBarBorderColor.value = config.inputBarBorderColor;

    // Apply tool card settings
    if (config.toolCardBackgroundColor) uiToolCardBackgroundColor.value = config.toolCardBackgroundColor;
    if (config.toolCardBackgroundOpacity !== undefined) uiToolCardBackgroundOpacity.value = config.toolCardBackgroundOpacity;
    if (config.toolCardBorderColor) uiToolCardBorderColor.value = config.toolCardBorderColor;

    // Apply Nixie tube colors
    if (config.nixieColor) uiNixieColor.value = config.nixieColor;
    if (config.nixieGlowColor) uiNixieGlowColor.value = config.nixieGlowColor;
    if (config.nixieButtonBackgroundColor) uiNixieButtonBackgroundColor.value = config.nixieButtonBackgroundColor;
    if (config.nixieExitColor) uiNixieExitColor.value = config.nixieExitColor;
    if (config.nixieExitGlowColor) uiNixieExitGlowColor.value = config.nixieExitGlowColor;

    // Apply sidebar settings for light themes
    if (config.sidebarBackgroundColor) uiSidebarBackgroundColor.value = config.sidebarBackgroundColor;
    if (config.sidebarBackgroundMode) uiSidebarBackgroundMode.value = config.sidebarBackgroundMode;

    // Apply user message bubble colors
    if (config.userMessageBackgroundColor) uiUserMessageBackgroundColor.value = config.userMessageBackgroundColor;
    if (config.userMessageBackgroundOpacity !== undefined) uiUserMessageBackgroundOpacity.value = config.userMessageBackgroundOpacity;
    if (config.userMessageBorderColor) uiUserMessageBorderColor.value = config.userMessageBorderColor;
    if (config.userMessageBorderOpacity !== undefined) uiUserMessageBorderOpacity.value = config.userMessageBorderOpacity;
    if (config.userMessageBackgroundMode) uiUserMessageBackgroundMode.value = config.userMessageBackgroundMode;

    // Apply assistant message bubble colors
    if (config.assistantMessageBackgroundColor) uiAssistantMessageBackgroundColor.value = config.assistantMessageBackgroundColor;
    if (config.assistantMessageBackgroundOpacity !== undefined) uiAssistantMessageBackgroundOpacity.value = config.assistantMessageBackgroundOpacity;
    if (config.assistantMessageBorderColor) uiAssistantMessageBorderColor.value = config.assistantMessageBorderColor;
    if (config.assistantMessageBorderOpacity !== undefined) uiAssistantMessageBorderOpacity.value = config.assistantMessageBorderOpacity;
    if (config.assistantMessageBackgroundMode) uiAssistantMessageBackgroundMode.value = config.assistantMessageBackgroundMode;

    // Apply header settings
    if (config.headerBackgroundColor) uiHeaderBackgroundColor.value = config.headerBackgroundColor;
    if (config.headerBackgroundMode) uiHeaderBackgroundMode.value = config.headerBackgroundMode;
};

// Handle theme mode changes (System/Dark/Light/Custom)
const handleThemeModeChange = (newMode) => {
    if (newMode === 'custom') {
        // Custom mode: re-apply the current theme preset to bypass CSS overrides completely
        if (selectedGlobalThemePreset.value) {
            // Re-apply the full theme preset - this sets native mode and all colors
            applyGlobalThemePreset();
        } else {
            // No preset selected, just set native mode to dark as fallback
            uiThemeNativeMode.value = 'dark';
            localStorage.setItem('uiThemeNativeMode', 'dark');
        }
    }
    // For System/Dark/Light modes, the CSS [data-theme] attribute handles colors
    // The watcher will call applyTheme() which sets data-theme appropriately
};

const autoThemeTokens = ref([]);
const themeTokenGroups = computed(() => {
    if (!autoThemeTokens.value.length) return THEME_TOKEN_GROUPS;
    return [
        ...THEME_TOKEN_GROUPS,
        {
            id: 'auto',
            label: 'Auto Tokens',
            tokens: autoThemeTokens.value
        }
    ];
});

const allAdvancedTokens = computed(() => {
    const seen = new Map();
    themeTokenGroups.value.forEach((group) => {
        group.tokens.forEach((token) => {
            if (!token || !token.key) return;
            if (!seen.has(token.key)) {
                seen.set(token.key, { ...token });
                return;
            }
            const existing = seen.get(token.key);
            if (!existing.label && token.label) existing.label = token.label;
            if (!existing.type && token.type) existing.type = token.type;
        });
    });
    return Array.from(seen.values());
});

// Hierarchical token section definitions organized by UI region
const hierarchicalTokenSections = [
    {
        id: 'right-rail',
        label: 'Right Rail',
        description: 'Drawer panels on the right side of the app.',
        children: [
            {
                id: 'tools-drawer',
                label: 'Tools Drawer',
                description: 'Tool history and MCP controls.',
                children: [
                    {
                        id: 'tools-drawer-surface',
                        label: 'Drawer Surface',
                        matchers: [/^--vera-drawer-bg$/, /^--vera-drawer-card-bg$/]
                    },
                    {
                        id: 'tools-tool-cards',
                        label: 'Tool Cards',
                        matchers: [/^--vera-tool-card-/, /^--vera-card-bg$/]
                    },
                    {
                        id: 'tools-filter-buttons',
                        label: 'Filter Buttons',
                        matchers: [/^--vera-filter-button-/]
                    },
                    {
                        id: 'tools-nixie-buttons',
                        label: 'Nixie Buttons',
                        matchers: [/^--vera-nixie-button-/]
                    }
                ]
            },
            {
                id: 'diagnostics-drawer',
                label: 'Diagnostics Drawer',
                description: 'System monitoring and metrics.',
                children: [
                    {
                        id: 'diag-drawer-surface',
                        label: 'Drawer Surface',
                        matchers: [/^--vera-drawer-bg$/, /^--vera-drawer-card-bg$/]
                    },
                    {
                        id: 'diag-status-indicators',
                        label: 'Status Indicators',
                        matchers: [/^--vera-status-/, /^--vera-success/, /^--vera-warning/, /^--vera-danger/, /^--vera-info/, /^--vera-error/]
                    },
                    {
                        id: 'diag-metrics',
                        label: 'Metrics & Charts',
                        matchers: [/diagnostic/i, /metric/i, /telemetry/i, /chart/i, /^--vera-grid-/]
                    },
                    {
                        id: 'diag-events',
                        label: 'Event Colors',
                        matchers: [/^--vera-event-/]
                    },
                    {
                        id: 'diag-scrollbars',
                        label: 'Scrollbars',
                        matchers: [/^--vera-scrollbar-/, /^--vera-scroll-btn-/]
                    }
                ]
            },
            {
                id: 'swarm-drawer',
                label: 'Swarm Drawer',
                description: 'Multi-agent quorum controls.',
                children: [
                    {
                        id: 'swarm-drawer-surface',
                        label: 'Drawer Surface',
                        matchers: [/^--vera-drawer-bg$/, /^--vera-drawer-card-bg$/]
                    },
                    {
                        id: 'swarm-agent-cards',
                        label: 'Agent Cards',
                        matchers: [/^--vera-card-bg$/, /swarm/i, /quorum/i]
                    }
                ]
            },
            {
                id: 'activity-drawer',
                label: 'Activity Drawer',
                description: 'Action history and logs.',
                children: [
                    {
                        id: 'activity-drawer-surface',
                        label: 'Drawer Surface',
                        matchers: [/^--vera-drawer-bg$/, /^--vera-drawer-card-bg$/]
                    },
                    {
                        id: 'activity-filter-buttons',
                        label: 'Filter Buttons',
                        matchers: [/^--vera-filter-button-/]
                    }
                ]
            },
            {
                id: 'config-drawer',
                label: 'Config Drawer',
                description: 'Model and settings configuration.',
                children: [
                    {
                        id: 'config-drawer-surface',
                        label: 'Drawer Surface',
                        matchers: [/^--vera-drawer-bg$/, /^--vera-drawer-card-bg$/]
                    },
                    {
                        id: 'config-cards',
                        label: 'Config Cards',
                        matchers: [/^--vera-card-bg$/]
                    }
                ]
            },
            {
                id: 'canvas-drawer',
                label: 'Canvas Drawer',
                description: 'Workspace file management.',
                matchers: [/^--vera-drawer-bg$/, /^--vera-drawer-card-bg$/]
            },
            {
                id: 'import-export-drawer',
                label: 'Import/Export Drawer',
                description: 'Data import and export.',
                matchers: [/^--vera-drawer-bg$/, /^--vera-drawer-card-bg$/]
            },
            {
                id: 'self-improve-drawer',
                label: 'Self-Improve Drawer',
                description: 'Agent self-improvement tools.',
                matchers: [/^--vera-drawer-bg$/, /^--vera-drawer-card-bg$/]
            }
        ]
    },
    {
        id: 'header',
        label: 'Header',
        description: 'Top navigation bar and branding.',
        children: [
            {
                id: 'header-surface',
                label: 'Header Surface',
                matchers: [/^--vera-header-bg$/, /^--vera-header-/]
            },
            {
                id: 'header-logo',
                label: 'VERA Logo',
                matchers: [/^--logo-/, /^--vera-text-header$/]
            },
            {
                id: 'header-swarm-indicator',
                label: 'Swarm Indicator',
                matchers: [/^--indicator-/, /^--orbit-/, /^--wing-/, /^--line-/, /^--consume-/, /^--glow-strength$/]
            },
            {
                id: 'header-nav-icons',
                label: 'Navigation Icons',
                matchers: [/^--vera-icon$/]
            }
        ]
    },
    {
        id: 'chat-area',
        label: 'Chat Area',
        description: 'Message display and input.',
        children: [
            {
                id: 'chat-messages',
                label: 'Messages',
                description: 'Conversation bubbles and content.',
                children: [
                    {
                        id: 'msg-user-bubbles',
                        label: 'User Messages',
                        matchers: [/^--vera-message-user-/, /^--vera-message-bg$/]
                    },
                    {
                        id: 'msg-assistant-bubbles',
                        label: 'Assistant Messages',
                        matchers: [/^--vera-message-assistant-/, /^--vera-message-bg$/]
                    },
                    {
                        id: 'msg-code-blocks',
                        label: 'Code Blocks',
                        matchers: [/^--vera-code-/, /^--vera-message-code-/]
                    },
                    {
                        id: 'msg-glow-effects',
                        label: 'Message Glow',
                        matchers: [/^--vera-message-glow$/, /^--vera-message-shadow$/, /^--vera-message-edge$/]
                    }
                ]
            },
            {
                id: 'chat-composer',
                label: 'Composer',
                description: 'Input field and controls.',
                children: [
                    {
                        id: 'composer-input-field',
                        label: 'Input Field',
                        matchers: [/^--vera-input-bg$/, /^--vera-input-text$/, /^--vera-input-border$/, /^--vera-input-/]
                    },
                    {
                        id: 'composer-send-button',
                        label: 'Send Button',
                        matchers: [/^--vera-send-button-/]
                    },
                    {
                        id: 'composer-ripple',
                        label: 'Ripple Effects',
                        matchers: [/^--vera-ripple-/]
                    }
                ]
            },
            {
                id: 'chat-avatar',
                label: 'Avatar',
                matchers: [/^--vera-avatar-/]
            },
            {
                id: 'chat-voice',
                label: 'Voice Controls',
                description: 'Voice input indicators.',
                children: [
                    {
                        id: 'voice-listening',
                        label: 'Listening State',
                        matchers: [/^--vera-voice-listening/]
                    },
                    {
                        id: 'voice-speaking',
                        label: 'Speaking State',
                        matchers: [/^--vera-voice-speaking/]
                    },
                    {
                        id: 'voice-processing',
                        label: 'Processing State',
                        matchers: [/^--vera-voice-processing/]
                    }
                ]
            }
        ]
    },
    {
        id: 'bottom-panel',
        label: 'Bottom Panel',
        description: 'Code editor, terminal, and file browser.',
        children: [
            {
                id: 'code-editor',
                label: 'Code Editor',
                matchers: [/^--vera-code-editor-/]
            },
            {
                id: 'terminal',
                label: 'Terminal',
                children: [
                    {
                        id: 'terminal-surface',
                        label: 'Terminal Surface',
                        matchers: [/^--vera-terminal-bg$/, /^--vera-terminal-header-bg$/]
                    },
                    {
                        id: 'terminal-text',
                        label: 'Terminal Text',
                        matchers: [/^--vera-terminal-text$/, /^--vera-terminal-/]
                    }
                ]
            },
            {
                id: 'file-browser',
                label: 'File Browser',
                matchers: [/^--vera-file-browser-/]
            }
        ]
    },
    {
        id: 'left-sidebar',
        label: 'Left Sidebar',
        description: 'Navigation and quick actions.',
        children: [
            {
                id: 'sidebar-surface',
                label: 'Sidebar Surface',
                matchers: [/^--vera-sidebar-bg$/, /^--vera-sidebar-/]
            },
            {
                id: 'sidebar-scroll',
                label: 'Scroll Areas',
                matchers: [/^--vera-scrollbar-/, /^--vera-scroll-btn-/]
            }
        ]
    },
    {
        id: 'dialogs',
        label: 'Dialogs & Modals',
        description: 'Overlay dialogs and settings panels.',
        children: [
            {
                id: 'dialog-surface',
                label: 'Dialog Surface',
                matchers: [/^--vera-dialog-content-bg$/, /^--vera-dialog-/]
            },
            {
                id: 'dialog-cards',
                label: 'Dialog Cards',
                matchers: [/^--vera-card-bg$/]
            }
        ]
    },
    {
        id: 'global',
        label: 'Global',
        description: 'App-wide styles and foundations.',
        children: [
            {
                id: 'global-shell',
                label: 'App Shell',
                description: 'Base backgrounds and surfaces.',
                children: [
                    {
                        id: 'shell-background',
                        label: 'Background',
                        matchers: [/^--vera-bg$/]
                    },
                    {
                        id: 'shell-surface',
                        label: 'Surfaces',
                        matchers: [/^--vera-surface$/, /^--vera-panel$/, /^--vera-panel-alt$/, /^--vera-panel-muted$/]
                    },
                    {
                        id: 'shell-text',
                        label: 'Text Colors',
                        matchers: [/^--vera-text$/, /^--vera-text-muted$/]
                    },
                    {
                        id: 'shell-borders',
                        label: 'Borders & Shadows',
                        matchers: [/^--vera-border$/, /^--vera-shadow$/]
                    }
                ]
            },
            {
                id: 'global-palette',
                label: 'Palette & Accents',
                description: 'Color ramps and tones.',
                children: [
                    {
                        id: 'palette-accent',
                        label: 'Accent Colors',
                        matchers: [/^--vera-accent/, /^--primary-color-text$/]
                    },
                    {
                        id: 'palette-secondary',
                        label: 'Secondary Colors',
                        matchers: [/^--vera-secondary/]
                    },
                    {
                        id: 'palette-status',
                        label: 'Status Colors',
                        matchers: [/^--vera-success/, /^--vera-warning/, /^--vera-danger/, /^--vera-info/, /^--vera-error/]
                    },
                    {
                        id: 'palette-channels',
                        label: 'Opacity Channels',
                        matchers: [/^--vera-black-/, /^--vera-white-/, /^--vera-contrast-/]
                    }
                ]
            },
            {
                id: 'global-effects',
                label: 'Effects & Glass',
                description: 'Visual depth and glow effects.',
                children: [
                    {
                        id: 'effects-glass',
                        label: 'Glass Effects',
                        matchers: [/^--vera-glass-/]
                    },
                    {
                        id: 'effects-glow',
                        label: 'Glow Effects',
                        matchers: [/^--vera-glow-/]
                    },
                    {
                        id: 'effects-panel-depth',
                        label: 'Panel Depth',
                        matchers: [/^--vera-panel-shadow$/, /^--vera-panel-edge$/, /^--vera-panel-inner-glow$/, /^--vera-panel-bevel$/]
                    }
                ]
            },
            {
                id: 'global-motion',
                label: 'Motion & Timing',
                description: 'Animation timing tokens.',
                matchers: [/^--stream-/, /^--split-/]
            }
        ]
    }
];

// State for expanded accordion sections
const expandedSections = ref(new Set(['right-rail', 'chat-area', 'global']));

const toggleSection = (sectionId) => {
    if (expandedSections.value.has(sectionId)) {
        expandedSections.value.delete(sectionId);
    } else {
        expandedSections.value.add(sectionId);
    }
    expandedSections.value = new Set(expandedSections.value); // Trigger reactivity
};

const isSectionExpanded = (sectionId) => expandedSections.value.has(sectionId);

const expandAllSections = () => {
    const collectIds = (sections) => {
        const ids = [];
        for (const section of sections) {
            ids.push(section.id);
            if (section.children) ids.push(...collectIds(section.children));
        }
        return ids;
    };
    expandedSections.value = new Set(collectIds(hierarchicalTokenSections));
};

const collapseAllSections = () => {
    expandedSections.value = new Set();
};

const tokenMatchesPattern = (token, pattern) => {
    if (!pattern || !token || !token.key) return false;
    if (typeof pattern === 'string') return token.key === pattern;
    if (pattern instanceof RegExp) return pattern.test(token.key);
    if (typeof pattern === 'function') return Boolean(pattern(token));
    return false;
};

const tokenMatchesSection = (token, section) => {
    if (!section) return false;
    if (Array.isArray(section.keys) && section.keys.includes(token.key)) return true;
    if (!Array.isArray(section.matchers)) return false;
    return section.matchers.some((pattern) => tokenMatchesPattern(token, pattern));
};

// Process hierarchical sections recursively to attach matching tokens
const processHierarchicalSections = (sections, tokens, matchedKeys) => {
    return sections.map((section) => {
        const processed = {
            id: section.id,
            label: section.label,
            description: section.description || null
        };

        // If section has direct matchers, find matching tokens
        if (section.matchers && Array.isArray(section.matchers)) {
            processed.tokens = tokens.filter((token) => {
                const matches = section.matchers.some((pattern) => tokenMatchesPattern(token, pattern));
                if (matches) matchedKeys.add(token.key);
                return matches;
            });
        } else {
            processed.tokens = [];
        }

        // Recursively process children
        if (section.children && Array.isArray(section.children)) {
            processed.children = processHierarchicalSections(section.children, tokens, matchedKeys);
            // Filter out empty children (no tokens and no non-empty grandchildren)
            processed.children = processed.children.filter((child) => {
                const hasTokens = child.tokens && child.tokens.length > 0;
                const hasChildren = child.children && child.children.length > 0;
                return hasTokens || hasChildren;
            });
        }

        return processed;
    }).filter((section) => {
        // Keep section if it has tokens or non-empty children
        const hasTokens = section.tokens && section.tokens.length > 0;
        const hasChildren = section.children && section.children.length > 0;
        return hasTokens || hasChildren;
    });
};

// Count total tokens in a section (including nested children)
const countSectionTokens = (section) => {
    let count = section.tokens ? section.tokens.length : 0;
    if (section.children) {
        for (const child of section.children) {
            count += countSectionTokens(child);
        }
    }
    return count;
};

const advancedTokenTree = computed(() => {
    const tokens = allAdvancedTokens.value;
    const matchedKeys = new Set();
    const tree = processHierarchicalSections(hierarchicalTokenSections, tokens, matchedKeys);

    // Collect unmatched tokens into "Other" section
    const unmatchedTokens = tokens.filter((token) => !matchedKeys.has(token.key));
    if (unmatchedTokens.length) {
        tree.push({
            id: 'unmapped',
            label: 'Other',
            description: 'Tokens not yet matched to a component section.',
            tokens: unmatchedTokens,
            children: []
        });
    }

    return tree;
});

// Legacy flat sections for backwards compatibility (if needed elsewhere)
const advancedTokenSections = computed(() => {
    const flattenSections = (sections, result = []) => {
        for (const section of sections) {
            if (section.tokens && section.tokens.length > 0) {
                result.push({
                    id: section.id,
                    label: section.label,
                    description: section.description,
                    tokens: section.tokens
                });
            }
            if (section.children) {
                flattenSections(section.children, result);
            }
        }
        return result;
    };
    return flattenSections(advancedTokenTree.value);
});

const tokenHighlightMap = {
    '--vera-bg': ['.app-container', '.app-body'],
    '--vera-surface': ['.app-container', '.chat'],
    '--vera-panel': ['.drawer-card', '.tools-dialog [class*="card"]', '.sidebar-drawer'],
    '--vera-panel-alt': ['.drawer-card', '.tools-dialog [class*="card"]'],
    '--vera-panel-muted': ['.drawer-card', '.theme-group'],
    '--vera-text': ['.message-contents', '.header'],
    '--vera-text-muted': ['.message-contents', '.header'],
    '--vera-border': ['.drawer-card', '.input-container'],
    '--vera-shadow': ['.drawer-card', '.tools-dialog [class*="card"]'],
    '--vera-icon': ['.header svg', '.tools-dialog svg'],
    '--vera-accent': ['.tab-indicator', '.accent-swatch', '.filter-chip.active'],
    '--vera-accent-strong': ['.tab-indicator', '.accent-swatch'],
    '--vera-accent-soft': ['.tab-indicator', '.accent-swatch'],
    '--vera-accent-faint': ['.tab-indicator', '.accent-swatch'],
    '--vera-secondary': ['.tab-indicator', '.accent-swatch'],
    '--vera-success': ['.status-dot.online', '.swarm-indicator'],
    '--vera-warning': ['.status-dot.away', '.swarm-indicator'],
    '--vera-danger': ['.status-dot.busy', '.swarm-indicator'],
    '--vera-info': ['.swarm-indicator'],
    '--primary-color-text': ['.header', '.settings-dialog'],
    '--vera-header-bg': ['.header'],
    '--vera-sidebar-bg': ['.sidebar-common', '.sidebar-conversations', '.sidebar-drawer'],
    '--vera-input-bg': ['.input-container', '#user-input'],
    '--vera-input-text': ['#user-input'],
    '--vera-input-bar-bg': ['.input-container'],
    '--vera-input-bar-border': ['.input-container'],
    '--vera-input-bar-glow': ['.input-container'],
    '--vera-tool-card-bg': ['.tools-dialog [class*="card"]'],
    '--vera-tool-card-border': ['.tools-dialog [class*="card"]'],
    '--vera-tool-card-glow': ['.tools-dialog [class*="card"]'],
    '--vera-message-user-bg': ['.message.user'],
    '--vera-message-assistant-bg': ['.message.gpt'],
    '--vera-message-user-border': ['.message.user'],
    '--vera-message-assistant-border': ['.message.gpt'],
    '--vera-code-bg': ['.message-contents pre', '.code-editor-panel'],
    '--vera-code-border': ['.message-contents pre', '.code-editor-panel'],
    '--vera-drawer-bg': ['.sidebar-drawer', '.sidebar-common'],
    '--vera-drawer-border': ['.sidebar-drawer', '.sidebar-common'],
    '--vera-drawer-card-bg': ['.drawer-card'],
    '--vera-code-editor-bg': ['.code-editor-panel'],
    '--vera-terminal-bg': ['.terminal-panel'],
    '--vera-terminal-header-bg': ['.terminal-header'],
    '--vera-file-browser-bg': ['.file-browser'],
    '--vera-dialog-content-bg': ['.dialog-content', '.settings-container'],
    '--vera-card-bg': ['.drawer-card'],
    '--vera-filter-button-bg': ['.filter-chip'],
    '--vera-filter-button-active-bg': ['.filter-chip.active'],
    '--vera-nixie-button-bg': ['.nixie-icon-btn', '.nixie-icon-container', '.nixie-display']
};

const isBackgroundToken = (token) => Boolean(token && token.type === 'color');

const tokenBackgroundSettings = reactive({});

const createBackgroundSettings = () => ({
    mode: 'solid',
    color: DEFAULT_THEME_RESET.backgroundColor,
    opacity: 1,
    preset: DEFAULT_BACKGROUND_PRESET,
    gradientStart: DEFAULT_THEME_RESET.backgroundGradientStart,
    gradientEnd: DEFAULT_THEME_RESET.backgroundGradientEnd,
    gradientAngle: DEFAULT_THEME_RESET.backgroundGradientAngle
});

const getTokenBackgroundSettings = (tokenKey) => {
    if (!tokenBackgroundSettings[tokenKey]) {
        tokenBackgroundSettings[tokenKey] = createBackgroundSettings();
    }
    return tokenBackgroundSettings[tokenKey];
};

const clampNumber = (value, min, max) => Math.min(max, Math.max(min, value));

const normalizeHex = (value) => {
    if (!value || typeof value !== 'string') return '';
    const trimmed = value.trim();
    if (!/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(trimmed)) return '';
    if (trimmed.length === 4) {
        const [r, g, b] = trimmed.slice(1).split('');
        return `#${r}${r}${g}${g}${b}${b}`;
    }
    return trimmed;
};

const hexToRgb = (hex) => {
    const normalized = normalizeHex(hex);
    if (!normalized) return null;
    const value = normalized.replace('#', '');
    const r = parseInt(value.slice(0, 2), 16);
    const g = parseInt(value.slice(2, 4), 16);
    const b = parseInt(value.slice(4, 6), 16);
    if ([r, g, b].some((channel) => Number.isNaN(channel))) return null;
    return { r, g, b };
};

const toRgba = (hex, opacity) => {
    const rgb = hexToRgb(hex);
    if (!rgb) return hex || '';
    const alpha = clampNumber(opacity ?? 1, 0, 1);
    if (alpha >= 0.999) return normalizeHex(hex) || hex;
    return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
};

const buildGradientValue = (settings) => {
    const angle = clampNumber(settings.gradientAngle ?? 0, 0, 360);
    const start = settings.gradientStart || DEFAULT_THEME_RESET.backgroundGradientStart;
    const end = settings.gradientEnd || DEFAULT_THEME_RESET.backgroundGradientEnd;
    return `linear-gradient(${angle}deg, ${start}, ${end})`;
};

const applyTokenBackgroundSettings = (tokenKey) => {
    const settings = getTokenBackgroundSettings(tokenKey);
    let value = '';
    switch (settings.mode) {
        case 'transparent':
            value = 'transparent';
            break;
        case 'glass-light':
            value = 'var(--vera-glass-bg)';
            break;
        case 'glass-strong':
            value = 'var(--vera-glass-strong)';
            break;
        case 'preset': {
            const presetValue = BACKGROUND_PRESETS[settings.preset]?.value
                || BACKGROUND_PRESETS[DEFAULT_BACKGROUND_PRESET]?.value
                || '';
            value = presetValue;
            break;
        }
        case 'gradient':
            value = buildGradientValue(settings);
            break;
        case 'solid':
        default:
            value = toRgba(settings.color, settings.opacity);
            break;
    }
    if (value) {
        setOverrideValue(tokenKey, value);
    }
};

const highlightedNodes = [];
let activeHighlightToken = '';

const clearTokenHighlight = () => {
    highlightedNodes.forEach((node) => node.classList.remove('theme-token-highlight'));
    highlightedNodes.length = 0;
    activeHighlightToken = '';
};

const getTokenHighlightSelectors = (tokenKey) => {
    if (tokenHighlightMap[tokenKey]) return tokenHighlightMap[tokenKey];
    const normalized = tokenKey.toLowerCase();
    if (normalized.includes('terminal')) return ['.terminal-panel', '.terminal-header'];
    if (normalized.includes('code-editor') || normalized.includes('code-bg')) return ['.code-editor-panel'];
    if (normalized.includes('file-browser')) return ['.file-browser'];
    if (normalized.includes('dialog')) return ['.dialog-content', '.settings-container'];
    if (normalized.includes('drawer')) return ['.sidebar-drawer', '.sidebar-common'];
    if (normalized.includes('sidebar')) return ['.sidebar-common', '.sidebar-conversations', '.sidebar-drawer'];
    if (normalized.includes('header')) return ['.header'];
    if (normalized.includes('message')) return ['.message'];
    if (normalized.includes('input')) return ['.input-container', '#user-input'];
    if (normalized.includes('tool-card')) return ['.tools-dialog [class*="card"]'];
    if (normalized.includes('card')) return ['.drawer-card'];
    if (normalized.includes('filter-button')) return ['.filter-chip'];
    if (normalized.includes('nixie')) return ['.nixie-icon-btn', '.nixie-icon-container', '.nixie-display'];
    if (normalized.includes('swarm') || normalized.includes('orbit') || normalized.includes('wing')) return ['.swarm-indicator'];
    return ['.appearance-panel'];
};

const highlightTokenTargets = (tokenKey) => {
    if (typeof window === 'undefined' || !tokenKey) return;
    if (activeHighlightToken === tokenKey) return;
    clearTokenHighlight();
    const selectors = getTokenHighlightSelectors(tokenKey);
    if (!selectors.length) return;
    const selectorList = Array.from(new Set(selectors)).join(', ');
    document.querySelectorAll(selectorList).forEach((node) => {
        node.classList.add('theme-token-highlight');
        highlightedNodes.push(node);
    });
    activeHighlightToken = tokenKey;
};
const customPanelPresets = uiPanelSurfacePresets;
const panelSurfacePresets = computed(() => [
    ...PANEL_SURFACE_PRESETS,
    ...customPanelPresets.value
]);

const panelPresetName = ref('Custom Panel Preset');
const panelPresetJson = ref('');
const panelPresetFileInput = ref(null);
const isPanelPresetDragging = ref(false);
const panelPresetEditingId = ref('');

const panelPresetFields = [
    { key: 'drawerBackgroundMode', ref: uiDrawerBackgroundMode, type: 'string' },
    { key: 'drawerBackgroundPreset', ref: uiDrawerBackgroundPreset, type: 'string' },
    { key: 'drawerBackgroundColor', ref: uiDrawerBackgroundColor, type: 'string' },
    { key: 'drawerBackgroundOpacity', ref: uiDrawerBackgroundOpacity, type: 'number' },
    { key: 'drawerBorderColor', ref: uiDrawerBorderColor, type: 'string' },
    { key: 'drawerBorderOpacity', ref: uiDrawerBorderOpacity, type: 'number' },
    { key: 'drawerCardBackgroundMode', ref: uiDrawerCardBackgroundMode, type: 'string' },
    { key: 'drawerCardBackgroundColor', ref: uiDrawerCardBackgroundColor, type: 'string' },
    { key: 'drawerCardBackgroundOpacity', ref: uiDrawerCardBackgroundOpacity, type: 'number' },
    { key: 'codeEditorBackgroundColor', ref: uiCodeEditorBackgroundColor, type: 'string' },
    { key: 'codeEditorBackgroundOpacity', ref: uiCodeEditorBackgroundOpacity, type: 'number' },
    { key: 'terminalBackgroundColor', ref: uiTerminalBackgroundColor, type: 'string' },
    { key: 'terminalBackgroundOpacity', ref: uiTerminalBackgroundOpacity, type: 'number' },
    { key: 'terminalHeaderBackgroundColor', ref: uiTerminalHeaderBackgroundColor, type: 'string' },
    { key: 'terminalHeaderBackgroundOpacity', ref: uiTerminalHeaderBackgroundOpacity, type: 'number' },
    { key: 'fileBrowserBackgroundColor', ref: uiFileBrowserBackgroundColor, type: 'string' },
    { key: 'fileBrowserBackgroundOpacity', ref: uiFileBrowserBackgroundOpacity, type: 'number' },
    { key: 'dialogContentBackgroundColor', ref: uiDialogContentBackgroundColor, type: 'string' },
    { key: 'dialogContentBackgroundOpacity', ref: uiDialogContentBackgroundOpacity, type: 'number' },
    { key: 'cardBackgroundColor', ref: uiCardBackgroundColor, type: 'string' },
    { key: 'cardBackgroundOpacity', ref: uiCardBackgroundOpacity, type: 'number' },
    { key: 'filterButtonBackgroundColor', ref: uiFilterButtonBackgroundColor, type: 'string' },
    { key: 'filterButtonBackgroundOpacity', ref: uiFilterButtonBackgroundOpacity, type: 'number' },
    { key: 'filterButtonActiveBackgroundColor', ref: uiFilterButtonActiveBackgroundColor, type: 'string' },
    { key: 'filterButtonActiveBackgroundOpacity', ref: uiFilterButtonActiveBackgroundOpacity, type: 'number' }
];

const isHexColorValue = (value) =>
    /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(value.trim());

const collectAutoThemeTokens = () => {
    if (typeof window === 'undefined') return;
    const styles = getComputedStyle(document.documentElement);
    const tokens = [];
    const seen = new Set();
    for (let i = 0; i < styles.length; i += 1) {
        const name = styles[i];
        if (!name) continue;
        if (name !== '--primary-color-text' && !name.startsWith('--vera-')) continue;
        if (THEME_TOKEN_INDEX[name]) continue;
        if (seen.has(name)) continue;
        seen.add(name);
        const value = styles.getPropertyValue(name).trim();
        tokens.push({
            key: name,
            label: name.replace(/^--/, ''),
            type: isHexColorValue(value) ? 'color' : 'text'
        });
    }
    tokens.sort((a, b) => a.key.localeCompare(b.key));
    autoThemeTokens.value = tokens;
};

const panelPresetNumberTolerance = 0.01;
const lastPanelPresetLabel = ref('None');
const lastPanelPresetValues = ref(null);

const getPanelPresetValues = () => panelPresetFields.reduce((acc, field) => {
    if (field.type === 'number') {
        const numericValue = Number(field.ref.value);
        acc[field.key] = Number.isFinite(numericValue) ? numericValue : 0;
    } else {
        acc[field.key] = field.ref.value ?? '';
    }
    return acc;
}, {});

const normalizePresetString = (value) => String(value ?? '').trim().toLowerCase();

const isPanelPresetActive = (preset) => {
    if (!preset || !preset.values) return false;
    return panelPresetFields.every((field) => {
        const presetValue = preset.values[field.key];
        if (presetValue === undefined) return false;
        if (field.type === 'number') {
            const currentValue = Number(field.ref.value);
            const presetNumber = Number(presetValue);
            if (!Number.isFinite(currentValue) || !Number.isFinite(presetNumber)) return false;
            return Math.abs(currentValue - presetNumber) <= panelPresetNumberTolerance;
        }
        return normalizePresetString(field.ref.value) === normalizePresetString(presetValue);
    });
};

const activePanelPresetId = computed(() => {
    const match = panelSurfacePresets.value.find((preset) => isPanelPresetActive(preset));
    return match ? match.id : '';
});

const activePanelPresetLabel = computed(() => {
    const match = panelSurfacePresets.value.find((preset) => preset.id === activePanelPresetId.value);
    return match ? match.label : 'Custom';
});

const panelPresetBaseline = computed(() => {
    if (lastPanelPresetValues.value) return lastPanelPresetValues.value;
    const match = panelSurfacePresets.value.find((preset) => preset.id === activePanelPresetId.value);
    return match ? match.values : null;
});

const panelPresetBaselineLabel = computed(() => {
    if (lastPanelPresetValues.value) return lastPanelPresetLabel.value;
    return activePanelPresetId.value ? activePanelPresetLabel.value : 'None';
});

const isPanelPresetEditing = computed(() => Boolean(panelPresetEditingId.value));

const panelPresetSaveLabel = computed(() => (isPanelPresetEditing.value ? 'Update Preset' : 'Save Preset'));

const panelPresetEditingLabel = computed(() => {
    if (!panelPresetEditingId.value) return '';
    const match = customPanelPresets.value.find((preset) => preset.id === panelPresetEditingId.value);
    return match ? match.label : '';
});

const isCustomPanelPreset = (preset) => customPanelPresets.value.some((item) => item.id === preset.id);

const setPanelSurfaceValues = (values) => {
    uiDrawerBackgroundMode.value = values.drawerBackgroundMode;
    uiDrawerBackgroundPreset.value = values.drawerBackgroundPreset;
    uiDrawerBackgroundColor.value = values.drawerBackgroundColor;
    uiDrawerBackgroundOpacity.value = values.drawerBackgroundOpacity;
    uiDrawerBorderColor.value = values.drawerBorderColor;
    uiDrawerBorderOpacity.value = values.drawerBorderOpacity;
    uiDrawerCardBackgroundMode.value = values.drawerCardBackgroundMode;
    uiDrawerCardBackgroundColor.value = values.drawerCardBackgroundColor;
    uiDrawerCardBackgroundOpacity.value = values.drawerCardBackgroundOpacity;
    uiCodeEditorBackgroundColor.value = values.codeEditorBackgroundColor;
    uiCodeEditorBackgroundOpacity.value = values.codeEditorBackgroundOpacity;
    uiTerminalBackgroundColor.value = values.terminalBackgroundColor;
    uiTerminalBackgroundOpacity.value = values.terminalBackgroundOpacity;
    uiTerminalHeaderBackgroundColor.value = values.terminalHeaderBackgroundColor;
    uiTerminalHeaderBackgroundOpacity.value = values.terminalHeaderBackgroundOpacity;
    uiFileBrowserBackgroundColor.value = values.fileBrowserBackgroundColor;
    uiFileBrowserBackgroundOpacity.value = values.fileBrowserBackgroundOpacity;
    uiDialogContentBackgroundColor.value = values.dialogContentBackgroundColor;
    uiDialogContentBackgroundOpacity.value = values.dialogContentBackgroundOpacity;
    uiCardBackgroundColor.value = values.cardBackgroundColor;
    uiCardBackgroundOpacity.value = values.cardBackgroundOpacity;
    uiFilterButtonBackgroundColor.value = values.filterButtonBackgroundColor;
    uiFilterButtonBackgroundOpacity.value = values.filterButtonBackgroundOpacity;
    uiFilterButtonActiveBackgroundColor.value = values.filterButtonActiveBackgroundColor;
    uiFilterButtonActiveBackgroundOpacity.value = values.filterButtonActiveBackgroundOpacity;
};

const buildPanelPresetPayload = (label, values) => ({
    version: 1,
    label,
    values
});

const panelPresetFieldLabels = {
    drawerBackgroundMode: 'Drawer mode',
    drawerBackgroundPreset: 'Drawer preset',
    drawerBackgroundColor: 'Drawer background',
    drawerBackgroundOpacity: 'Drawer opacity',
    drawerBorderColor: 'Drawer border',
    drawerBorderOpacity: 'Drawer border opacity',
    drawerCardBackgroundMode: 'Drawer card mode',
    drawerCardBackgroundColor: 'Drawer card background',
    drawerCardBackgroundOpacity: 'Drawer card opacity',
    codeEditorBackgroundColor: 'Code editor background',
    codeEditorBackgroundOpacity: 'Code editor opacity',
    terminalBackgroundColor: 'Terminal background',
    terminalBackgroundOpacity: 'Terminal opacity',
    terminalHeaderBackgroundColor: 'Terminal header background',
    terminalHeaderBackgroundOpacity: 'Terminal header opacity',
    fileBrowserBackgroundColor: 'File browser background',
    fileBrowserBackgroundOpacity: 'File browser opacity',
    dialogContentBackgroundColor: 'Dialog background',
    dialogContentBackgroundOpacity: 'Dialog opacity',
    cardBackgroundColor: 'Card background',
    cardBackgroundOpacity: 'Card opacity',
    filterButtonBackgroundColor: 'Filter button background',
    filterButtonBackgroundOpacity: 'Filter button opacity',
    filterButtonActiveBackgroundColor: 'Filter active background',
    filterButtonActiveBackgroundOpacity: 'Filter active opacity'
};

const formatPanelPresetValue = (value, type) => {
    if (type === 'number') {
        const numericValue = Number(value);
        if (!Number.isFinite(numericValue)) return '0.00';
        return numericValue.toFixed(2);
    }
    return String(value ?? '');
};

const panelPresetDiffs = computed(() => {
    const baseline = panelPresetBaseline.value;
    if (!baseline) return [];
    return panelPresetFields.reduce((acc, field) => {
        const baselineValue = baseline[field.key];
        if (baselineValue === undefined) return acc;
        if (field.type === 'number') {
            const currentValue = Number(field.ref.value);
            const presetNumber = Number(baselineValue);
            if (!Number.isFinite(currentValue) || !Number.isFinite(presetNumber)) return acc;
            if (Math.abs(currentValue - presetNumber) > panelPresetNumberTolerance) {
                acc.push({
                    key: field.key,
                    label: panelPresetFieldLabels[field.key] || field.key,
                    current: formatPanelPresetValue(currentValue, field.type),
                    baseline: formatPanelPresetValue(presetNumber, field.type)
                });
            }
            return acc;
        }
        if (normalizePresetString(field.ref.value) !== normalizePresetString(baselineValue)) {
            acc.push({
                key: field.key,
                label: panelPresetFieldLabels[field.key] || field.key,
                current: formatPanelPresetValue(field.ref.value, field.type),
                baseline: formatPanelPresetValue(baselineValue, field.type)
            });
        }
        return acc;
    }, []);
});

const applyPanelSurfacePreset = (preset) => {
    if (!preset || !preset.values) return;
    const values = { ...getPanelPresetValues(), ...preset.values };
    setPanelSurfaceValues(values);
    if (preset.label) {
        panelPresetName.value = preset.label;
    }
    lastPanelPresetLabel.value = preset.label || 'Custom';
    lastPanelPresetValues.value = getPanelPresetValues();
    panelPresetJson.value = JSON.stringify(buildPanelPresetPayload(lastPanelPresetLabel.value, lastPanelPresetValues.value), null, 2);
    panelPresetEditingId.value = isCustomPanelPreset(preset) ? preset.id : '';
};

const panelPresetPreviewStyle = (preset) => {
    const primary = preset?.preview?.primary || 'var(--vera-panel)';
    const secondary = preset?.preview?.secondary || 'var(--vera-panel-alt)';
    const accent = preset?.preview?.accent || 'var(--vera-accent)';
    return {
        background: `linear-gradient(135deg, ${primary} 0%, ${primary} 44%, ${secondary} 44%, ${secondary} 72%, ${accent} 72%, ${accent} 100%)`
    };
};

const parsePanelPresetJson = (json) => {
    try {
        const parsed = JSON.parse(json);
        const values = parsed?.values && typeof parsed.values === 'object'
            ? parsed.values
            : parsed && typeof parsed === 'object'
                ? parsed
                : null;
        if (!values || typeof values !== 'object') {
            return { error: 'Invalid panel preset format' };
        }
        const label = typeof parsed?.label === 'string' && parsed.label.trim()
            ? parsed.label.trim()
            : 'Imported preset';
        return { label, values };
    } catch (error) {
        return { error: 'Invalid JSON preset' };
    }
};

const applyPanelPresetJson = (json) => {
    const result = parsePanelPresetJson(json);
    if (result.error) {
        showToast(result.error, 'error');
        return;
    }
    panelPresetName.value = result.label;
    applyPanelSurfacePreset({ label: result.label, values: result.values });
    showToast('Panel preset imported');
};

const exportPanelPreset = async () => {
    const payload = buildPanelPresetPayload(panelPresetName.value || 'Custom Panel Preset', getPanelPresetValues());
    const json = JSON.stringify(payload, null, 2);
    panelPresetJson.value = json;
    try {
        if (navigator?.clipboard?.writeText) {
            await navigator.clipboard.writeText(json);
            showToast('Panel preset copied to clipboard');
        } else {
            showToast('Panel preset JSON ready to copy');
        }
    } catch (error) {
        showToast('Panel preset JSON ready to copy');
    }
};

const downloadPanelPreset = () => {
    const payload = buildPanelPresetPayload(panelPresetName.value || 'Custom Panel Preset', getPanelPresetValues());
    const json = JSON.stringify(payload, null, 2);
    const safeName = (panelPresetName.value || 'panel-preset')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/(^-|-$)/g, '');
    const fileName = `${safeName || 'panel-preset'}.json`;
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    link.click();
    URL.revokeObjectURL(url);
    showToast('Panel preset downloaded');
};

const importPanelPreset = () => {
    if (!panelPresetJson.value) {
        showToast('Paste a panel preset JSON first', 'error');
        return;
    }
    applyPanelPresetJson(panelPresetJson.value);
};

const buildPanelPresetPreview = (values) => ({
    primary: values.drawerBackgroundColor || 'var(--vera-panel)',
    secondary: values.drawerCardBackgroundColor || values.cardBackgroundColor || 'var(--vera-panel-alt)',
    accent: values.drawerBorderColor || values.filterButtonActiveBackgroundColor || 'var(--vera-accent)'
});

const savePanelPreset = () => {
    const label = panelPresetName.value || 'Custom Panel Preset';
    const values = getPanelPresetValues();
    const preview = buildPanelPresetPreview(values);
    if (panelPresetEditingId.value) {
        const existingIndex = customPanelPresets.value.findIndex(
            (preset) => preset.id === panelPresetEditingId.value
        );
        if (existingIndex >= 0) {
            customPanelPresets.value[existingIndex] = {
                ...customPanelPresets.value[existingIndex],
                label,
                preview,
                values
            };
        } else {
            customPanelPresets.value.push({
                id: panelPresetEditingId.value,
                label,
                description: 'Saved preset',
                preview,
                values
            });
        }
        panelPresetEditingId.value = '';
    } else {
        const normalizedLabel = normalizePresetString(label);
        const existingIndex = customPanelPresets.value.findIndex(
            (preset) => normalizePresetString(preset.label) === normalizedLabel
        );
        if (existingIndex >= 0) {
            customPanelPresets.value[existingIndex] = {
                ...customPanelPresets.value[existingIndex],
                label,
                preview,
                values
            };
        } else {
            customPanelPresets.value.push({
                id: `custom-${Date.now()}`,
                label,
                description: 'Saved preset',
                preview,
                values
            });
        }
    }
    lastPanelPresetLabel.value = label;
    lastPanelPresetValues.value = { ...values };
    panelPresetJson.value = JSON.stringify(buildPanelPresetPayload(label, values), null, 2);
    showToast('Panel preset saved');
};

const startPanelPresetRename = (preset) => {
    if (!isCustomPanelPreset(preset)) return;
    panelPresetEditingId.value = preset.id;
    panelPresetName.value = preset.label;
    panelPresetJson.value = JSON.stringify(buildPanelPresetPayload(preset.label, preset.values), null, 2);
};

const cancelPanelPresetEdit = () => {
    panelPresetEditingId.value = '';
};

const deleteCustomPanelPreset = (preset) => {
    if (!isCustomPanelPreset(preset)) return;
    const confirmed = window.confirm(`Delete panel preset "${preset.label}"?`);
    if (!confirmed) return;
    customPanelPresets.value = customPanelPresets.value.filter((item) => item.id !== preset.id);
    if (panelPresetEditingId.value === preset.id) {
        panelPresetEditingId.value = '';
    }
    showToast('Panel preset deleted');
};

const resetPanelPresetBaseline = () => {
    const baseline = panelPresetBaseline.value;
    if (!baseline) {
        showToast('No baseline preset to reset to', 'error');
        return;
    }
    const values = { ...getPanelPresetValues(), ...baseline };
    setPanelSurfaceValues(values);
    showToast(`Reset to ${panelPresetBaselineLabel.value}`);
};

const handlePanelPresetFile = async (file) => {
    if (!file) return;
    const isJson = file.name.toLowerCase().endsWith('.json');
    if (!isJson) {
        showToast('Please upload a JSON preset file', 'error');
        return;
    }
    try {
        const json = await file.text();
        panelPresetJson.value = json;
        applyPanelPresetJson(json);
    } catch (error) {
        showToast('Failed to read preset file', 'error');
    }
};

const handlePanelPresetFileInput = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    await handlePanelPresetFile(file);
    event.target.value = '';
};

const handlePanelPresetFileDrop = async (event) => {
    isPanelPresetDragging.value = false;
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    await handlePanelPresetFile(file);
};

const triggerPanelPresetFileInput = () => {
    panelPresetFileInput.value?.click();
};

const getOverrideValue = (tokenKey) => {
    const overrides = uiThemeOverrides.value || {};
    const value = overrides[tokenKey];
    return value === undefined || value === null ? '' : String(value);
};

const setOverrideValue = (tokenKey, value) => {
    const nextOverrides = { ...(uiThemeOverrides.value || {}) };
    if (!value) {
        delete nextOverrides[tokenKey];
    } else {
        nextOverrides[tokenKey] = value;
    }
    uiThemeOverrides.value = nextOverrides;
};

const resetOverrideValue = (tokenKey) => {
    const nextOverrides = { ...(uiThemeOverrides.value || {}) };
    delete nextOverrides[tokenKey];
    uiThemeOverrides.value = nextOverrides;
};

const resetAllOverrides = () => {
    uiThemeOverrides.value = {};
};

const getComputedTokenValue = (tokenKey) => {
    if (typeof window === 'undefined') return '';
    return getComputedStyle(document.documentElement).getPropertyValue(tokenKey).trim();
};

const extractHexColor = (value) => {
    if (!value) return '';
    const trimmed = value.trim();
    return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(trimmed)
        ? trimmed
        : '';
};

const getTokenColorValue = (tokenKey) => {
    const overrideHex = extractHexColor(getOverrideValue(tokenKey));
    if (overrideHex) return overrideHex;
    const computedHex = extractHexColor(getComputedTokenValue(tokenKey));
    return computedHex || DEFAULT_TOKEN_COLOR_FALLBACK;
};

// Reset functions for new color sections
const resetTerminalColors = () => {
    uiTerminalBackground.value = DEFAULT_TERMINAL_COLORS.background;
    uiTerminalForeground.value = DEFAULT_TERMINAL_COLORS.foreground;
    uiTerminalCursor.value = DEFAULT_TERMINAL_COLORS.cursor;
    uiTerminalSelection.value = DEFAULT_TERMINAL_COLORS.selection;
    uiTerminalBlack.value = DEFAULT_TERMINAL_COLORS.black;
    uiTerminalRed.value = DEFAULT_TERMINAL_COLORS.red;
    uiTerminalGreen.value = DEFAULT_TERMINAL_COLORS.green;
    uiTerminalYellow.value = DEFAULT_TERMINAL_COLORS.yellow;
    uiTerminalBlue.value = DEFAULT_TERMINAL_COLORS.blue;
    uiTerminalMagenta.value = DEFAULT_TERMINAL_COLORS.magenta;
    uiTerminalCyan.value = DEFAULT_TERMINAL_COLORS.cyan;
    uiTerminalWhite.value = DEFAULT_TERMINAL_COLORS.white;
};

const resetStatusColors = () => {
    // Status colors
    uiStatusSuccess.value = DEFAULT_STATUS_COLORS.success;
    uiStatusWarning.value = DEFAULT_STATUS_COLORS.warning;
    uiStatusError.value = DEFAULT_STATUS_COLORS.error;
    uiStatusInfo.value = DEFAULT_STATUS_COLORS.info;
    // Event colors
    uiEventRouting.value = DEFAULT_EVENT_COLORS.routing;
    uiEventMemory.value = DEFAULT_EVENT_COLORS.memory;
    uiEventTool.value = DEFAULT_EVENT_COLORS.tool;
    uiEventDecision.value = DEFAULT_EVENT_COLORS.decision;
    uiEventQuorum.value = DEFAULT_EVENT_COLORS.quorum;
    // Git colors
    uiGitAdded.value = DEFAULT_GIT_COLORS.added;
    uiGitModified.value = DEFAULT_GIT_COLORS.modified;
    uiGitDeleted.value = DEFAULT_GIT_COLORS.deleted;
    uiGitUntracked.value = DEFAULT_GIT_COLORS.untracked;
};

// Tab bar with floating indicator
const tabsRef = ref(null);
const themeTabsRef = ref(null);
const panelTabsRef = ref(null);
const isDraggingFile = ref(false);

// Computed style for the floating tab indicator
const tabIndicatorStyle = computed(() => {
    tabIndicatorKey.value;
    if (!tabsRef.value) return { opacity: 0 };
    const activeButton = tabsRef.value.querySelector(`button[data-tab="${activeTab.value}"]`);
    if (!activeButton) return { opacity: 0 };
    return {
        width: `${activeButton.offsetWidth}px`,
        transform: `translateX(${activeButton.offsetLeft}px)`,
        opacity: 1
    };
});

const themeTabIndicatorStyle = computed(() => {
    themeTabIndicatorKey.value;
    if (!themeTabsRef.value) return { opacity: 0 };
    const activeButton = themeTabsRef.value.querySelector(`button[data-tab="${activeThemeTab.value}"]`);
    if (!activeButton) return { opacity: 0 };
    return {
        width: `${activeButton.offsetWidth}px`,
        transform: `translateX(${activeButton.offsetLeft}px)`,
        opacity: 1
    };
});

const panelTabIndicatorStyle = computed(() => {
    panelTabIndicatorKey.value;
    if (activeThemeTab.value !== 'panels' || !panelTabsRef.value) return { opacity: 0 };
    const activeButton = panelTabsRef.value.querySelector(`button[data-tab="${activePanelTab.value}"]`);
    if (!activeButton) return { opacity: 0 };
    return {
        width: `${activeButton.offsetWidth}px`,
        transform: `translateX(${activeButton.offsetLeft}px)`,
        opacity: 1
    };
});

// Current avatar preview image
const currentPreviewImage = computed(() => {
    if (avatarType.value.value === 'ai') {
        return avatarUrl.value || null;
    }
    return userAvatarUrl.value || null;
});

// Get icon component for preset
const getPresetIcon = (presetValue) => {
    const iconMap = {
        'default': User,
        'robot': Bot,
        'brain': Brain,
        'spark': Sparkles,
        'bot': Bot,
        'sparkles': Sparkles,
        'circuit': Cpu,
        'silhouette': UserCircle,
        'abstract': Hexagon,
        'initials': AtSign,
        'custom': ImagePlus
    };
    return iconMap[presetValue] || User;
};

// Handle file drop
const handleFileDrop = async (event) => {
    isDraggingFile.value = false;
    const files = event.dataTransfer?.files;
    if (files && files.length > 0) {
        const file = files[0];
        if (file.type.startsWith('image/')) {
            await processUploadedFile(file);
        }
    }
};

// Process uploaded file
const processUploadedFile = async (file) => {
    try {
        const reader = new FileReader();
        reader.onload = async (e) => {
            const fileData = e.target.result;
            await storeFileData(file.name, fileData, file.type);
            await loadStoredFiles();
            showToast('Image uploaded successfully!');
        };
        reader.readAsDataURL(file);
    } catch (error) {
        showToast('Failed to upload image', 'error');
    }
};

// Select stored image
const selectStoredImage = (file) => {
    selectedFile.value = file;
    updateAvatarUrl();
};

const avatarType = ref({ name: 'AI', value: 'ai' });
const avatarOptions = [
    { name: 'AI', value: 'ai' },
    { name: 'User', value: 'user' }
];

const avatarShapes = [
    { name: 'Circle', value: 'circle' },
    { name: 'Square', value: 'square' },
    { name: 'Squircle', value: 'squircle' },
    { name: 'Oval H', value: 'oval-h' },
    { name: 'Oval V', value: 'oval-v' }
];

const themeModeOptions = [
    { label: 'System', value: 'system' },
    { label: 'Dark', value: 'dark' },
    { label: 'Light', value: 'light' },
    { label: 'Custom', value: 'custom' }
];

const themePresetOptions = THEME_PRESET_OPTIONS;

const backgroundModeOptions = [
    { label: 'Preset', value: 'preset' },
    { label: 'Color', value: 'color' },
    { label: 'Gradient', value: 'gradient' },
    { label: 'Image', value: 'image' }
];

const sidebarBackgroundModeOptions = [
    { label: 'Glass', value: 'glass' },
    { label: 'Preset', value: 'preset' },
    { label: 'Inherit', value: 'inherit' },
    { label: 'Color', value: 'color' },
    { label: 'Gradient', value: 'gradient' },
    { label: 'Image', value: 'image' }
];

const backgroundPresetOptions = BACKGROUND_PRESET_OPTIONS;
const messageEdgeTintOptions = [
    { label: 'Neutral', value: 'neutral' },
    { label: 'Accent', value: 'accent' }
];

const borderRadiusOptions = [
    { label: 'Sharp', value: 'sharp' },
    { label: 'Normal', value: 'normal' },
    { label: 'Rounded', value: 'rounded' }
];

const fontFamilyOptions = FONT_FAMILY_OPTIONS;
const codeFontOptions = CODE_FONT_OPTIONS;

// Avatar customization options
const avatarSizeOptions = [
    { label: 'Small', value: 'small' },
    { label: 'Medium', value: 'medium' },
    { label: 'Large', value: 'large' },
    { label: 'X-Large', value: 'xlarge' }
];

const avatarBorderStyleOptions = [
    { label: 'None', value: 'none' },
    { label: 'Solid', value: 'solid' },
    { label: 'Dashed', value: 'dashed' },
    { label: 'Double', value: 'double' },
    { label: 'Gradient', value: 'gradient' }
];

const avatarAnimationOptions = [
    { label: 'None', value: 'none' },
    { label: 'Pulse', value: 'pulse' },
    { label: 'Glow', value: 'glow' },
    { label: 'Float', value: 'float' }
];

const avatarPositionOptions = [
    { label: 'Beside', value: 'beside' },
    { label: 'Above', value: 'above' }
];

const avatarDefaultStyleOptions = [
    { label: 'Initials', value: 'initials' },
    { label: 'Icon', value: 'icon' },
    { label: 'Silhouette', value: 'silhouette' }
];

const userStatusOptions = [
    { label: 'Online', value: 'online' },
    { label: 'Away', value: 'away' },
    { label: 'Busy', value: 'busy' },
    { label: 'Offline', value: 'offline' }
];

const avatarPresetOptions = [
    { label: 'Default', value: 'default' },
    { label: 'Robot', value: 'robot' },
    { label: 'Brain', value: 'brain' },
    { label: 'Spark', value: 'spark' },
    { label: 'Custom', value: 'custom' }
];

// Computed property to get the current avatar preset value based on avatarType
const currentAvatarPresetValue = computed(() => {
    return avatarType.value.value === 'ai' ? aiAvatarPreset.value : userAvatarPreset.value;
});

// Handler to set the correct avatar preset based on current avatarType
const handleAvatarPresetChange = (newValue) => {
    if (avatarType.value.value === 'ai') {
        aiAvatarPreset.value = newValue;
    } else {
        userAvatarPreset.value = newValue;
    }
};

// Current avatar icon color based on type
const currentAvatarIconColor = computed(() => {
    return avatarType.value.value === 'ai' ? aiAvatarIconColor.value : userAvatarIconColor.value;
});

// Handler to set avatar icon color
const handleAvatarIconColorChange = (newValue) => {
    if (avatarType.value.value === 'ai') {
        aiAvatarIconColor.value = newValue;
    } else {
        userAvatarIconColor.value = newValue;
    }
};

// Reset avatar icon color to default
const resetAvatarIconColor = () => {
    if (avatarType.value.value === 'ai') {
        aiAvatarIconColor.value = DEFAULT_AVATAR_ICON_COLORS.ai;
    } else {
        userAvatarIconColor.value = DEFAULT_AVATAR_ICON_COLORS.user;
    }
};

const accentSwatches = ACCENT_SWATCHES;
const secondarySwatches = SECONDARY_SWATCHES;

const handleFetchStoredFiles = async () => {
    storedFiles.value = await fetchStoredImageFiles();
};

const uploadFile = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (e) => {
        const contents = e.target.result;
        await storeFileData(file.name, contents, file.size, file.type);
        showToast('Image uploaded and stored successfully');
        await handleFetchStoredFiles();
    };
    reader.readAsDataURL(file);
};

const triggerFileInput = () => {
    fileInput.value.click();
};

const handleAvatarShapeChange = () => {
    localStorage.setItem("avatarShape", JSON.stringify({ name: avatarShape.value === 'circle' ? 'Circle' : 'Square', value: avatarShape.value }));
};

const handleAvatarTypeChange = () => {
    selectedFile.value = null;
};

const handleAvatarUrlUpdate = (newValue) => {
    handleUpdate(avatarType.value.value === 'ai' ? 'avatarUrl' : 'userAvatarUrl', newValue);
};

const resetThemePreset = () => {
    uiThemePreset.value = DEFAULT_THEME_PRESET;
};

const resetAllTheme = () => {
    uiThemeMode.value = 'system';
    uiThemePreset.value = DEFAULT_THEME_PRESET;
    uiAccentColor.value = DEFAULT_ACCENT_COLOR;
    uiBackgroundMode.value = 'preset';
    uiBackgroundPreset.value = DEFAULT_BACKGROUND_PRESET;
    uiBackgroundColor.value = DEFAULT_THEME_RESET.backgroundColor;
    uiBackgroundGradientStart.value = DEFAULT_THEME_RESET.backgroundGradientStart;
    uiBackgroundGradientEnd.value = DEFAULT_THEME_RESET.backgroundGradientEnd;
    uiBackgroundGradientAngle.value = DEFAULT_THEME_RESET.backgroundGradientAngle;
    uiBackgroundImage.value = '';
    uiBackgroundImageOpacity.value = DEFAULT_THEME_RESET.backgroundImageOpacity;
    uiBackgroundImageBlur.value = DEFAULT_THEME_RESET.backgroundImageBlur;
    uiSidebarBackgroundMode.value = 'glass';
    uiSidebarBackgroundPreset.value = DEFAULT_SIDEBAR_BACKGROUND_PRESET;
    uiSidebarBackgroundColor.value = DEFAULT_THEME_RESET.sidebarBackgroundColor;
    uiSidebarBackgroundGradientStart.value = DEFAULT_THEME_RESET.sidebarBackgroundGradientStart;
    uiSidebarBackgroundGradientEnd.value = DEFAULT_THEME_RESET.sidebarBackgroundGradientEnd;
    uiSidebarBackgroundGradientAngle.value = DEFAULT_THEME_RESET.sidebarBackgroundGradientAngle;
    uiSidebarBackgroundImage.value = '';
    uiSidebarBackgroundImageOpacity.value = DEFAULT_THEME_RESET.sidebarBackgroundImageOpacity;
    uiSidebarBackgroundImageBlur.value = DEFAULT_THEME_RESET.sidebarBackgroundImageBlur;
    uiInputBarBackgroundColor.value = DEFAULT_THEME_RESET.inputBarBackgroundColor;
    uiInputBarBackgroundOpacity.value = DEFAULT_THEME_RESET.inputBarBackgroundOpacity;
    uiInputBarBorderColor.value = DEFAULT_THEME_RESET.inputBarBorderColor;
    uiInputBarBorderOpacity.value = DEFAULT_THEME_RESET.inputBarBorderOpacity;
    uiInputBarGlow.value = DEFAULT_THEME_RESET.inputBarGlow;
    uiToolCardBackgroundColor.value = DEFAULT_THEME_RESET.toolCardBackgroundColor;
    uiToolCardBackgroundOpacity.value = DEFAULT_THEME_RESET.toolCardBackgroundOpacity;
    uiToolCardBorderColor.value = DEFAULT_THEME_RESET.toolCardBorderColor;
    uiToolCardBorderOpacity.value = DEFAULT_THEME_RESET.toolCardBorderOpacity;
    uiToolCardGlow.value = DEFAULT_THEME_RESET.toolCardGlow;
    resetPanelSurfaces();
    uiFontScale.value = 1.0;
    uiBorderRadius.value = 'normal';
    uiCompactMode.value = false;
};

const resetHeaderTheme = () => {
    uiHeaderBackgroundMode.value = 'transparent';
    uiHeaderBackgroundPreset.value = 'deep-space';
    uiHeaderBackgroundColor.value = DEFAULT_HEADER_THEME.backgroundColor;
    uiHeaderBackgroundImage.value = '';
    uiHeaderBackgroundImageOpacity.value = DEFAULT_HEADER_THEME.backgroundImageOpacity;
    uiHeaderBackgroundImageBlur.value = DEFAULT_HEADER_THEME.backgroundImageBlur;
};

const resetInputBarTheme = () => {
    uiInputBarBackgroundMode.value = 'glass';
    uiInputBarBackgroundPreset.value = 'deep-space';
    uiInputBarBackgroundColor.value = DEFAULT_INPUT_BAR_THEME.backgroundColor;
    uiInputBarBackgroundOpacity.value = DEFAULT_INPUT_BAR_THEME.backgroundOpacity;
    uiInputBarBorderColor.value = DEFAULT_INPUT_BAR_THEME.borderColor;
    uiInputBarBorderOpacity.value = DEFAULT_INPUT_BAR_THEME.borderOpacity;
    uiInputBarGlow.value = DEFAULT_INPUT_BAR_THEME.glow;
};

const resetUserMessageTheme = () => {
    uiUserMessageBackgroundMode.value = 'glass';
    uiUserMessageBackgroundPreset.value = 'deep-space';
    uiUserMessageBackgroundColor.value = DEFAULT_USER_MESSAGE_THEME.backgroundColor;
    uiUserMessageBackgroundOpacity.value = DEFAULT_USER_MESSAGE_THEME.backgroundOpacity;
    uiUserMessageBorderColor.value = DEFAULT_USER_MESSAGE_THEME.borderColor;
    uiUserMessageBorderOpacity.value = DEFAULT_USER_MESSAGE_THEME.borderOpacity;
};

const resetAssistantMessageTheme = () => {
    uiAssistantMessageBackgroundMode.value = 'glass';
    uiAssistantMessageBackgroundPreset.value = 'steel-veil';
    uiAssistantMessageBackgroundColor.value = DEFAULT_ASSISTANT_MESSAGE_THEME.backgroundColor;
    uiAssistantMessageBackgroundOpacity.value = DEFAULT_ASSISTANT_MESSAGE_THEME.backgroundOpacity;
    uiAssistantMessageBorderColor.value = DEFAULT_ASSISTANT_MESSAGE_THEME.borderColor;
    uiAssistantMessageBorderOpacity.value = DEFAULT_ASSISTANT_MESSAGE_THEME.borderOpacity;
};

const resetSendButtonTheme = () => {
    uiSendButtonBackgroundColor.value = '';
    uiSendButtonTextColor.value = '';
    uiSendButtonGlow.value = 0;
};

const resetToolCardTheme = () => {
    uiToolCardBackgroundMode.value = 'glass';
    uiToolCardBackgroundPreset.value = 'deep-space';
    uiToolCardBackgroundColor.value = DEFAULT_TOOL_CARD_THEME.backgroundColor;
    uiToolCardBackgroundOpacity.value = DEFAULT_TOOL_CARD_THEME.backgroundOpacity;
    uiToolCardBorderColor.value = DEFAULT_TOOL_CARD_THEME.borderColor;
    uiToolCardBorderOpacity.value = DEFAULT_TOOL_CARD_THEME.borderOpacity;
    uiToolCardGlow.value = DEFAULT_TOOL_CARD_THEME.glow;
};

const resetButtonTheme = () => {
    uiButtonBackgroundMode.value = 'glass';
    uiButtonBackgroundPreset.value = 'deep-space';
    uiButtonBackgroundColor.value = DEFAULT_BUTTON_THEME.backgroundColor;
    uiButtonBackgroundOpacity.value = DEFAULT_BUTTON_THEME.backgroundOpacity;
    uiButtonBorderColor.value = DEFAULT_BUTTON_THEME.borderColor;
    uiButtonBorderOpacity.value = DEFAULT_BUTTON_THEME.borderOpacity;
    uiButtonGlow.value = DEFAULT_BUTTON_THEME.glow;
    uiStopButtonBackgroundColor.value = '';
};

const resetPanelSurfaces = () => {
    uiDrawerBackgroundMode.value = 'glass';
    uiDrawerBackgroundPreset.value = 'deep-space';
    uiDrawerBackgroundColor.value = DEFAULT_DRAWER_THEME.backgroundColor;
    uiDrawerBackgroundOpacity.value = DEFAULT_DRAWER_THEME.backgroundOpacity;
    uiDrawerBorderColor.value = DEFAULT_DRAWER_THEME.borderColor;
    uiDrawerBorderOpacity.value = DEFAULT_DRAWER_THEME.borderOpacity;
    uiDrawerCardBackgroundMode.value = 'glass';
    uiDrawerCardBackgroundColor.value = DEFAULT_DRAWER_THEME.cardBackgroundColor;
    uiDrawerCardBackgroundOpacity.value = DEFAULT_DRAWER_THEME.cardBackgroundOpacity;
    uiCodeEditorBackgroundColor.value = DEFAULT_CODE_EDITOR_THEME.backgroundColor;
    uiCodeEditorBackgroundOpacity.value = DEFAULT_CODE_EDITOR_THEME.backgroundOpacity;
    uiTerminalBackgroundColor.value = DEFAULT_TERMINAL_PANEL_THEME.backgroundColor;
    uiTerminalBackgroundOpacity.value = DEFAULT_TERMINAL_PANEL_THEME.backgroundOpacity;
    uiTerminalHeaderBackgroundColor.value = DEFAULT_TERMINAL_PANEL_THEME.headerBackgroundColor;
    uiTerminalHeaderBackgroundOpacity.value = DEFAULT_TERMINAL_PANEL_THEME.headerBackgroundOpacity;
    uiFileBrowserBackgroundColor.value = DEFAULT_FILE_BROWSER_THEME.backgroundColor;
    uiFileBrowserBackgroundOpacity.value = DEFAULT_FILE_BROWSER_THEME.backgroundOpacity;
    uiDialogContentBackgroundColor.value = DEFAULT_DIALOG_CONTENT_THEME.backgroundColor;
    uiDialogContentBackgroundOpacity.value = DEFAULT_DIALOG_CONTENT_THEME.backgroundOpacity;
    uiCardBackgroundColor.value = DEFAULT_CARD_THEME.backgroundColor;
    uiCardBackgroundOpacity.value = DEFAULT_CARD_THEME.backgroundOpacity;
    uiFilterButtonBackgroundColor.value = DEFAULT_FILTER_BUTTON_THEME.backgroundColor;
    uiFilterButtonBackgroundOpacity.value = DEFAULT_FILTER_BUTTON_THEME.backgroundOpacity;
    uiFilterButtonActiveBackgroundColor.value = DEFAULT_FILTER_BUTTON_THEME.activeBackgroundColor;
    uiFilterButtonActiveBackgroundOpacity.value = DEFAULT_FILTER_BUTTON_THEME.activeBackgroundOpacity;
};

const resetThinkingDropdownTheme = () => {
    // Header/Idle state
    uiThinkingHeaderBackgroundMode.value = 'glass';
    uiThinkingHeaderBackgroundPreset.value = 'steel-veil';
    uiThinkingHeaderBackgroundColor.value = DEFAULT_THINKING_DROPDOWN_THEME.headerBackgroundColor;
    uiThinkingHeaderBackgroundOpacity.value = DEFAULT_THINKING_DROPDOWN_THEME.headerBackgroundOpacity;
    uiThinkingHeaderBorderColor.value = DEFAULT_THINKING_DROPDOWN_THEME.headerBorderColor;
    uiThinkingHeaderBorderOpacity.value = DEFAULT_THINKING_DROPDOWN_THEME.headerBorderOpacity;
    // Content/Expanded state
    uiThinkingContentBackgroundMode.value = 'glass';
    uiThinkingContentBackgroundPreset.value = 'deep-space';
    uiThinkingContentBackgroundColor.value = DEFAULT_THINKING_DROPDOWN_THEME.contentBackgroundColor;
    uiThinkingContentBackgroundOpacity.value = DEFAULT_THINKING_DROPDOWN_THEME.contentBackgroundOpacity;
};

const resetEventColors = () => {
    uiEventColorRouting.value = DEFAULT_EVENT_COLORS.routing;
    uiEventColorMemory.value = DEFAULT_EVENT_COLORS.memory;
    uiEventColorTool.value = DEFAULT_EVENT_COLORS.tool;
    uiEventColorDecision.value = DEFAULT_EVENT_COLORS.decision;
    uiEventColorQuorum.value = DEFAULT_EVENT_COLORS.quorum;
    uiEventColorError.value = DEFAULT_EVENT_COLORS.error;
};

const resetVoiceColors = () => {
    uiVoiceListeningColor.value = DEFAULT_VOICE_COLORS.listening;
    uiVoiceSpeakingColor.value = DEFAULT_VOICE_COLORS.speaking;
    uiVoiceProcessingColor.value = DEFAULT_VOICE_COLORS.processing;
};

const resetEffects = () => {
    uiEffectScanlines.value = false;
    uiEffectScanlineOpacity.value = 0.12;
    uiEffectNoise.value = false;
    uiEffectNoiseOpacity.value = 0.08;
    uiEffectGlowPulse.value = false;
    uiEffectGlowPulseStrength.value = 0.35;
    uiEffectGlowPulseSpeed.value = 6;
    uiEffectGrid.value = false;
    uiEffectGridOpacity.value = 0.12;
    uiEffectVignette.value = false;
    uiEffectVignetteStrength.value = 0.2;
    uiEffectAurora.value = false;
    uiEffectAuroraOpacity.value = 0.18;
    uiEffectAuroraSpeed.value = 60;
    uiEffectHeaderShimmer.value = false;
    uiEffectHeaderShimmerStrength.value = 0.18;
    uiEffectHeaderShimmerSpeed.value = 12;
    uiEffectMessageDepth.value = true;
    uiEffectMessageDepthStrength.value = 0.22;
    uiEffectPanelEdge.value = false;
    uiEffectPanelEdgeStrength.value = 0.2;
    uiEffectMessageEdge.value = false;
    uiEffectMessageEdgeStrength.value = 0.18;
    uiEffectMessageEdgeTint.value = 'neutral';
    uiEffectPanelGlow.value = false;
    uiEffectPanelGlowStrength.value = 0.2;
    uiEffectPanelBevel.value = false;
    uiEffectPanelBevelStrength.value = 0.12;
    uiBackgroundBlur.value = 0;
    uiHeaderBlur.value = 18;
};

const resetNixieTube = () => {
    uiNixieColor.value = DEFAULT_NIXIE_THEME.color;
    uiNixieGlowColor.value = DEFAULT_NIXIE_THEME.glow;
    uiNixieSpeed.value = 1.0;
    uiNixieGlowIntensity.value = 1.0;
    uiNixieFlicker.value = true;
};

const resetExitButton = () => {
    uiNixieExitColor.value = DEFAULT_EXIT_BUTTON_THEME.color;
    uiNixieExitGlowColor.value = DEFAULT_EXIT_BUTTON_THEME.glow;
    uiNixieExitGlowIntensity.value = 1.0;
};

const resetNixieButton = () => {
    uiNixieButtonBackgroundColor.value = DEFAULT_NIXIE_BUTTON_THEME.backgroundColor;
};

const resetPanelDepth = () => {
    uiPanelDepth.value = 0.22;
};

const resetAnimations = () => {
    uiAnimMessageMotion.value = true;
    uiAnimHoverLift.value = true;
    uiAnimBackgroundDrift.value = false;
    uiAnimBackgroundDriftSpeed.value = 45;
    uiAnimButtonMotion.value = true;
    uiAnimButtonScale.value = 1.02;
    uiAnimButtonRipple.value = false;
    uiAnimSpeed.value = 1.0;
};

const resetAllFonts = () => {
    uiFontFamilyGlobal.value = 'default';
    uiFontFamilyHeader.value = 'inherit';
    uiFontFamilySidebar.value = 'inherit';
    uiFontFamilyMessages.value = 'inherit';
    uiFontFamilyInput.value = 'inherit';
    uiFontFamilyCode.value = 'default';
};

const resetAllFontColors = () => {
    uiFontColorHeader.value = '';
    uiFontColorSidebar.value = '';
    uiFontColorMessages.value = '';
    uiFontColorInput.value = '';
    uiFontColorMuted.value = '';
};

const resetAvatarStyling = () => {
    avatarSize.value = 'medium';
    avatarBorderStyle.value = 'none';
    avatarBorderColor.value = DEFAULT_AVATAR_STYLE.borderColor;
    avatarBorderWidth.value = DEFAULT_AVATAR_STYLE.borderWidth;
    avatarGlow.value = false;
    avatarGlowColor.value = DEFAULT_AVATAR_STYLE.glowColor;
    avatarGlowIntensity.value = DEFAULT_AVATAR_STYLE.glowIntensity;
    avatarAnimation.value = 'none';
    avatarPosition.value = 'beside';
    avatarDefaultStyle.value = 'initials';
    showStatusIndicator.value = true;
    aiAvatarPreset.value = 'default';
    userAvatarPreset.value = 'default';
};

const handleBackgroundImage = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
        showToast('Please select an image file.');
        return;
    }
    if (file.size > 3 * 1024 * 1024) {
        showToast('Image too large. Please use a file under 3MB.');
        return;
    }
    const reader = new FileReader();
    reader.onload = () => {
        uiBackgroundImage.value = String(reader.result || '');
        uiBackgroundMode.value = 'image';
    };
    reader.readAsDataURL(file);
};

const clearBackgroundImage = () => {
    uiBackgroundImage.value = '';
};

const handleSidebarBackgroundImage = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
        showToast('Please select an image file.');
        return;
    }
    if (file.size > 3 * 1024 * 1024) {
        showToast('Image too large. Please use a file under 3MB.');
        return;
    }
    const reader = new FileReader();
    reader.onload = () => {
        uiSidebarBackgroundImage.value = String(reader.result || '');
        uiSidebarBackgroundMode.value = 'image';
    };
    reader.readAsDataURL(file);
};

const clearSidebarBackgroundImage = () => {
    uiSidebarBackgroundImage.value = '';
};

// Independent background handlers
const handleLeftSidebarBackgroundImage = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
        showToast('Please select an image file.');
        return;
    }
    if (file.size > 3 * 1024 * 1024) {
        showToast('Image too large. Please use a file under 3MB.');
        return;
    }
    const reader = new FileReader();
    reader.onload = () => {
        uiLeftSidebarBackgroundImage.value = String(reader.result || '');
    };
    reader.readAsDataURL(file);
};

const clearLeftSidebarBackgroundImage = () => {
    uiLeftSidebarBackgroundImage.value = '';
};

const handleRightSidebarBackgroundImage = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
        showToast('Please select an image file.');
        return;
    }
    if (file.size > 3 * 1024 * 1024) {
        showToast('Image too large. Please use a file under 3MB.');
        return;
    }
    const reader = new FileReader();
    reader.onload = () => {
        uiRightSidebarBackgroundImage.value = String(reader.result || '');
    };
    reader.readAsDataURL(file);
};

const clearRightSidebarBackgroundImage = () => {
    uiRightSidebarBackgroundImage.value = '';
};

const handleHeaderBackgroundImage = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
        showToast('Please select an image file.');
        return;
    }
    if (file.size > 3 * 1024 * 1024) {
        showToast('Image too large. Please use a file under 3MB.');
        return;
    }
    const reader = new FileReader();
    reader.onload = () => {
        uiHeaderBackgroundImage.value = String(reader.result || '');
    };
    reader.readAsDataURL(file);
};

const clearHeaderBackgroundImage = () => {
    uiHeaderBackgroundImage.value = '';
};

const handleChatBackgroundImage = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
        showToast('Please select an image file.');
        return;
    }
    if (file.size > 3 * 1024 * 1024) {
        showToast('Image too large. Please use a file under 3MB.');
        return;
    }
    const reader = new FileReader();
    reader.onload = () => {
        uiChatBackgroundImage.value = String(reader.result || '');
    };
    reader.readAsDataURL(file);
};

const clearChatBackgroundImage = () => {
    uiChatBackgroundImage.value = '';
};

const updateAvatarUrl = () => {
    if (selectedFile.value) {
        handleUpdate(avatarType.value.value === 'ai' ? 'avatarUrl' : 'userAvatarUrl', selectedFile.value.fileData);
    }
};

const setAccentColor = (value) => {
    uiAccentColor.value = value;
};

const resetAccentColor = () => {
    uiAccentColor.value = DEFAULT_ACCENT_COLOR;
};

onBeforeMount(handleFetchStoredFiles);
onBeforeUnmount(() => {
    clearTokenHighlight();
});

// Force tab indicator recalculation when tab changes
const tabIndicatorKey = ref(0);
const themeTabIndicatorKey = ref(0);
const panelTabIndicatorKey = ref(0);
watch(activeTab, () => {
    clearTokenHighlight();
    nextTick(() => {
        tabIndicatorKey.value++;
    });
});

watch([activeThemeTab, isThemeConfigOpen], () => {
    nextTick(() => {
        themeTabIndicatorKey.value++;
    });
});

watch([activePanelTab, activeThemeTab], () => {
    nextTick(() => {
        panelTabIndicatorKey.value++;
    });
});

watch(activeThemeTab, (tab) => {
    clearTokenHighlight();
    if (tab === 'advanced') {
        nextTick(() => {
            collectAutoThemeTokens();
        });
    }
});

onMounted(() => {
    // Initialize tab indicator position
    nextTick(() => {
        tabIndicatorKey.value++;
        themeTabIndicatorKey.value++;
        panelTabIndicatorKey.value++;
        collectAutoThemeTokens();
    });
});


// ===========================================
// Debounced "Settings Saved" Toast Feedback
// ===========================================
let saveToastTimeout = null;
let isInitialLoad = true;

const showSaveToast = () => {
    if (isInitialLoad) return;
    if (saveToastTimeout) clearTimeout(saveToastTimeout);
    saveToastTimeout = setTimeout(() => {
        showToast('Settings saved', 'success');
    }, 600); // Debounce rapid changes
};

// Watch key theme settings and show feedback when they change
const settingsToWatch = [
    uiThemeMode, uiAccentColor, uiThemePreset, uiBackgroundMode,
    uiBackgroundPreset, uiFontScale, uiBorderRadius, uiCompactMode,
    uiFontFamilyGlobal, uiFontFamilyHeader, uiFontFamilyCode,
    uiEffectScanlines, uiEffectNoise, uiEffectGlowPulse, uiLiteMode,
    uiAnimSpeed, uiPanelDepth
];

settingsToWatch.forEach(setting => {
    watch(setting, showSaveToast);
});

// Mark initial load complete after a brief delay
setTimeout(() => { isInitialLoad = false; }, 1000);
</script>

<style lang="scss" scoped>
// ============================================
// VERA AppearanceConfigSection Premium Styling
// 2030 Dev Lab Aesthetic - Futuristic & Refined
// ============================================

.appearance-panel {
    display: flex;
    flex-direction: column;
    gap: 20px;
}

// ============================================
// PREMIUM TAB BAR WITH FLOATING INDICATOR
// ============================================

.appearance-tabs-container {
    position: relative;
}

.appearance-tabs {
    display: flex;
    gap: 2px;
    padding: 4px 5px;
    background: var(--vera-black-60);
    border: 1px solid var(--vera-border);
    border-radius: 14px;
    backdrop-filter: blur(12px);
    position: relative;
    overflow: visible;

    // Subtle inner glow
    &::before {
        content: '';
        position: absolute;
        inset: 0;
        border-radius: 14px;
        background: linear-gradient(135deg, var(--vera-accent-03), transparent 50%);
        pointer-events: none;
    }

    button {
        display: flex;
        align-items: center;
        gap: 5px;
        border-radius: 10px;
        border: none;
        background: transparent;
        color: var(--vera-text-muted);
        padding: 10px 12px;
        font-size: 0.75rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        z-index: 2;
        white-space: nowrap;

        svg {
            width: 14px;
            height: 14px;
            opacity: 0.7;
            transition: opacity 0.3s ease;
        }

        span {
            transition: color 0.3s ease;
        }

        &:hover {
            color: var(--vera-text);

            svg {
                opacity: 1;
            }
        }

        &.active {
            color: var(--vera-text);

            svg {
                opacity: 1;
                filter: drop-shadow(0 0 4px var(--vera-accent));
            }
        }
    }

    // Floating indicator
    .tab-indicator {
        position: absolute;
        top: 4px;
        left: 4px;
        height: calc(100% - 8px);
        background: linear-gradient(135deg, var(--vera-accent-20), var(--vera-accent-08));
        border: 1px solid var(--vera-accent-30);
        border-radius: 10px;
        transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
        z-index: 1;
        box-shadow:
            0 0 20px var(--vera-accent-15),
            inset 0 1px 0 var(--vera-white-10);

        // Glow effect - contained within parent bounds
        &::before {
            content: '';
            position: absolute;
            inset: 0;
            border-radius: 10px;
            background: radial-gradient(ellipse at center, var(--vera-accent-20), transparent 70%);
            pointer-events: none;
            animation: indicatorPulse 3s ease-in-out infinite;
        }
    }
}

@keyframes indicatorPulse {
    0%, 100% { opacity: 0.5; }
    50% { opacity: 1; }
}

.appearance-section {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.theme-subtabs-container {
    position: relative;
}

.theme-subtabs {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 4px;
    background: var(--vera-black-60);
    border: 1px solid var(--vera-border);
    border-radius: 12px;
    position: relative;
    overflow-x: auto;
    scrollbar-width: none;
}

.theme-subtabs::-webkit-scrollbar {
    display: none;
}

.theme-subtabs button {
    display: flex;
    align-items: center;
    gap: 6px;
    border-radius: 10px;
    border: none;
    background: transparent;
    color: var(--vera-text-muted);
    padding: 8px 12px;
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
    transition: color 0.2s ease;
    position: relative;
    z-index: 2;
    white-space: nowrap;
}

.theme-subtabs button:hover,
.theme-subtabs button.active {
    color: var(--vera-text);
}

.theme-subtabs .tab-indicator {
    position: absolute;
    top: 4px;
    left: 4px;
    height: calc(100% - 8px);
    background: linear-gradient(135deg, var(--vera-accent-18), var(--vera-accent-06));
    border: 1px solid var(--vera-accent-25);
    border-radius: 10px;
    transition: all 0.3s ease;
    z-index: 1;
}

.theme-subtabs--compact {
    padding: 3px;
    border-radius: 10px;
}

.theme-subtabs--compact button {
    padding: 6px 10px;
    font-size: 0.6875rem;
}

.theme-subtabs--compact .tab-indicator {
    top: 3px;
    left: 3px;
    height: calc(100% - 6px);
    border-radius: 8px;
}

.theme-tab-panel {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.theme-group {
    padding: 14px;
    border-radius: 14px;
    border: 1px solid var(--vera-border);
    background: var(--vera-black-50);
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.theme-group-header {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.theme-group-title {
    font-size: 0.6875rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--vera-text-muted);
}

.theme-group-body {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.section-header.static {
    cursor: default;
}

// ============================================
// AVATAR TAB - Premium Redesign
// ============================================

.avatar-tab {
    gap: 20px;
}

// ============================================
// AVATAR PANEL SECTION CARDS - Premium Effects
// Animated gradients, shimmers, ambient glows
// ============================================

// Shared card styling mixin for all avatar sections
%avatar-section-card {
    background: var(--vera-drawer-bg);
    border: 1px solid var(--vera-accent-12);
    border-radius: 16px;
    backdrop-filter: blur(16px);
    position: relative;
    overflow: hidden;
    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);

    // Animated gradient background
    &::before {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(
            135deg,
            var(--vera-accent-04) 0%,
            transparent 40%,
            var(--vera-secondary-02) 100%
        );
        opacity: 1;
        transition: opacity 0.4s ease;
        pointer-events: none;
    }

    // Shimmer sweep effect on hover
    &::after {
        content: '';
        position: absolute;
        top: 0;
        left: -150%;
        width: 100%;
        height: 100%;
        background: linear-gradient(
            90deg,
            transparent 0%,
            var(--vera-accent-06) 45%,
            var(--vera-white-08) 50%,
            var(--vera-accent-06) 55%,
            transparent 100%
        );
        transition: left 0.7s ease;
        pointer-events: none;
    }

    &:hover {
        border-color: var(--vera-accent-25);
        box-shadow:
            0 0 30px var(--vera-accent-08),
            inset 0 0 40px var(--vera-accent-02);

        &::after {
            left: 150%;
        }
    }
}

// Hero Preview Section - The showpiece
.avatar-hero-section {
    @extend %avatar-section-card;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    padding: 28px;

    // Animated ambient glow pulse
    &::before {
        background:
            radial-gradient(ellipse at 20% 50%, var(--vera-accent-08) 0%, transparent 50%),
            radial-gradient(ellipse at 80% 50%, var(--vera-secondary-05) 0%, transparent 50%),
            linear-gradient(135deg, var(--vera-accent-03) 0%, transparent 60%);
        animation: ambientGlow 6s ease-in-out infinite;
    }

    // Floating light particles effect
    .hero-particles {
        position: absolute;
        inset: 0;
        pointer-events: none;
        overflow: hidden;

        span {
            position: absolute;
            width: 4px;
            height: 4px;
            background: var(--vera-accent);
            border-radius: 50%;
            opacity: 0;
            animation: floatParticle 8s ease-in-out infinite;

            &:nth-child(1) { left: 10%; top: 20%; animation-delay: 0s; }
            &:nth-child(2) { left: 80%; top: 60%; animation-delay: 2s; }
            &:nth-child(3) { left: 50%; top: 80%; animation-delay: 4s; }
        }
    }
}

@keyframes ambientGlow {
    0%, 100% {
        opacity: 0.8;
        filter: hue-rotate(0deg);
    }
    50% {
        opacity: 1;
        filter: hue-rotate(15deg);
    }
}

@keyframes floatParticle {
    0%, 100% {
        opacity: 0;
        transform: translateY(0) scale(0);
    }
    20% {
        opacity: 0.6;
        transform: translateY(-10px) scale(1);
    }
    80% {
        opacity: 0.3;
        transform: translateY(-30px) scale(0.5);
    }
}

.avatar-preview-showcase {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    position: relative;
    z-index: 1;
}

.avatar-preview-large {
    width: 96px;
    height: 96px;
    border-radius: 50%;
    background: var(--vera-black-80);
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    overflow: hidden;
    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);

    // Shape variants
    &.shape-circle { border-radius: 50%; }
    &.shape-square { border-radius: 12px; }
    &.shape-squircle { border-radius: 30%; }
    &.shape-oval-h { border-radius: 50%; width: 110px; height: 80px; }
    &.shape-oval-v { border-radius: 50%; width: 80px; height: 110px; }

    // Size variants
    &.size-small { width: 64px; height: 64px; }
    &.size-medium { width: 80px; height: 80px; }
    &.size-large { width: 96px; height: 96px; }
    &.size-xlarge { width: 120px; height: 120px; }

    // Border effect
    &.has-border {
        border: var(--avatar-border-width) solid var(--avatar-border-color);
    }

    // Glow effect
    &.has-glow {
        box-shadow:
            0 0 calc(20px * var(--avatar-glow-intensity)) var(--avatar-glow-color),
            0 0 calc(40px * var(--avatar-glow-intensity)) color-mix(in srgb, var(--avatar-glow-color) 50%, transparent);
    }

    // Animation variants
    &.anim-pulse {
        animation: avatarPulse 2s ease-in-out infinite;
    }
    &.anim-glow {
        animation: avatarGlow 2s ease-in-out infinite;
    }
    &.anim-float {
        animation: avatarFloat 3s ease-in-out infinite;
    }
    &.anim-breathe {
        animation: avatarBreathe 4s ease-in-out infinite;
    }

    .preview-image {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    .preview-placeholder {
        color: var(--vera-text-muted);
        opacity: 0.6;
    }

    // Status dot
    .status-dot {
        position: absolute;
        bottom: 4px;
        right: 4px;
        width: 14px;
        height: 14px;
        border-radius: 50%;
        border: 2px solid var(--vera-black-90);

        &.online { background: var(--vera-status-success); box-shadow: 0 0 8px var(--vera-status-success); }
        &.away { background: var(--vera-status-warning); box-shadow: 0 0 8px var(--vera-status-warning); }
        &.busy { background: var(--vera-status-error); box-shadow: 0 0 8px var(--vera-status-error); }
        &.offline { background: var(--vera-text-muted); }
    }
}

@keyframes avatarPulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.05); }
}

@keyframes avatarGlow {
    0%, 100% { filter: brightness(1); }
    50% { filter: brightness(1.2); }
}

@keyframes avatarFloat {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-6px); }
}

@keyframes avatarBreathe {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.02); opacity: 0.9; }
}

.preview-label {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;

    .preview-type {
        font-size: 0.8125rem;
        font-weight: 600;
        color: var(--vera-text);
    }

    .preview-hint {
        font-size: 0.6875rem;
        color: var(--vera-text-muted);
    }
}

.avatar-master-toggle {
    position: relative;
    z-index: 1;
}

// ============================================
// PREMIUM TOGGLE SWITCH
// Glass morphism with animated glow
// ============================================

.premium-toggle {
    display: flex;
    align-items: center;
    gap: 12px;
    cursor: pointer;

    input[type="checkbox"] {
        position: absolute;
        opacity: 0;
        pointer-events: none;
    }

    .toggle-track {
        position: relative;
        width: 52px;
        height: 28px;
        background: var(--vera-black-80);
        border: 1px solid var(--vera-border);
        border-radius: 14px;
        transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
        overflow: hidden;

        // Inner glow when off
        &::before {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(180deg, var(--vera-white-03), transparent);
            border-radius: 14px;
        }

        .toggle-thumb {
            position: absolute;
            top: 3px;
            left: 3px;
            width: 20px;
            height: 20px;
            background: linear-gradient(135deg, var(--vera-panel), var(--vera-panel-alt));
            border-radius: 50%;
            transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 2px 4px var(--vera-black-30);

            // Inner highlight
            &::before {
                content: '';
                position: absolute;
                top: 2px;
                left: 2px;
                width: 8px;
                height: 8px;
                background: radial-gradient(circle, var(--vera-white-30), transparent);
                border-radius: 50%;
            }
        }
    }

    .toggle-label {
        font-size: 0.8125rem;
        font-weight: 500;
        color: var(--vera-text);
        transition: color 0.3s ease;
    }

    // Checked state
    input:checked + .toggle-track {
        background: linear-gradient(135deg, var(--vera-accent-30), var(--vera-accent-15));
        border-color: var(--vera-accent-50);
        box-shadow:
            0 0 20px var(--vera-accent-20),
            inset 0 0 15px var(--vera-accent-10);

        .toggle-thumb {
            left: calc(100% - 23px);
            background: linear-gradient(135deg, var(--vera-accent), var(--vera-accent-strong));
            box-shadow:
                0 0 12px var(--vera-accent),
                0 2px 4px var(--vera-black-30);
        }
    }

    // Hover state
    &:hover .toggle-track {
        border-color: var(--vera-accent-soft);
    }

    // Compact version
    &.compact {
        .toggle-track {
            width: 40px;
            height: 22px;
            border-radius: 11px;
        }

        .toggle-thumb {
            width: 16px;
            height: 16px;
        }

        input:checked + .toggle-track .toggle-thumb {
            left: calc(100% - 19px);
        }
    }
}

// ============================================
// SECTION TITLES
// ============================================

.section-title {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--vera-text);
    margin: 0 0 14px 0;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--vera-border);
    position: relative;
    z-index: 1;

    svg {
        color: var(--vera-accent);
        opacity: 0.8;
    }

    &::after {
        content: '';
        position: absolute;
        bottom: -1px;
        left: 0;
        width: 40px;
        height: 2px;
        background: linear-gradient(90deg, var(--vera-accent), transparent);
        border-radius: 1px;
    }
}

// ============================================
// TYPE SELECTOR CARDS
// ============================================

.avatar-type-selector {
    @extend %avatar-section-card;
    padding: 20px;
}

.type-cards {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
    position: relative;
    z-index: 1;
}

.type-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 20px 16px;
    background: var(--vera-black-50);
    border: 1px solid var(--vera-border);
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;

    &::before {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(135deg, var(--vera-accent-05), transparent);
        opacity: 0;
        transition: opacity 0.3s ease;
    }

    .card-icon {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.3s ease;

        &.ai-icon {
            background: linear-gradient(135deg, var(--vera-accent-20), var(--vera-accent-08));
            color: var(--vera-accent);
        }

        &.user-icon {
            background: linear-gradient(135deg, var(--vera-secondary-20), var(--vera-secondary-08));
            color: var(--vera-secondary);
        }
    }

    .card-label {
        font-size: 0.8125rem;
        font-weight: 600;
        color: var(--vera-text);
    }

    .card-hint {
        font-size: 0.6875rem;
        color: var(--vera-text-muted);
    }

    &:hover {
        border-color: var(--vera-accent-soft);
        transform: translateY(-2px);

        &::before {
            opacity: 1;
        }

        .card-icon {
            transform: scale(1.1);
        }
    }

    &.active {
        border-color: var(--vera-accent);
        background: var(--vera-accent-08);
        box-shadow:
            0 0 20px var(--vera-accent-15),
            inset 0 0 20px var(--vera-accent-05);

        &::before {
            opacity: 1;
        }
    }
}

// ============================================
// PRESET GALLERY
// ============================================

.avatar-presets-section {
    @extend %avatar-section-card;
    padding: 20px;
}

.presets-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
    gap: 10px;
    position: relative;
    z-index: 1;
}

.preset-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 14px 8px;
    background: var(--vera-black-50);
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);

    .preset-icon {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--vera-accent-10);
        display: flex;
        align-items: center;
        justify-content: center;
        // Color is set dynamically via :style binding
        transition: all 0.3s ease;
    }

    .preset-label {
        font-size: 0.6875rem;
        font-weight: 500;
        color: var(--vera-text-muted);
        text-align: center;
    }

    &:hover {
        border-color: var(--vera-accent-soft);
        transform: translateY(-2px);

        .preset-icon {
            background: var(--vera-accent-20);
            transform: scale(1.1);
        }
    }

    &.active {
        border-color: var(--vera-accent);
        background: var(--vera-accent-10);
        box-shadow: 0 0 15px var(--vera-accent-15);

        .preset-icon {
            background: linear-gradient(135deg, var(--vera-accent), var(--vera-accent-strong));
            color: var(--primary-color-text);
            box-shadow: 0 0 12px var(--vera-accent);
        }

        .preset-label {
            color: var(--vera-text);
        }
    }
}

// ============================================
// ICON COLOR SECTION
// ============================================

.icon-color-section {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--vera-border);
    position: relative;
    z-index: 1;
}

.icon-color-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.icon-color-label {
    font-size: 0.8125rem;
    font-weight: 500;
    color: var(--vera-text);
}

.icon-color-controls {
    display: flex;
    align-items: center;
    gap: 10px;
}

.icon-color-picker {
    width: 36px;
    height: 36px;
    padding: 0;
    background: transparent;
    border: 2px solid var(--vera-border);
    border-radius: 50%;
    cursor: pointer;
    transition: all 0.3s ease;
    overflow: hidden;

    &::-webkit-color-swatch-wrapper {
        padding: 2px;
    }

    &::-webkit-color-swatch {
        border: none;
        border-radius: 50%;
    }

    &:hover {
        border-color: var(--vera-accent);
        transform: scale(1.1);
        box-shadow: 0 0 12px var(--vera-accent-20);
    }
}

.icon-color-value {
    font-size: 0.75rem;
    font-weight: 500;
    font-family: 'JetBrains Mono', monospace;
    color: var(--vera-text-muted);
    text-transform: uppercase;
}

.icon-color-reset {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    background: var(--vera-black-50);
    border: 1px solid var(--vera-border);
    border-radius: 6px;
    color: var(--vera-text-muted);
    cursor: pointer;
    transition: all 0.3s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
        color: var(--vera-accent);
        background: var(--vera-accent-10);
    }

    svg {
        transition: transform 0.3s ease;
    }

    &:hover svg {
        transform: rotate(-180deg);
    }
}

// ============================================
// CUSTOM IMAGE SECTION
// ============================================

.avatar-custom-section {
    @extend %avatar-section-card;
    padding: 20px;
}

.custom-upload-area {
    display: flex;
    flex-direction: column;
    gap: 16px;
    position: relative;
    z-index: 1;
}

// Drag & Drop Zone
.drop-zone {
    padding: 32px 24px;
    background: var(--vera-black-50);
    border: 2px dashed var(--vera-border);
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;

    &::before {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(135deg, var(--vera-accent-03), transparent);
        opacity: 0;
        transition: opacity 0.3s ease;
    }

    .drop-zone-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 10px;
        position: relative;
        z-index: 1;
    }

    .drop-icon {
        width: 56px;
        height: 56px;
        border-radius: 50%;
        background: var(--vera-accent-10);
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--vera-accent);
        transition: all 0.3s ease;
    }

    .drop-text {
        font-size: 0.8125rem;
        font-weight: 500;
        color: var(--vera-text);
    }

    .drop-hint {
        font-size: 0.6875rem;
        color: var(--vera-text-muted);
    }

    &:hover, &.drag-over {
        border-color: var(--vera-accent);
        background: var(--vera-accent-05);

        &::before {
            opacity: 1;
        }

        .drop-icon {
            background: var(--vera-accent-20);
            transform: scale(1.1);
        }
    }

    &.drag-over {
        border-style: solid;
        box-shadow:
            0 0 20px var(--vera-accent-20),
            inset 0 0 30px var(--vera-accent-05);
    }
}

.url-input-row {
    margin-top: 8px;
}

// Stored Images Gallery
.stored-images-gallery {
    h4 {
        font-size: 0.75rem;
        font-weight: 600;
        color: var(--vera-text-muted);
        margin-bottom: 12px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
}

.images-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
    gap: 10px;
}

.stored-image-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 8px;
    background: var(--vera-black-50);
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.3s ease;

    img {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        object-fit: cover;
        transition: transform 0.3s ease;
    }

    .image-name {
        font-size: 0.625rem;
        color: var(--vera-text-muted);
        max-width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    &:hover {
        border-color: var(--vera-accent-soft);

        img {
            transform: scale(1.1);
        }
    }

    &.active {
        border-color: var(--vera-accent);
        background: var(--vera-accent-10);

        img {
            box-shadow: 0 0 10px var(--vera-accent);
        }
    }
}

// ============================================
// APPEARANCE SETTINGS
// ============================================

.avatar-appearance-settings {
    @extend %avatar-section-card;
    padding: 20px;
}

.settings-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
    position: relative;
    z-index: 1;

    @media (max-width: 500px) {
        grid-template-columns: 1fr;
    }
}

.setting-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.setting-label {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--vera-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

// ============================================
// PREMIUM SEGMENTED CONTROL
// Animated floating indicator
// ============================================

.premium-segmented {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
    padding: 3px;
    background: color-mix(in srgb, var(--vera-panel) 70%, transparent);
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    position: relative;

    button {
        flex: 1 1 auto;
        min-width: fit-content;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
        padding: 8px 8px;
        background: transparent;
        border: none;
        border-radius: 8px;
        font-size: 0.625rem;
        font-weight: 500;
        color: var(--vera-text-muted);
        cursor: pointer;
        transition: all 0.25s ease;
        white-space: nowrap;
        position: relative;
        z-index: 1;

        &:hover {
            color: var(--vera-text);
        }

        &.active {
            color: var(--vera-text);
            background: linear-gradient(135deg, var(--vera-accent-20), var(--vera-accent-08));
            box-shadow: 0 0 12px var(--vera-accent-15);
        }

        .status-preview {
            width: 8px;
            height: 8px;
            border-radius: 50%;

            &.online { background: var(--vera-status-success); }
            &.away { background: var(--vera-status-warning); }
            &.busy { background: var(--vera-status-error); }
            &.offline { background: var(--vera-text-muted); }
        }
    }

    &.compact {
        padding: 2px;

        button {
            padding: 6px 8px;
            font-size: 0.625rem;
        }
    }
}

// ============================================
// EFFECTS SETTINGS
// ============================================

.avatar-effects-settings {
    @extend %avatar-section-card;
    padding: 20px;
}

.effects-grid {
    display: flex;
    flex-direction: column;
    gap: 14px;
    position: relative;
    z-index: 1;
}

.effect-card {
    padding: 14px;
    background: var(--vera-black-50);
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    transition: border-color 0.3s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
    }
}

.effect-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0;

    .effect-title {
        font-size: 0.8125rem;
        font-weight: 600;
        color: var(--vera-text);
    }
}

.effect-controls {
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid var(--vera-border);
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.control-row {
    display: flex;
    align-items: center;
    gap: 12px;

    > label {
        font-size: 0.75rem;
        color: var(--vera-text-muted);
        min-width: 60px;
    }
}

// ============================================
// PREMIUM COLOR PICKER
// ============================================

.premium-color-picker {
    width: 36px;
    height: 28px;
    padding: 2px;
    background: var(--vera-black-80);
    border: 1px solid var(--vera-border);
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.3s ease;

    &::-webkit-color-swatch-wrapper {
        padding: 2px;
    }

    &::-webkit-color-swatch {
        border: none;
        border-radius: 4px;
    }

    &:hover {
        border-color: var(--vera-accent-soft);
        transform: scale(1.05);
    }
}

// ============================================
// PREMIUM SLIDER
// Gradient track with glowing thumb
// ============================================

.premium-slider-container {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: 1;
}

.premium-slider {
    flex: 1;
    height: 6px;
    background: var(--vera-black-80);
    border-radius: 3px;
    appearance: none;
    cursor: pointer;
    position: relative;

    &::-webkit-slider-track {
        height: 6px;
        background: linear-gradient(90deg, var(--vera-accent-30), var(--vera-accent-10));
        border-radius: 3px;
    }

    &::-webkit-slider-thumb {
        appearance: none;
        width: 18px;
        height: 18px;
        background: linear-gradient(135deg, var(--vera-accent), var(--vera-accent-strong));
        border-radius: 50%;
        cursor: pointer;
        box-shadow:
            0 0 10px var(--vera-accent),
            0 2px 4px var(--vera-black-30);
        transition: all 0.2s ease;
        margin-top: -6px;
    }

    &::-webkit-slider-thumb:hover {
        transform: scale(1.15);
        box-shadow:
            0 0 16px var(--vera-accent),
            0 2px 6px var(--vera-black-40);
    }

    &::-moz-range-track {
        height: 6px;
        background: linear-gradient(90deg, var(--vera-accent-30), var(--vera-accent-10));
        border-radius: 3px;
    }

    &::-moz-range-thumb {
        width: 18px;
        height: 18px;
        background: linear-gradient(135deg, var(--vera-accent), var(--vera-accent-strong));
        border: none;
        border-radius: 50%;
        cursor: pointer;
        box-shadow: 0 0 10px var(--vera-accent);
    }
}

.slider-value {
    min-width: 40px;
    text-align: right;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--vera-accent);
    font-family: 'JetBrains Mono', monospace;
}

// ============================================
// RESET BUTTON
// ============================================

.avatar-reset-section {
    display: flex;
    justify-content: center;
}

.premium-reset-button {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 24px;
    background: var(--vera-error-10);
    border: 1px solid var(--vera-error-30);
    border-radius: 10px;
    color: var(--vera-danger);
    font-size: 0.8125rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.3s ease;

    &:hover {
        background: var(--vera-error-20);
        border-color: var(--vera-error-50);
        transform: translateY(-2px);
        box-shadow: 0 4px 15px var(--vera-error-20);
    }

    svg {
        transition: transform 0.3s ease;
    }

    &:hover svg {
        transform: rotate(-180deg);
    }
}

// ============================================
// Panel Presets & Previews
// ============================================

.panel-presets-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 12px;
    margin-bottom: 12px;
}

.panel-preset-card {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px;
    background: var(--vera-black-50);
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    text-align: left;
    cursor: pointer;
    transition: all 0.3s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
        background: var(--vera-accent-05);
    }

    &.active {
        border-color: var(--vera-accent);
        box-shadow:
            0 0 16px var(--vera-accent-12),
            inset 0 0 12px var(--vera-accent-06);
    }
}

.panel-preset-preview {
    height: 32px;
    border-radius: 8px;
    border: 1px solid var(--vera-border);
    background-size: cover;
    background-position: center;
    box-shadow: inset 0 0 0 1px var(--vera-black-30);
}

.panel-preset-meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.panel-preset-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.panel-preset-action {
    padding: 4px 8px;
    border-radius: 8px;
    border: 1px solid var(--vera-border);
    background: transparent;
    color: var(--vera-text-muted);
    font-size: 0.6875rem;
    cursor: pointer;
    transition: all 0.2s ease;
}

.panel-preset-action:hover {
    border-color: var(--vera-accent);
    color: var(--vera-accent);
    background: var(--vera-accent-05);
}

.panel-preset-action.danger:hover {
    border-color: var(--vera-error-60);
    color: var(--vera-danger);
    background: var(--vera-error-10);
}

.panel-preset-label {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--vera-text);
}

.panel-preset-tag {
    align-self: flex-start;
    padding: 2px 6px;
    border-radius: 999px;
    font-size: 0.625rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: var(--vera-text);
    background: var(--vera-accent-15);
    border: 1px solid var(--vera-accent-30);
}

.panel-preset-desc {
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
}

.panel-preset-tools {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-bottom: 12px;
}

.panel-preset-actions,
.panel-preset-json {
    align-items: flex-start;
}

.panel-preset-actions {
    flex-wrap: wrap;
    gap: 10px;
}

.panel-preset-drop {
    margin-top: 6px;
}

.panel-preset-dropzone {
    padding: 18px 16px;
}

.panel-preset-dropzone .drop-icon {
    width: 42px;
    height: 42px;
}

.panel-preset-dropzone .drop-text {
    font-size: 0.75rem;
}

.panel-preset-dropzone .drop-hint {
    font-size: 0.625rem;
}

.panel-preset-input {
    flex: 1;
    min-width: 160px;
    height: 32px;
    padding: 0 10px;
    border-radius: 8px;
    border: 1px solid var(--vera-border);
    background: var(--vera-black-50);
    color: var(--vera-text);
    font-size: 0.75rem;
}

.panel-preset-textarea {
    flex: 1 1 100%;
    min-height: 120px;
    padding: 10px;
    border-radius: 10px;
    border: 1px solid var(--vera-border);
    background: var(--vera-black-50);
    color: var(--vera-text);
    font-size: 0.75rem;
    font-family: 'JetBrains Mono', monospace;
    resize: vertical;
}

.panel-preset-textarea::placeholder,
.panel-preset-input::placeholder {
    color: var(--vera-text-muted);
}

.panel-preset-json {
    flex-wrap: wrap;
}

.panel-preset-diff {
    padding: 12px;
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    background: var(--vera-black-50);
}

.panel-preset-diff-header {
    font-size: 0.6875rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--vera-text-muted);
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.panel-preset-reset {
    padding: 4px 8px;
    border-radius: 8px;
    border: 1px solid var(--vera-border);
    background: var(--vera-black-50);
    color: var(--vera-text);
    font-size: 0.6875rem;
    cursor: pointer;
    transition: all 0.2s ease;
}

.panel-preset-reset:hover:enabled {
    border-color: var(--vera-accent);
    color: var(--vera-accent);
    background: var(--vera-accent-05);
}

.panel-preset-reset:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.panel-preset-diff-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: 200px;
    overflow: auto;
}

.panel-preset-diff-item {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    font-size: 0.75rem;
    color: var(--vera-text);
}

.panel-preset-diff-label {
    color: var(--vera-text-muted);
}

.panel-preset-diff-values {
    display: flex;
    align-items: center;
    gap: 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.6875rem;
}

.panel-preset-diff-current {
    color: var(--vera-text);
}

.panel-preset-diff-baseline {
    color: var(--vera-text-muted);
}

.panel-preset-diff-arrow {
    color: var(--vera-accent);
}

.surface-preview {
    width: 44px;
    height: 30px;
    border-radius: 8px;
    border: 1px solid var(--vera-border);
    background-size: cover;
    background-position: center;
    box-shadow: inset 0 0 0 1px var(--vera-black-30);
    margin-left: auto;
    flex: 0 0 auto;
}

// ============================================
// Theme Row States (Legacy Support)
// ============================================

.theme-row.disabled {
    opacity: 0.45;
    pointer-events: none;

    h4 {
        color: var(--vera-text-muted);
    }
}

.range-slider:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

// ============================================
// EVENT COLORS GRID - Premium Color Palette
// Clean grid layout for thinking event colors
// ============================================

.event-colors-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    padding: 14px;
    background: var(--vera-black-50);
    border: 1px solid var(--vera-border);
    border-radius: 10px;

    @media (max-width: 450px) {
        grid-template-columns: repeat(2, 1fr);
    }
}

.event-color-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 10px;
    background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
    border: 1px solid transparent;
    border-radius: 8px;
    transition: all 0.3s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
        background: var(--vera-accent-05);
    }
}

.event-color-picker {
    width: 40px;
    height: 40px;
    padding: 0;
    background: transparent;
    border: 2px solid var(--vera-border);
    border-radius: 50%;
    cursor: pointer;
    transition: all 0.3s ease;
    overflow: hidden;

    &::-webkit-color-swatch-wrapper {
        padding: 2px;
    }

    &::-webkit-color-swatch {
        border: none;
        border-radius: 50%;
    }

    &:hover {
        border-color: var(--vera-accent);
        transform: scale(1.1);
        box-shadow: 0 0 12px var(--vera-accent-20);
    }
}

.event-color-label {
    font-size: 0.6875rem;
    font-weight: 500;
    color: var(--vera-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.theme-overrides {
    margin-top: 8px;
}

.theme-token-section {
    margin-bottom: 16px;
    padding: 14px;
    border-radius: 14px;
    border: 1px solid var(--vera-border);
    background: color-mix(in srgb, var(--vera-panel) 70%, transparent);
}

.theme-token-section:last-child {
    margin-bottom: 0;
}

.theme-token-group {
    margin-bottom: 18px;
}

.theme-token-grid {
    display: grid;
    gap: 12px;
}

.theme-token-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 10px 12px;
    border-radius: 12px;
    border: 1px solid var(--vera-border);
    background: var(--vera-panel-muted);
}

.token-meta {
    display: flex;
    flex-direction: column;
    min-width: 0;
    gap: 2px;
}

.token-label {
    color: var(--vera-text);
    font-weight: 600;
    font-size: 0.95rem;
}

.token-key {
    color: var(--vera-text-muted);
    font-size: 0.75rem;
}

.token-controls {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-end;
}

.token-background-tools {
    flex: 1 1 100%;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding-top: 8px;
    border-top: 1px dashed var(--vera-border);
    align-self: stretch;
}

.token-background-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-start;
}

.token-bg-label {
    font-size: 0.625rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--vera-text-muted);
}

.token-mode-select {
    min-width: 160px;
    padding: 6px 10px;
    border-radius: 8px;
    border: 1px solid var(--vera-border);
    background: var(--vera-input-bg);
    color: var(--vera-text);
    font-size: 0.75rem;
}

.token-range {
    min-width: 140px;
}

.token-range-value {
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
    min-width: 40px;
    text-align: right;
}

.token-input {
    min-width: 200px;
    padding: 6px 10px;
    border-radius: 8px;
    border: 1px solid var(--vera-border);
    background: var(--vera-input-bg);
    color: var(--vera-input-text);
    font-size: 0.85rem;
}

.token-input:focus {
    outline: none;
    border-color: var(--vera-accent);
    box-shadow: 0 0 8px var(--vera-accent-soft);
}

.token-reset {
    padding: 6px 10px;
    border-radius: 8px;
    border: 1px solid var(--vera-border);
    background: transparent;
    color: var(--vera-text-muted);
    cursor: pointer;
    transition: border-color 0.2s ease, color 0.2s ease;
}

.token-reset:hover {
    border-color: var(--vera-accent-soft);
    color: var(--vera-text);
}

@media (max-width: 720px) {
    .theme-token-row {
        flex-direction: column;
        align-items: stretch;
    }

    .token-controls {
        justify-content: space-between;
    }

    .token-input {
        width: 100%;
        min-width: 0;
    }
}

// ============================================
// Global Theme Presets
// ============================================

.global-theme-group {
    border: 1px solid var(--vera-accent-20);
    background: linear-gradient(135deg, var(--vera-accent-05) 0%, transparent 100%);
}

.global-theme-selector {
    margin-bottom: 16px;
}

.global-theme-dropdown {
    margin-bottom: 12px;
}

.global-theme-select {
    width: 100%;
    max-width: 320px;
    padding: 10px 14px;
    border-radius: 10px;
    border: 1px solid var(--vera-border);
    background: var(--vera-input-bg);
    color: var(--vera-text);
    font-size: 0.875rem;
    cursor: pointer;
    transition: all 0.2s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
    }

    &:focus {
        outline: none;
        border-color: var(--vera-accent);
        box-shadow: 0 0 12px var(--vera-accent-20);
    }
}

.global-theme-description {
    font-size: 0.75rem;
    color: var(--vera-text-muted);
    font-style: italic;
    margin: 0 0 8px 0;
}

.global-theme-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
    gap: 10px;

    @media (max-width: 600px) {
        grid-template-columns: repeat(3, 1fr);
    }

    @media (max-width: 400px) {
        grid-template-columns: repeat(2, 1fr);
    }
}

.global-theme-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 10px 8px;
    border-radius: 12px;
    border: 2px solid var(--vera-border);
    background: var(--vera-panel-muted);
    cursor: pointer;
    transition: all 0.25s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
        background: var(--vera-accent-05);
        transform: translateY(-2px);
    }

    &.active {
        border-color: var(--vera-accent);
        background: var(--vera-accent-10);
        box-shadow: 0 0 16px var(--vera-accent-20), inset 0 0 12px var(--vera-accent-06);
    }
}

.global-theme-preview {
    position: relative;
    width: 60px;
    height: 40px;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid var(--vera-border);

    .preview-bg {
        position: absolute;
        inset: 0;
    }

    .preview-accent {
        position: absolute;
        bottom: 6px;
        left: 6px;
        width: 16px;
        height: 16px;
        border-radius: 50%;
        box-shadow: 0 0 8px currentColor;
    }

    .preview-secondary {
        position: absolute;
        bottom: 6px;
        right: 6px;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        opacity: 0.8;
    }
}

.global-theme-label {
    font-size: 0.6875rem;
    font-weight: 500;
    color: var(--vera-text);
    text-align: center;
    line-height: 1.2;
}

// ============================================
// Accordion Tree (Advanced Tab)
// ============================================

.accordion-controls {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
}

.accordion-control-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 8px;
    border: 1px solid var(--vera-border);
    background: transparent;
    color: var(--vera-text-muted);
    font-size: 0.75rem;
    cursor: pointer;
    transition: all 0.2s ease;

    &:hover {
        border-color: var(--vera-accent-soft);
        color: var(--vera-text);
        background: var(--vera-accent-05);
    }
}

.token-accordion-tree {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

// Region level (top level)
.accordion-region {
    border: 1px solid var(--vera-border);
    border-radius: 14px;
    background: color-mix(in srgb, var(--vera-panel) 50%, transparent);
    overflow: hidden;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;

    &.expanded {
        border-color: var(--vera-accent-30);
        box-shadow: 0 0 12px var(--vera-accent-10);
    }
}

.accordion-header {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 12px 14px;
    border: none;
    background: transparent;
    color: var(--vera-text);
    cursor: pointer;
    transition: background 0.2s ease;

    &:hover {
        background: var(--vera-accent-05);
    }
}

.accordion-header--region {
    font-size: 0.95rem;
    font-weight: 600;
}

.accordion-header--panel {
    font-size: 0.9rem;
    font-weight: 500;
    padding: 10px 12px;
}

.accordion-header--part {
    font-size: 0.85rem;
    font-weight: 500;
    padding: 8px 10px;
}

.accordion-chevron {
    color: var(--vera-accent);
    flex-shrink: 0;
    transition: transform 0.2s ease;
}

.accordion-label {
    flex: 1;
    text-align: left;
}

.accordion-count {
    font-size: 0.6875rem;
    font-weight: 500;
    color: var(--vera-text-muted);
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--vera-accent-10);
}

.accordion-description {
    margin: 0 14px 10px;
    padding: 0;
    font-size: 0.75rem;
    color: var(--vera-text-muted);
    line-height: 1.4;
}

.accordion-description--panel {
    margin: 0 12px 8px;
    font-size: 0.6875rem;
}

.accordion-content {
    padding: 0 14px 14px;
}

.accordion-content--panel {
    padding: 0 12px 12px;
}

.accordion-content--part {
    padding: 0 10px 10px;
}

// Panel level (second level)
.accordion-panel {
    margin-top: 4px;
    border: 1px solid var(--vera-border);
    border-radius: 12px;
    background: color-mix(in srgb, var(--vera-panel-alt) 40%, transparent);
    overflow: hidden;
    transition: border-color 0.2s ease;

    &.expanded {
        border-color: var(--vera-accent-20);
    }
}

// Part level (third level)
.accordion-part {
    margin-top: 4px;
    border: 1px solid var(--vera-border);
    border-radius: 10px;
    background: color-mix(in srgb, var(--vera-panel-muted) 30%, transparent);
    overflow: hidden;
    transition: border-color 0.2s ease;

    &.expanded {
        border-color: var(--vera-accent-15);
    }
}

// Subpart level (fourth level - no expand/collapse)
.accordion-subpart {
    margin-top: 8px;
    padding: 8px 10px;
    border-radius: 8px;
    background: var(--vera-panel-muted);
    border: 1px dashed var(--vera-border);
}

.accordion-subpart-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
    padding-bottom: 6px;
    border-bottom: 1px dashed var(--vera-border);

    .accordion-label {
        font-size: 0.75rem;
        font-weight: 500;
        color: var(--vera-text-muted);
    }
}

.token-accordion-tokens {
    margin-top: 8px;
}

// Slide transition for accordion
.accordion-slide-enter-active,
.accordion-slide-leave-active {
    transition: all 0.25s ease;
    overflow: hidden;
}

.accordion-slide-enter-from,
.accordion-slide-leave-to {
    opacity: 0;
    max-height: 0;
    padding-top: 0;
    padding-bottom: 0;
}

.accordion-slide-enter-to,
.accordion-slide-leave-from {
    opacity: 1;
    max-height: 2000px;
}

// ============================================
// Color Grid (for Terminal/Status colors)
// ============================================

.color-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    padding: 8px 0;

    @media (max-width: 600px) {
        grid-template-columns: repeat(2, 1fr);
    }
}

.color-item {
    display: flex;
    flex-direction: column;
    gap: 6px;
    align-items: center;

    label {
        font-size: 0.6875rem;
        font-weight: 500;
        color: var(--vera-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    input[type="color"] {
        width: 48px;
        height: 32px;
        border: 1px solid var(--vera-border);
        border-radius: 8px;
        cursor: pointer;
        background: var(--vera-glass-bg);
        transition: all 0.2s ease;

        &:hover {
            border-color: var(--vera-accent);
            box-shadow: 0 0 8px rgba(var(--vera-accent-rgb), 0.2);
        }

        &::-webkit-color-swatch-wrapper {
            padding: 3px;
        }

        &::-webkit-color-swatch {
            border: none;
            border-radius: 5px;
        }
    }
}

// ============================================
// Reduced Motion
// ============================================

@media (prefers-reduced-motion: reduce) {
    .avatar-preview-large,
    .tab-indicator,
    .premium-toggle .toggle-thumb,
    .premium-slider::-webkit-slider-thumb,
    .type-card,
    .preset-card,
    .drop-zone,
    .premium-reset-button svg {
        animation: none !important;
        transition-duration: 0.01ms !important;
    }
}
</style>

<style lang="scss">
// Transition for collapsible sections - must be unscoped for Vue transitions
.slide-fade-enter-active,
.slide-fade-leave-active {
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    max-height: 90vh;
    overflow: hidden;
}

.slide-fade-enter-from,
.slide-fade-leave-to {
    max-height: 0;
    opacity: 0;
    transform: translateY(-10px);
}

.theme-token-highlight {
    outline: 3px solid rgba(var(--vera-accent-rgb), 0.95);
    outline-offset: 3px;
    box-shadow:
        0 0 0 3px rgba(var(--vera-accent-rgb), 0.35),
        0 0 26px rgba(var(--vera-accent-rgb), 0.6),
        0 0 60px rgba(var(--vera-accent-rgb), 0.45);
    animation: themeTokenPulse 0.9s ease-in-out infinite;
}

@keyframes themeTokenPulse {
    0%, 100% {
        box-shadow:
            0 0 0 3px rgba(var(--vera-accent-rgb), 0.35),
            0 0 20px rgba(var(--vera-accent-rgb), 0.55),
            0 0 50px rgba(var(--vera-accent-rgb), 0.4);
    }
    50% {
        box-shadow:
            0 0 0 4px rgba(var(--vera-accent-rgb), 0.55),
            0 0 36px rgba(var(--vera-accent-rgb), 0.8),
            0 0 80px rgba(var(--vera-accent-rgb), 0.65);
    }
}

@media (prefers-reduced-motion: reduce) {
    .theme-token-highlight {
        animation: none;
    }
}
</style>
