<script setup lang="ts">
// 地点搜索框(浮在地图左上角):输入地名回车,后端代查 OpenStreetMap,
// 点某条结果让父组件把视角飞过去。
// 列表项用 mousedown 选中:click 的话输入框先失焦、列表先被收起,就点不到了。

import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, formatApiError } from '@/api/client'
import type { PlaceResult } from '@/api/types'

const emit = defineEmits<{ pick: [place: PlaceResult] }>()

const { t } = useI18n()
const q = ref('')
const results = ref<PlaceResult[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

async function search() {
  const word = q.value.trim()
  if (!word || loading.value) return
  loading.value = true
  error.value = null
  results.value = []
  try {
    results.value = await api.geocode(word)
    if (!results.value.length) error.value = t('search.noResults')
  } catch (e) {
    error.value = formatApiError(e)
  } finally {
    loading.value = false
  }
}

function pick(r: PlaceResult) {
  emit('pick', r)
  results.value = [] // 选完把列表收起来
}

// 输入框失焦稍等一下再收列表,给 mousedown 一点反应时间
function onBlur() {
  setTimeout(() => (results.value = []), 150)
}
</script>

<template>
  <div class="map-search">
    <form class="row" @submit.prevent="search">
      <input
        v-model="q"
        type="text"
        :placeholder="$t('search.placeholder')"
        @blur="onBlur"
      />
      <button type="submit" :disabled="loading">{{ loading ? '…' : $t('search.go') }}</button>
    </form>
    <p v-if="error" class="msg">{{ error }}</p>
    <ul v-if="results.length" class="results">
      <li v-for="r in results" :key="r.display_name" @mousedown.prevent="pick(r)">
        <strong>{{ r.name }}</strong>
        <small>{{ r.display_name }}</small>
      </li>
    </ul>
  </div>
</template>
