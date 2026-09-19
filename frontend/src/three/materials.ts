// 各图层的统一材质:白模风格(颜色淡、不反光),和后端导出的 GLB 长一个样。

import * as THREE from 'three'
import { LAYERS } from './layers'

/** 按图层名建材质;GLB 自带材质时可不覆盖,这里主要给"重新着色"用 */
export function makeLayerMaterial(key: string): THREE.MeshStandardMaterial {
  const def = LAYERS.find((l) => l.key === key) ?? LAYERS[0]
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(def.color),
    roughness: 0.9, // 哑光,白模质感
    metalness: 0.0,
    flatShading: false,
    side: THREE.FrontSide,
  })
}

/** 一次性把一组材质占的显存还回去,不还的话切几次页面就卡了 */
export function disposeMaterials(mats: THREE.Material[]): void {
  mats.forEach((m) => m.dispose())
}
