<template>
    <div class="accessibility-config-section">
        <div class="config-section show">
            <div class="section-header static">
                <h3>
                    <Eye size="20" class="section-icon" />
                    Visual Accessibility
                </h3>
            </div>
            <div class="accessibility-content">
                <div class="setting-row">
                    <h4>Reduced Motion</h4>
                    <SelectButton
                        v-model="a11yReducedMotion"
                        :options="reducedMotionOptions"
                        optionLabel="label"
                        optionValue="value"
                        class="setting-selector"
                    />
                    <p class="setting-hint">Minimizes animations for users sensitive to motion.</p>
                </div>
                <div class="setting-row">
                    <h4>High Contrast</h4>
                    <SliderCheckbox inputId="a11y-high-contrast" labelText="Increase text and border contrast"
                        v-model="a11yHighContrast" />
                    <p class="setting-hint">Improves visibility for users with low vision.</p>
                </div>
                <div class="setting-row">
                    <h4>Large Text</h4>
                    <SliderCheckbox inputId="a11y-large-text" labelText="Increase base font size by 25%"
                        v-model="a11yLargeText" />
                    <p class="setting-hint">Makes text larger without changing zoom level.</p>
                </div>
                <div class="setting-row">
                    <h4>Dyslexia-Friendly Font</h4>
                    <SliderCheckbox inputId="a11y-dyslexia-font" labelText="Use Atkinson Hyperlegible font"
                        v-model="a11yDyslexiaFont" />
                    <p class="setting-hint">Highly legible font designed for low-vision readers.</p>
                </div>
                <div class="setting-row">
                    <h4>Line Spacing</h4>
                    <SelectButton
                        v-model="a11yLineSpacing"
                        :options="lineSpacingOptions"
                        optionLabel="label"
                        optionValue="value"
                        class="setting-selector"
                    />
                    <p class="setting-hint">Adjust space between lines for better readability.</p>
                </div>
                <div class="setting-row">
                    <h4>Letter Spacing</h4>
                    <SelectButton
                        v-model="a11yLetterSpacing"
                        :options="letterSpacingOptions"
                        optionLabel="label"
                        optionValue="value"
                        class="setting-selector"
                    />
                    <p class="setting-hint">Adjust space between letters for better readability.</p>
                </div>
                <div class="setting-row">
                    <h4>Focus Indicators</h4>
                    <SelectButton
                        v-model="a11yFocusHighlight"
                        :options="focusHighlightOptions"
                        optionLabel="label"
                        optionValue="value"
                        class="setting-selector"
                    />
                    <p class="setting-hint">Controls visibility of keyboard focus outlines.</p>
                </div>
                <div class="setting-row">
                    <h4>Reset Visual Settings</h4>
                    <button class="reset-button" @click="resetVisualAccessibility">
                        <RotateCcw size="16" />
                        <span>Reset All</span>
                    </button>
                </div>
            </div>
        </div>

        <div class="config-section show">
            <div class="section-header static">
                <h3>
                    <Volume2 size="20" class="section-icon" />
                    Audio & Interaction
                </h3>
            </div>
            <div class="accessibility-content">
                <div class="setting-row">
                    <h4>Screen Reader Announcements</h4>
                    <SliderCheckbox inputId="a11y-screen-reader" labelText="Enable ARIA live announcements"
                        v-model="a11yScreenReaderAnnounce" />
                    <p class="setting-hint">Announces new messages and status changes to screen readers.</p>
                </div>
                <div class="setting-row">
                    <h4>Message Verbosity</h4>
                    <SelectButton
                        v-model="a11yMessageVerbosity"
                        :options="messageVerbosityOptions"
                        optionLabel="label"
                        optionValue="value"
                        class="setting-selector"
                    />
                    <p class="setting-hint">How much detail screen readers announce for messages.</p>
                </div>
                <div class="setting-row">
                    <h4>Keyboard Shortcuts</h4>
                    <SliderCheckbox inputId="a11y-keyboard" labelText="Enable keyboard navigation shortcuts"
                        v-model="a11yKeyboardShortcuts" />
                    <p class="setting-hint">Quick actions via keyboard (Ctrl+Enter to send, etc.).</p>
                </div>
                <div class="setting-row">
                    <h4>Sound Effects</h4>
                    <SliderCheckbox inputId="a11y-sound-effects" labelText="Play UI sound effects"
                        v-model="a11ySoundEffects" />
                    <p class="setting-hint">Audio feedback for actions like sending messages.</p>
                </div>
                <div class="setting-row">
                    <h4>Auto-Play Media</h4>
                    <SliderCheckbox inputId="a11y-autoplay" labelText="Auto-play audio/video in messages"
                        v-model="a11yAutoPlayMedia" />
                    <p class="setting-hint">Disable for reduced distraction or data saving.</p>
                </div>
                <div class="setting-row">
                    <h4>Reset Audio Settings</h4>
                    <button class="reset-button" @click="resetAudioAccessibility">
                        <RotateCcw size="16" />
                        <span>Reset All</span>
                    </button>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup>
import SliderCheckbox from '../controls/SliderCheckbox.vue';
import SelectButton from 'primevue/selectbutton';
import { Eye, Volume2, RotateCcw } from 'lucide-vue-next';
import {
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
} from '@/libs/state-management/state';

// Options for select buttons
const reducedMotionOptions = [
    { label: 'System', value: 'system' },
    { label: 'On', value: 'on' },
    { label: 'Off', value: 'off' }
];

const lineSpacingOptions = [
    { label: 'Tight', value: 'tight' },
    { label: 'Normal', value: 'normal' },
    { label: 'Relaxed', value: 'relaxed' },
    { label: 'Loose', value: 'loose' }
];

const letterSpacingOptions = [
    { label: 'Tight', value: 'tight' },
    { label: 'Normal', value: 'normal' },
    { label: 'Relaxed', value: 'relaxed' },
    { label: 'Loose', value: 'loose' }
];

const focusHighlightOptions = [
    { label: 'Subtle', value: 'subtle' },
    { label: 'Normal', value: 'normal' },
    { label: 'Strong', value: 'strong' },
    { label: 'High', value: 'high' }
];

const messageVerbosityOptions = [
    { label: 'Minimal', value: 'minimal' },
    { label: 'Normal', value: 'normal' },
    { label: 'Detailed', value: 'detailed' }
];

// Reset functions
const resetVisualAccessibility = () => {
    a11yReducedMotion.value = 'system';
    a11yHighContrast.value = false;
    a11yLargeText.value = false;
    a11yDyslexiaFont.value = false;
    a11yLineSpacing.value = 'normal';
    a11yLetterSpacing.value = 'normal';
    a11yFocusHighlight.value = 'normal';
};

const resetAudioAccessibility = () => {
    a11yScreenReaderAnnounce.value = true;
    a11yMessageVerbosity.value = 'normal';
    a11yKeyboardShortcuts.value = true;
    a11ySoundEffects.value = true;
    a11yAutoPlayMedia.value = true;
};
</script>

<style lang="scss" scoped>
.accessibility-config-section {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 20px;
}

.config-section {
    background: var(--vera-drawer-bg);
    border: 1px solid var(--vera-accent-12);
    border-radius: 16px;
    backdrop-filter: blur(16px);
    overflow: hidden;
    transition: all 0.3s ease;

    &:hover {
        border-color: var(--vera-accent-25);
        box-shadow: 0 0 30px var(--vera-accent-08);
    }
}

.section-header {
    display: flex;
    align-items: center;
    padding: 16px 20px;
    background: var(--vera-black-40);
    border-bottom: 1px solid var(--vera-border);

    h3 {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 0.875rem;
        font-weight: 600;
        color: var(--vera-text);
        margin: 0;

        .section-icon {
            color: var(--vera-accent);
            opacity: 0.9;
        }
    }
}

.accessibility-content {
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 20px;
}

.setting-row {
    display: flex;
    flex-direction: column;
    gap: 8px;

    h4 {
        font-size: 0.8125rem;
        font-weight: 600;
        color: var(--vera-text);
        margin: 0;
    }
}

.setting-hint {
    font-size: 0.6875rem;
    color: var(--vera-text-muted);
    margin: 4px 0 0 0;
    line-height: 1.4;
}

// Premium SelectButton styling
.setting-selector {
    :deep(.p-selectbutton) {
        display: inline-flex;
        gap: 2px;
        padding: 3px;
        background: var(--vera-black-70);
        border: 1px solid var(--vera-border);
        border-radius: 10px;
        backdrop-filter: blur(8px);

        .p-button {
            padding: 8px 12px;
            font-size: 0.75rem;
            font-weight: 500;
            background: transparent;
            border: none;
            color: var(--vera-text-muted);
            border-radius: 8px;
            transition: all 0.25s ease;

            &:hover:not(.p-highlight) {
                background: var(--vera-accent-08);
                color: var(--vera-text);
            }

            &.p-highlight {
                background: linear-gradient(135deg, var(--vera-accent-25), var(--vera-accent-10));
                color: var(--vera-text);
                box-shadow: 0 0 16px var(--vera-accent-20);
            }
        }
    }
}

// Premium reset button
.reset-button {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    background: var(--vera-black-60);
    border: 1px solid var(--vera-accent-15);
    border-radius: 8px;
    color: var(--vera-text-muted);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.3s ease;
    backdrop-filter: blur(8px);
    width: fit-content;

    svg {
        opacity: 0.7;
        transition: all 0.3s ease;
    }

    &:hover {
        border-color: var(--vera-accent-35);
        color: var(--vera-text);
        box-shadow: 0 0 16px var(--vera-accent-12);

        svg {
            opacity: 1;
            color: var(--vera-accent);
        }
    }
}
</style>
