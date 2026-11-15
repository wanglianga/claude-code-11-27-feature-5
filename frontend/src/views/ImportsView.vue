<template>
  <div>
    <div class="page-card">
      <h3>导入报价文件（CSV / JSON / 市场快照）</h3>
      <el-upload :auto-upload="false" :limit="1" :on-change="onFile" :file-list="fileList" accept=".csv,.json">
        <el-button type="primary">选择文件</el-button>
        <template #tip><div class="muted">支持随题 CSV、JSON 及结构化市场快照；同文件重复导入幂等，中断可按原文件续接。</div></template>
      </el-upload>
      <el-button style="margin-top: 12px" type="success" :disabled="!file" :loading="uploading" @click="upload">开始导入</el-button>
      <el-alert v-if="uploadResult" style="margin-top: 12px" :closable="false" type="success"
        :title="`批次 #${uploadResult.id} 导入${uploadResult.status === 'completed' ? '完成' : '部分完成'}：成功 ${uploadResult.ok_rows} 行，坏行 ${uploadResult.bad_rows} 行`" />
    </div>

    <div class="page-card">
      <h3>导入批次</h3>
      <el-table :data="batches" border v-loading="loading">
        <el-table-column label="批次" prop="id" width="70" />
        <el-table-column label="文件名" prop="filename" min-width="180" />
        <el-table-column label="类型" prop="kind" width="80" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'completed' ? 'success' : 'warning'">
              {{ row.status === 'completed' ? '完成' : row.status === 'partial' ? '部分(可续接)' : row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="成功/坏行" width="100">
          <template #default="{ row }">{{ row.ok_rows }} / {{ row.bad_rows }}</template>
        </el-table-column>
        <el-table-column label="解析修订" prop="revision" width="90" />
        <el-table-column label="来源批次" prop="parent_batch_id" width="90">
          <template #default="{ row }">{{ row.parent_batch_id || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260">
          <template #default="{ row }">
            <el-button size="small" @click="showDetail(row)">明细</el-button>
            <el-button size="small" :disabled="row.status === 'completed'" @click="resume(row)">续接</el-button>
            <el-button size="small" type="warning" plain @click="openReparse(row)">重解析试算</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="detailVisible" :title="`批次 #${detail?.id} 明细（坏行单列，不悄悄丢失）`" width="760px">
      <el-table :data="detail?.rows || []" border size="small" max-height="420">
        <el-table-column label="行号" prop="row_no" width="70" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'ok' ? 'success' : 'danger'">{{ row.status === 'ok' ? '成功' : '坏行' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="错误原因" prop="error" min-width="180" />
        <el-table-column label="原始行" min-width="240">
          <template #default="{ row }"><span class="mono" style="font-size: 11px">{{ JSON.stringify(row.raw) }}</span></template>
        </el-table-column>
        <el-table-column label="报价" width="80">
          <template #default="{ row }">
            <el-button v-if="row.quote_id" link type="primary" @click="$router.push({ name: 'quote-detail', params: { id: row.quote_id } })">#{{ row.quote_id }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="reparseVisible" :title="`批次 #${reparseTarget?.id} 重解析试算（生成新修订，旧依据不动）`" width="640px">
      <el-form label-width="110px">
        <el-form-item label="列名映射表">
          <el-input v-model="reparseMapping" type="textarea" :rows="8" class="mono" />
        </el-form-item>
        <el-form-item label="单位表">
          <el-input v-model="reparseUnits" type="textarea" :rows="4" class="mono" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reparseVisible = false">取消</el-button>
        <el-button type="primary" :loading="reparsing" @click="doReparse">生成新修订试算</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const batches = ref([])
const loading = ref(false)
const file = ref(null)
const fileList = ref([])
const uploading = ref(false)
const uploadResult = ref(null)
const detailVisible = ref(false)
const detail = ref(null)
const reparseVisible = ref(false)
const reparseTarget = ref(null)
const reparseMapping = ref('')
const reparseUnits = ref('')
const reparsing = ref(false)

function onFile(f) {
  file.value = f.raw
  fileList.value = [f]
}

async function upload() {
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    const { data } = await api.post('/imports', fd)
    uploadResult.value = data
    ElMessage.success('导入完成')
    await load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    uploading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/imports')
    batches.value = data
  } finally {
    loading.value = false
  }
}

async function showDetail(row) {
  const { data } = await api.get(`/imports/${row.id}`)
  detail.value = data
  detailVisible.value = true
}

async function resume(row) {
  try {
    const { data } = await api.post(`/imports/${row.id}/resume`)
    ElMessage.success(`续接完成：成功 ${data.ok_rows} 行，坏行 ${data.bad_rows} 行`)
    await load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  }
}

async function openReparse(row) {
  reparseTarget.value = row
  const { data } = await api.get('/imports/defaults')
  reparseMapping.value = JSON.stringify(data.column_mapping, null, 2)
  reparseUnits.value = JSON.stringify(data.unit_table, null, 2)
  reparseVisible.value = true
}

async function doReparse() {
  reparsing.value = true
  try {
    const payload = {
      column_mapping: JSON.parse(reparseMapping.value),
      unit_table: JSON.parse(reparseUnits.value),
    }
    const { data } = await api.post(`/imports/${reparseTarget.value.id}/reparse`, payload)
    ElMessage.success(`已生成修订 ${data.revision} 批次 #${data.id}（试算，不影响已选采购依据）`)
    reparseVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage)
  } finally {
    reparsing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
h3 { margin: 0 0 12px; font-size: 15px; }
</style>
