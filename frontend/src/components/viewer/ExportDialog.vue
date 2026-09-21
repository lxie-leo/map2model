<script setup lang="ts">
// 导出对话框:按 3D / 2D / GIS 分组列出全部格式,后端不支持的一律禁用置灰。

import { computed, onMounted, ref } from 'vue'
import { api, formatApiError } from '@/api/client'
import { useSettingsStore } from '@/stores/settings'
import { useExportsStore } from '@/stores/exports'
import { ensureSubscribed } from '@/composables/useTaskEvents'
import { tEnum } from '@/locales'

const props = defineProps<{ taskId: string; layers?: string[] }>()
const emit = defineEmits<{ close: []; done: [] }>()

const settings = useSettingsStore()
const exportsStore = useExportsStore()
const submitting = ref<string | null>(null)
const error = ref<string | null>(null)

const groups = computed(() => {
  const caps = settings.capabilities
  if (!caps) return []
  return Object.entries(caps.groups).map(([group, formats]) => ({
    group,
    formats: formats.map((f) => ({
      key: f,
      enabled: caps.formats[f] ?? false,
    })),
  }))
})

onMounted(() => {
  void settings.loadCapabilities().catch((e) => (error.value = formatApiError(e)))
})

async function run(format: string) {
  submitting.value = format
  error.value = null
  try {
    const job = await api.createExport(props.taskId, format, props.layers)
    exportsStore.add(job)
    ensureSubscribed() // SSE 模式下给这个任务补开事件流收导出进度
    emit('done') // 先告诉父页面弹"正在下载"的提示,再收起对话框
    emit('close')
  } catch (e) {
    error.value = formatApiError(e)
  } finally {
    submitting.value = null
  }
}
</script>

<template>
  <div class="dialog-mask" @click.self="emit('close')">
    <div class="dialog">
      <header>
        <h2>{{ $t('export_.dialogTitle') }}</h2>
        <button class="btn" @click="emit('close')">✕</button>
      </header>

      <p v-if="error" class="error">{{ error }}</p>

      <section v-for="g in groups" :key="g.group">
        <h3>{{ g.group }}</h3>
        <div class="fmt-grid">
          <button
            v-for="f in g.formats"
            :key="f.key"
            class="fmt"
            :disabled="!f.enabled || submitting !== null"
            :title="f.enabled ? '' : $t('export_.disabledTip')"
            @click="run(f.key)"
          >
            <strong>{{ f.key }}</strong>
            <small>{{ tEnum(`format.${f.key}`) }}</small>
            <span v-if="submitting === f.key" class="busy">{{ $t('export_.submitting') }}</span>
          </button>
        </div>
      </section>

      <footer>
        <span class="tip">{{ $t('export_.footerTip') }}</span>
      </footer>
    </div>
  </div>
</template>
