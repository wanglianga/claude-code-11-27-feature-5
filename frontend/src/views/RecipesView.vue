<template>
  <div>
    <div class="page-card">
      <el-tabs v-model="tab">
        <el-tab-pane label="菜品与食谱版本" name="recipes">
          <el-form inline>
            <el-form-item label="菜品">
              <el-select v-model="dishId" style="width: 180px" @change="loadRecipes">
                <el-option v-for="d in dishes" :key="d.id" :label="`${d.name}（${d.code}）`" :value="d.id" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button v-if="session.isBuyer" type="primary" @click="openRecipeDialog">登记食谱新版本</el-button>
            </el-form-item>
          </el-form>
          <el-table :data="recipes" border v-loading="loading" row-key="id">
            <el-table-column type="expand">
              <template #default="{ row }">
                <el-table :data="row.items" border size="small" class="inner">
                  <el-table-column label="行号" prop="line_no" width="70" />
                  <el-table-column label="原料" prop="ingredient_name" width="140" />
                  <el-table-column label="净用量" width="120">
                    <template #default="{ row: r }">
                      <span v-if="r.net_qty !== null">{{ r.net_qty }} {{ r.net_unit }}</span>
                      <el-tag v-else size="small" type="danger">缺净用量·不可补齐</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="备注" prop="note" />
                </el-table>
              </template>
            </el-table-column>
            <el-table-column label="版本" prop="revision" width="80" />
            <el-table-column label="餐期" prop="meal_period" width="160" />
            <el-table-column label="份数" prop="servings" width="90" />
            <el-table-column label="生效起" prop="effective_from" width="120" />
            <el-table-column label="生效止" width="120">
              <template #default="{ row }">{{ row.effective_to || '当前生效' }}</template>
            </el-table-column>
            <el-table-column label="来源单据" prop="source_ref" width="140" />
            <el-table-column label="备注" prop="note" />
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="原料语义映射" name="mappings">
          <el-alert type="info" :closable="false" style="margin-bottom: 10px"
            title="映射绑定采购编码、成分编码、等级、过敏原标签与单位换算依据；同一生效时刻两版并存时保留双候选，不按上传时间覆盖。" />
          <el-table :data="mappings" border size="small">
            <el-table-column label="原料" prop="ingredient_name" width="120" />
            <el-table-column label="修订" prop="revision" width="70" />
            <el-table-column label="标准品" prop="product_name" width="100" />
            <el-table-column label="采购编码" prop="purchase_code" width="110" />
            <el-table-column label="成分编码" prop="composition_code" width="120" />
            <el-table-column label="等级" prop="grade" width="70" />
            <el-table-column label="加工状态" prop="processing_status" width="100" />
            <el-table-column label="过敏原" width="120">
              <template #default="{ row }">
                <el-tag v-for="t in row.allergen_tags" :key="t" size="small" style="margin-right: 4px">{{ t }}</el-tag>
                <el-tag v-if="!row.allergen_mapped" size="small" type="warning">过敏原未映射</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="单位换算依据" min-width="180">
              <template #default="{ row }">
                <span v-if="row.conversion" class="mono">{{ JSON.stringify(row.conversion) }}</span>
                <el-tag v-else size="small" type="danger">换算缺失</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="生效区间" width="190">
              <template #default="{ row }">{{ row.effective_from }} ~ {{ row.effective_to || '至今' }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="出成率证据账" name="evidence">
          <el-alert type="info" :closable="false" style="margin-bottom: 10px"
            title="抽样实测 / 历史估计 / 缺失三态分明；估计值不伪装成验收事实，缺失不补默认出成率。" />
          <el-table :data="evidences" border size="small">
            <el-table-column label="标准品" prop="product_name" width="100" />
            <el-table-column label="等级" prop="grade" width="70" />
            <el-table-column label="加工状态" prop="processing_status" width="110" />
            <el-table-column label="证据类型" width="110">
              <template #default="{ row }">
                <el-tag v-if="row.evidence_kind === 'measured'" type="success" size="small">抽样实测</el-tag>
                <el-tag v-else-if="row.evidence_kind === 'estimated'" type="warning" size="small">历史估计</el-tag>
                <el-tag v-else type="info" size="small">缺失</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="采用值" width="100">
              <template #default="{ row }">{{ row.point ?? `${row.lower}~${row.upper}` }}</template>
            </el-table-column>
            <el-table-column label="实测批次" prop="sample_batch" width="150" />
            <el-table-column label="实测日期" prop="measured_at" width="120" />
            <el-table-column label="备注" prop="note" min-width="180" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="recipeDialog" title="登记食谱新版本（版本号自动递增）" width="640px">
      <el-form :model="recipeForm" label-width="92px">
        <el-form-item label="餐期"><el-input v-model="recipeForm.meal_period" style="width: 220px" /></el-form-item>
        <el-form-item label="份数"><el-input-number v-model="recipeForm.servings" :min="1" /></el-form-item>
        <el-form-item label="生效日期"><el-date-picker v-model="recipeForm.effective_from" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="原料行">
          <div v-for="(it, idx) in recipeForm.items" :key="idx" class="line-row">
            <el-input v-model="it.ingredient_name" placeholder="原料名" style="width: 150px" />
            <el-input-number v-model="it.net_qty" :min="0" placeholder="净用量(缺省留空)" style="width: 140px" controls-position="right" />
            <el-input v-model="it.net_unit" placeholder="单位" style="width: 90px" />
            <el-button link type="danger" @click="recipeForm.items.splice(idx, 1)">删除</el-button>
          </div>
          <el-button size="small" @click="recipeForm.items.push({ ingredient_name: '', net_qty: null, net_unit: 'kg' })">+ 加一行</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="recipeDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRecipe">保存版本</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { session } from '../store'

const tab = ref('recipes')
const dishes = ref([])
const dishId = ref(null)
const recipes = ref([])
const mappings = ref([])
const evidences = ref([])
const loading = ref(false)
const recipeDialog = ref(false)
const saving = ref(false)
const recipeForm = reactive({ meal_period: '', servings: 100, effective_from: '', items: [] })

async function loadRecipes() {
  if (!dishId.value) return
  loading.value = true
  try {
    const { data } = await api.get(`/dishes/${dishId.value}/recipe-versions`)
    recipes.value = data
  } finally {
    loading.value = false
  }
}

async function loadMappings() {
  const { data } = await api.get('/ingredient-mappings')
  mappings.value = data
}

async function loadEvidences() {
  const { data } = await api.get('/yield-evidences')
  evidences.value = data
}

function openRecipeDialog() {
  Object.assign(recipeForm, { meal_period: '', servings: 100, effective_from: '', items: [{ ingredient_name: '', net_qty: null, net_unit: 'kg' }] })
  recipeDialog.value = true
}

async function saveRecipe() {
  if (!recipeForm.meal_period || !recipeForm.effective_from) {
    ElMessage.warning('餐期与生效日期必填')
    return
  }
  const items = recipeForm.items
    .filter((i) => i.ingredient_name)
    .map((i) => ({ ingredient_name: i.ingredient_name, net_qty: i.net_qty || null, net_unit: i.net_unit }))
  saving.value = true
  try {
    await api.post(`/dishes/${dishId.value}/recipe-versions`, { ...recipeForm, items })
    ElMessage.success('食谱版本已登记，旧版本已在生效日收口')
    recipeDialog.value = false
    await loadRecipes()
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
    await loadRecipes()
  }
  await Promise.all([loadMappings(), loadEvidences()])
})
</script>

<style scoped>
.inner { margin: 8px 16px; }
.line-row { display: flex; gap: 8px; margin-bottom: 8px; align-items: center; }
</style>
