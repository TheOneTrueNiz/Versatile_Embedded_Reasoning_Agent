<script setup>
import { ref, defineProps, defineEmits } from 'vue';

const props = defineProps({
    inputId: String,
    labelText: String,
    modelValue: Boolean,
    disabled: {
        type: Boolean,
        default: false
    }
});

const componentModelValue = ref(props.modelValue);

const emit = defineEmits(['update:modelValue']);

const handleChange = (event) => {
    if (!props.disabled) {
        emit('update:modelValue', event.target.checked);
    }
};
</script>

<template>
    <div class="control-checkbox" :class="{ disabled: disabled }">
        <label :for="inputId">
            {{ labelText }}:
            &nbsp;
            <ToggleButton :inputId="inputId" v-model="componentModelValue" @change="handleChange" :disabled="disabled" />
        </label>
    </div>
</template>

<style scoped lang="scss">
.control-checkbox {
    display: flex;
    align-items: center;
    width: fit-content;
    transition: opacity 0.2s ease;

    &.disabled {
        opacity: 0.5;
        pointer-events: none;
    }

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
</style>
