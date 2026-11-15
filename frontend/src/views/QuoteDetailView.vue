<template>
  <div v-if="quote">
    <div class="page-card">
      <el-page-header @back="$router.back()" :title="`报价 #${quote.id} 溯源`" />
      <el-descriptions :column="3" border style="margin-top: 16px">
        <el-descriptions-item label="来源">{{ quote.source_name }}（{{ quote.source_type }}）</el-descriptions-item>
        <el-descriptions-item label="报价编号">{{ quote.external_id || '—' }} · 第 {{ quote.revision }} 版</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag v-if="quote.review_status === 'pending'" type="warning" size="small">待核：{{ (quote.pending_reasons || []).join('；') }}</el-tag>
          <el-tag v-else-if="quote.expired" type="danger" size="small" effect="plain">已过期</el-tag>
          <el-tag v-else type="success" size="small" effect="plain">有效</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="商品名">{{ quote.raw_product_name }}</el-descriptions-item>
        <el-descriptions-item label="标准品">{{ quote.product_name || '未映射' }}</el-descriptions-item>
        <el-descriptions-item label="映射状态">{{ quote.mapping_status === 'mapped' ? '已审核映射' : '待审核' }}</el-descriptions-item>
        <el-descriptions-item label="等级">{{ quote.grade || '缺' }}</el-descriptions-item>
        <el-descriptions-item label="产地">{{ quote.origin || '—' }}</el-descriptions-item>
        <el-descriptions-item label="加工状态">{{ quote.processing_status || '—' }}</el-descriptions-item>
        <el-descriptions-item label="包装">{{ quote.package_desc || '—' }}</el-descriptions-item>
        <el-descriptions-item label="单件净重/毛重">{{ quote.net_weight_per_unit_kg || '—' }} / {{ quote.gross_weight_per_unit_kg || '—' }} kg</el-descriptions-item>
        <el-descriptions-item label="单位">{{ quote.unit_raw || quote.unit || '缺' }}</el-descriptions-item>
        <el-descriptions-item label="单价">{{ quote.price_per_unit }} 元/{{ quote.unit_raw || quote.unit }}</el-descriptions-item>
        <el-descriptions-item label="税费">
          <span v-if="quote.tax_included === true">已含在单价中</span>
          <span v-else-if="quote.tax_included === false">未含，税率 {{ quote.tax_rate }}</span>
          <el-tag v-else size="small" type="warning">未声明，待补</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="零价依据" v-if="quote.price_per_unit === 0">{{ quote.zero_price_basis || '缺（不可采用）' }}</el-descriptions-item>
        <el-descriptions-item label="有效期">{{ quote.valid_from || '—' }} ~ {{ quote.valid_to || '—' }}</el-descriptions-item>
        <el-descriptions-item label="起订量">{{ quote.moq_quantity ? quote.moq_quantity + (quote.moq_unit || '') : '—' }}</el-descriptions-item>
        <el-descriptions-item label="交付">{{ quote.delivery_mode }} · {{ quote.lead_days === 0 ? '当天' : (quote.lead_days || 0) + ' 日达' }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <div class="page-card">
      <h3>费用规则</h3>
      <pre class="json">{{ JSON.stringify(quote.fee_rules || { 说明: '未声明费用规则' }, null, 2) }}</pre>
    </div>

    <div class="page-card">
      <h3>原始行（导入批次 #{{ quote.batch_id }} · 第 {{ quote.row_no }} 行 · 解析修订 {{ quote.parse_revision }}）</h3>
      <pre class="json">{{ JSON.stringify(quote.raw, null, 2) }}</pre>
    </div>

    <div class="page-card" v-if="quote.revision_chain?.length">
      <h3>同号换值修订链（旧版保留）</h3>
      <el-table :data="quote.revision_chain" border size="small">
        <el-table-column label="报价ID" prop="id" width="90" />
        <el-table-column label="版本" prop="revision" width="70" />
        <el-table-column label="单价" prop="price_per_unit" width="90" />
        <el-table-column label="有效期至" prop="valid_to" width="110" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_latest ? 'success' : 'info'" effect="plain">{{ row.is_latest ? '最新' : '已被替换' }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="page-card" v-if="quote.decisions?.length">
      <h3>被采用的采购依据</h3>
      <el-table :data="quote.decisions" border size="small">
        <el-table-column label="依据ID" prop="id" width="90" />
        <el-table-column label="需求" width="160">
          <template #default="{ row }">{{ row.need_type === 'net' ? '可用净重' : '毛重数量' }} {{ row.need_quantity }} kg</template>
        </el-table-column>
        <el-table-column label="件数" prop="units" width="80" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '有效' : '已被更正' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" prop="created_at" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click="$router.push({ name: 'decision-detail', params: { id: row.id } })">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import api from '../api'

const route = useRoute()
const quote = ref(null)

onMounted(async () => {
  const { data } = await api.get(`/quotes/${route.params.id}`)
  quote.value = data
})
</script>

<style scoped>
h3 { margin: 0 0 12px; font-size: 15px; }
.json { background: #f6f8fa; padding: 12px; border-radius: 4px; font-size: 12px; overflow: auto; max-height: 320px; }
</style>
