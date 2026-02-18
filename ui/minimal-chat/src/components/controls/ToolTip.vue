<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import tippy from 'tippy.js';
import 'tippy.js/animations/shift-away-subtle.css';

const props = defineProps({
  targetId: String,
  customClass: String,
  placement: {
    type: String,
    default: 'auto',
    validator: (value) => ['auto', 'top', 'right', 'bottom', 'left'].includes(value)
  },
  interactive: {
    type: Boolean,
    default: false
  },
  showDelay: {
    type: Number,
    default: 150
  }
});

const tooltipElement = ref(null);
let tippyInstance = null;

const createTooltip = () => {
  const target = document.getElementById(props.targetId);
  if (target && tooltipElement.value) {
    if (!tippyInstance) {
      tippyInstance = tippy(target, {
        content: tooltipElement.value,
        placement: props.placement,
        trigger: 'mouseenter focus',
        appendTo: document.body,
        arrow: true,
        animation: 'shift-away-subtle',
        interactive: props.interactive,
        hideOnClick: true,
        theme: 'custom',
        maxWidth: 250,
        delay: [props.showDelay, 0], // Use configurable delay
        duration: [200, 150], // Animation duration [show, hide]
        offset: [0, 8], // Offset from element [skidding, distance]
        zIndex: 1000001,
      });
    }
  }
};


onMounted(() => {
  createTooltip();
});

onUnmounted(() => {
  if (tippyInstance) {
    tippyInstance.destroy();
  }
});
</script>

<template>
  <div ref="tooltipElement" :class="['tooltip-container', customClass]">
    <slot></slot>
  </div>
</template>

<style lang="scss">
.tooltip-container {
  padding: 8px 12px;
  background-color: color-mix(in srgb, var(--vera-panel) 95%, transparent);
  color: var(--vera-text);
  border-radius: 6px;
  font-size: 0.875rem;
  z-index: 1000001;
  pointer-events: none;
  box-shadow: 0 4px 10px rgba(var(--vera-shadow-rgb), 0.3);
  max-width: 250px;
  line-height: 1.4;
  transition: opacity 0.2s ease-in-out;
  font-weight: 400;
  border: 1px solid var(--vera-success-30);
}

.tippy-box[data-animation='shift-away-subtle'][data-state='hidden'] {
  opacity: 0;
}

.tippy-arrow {
  color: color-mix(in srgb, var(--vera-panel) 95%, transparent);
}
</style>
