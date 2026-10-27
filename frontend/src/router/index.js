import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Process from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
  },
  {
    path: '/process/:projectId',
    name: 'Process',
    component: Process,
    props: true
  },
  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    component: SimulationView,
    props: true
  },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    component: SimulationRunView,
    props: true
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: ReportView,
    props: true
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    component: InteractionView,
    props: true
  },
  { path: '/overview', name: 'Overview', component: () => import('../views/Overview.vue') },
  { path: '/treasury', name: 'Treasury', component: () => import('../views/Treasury.vue') },
  { path: '/lending', name: 'Lending', component: () => import('../views/Lending.vue') },
  { path: '/decisions', name: 'Decisions', component: () => import('../views/Decisions.vue') },
  { path: '/execution', name: 'Execution', component: () => import('../views/Execution.vue') }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
