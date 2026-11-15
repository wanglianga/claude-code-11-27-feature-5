<template>
  <div class="page-card">
    <el-form inline>
      <el-form-item label="标准品">
        <el-select v-model="filters.product_id" clearable placeholder="全部" style="width: 130px" @change="load">
          <el-option v-for="p in products" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="等级">
        <el-select v-model="filters.grade" clearable placeholder="全部" style="width: 100px" @change="load">
          <el-option v-for="g in ['一级', '二级', '特级']" :key="g" :label="g" :value="g" />
        </el-select>
      </el-form-item>
      <el-form-item label="产地">
        <el-input v-model="filters.origin" clearable placeholder="如 山东" style="width: 120px" @change="load" />
      </el-form-item>
      <el-form-item label="要求到货日">
        <el-date-picker v-model="filters.deliverable_by" type="date" value-format="YYYY-MM-DD" style="width: 150px" @change="load" />
      </el-form-item>
      <el-form-item label="状态">
        <el-radio-group v-model="statusTab" @change="load">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="ok">有效</el-radio-button>
          <el-radio-button value="pending">待核</el-radio-button>
          <el-radio-button value="expired">已过期</el-radio-button>
        </el-radio-group>
      </el-form-item>
    </el-form>

    <el-table :data="rows" border v-loading="loading">
      <el-table-column label="编号" width="90">
        <template #default="{ row }">{{ row.external_id || '#' + row.id }}</template>
      </el-table-column>
      <el-table-column label="来源" prop="source_name" width="130" />
      <el-table-column label="商品名" prop="raw_product_name" width="90" />
      <el-table-column label="标准品" width="90">
        <template #default="{ row }">{{ productName(row.product_id) || '—' }}</template>
      </el-table-column>
      <el-table-column label="等级" width="70">
        <template #default="{ row }">{{ row.grade || '—' }}</template>
      </el-table-column>
      <el-table-column label="产地" prop="origin" width="80" />
      <el-table-column label="加工状态" prop="processing_status" width="100" />
      <el-table-column label="单价" width="110">
        <template #default="{ row }">
          {{ row.price_per_unit }} 元/{{ row.unit_raw || row.unit || '?' }}
          <el-tooltip v-if="row.price_per_unit === 0" content="零价依据"><el-tag size="small" type="success">零价</el-tag></el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="含税" width="80">
        <template #default="{ row }">
          <span v-if="row.tax_included === true">已含</span>
          <span v-else-if="row.tax_included === false">未含</span>
          <el-tag v-else size="small" type="warning">待补</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="有效期至" width="110">
        <template #default="{ row }">{{ row.valid_to || '—' }}</template>
      </el-table-column>
      <el-table-column label="起订量" width="90">
        <template #default="{ row }">{{ row.moq_quantity ? row.moq_quantity + (row.moq_unit || '') : '—' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="180">
        <template #default="{ row }">
          <el-tag v-if="row.review_status === 'pending'" type="warning" size="small">待核</el-tag>
          <el-tag v-else-if="row.expired" type="danger" size="small" effect="plain">已过期</el-tag>
          <el-tag v-else type="success" size="small" effect="plain">有效</el-tag>
          <div v-if="row.pending_reasons?.length" class="muted">{{ row.pending_reasons.join('；') }}</div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="$router.push({ name: 'quote-detail', params: { id: row.id } })">溯源</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import api from '../api'

const products = ref([])
const all = ref([])
const loading = ref(false)
const statusTab = ref('all')
const filters = reactive({ product_id: null, grade: null, origin: null, deliverable_by: null })

const rows = computed(() => all.value.filter((q) => {
  if (statusTab.value === 'pending') return q.review_status === 'pending'
  if (statusTab.value === 'expired') return q.review_status !== 'pending' && q.expired
  if (statusTab.value === 'ok') return q.review_status !== 'pending' && !q.expired
  return true
}))

function productName(id) {
  return products.value.find((p) => p.id === id)?.name
}

async function load() {
  loading.value = true
  try {
    const params = {}
    for (const [k, v] of Object.entries(filters)) if (v) params[k] = v
    const { data } = await api.get('/quotes', { params })
    all.value = data
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  const { data } = await api.get('/products')
  products.value = data
  await load()
})
</script>
