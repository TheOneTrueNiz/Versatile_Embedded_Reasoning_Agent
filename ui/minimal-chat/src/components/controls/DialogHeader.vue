<!-- DialogHeader.vue -->
<template>
    <div class="dialog-header">
        <div class="header-content">
            <component :is="icon" v-if="icon" :size="iconSize" class="header-icon" />
            <h2 :id="headerId">{{ title }}</h2>
        </div>
        <button class="close-icon" @click="$emit('close')">
            <X :size="iconSize" />
        </button>
        <ToolTip :targetId="headerId">{{ tooltipText }}</ToolTip>
    </div>
</template>

<script setup>
import { X } from 'lucide-vue-next';
import ToolTip from '@/components/controls/ToolTip.vue';

defineProps({
    title: {
        type: String,
        required: true,
    },
    tooltipText: {
        type: String,
        default: '',
    },
    headerId: {
        type: String,
        required: true,
    },
    icon: {
        type: [Object, Function], // Accepting a component
        default: null,
    },
    iconSize: {
        type: [Number, String],
        default: 24,
    },
});

defineEmits(['close']);
</script>

<style lang="scss" scoped>
.tooltip-container {
    font-size: 1rem;
    width: fit-content;
}

.dialog-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px;
    text-align: center;
    background: var(--vera-header-bg);
    font-size: 1.5rem;
    font-weight: bold;
    color: var(--vera-text);
    text-shadow: 2px 2px 4px rgba(var(--vera-shadow-rgb), 0.5);
    border-bottom: 1px solid var(--vera-glass-border);
    margin-bottom: 20px;
    position: sticky;
    top: 0;
    z-index: 5;
    backdrop-filter: blur(var(--vera-header-blur));

    @media (max-width: 600px) {
        padding: 10px;
        font-size: 1.25rem;
        border-bottom: 1px solid var(--vera-glass-border);
        margin-bottom: 15px;
    }

    .header-content {
        display: flex;
        align-items: center;

        .header-icon {
            margin-right: 8px;
        }

        h2 {
            margin: 0;
            
            @media (max-width: 600px) {
                font-size: 1.3rem;
            }
        }
    }

    .close-icon {
        background: none;
        border: none;
        color: var(--vera-text);
        font-size: 1.5rem;
        cursor: pointer;
        transition: color 0.15s ease;
        padding: 8px;
        
        @media (max-width: 600px) {
            padding: 10px;
        }

        &:hover {
            color: var(--vera-danger);
        }
    }
}
</style>
