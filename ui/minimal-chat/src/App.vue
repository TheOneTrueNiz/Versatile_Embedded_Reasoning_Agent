<script setup>
import ChatLayout from './views/ChatLayout.vue';
</script>
<template>

  <body>
    <ChatLayout />
  </body>
</template>

<style lang="scss">
/* Base font definitions */
@font-face {
  font-family: 'Roboto';
  src: url('/webfonts/Roboto-Light.ttf') format('truetype');
  font-weight: 300;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'Roboto';
  src: url('/webfonts/Roboto-Regular.ttf') format('truetype');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'Roboto';
  src: url('/webfonts/Roboto-Medium.ttf') format('truetype');
  font-weight: 500;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'Roboto';
  src: url('/webfonts/Roboto-Bold.ttf') format('truetype');
  font-weight: 700;
  font-style: normal;
  font-display: swap;
}

/* Apply font family to the body */
body {
  display: flex;
  font-family: 'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
  font-weight: 400;
  background-color: var(--vera-bg);
  color: var(--vera-text);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  
  @media (max-width: 600px) {
    font-size: 14px;
  }
}

@keyframes spinner {
  to {
    transform: rotate(360deg);
  }
}

.spinner {
  display: inline-block;
  width: 10px;
  color: var(--vera-accent);
  height: 10px;
  margin-left: 5px;
  border: 4px solid var(--vera-accent);
  border-left-color: var(--vera-accent-strong);
  border-radius: 50%;
  animation: spinner 1s linear infinite;
}

.loading {
  background-color: var(--vera-panel-alt);
  color: var(--vera-text-muted);
}

.loading::after {
  content: '';
  position: absolute;
  top: 0;
  left: -5px;
  border-width: 5px 5px 0 0;
  border-style: solid;
  border-color: transparent var(--vera-panel-alt);
}
</style>
