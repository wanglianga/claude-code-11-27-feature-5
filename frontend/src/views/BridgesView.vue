<template>
  <div>
    <div class="page-card">
      <h3>新建成本桥（固定顺序：份量 → 价格 → 出成率 → 规格 → 映射）</h3>
      <el-form inline>
        <el-form-item label="菜品">
          <el-select v-model="dishId" style="width: 170px" @change="loadSnaps">
            <el-option v-for="d in dishes" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="基准餐期快照">
          <el-select v-model="baseId" style="width: 260px" placeholder="较早餐期">
            <el-option v-for="s in explainableSnaps" :key="s.id"
              :label="`#${s.id} ${s.serving_date} ${s.meal_period}（${s.total_unit_cost}元/份）`" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="对比餐期快照">
          <el-select v-model="targetId" style="width: 260px" placeholder="较晚餐期">
            <el-option v-for="s in explainableSnaps" :key="s.id"
              :label="`#${s.id} ${s.serving_date} ${s.meal_period}（${s.total_unit_cost}元/份）`" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button v-if="session.isBuyer" type="primary" :loading="saving" @click="createBridge">分解单位成本变化</el-button>
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false"
        title="只允许在两个可完整解释的餐期间桥接；不可解释的期间在「覆盖质量」页列出。全部依据只读自快照，不回查实时主数据。" />
    </div>

    <div class="page-card">
      <h3>已生成的成本桥</h3>
      <el-table :data="bridges" border v-loading="loading" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div style="padding: 8px 16px">
              <el-table :data="row.steps" border size="small">
                <el-table-column label="分解顺序/因素" prop="factor" width="110" />
                <el-table-column label="本步贡献(元/份)" width="150">
                  <template #default="{ row: s }">
                    <span :style="{ color: s.contribution > 0 ? '#f56c6c' : '#67c23a' }">
                      {{ s.contribution > 0 ? '+' : '' }}{{ s.contribution }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="替换后单位成本" prop="unit_cost_after" width="140" />
                <el-table-column label="变化明细/依据" min-width="280">
                  <template #default="{ row: s }">
                    <pre class="json">{{ JSON.stringify(s.detail, null, 1) }}</pre>
                    <div class="muted">依据：{{ JSON.stringify(s.evidence) }}</div>
                  </template>
                </el-table-column>
              </el-table>
              <el-alert style="margin-top: 8px" type="info" :closable="false" :title="row.note" />
            </div>
          </template>
        </el-table-column>
        <el-table-column label="桥#" prop="id" width="70" />
        <el-table-column label="基准快照#" prop="base_snapshot_id" width="100" />
        <el-table-column label="对比快照#" prop="target_snapshot_id" width="100" />
        <el-table-column label="基准单位成本" prop="base_unit_cost" width="120" />
        <el-table-column label="对比单位成本" prop="target_unit_cost" width="120" />
        <el-table-column label="总差额(=各步之和)" width="150">
          <template #default="{ row }">
            <b :style="{ color: row.total_delta > 0 ? '#f56c6c' : '#67c23a' }">
              {{ row.total_delta > 0 ? '+' : '' }}{{ row.total_delta }}
            </b>
          </template>
        </el-table-column>
        <el-table-column label="自洽" width="80">
          <template #default="{ row }">
            <el-tag :type="row.consistent ? 'success' : 'danger'" size="small">{{ row.consistent ? '是' : '否' }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { session } from '../store'

const dishes = ref([])
const dishId = ref(null)
const snaps = ref([])
const bridges = ref([])
const baseId = ref(null)
const targetId = ref(null)
const loading = ref(false)
const saving = ref(false)

const explainableSnaps = computed(() => snaps.value.filter((s) => s.fully_explainable && s.status !== 'superseded'))

async function loadSnaps() {
  if (!dishId.value) return
  const { data } = await api.get('/snapshots', { params: { dish_id: dishId.value } })
  snaps.value = data
}

async function loadBridges() {
  loading.value = true
  try {
    const params = dishId.value ? { dish_id: dishId.value } : {}
    const { data } = await api.get('/cost-bridges', { params })
    bridges.value = data
  } finally {
    loading.value = false
  }
}

async function createBridge() {
  if (!baseId.value || !targetId.value) {
    ElMessage.warning('请选择两个餐期快照')
    return
  }
  saving.value = true
  try {
    await api.post('/cost-bridges', { base_snapshot_id: baseId.value, target_snapshot_id: targetId.value })
    ElMessage.success('成本桥已生成，可展开查看五步分解与依据')
    await loadBridges()
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  const { data } = await api.get('/dishes')
  dishes.value = data
  if (data.length) {
    dishId.value = data[0].id
    await Promise.all([loadSnaps(), loadBridges()])
  }
})
</script>

<style scoped>
h3 { margin: 0 0 12px; font-size: 15px; }
.json { margin: 0; font-size: 12px; white-space: pre-wrap; word-break: break-all; }
</style>
