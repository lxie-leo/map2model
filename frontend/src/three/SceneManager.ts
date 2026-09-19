// three.js 场景管理器:加载 hub.glb、灯光、相机、图层显隐、渲染循环。
// 一个画布一个实例,组件销毁前必须调 dispose(),不然显存越占越多。

import * as THREE from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { LAYERS, type LayerKey } from './layers'

export class SceneManager {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera: THREE.PerspectiveCamera
  private controls: OrbitControls
  private raf = 0
  private resizeObs: ResizeObserver
  private root: THREE.Object3D | null = null
  private disposed = false
  /** 加载序号:连续换模型时,只认最新一次加载的结果 */
  private loadToken = 0

  constructor(private canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      // 场景又大又高(单位是米),普通算法会远近打架,开对数深度能让远处的楼不闪烁
      logarithmicDepthBuffer: true,
    })
    this.renderer.setClearColor(0x1c2430)

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.5, 20000)

    // 半球光打底 + 平行光造立体感
    const hemi = new THREE.HemisphereLight(0xffffff, 0x666666, 1.1)
    this.scene.add(hemi)
    const sun = new THREE.DirectionalLight(0xffffff, 1.6)
    sun.position.set(-1, 1.6, 0.8) // 西北方向照过来
    this.scene.add(sun)

    this.controls = new OrbitControls(this.camera, canvas)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.08
    this.controls.maxPolarAngle = Math.PI / 2 - 0.02 // 不允许钻到地面以下

    // 画布尺寸跟随容器
    this.resizeObs = new ResizeObserver(() => this.resize())
    this.resizeObs.observe(canvas.parentElement ?? canvas)
    this.resize()

    this.animate()
  }

  /** 加载任务的 hub.glb;url 为空则清空场景 */
  async loadModel(url: string | null): Promise<void> {
    if (this.disposed) return
    // 连续换模型时,先记下这是第几次加载;等文件下载回来时如果已经又换了
    // (序号变了),这份就作废丢弃,不然场景里会叠两个城市模型,旧的还释放不掉
    const token = ++this.loadToken
    this.clearModel()
    if (!url) return
    const gltf = await new GLTFLoader().loadAsync(url)
    if (this.disposed || token !== this.loadToken) {
      // 作废的模型也得把刚解析出来的资源放掉,别白占显存
      gltf.scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh
        if (mesh.isMesh) {
          mesh.geometry.dispose()
          const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
          mats.forEach((m) => m.dispose())
        }
      })
      return
    }
    this.root = gltf.scene
    this.scene.add(this.root)
    this.fitCamera()
  }

  /** 按图层名设置显隐(GLB 节点名 = 图层名) */
  setLayerVisible(key: LayerKey, visible: boolean): void {
    this.root?.traverse((obj) => {
      if (obj.name === key) obj.visible = visible
    })
  }

  /** 俯视 / 透视 两个常用视角 */
  setView(mode: 'perspective' | 'top'): void {
    if (!this.root) return
    const box = new THREE.Box3().setFromObject(this.root)
    const center = box.getCenter(new THREE.Vector3())
    const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1)
    if (mode === 'top') {
      this.camera.position.set(center.x, center.y + radius * 2.2, center.z + 0.01)
    } else {
      this.camera.position.set(
        center.x - radius * 1.4,
        center.y + radius * 1.1,
        center.z + radius * 1.4,
      )
    }
    this.controls.target.copy(center)
    this.controls.update()
  }

  /** 相机对准整个模型(加载完自动调用一次) */
  fitCamera(): void {
    this.setView('perspective')
  }

  private clearModel(): void {
    if (!this.root) return
    this.scene.remove(this.root)
    this.root.traverse((obj) => {
      const mesh = obj as THREE.Mesh
      if (mesh.isMesh) {
        mesh.geometry.dispose()
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
        mats.forEach((m) => m.dispose())
      }
    })
    this.root = null
  }

  private resize(): void {
    const parent = this.canvas.parentElement
    const w = parent?.clientWidth ?? this.canvas.clientWidth
    const h = parent?.clientHeight ?? this.canvas.clientHeight
    if (w === 0 || h === 0) return
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.setSize(w, h, false)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  private animate = (): void => {
    if (this.disposed) return
    this.raf = requestAnimationFrame(this.animate)
    this.controls.update()
    this.renderer.render(this.scene, this.camera)
  }

  dispose(): void {
    this.disposed = true
    cancelAnimationFrame(this.raf)
    this.resizeObs.disconnect()
    this.controls.dispose()
    this.clearModel()
    this.renderer.dispose()
    // 每次进查看页都会新建一个 WebGL 画布,光 dispose 浏览器不会马上收回
    // 显卡资源,攒多了会报"WebGL 上下文太多"然后强杀旧画布;主动松手最稳
    this.renderer.forceContextLoss()
  }
}

/** 图层列表导出给图层面板复用 */
export { LAYERS }
