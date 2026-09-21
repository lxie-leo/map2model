// 中文文案(默认语言、最全的一份)。
// en.ts 用 satisfies 对齐这份的结构:少 key/多 key/类型不对都会编译报错。

const messages = {
  app: {
    title: 'map2model — 地图框选生成 2D/3D 模型',
    lang: '界面语言',
  },
}

export default messages

/** 整棵文案树的形状,en.ts 按它对齐 */
export type MessageSchema = typeof messages
