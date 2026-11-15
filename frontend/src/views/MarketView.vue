<template>
  <div>
    <div class="page-card">
      <el-form inline>
        <el-form-item label="标准品">
          <el-select v-model="form.product_id" style="width: 140px">
            <el-option v-for="p in products" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="等级">
          <el-select v-model="form.grade" clearable placeholder="不限" style="width: 110px">
            <el-option v-for="g in ['一级', '二级', '特级']" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="加工状态">
          <el-select v-model="form.processing_status" clearable placeholder="不限" style="width: 130px">
            <el-option v-for="s in ['净菜', '带泥毛菜', '带根毛菜']" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD"
            start-placeholder="开始" end-placeholder="结束" style="width: 240px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="load">统计</el-button>
        </el-form-item>
      </el-form>
      <div class="muted">只在同等级、同状态、同时间范围内统计；以独立卖方为单位先归并再取中位数，转载不增加权重。</div>
    </div>

    <div class="page-card" v-if="result">
      <el-row :gutter="16">
        <el-col :span="6">
          <el-statistic title="参考中位数(元/kg)" :value="result.reference_median ?? '—'" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="独立卖方数" :value="result.seller_count" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="有效样本数(已去转载)" :value="result.sample_count" />
        </el-col>
      </el-row>
      <el-table :data="result.seller_medians" border size="small" style="margin-top: 16px">
        <el-table-column label="独立卖方" prop="seller" />
        <el-table-column label="卖方内中位数(元/kg)" prop="median" />
        <el-table-column label="样本数" prop="samples" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const products = ref([])
const result = ref(null)
const loading = ref(false)
const dateRange = ref(null)
const form = reactive({ product_id: null, grade: null, processing_status: null })

async function load() {
  loading.value = true
  try {
    const params = { ...form }
    if (dateRange.value?.[0]) params.date_from = dateRange.value[0]
    if (dateRange.value?.[1]) params.date_to = dateRange.value[1]
    const { data } = await api.get('/market/reference', { params })
    result.value = data
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  const { data } = await api.get('/products')
  products.value = data
  if (data.length) {
    form.product_id = data[0].id
    await load()
  }
})
</script>
