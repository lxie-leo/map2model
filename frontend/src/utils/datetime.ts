// 时间格式化:跟界面语言走(任务卡片、下载列表都从这儿拿),
// 免得各组件自己 toLocaleString('zh-CN') 把语言写死。

import { i18n } from '@/locales'

/** 完整时间(任务卡片、悬停提示用),如 2026/9/21 14:30:05 */
export function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString(i18n.global.locale.value, { hour12: false })
}

/** 短时间(下载列表一屏好多条,不带年份) */
export function fmtShortDateTime(iso: string): string {
  return new Date(iso).toLocaleString(i18n.global.locale.value, {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
