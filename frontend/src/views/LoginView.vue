<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2>农产品报价归集与可比成本分析平台</h2>
      <p class="muted">请使用测试账号登录（见 README）</p>
      <el-form @submit.prevent="doLogin">
        <el-form-item>
          <el-input v-model="username" placeholder="用户名" autofocus />
        </el-form-item>
        <el-form-item>
          <el-input v-model="password" type="password" placeholder="密码" show-password />
        </el-form-item>
        <el-button type="primary" style="width: 100%" :loading="loading" @click="doLogin">登录</el-button>
      </el-form>
      <el-alert v-if="error" :title="error" type="error" style="margin-top: 12px" :closable="false" />
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import { session } from '../store'

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const router = useRouter()

async function doLogin() {
  if (!username.value || !password.value) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.post('/login', { username: username.value, password: password.value })
    session.login(data)
    router.push({ name: 'compare' })
  } catch (e) {
    error.value = e.friendlyMessage || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap { display: flex; justify-content: center; align-items: center; min-height: 100vh; background: #eef3ee; }
.login-card { width: 380px; }
h2 { font-size: 18px; margin: 0 0 4px; color: #2c5e2e; }
</style>
