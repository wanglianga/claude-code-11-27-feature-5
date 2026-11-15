<template>
  <div>
    <div class="page-card">
      <el-form inline>
        <el-form-item label="标准品">
          <el-select v-model="form.product_id" style="width: 140px" @change="onProductChange">
            <el-option v-for="p in products" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="比较口径">
          <el-radio-group v-model="form.need_type">
            <el-radio-button value="gross">毛重数量</el-radio-button>
            <el-radio-button value="net">可用净重</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="需求量(kg)">
          <el-input-number v-model="form.need_quantity" :min="1" :step="10" style="width: 140px" />
        </el-form-item>
        <el-form-item label="等级">
          <el-select v-model="form.grade" clearable placeholder="不限" style="width: 110px">
            <el-option v-for="g in gradeOptions" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="产地">
          <el-select v-model="form.origin" clearable placeholder="不限" style="width: 120px">
            <el-option v-for="o in originOptions" :key="o" :label="o" :value="o" />
          </el-select>
        </el-form-item>
        <el-form-item label="要求到货日">
          <el-date-picker v-model="form.deliverable_by" type="date" value-format="YYYY-MM-DD" style="width: 150px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="runCompare">对比</el-button>
        </el-form-item>
      </el-form>
      <div class="muted" v-if="result">
        筛选条件严格生效（不为补齐报价而取消）；本次有 {{ result.filtered_out_count }} 条报价因不满足筛选条件未参与。
        区间重叠的报价不强制排名；缺出成率实测的报价按原价展示。
      </div>
    </div>

    <div class="page-card" v-if="result">
      <h3>可比报价（{{ convertibleResults.length }}）</h3>
      <el-table :data="convertibleResults" row-key="quote_id" border>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="breakdown">
              <el-descriptions :column="3" size="small" border>
                <el-descriptions-item label="采购件数">{{ row.units }} {{ row.unit_raw || row.unit }}</el-descriptions-item>
                <el-descriptions-item label="净含量合计">{{ row.purchase_kg }} kg</el-descriptions-item>
                <el-descriptions-item label="计费重量">{{ row.freight_weight_kg }} kg</el-descriptions-item>
                <el-descriptions-item label="货值">{{ row.goods_amount }} 元</el-descriptions-item>
                <el-descriptions-item label="税额">{{ row.tax_amount }} 元</el-descriptions-item>
                <el-descriptions-item label="运费">{{ row.freight }} 元（{{ row.freight_desc }}）</el-descriptions-item>
                <el-descriptions-item label="分摊费用">
                  {{ row.alloc_fees }} 元
                  <span v-if="row.alloc_items?.length" class="muted">
                    （<span v-for="it in row.alloc_items" :key="it.name">{{ it.name }} {{ it.amount }} </span>）
                  </span>
                </el-descriptions-item>
                <el-descriptions-item label="总成本">{{ row.total_cost }} 元</el-descriptions-item>
                <el-descriptions-item label="毛重成本">{{ row.cost_per_gross_kg }} 元/kg</el-descriptions-item>
                <el-descriptions-item label="出成率依据" v-if="row.yield_rate">
                  {{ row.yield_rate.lower }} ~ {{ row.yield_rate.upper }}（{{ row.yield_rate.evidence }}）
                </el-descriptions-item>
                <el-descriptions-item label="预计可用范围" v-if="row.expected_usable_range">
                  {{ row.expected_usable_range[0] }} ~ {{ row.expected_usable_range[1] }} kg
                </el-descriptions-item>
                <el-descriptions-item label="保守余量">{{ row.surplus_kg }} kg</el-descriptions-item>
                <el-descriptions-item label="溯源">
                  <el-button link type="primary" @click="$router.push({ name: 'quote-detail', params: { id: row.quote_id } })">
                    查看原始报价与换算依据
                  </el-button>
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="来源" prop="source_name" width="130" />
        <el-table-column label="等级" prop="grade" width="70" />
        <el-table-column label="产地" prop="origin" width="80" />
        <el-table-column label="加工状态" prop="processing_status" width="100" />
        <el-table-column label="交付" width="110">
          <template #default="{ row }">{{ row.delivery_mode }}·{{ row.lead_days === 0 ? '当天' : row.lead_days + '日达' }}</template>
        </el-table-column>
        <el-table-column label="单价" width="110">
          <template #default="{ row }">{{ row.price_per_unit }} 元/{{ row.unit_raw || row.unit }}</template>
        </el-table-column>
        <el-table-column label="件数" prop="units" width="80" />
        <el-table-column label="总成本(元)" prop="total_cost" width="100" />
        <el-table-column label="可用成本区间(元/kg)" min-width="170">
          <template #default="{ row }">
            <span class="mono">[{{ row.cost_per_usable_kg_lower }}, {{ row.cost_per_usable_kg_upper }}]</span>
            <el-tag v-if="row.overlapped" size="small" type="warning" style="margin-left: 6px">区间重叠·不排名次</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="保守余量(kg)" prop="surplus_kg" width="110" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button v-if="session.isBuyer" size="small" type="primary" @click="adopt(row)">采用</el-button>
          </template>
        </el-table-column>
      </el-table>

      <template v-if="unconvertibleResults.length">
        <h3 style="margin-top: 20px">缺出成率实测·按原价展示（不参与排名）</h3>
        <el-table :data="unconvertibleResults" border>
          <el-table-column label="来源" prop="source_name" width="140" />
          <el-table-column label="等级" prop="grade" width="80" />
          <el-table-column label="加工状态" prop="processing_status" width="110" />
          <el-table-column label="原价">
            <template #default="{ row }">{{ row.original_price_text }}</template>
          </el-table-column>
          <el-table-column label="说明" prop="note" />
        </el-table>
      </template>
    </div>

    <div class="page-card" v-if="result && result.excluded.length">
      <h3>不可采用报价（{{ result.excluded.length }}）</h3>
      <el-table :data="result.excluded" border>
        <el-table-column label="来源" prop="source_name" width="140" />
        <el-table-column label="等级" width="80">
          <template #default="{ row }">{{ row.grade || '—' }}</template>
        </el-table-column>
        <el-table-column label="单价" width="110">
          <template #default="{ row }">{{ row.price_per_unit }} 元/{{ row.unit_raw || row.unit }}</template>
        </el-table-column>
        <el-table-column label="不可采用原因">
          <template #default="{ row }">
            <el-tag v-for="r in row.reasons" :key="r" size="small" type="danger" effect="plain" style="margin-right: 6px">{{ r }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click="$router.push({ name: 'quote-detail', params: { id: row.quote_id } })">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="adoptDialog" title="采用报价生成采购依据" width="480px">
      <el-alert type="warning" :closable="false" style="margin-bottom: 12px"
        title="采用前将重新校验：报价未过期、满足起订量、税费字段齐全、条款未被新修订替换。采购依据生成后只读。" />
      <el-descriptions :column="1" border size="small" v-if="adoptTarget">
        <el-descriptions-item label="来源">{{ adoptTarget.source_name }}</el-descriptions-item>
        <el-descriptions-item label="单价">{{ adoptTarget.price_per_unit }} 元/{{ adoptTarget.unit_raw }}</el-descriptions-item>
        <el-descriptions-item label="需求">{{ form.need_type === 'net' ? '可用净重' : '毛重数量' }} {{ form.need_quantity }} kg</el-descriptions-item>
        <el-descriptions-item label="采购件数">{{ adoptTarget.units }} {{ adoptTarget.unit_raw }}</el-descriptions-item>
        <el-descriptions-item label="总成本">{{ adoptTarget.total_cost }} 元</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="adoptDialog = false">取消</el-button>
        <el-button type="primary" :loading="adopting" @click="confirmAdopt">确认采用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'
import { session } from '../store'

const router = useRouter()
const products = ref([])
const quotes = ref([])
const loading = ref(false)
const result = ref(null)
const form = reactive({
  product_id: null, need_type: 'net', need_quantity: 100,
  grade: null, origin: null, deliverable_by: null,
})
const adoptDialog = ref(false)
const adoptTarget = ref(null)
const adopting = ref(false)

const gradeOptions = computed(() => [...new Set(quotes.value.map((q) => q.grade).filter(Boolean))])
const originOptions = computed(() => [...new Set(quotes.value.map((q) => q.origin).filter(Boolean))])
const convertibleResults = computed(() => (result.value?.results || []).filter((r) => r.convertible))
const unconvertibleResults = computed(() => (result.value?.results || []).filter((r) => !r.convertible))

onMounted(async () => {
  const { data } = await api.get('/products')
  products.value = data
  if (data.length) {
    form.product_id = data[0].id
    await onProductChange()
  }
})

async function onProductChange() {
  const { data } = await api.get('/quotes', { params: { product_id: form.product_id } })
  quotes.value = data
  result.value = null
}

async function runCompare() {
  loading.value = true
  try {
    const { data } = await api.post('/compare', { ...form })
    result.value = data
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    loading.value = false
  }
}

function adopt(row) {
  adoptTarget.value = row
  adoptDialog.value = true
}

async function confirmAdopt() {
  adopting.value = true
  try {
    const { data } = await api.post('/decisions', {
      quote_id: adoptTarget.value.quote_id,
      need_type: form.need_type,
      need_quantity: form.need_quantity,
    })
    ElMessage.success('已生成只读采购依据')
    adoptDialog.value = false
    router.push({ name: 'decision-detail', params: { id: data.id } })
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    adopting.value = false
  }
}
</script>

<style scoped>
h3 { margin: 0 0 12px; font-size: 15px; }
.breakdown { padding: 8px 24px; background: #fafafa; }
</style>
