// English messages. `satisfies` keeps the structure in sync with zh-CN.ts:
// a missing / extra / wrongly-typed key fails the build.
import type { MessageSchema } from './zh-CN'

const messages = {
  app: {
    title: 'map2model — box an area on the map, get 2D/3D models',
    lang: 'UI language',
  },
} satisfies MessageSchema

export default messages
