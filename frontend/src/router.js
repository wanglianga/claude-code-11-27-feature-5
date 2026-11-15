import { createRouter, createWebHistory } from 'vue-router'
import { session } from './store'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
  { path: '/', name: 'compare', component: () => import('./views/CompareView.vue') },
  { path: '/quotes', name: 'quotes', component: () => import('./views/QuotesView.vue') },
  { path: '/quotes/:id', name: 'quote-detail', component: () => import('./views/QuoteDetailView.vue') },
  { path: '/mappings', name: 'mappings', component: () => import('./views/MappingsView.vue') },
  { path: '/imports', name: 'imports', component: () => import('./views/ImportsView.vue') },
  { path: '/decisions', name: 'decisions', component: () => import('./views/DecisionsView.vue') },
  { path: '/decisions/:id', name: 'decision-detail', component: () => import('./views/DecisionDetailView.vue') },
  { path: '/market', name: 'market', component: () => import('./views/MarketView.vue') },
  { path: '/recipes', name: 'recipes', component: () => import('./views/RecipesView.vue') },
  { path: '/snapshots', name: 'snapshots', component: () => import('./views/SnapshotsView.vue') },
  { path: '/snapshots/:id', name: 'snapshot-detail', component: () => import('./views/SnapshotDetailView.vue') },
  { path: '/bridges', name: 'bridges', component: () => import('./views/BridgesView.vue') },
  { path: '/coverage', name: 'coverage', component: () => import('./views/CoverageView.vue') },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  if (!session.user && to.name !== 'login') return { name: 'login' }
  if (session.user && to.name === 'login') return { name: 'compare' }
})

export default router
