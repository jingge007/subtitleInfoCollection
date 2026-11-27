import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { title: '任务中心', subtitle: '采集总览 · 最近运行' },
    },
    {
      path: '/collect',
      name: 'collect',
      component: () => import('@/views/CollectView.vue'),
      meta: { title: '开始采集', subtitle: '任务参数 · 实时进度' },
    },
    {
      path: '/parser',
      name: 'parser',
      component: () => import('@/views/ParserView.vue'),
      meta: { title: '字幕解析', subtitle: '本地 SRT / ASS 导入' },
    },
    {
      path: '/automation',
      name: 'automation',
      component: () => import('@/views/AutomationView.vue'),
      meta: { title: '自动化', subtitle: '33 台词任务' },
    },
    {
      path: '/scripts',
      name: 'scripts',
      component: () => import('@/views/ScriptsView.vue'),
      meta: { title: '脚本中心', subtitle: '常用自动化入口' },
    },
    {
      path: '/classic',
      name: 'classic',
      component: () => import('@/views/ClassicView.vue'),
      meta: { title: '经典台词', subtitle: '全量抓取' },
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/HistoryView.vue'),
      meta: { title: '历史记录', subtitle: '运行统计与产物' },
    },
    {
      path: '/config',
      name: 'config',
      component: () => import('@/views/ConfigView.vue'),
      meta: { title: '配置项', subtitle: '本机 .env' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: { title: '设置与维护', subtitle: '更新与数据维护' },
    },
  ],
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || '字幕采集工具'
  document.title = `${title} · 字幕采集工具`
})

export default router
