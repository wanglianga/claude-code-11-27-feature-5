<template>
  <div v-if="detail">
    <div class="page-card">
      <el-page-header @back="$router.back()" :title="`采购依据 #${detail.id}（只读）`" />
      <el-alert v-if="!detail.terms_still_valid" type="warning" :closable="false" style="margin-top: 12px"
        title="该报价条款已发生变化（存在新修订）。已选采购仍指向本依据；人员明确采用新修订后才生成更正。">
        <el-button v-if="session.isBuyer" size="small" type="warning" style="margin-top: 8px" @click="openCorrect">采用新修订并更正</el-button>
      </el-alert>
      <el-descriptions :column="3" border style="margin-top: 16px" title="冻结条款">
        <el-descriptions-item label="来源">{{ detail.source_name }}</el-descriptions-item>
        <el-descriptions-item label="报价编号">{{ detail.snapshot.terms.external_id }} · 第 {{ detail.snapshot.terms.quote_revision }} 版</el-descriptions-item>
        <el-descriptions-item label="需求">{{ detail.need_type === 'net' ? '可用净重' : '毛重数量' }} {{ detail.need_quantity }} kg</el-descriptions-item>
        <el-descriptions-item label="单价">{{ detail.snapshot.terms.price_per_unit }} 元/{{ detail.snapshot.terms.unit_raw }}</el-descriptions-item>
        <el-descriptions-item label="采购件数">{{ detail.units }} {{ detail.snapshot.terms.unit_raw }}</el-descriptions-item>
        <el-descriptions-item label="税费">{{ detail.snapshot.terms.tax_included ? '已含' : '未含（税率 ' + (detail.snapshot.terms.tax_rate ?? '—') + '）' }}</el-descriptions-item>
        <el-descriptions-item label="等级/产地">{{ detail.snapshot.terms.grade }} / {{ detail.snapshot.terms.origin }}</el-descriptions-item>
        <el-descriptions-item label="加工状态">{{ detail.snapshot.terms.processing_status }}</el-descriptions-item>
        <el-descriptions-item label="交付">{{ detail.snapshot.terms.delivery_mode }} · {{ detail.snapshot.terms.lead_days }} 日达</el-descriptions-item>
        <el-descriptions-item label="计划总成本">{{ detail.snapshot.planned.total_cost }} 元</el-descriptions-item>
        <el-descriptions-item label="计划可用量">{{ detail.snapshot.planned.usable_kg_planned }} kg（出成率 {{ detail.snapshot.planned.yield_used }}）</el-descriptions-item>
        <el-descriptions-item label="出成率依据" v-if="detail.snapshot.yield_rate">
          {{ detail.snapshot.yield_rate.lower }} ~ {{ detail.snapshot.yield_rate.upper }}（{{ detail.snapshot.yield_rate.evidence }}）
        </el-descriptions-item>
      </el-descriptions>
      <el-descriptions :column="4" border size="small" style="margin-top: 12px" title="计划成本构成">
        <el-descriptions-item label="货值">{{ detail.snapshot.planned.breakdown.goods_amount }} 元</el-descriptions-item>
        <el-descriptions-item label="税额">{{ detail.snapshot.planned.breakdown.tax_amount }} 元</el-descriptions-item>
        <el-descriptions-item label="运费">{{ detail.snapshot.planned.breakdown.freight }} 元（{{ detail.snapshot.planned.breakdown.freight_desc }}）</el-descriptions-item>
        <el-descriptions-item label="分摊费用">{{ detail.snapshot.planned.breakdown.alloc_fees }} 元</el-descriptions-item>
      </el-descriptions>
    </div>

    <div class="page-card">
      <h3>验收记录（按实际车次关联原订单；短装、退货、等级拒收分开登记）</h3>
      <el-table :data="detail.acceptances" border size="small" style="margin-bottom: 12px">
        <el-table-column label="车次" prop="trip_no" width="110" />
        <el-table-column label="实到毛重(kg)" prop="received_weight_kg" width="110" />
        <el-table-column label="实际单价" prop="actual_unit_price" width="90" />
        <el-table-column label="实际等级" prop="actual_grade" width="90" />
        <el-table-column label="退货(kg)" prop="returned_weight_kg" width="90" />
        <el-table-column label="等级拒收(kg)" prop="grade_rejected_weight_kg" width="110" />
        <el-table-column label="实测出成率" width="100">
          <template #default="{ row }">{{ row.actual_yield ?? '未实测' }}</template>
        </el-table-column>
        <el-table-column label="备注" prop="note" min-width="180" />
        <el-table-column label="登记人" prop="created_by" width="90" />
      </el-table>

      <el-form v-if="session.isChecker" inline @submit.prevent>
        <el-form-item label="车次"><el-input v-model="accForm.trip_no" style="width: 110px" /></el-form-item>
        <el-form-item label="实到毛重kg"><el-input-number v-model="accForm.received_weight_kg" :min="0" style="width: 130px" /></el-form-item>
        <el-form-item label="实际单价"><el-input-number v-model="accForm.actual_unit_price" :min="0" style="width: 110px" /></el-form-item>
        <el-form-item label="实际等级"><el-input v-model="accForm.actual_grade" style="width: 90px" /></el-form-item>
        <el-form-item label="退货kg"><el-input-number v-model="accForm.returned_weight_kg" :min="0" style="width: 100px" /></el-form-item>
        <el-form-item label="等级拒收kg"><el-input-number v-model="accForm.grade_rejected_weight_kg" :min="0" style="width: 110px" /></el-form-item>
        <el-form-item label="实测出成率"><el-input-number v-model="accForm.actual_yield" :min="0" :max="1" :step="0.01" style="width: 120px" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="accForm.note" style="width: 180px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="saving" @click="addAcceptance">登记验收</el-button></el-form-item>
      </el-form>
      <el-alert v-else type="info" :closable="false" title="验收登记需要验收员角色（checker01）。" />
    </div>

    <div class="page-card" v-if="deviation?.summary">
      <h3>验收汇总</h3>
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="计划毛重">{{ deviation.summary.planned_gross_kg }} kg</el-descriptions-item>
        <el-descriptions-item label="实收">{{ deviation.summary.received_kg }} kg</el-descriptions-item>
        <el-descriptions-item label="短装">{{ deviation.summary.short_kg }} kg</el-descriptions-item>
        <el-descriptions-item label="退货">{{ deviation.summary.returned_kg }} kg</el-descriptions-item>
        <el-descriptions-item label="等级拒收">{{ deviation.summary.grade_rejected_kg }} kg</el-descriptions-item>
        <el-descriptions-item label="未验收">
          {{ deviation.summary.unaccepted_kg }} kg
          <span class="muted" v-if="deviation.summary.unaccepted_note">（{{ deviation.summary.unaccepted_note }}）</span>
        </el-descriptions-item>
        <el-descriptions-item label="实际单价(加权)">{{ deviation.summary.actual_unit_price_avg ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="实测出成率(加权)">{{ deviation.summary.actual_yield_avg ?? '未实测' }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <div class="page-card" v-if="deviation?.available">
      <h3>成本偏差归因（固定顺序：单价 → 收货数量 → 出成率）</h3>
      <el-table :data="deviation.steps" border size="small">
        <el-table-column label="因素" prop="factor" width="110" />
        <el-table-column label="计划值" width="130">
          <template #default="{ row }">{{ row.from ?? row.from_kg }}</template>
        </el-table-column>
        <el-table-column label="实际值" width="130">
          <template #default="{ row }">
            {{ row.to ?? row.to_kg }}
            <el-tag v-if="row.measured === false" size="small" type="info">未实测·按计划值</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="替换后单位成本(元/可用kg)" prop="unit_cost_after" width="200" />
        <el-table-column label="本步贡献(元/可用kg)" width="170">
          <template #default="{ row }">
            <span :style="{ color: row.contribution > 0 ? '#f56c6c' : '#67c23a' }">
              {{ row.contribution > 0 ? '+' : '' }}{{ row.contribution }}
            </span>
          </template>
        </el-table-column>
      </el-table>
      <el-descriptions :column="3" border style="margin-top: 12px">
        <el-descriptions-item label="计划单位成本">{{ deviation.planned.unit_cost }} 元/可用kg</el-descriptions-item>
        <el-descriptions-item label="实际单位成本">{{ deviation.actual.unit_cost }} 元/可用kg</el-descriptions-item>
        <el-descriptions-item label="总差额（=各步贡献之和）">
          <b :style="{ color: deviation.total_deviation > 0 ? '#f56c6c' : '#67c23a' }">
            {{ deviation.total_deviation > 0 ? '+' : '' }}{{ deviation.total_deviation }} 元/可用kg
          </b>
        </el-descriptions-item>
      </el-descriptions>
      <el-alert type="info" :closable="false" style="margin-top: 12px" :title="deviation.note" />
    </div>
    <div class="page-card" v-else-if="deviation">
      <el-alert type="info" :closable="false" :title="deviation.reason || '暂无偏差数据'" />
    </div>

    <el-dialog v-model="correctVisible" title="采用新修订并生成更正" width="520px">
      <el-select v-model="correctQuoteId" placeholder="选择新修订报价" style="width: 100%">
        <el-option v-for="q in newerQuotes" :key="q.id"
          :label="`#${q.id} ${q.source_name} ${q.price_per_unit}元/${q.unit_raw}（第${q.revision}版）`" :value="q.id" />
      </el-select>
      <template #footer>
        <el-button @click="correctVisible = false">取消</el-button>
        <el-button type="primary" :loading="correcting" @click="doCorrect">确认更正</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'
import { session } from '../store'

const route = useRoute()
const router = useRouter()
const detail = ref(null)
const deviation = ref(null)
const saving = ref(false)
const correctVisible = ref(false)
const correctQuoteId = ref(null)
const correcting = ref(false)
const newerQuotes = ref([])

const accForm = reactive({
  trip_no: '', received_weight_kg: 0, actual_unit_price: null, actual_grade: '',
  returned_weight_kg: 0, grade_rejected_weight_kg: 0, actual_yield: null, note: '',
})

async function load() {
  const id = route.params.id
  const [{ data: d }, { data: dev }] = await Promise.all([
    api.get(`/decisions/${id}`),
    api.get(`/decisions/${id}/deviation`),
  ])
  detail.value = d
  deviation.value = dev
}

async function addAcceptance() {
  if (!accForm.trip_no || !accForm.received_weight_kg) {
    ElMessage.warning('车次与实到毛重必填')
    return
  }
  saving.value = true
  try {
    await api.post(`/decisions/${route.params.id}/acceptances`, { ...accForm })
    ElMessage.success('验收已登记')
    accForm.trip_no = ''
    accForm.note = ''
    await load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    saving.value = false
  }
}

async function openCorrect() {
  const { data } = await api.get('/quotes', { params: { product_id: detail.value.product_id } })
  newerQuotes.value = data.filter((q) => q.revision > detail.value.snapshot.terms.quote_revision
    && q.source_name === detail.value.source_name && q.review_status === 'ok' && !q.expired)
  if (!newerQuotes.value.length) {
    ElMessage.warning('当前没有可用的更新修订报价')
    return
  }
  correctVisible.value = true
}

async function doCorrect() {
  correcting.value = true
  try {
    const { data } = await api.post(`/decisions/${route.params.id}/correct`, { new_quote_id: correctQuoteId.value })
    ElMessage.success(`已生成更正依据 #${data.id}（修订 ${data.revision}）`)
    correctVisible.value = false
    router.push({ name: 'decision-detail', params: { id: data.id } })
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    correcting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
h3 { margin: 0 0 12px; font-size: 15px; }
</style>
