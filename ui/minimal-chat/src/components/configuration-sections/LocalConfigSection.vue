<template>
    <div class="local-config-container">
        <!-- Connection Settings Card -->
        <div class="config-card">
            <div class="card-header">
                <NetworkIcon class="header-icon" size="18" />
                <h3>Connection Settings</h3>
                <ToolTip targetId="local-model-endpoint">Updating the endpoint will automatically save a new connection entry</ToolTip>
            </div>
            <div class="card-content">
                <InputField :isSecret="false" labelText="Model Endpoint" inputId="local-model-endpoint" 
                    :value="localModelEndpoint" @update:value="handleUpdate('localModelEndpoint', $event)"
                    :placeholderText="'Enter the VERA or OpenAI-compatible base URL'" />
                    
                <InputField :isSecret="true" labelText="Endpoint API Key" inputId="local-model-key" 
                    :value="localModelKey" @update:value="updateSettingAndFetchModels('localModelKey', $event)"
                    :placeholderText="'Enter the API key if applicable'" />
            </div>
        </div>
        
        <!-- Model Selection Card -->
        <div class="config-card">
            <div class="card-header clickable" @click="isModelSelectorOpen = !isModelSelectorOpen">
                <ServerIcon class="header-icon" size="18" />
                <h3>Available Models</h3>
                <div class="card-actions">
                    <span class="model-name">{{ localModelName || 'No model selected' }}</span>
                    <ChevronDown v-if="isModelSelectorOpen" class="indicator" size="18" />
                    <ChevronRight v-else class="indicator" size="18" />
                </div>
            </div>
            <transition name="slide-fade">
                <div v-show="isModelSelectorOpen" class="card-content">
                    <div class="model-list-container">
                        <Listbox filter id="custom-model-selector" v-model="localModelName" 
                            :options="availableModels" optionLabel="name" optionValue="id" 
                            @change="handleUpdate('localModelName', $event.value)" class="model-listbox" />
                            
                        <div v-if="!availableModels.length" class="empty-models">
                            <ServerOffIcon size="24" />
                            <p>No models available. Enter a valid API endpoint and key.</p>
                        </div>
                    </div>
                    <div class="model-override">
                        <InputField
                            :isSecret="false"
                            labelText="Model ID override"
                            inputId="local-model-override"
                            :value="localModelName"
                            :placeholderText="'Enter a model ID (e.g., grok-4.20-experimental-beta-0304-reasoning or a local OSS model)'"
                            @update:value="updateModelOverride"
                        />
                        <p class="model-hint">
                            Use this to set an open-source/local model ID when your endpoint supports OpenAI format.
                        </p>
                    </div>
                </div>
            </transition>
        </div>
        
        <!-- Parameters Card -->
        <div class="config-card">
            <div class="card-header clickable" @click="isParametersOpen = !isParametersOpen">
                <SlidersIcon class="header-icon" size="18" />
                <h3>Model Parameters</h3>
                <div class="card-actions">
                    <span v-if="isReasoningModel" class="param-badge" title="Reasoning models ignore frequency, presence, and stop. Use temperature/top_p only.">Reasoning model</span>
                    <ChevronDown v-if="isParametersOpen" class="indicator" size="18" />
                    <ChevronRight v-else class="indicator" size="18" />
                </div>
            </div>
            <transition name="slide-fade">
                <div v-show="isParametersOpen" class="card-content">
                    <div v-if="toolCallingEnabled" class="param-callout">
                        <Info class="param-callout-icon" size="14" />
                        Tool calling respects only temperature and top_p; other sampling params are ignored.
                    </div>
                    <div class="parameter-sliders">
                        <Slider label="Temperature" v-model="localSliderValue" :min="0" :max="1" :step="0.01" 
                            minLabel="Serious" maxLabel="Creative" @update:modelValue="updateLocalSliderValue" />
                            
                        <Slider label="Top P" v-model="top_P" :min="0" :max="1" :step="0.01" 
                            minLabel="Lower" maxLabel="Higher" @update:modelValue="updateTopPSliderValue" />

                        <div class="parameter-item">
                            <Slider label="Frequency Penalty" v-model="repetitionPenalty" :min="0" :max="2" :step="0.01"
                                minLabel="Lower" maxLabel="Higher" :disabled="isReasoningModel" @update:modelValue="updateRepetitionSliderValue" />
                            <span v-if="isReasoningModel" class="param-note">Ignored by reasoning models.</span>
                        </div>

                        <div class="parameter-item">
                            <Slider label="Presence Penalty" v-model="presencePenalty" :min="0" :max="2" :step="0.01"
                                minLabel="Lower" maxLabel="Higher" :disabled="isReasoningModel" @update:modelValue="updatePresenceSliderValue" />
                            <span v-if="isReasoningModel" class="param-note">Ignored by reasoning models.</span>
                        </div>
                            
                        <Slider label="Max Tokens" v-model="maxTokens" :min="0" :max="4096" :step="1" 
                            minLabel="Less" maxLabel="More" @update:modelValue="updateMaxTokensSliderValue" />
                    </div>
                </div>
            </transition>
        </div>
    </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import InputField from '../controls/InputField.vue';
import { ChevronDown, ChevronRight, Info, Network as NetworkIcon, Server as ServerIcon, ServerOff as ServerOffIcon, Sliders as SlidersIcon } from 'lucide-vue-next';
import Listbox from 'primevue/listbox';
import Slider from '../controls/Slider.vue';
import { localModelEndpoint, localModelKey, localModelName, maxTokens, localSliderValue, top_P, repetitionPenalty, presencePenalty, availableModels, selectedModel } from '@/libs/state-management/state';
import { handleUpdate, updateLocalSliderValue, updateTopPSliderValue, updateRepetitionSliderValue, updatePresenceSliderValue, customConfigs, selectedCustomConfigIndex, updateMaxTokensSliderValue, fetchAvailableModels } from '@/libs/utils/settings-utils';
import ToolTip from '../controls/ToolTip.vue';


const isModelSelectorOpen = ref(false);
const isParametersOpen = ref(false);
const toolPayload = ref(null);
const isReasoningModel = computed(() => {
    const name = (localModelName.value || '').toLowerCase();
    if (!name) {
        return false;
    }
    if (name.includes('non-reasoning')) {
        return false;
    }
    if (name.includes('reasoning')) {
        return true;
    }
    return name.startsWith('grok-3') || name.startsWith('grok-4');
});

const toolCallingEnabled = computed(() => {
    const payload = toolPayload.value;
    if (!payload) {
        return false;
    }
    const toolMode = (payload.tool_mode || '').toLowerCase();
    if (toolMode && toolMode !== 'none') {
        return true;
    }
    if (payload.tool_count && payload.tool_count > 0) {
        return true;
    }
    return Boolean(payload.router_enabled);
});

async function fetchToolPayload() {
    try {
        const response = await fetch('/api/tools/last_payload');
        if (!response.ok) {
            return;
        }
        const data = await response.json();
        toolPayload.value = data.payload || null;
    } catch (error) {
        toolPayload.value = null;
    }
}

async function updateSettingAndFetchModels(field, value) {
    handleUpdate(field, value)

    await fetchAvailableModels();
}

function ensureModelEntry(modelId) {
    if (!modelId) {
        return;
    }
    const trimmed = modelId.trim();
    if (!trimmed) {
        return;
    }
    const exists = availableModels.value.some((model) => model.id === trimmed);
    if (!exists) {
        availableModels.value = [{ id: trimmed, name: trimmed }, ...availableModels.value];
    }
}

function updateModelOverride(value) {
    const trimmed = (value || '').trim();
    if (!trimmed) {
        return;
    }
    ensureModelEntry(trimmed);
    handleUpdate('localModelName', trimmed);
}

onMounted(fetchToolPayload);

watch(isParametersOpen, (isOpen) => {
    if (isOpen) {
        fetchToolPayload();
    }
});
</script>

<style scoped lang="scss">
// ============================================
// VERA LocalConfigSection Premium Styling
// Premium glass morphism, hover effects, refined controls
// Matches ToolsDrawer/SwarmDrawer aesthetic
// ============================================

// Animations
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

// Main container
.local-config-container {
    display: flex;
    flex-direction: column;
    gap: 18px;

    @media (max-width: 600px) {
        gap: 14px;
    }
}

// ============================================
// Premium Card Styling
// ============================================

.config-card {
    background: var(--vera-drawer-bg);
    backdrop-filter: blur(16px);
    border: 1px solid var(--vera-border);
    border-radius: 14px;
    overflow: hidden;
    position: relative;
    opacity: 0;
    animation: cardSlideIn 0.5s ease forwards;
    transition: all 0.3s ease;

    // Staggered entry animation
    &:nth-of-type(1) { animation-delay: 0.05s; }
    &:nth-of-type(2) { animation-delay: 0.1s; }
    &:nth-of-type(3) { animation-delay: 0.15s; }

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

    .card-header {
        background: linear-gradient(135deg, var(--vera-accent-08) 0%, var(--vera-accent-02) 100%);
        padding: 14px 16px;
        display: flex;
        align-items: center;
        gap: 10px;
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

        &.clickable {
            cursor: pointer;
            transition: all 0.25s ease;

            &:hover {
                background: linear-gradient(135deg, var(--vera-accent-12) 0%, var(--vera-accent-04) 100%);

                &::after {
                    width: 60px;
                }
            }
        }

        h3 {
            margin: 0;
            font-size: 0.875rem;
            font-weight: 600;
            flex-grow: 1;
            background: linear-gradient(135deg, var(--vera-text) 0%, var(--vera-accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;

            @media (max-width: 600px) {
                font-size: 0.8125rem;
            }
        }

        .header-icon {
            color: var(--vera-accent);
            filter: drop-shadow(0 0 4px var(--vera-accent-soft));
            flex-shrink: 0;
        }

        .card-actions {
            display: flex;
            align-items: center;
            gap: 8px;

            .model-name {
                font-size: 0.75rem;
                opacity: 0.7;
                max-width: 140px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                color: var(--vera-text-muted);

                @media (max-width: 600px) {
                    max-width: 90px;
                }
            }

            .indicator {
                color: var(--vera-accent);
                transition: transform 0.2s ease;
            }
        }
    }

    .card-content {
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        background: var(--vera-black-40);

        @media (max-width: 600px) {
            padding: 12px;
        }
    }
}

// ============================================
// Premium Badge
// ============================================

.param-badge {
    font-size: 0.625rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 3px 10px;
    border-radius: 999px;
    background: linear-gradient(135deg, var(--vera-accent-15), var(--vera-accent-05));
    color: var(--vera-text);
    border: 1px solid var(--vera-accent-soft);
    box-shadow: 0 0 8px var(--vera-accent-10);
    animation: badgeGlow 3s ease-in-out infinite;
}

@keyframes badgeGlow {
    0%, 100% { box-shadow: 0 0 8px var(--vera-accent-10); }
    50% { box-shadow: 0 0 14px var(--vera-accent-20); }
}

// ============================================
// Model List Container
// ============================================

.model-list-container {
    margin-top: 4px;

    .model-listbox {
        width: 100%;

        :deep(.p-listbox) {
            background: var(--vera-black-60);
            border: 1px solid var(--vera-border);
            border-radius: 10px;
            width: 100%;
            height: auto;
            max-height: 280px;
            font-size: 0.8125rem;
            transition: all 0.25s ease;

            @media (max-width: 600px) {
                max-height: 220px;
            }

            &:hover {
                border-color: var(--vera-accent-soft);
                box-shadow: 0 0 16px var(--vera-accent-08);
            }

            .p-listbox-header {
                background: var(--vera-accent-04);
                padding: 10px;
                border-bottom: 1px solid var(--vera-border);

                .p-listbox-filter-container {
                    width: 100%;

                    .p-inputtext {
                        background: var(--vera-black-80);
                        border: 1px solid var(--vera-border);
                        border-radius: 8px;
                        padding: 10px 14px;
                        color: var(--vera-text);
                        width: 100%;
                        font-size: 0.8125rem;
                        transition: all 0.2s ease;

                        &:focus {
                            border-color: var(--vera-accent);
                            box-shadow: 0 0 0 3px var(--vera-accent-10);
                        }
                    }

                    .p-listbox-filter-icon {
                        color: var(--vera-accent);
                    }
                }
            }

            .p-listbox-list {
                padding: 8px;

                .p-listbox-item {
                    padding: 10px 12px;
                    color: var(--vera-text);
                    border-radius: 8px;
                    transition: all 0.2s ease;
                    margin-bottom: 4px;
                    position: relative;
                    border-left: 3px solid transparent;

                    &::before {
                        content: '';
                        position: absolute;
                        left: 0;
                        top: 50%;
                        width: 3px;
                        height: 0;
                        background: var(--vera-accent);
                        border-radius: 0 2px 2px 0;
                        transform: translateY(-50%);
                        transition: height 0.2s ease;
                    }

                    &:hover {
                        background: var(--vera-accent-08);

                        &::before {
                            height: 50%;
                        }
                    }

                    &.p-highlight {
                        background: linear-gradient(135deg, var(--vera-accent-15) 0%, var(--vera-accent-05) 100%);
                        color: var(--vera-text);
                        border-left: 3px solid var(--vera-accent);
                        box-shadow: inset 0 0 20px var(--vera-accent-05);
                    }
                }
            }
        }
    }

    .empty-models {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 28px 20px;
        text-align: center;
        color: var(--vera-text-muted);
        background: var(--vera-black-50);
        border-radius: 10px;
        border: 1px dashed var(--vera-border);
        transition: all 0.2s ease;

        svg {
            opacity: 0.5;
            color: var(--vera-accent);
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
}

// ============================================
// Model Override Section
// ============================================

.model-override {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding-top: 12px;
    border-top: 1px solid var(--vera-border);
    margin-top: 4px;
}

.model-hint {
    margin: 0;
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
    line-height: 1.5;
    padding-left: 2px;
}

// ============================================
// Parameter Sliders Section
// ============================================

.parameter-sliders {
    display: flex;
    flex-direction: column;
    gap: 18px;

    @media (max-width: 600px) {
        gap: 20px;
    }
}

.parameter-item {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    background: color-mix(in srgb, var(--vera-panel) 40%, transparent);
    border-radius: 10px;
    border: 1px solid transparent;
    transition: all 0.2s ease;

    &:hover {
        border-color: var(--vera-border);
        background: var(--vera-accent-02);
    }
}

.param-note {
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
    padding-left: 2px;
    font-style: italic;
}

// ============================================
// Parameter Callout
// ============================================

.param-callout {
    margin-bottom: 12px;
    padding: 12px 14px;
    border-radius: 10px;
    border: 1px solid var(--vera-accent-soft);
    background: linear-gradient(135deg, var(--vera-accent-08) 0%, var(--vera-accent-02) 100%);
    color: var(--vera-text);
    font-size: 0.75rem;
    display: flex;
    align-items: center;
    gap: 10px;
    line-height: 1.5;
    animation: calloutFadeIn 0.4s ease;
}

@keyframes calloutFadeIn {
    from {
        opacity: 0;
        transform: translateY(-6px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.param-callout-icon {
    color: var(--vera-accent);
    flex-shrink: 0;
    filter: drop-shadow(0 0 4px var(--vera-accent-soft));
}

// ============================================
// Keyframe Animations
// ============================================

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

// ============================================
// Reduced Motion Support
// ============================================

@media (prefers-reduced-motion: reduce) {
    .config-card,
    .param-badge,
    .param-callout {
        animation: none !important;
    }

    .config-card {
        opacity: 1;
    }

    .slide-fade-enter-active,
    .slide-fade-leave-active {
        transition-duration: 0.01s;
    }
}
</style>
