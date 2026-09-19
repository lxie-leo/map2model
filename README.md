<div align="center">

# map2model

**在地图上框一块地，生成它的 2D 彩色地图和 3D 白模，再导出成 17 种格式，拿去 Blender / AutoCAD / QGIS / Cesium 里用。**

![Vue 3](https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![MapLibre](https://img.shields.io/badge/MapLibre%20GL-3D7FB2?logo=maplibre&logoColor=white)
![three.js](https://img.shields.io/badge/three.js-000000?logo=threedotjs&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/Node-20%2B-339933?logo=nodedotjs&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)
[![CI](https://github.com/lxie-leo/map2model/actions/workflows/ci.yml/badge.svg)](https://github.com/lxie-leo/map2model/actions/workflows/ci.yml)

</div>

---

[English](README_EN.md) | 简体中文

## 演示

<video src="assets/demo.mp4" controls width="720"></video>

## 这是什么

一个跑在自己电脑上的网页工具。你在地图上按住左键拖一个框，后台去把这块地的 OpenStreetMap 数据和地形高程抓回来，一分钟后你就能：

- 看 **2D 彩色地图** —— 建筑、道路、铁路、水系、绿地分颜色画好，看着跟纸质地图似的
- 看 **3D 白模** —— 楼房按真实高度立起来，地面有起伏，六个图层想开就开想关就关
- **导出成 17 种格式**，丢进你顺手的软件接着干活

数据全部来自免费公开渠道（OSM + AWS 地形瓦片），不用注册账号，不用申请密钥。

## 生成过程

```
 框选范围 ──► 抓 OSM 数据 ──► 抓地形高程 ──► 解析换算 ──► 建模型 ──► 出成果
    │                                                    │
    │                                       ┌────────────┼────────────┐
    │                                       ▼            ▼            ▼
    └── 进度实时推到网页                hub.glb     preview.geojson   meta.json
                                              │            │
                                        3D 各格式      2D/GIS 各格式
```

一共五步，每一步进行到哪了网页上都能看到，中途随时可以取消。

## 有哪些功能

- 在地图上直接拖框选地，面积实时显示，框太大（超过 25 km²）会拦下来不让选
- 六类要素统一配色：SVG / PDF 是矢量的，放大多少倍都不糊；PNG / DXF / GeoJSON 各取所需
- 楼房按 `height` 拉伸，没填高度的按楼层数估算；道路铁路按等级给宽度；地形照着 AWS 高程数据做出起伏
- 3D 格式六种（GLB / OBJ / STL / USDZ / FBX / DAE），2D 四种（SVG / PDF / PNG / DXF），GIS 七种（GeoJSON / GPKG / SHP / KML / KMZ / CityJSON / 3D Tiles）
- 「上」的方向提前替你转好了：GLB / USDZ 的上是 Y（Blender、three.js 的习惯），OBJ / STL / CityJSON 的上是 Z（CAD 的习惯），3D Tiles 自带经纬度定位，扔进 Cesium 就落在原地
- 网络不好不至于白等：抓数据换着镜像挨个试；地形实在抓不到就改用平地，提醒你一声，任务不中断
- 进度用 WebSocket 推，断网自动重连，实在连不上就换个法子接着收
- 图层的名字一路保留到底：GLB 里的节点就叫 TERRAIN、BUILDING 这些，进了 Blender 图层面板直接对得上

## 快速开始

### 先装好这些

| 软件 | 版本 | 干嘛用 |
| --- | --- | --- |
| Python | ≥ 3.11（推荐 3.12 / 3.13） | 跑后端 |
| Node.js | ≥ 20 | 跑前端 |
| Blender（可选） | 近期版本都行 | 只有 FBX / DAE 两种格式用得上 |

### 开跑

Windows 下两条命令：

```powershell
# 1. 起后端（第一次会自动建虚拟环境、装依赖）
powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1

# 2. 另开一个窗口，起前端
powershell -ExecutionPolicy Bypass -File scripts\dev-frontend.ps1
```

打开 **http://127.0.0.1:5173**，拖个框，点「生成」。

> 嫌开两个窗口麻烦就跑 `scripts\run_all.ps1`；拿不准环境缺什么，先跑 `scripts\check_env.ps1` 查一遍。

### 用 Docker 跑（可选）

```bash
docker compose up -d --build
# 打开 http://localhost:8080
```

生成的文件都存在 `./data` 里，容器删了重建，东西还在。

## 能导出哪些格式

| 分组 | 格式 | 状态 | 拿来干嘛 |
| --- | --- | :-: | --- |
| 3D | **GLB** | ✅ | 首选。Blender、three.js 直接打开，图层名都在 |
| 3D | OBJ | ✅ | 建模软件通用，上是 Z |
| 3D | STL | ✅ | 3D 打印，单位毫米 |
| 3D | USDZ | ✅ | 发到 iPhone，用文件 App 就能 AR 预览 |
| 3D | FBX | ⚠️ 要装 Blender | Unity / Unreal / Maya |
| 3D | DAE | ⚠️ 要装 Blender | 老牌 3D 交换格式 |
| 2D | SVG | ✅ | 矢量地图，网页、设计软件里随便放大 |
| 2D | PDF | ✅ | 打印 |
| 2D | PNG | ✅ | 图片快照 |
| 2D | DXF | ✅ | AutoCAD，图层按 `M2M_*` 分好 |
| GIS | GeoJSON | ✅ | 最通用的矢量格式，谁都能读 |
| GIS | GPKG | ✅ | 一个文件装多层数据，QGIS / ArcGIS 直接开 |
| GIS | SHP | ✅ | 传统 GIS 格式，按图层打包成 zip |
| GIS | KML / KMZ | ✅ | Google Earth，楼房是立起来的 |
| GIS | CityJSON | ✅ | 城市模型标准（2.0 版） |
| GIS | 3D Tiles | ✅ | Cesium 加载大场景用，自带地球定位 |

✅ = 装完就能用；⚠️ = 电脑上得装 Blender（程序会自己去 `C:\Program Files\Blender Foundation\` 底下找）。

哪种格式能不能用，界面上的按钮会照实显示：能用的亮着，不能用的灰着，鼠标放上去告诉你缺什么。

## 图层和颜色

2D 和 3D 六个图层叫一样的名字、用一样的颜色：

| 图层 | 颜色 | 说明 |
| --- | --- | --- |
| Terrain | `#c8c3ba` | 地面（有高程数据时带起伏） |
| Green | `#b7d6a8` | 公园、草地、树林 |
| Water | `#a8cfe8` | 河流、湖泊 |
| Building | `#ded7cb` | 楼房，按真实或估算的高度立起来 |
| Road | `#a8a8a8` | 道路，主路次路宽度不一样 |
| Railway | `#6b6f73` | 铁路 |

## 配置

不改任何配置就能跑。想调的话，改这些环境变量（都带 `M2M_` 前缀）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `M2M_DATA_DIR` | `data` | 存数据库和生成文件的地方 |
| `M2M_OVERPASS_ENDPOINTS` | 内置一排镜像 | 逗号隔开，从前往后挨个试 |
| `M2M_MAX_BBOX_AREA_KM2` | `25` | 一次最多框多大 |
| `M2M_MAX_BUILDINGS` | `20000` | 一次最多处理多少栋楼 |
| `M2M_TASK_CONCURRENCY` | `2` | 同时跑几个任务 |
| `M2M_BLENDER_PATH` | `auto` | Blender 装在哪；`auto` = 自己去找 |

想加料可以装可选依赖：`pip install -e ".[gis,usd]"` 让 GPKG 走 geopandas、USDZ 走官方库；`pip install -e ".[dev]"` 装开发和测试工具。不装也照样跑，界面上照实显示哪些可用。

## 常见问题

**Q：npm 装依赖老是报错，文件还损坏？**
有些 Windows 电脑上 npm 解包会被杀毒软件搅和（报 `TAR_ENTRY_ERROR`，文件变成零字节）。这个项目统一用 pnpm 就没事：`corepack pnpm install`。

**Q：生成一次要多久？**
时间主要花在从 Overpass 拉数据：0.3 km² 的城区大概一分钟，地盘越大越慢。同一块地第二次生成直接用上次存的，几乎秒出。

**Q：怎么我的地形是平的？**
有的网络访问不了 AWS 的地形瓦片，这时程序会自动改用平地，并在任务的警告里写明原因。挂个代理或换个网络就有了。

**Q：FBX / DAE 按钮是灰的？**
这两种格式要借 Blender 帮忙转一手。[装个 Blender](https://www.blender.org/download/)（免费），重启后端就亮了。其它 15 种格式不受影响。

**Q：模型进了 Blender 是躺着的？**
这不是坏了。GLB 里「上」是 Y 方向，Blender 打开 GLB 时会自动摆正；如果你导入的是 OBJ（上是 Z）发现躺着，手动转一下就好。

## 开发

```powershell
# 后端测试（53 个用例）
cd backend; .venv\Scripts\python.exe -m pytest -q

# 前端类型检查 + 单元测试
cd frontend; corepack pnpm typecheck; corepack pnpm test

# 前端打包
cd frontend; corepack pnpm build
```

用 Python 3.14 的话注意：`mapbox-earcut` 还没出支持 3.14 的安装包，程序会自动换用自己写的切三角形代码，结果一样，就是慢一点。Docker 镜像固定用 3.12，没这个问题。

## 目录结构

```
map2model/
├── backend/
│   ├── app/
│   │   ├── api/            # 接口：tasks / exports / system / ws
│   │   ├── core/           # 任务调度、事件广播、错误定义
│   │   ├── services/
│   │   │   ├── overpass.py     # 抓 OSM 数据（换镜像 + 缓存）
│   │   │   ├── osm_parse.py    # 解析要素（补高度、滤隧道、拼圈）
│   │   │   ├── projection.py   # 坐标换算
│   │   │   ├── terrain.py      # 抓地形、缩成高程网格
│   │   │   ├── pipeline.py     # 五步主流程
│   │   │   ├── mesh/           # 生成地形/楼房/道路的三角形网格
│   │   │   ├── vector/         # 2D 绘制数据
│   │   │   └── export/         # 17 种格式的导出代码
│   │   └── ...
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/            # 调后端接口
│       ├── stores/         # 任务 / 导出 / 设置的数据
│       ├── composables/    # WS/SSE 收实时进度（自动重连）
│       ├── three/          # 3D 场景
│       ├── components/     # 地图框选 / 任务卡片 / 查看器
│       └── views/          # 主页 / 任务列表 / 查看页
├── scripts/                # Windows 启动脚本
└── docker-compose.yml
```

## 许可

代码按 [MIT](LICENSE) 开源：随便用、随便改、商用也行，把 LICENSE 文件带着就好。

提醒一句：这个工具生成的地图和模型来自 OpenStreetMap 的数据（ODbL 协议）。自己看、自己用没事；如果要公开发布或商业分发生成的成果，记得带上 OSM 的署名（一句 "© OpenStreetMap contributors" 即可）。
