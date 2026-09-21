// 时间格式化(任务卡片、下载列表都从这儿拿)。
// 格式固定不跟界面语言走:纯数字不存在翻译问题,还能避免 en-US 把日期
// 重排成 "9/21/2026, 14:30" 这种和中文界面对不上的写法。

/** 补两位:1 → 01 */
function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** 完整时间,如 2026/9/21 14:30:05 */
export function fmtDateTime(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 短时间(下载列表一屏好多条,不带年份),如 09-21 14:30 */
export function fmtShortDateTime(iso: string): string {
  const d = new Date(iso)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
