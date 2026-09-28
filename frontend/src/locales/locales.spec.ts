// 枚举文案全覆盖测试:后端每加一个枚举值,双语 locale 忘配文案时这里直接红。
// 由来:接入 Overture 时加了 FETCH_OVERTURE 阶段,locale 漏了一条,
// 进度条就按 tEnum 的兜底显示英文枚举名(acfea70 补的),这类遗漏用测试堵死。
import { describe, expect, it } from 'vitest'
import type { TaskStage, TaskStatus } from '@/api/types'
import { i18n } from '@/locales'

// as const + 类型标注双向卡死:漏一个值、多一个值、拼错都过不了编译
const STAGES = [
  'FETCH_OVERPASS',
  'FETCH_OVERTURE',
  'FETCH_TERRAIN',
  'PARSE_VECTOR',
  'BUILD_MESH',
  'WRITE_HUB',
] as const satisfies readonly TaskStage[]
type _StagesExhaustive = Exclude<TaskStage, (typeof STAGES)[number]> extends never ? true : never

const STATUSES = ['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'] as const
type _StatusesExhaustive = Exclude<TaskStatus, (typeof STATUSES)[number]> extends never ? true : never

describe('枚举文案全覆盖', () => {
  for (const loc of ['zh-CN', 'en'] as const) {
    it(`${loc}: 六个任务阶段都有文案(不许兜底成枚举名)`, () => {
      i18n.global.locale.value = loc
      for (const s of STAGES) {
        expect(i18n.global.te(`task.stage.${s}`), `task.stage.${s} 在 ${loc} 缺文案`).toBe(true)
      }
    })

    it(`${loc}: 五个任务状态都有文案`, () => {
      i18n.global.locale.value = loc
      for (const s of STATUSES) {
        expect(i18n.global.te(`task.status.${s}`), `task.status.${s} 在 ${loc} 缺文案`).toBe(true)
      }
    })
  }
})
