import { createApp } from 'vue';
import App from './App.vue';
import router from './router';

import PrimeVue from 'primevue/config';

import Sidebar from 'primevue/sidebar';
import DataTable from 'primevue/datatable';
import ToggleButton from 'primevue/togglebutton';
import Column from 'primevue/column';
import Button from 'primevue/button';
import Dropdown from 'primevue/dropdown';
import InputText from 'primevue/inputtext';
import Listbox from 'primevue/listbox';
import Ripple from 'primevue/ripple';
import Menu from 'primevue/menu';
import ContextMenu from 'primevue/contextmenu';
import Avatar from 'primevue/avatar';
import SelectButton from 'primevue/selectbutton';

import 'primeicons/primeicons.css';
import 'primevue/resources/themes/aura-dark-green/theme.css';
import './assets/main.css';

const UI_CACHE_EPOCH_KEY = 'uiCacheEpoch';
const UI_CACHE_EPOCH_VALUE = '2026-02-12-sidebar-collapse-fix-3';

const clearServiceWorkerCaches = async () => {
    if (typeof window === 'undefined') return;
    if ('serviceWorker' in navigator) {
        const registrations = await navigator.serviceWorker.getRegistrations();
        await Promise.all(registrations.map((registration) => registration.unregister()));
    }
    if ('caches' in window) {
        const cacheKeys = await caches.keys();
        await Promise.all(cacheKeys.map((key) => caches.delete(key)));
    }
};

const maybeInvalidateStaleUiCache = async () => {
    if (typeof window === 'undefined') return false;
    const currentEpoch = localStorage.getItem(UI_CACHE_EPOCH_KEY);
    if (currentEpoch === UI_CACHE_EPOCH_VALUE) {
        return false;
    }
    const reducedMotionPref = localStorage.getItem('a11yReducedMotion');
    if (!reducedMotionPref || reducedMotionPref === 'system') {
        localStorage.setItem('a11yReducedMotion', 'off');
    }
    localStorage.setItem(UI_CACHE_EPOCH_KEY, UI_CACHE_EPOCH_VALUE);
    await clearServiceWorkerCaches();
    window.location.reload();
    return true;
};

const maybeResetUiTokens = async () => {
    if (typeof window === 'undefined') return false;
    const url = new URL(window.location.href);
    if (url.searchParams.get('resetTokens') !== '1') return false;
    const resetCache = url.searchParams.get('resetCache') === '1';
    const keysToRemove = [];
    for (let i = 0; i < localStorage.length; i += 1) {
        const key = localStorage.key(i);
        if (key && key.startsWith('ui')) {
            keysToRemove.push(key);
        }
    }
    keysToRemove.forEach((key) => localStorage.removeItem(key));
    if (resetCache) {
        await clearServiceWorkerCaches();
    }
    url.searchParams.delete('resetTokens');
    url.searchParams.delete('resetCache');
    window.location.replace(url.toString());
    return true;
};

const bootstrap = async () => {
    if (await maybeResetUiTokens()) {
        // Stop bootstrapping the app during reset.
        return;
    }
    if (await maybeInvalidateStaleUiCache()) {
        // Stop bootstrapping while cache invalidation reloads the app.
        return;
    }
    const app = createApp(App);

    app.use(router);

    // Configure PrimeVue
    app.use(PrimeVue, { ripple: true });
    app.directive('ripple', Ripple);

    app.component('Sidebar', Sidebar);
    app.component('ToggleButton', ToggleButton);
    app.component('DataTable', DataTable);
    app.component('Column', Column);
    app.component('Button', Button);
    app.component('Dropdown', Dropdown);
    app.component('InputText', InputText);
    app.component('Listbox', Listbox);
    app.component('Menu', Menu);
    app.component('ContextMenu', ContextMenu);
    app.component('Avatar', Avatar);
    app.component('SelectButton', SelectButton);

    app.mount('#app');
};

bootstrap();
