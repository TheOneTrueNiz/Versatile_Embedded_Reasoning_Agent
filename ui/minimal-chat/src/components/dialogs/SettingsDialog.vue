<script setup>
import { ref, watch, onMounted } from 'vue';
import DialogHeader from '@/components/controls/DialogHeader.vue';
import GeneralConfigSection from '@/components/configuration-sections/GeneralConfigSection.vue';
import AppearanceConfigSection from '@/components/configuration-sections/AppearanceConfigSection.vue';
import AccessibilityConfigSection from '@/components/configuration-sections/AccessibilityConfigSection.vue';
import LocalConfigSection from '@/components/configuration-sections/LocalConfigSection.vue';
import ImportExportConfigSection from '@/components/configuration-sections/ImportExportConfigSection.vue';
import { getOpenAICompatibleAvailableModels } from '@/libs/api-access/open-ai-api-standard-access';
import {
    selectedModel,
    localModelEndpoint,
    localModelKey,
    maxTokens,
    localSliderValue,
    top_P,
    repetitionPenalty,
    isSidebarOpen,
    isSmallScreen,
    isSidebarVisible,
    systemPrompt,
    availableModels,

} from '@/libs/state-management/state';
import { removeAPIEndpoints } from '@/libs/utils/general-utils';
import { runTutorialForSettings } from '@/libs/utils/tutorial-utils';
import {
    selectCustomConfig,
    systemPrompts,
    selectedSystemPromptIndex,
    customConfigs,
    selectedCustomConfigIndex,
    handleSelectCustomConfig,
    handleDeleteCustomConfig

} from '@/libs/utils/settings-utils';
import "swiped-events";
import { ChevronDown, ChevronRight, Settings, Trash2, Menu, X, Database, PlusCircle, Github, Palette, Accessibility } from 'lucide-vue-next';

// Visibility states for collapsible config sections
const isClaudeConfigOpen = ref(false);
const isGPTConfigOpen = ref(false);
const isCustomConfigOpen = ref(false);
const selectedCustomConfig = ref(null);

watch(isSidebarOpen, (newVal) => {
    if (newVal) {
        runTutorialForSettings();
    }
});

async function fetchAvailableModels() {
    try {
        if (localModelEndpoint.value.trim() !== '') {
            const models = await getOpenAICompatibleAvailableModels(removeAPIEndpoints(localModelEndpoint.value));
            availableModels.value = models;
        }
    } catch (error) {
        console.error('Error fetching available models:', error);
    }
}

function toggleSidebar() {
    isSidebarVisible.value = !isSidebarVisible.value;
}

function swipedRight(e) {
    event.stopPropagation();
    if (!e.detail.xStart || e.detail.xStart >= 100) {
        console.log('Swipe did not start at the edge of the left side of the screen');
        isSidebarOpen.value = true;
        return;
    }

    isSidebarOpen.value = false;
}

const lastTap = ref(0);
function handleTouchStart(event) {


    if (!isSmallScreen.value) {
        return;
    }

    const currentTime = new Date().getTime();
    const tapLength = currentTime - lastTap.value;

    console.log(tapLength);
    if (tapLength < 300 && tapLength > 0) {
        event.preventDefault();

        isSidebarVisible.value = true;
    }
    lastTap.value = currentTime;
}

const showingGeneralConfig = ref(true);
const showingAppearanceConfig = ref(false);
const showingAccessibilityConfig = ref(false);

function showGeneralConfigSection() {
    showingGeneralConfig.value = true;
    showingAppearanceConfig.value = false;
    showingAccessibilityConfig.value = false;
    isSidebarVisible.value = false;
}

function showAppearanceConfigSection() {
    showingGeneralConfig.value = false;
    showingAppearanceConfig.value = true;
    showingAccessibilityConfig.value = false;
    isSidebarVisible.value = false;
}

function showAccessibilityConfigSection() {
    showingGeneralConfig.value = false;
    showingAppearanceConfig.value = false;
    showingAccessibilityConfig.value = true;
    isSidebarVisible.value = false;
}

function selectCustomModel(index) {
    handleSelectCustomConfig(index);
    // selectedCustomConfig.value = configName;

    showingGeneralConfig.value = false;
    showingAppearanceConfig.value = false;
    showingAccessibilityConfig.value = false;
    isClaudeConfigOpen.value = false;
    isGPTConfigOpen.value = false;
    isCustomConfigOpen.value = false;

    isSidebarVisible.value = false;

}

function selectModel(model) {
    selectedModel.value = model;
    selectedCustomConfig.value = null;
    isCustomConfigOpen.value = false;

    showingGeneralConfig.value = false;
    showingAppearanceConfig.value = false;
    showingAccessibilityConfig.value = false;
    isClaudeConfigOpen.value = false;
    isGPTConfigOpen.value = false;
    isCustomConfigOpen.value = false;

    if (model === 'open-ai-format') {
        // Reset fields when adding a new connection
        localModelEndpoint.value = localStorage.getItem('localModelEndpoint') || window.location.origin;
        localModelKey.value = '';
        localModelName.value = '';
        availableModels.value = [];
        selectedCustomConfigIndex.value = null;
        fetchAvailableModels();
    }

    isSidebarVisible.value = false;
}


// Lifecycle hooks
onMounted(() => {
    if (selectedModel.value !== 'open-ai-format') {
        selectedModel.value = 'open-ai-format';
    }
    if (selectedModel.value === 'open-ai-format') {
        fetchAvailableModels();
    }
    
    // Ensure GeneralConfigSection is always shown first when opening
    showingGeneralConfig.value = true;
    showingAppearanceConfig.value = false;
    showingAccessibilityConfig.value = false;

    console.log("Mounted");
    console.log("Selected Model:", selectedModel.value);

    const storedSystemPrompts = localStorage.getItem('system-prompts');
    if (storedSystemPrompts) {
        systemPrompts.value = JSON.parse(storedSystemPrompts);
        const savedPromptIndex = systemPrompts.value.findIndex((prompt) => prompt === systemPrompt.value);
        if (savedPromptIndex !== -1) {
            selectedSystemPromptIndex.value = savedPromptIndex;
        }
    }

    const storedCustomConfigs = localStorage.getItem('saved-custom-configs');
    if (storedCustomConfigs) {
        customConfigs.value = JSON.parse(storedCustomConfigs);

        if (customConfigs.value.length > 0) {
            const matchingConfigIndex = customConfigs.value.findIndex((config) => config.endpoint === localModelEndpoint.value);

            if (matchingConfigIndex !== -1 && selectedModel.value.includes("open-ai-format")) {
                selectedCustomConfigIndex.value = matchingConfigIndex;
                const config = customConfigs.value[matchingConfigIndex];
                localModelEndpoint.value = config.endpoint;
                localModelKey.value = config.apiKey;
                maxTokens.value = config.maxTokens;
                localSliderValue.value = config.temperature;
                top_P.value = config.top_P;
                repetitionPenalty.value = config.repetitionPenalty;

                selectCustomConfig(selectedCustomConfigIndex.value, localModelEndpoint, localModelKey, maxTokens, localSliderValue, top_P, repetitionPenalty);
            }
        } else {
            console.log('No saved custom configs found.');
        }
    } else {
        console.log('No saved custom configs found.');
    }
});
</script>

<template>
    <div class="settings-dialog" data-swipe-threshold="15" data-swipe-unit="vw" data-swipe-timeout="500"
        @swiped-right="swipedRight">
        <!-- Premium Background Layers (matching ToolsDrawer/SwarmDrawer architecture) -->
        <div class="bg-layer bg-hexgrid">
            <svg class="hexgrid-svg" viewBox="0 0 800 600" preserveAspectRatio="xMidYMid slice">
                <defs>
                    <pattern id="hexPattern" x="0" y="0" width="60" height="52" patternUnits="userSpaceOnUse">
                        <path class="hex-path" d="M30,0 L60,15 L60,37 L30,52 L0,37 L0,15 Z" fill="none" stroke-width="0.5"/>
                    </pattern>
                    <radialGradient id="hexFade" cx="50%" cy="50%" r="70%">
                        <stop offset="0%" stop-color="rgba(var(--vera-contrast-rgb),0.15)"/>
                        <stop offset="100%" stop-color="rgba(var(--vera-contrast-rgb),0)"/>
                    </radialGradient>
                </defs>
                <rect width="100%" height="100%" fill="url(#hexPattern)" mask="url(#hexFade)"/>
                <!-- Animated connection lines -->
                <line v-for="i in 8" :key="'hline-'+i" class="hex-connection"
                    :x1="50 + i * 90" :y1="50 + (i % 3) * 120"
                    :x2="140 + i * 90" :y2="110 + (i % 4) * 100"
                    :style="`animation-delay: ${i * 0.3}s`"/>
                <!-- Node points -->
                <circle v-for="i in 12" :key="'hnode-'+i" class="hex-node"
                    :cx="30 + (i % 6) * 130" :cy="40 + Math.floor(i / 6) * 200" r="3"
                    :style="`animation-delay: ${i * 0.2}s`"/>
            </svg>
        </div>
        <div class="bg-layer bg-radial-glow"></div>
        <div class="bg-layer bg-data-streams">
            <span v-for="i in 6" :key="'stream-'+i" class="data-stream-particle" :style="`--delay: ${i * 0.7}s; --x-pos: ${8 + i * 15}%`"></span>
        </div>
        <div class="bg-layer bg-glow-orbs">
            <span class="glow-orb glow-orb-1"></span>
            <span class="glow-orb glow-orb-2"></span>
            <span class="glow-orb glow-orb-3"></span>
        </div>

        <!-- Premium Border System -->
        <div class="premium-border premium-border-top">
            <span class="border-pulse"></span>
        </div>
        <div class="premium-border premium-border-bottom"></div>
        <div class="premium-border premium-border-left"></div>
        <div class="premium-border premium-border-right"></div>

        <DialogHeader title="Configuration" :icon="Settings" :iconSize="32"
            tooltipText="Current Version: 6.3.0 Stellar Nebula" headerId="settings-header"
            @close="() => isSidebarOpen = false" />
        <div class="settings-container">
            <Sidebar v-model:visible="isSidebarVisible" :baseZIndex="1000" :modal="true" @hide="isSidebarVisible = false" class="mobile-sidebar">
                <div class="sidebar-header">
                    <h3>Configuration</h3>
                </div>
                <div class="sidebar-divider"></div>
                <ul class="sidebar-menu">
                    <li :class="{ selected: showingGeneralConfig }" @click="showGeneralConfigSection">
                        <Settings size="18" class="menu-icon" />
                        <span>VERA Settings</span>
                    </li>
                    <li :class="{ selected: showingAppearanceConfig }" @click="showAppearanceConfigSection">
                        <Palette size="18" class="menu-icon" />
                        <span>Appearance</span>
                    </li>
                    <li :class="{ selected: showingAccessibilityConfig }" @click="showAccessibilityConfigSection">
                        <Accessibility size="18" class="menu-icon" />
                        <span>Accessibility</span>
                    </li>
                    <li class="parent-item">
                        <div class="list-header" @click="isCustomConfigOpen = !isCustomConfigOpen">
                            <div class="header-left">
                                <Database size="18" class="menu-icon" />
                                <span>API Connections</span>
                            </div>
                            <ChevronDown v-if="isCustomConfigOpen" class="indicator" size="20" />
                            <ChevronRight v-else class="indicator" size="20" />
                        </div>
                        <transition name="slide-fade">
                            <ul v-show="isCustomConfigOpen" class="nested-list">
                                <li v-for="(config, index) in customConfigs" :key="config.endpoint"
                                    :class="{ selected: selectedModel === 'open-ai-format' && localModelEndpoint === config.endpoint }"
                                    @click="selectCustomModel(index)">
                                    <div class="item-content">
                                        <Trash2 :size="18" :stroke-width="1.5" @click.stop="handleDeleteCustomConfig(index)" 
                                          class="delete-icon" />
                                        <span class="endpoint-text">{{ config.endpoint }}</span>
                                    </div>
                                </li>
                                <li v-if="!customConfigs.length" @click="selectModel('open-ai-format')" class="add-api-item">
                                    <div class="item-content">
                                        <PlusCircle size="18" class="add-icon" />
                                        <span>Add Connection</span>
                                    </div>
                                </li>
                            </ul>
                        </transition>
                    </li>
                    <!-- Browser model selection removed for VERA-only setup -->
                </ul>
            </Sidebar>

            <div v-show="!isSmallScreen" class="left-panel">
                <h3>Configuration</h3>
                <ul class="model-menu">
                    <li :class="{ selected: showingGeneralConfig }" @click="showGeneralConfigSection">
                        <Settings size="18" class="menu-icon" />
                        <span>VERA Settings</span>
                    </li>
                    <li :class="{ selected: showingAppearanceConfig }" @click="showAppearanceConfigSection">
                        <Palette size="18" class="menu-icon" />
                        <span>Appearance</span>
                    </li>
                    <li :class="{ selected: showingAccessibilityConfig }" @click="showAccessibilityConfigSection">
                        <Accessibility size="18" class="menu-icon" />
                        <span>Accessibility</span>
                    </li>

                    <!-- API Connections Section -->
                    <div class="connections-section">
                        <div class="section-header" @click="isCustomConfigOpen = !isCustomConfigOpen">
                            <Database size="18" class="menu-icon" />
                            <span>API Connections</span>
                            <div class="header-icon">
                                <ChevronDown v-if="isCustomConfigOpen || selectedModel === 'open-ai-format'" :size="16" />
                                <ChevronRight v-else :size="16" />
                            </div>
                        </div>
                        
                        <transition name="slide-fade">
                            <div v-show="isCustomConfigOpen || selectedModel === 'open-ai-format'" class="connections-container">
                                <!-- Empty state when no connections -->
                                <div v-if="!customConfigs.length" 
                                     class="empty-connections"
                                     @click="selectModel('open-ai-format')">
                                    <PlusCircle size="24" class="add-icon" />
                                    <p>Add your first connection</p>
                                </div>
                                
                                <!-- Connection cards list -->
                                <div v-else class="connection-cards">
                                    <div v-for="(config, index) in customConfigs" 
                                         :key="config.endpoint"
                                         :class="['connection-card', { 'selected': selectedModel === 'open-ai-format' && selectedCustomConfigIndex === index }]"
                                         @click="selectCustomModel(index)">
                                        <div class="connection-content">
                                            <div class="connection-url">{{ config.endpoint }}</div>
                                            <div class="connection-model">{{ config.modelName || 'No model selected' }}</div>
                                        </div>
                                        <button class="delete-btn" @click.stop="handleDeleteCustomConfig(index)">
                                            <Trash2 :size="16" :stroke-width="1.5" />
                                        </button>
                                    </div>
                                    
                                    <!-- Add new connection button -->
                                    <div class="add-connection" @click="selectModel('open-ai-format')">
                                        <PlusCircle size="16" class="add-icon" />
                                        <span>Add Connection</span>
                                    </div>
                                </div>
                            </div>
                        </transition>
                    </div>
                    
                    <!-- Browser model selection removed for VERA-only setup -->
                </ul>
                <div class="close-btn-wrapper">
                </div>
            </div>
            <div class="right-panel" @touchstart="handleTouchStart">
                <div v-if="selectedModel">
                    <div v-if="showingGeneralConfig">
                        <GeneralConfigSection />
                        <ImportExportConfigSection />
                        
                        <!-- GitHub repository section -->
                        <div class="github-section">
                            <a href="https://github.com/nizbot/NizBot_Vera" target="_blank" class="github-link">
                                <div class="github-content">
                                    <div class="github-icon">
                                        <Github size="22" />
                                    </div>
                                    <div class="github-info">
                                        <h4>VERA</h4>
                                        <p>View VERA source code on GitHub</p>
                                    </div>
                                </div>
                            </a>
                        </div>
                    </div>
                    <div v-if="showingAppearanceConfig">
                        <AppearanceConfigSection />
                    </div>
                    <div v-if="showingAccessibilityConfig">
                        <AccessibilityConfigSection />
                    </div>
                    <div v-if="selectedModel === 'open-ai-format' && !showingGeneralConfig && !showingAppearanceConfig && !showingAccessibilityConfig">
                        <LocalConfigSection />
                    </div>
                    <!-- Web LLM config removed for VERA-only setup -->
                </div>
            </div>
        </div>
        <button v-if="isSmallScreen" class="floating-button" @click="toggleSidebar">
    <Menu size="24" />
</button>
    </div>
</template>


<style lang="scss" scoped>
$shadow-color: var(--vera-shadow);
$icon-color: var(--vera-icon);
$primary-bg-color: var(--vera-glass-strong);
$secondary-bg-color: var(--vera-glass-bg);
$highlight-bg-color: var(--vera-accent);
$button-bg-color: var(--vera-accent);
$button-hover-bg-color: var(--vera-accent-strong);
$delete-color: var(--vera-danger);
$delete-hover-color: var(--vera-danger);
$input-bg-color: var(--vera-input-bg);
$input-hover-bg-color: var(--vera-panel);
$input-focus-bg-color: var(--vera-panel-alt);
$header-bg-color: var(--vera-header-bg);
$close-btn-bg-color: var(--vera-glass-bg);
$close-btn-hover-bg-color: var(--vera-accent-faint);
$close-btn-active-bg-color: var(--vera-accent-soft);
$border-color: var(--vera-glass-border);
$header-border-color: var(--vera-glass-border);
$bottom-panel-bg-color: var(--vera-glass-bg);
$bottom-panel-border-color: var(--vera-glass-border);

.slide-fade-enter-active,
.slide-fade-leave-active {
    transition: all 0.2s ease-out;
    max-height: 500px;
    overflow: hidden;
}

.slide-fade-enter-from,
.slide-fade-leave-to {
    max-height: 0;
    opacity: 0;
    transform: translateY(-10px);
}

.scale-enter-active,
.scale-leave-active {
    transition: transform 0.15s ease-out;
}

.p-sidebar {
    background-color: var(--vera-glass-strong);
    width: 250px;
    padding: 0;
    animation: slideIn calc(0.15s / var(--vera-anim-speed, 1)) ease;
    transition: all calc(0.15s / var(--vera-anim-speed, 1));
    z-index: 1000;
    box-shadow: 0 0 24px var(--vera-shadow);
    border-right: 1px solid var(--vera-glass-border);
    font-family: var(--vera-font-sidebar);
    color: var(--vera-text-sidebar);
    
    @media (max-width: 600px) {
        width: 85vw;
        padding: 0;
    }
    
    &.mobile-sidebar {
        .p-sidebar-content {
            padding: 0 !important;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            height: 100%;
        }
        
        .sidebar-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px;
            background: var(--vera-panel-gradient);
            border-bottom: 1px solid var(--vera-glass-border);
            
            h3 {
                margin: 0;
                font-size: 1.3em;
                color: var(--vera-text);
            }

            .close-sidebar-btn {
                background: transparent;
                border: none;
                color: var(--vera-text);
                cursor: pointer;
                padding: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 50%;
                transition: background-color 0.2s;
                
                &:hover {
                    background-color: rgba(var(--vera-contrast-rgb), 0.1);
                }
            }
        }
        
        .sidebar-divider {
            height: 1px;
            background: linear-gradient(to right, var(--vera-accent-15), var(--vera-accent-60), var(--vera-accent-15));
            margin: 0;
        }
        
        .sidebar-menu {
            list-style-type: none;
            padding: 16px;
            margin: 0;
            overflow-y: auto;
            flex-grow: 1;
            
            > li {
                padding: 14px 12px;
                cursor: pointer;
                border-radius: 8px;
                transition: all 0.2s ease;
                margin-bottom: 8px;
                display: flex;
                align-items: center;
                font-size: 1rem;
                
                .menu-icon {
                    margin-right: 12px;
                    opacity: 0.7;
                    color: var(--vera-text-muted);
                    transition: all 0.2s ease;
                }
                
                &:hover {
                    background-color: var(--vera-accent-faint);
                    box-shadow: inset 0 0 0 1px var(--vera-accent-faint);
                    
                    .menu-icon {
                        opacity: 1;
                        color: var(--vera-accent);
                    }
                }
                
                &.selected {
                    background-color: var(--vera-accent-soft);
                    color: var(--vera-text);
                    box-shadow: inset 0 0 0 1px var(--vera-accent);
                    
                    .menu-icon {
                        opacity: 1;
                        color: var(--vera-accent);
                    }
                }
            }
            
            .parent-item {
                padding: 0;
                margin-bottom: 12px;
                border-radius: 8px;
                overflow: visible;
                background-color: transparent;
                display: block;
                
                .list-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 14px 12px;
                    cursor: pointer;
                    border-radius: 8px;
                    transition: all 0.2s ease;
                    
                    .header-left {
                        display: flex;
                        align-items: center;
                        
                        .menu-icon {
                            margin-right: 12px;
                            opacity: 0.7;
                            color: var(--vera-text-muted);
                            transition: all 0.2s ease;
                        }
                    }
                    
                    &:hover {
                        background-color: var(--vera-accent-faint);
                        box-shadow: inset 0 0 0 1px var(--vera-accent-faint);
                        
                        .menu-icon {
                            opacity: 1;
                            color: var(--vera-accent);
                        }
                    }
                    
                    .indicator {
                        color: var(--vera-text-muted);
                        transition: all 0.2s ease;
                    }
                }
            }
            
            .nested-list {
                padding: 8px 0 0 0;
                margin-top: 4px;
                list-style: none;
                
                li {
                    margin-top: 4px;
                    margin-bottom: 4px;
                    background-color: var(--vera-success-10);
                    padding: 12px;
                    border-radius: 6px;
                    font-size: 0.9375rem;
                    display: flex;
                    align-items: center;
                    
                    .item-content {
                        display: flex;
                        align-items: center;
                        width: 100%;
                        overflow: hidden;
                    }
                    
                    .delete-icon {
                        margin-right: 10px;
                        min-width: 18px;
                        color: var(--vera-text-muted);
                        transition: color 0.2s ease;
                        
                        &:hover {
                            color: var(--vera-danger);
                        }
                    }
                    
                    .endpoint-text {
                        overflow: hidden;
                        text-overflow: ellipsis;
                        white-space: nowrap;
                        max-width: calc(100% - 30px);
                    }
                    
                    &:hover {
                        background-color: var(--vera-accent-faint);
                    }
                    
                    &.selected {
                        background-color: var(--vera-accent-soft);
                    }
                    
                    &.add-api-item {
                        background-color: var(--vera-accent-faint);
                        border: 1px dashed var(--vera-accent-soft);
                        
                        .add-icon {
                            color: var(--vera-accent);
                            margin-right: 10px;
                        }
                        
                        &:hover {
                            background-color: var(--vera-accent-soft);
                            border-color: var(--vera-accent);
                        }
                    }
                }
            }
        }
    }
}

@keyframes slideIn {
    0% {
        transform: translateX(-100%);
    }

    100% {
        transform: translateX(0);
    }
}

.center-text {
    text-align: center;
    padding-bottom: 6px;
}

.expand-sidebar-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    background-color: $button-bg-color;
    color: var(--primary-color-text);
    padding: 10px;
    border-radius: 4px;
    cursor: pointer;
    margin: 10px;
    transition: background-color 0.15s;

    &:hover {
        background-color: $button-hover-bg-color;
    }
}

.config-section {
    margin-bottom: 15px;

    h3 {
        margin-bottom: 15px;
        background-color: transparent;
        border-bottom: 2px solid var(--vera-accent);
        text-align: left;
        position: relative;
        display: flex;
        justify-content: space-between;
        align-items: center;
        cursor: pointer;
        padding: 8px;
    }

    .config-info {
        font-size: 0.75rem;
    }

    .control-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 20px;
        transition: max-height 0.15s ease-in-out;
        overflow: hidden;
        max-height: 0;

        @media (max-width: 600px) {
            grid-template-columns: repeat(1, 1fr);
        }
    }

    &.show .control-grid {
        max-height: fit-content;
    }
}

.control-checkbox {
    display: flex;
    align-items: center;
    width: 100%;

    label {
        display: flex;
        align-items: center;
        cursor: pointer;
        font-size: 1rem;
        color: var(--vera-text);
        position: relative;
        width: 100%;
        user-select: none;

        input[type="checkbox"] {
            opacity: 0;
            width: 0;
            height: 0;

            &:checked+.slider:before {
                transform: translateX(26px);
            }

            &:checked+.slider {
                background-color: var(--vera-accent);
            }
        }

        .slider {
            width: 40px;
            height: 20px;
            background-color: var(--vera-panel-alt);
            border-radius: 34px;
            transition: background-color 0.15s;
            position: relative;
            margin-left: 10px;

            &:before {
                position: absolute;
                content: "";
                height: 12px;
                width: 12px;
                left: 4px;
                bottom: 4px;
                background-color: var(--vera-text);
                border-radius: 50%;
                transition: transform 0.15s;
            }
        }
    }
}

.select-dropdown select {
    appearance: none;
    background-color: $input-bg-color;
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
        background-color: $input-hover-bg-color;
    }

    &:focus {
        outline: none;
    }
}

.select-dropdown option {
    background-color: $input-focus-bg-color;
    color: var(--vera-text);
}

.control-grid .settings-list {
    display: flex;
    gap: 0.5rem;

    .settings-item-button {
        display: inline-flex;
        justify-content: space-between;
        align-items: center;
        gap: 8px;
        padding: 6px 8px;
        margin: 6px 0;
        border-radius: 6px;
        cursor: pointer;
        background: $button-bg-color;
        flex-direction: column-reverse;
        transition: background 0.15s ease;

        &:hover {
            background: var(--vera-accent-strong);
        }
    }
}

.system-prompt-container,
.saved-custom-configs,
.saved-system-prompts {

    h4 {
        margin-bottom: 10px;
    }

    ul {
        list-style-type: none;
        padding: 0;
        max-height: 15vh;
        overflow-y: auto;
        text-overflow: ellipsis;
        scrollbar-width: none;
        text-wrap: nowrap;

        li {
            display: flex;
            align-items: center;
            padding: 8px;
            background-color: var(--vera-accent-strong);
            border-radius: 4px;
            margin-bottom: 8px;
            max-height: 6vh;
            overflow: hidden;
            text-align: left;
            cursor: pointer;

            &.selected {
                background-color: $button-bg-color;
            }

            .delete-system-prompt-btn,
            .delete-custom-config-btn {
                background-color: transparent;
                border: none;
                color: $delete-color;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 5px;

                &:hover {
                    color: $delete-hover-color;
                }
            }
        }
    }
}

.save-system-prompt-btn,
.save-custom-config-btn {
    padding: 6px 12px;
    background-color: $button-bg-color;
    color: var(--primary-color-text);
    border: none;
    border-radius: 4px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 5px;

    &:hover {
        background-color: $button-hover-bg-color;
    }
}

// ============================================
// Main Container - Premium Glass Surface
// ============================================

.settings-dialog {
    display: flex;
    flex-direction: column;
    max-height: 98vh;
    min-height: 98vh;
    max-width: 99vw;
    position: relative;
    overflow: hidden;
    border-radius: var(--vera-radius-xl);

    // Text color that contrasts with surface
    color: var(--vera-surface-text);

    // Premium glass surface
    background: var(--vera-panel-gradient);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);

    // Premium border with gradient
    border: 1px solid transparent;
    background-clip: padding-box;

    // Layered shadow for depth
    box-shadow:
        0 0 0 1px var(--vera-accent-10),
        0 4px 30px rgba(var(--vera-shadow-rgb), 0.4),
        0 8px 60px rgba(var(--vera-shadow-rgb), 0.3),
        inset 0 1px 0 rgba(var(--vera-contrast-rgb), 0.05),
        inset 0 -1px 0 rgba(var(--vera-shadow-rgb), 0.2);

    // Content above background layers
    > *:not(.bg-layer):not(.premium-border) {
        position: relative;
        z-index: 10;
    }
    
/* Model menu */
.model-menu {
    display: flex;
    flex-direction: column;
    gap: 10px;
    
    li {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 15px;
        border-radius: 8px;
        transition: all 0.2s ease;
        border: none;
        margin-bottom: 0;
        
        .menu-icon {
            color: var(--vera-accent);
            opacity: 0.8;
            transition: all 0.2s ease;
        }
        
        &:hover {
            background-color: var(--vera-accent-faint);
            box-shadow: inset 0 0 0 1px var(--vera-accent-faint);
            
            .menu-icon {
                opacity: 1;
            }
        }
        
        &.selected {
            background-color: var(--vera-accent-soft);
            border-left: 3px solid var(--vera-accent);
            box-shadow: inset 0 0 0 1px var(--vera-accent);
            
            .menu-icon {
                opacity: 1;
            }
        }
    }
}

/* API Connections section */
.connections-section {
    margin: 5px 0;
    border-radius: 8px;
    overflow: hidden;
    
    .section-header {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 15px;
        cursor: pointer;
        border-radius: 8px;
        transition: background-color 0.2s ease;
        
        .menu-icon {
            color: var(--vera-accent);
            opacity: 0.8;
            transition: all 0.2s ease;
        }
        
        span {
            flex-grow: 1;
        }
        
        .header-icon {
            color: var(--vera-text-muted);
            transition: all 0.2s ease;
        }
        
        &:hover {
            background-color: var(--vera-accent-faint);
            box-shadow: inset 0 0 0 1px var(--vera-accent-faint);
            
            .menu-icon {
                opacity: 1;
            }
        }
    }
    
    .connections-container {
        padding: 5px 10px 10px 10px;
    }
    
    .empty-connections {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 10px;
        padding: 20px;
        text-align: center;
        background-color: var(--vera-accent-faint);
        border: 1px dashed var(--vera-accent-soft);
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s ease;
        
        .add-icon {
            color: var(--vera-accent);
            opacity: 0.8;
        }
        
        p {
            margin: 0;
            color: var(--vera-text-muted);
            font-size: 0.875rem;
        }
        
        &:hover {
            background-color: var(--vera-accent-soft);
            border-color: var(--vera-accent);
            box-shadow: inset 0 0 0 1px var(--vera-accent);
            
            .add-icon {
                opacity: 1;
            }
        }
    }
    
    .connection-cards {
        display: flex;
        flex-direction: column;
        gap: 8px;
        
        .connection-card {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px;
            background-color: var(--vera-accent-faint);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s ease;
            position: relative;
            overflow: hidden;
            
            &::before {
                content: '';
                position: absolute;
                left: 0;
                top: 0;
                height: 100%;
                width: 0;
                background-color: var(--vera-accent);
                transition: width 0.2s ease;
            }
            
            .connection-content {
                flex-grow: 1;
                z-index: 1;
                
                .connection-url {
                    font-weight: 500;
                    font-size: 0.875rem;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    max-width: 180px;
                }
                
                .connection-model {
                    font-size: 0.75rem;
                    color: var(--vera-text-muted);
                    margin-top: 4px;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    max-width: 180px;
                }
            }
            
            .delete-btn {
                background: transparent;
                border: none;
                color: var(--vera-text-muted);
                cursor: pointer;
                padding: 5px;
                border-radius: 4px;
                z-index: 1;
                opacity: 0.7;
                transition: all 0.2s ease;
                
                &:hover {
                    color: var(--vera-danger);
                    background-color: var(--vera-error-10);
                    opacity: 1;
                }
            }
            
            &:hover {
                background-color: var(--vera-accent-faint);
                box-shadow: inset 0 0 0 1px var(--vera-accent-faint);
                
                &::before {
                    width: 3px;
                }
            }
            
            &.selected {
                background-color: var(--vera-accent-soft);
                box-shadow: inset 0 0 0 1px var(--vera-accent);
                
                &::before {
                    width: 3px;
                }
                
                .connection-url {
                    color: var(--primary-color-text);
                }
            }
        }
        
        .add-connection {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 12px;
        background-color: var(--vera-accent-faint);
        border: 1px dashed var(--vera-accent-soft);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-top: 4px;
            
            .add-icon {
                color: var(--vera-accent);
                opacity: 0.8;
                transition: all 0.2s ease;
            }
            
            span {
                font-size: 0.875rem;
                color: var(--vera-text-muted);
            }
            
            &:hover {
                background-color: var(--vera-accent-soft);
                border-color: var(--vera-accent);
                box-shadow: inset 0 0 0 1px var(--vera-accent);
                
                .add-icon {
                    opacity: 1;
                }
                
                span {
                    color: var(--vera-text-muted);
                }
            }
        }
    }
}

    .close-btn {
        align-self: flex-end;
        padding: 10px;
        padding-bottom: 0px;
        border: none;
        border-bottom: 1px solid var(--vera-glass-border);
        color: var(--vera-text);
        cursor: pointer;
        width: 100%;
        height: 50px;
        background-color: var(--vera-glass-bg);
        font-size: 1.125rem;
        outline: none;
        letter-spacing: 1px;

        &:hover {
            background-color: var(--vera-panel-alt);
            box-shadow: 0 4px 8px rgba(var(--vera-shadow-rgb), 0.2);
        }

        &:active {
            transform: translateY(1px);
        }
    }

    .flex-container {
        align-items: center;
        gap: 10px;
        width: 100%;

        .slider-container {
            flex-grow: 1;
            display: flex;
            align-items: center;
            justify-content: space-between;

            input[type='range'] {
                -webkit-appearance: none;
                flex-grow: 1;
                height: 5px;
                background: var(--vera-panel-alt);
                outline: none;
                margin-left: 10px;
                margin-right: 10px;

                &::-webkit-slider-thumb {
                    -webkit-appearance: none;
                    width: 25px;
                    height: 25px;
                    border-radius: 50%;
                    background: var(--vera-accent);
                    cursor: pointer;
                }

                background: var(--vera-accent);
                cursor: pointer;
            }
        }
    }
}

.settings-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px;
    text-align: center;
    font-size: 1.5rem;
    font-weight: bold;
    color: var(--vera-text);
    text-shadow: 2px 2px 4px rgba(var(--vera-shadow-rgb), 0.5);
    border-bottom: 1px solid var(--vera-glass-border);
    margin-bottom: 20px;
    background: var(--vera-glass-strong);
    backdrop-filter: blur(18px);

    h2 {
        margin: 0;
    }

    .close-icon {
        background: none;
        border: none;
        color: var(--vera-text);
        font-size: 1.5rem;
        cursor: pointer;
        transition: color 0.15s ease;

        &:hover {
            color: var(--vera-danger);
        }
    }

    .reload-icon {
        cursor: pointer;
        transition: transform 0.15s ease;

        &:hover {
            transform: rotate(360deg);
        }
    }
}

// ============================================
// Premium Panel Layout System
// ============================================

.settings-container {
    display: flex;
    height: 98vh;
    position: relative;

    @media (max-width: 600px) {
        height: 100vh;
        flex-direction: column;
        overflow-x: hidden;
    }
}

// ============================================
// Left Navigation Panel - Premium Glass Card
// ============================================

.left-panel {
    position: relative;
    min-width: 260px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    height: 70vh;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--vera-accent-soft) transparent;

    // Premium glass surface
    background: var(--vera-dialog-content-bg);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);

    // Premium border treatment
    border-right: 1px solid var(--vera-accent-15);
    box-shadow:
        inset -1px 0 0 rgba(var(--vera-contrast-rgb), 0.03),
        4px 0 30px rgba(var(--vera-shadow-rgb), 0.2);

    // Entry animation
    animation: panelSlideIn calc(0.4s / var(--vera-anim-speed, 1)) ease-out backwards;

    // Custom scrollbar
    &::-webkit-scrollbar {
        width: 4px;
    }
    &::-webkit-scrollbar-track {
        background: transparent;
    }
    &::-webkit-scrollbar-thumb {
        background: var(--vera-accent-soft);
        border-radius: 2px;
        &:hover {
            background: var(--vera-accent);
        }
    }

    @media (max-width: 600px) {
        max-width: 30vw;
        min-width: 30vw;
        padding: 15px 8px;
        font-size: 0.75rem;
        height: 92vh;
    }

    // Premium title with gradient
    h3 {
        margin-bottom: 20px;
        font-size: 0.9375rem;
        font-weight: 700;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        background: linear-gradient(135deg, var(--vera-text) 0%, var(--vera-accent) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        position: relative;
        padding-bottom: 12px;

        // Animated underline
        &::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 0;
            width: 60px;
            height: 2px;
            background: linear-gradient(90deg, var(--vera-accent), transparent);
            animation: lineGlow calc(3s / var(--vera-anim-speed, 1)) ease-in-out infinite;
        }
    }

    ul {
        list-style-type: none;
        padding: 0;

        li {
            padding: 12px 14px;
            cursor: pointer;
            color: var(--vera-text);
            border-radius: 10px;
            margin-bottom: 6px;
            border: 1px solid transparent;
            transition: all 0.25s ease;
            position: relative;
            overflow: hidden;

            // Shimmer effect on hover
            &::before {
                content: '';
                position: absolute;
                top: 0;
                left: -100%;
                width: 100%;
                height: 100%;
                background: linear-gradient(90deg, transparent, rgba(var(--vera-contrast-rgb), 0.05), transparent);
                transition: left 0.4s ease;
            }

            &:hover {
                background: var(--vera-accent-08);
                border-color: var(--vera-accent-20);
                transform: translateX(4px);
                box-shadow: 0 4px 15px rgba(var(--vera-shadow-rgb), 0.15);

                &::before {
                    left: 100%;
                }
            }

            &.selected {
                background: linear-gradient(135deg, var(--vera-accent-15) 0%, var(--vera-accent-08) 100%);
                border-color: var(--vera-accent);
                border-left: 3px solid var(--vera-accent);
                box-shadow:
                    0 0 20px var(--vera-accent-15),
                    inset 0 0 20px var(--vera-accent-05);

                .menu-icon {
                    color: var(--vera-accent);
                    filter: drop-shadow(0 0 4px var(--vera-accent-soft));
                }
            }
        }

        .sub-item {
            padding-left: 12px;
            margin-top: 4px;

            li {
                background: var(--vera-accent-05);
                border: 1px solid var(--vera-accent-10);
                padding: 10px 12px;
                font-size: 0.8125rem;

                &:hover,
                &.selected {
                    background: var(--vera-accent-12);
                    border-color: var(--vera-accent-soft);
                }
            }
        }
    }

    .close-btn-wrapper {
        margin-top: auto;
    }

    .close-btn {
        align-self: flex-end;
        padding: 12px;
        border: 1px solid var(--vera-glass-border);
        border-radius: 10px;
        color: var(--vera-text);
        cursor: pointer;
        width: 100%;
        background: var(--vera-accent-05);
        font-size: 0.875rem;
        letter-spacing: 0.5px;
        transition: all 0.25s ease;

        &:hover {
            background: var(--vera-accent-10);
            border-color: var(--vera-accent-soft);
            box-shadow: 0 4px 15px rgba(var(--vera-shadow-rgb), 0.2);
            transform: translateY(-2px);
        }

        &:active {
            transform: translateY(0);
        }
    }
}

// ============================================
// Right Content Panel - Premium Surface
// ============================================

.right-panel {
    flex-grow: 1;
    padding: 24px;
    overflow-y: auto;
    overflow-x: hidden;
    max-height: 70vh;
    scrollbar-width: thin;
    scrollbar-color: var(--vera-accent-soft) transparent;

    // Premium gradient background
    background: var(--vera-dialog-content-bg);

    // Custom scrollbar
    &::-webkit-scrollbar {
        width: 6px;
    }
    &::-webkit-scrollbar-track {
        background: rgba(var(--vera-shadow-rgb), 0.1);
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
        padding: 15px;
        font-size: 0.875rem;
        width: 100%;
        height: auto;
        min-height: calc(100vh - 60px);
        padding-bottom: 100px;
    }

    // Section titles with premium treatment
    h3 {
        margin-bottom: 20px;
        font-size: 0.875rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        color: var(--vera-text-muted);
        position: relative;
        padding-left: 12px;

        &::before {
            content: '';
            position: absolute;
            left: 0;
            top: 50%;
            transform: translateY(-50%);
            width: 3px;
            height: 16px;
            background: var(--vera-accent);
            border-radius: 2px;
            box-shadow: 0 0 8px var(--vera-accent-soft);
        }

        @media (max-width: 600px) {
            font-size: 1.1em;
        }
    }

    .control-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 20px;

        @media (max-width: 600px) {
            grid-template-columns: 1fr;
            gap: 15px;
        }
    }

    .slider-container {
        display: flex;
        justify-content: space-between;
        align-items: center;
        width: 100%;

        @media (max-width: 600px) {
            margin-bottom: 10px;
        }

        input[type='range'] {
            -webkit-appearance: none;
            flex-grow: 1;
            height: 6px;
            background: var(--vera-accent-15);
            border-radius: 3px;
            outline: none;
            margin-left: 10px;
            margin-right: 10px;

            &::-webkit-slider-thumb {
                -webkit-appearance: none;
                width: 18px;
                height: 18px;
                border-radius: 50%;
                background: var(--vera-accent);
                cursor: pointer;
                box-shadow: 0 0 10px var(--vera-accent-soft);
                transition: all 0.2s ease;

                &:hover {
                    transform: scale(1.1);
                    box-shadow: 0 0 15px var(--vera-accent);
                }

                @media (max-width: 600px) {
                    width: 24px;
                    height: 24px;
                }
            }

            background: var(--vera-accent);
            cursor: pointer;
            
            @media (max-width: 600px) {
                height: 18px;
            }
        }
    }
}

.bottom-panel {
    background: transparent;
}

.floating-button {
    position: fixed;
    bottom: 20px;
    left: 20px;
    background-color: var(--vera-accent);
    color: var(--primary-color-text);
    border: none;
    border-radius: 50%;
    width: 50px;
    height: 50px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 4px 8px rgba(var(--vera-shadow-rgb), 0.2);
    transition: all 0.2s ease;
    z-index: 5;

    @media (max-width: 600px) {
        bottom: 30px;
        left: 20px;
        width: 60px;
        height: 60px;
        background-color: var(--vera-accent);
        box-shadow: 0 4px 12px rgba(var(--vera-shadow-rgb), 0.4);
        border: 2px solid rgba(var(--vera-contrast-rgb), 0.1);
    }

    &::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: radial-gradient(circle at center, rgba(var(--vera-contrast-rgb), 0.1) 0%, transparent 70%);
        border-radius: 50%;
        opacity: 0;
        transition: opacity 0.3s ease;
    }

    &:hover {
        background-color: var(--vera-accent-strong);
        transform: translateY(-3px);
        box-shadow: 0 6px 15px rgba(var(--vera-shadow-rgb), 0.3);
        
        &::before {
            opacity: 1;
        }
    }

    &:active {
        transform: translateY(0) scale(0.95);
        box-shadow: 0 2px 8px rgba(var(--vera-shadow-rgb), 0.3);
    }
    
    svg {
        filter: drop-shadow(0 1px 2px rgba(var(--vera-shadow-rgb), 0.3));
        transition: transform 0.2s ease;
        
        @media (max-width: 600px) {
            width: 28px;
            height: 28px;
        }
    }
    
    &:hover svg {
        transform: scale(1.1);
    }
}

/* GitHub section styles */
.github-section {
    margin: 20px 0;

    .github-link {
        text-decoration: none;
        color: inherit;
        display: block;
    }

    .github-content {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 16px;
        background-color: var(--vera-success-10);
        border-radius: 8px;
        transition: all 0.2s ease;

        &:hover {
            background-color: var(--vera-accent-soft);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(var(--vera-shadow-rgb), 0.1);
        }

        .github-icon {
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--vera-accent);
            background-color: var(--vera-accent-faint);
            width: 45px;
            height: 45px;
            border-radius: 50%;
        }

        .github-info {
            h4 {
                margin: 0 0 5px 0;
                font-size: 1rem;
                font-weight: 600;
            }

            p {
                margin: 0;
                font-size: 0.875rem;
                color: var(--vera-text-muted);
            }
        }
    }
}

// ============================================
// VERA Settings Dialog - 2030 Premium Aesthetic
// Matching ToolsDrawer/SwarmDrawer design language
// ============================================

$secondary-accent-rgb: var(--vera-secondary-rgb);
$tertiary-accent-rgb: var(--vera-success-rgb);

// ============================================
// Background Layer System
// ============================================

.bg-layer {
    position: absolute;
    inset: 0;
    pointer-events: none;
    overflow: hidden;
}

// Layer 1: Hexagonal Grid Pattern (SVG-based like ToolsDrawer circuits)
.bg-hexgrid {
    z-index: 1;
    opacity: 0.4;

    .hexgrid-svg {
        width: 100%;
        height: 100%;
    }

    .hex-path {
        stroke: var(--vera-accent-soft);
        opacity: 0.3;
    }

    .hex-connection {
        stroke: var(--vera-accent);
        stroke-width: 1;
        stroke-dasharray: 60;
        stroke-dashoffset: 60;
        opacity: 0.4;
        animation: hexTrace calc(6s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    .hex-node {
        fill: var(--vera-accent);
        filter: drop-shadow(0 0 4px var(--vera-accent));
        animation: hexNodePulse calc(3s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }
}

// Layer 2: Radial Glow Background
.bg-radial-glow {
    z-index: 2;
    background:
        radial-gradient(ellipse at 15% 20%, var(--vera-accent-soft) 0%, transparent 50%),
        radial-gradient(ellipse at 85% 80%, rgba($secondary-accent-rgb, 0.15) 0%, transparent 45%),
        radial-gradient(ellipse at 50% 50%, rgba($tertiary-accent-rgb, 0.05) 0%, transparent 60%);
    animation: radialDrift calc(20s / var(--vera-anim-speed, 1)) ease-in-out infinite;
}

// Layer 3: Data Stream Particles
.bg-data-streams {
    z-index: 3;

    .data-stream-particle {
        position: absolute;
        width: 2px;
        height: 20px;
        background: linear-gradient(180deg, var(--vera-accent), transparent);
        border-radius: 2px;
        left: var(--x-pos, 50%);
        top: -30px;
        opacity: 0;
        animation: dataStreamFall calc(5s / var(--vera-anim-speed, 1)) linear infinite;
        animation-delay: var(--delay, 0s);
    }
}

// Layer 4: Ambient Glow Orbs
.bg-glow-orbs {
    z-index: 4;

    .glow-orb {
        position: absolute;
        border-radius: 50%;
        filter: blur(80px);

        &.glow-orb-1 {
            width: 300px;
            height: 300px;
            top: -50px;
            right: -50px;
            background: radial-gradient(circle, var(--vera-accent-soft) 0%, transparent 70%);
            opacity: 0.35;
            animation: orbFloat calc(8s / var(--vera-anim-speed, 1)) ease-in-out infinite;
        }

        &.glow-orb-2 {
            width: 200px;
            height: 200px;
            bottom: 10%;
            left: -30px;
            background: radial-gradient(circle, rgba($secondary-accent-rgb, 0.4) 0%, transparent 70%);
            opacity: 0.3;
            animation: orbFloat calc(10s / var(--vera-anim-speed, 1)) ease-in-out infinite 3s;
        }

        &.glow-orb-3 {
            width: 150px;
            height: 150px;
            top: 40%;
            right: 20%;
            background: radial-gradient(circle, rgba($tertiary-accent-rgb, 0.25) 0%, transparent 70%);
            opacity: 0.25;
            animation: orbFloat calc(12s / var(--vera-anim-speed, 1)) ease-in-out infinite 6s;
        }
    }
}

// ============================================
// Premium Border System
// ============================================

.premium-border {
    position: absolute;
    pointer-events: none;
    z-index: 100;

    &.premium-border-top {
        top: 0;
        left: 0;
        right: 0;
        height: 2px;
        background: linear-gradient(
            90deg,
            transparent 0%,
            var(--vera-accent-soft) 10%,
            var(--vera-accent) 50%,
            var(--vera-accent-soft) 90%,
            transparent 100%
        );
        box-shadow:
            0 0 20px var(--vera-accent-soft),
            0 2px 30px var(--vera-accent-30);

        .border-pulse {
            position: absolute;
            top: 0;
            left: -150px;
            width: 150px;
            height: 2px;
            background: linear-gradient(90deg, transparent, rgba(var(--vera-contrast-rgb),0.8), var(--vera-accent), transparent);
            animation: borderSweep calc(4s / var(--vera-anim-speed, 1)) linear infinite;
        }
    }

    &.premium-border-bottom {
        bottom: 0;
        left: 0;
        right: 0;
        height: 2px;
        background: linear-gradient(
            90deg,
            transparent 0%,
            rgba($secondary-accent-rgb, 0.5) 15%,
            rgba($secondary-accent-rgb, 1) 50%,
            rgba($secondary-accent-rgb, 0.5) 85%,
            transparent 100%
        );
        box-shadow:
            0 0 20px rgba($secondary-accent-rgb, 0.4),
            0 -2px 30px rgba($secondary-accent-rgb, 0.2);
        animation: borderGlow calc(4s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    &.premium-border-left {
        top: 60px;
        bottom: 60px;
        left: 0;
        width: 2px;
        background: linear-gradient(
            180deg,
            transparent 0%,
            var(--vera-accent-soft) 20%,
            var(--vera-accent) 50%,
            var(--vera-accent-soft) 80%,
            transparent 100%
        );
        box-shadow: 2px 0 20px var(--vera-accent-soft);
        opacity: 0.6;
        animation: verticalGlow calc(5s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    &.premium-border-right {
        top: 60px;
        bottom: 60px;
        right: 0;
        width: 2px;
        background: linear-gradient(
            180deg,
            transparent 0%,
            rgba($secondary-accent-rgb, 0.4) 20%,
            rgba($secondary-accent-rgb, 0.7) 50%,
            rgba($secondary-accent-rgb, 0.4) 80%,
            transparent 100%
        );
        box-shadow: -2px 0 20px rgba($secondary-accent-rgb, 0.3);
        opacity: 0.5;
        animation: verticalGlow calc(5s / var(--vera-anim-speed, 1)) ease-in-out infinite 2s;
    }
}

// ============================================
// Premium Keyframe Animations
// ============================================

@keyframes hexTrace {
    0% {
        stroke-dashoffset: 60;
        opacity: 0.2;
    }
    50% {
        stroke-dashoffset: 0;
        opacity: 0.6;
    }
    100% {
        stroke-dashoffset: -60;
        opacity: 0.2;
    }
}

@keyframes hexNodePulse {
    0%, 100% {
        r: 3;
        filter: drop-shadow(0 0 3px var(--vera-accent-soft));
    }
    50% {
        r: 4;
        filter: drop-shadow(0 0 8px var(--vera-accent));
    }
}

@keyframes radialDrift {
    0%, 100% {
        opacity: 0.8;
        transform: scale(1) translate(0, 0);
    }
    33% {
        opacity: 1;
        transform: scale(1.05) translate(10px, -10px);
    }
    66% {
        opacity: 0.9;
        transform: scale(0.98) translate(-5px, 5px);
    }
}

@keyframes dataStreamFall {
    0% {
        top: -30px;
        opacity: 0;
    }
    10% {
        opacity: 0.7;
    }
    90% {
        opacity: 0.5;
    }
    100% {
        top: 100%;
        opacity: 0;
    }
}

@keyframes orbFloat {
    0%, 100% {
        transform: translate(0, 0) scale(1);
        opacity: 0.3;
    }
    25% {
        transform: translate(15px, -10px) scale(1.05);
        opacity: 0.4;
    }
    50% {
        transform: translate(-10px, 15px) scale(0.95);
        opacity: 0.35;
    }
    75% {
        transform: translate(-15px, -5px) scale(1.02);
        opacity: 0.38;
    }
}

@keyframes borderSweep {
    0% {
        left: -150px;
        opacity: 0;
    }
    10% {
        opacity: 1;
    }
    90% {
        opacity: 1;
    }
    100% {
        left: 100%;
        opacity: 0;
    }
}

@keyframes borderGlow {
    0%, 100% {
        opacity: 0.5;
        box-shadow: 0 0 15px rgba($secondary-accent-rgb, 0.3);
    }
    50% {
        opacity: 0.8;
        box-shadow: 0 0 25px rgba($secondary-accent-rgb, 0.5);
    }
}

@keyframes verticalGlow {
    0%, 100% {
        opacity: 0.4;
    }
    50% {
        opacity: 0.7;
    }
}

@keyframes panelSlideIn {
    0% {
        opacity: 0;
        transform: translateX(-20px);
    }
    100% {
        opacity: 1;
        transform: translateX(0);
    }
}

@keyframes lineGlow {
    0%, 100% {
        opacity: 0.6;
        width: 60px;
    }
    50% {
        opacity: 1;
        width: 80px;
    }
}

@keyframes cardEntry {
    0% {
        opacity: 0;
        transform: translateY(10px);
    }
    100% {
        opacity: 1;
        transform: translateY(0);
    }
}

// ============================================
// Reduced Motion & Lite Mode Support
// ============================================

@media (prefers-reduced-motion: reduce) {
    .bg-layer,
    .premium-border,
    .hex-connection,
    .hex-node,
    .data-stream-particle,
    .glow-orb,
    .border-pulse {
        animation: none !important;
    }

    .bg-hexgrid { opacity: 0.2; }
    .bg-radial-glow { opacity: 0.5; }
    .glow-orb { opacity: 0.2; }
    .premium-border { opacity: 0.6; }
}
</style>
