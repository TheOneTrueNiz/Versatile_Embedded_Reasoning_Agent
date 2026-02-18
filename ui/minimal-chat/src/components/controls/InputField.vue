<script setup>
import { defineProps, defineEmits } from 'vue';

const props = defineProps({
  labelText: String,
  value: String,
  inputId: String,
  placeholderText: String,
  isSecret: Boolean,
  isMultiline: Boolean, // New prop to enable multiline input
  type: {
    type: String,
    default: 'text',
  },
});

const emit = defineEmits(['update:value']);

function emitUpdate(event) {
  emit('update:value', event.target.value);
}
</script>

<template>
  <div class="input-field">
    <!-- Render the label if labelText is provided -->
    <label :for="props.inputId" v-if="props.labelText">{{ props.labelText }}</label>
    <!-- Conditionally render input or textarea based on isMultiline -->
    <InputText v-if="!props.isMultiline" :id="props.inputId" :value="props.value" @blur="emitUpdate"
      :type="props.isSecret ? 'password' : props.type" :placeholder="props.placeholderText"
      :autocomplete="props.isSecret ? 'off' : 'on'" />
    <textarea v-else :id="props.inputId" :value="props.value" @blur="emitUpdate" :placeholder="props.placeholderText"
      rows="4"></textarea>
  </div>
</template>

<style lang="scss" scoped>
.input-field {
  display: flex;
  flex-direction: column;
  padding-bottom: 15px;
  min-width: 0;

  label {
    font-size: 0.875rem;
    font-weight: bold;
    margin-bottom: 5px;
    display: block;
    color: var(--vera-text);
    line-height: 1.2;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
    
    @media (max-width: 600px) {
      font-size: 1rem;
      margin-bottom: 8px;
    }
  }

  input,
  textarea {
    width: 100%;
    padding: 10px;
    color: var(--vera-input-text);
    border-radius: 5px;
    border: none;
    background-color: var(--vera-input-bg);
    font-size: 1rem;
    font-family: Roboto-Regular, sans-serif;
    
    @media (max-width: 600px) {
      padding: 12px;
      border-radius: 8px;
      font-size: 1rem;
      margin-bottom: 5px;
    }

    &:focus {
      outline: none;
      border-color: var(--vera-accent);
      box-shadow: 0 0 6px var(--vera-accent-soft);
    }
  }

  // Additional styles for textarea
  textarea {
    resize: vertical; // Allow vertical resizing
    min-height: 80px;
    
    @media (max-width: 600px) {
      min-height: 100px;
    }
  }
}
</style>
