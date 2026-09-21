// 中文文案(默认语言、最全的一份)。
// en.ts 用 satisfies 对齐这份的结构:少 key/多 key/类型不对都会编译报错。
// 约定:枚举类 key 直接用后端原值(大写),渲染时缺 key 就回显枚举值本身。

const messages = {
  app: {
    title: 'map2model — 地图框选生成 2D/3D 模型',
    lang: '界面语言',
  },

  // ---- 任务(卡片 + 查看页共用) ----
  task: {
    stage: {
      FETCH_OVERPASS: '拉取 OSM 数据',
      FETCH_TERRAIN: '拉取地形高程',
      PARSE_VECTOR: '解析矢量要素',
      BUILD_MESH: '构建三维网格',
      WRITE_HUB: '写出模型文件',
    },
    status: {
      QUEUED: '排队中',
      RUNNING: '运行中',
      COMPLETED: '已完成',
      FAILED: '失败',
      CANCELLED: '已取消',
    },
    idLabel: '任务 {id}',
    view: '查看',
    cancel: '取消',
    remove: '删除',
    cardTitle: '点击在地图上显示框选范围',
  },

  // ---- 导出 ----
  export_: {
    status: {
      QUEUED: '排队中',
      RUNNING: '导出中',
      COMPLETED: '完成',
      FAILED: '失败',
      CANCELLED: '取消',
    },
    dialogTitle: '导出模型',
    submitting: '提交中…',
    disabledTip: '后端未安装对应组件或未检测到 Blender',
    footerTip: '只导出图层面板里勾选的图层;导出在后台进行,可在"下载"页看进度和拿文件',
    empty: '还没有导出记录,点右上"导出"按钮选格式',
    download: '下载',
    retry: '重试',
    retrying: '重试中…',
    downloadNotice: '正在下载,请进入下载页面查看进度',
    goDownloads: '进入下载页',
    exportButton: '导出',
  },

  // 17 种格式的一句话说明(键 = 后端格式名)
  format: {
    glb: 'glTF 二进制 · 通用 3D,推荐',
    obj: 'Wavefront OBJ · 建模软件通用',
    stl: 'STL · 3D 打印',
    fbx: 'FBX · 需要 Blender 转换',
    dae: 'Collada DAE · 需要 Blender 转换',
    usdz: 'USDZ · Apple AR 快速预览',
    dxf: 'AutoCAD DXF · CAD 图层',
    svg: 'SVG · 矢量地图,可无限放大',
    pdf: 'PDF · 打印版矢量地图',
    png: 'PNG · 位图快照',
    geojson: 'GeoJSON · 最通用的矢量交换',
    gpkg: 'GeoPackage · 单文件数据库,QGIS 直开',
    shp: 'Shapefile · 传统 GIS,打包 zip',
    kml: 'KML · Google Earth',
    kmz: 'KMZ · KML 压缩包',
    cityjson: 'CityJSON · 城市 3D 标准',
    '3dtiles': '3D Tiles · Cesium 流式加载',
  },

  // ---- 框选面板 ----
  bbox: {
    drawingHint: '在地图上按住左键拖出矩形(右键取消)',
    emptyHint: '点下方「框选」按钮,再到地图上拖出矩形',
    west: '西经 W',
    east: '东经 E',
    south: '南纬 S',
    north: '北纬 N',
    area: '面积 {area} km²',
    tooLarge: ' — 超过上限 {max} km²,请缩小范围',
    drawingButton: '框选中…(在地图上拖动)',
    draw: '框选',
    create: '生成 2D / 3D 模型',
    redraw: '重新框选',
  },

  // 图层开关(键 = TaskOptions 字段名)
  option: {
    buildings: '建筑',
    roads: '道路',
    railways: '铁路',
    water: '水体',
    green: '绿地',
    terrain: '地形起伏',
  },

  // 图层名(键 = GLB 节点名,和后端图层一致)
  layer: {
    TERRAIN: '地形',
    GREEN: '绿地',
    WATER: '水体',
    BUILDING: '建筑',
    ROAD: '道路',
    RAILWAY: '铁路',
  },

  // ---- 查看页 ----
  viewer: {
    back: '← 返回地图',
    wait3d: '任务完成后可查看 3D 模型',
    wait2d: '任务完成后可查看 2D 制图',
    loading: '加载任务中…',
  },

  // 查看页三个标签
  tab: {
    model3d: '3D 模型',
    map2d: '2D 制图',
    exports: '下载',
  },

  // 图层/视角浮层
  layerPanel: {
    title: '图层',
    view: '视角',
    perspective: '透视',
    top: '俯视',
  },

  // ---- 主页 ----
  home: {
    panel: '☰ 面板',
    openSide: '展开侧栏',
    closeSide: '收起侧栏',
  },

  // 实时通道连接状态
  conn: {
    ws: '实时通道已连接',
    sse: '实时通道:备用模式',
    offline: '正在连接实时通道…',
  },
}

export default messages

/** 整棵文案树的形状,en.ts 按它对齐 */
export type MessageSchema = typeof messages
