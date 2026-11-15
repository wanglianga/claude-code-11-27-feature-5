<template>
  <div>
    <div class="page-card">
      <h3>待审核映射（名称相似只提候选，需人工确认后归到标准品）</h3>
      <el-table :data="pending" border v-loading="loading">
        <el-table-column label="原始商品名" prop="raw_name" width="140" />
        <el-table-column label="候选标准品" min-width="240">
          <template #default="{ row }">
            <el-radio-group v-model="row._selected">
              <el-radio v-for="c in row.candidates || []" :key="c.product_id" :value="c.product_id">
                {{ c.name }}
              </el-radio>
              <el-radio :value="'other'">其他标准品…</el-radio>
            </el-radio-group>
            <el-select v-if="row._selected === 'other'" v-model="row._other" size="small" style="width: 140px; margin-left: 8px">
              <el-option v-for="p in products" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="关联报价数" prop="quote_count" width="110" />
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" type="primary" :disabled="!canApprove(row)" @click="approve(row)">通过</el-button>
            <el-button size="small" type="danger" plain @click="reject(row)">驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="page-card">
      <h3>已审核映射</h3>
      <el-table :data="approved" border size="small">
        <el-table-column label="原始商品名" prop="raw_name" width="160" />
        <el-table-column label="标准品" prop="product_name" width="120" />
        <el-table-column label="修订" prop="revision" width="70" />
        <el-table-column label="审核人" prop="reviewed_by" width="110" />
        <el-table-column label="审核时间" prop="reviewed_at" />
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" @click="startRevise(row)">修订映射</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-alert type="info" :closable="false" style="margin-top: 8px"
        title="映射修订只影响后续归集与对比；已生成的采购依据保存当时快照，不受影响。" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const mappings = ref([])
const products = ref([])
const loading = ref(false)

const pending = computed(() => mappings.value.filter((m) => m.status === 'pending'))
const approved = computed(() => mappings.value.filter((m) => m.status === 'approved'))

function canApprove(row) {
  return row._selected && (row._selected !== 'other' || row._other)
}

async function load() {
  loading.value = true
  try {
    const [{ data: ms }, { data: ps }] = await Promise.all([
      api.get('/mappings'), api.get('/products'),
    ])
    mappings.value = ms.map((m) => ({ ...m, _selected: null, _other: null }))
    products.value = ps
  } finally {
    loading.value = false
  }
}

async function approve(row) {
  const productId = row._selected === 'other' ? row._other : row._selected
  try {
    await api.post(`/mappings/${row.id}/approve`, { product_id: productId })
    ElMessage.success('映射已通过，相关报价已归入标准品')
    await load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  }
}

async function reject(row) {
  await ElMessageBox.confirm(`驳回「${row.raw_name}」的映射候选？`, '确认', { type: 'warning' })
  await api.post(`/mappings/${row.id}/reject`, {})
  ElMessage.success('已驳回')
  await load()
}

async function startRevise(row) {
  const { value } = await ElMessageBox.prompt('输入新的标准品 ID（当前：' + (row.product_name || '无') + '）', '修订映射', {
    inputPattern: /^\d+$/, inputErrorMessage: '请输入标准品 ID',
  })
  try {
    await api.post(`/mappings/${row.id}/approve`, { product_id: Number(value), note: '映射修订' })
    ElMessage.success('映射已修订（修订号 +1）')
    await load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  }
}

onMounted(load)
</script>

<style scoped>
h3 { margin: 0 0 12px; font-size: 15px; }
</style>
