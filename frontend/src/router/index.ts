import { createRouter, createWebHistory } from 'vue-router'

import { useAuth } from '@/composables/useAuth'
import DashboardView from '@/views/DashboardView.vue'
import HomeView from '@/views/HomeView.vue'
import LoginView from '@/views/LoginView.vue'
import SettingsView from '@/views/SettingsView.vue'
import UploadView from '@/views/UploadView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { bare: true, title: 'Вход' } },
    { path: '/', name: 'home', component: HomeView, meta: { title: 'Главная' } },
    { path: '/dashboard', name: 'dashboard', component: DashboardView, meta: { title: 'Дашборд' } },
    { path: '/upload', name: 'upload', component: UploadView, meta: { title: 'Загрузка данных' } },
    { path: '/settings', name: 'settings', component: SettingsView, meta: { title: 'Настройки' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  const { signedIn } = useAuth()
  if (to.meta.bare) return signedIn.value ? { name: 'home' } : true
  return signedIn.value ? true : { name: 'login' }
})

export default router
