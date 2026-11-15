<template>
  <div>
    <div class="page-card">
      <h3>每道菜的可解释成本比例与缺失证据</h3>
      <el-table :data="rows" border v-loading="loading" row-key="dish_id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div style="padding: 8px 16px">
              <div class="muted" style="margin-bottom: 6px">缺失证据 / 质量事件（最新餐期）：</div>
              <el-table :data="row.missing_evidence" border size="small" style="margin-bottom: 12px">
                <el-table-column label="事件类型" prop="type" width="180" />
                <el-table-column label="级别" prop="severity" width="90" />
                <el-table-column label="原料" prop="ingredient" width="120" />
                <el-table-column label="说明" prop="detail" />
              </el-table>
              <div class="muted" style="margin-bottom: 6px">不能比较的期间（不可完整解释，不参与成本桥接）：</div>
              <el-table :data="row.incomparable_periods" border size="small">
                <el-table-column label="快照#" prop="snapshot_id" width="90" />
                <el-table-column label="供餐日" prop="serving_date" width="130" />
                <el-table-column label="餐期" prop="meal_period" width="160" />
                <el-table-column label="状态" prop="status" width="110" />
                <el-table-column label="原因" min-width="240">
                  <template #default="{ row: p }">
                    <el-tag v-for="r in p.reasons" :key="r" size="small" type="warning" effect="plain" style="margin: 2px">{{ r }}</el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="菜品" prop="dish_name" width="130" />
        <el-table-column label="编码" prop="dish_code" width="130" />
        <el-table-column label="最新快照#" prop="latest_snapshot_id" width="100" />
        <el-table-column label="最新供餐日" prop="latest_serving_date" width="120" />
        <el-table-column label="可完整解释" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.fully_explainable === true" type="success" size="small">是</el-tag>
            <el-tag v-else-if="row.fully_explainable === false" type="danger" size="small">否</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="可解释成本比例" width="150">
          <template #default="{ row }">
            <el-progress v-if="row.explainable_ratio != null"
              :percentage="Math.round(row.explainable_ratio * 100)"
              :status="row.explainable_ratio === 1 ? 'success' : 'warning'" />
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="单位成本(元/份)" prop="total_unit_cost" width="130" />
        <el-table-column label="缺失证据数" width="110">
          <template #default="{ row }">
            <el-badge :value="row.missing_evidence.length" :hidden="!row.missing_evidence.length" type="danger">
              <el-tag size="small" effect="plain">查看</el-tag>
            </el-badge>
          </template>
        </el-table-column>
        <el-table-column label="不可比较期间" width="120">
          <template #default="{ row }">{{ row.incomparable_periods.length }} 个</template>
        </el-table-column>
      </el-table>
    </div>

    <div class="page-card" v-if="session.isChecker">
      <h3>补传验收实测出成率（迟到证据 → 自动生成影响版本）</h3>
      <el-alert type="warning" :closable="false" style="margin-bottom: 12px"
        title="仅当某原料历史餐期采用的是历史估计出成率时，补传同等级同加工状态的抽样实测会生成引用原餐期快照的影响版本，原估计与新证据差额分别保留。" />
      <el-form :model="form" inline>
        <el-form-item label="标准品">
          <el-select v-model="form.product_id" style="width: 140px">
            <el-option v-for="p in products" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="等级"><el-input v-model="form.grade" style="width: 90px" /></el-form-item>
        <el-form-item label="加工状态"><el-input v-model="form.processing_status" style="width: 120px" /></el-form-item>
        <el-form-item label="实测出成率"><el-input-number v-model="form.point" :min="0.01" :max="1" :step="0.01" style="width: 120px" /></el-form-item>
        <el-form-item label="抽样批次"><el-input v-model="form.sample_batch" style="width: 150px" /></el-form-item>
        <el-form-item label="实测日期"><el-date-picker v-model="form.measured_at" type="date" value-format="YYYY-MM-DD" style="width: 140px" /></el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="upload">补传并生成影响版本</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="lastResult" type="success" :closable="false"
        :title="`已登记实测证据 #${lastResult.evidence_id}，影响 ${lastResult.affected_snapshots} 个历史餐期快照、${lastResult.impacts.length} 条影响版本`" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { session } from '../store'

const rows = ref([])
const products = ref([])
const loading = ref(false)
const saving = ref(false)
const lastResult = ref(null)
const form = reactive({
  product_id: null, grade: '一级', processing_status: '带泥毛菜',
  point: 0.68, sample_batch: '', measured_at: '',
})

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/coverage')
    rows.value = data
  } finally {
    loading.value = false
  }
}

async function upload() {
  if (!form.product_id || !form.sample_batch || !form.measured_at) {
    ElMessage.warning('标准品、抽样批次与实测日期必填')
    return
  }
  saving.value = true
  try {
    const { data } = await api.post('/yield-evidences/measured-upload', { ...form })
    lastResult.value = data
    ElMessage.success('影响版本已生成，可到对应餐期快照详情查看原估计与新证据差额')
    await load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  const { data } = await api.get('/products')
  products.value = data
  form.product_id = data[0]?.id ?? null
  await load()
})
</script>

<style scoped>
h3 { margin: 0 0 12px; font-size: 15px; }
</style>
