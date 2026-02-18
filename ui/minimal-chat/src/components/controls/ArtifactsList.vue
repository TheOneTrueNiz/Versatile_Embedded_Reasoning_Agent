<script setup>
import { computed } from 'vue';
import { FileCode, Plus } from 'lucide-vue-next';
import ArtifactCard from './ArtifactCard.vue';

const props = defineProps({
  artifacts: {
    type: Array,
    default: () => []
  }
});

const emit = defineEmits(['load-artifact', 'delete-artifact', 'create-artifact']);

const hasArtifacts = computed(() => props.artifacts.length > 0);

function handleLoad(artifact) {
  emit('load-artifact', artifact);
}

function handleDelete(artifact) {
  emit('delete-artifact', artifact);
}

function handleCopy(artifact) {
  // Just emit for tracking/notification purposes
}

function createNew() {
  emit('create-artifact');
}
</script>

<template>
  <div class="artifacts-list" v-if="hasArtifacts">
    <div class="artifacts-header">
      <div class="header-left">
        <FileCode :size="16" />
        <span>Artifacts ({{ artifacts.length }})</span>
      </div>
      <button class="add-btn" @click="createNew" title="Create new artifact">
        <Plus :size="14" />
      </button>
    </div>
    <div class="artifacts-container">
      <ArtifactCard
        v-for="artifact in artifacts"
        :key="artifact.id"
        :artifact="artifact"
        @load="handleLoad"
        @delete="handleDelete"
        @copy="handleCopy"
      />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.artifacts-list {
  margin: 12px 0;
  padding: 12px;
  background: var(--vera-panel-alt);
  border-radius: 10px;
  border: 1px solid var(--vera-border);
}

.artifacts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--vera-border);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--vera-text);

  svg {
    color: var(--vera-accent);
  }
}

.add-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: var(--vera-accent-faint);
  color: var(--vera-accent);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s ease;

  &:hover {
    background: var(--vera-accent);
    color: var(--primary-color-text);
  }
}

.artifacts-container {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
</style>
