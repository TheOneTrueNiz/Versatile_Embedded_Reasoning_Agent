import { createRouter, createWebHistory } from 'vue-router';
import ChatLayout from '@/views/ChatLayout.vue';

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'VERA',
      component: ChatLayout,
    },
  ],
});

export default router;
