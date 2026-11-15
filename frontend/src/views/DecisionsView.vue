<template>
  <div class="page-card">
    <h3>采购依据（只读；更正生成新修订，旧依据保留）</h3>
    <el-table :data="decisions" border v-loading="loading">
      <el-table-column label="ID" prop="id" width="70" />
      <el-table-column label="标准品" width="100">
        <template #default="{ row }">{{ productName(row.product_id) }}</template>
      </el-table-column>
      <el-table-column label="来源" prop="source_name" width="140" />
      <el-table-column label="需求" width="170">
        <template #default="{ row }">{{ row.need_type === 'net' ? '可用净重' : '毛重数量' }} {{ row.need_quantity }} kg</template>
      </el-table-column>
      <el-table-column label="采购件数" prop="units" width="100" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">
            {{ row.status === 'active' ? '有效' : '已被更正' }}
          </el-tag>
          <el-tag v-if="row.status === 'active' && !row.terms_still_valid" size="small" type="warning" style="margin-left: 4px">条款已变</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="修订" prop="revision" width="70" />
      <el-table-column label="创建人" prop="created_by" width="100" />
      <el-table-column label="创建时间" prop="created_at" min-width="170" />
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="$router.push({ name: 'decision-detail', params: { id: row.id } })">详情</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api from '../api'

const decisions = ref([])
const products = ref([])
const loading = ref(false)

function productName(id) {
  return products.value.find((p) => p.id === id)?.name || id
}

onMounted(async () => {
  loading.value = true
  try {
    const [{ data: ds }, { data: ps }] = await Promise.all([
      api.get('/decisions'), api.get('/products'),
    ])
    decisions.value = ds
    products.value = ps
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
h3 { margin: 0 0 12px; font-size: 15px; }
</style>
