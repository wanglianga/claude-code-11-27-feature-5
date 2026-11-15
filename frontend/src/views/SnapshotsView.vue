<template>
  <div>
    <div class="page-card">
      <el-form inline>
        <el-form-item label="菜品">
          <el-select v-model="filters.dish_id" clearable placeholder="全部" style="width: 180px" @change="load">
            <el-option v-for="d in dishes" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width: 130px" @change="load">
            <el-option label="生效" value="active" />
            <el-option label="冲突待确认" value="conflicted" />
            <el-option label="已被替代" value="superseded" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button v-if="session.isBuyer" type="primary" @click="openCreate">生成餐期选价快照</el-button>
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false"
        title="快照为只读事实：固化采用的报价、来源批次、换算依据与出成率证据；后续主数据改版不改写历史快照。" />
    </div>

    <div class="page-card">
      <el-table :data="rows" border v-loading="loading" row-key="id">
        <el-table-column label="快照#" prop="id" width="80" />
        <el-table-column label="菜品" prop="dish_name" width="120" />
        <el-table-column label="餐期" prop="meal_period" width="150" />
        <el-table-column label="供餐日" prop="serving_date" width="110" />
        <el-table-column label="份数" prop="servings" width="80" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'active'" type="success" size="small">生效</el-tag>
            <el-tag v-else-if="row.status === 'conflicted'" type="danger" size="small">冲突待确认</el-tag>
            <el-tag v-else type="info" size="small" effect="plain">已被替代</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="可完整解释" width="110">
          <template #default="{ row }">
            <el-tag :type="row.fully_explainable ? 'success' : 'warning'" size="small">
              {{ row.fully_explainable ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="可解释比例" width="100">
          <template #default="{ row }">{{ row.explainable_ratio != null ? (row.explainable_ratio * 100).toFixed(1) + '%' : '—' }}</template>
        </el-table-column>
        <el-table-column label="单位成本(元/份)" prop="total_unit_cost" width="130" />
        <el-table-column label="发布" width="150">
          <template #default="{ row }">{{ row.published_at ? row.published_at.slice(0, 16).replace('T', ' ') : '未发布' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="$router.push({ name: 'snapshot-detail', params: { id: row.id } })">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="createVisible" title="生成餐期选价快照（只读）" width="480px">
      <el-form :model="form" label-width="92px">
        <el-form-item label="菜品">
          <el-select v-model="form.dish_id" style="width: 100%">
            <el-option v-for="d in dishes" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="供餐日期">
          <el-date-picker v-model="form.serving_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="餐期"><el-input v-model="form.meal_period" /></el-form-item>
        <el-form-item label="即发布报表">
          <el-switch v-model="form.published" />
        </el-form-item>
      </el-form>
      <el-alert type="warning" :closable="false"
        title="缺净用量/换算/过敏原映射会标记为不可完整解释；等级失配不折算可用成本；同生效时刻冲突将挂起待确认。" />
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createSnap">生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'
import { session } from '../store'

const router = useRouter()
const dishes = ref([])
const rows = ref([])
const loading = ref(false)
const createVisible = ref(false)
const saving = ref(false)
const filters = reactive({ dish_id: null, status: null })
const form = reactive({ dish_id: null, serving_date: '', meal_period: '', published: false })

async function load() {
  loading.value = true
  try {
    const params = {}
    for (const [k, v] of Object.entries(filters)) if (v) params[k] = v
    const { data } = await api.get('/snapshots', { params })
    rows.value = data
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { dish_id: dishes.value[0]?.id || null, serving_date: '', meal_period: '', published: false })
  createVisible.value = true
}

async function createSnap() {
  if (!form.dish_id || !form.serving_date || !form.meal_period) {
    ElMessage.warning('请填写菜品、供餐日期与餐期')
    return
  }
  saving.value = true
  try {
    const { data } = await api.post('/snapshots', { ...form })
    ElMessage.success('快照已生成（只读）')
    createVisible.value = false
    router.push({ name: 'snapshot-detail', params: { id: data.id } })
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  const { data } = await api.get('/dishes')
  dishes.value = data
  await load()
})
</script>
