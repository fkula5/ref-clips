import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useSession } from '../composables/useSession'

const formerPaths = [
  ['mecze', 'matches'],
  ['mecze/nowy', 'match-create'],
  ['mecze/:id(\\d+)', 'match-detail'],
  ['mecze/:id(\\d+)/edycja', 'match-edit'],
  ['mecze/:id(\\d+)/opisywanie', 'describe-queue'],
  ['klipy', 'clips'],
  ['klipy/:id(\\d+)', 'clip-detail'],
  ['nagrania/:id(\\d+)', 'recording'],
  ['nagrania/:id(\\d+)/edycja', 'recording-edit'],
  ['powiadomienia', 'notifications'],
  ['powiadomienia/ustawienia', 'notification-settings'],
  ['grupy', 'groups'],
  ['grupy/:id(\\d+)', 'group-detail'],
  ['grupy/:id(\\d+)/do-oceny', 'group-review'],
  ['zestawy', 'sets'],
  ['zestawy/:id(\\d+)', 'set-detail'],
  ['zestawy/:id(\\d+)/klipy/:clipId(\\d+)', 'set-clip'],
  ['administracja/:section?', 'administration'],
  ['arkusze/:id(\\d+)', 'sheet'],
  ['samooceny', 'self-assessments'],
  ['samooceny/:id(\\d+)', 'self-assessment'],
  ['sedziowie/:id(\\d+)', 'referee'],
] as const

const formerRoutes: RouteRecordRaw[] = [
  ...formerPaths.map(([path, name]) => ({ path, redirect: { name } })),
  {
    path: 'arkusze/:id(\\d+)/edycja',
    redirect: to => ({ name: 'sheet', params: { id: to.params.id, mode: 'edit' } }),
  },
  {
    path: 'samooceny/:id(\\d+)/edycja',
    redirect: to => ({ name: 'self-assessment', params: { id: to.params.id, mode: 'edit' } }),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/auth/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { title: 'Logowanie' } },
    { path: '/connection-error', name: 'connection-error', component: () => import('../views/ConnectionErrorView.vue'), meta: { title: 'Brak połączenia' } },
    { path: '/auth/reset', name: 'password-reset', component: () => import('../views/PasswordResetView.vue'), meta: { standalone: true, title: 'Odzyskiwanie hasła' } },
    { path: '/set-password/:token', name: 'set-password', component: () => import('../views/SetPasswordView.vue'), meta: { standalone: true, title: 'Ustaw hasło' } },
    { path: '/s/:code', name: 'public-share', component: () => import('../views/PublicShareView.vue'), meta: { standalone: true, title: 'Udostępnione klipy' } },
    { path: '/unsubscribe/:token', name: 'unsubscribe', component: () => import('../views/UnsubscribeView.vue'), meta: { standalone: true, title: 'Wypisanie z podsumowań' } },
    {
      path: '/', component: () => import('../layouts/MainLayout.vue'), meta: { requiresAuth: true },
      children: [
        { path: '', redirect: { name: 'matches' } },
        { path: 'matches', name: 'matches', component: () => import('../views/MatchesView.vue'), meta: { title: 'Mecze' } },
        { path: 'matches/:id(\\d+)', name: 'match-detail', component: () => import('../views/MatchDetailView.vue'), meta: { title: 'Szczegóły meczu' } },
        { path: 'matches/new', name: 'match-create', component: () => import('../views/MatchFormView.vue'), meta: { title: 'Nowy mecz' } },
        { path: 'matches/:id(\\d+)/edit', name: 'match-edit', component: () => import('../views/MatchFormView.vue'), meta: { title: 'Edycja meczu' } },
        { path: 'matches/:id(\\d+)/describe', name: 'describe-queue', component: () => import('../views/DescribeQueueView.vue'), meta: { title: 'Opisywanie znaczników' } },
        { path: 'clips/:id(\\d+)', name: 'clip-detail', component: () => import('../views/ClipDetailView.vue'), meta: { title: 'Szczegóły klipu' } },
        { path: 'clips', name: 'clips', component: () => import('../views/ClipsView.vue'), meta: { title: 'Klipy' } },
        { path: 'recordings/:id(\\d+)', name: 'recording', component: () => import('../views/RecordingView.vue'), meta: { title: 'Analiza nagrania' } },
        { path: 'recordings/:id(\\d+)/edit', name: 'recording-edit', component: () => import('../views/RecordingEditView.vue'), meta: { title: 'Edycja nagrania' } },
        { path: 'notifications', name: 'notifications', component: () => import('../views/NotificationsView.vue'), meta: { title: 'Powiadomienia' } },
        { path: 'notifications/settings', name: 'notification-settings', component: () => import('../views/NotificationSettingsView.vue'), meta: { title: 'Ustawienia powiadomień' } },
        { path: 'groups', name: 'groups', component: () => import('../views/GroupsView.vue'), meta: { title: 'Grupy szkoleniowe' } },
        { path: 'groups/:id(\\d+)', name: 'group-detail', component: () => import('../views/GroupDetailView.vue'), meta: { title: 'Grupa szkoleniowa' } },
        { path: 'groups/:id(\\d+)/review', name: 'group-review', component: () => import('../views/GroupReviewView.vue'), meta: { title: 'Klipy do oceny' } },
        { path: 'training-sets', name: 'sets', component: () => import('../views/SetsView.vue'), meta: { title: 'Zestawy szkoleniowe' } },
        { path: 'training-sets/:id(\\d+)', name: 'set-detail', component: () => import('../views/SetDetailView.vue'), meta: { title: 'Zestaw szkoleniowy' } },
        { path: 'training-sets/:id(\\d+)/clips/:clipId(\\d+)', name: 'set-clip', component: () => import('../views/SetClipView.vue'), meta: { title: 'Klip szkoleniowy' } },
        { path: 'admin/:section?', name: 'administration', component: () => import('../views/AdminView.vue'), meta: { title: 'Administracja' } },
        { path: 'sheets/:id(\\d+)/:mode(edit)?', name: 'sheet', component: () => import('../views/SheetView.vue'), meta: { title: 'Arkusz oceny' } },
        { path: 'self-assessments', name: 'self-assessments', component: () => import('../views/SelfAssessmentsView.vue'), meta: { title: 'Samooceny' } },
        { path: 'self-assessments/:id(\\d+)/:mode(edit)?', name: 'self-assessment', component: () => import('../views/SelfAssessmentView.vue'), meta: { title: 'Samoocena' } },
        { path: 'referees/:id(\\d+)', name: 'referee', component: () => import('../views/RefereeView.vue'), meta: { title: 'Profil sędziego' } },
        ...formerRoutes,
        { path: ':pathMatch(.*)*', name: 'not-found', component: () => import('../views/NotFoundView.vue'), meta: { title: 'Nie znaleziono strony' } },
      ],
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async to => {
  if (to.name === 'connection-error' || to.meta.standalone) return
  const session = useSession()
  try {
    await session.initialize()
  } catch {
    return { name: 'connection-error' }
  }
  if (to.meta.requiresAuth && !session.user.value) {
    const keepRoom = to.name === 'recording' && to.hash.startsWith('#room=')
    return { name: 'login', query: { next: keepRoom ? to.fullPath.split('#')[0] : to.fullPath }, hash: keepRoom ? to.hash : '' }
  }
  if (to.name === 'login' && session.user.value) return { name: 'matches' }
})

router.afterEach(to => { document.title = `${String(to.meta.title || 'Analiza meczu')} — Ref Clips` })

export default router
