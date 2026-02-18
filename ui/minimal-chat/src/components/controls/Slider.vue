<!-- Slider.vue -->
<template>
    <div class="flex-container" :class="{ 'is-disabled': disabled }">
        <div class="center-text">{{ label }}: ({{ modelValue }})</div>
        <div class="slider-container">
            <span>{{ minLabel }}</span>
            <input type="range" :min="min" :max="max" :step="step" :value="modelValue" :disabled="disabled"
                @input="updateValue($event.target.value)" />
            <span>{{ maxLabel }}</span>
        </div>
    </div>
</template>

<script setup>
import { defineProps, defineEmits } from 'vue';

const props = defineProps({
    label: {
        type: String,
        required: true
    },
    modelValue: {
        type: [Number, String],
        required: true
    },
    min: {
        type: [Number, String],
        default: 0
    },
    max: {
        type: [Number, String],
        default: 100
    },
    step: {
        type: [Number, String],
        default: 1
    },
    minLabel: {
        type: String,
        default: 'Min'
    },
    maxLabel: {
        type: String,
        default: 'Max'
    },
    disabled: {
        type: Boolean,
        default: false
    }
});

const emit = defineEmits(['update:modelValue']);

const updateValue = (value) => {
    if (props.disabled) {
        return;
    }
    emit('update:modelValue', value);
};
</script>

<style scoped lang="scss">
.flex-container {
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 12px;

    .center-text {
        text-align: center;
        bottom: 10px;
        position: relative;
    }

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

.flex-container.is-disabled {
    opacity: 0.55;

    .slider-container input[type='range'] {
        cursor: not-allowed;
    }

    .slider-container input[type='range']::-webkit-slider-thumb {
        cursor: not-allowed;
    }
}
</style>
