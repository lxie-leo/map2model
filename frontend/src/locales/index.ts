// i18n 入口:实例、语言探测、切换时同步 DOM。
// 注意:测试(vitest)跑在 node 环境里,没有 localStorage/navigator/document,
// 所有碰它们的地方都要兜住——这里不 import 任何 store,store 只能反过来引 i18n。

import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN'
import en from './en'

export type AppLocale = 'zh-CN' | 'en'

const STORAGE_KEY = 'm2m.locale'

/** 首选语言:手动选过的(localStorage)> 浏览器语言(非中文系就英文)> 中文。 */
export function resolveInitialLocale(): AppLocale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'zh-CN' || saved === 'en') return saved
  } catch {
    // node 环境没有 localStorage
  }
  try {
    if (!navigator.language.toLowerCase().startsWith('zh')) return 'en'
  } catch {
    // node 环境没有 navigator
  }
  return 'zh-CN'
}

export const i18n = createI18n({
  legacy: false, // 用 Composition API(useI18n())
  globalInjection: true, // 模板里才能直接写 $t()
  locale: resolveInitialLocale(),
  fallbackLocale: 'zh-CN',
  messages: { 'zh-CN': zhCN, en },
})

/** 切换语言/启动时把 DOM 同步过来:html 的 lang 属性和页面标题跟着走。 */
export function applyLocaleSideEffects() {
  const loc = i18n.global.locale.value
  try {
    document.documentElement.lang = loc
    document.title = i18n.global.t('app.title')
  } catch {
    // node 环境没有 document
  }
}
