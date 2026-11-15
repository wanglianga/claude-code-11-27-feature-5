<template>
  <el-container v-if="session.user" class="layout">
    <el-header class="header">
      <div class="brand">农产品报价归集与可比成本分析平台</div>
      <el-menu :default-active="$route.name" mode="horizontal" router class="nav" :ellipsis="false">
        <el-menu-item index="compare" :route="{ name: 'compare' }">成本对比</el-menu-item>
        <el-menu-item index="quotes" :route="{ name: 'quotes' }">报价与待核</el-menu-item>
        <el-menu-item index="mappings" :route="{ name: 'mappings' }">映射审核</el-menu-item>
        <el-menu-item index="imports" :route="{ name: 'imports' }">导入管理</el-menu-item>
        <el-menu-item index="decisions" :route="{ name: 'decisions' }">采购依据</el-menu-item>
        <el-menu-item index="market" :route="{ name: 'market' }">市场参考价</el-menu-item>
        <el-menu-item index="recipes" :route="{ name: 'recipes' }">食谱事实</el-menu-item>
        <el-menu-item index="snapshots" :route="{ name: 'snapshots' }">餐期快照</el-menu-item>
        <el-menu-item index="bridges" :route="{ name: 'bridges' }">成本桥接</el-menu-item>
        <el-menu-item index="coverage" :route="{ name: 'coverage' }">覆盖质量</el-menu-item>
      </el-menu>
      <div class="user">
        <el-tag size="small" effect="plain">{{ session.user.role_name }}</el-tag>
        <span>{{ session.user.display_name }}</span>
        <el-button link type="primary" @click="logout">退出</el-button>
      </div>
    </el-header>
    <el-main>
      <router-view />
    </el-main>
  </el-container>
  <router-view v-else />
</template>

<script setup>
import { useRouter } from 'vue-router'
import { session } from './store'

const router = useRouter()
function logout() {
  session.logout()
  router.push({ name: 'login' })
}
</script>

<style>
body { margin: 0; font-family: 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif; }
.layout .header { display: flex; align-items: center; gap: 24px; border-bottom: 1px solid #e4e7ed; padding: 0 20px; }
.brand { font-weight: 700; font-size: 16px; white-space: nowrap; color: #2c5e2e; }
.nav { flex: 1; border-bottom: none; }
.user { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.el-main { background: #f5f7fa; min-height: calc(100vh - 60px); }
.page-card { background: #fff; border-radius: 6px; padding: 16px 20px; margin-bottom: 16px; }
.muted { color: #909399; font-size: 12px; }
.mono { font-family: 'SFMono-Regular', Consolas, monospace; }
</style>
