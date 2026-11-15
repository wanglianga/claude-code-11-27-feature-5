<template>
  <div v-if="snap">
    <div class="page-card">
      <el-page-header @back="$router.back()" :title="`餐期选价快照 #${snap.id}（只读）`" />
      <el-descriptions :column="4" border size="small" style="margin-top: 14px">
        <el-descriptions-item label="菜品">{{ snap.dish_name }}</el-descriptions-item>
        <el-descriptions-item label="餐期">{{ snap.meal_period }}</el-descriptions-item>
        <el-descriptions-item label="供餐日">{{ snap.serving_date }}</el-descriptions-item>
        <el-descriptions-item label="份数">{{ snap.servings }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag v-if="snap.status === 'active'" type="success" size="small">生效</el-tag>
          <el-tag v-else-if="snap.status === 'conflicted'" type="danger" size="small">冲突待确认</el-tag>
          <el-tag v-else type="info" size="small" effect="plain">已被替代</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="可完整解释">
          <el-tag :type="snap.fully_explainable ? 'success' : 'warning'" size="small">
            {{ snap.fully_explainable ? '是' : '否' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="可解释比例">
          {{ snap.explainable_ratio != null ? (snap.explainable_ratio * 100).toFixed(1) + '%' : '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="单位成本(元/份)">{{ snap.total_unit_cost ?? '—' }}</el-descriptions-item>
      </el-descriptions>
      <el-alert v-if="snap.conflict_note" type="warning" :closable="false" style="margin-top: 10px" :title="snap.conflict_note" />
    </div>

    <div class="page-card">
      <h3>快照行：固化的关联与换算链</h3>
      <el-table :data="snap.lines" border size="small" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="break">
              <el-descriptions :column="2" size="small" border>
                <el-descriptions-item label="净用量">{{ row.net_qty }} {{ row.net_unit }}</el-descriptions-item>
                <el-descriptions-item label="要求等级/状态">{{ row.required_grade || '—' }} / {{ row.required_processing || '—' }}</el-descriptions-item>
                <el-descriptions-item label="采用报价">
                  <span v-if="row.price_basis">
                    {{ row.source_name }} {{ row.quote_external_id }}（第{{ row.price_basis.quote_revision }}版）
                    {{ row.price_basis.price_per_unit }} 元/{{ row.price_basis.unit_raw }}
                  </span>
                  <span v-else>—</span>
                </el-descriptions-item>
                <el-descriptions-item label="来源批次">
                  {{ row.price_basis ? '#' + row.price_basis.source_batch_id : '—' }}
                </el-descriptions-item>
                <el-descriptions-item label="含税毛价(元/kg)">{{ row.price_basis?.gross_price_per_kg ?? '—' }}</el-descriptions-item>
                <el-descriptions-item label="净用量单价(元/kg)">{{ row.price_basis?.net_price_per_kg ?? '—' }}</el-descriptions-item>
                <el-descriptions-item label="采用出成率">
                  {{ row.yield_value ?? '—' }}
                  <el-tag v-if="row.yield_evidence_kind === 'measured'" size="small" type="success">抽样实测</el-tag>
                  <el-tag v-else-if="row.yield_evidence_kind === 'estimated'" size="small" type="warning">历史估计</el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="行成本(元)">{{ row.line_cost ?? '不计价' }}</el-descriptions-item>
              </el-descriptions>
              <div class="muted" style="margin-top: 8px">换算链（只读固化）：</div>
              <el-steps v-if="row.conversion_chain?.length" :active="row.conversion_chain.length" align-center finish-status="success" size="small">
                <el-step v-for="(c, i) in row.conversion_chain" :key="i" :title="`${c.from}→${c.to}`"
                  :description="`因子 ${c.factor}｜${c.basis}`" />
              </el-steps>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="原料" prop="ingredient_name" width="130" />
        <el-table-column label="可解释" width="90">
          <template #default="{ row }">
            <el-tag :type="row.explainable ? 'success' : 'danger'" size="small">{{ row.explainable ? '是' : '否' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="采用报价" width="140">
          <template #default="{ row }">{{ row.quote_external_id || '—' }}</template>
        </el-table-column>
        <el-table-column label="等级" prop="quote_grade" width="80" />
        <el-table-column label="出成率/证据" width="130">
          <template #default="{ row }">
            <span v-if="row.yield_value != null">
              {{ row.yield_value }}
              <el-tag v-if="row.yield_evidence_kind === 'estimated'" size="small" type="warning">估计</el-tag>
              <el-tag v-else-if="row.yield_evidence_kind === 'measured'" size="small" type="success">实测</el-tag>
            </span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="行成本" prop="line_cost" width="100" />
        <el-table-column label="不可解释原因" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="r in row.unexplained_reasons" :key="r" size="small" type="danger" effect="plain" style="margin: 2px">{{ r }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="page-card" v-if="snap.events.length">
      <h3>质量事件（不静默吞掉）</h3>
      <el-table :data="snap.events" border size="small">
        <el-table-column label="类型" prop="event_type" width="170" />
        <el-table-column label="级别" prop="severity" width="90" />
        <el-table-column label="原料" prop="ingredient_name" width="120" />
        <el-table-column label="说明" prop="detail" />
      </el-table>
    </div>

    <div class="page-card" v-if="snap.conflicts.length">
      <h3>生效时刻映射冲突（保留双候选，待人工确认）</h3>
      <el-alert type="error" :closable="false" style="margin-bottom: 10px"
        title="食谱版本与原料映射版本在同一生效时刻相互冲突；不按最后上传时间覆盖，请数据管理员确认采用哪一套关联。" />
      <div v-for="c in snap.conflicts" :key="c.id" class="conflict-box">
        <div class="muted">冲突 #{{ c.id }} · {{ c.ingredient_name }} · 生效时刻 {{ c.effective_at }} · 状态 {{ c.status === 'pending' ? '待确认' : '已确认(' + c.resolution + ')' }}</div>
        <el-row :gutter="12" style="margin-top: 8px">
          <el-col :span="12">
            <el-card shadow="never" :class="{ chosen: c.resolution === 'a' }">
              <template #header>候选 A（映射修订 {{ c.candidate_a.revision }}）</template>
              <div>标准品ID：{{ c.candidate_a.product_id }}</div>
              <div>采购编码：{{ c.candidate_a.purchase_code || '—' }}</div>
              <div>等级/状态：{{ c.candidate_a.grade }} / {{ c.candidate_a.processing_status }}</div>
              <div class="muted">{{ c.candidate_a.note }}</div>
              <el-button v-if="c.status === 'pending' && session.isBuyer" size="small" type="primary"
                style="margin-top: 8px" :loading="resolving" @click="resolve(c.id, 'a')">采用候选 A 重建快照</el-button>
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never" :class="{ chosen: c.resolution === 'b' }">
              <template #header>候选 B（映射修订 {{ c.candidate_b.revision }}）</template>
              <div>标准品ID：{{ c.candidate_b.product_id }}</div>
              <div>采购编码：{{ c.candidate_b.purchase_code || '—' }}</div>
              <div>等级/状态：{{ c.candidate_b.grade }} / {{ c.candidate_b.processing_status }}</div>
              <div class="muted">{{ c.candidate_b.note }}</div>
              <el-button v-if="c.status === 'pending' && session.isBuyer" size="small" type="success"
                style="margin-top: 8px" :loading="resolving" @click="resolve(c.id, 'b')">采用候选 B 重建快照</el-button>
            </el-card>
          </el-col>
        </el-row>
      </div>
    </div>

    <div class="page-card" v-if="snap.impacts.length">
      <h3>影响版本：报表发布后补传的验收实测出成率（引用本原快照，原估计保留）</h3>
      <el-table :data="snap.impacts" border size="small">
        <el-table-column label="影响#" prop="id" width="80" />
        <el-table-column label="原因" prop="reason" min-width="200" />
        <el-table-column label="原估计出成率" width="120">
          <template #default="{ row }">{{ row.old_yield }}（{{ row.old_yield_kind === 'estimated' ? '历史估计' : row.old_yield_kind }}）</template>
        </el-table-column>
        <el-table-column label="新实测出成率" prop="new_yield" width="120" />
        <el-table-column label="原行成本" prop="old_line_cost" width="100" />
        <el-table-column label="新行成本" prop="new_line_cost" width="100" />
        <el-table-column label="行差额" width="100">
          <template #default="{ row }">
            <span :style="{ color: row.cost_delta > 0 ? '#f56c6c' : '#67c23a' }">{{ row.cost_delta > 0 ? '+' : '' }}{{ row.cost_delta }}</span>
          </template>
        </el-table-column>
        <el-table-column label="每份差额" width="110">
          <template #default="{ row }">
            <span :style="{ color: row.unit_cost_delta > 0 ? '#f56c6c' : '#67c23a' }">{{ row.unit_cost_delta > 0 ? '+' : '' }}{{ row.unit_cost_delta }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'
import { session } from '../store'

const route = useRoute()
const router = useRouter()
const snap = ref(null)
const resolving = ref(false)

async function load() {
  const { data } = await api.get(`/snapshots/${route.params.id}`)
  snap.value = data
}

async function resolve(conflictId, choice) {
  resolving.value = true
  try {
    const { data } = await api.post(`/mapping-conflicts/${conflictId}/resolve`, { choice })
    ElMessage.success(`已按候选 ${choice.toUpperCase()} 重建只读快照 #${data.id}，原快照保留留痕`)
    router.push({ name: 'snapshot-detail', params: { id: data.id } })
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    resolving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
h3 { margin: 0 0 12px; font-size: 15px; }
.break { padding: 8px 16px; background: #fafafa; }
.conflict-box { border: 1px solid #f56c6c33; border-radius: 6px; padding: 12px; margin-bottom: 12px; }
.chosen { border-color: #67c23a; }
</style>
