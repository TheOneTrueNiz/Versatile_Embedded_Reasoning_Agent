<!-- ContextWindow.vue -->
<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { deleteCurrentConversation } from '@/libs/conversation-management/useConversations';
import { messages, selectedConversation, contextMenuOpened } from '@/libs/state-management/state';
import { showToast } from '@/libs/utils/general-utils';
import Menu from 'primevue/menu';
import { CircleEllipsis } from 'lucide-vue-next';

const menu = ref(null);

function showContextMenu(event) {
    menu.value.toggle(event);
}

function hideContextMenu() {
    contextMenuOpened.value = false;
}

function startNewConversation() {
    selectedConversation.value = null;
    messages.value = [];

    showToast('Conversation Saved');
    hideContextMenu();
}

function deleteCurrentConversationHandler() {
    deleteCurrentConversation();
    hideContextMenu();
}

const items = [
    {
        label: 'New Conversation',
        icon: 'pi pi-plus',
        command: startNewConversation
    },
    {
        label: 'Delete Conversation',
        icon: 'pi pi-trash',
        command: deleteCurrentConversationHandler
    }
];

defineExpose({ showContextMenu, hideContextMenu });

onMounted(() => {

});

onBeforeUnmount(() => {

});
</script>

<template>
    <div class="pi pi-ellipsis-v" @click="showContextMenu" aria-haspopup="true" aria-controls="overlay_menu"
        style="font-size: 1.2rem; color: var(--vera-text-muted);"></div>
    <Menu ref="menu" id="overlay_menu" class="custom-context-menu" :model="items" :popup="true"></Menu>
</template>

<style lang="scss">
.custom-context-menu {
    .p-menu {
        background: color-mix(in srgb, var(--vera-panel) 95%, transparent);
        background-color: color-mix(in srgb, var(--vera-panel) 95%, transparent);
        color: var(--vera-text);
        box-shadow: 0 2px 10px rgba(var(--vera-shadow-rgb), 0.5);
    }

    .p-menuitem {
        padding: 10px 14px;
        transition: background 0.15s, transform 0.15s;

        &:hover {
            background-color: var(--vera-accent-faint);
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(var(--vera-shadow-rgb), 0.2);
        }
    }

    .p-menuitem-text {
        padding-left: 6px;
    }

    .p-menuitem-link {
        color: var(--vera-text);
    }
}
</style>
