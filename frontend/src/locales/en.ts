// English messages. `satisfies` keeps the structure in sync with zh-CN.ts:
// a missing / extra / wrongly-typed key fails the build.
import type { MessageSchema } from './zh-CN'

const messages = {
  app: {
    title: 'map2model — box an area on the map, get 2D/3D models',
    lang: 'UI language',
  },

  task: {
    stage: {
      FETCH_OVERPASS: 'Fetching OSM data',
      FETCH_TERRAIN: 'Fetching terrain elevation',
      PARSE_VECTOR: 'Parsing vector features',
      BUILD_MESH: 'Building 3D meshes',
      WRITE_HUB: 'Writing model files',
    },
    status: {
      QUEUED: 'Queued',
      RUNNING: 'Running',
      COMPLETED: 'Completed',
      FAILED: 'Failed',
      CANCELLED: 'Cancelled',
    },
    idLabel: 'Task {id}',
    view: 'View',
    cancel: 'Cancel',
    remove: 'Delete',
    cardTitle: 'Click to show the selected area on the map',
  },

  export_: {
    status: {
      QUEUED: 'Queued',
      RUNNING: 'Exporting',
      COMPLETED: 'Done',
      FAILED: 'Failed',
      CANCELLED: 'Cancelled',
    },
    dialogTitle: 'Export model',
    submitting: 'Submitting…',
    disabledTip: 'Backend package missing, or Blender not detected',
    footerTip: 'Only layers enabled in the layer panel are exported; exports run in the background — see the Downloads tab for progress and files',
    empty: 'No exports yet — pick a format from the Export button at the top right',
    download: 'Download',
    retry: 'Retry',
    retrying: 'Retrying…',
    downloadNotice: 'Export started — check the Downloads tab for progress',
    goDownloads: 'Open downloads',
    exportButton: 'Export',
  },

  format: {
    glb: 'glTF binary · universal 3D, recommended',
    obj: 'Wavefront OBJ · standard in modeling tools',
    stl: 'STL · 3D printing',
    fbx: 'FBX · needs Blender to convert',
    dae: 'Collada DAE · needs Blender to convert',
    usdz: 'USDZ · Apple AR quick look',
    dxf: 'AutoCAD DXF · CAD layers',
    svg: 'SVG · vector map, scales infinitely',
    pdf: 'PDF · print-ready vector map',
    png: 'PNG · bitmap snapshot',
    geojson: 'GeoJSON · most portable vector format',
    gpkg: 'GeoPackage · single-file database, opens in QGIS',
    shp: 'Shapefile · classic GIS, zipped',
    kml: 'KML · Google Earth',
    kmz: 'KMZ · zipped KML',
    cityjson: 'CityJSON · 3D city standard',
    '3dtiles': '3D Tiles · streamed by Cesium',
  },

  bbox: {
    drawingHint: 'Hold the left mouse button and drag a rectangle on the map (right-click to cancel)',
    emptyHint: 'Click the "Box" button below, then drag a rectangle on the map',
    west: 'West lon W',
    east: 'East lon E',
    south: 'South lat S',
    north: 'North lat N',
    area: 'Area {area} km²',
    tooLarge: ' — exceeds the {max} km² limit, pick a smaller area',
    drawingButton: 'Boxing… (drag on the map)',
    draw: 'Box area',
    create: 'Generate 2D / 3D models',
    redraw: 'Redraw box',
  },

  option: {
    buildings: 'Buildings',
    roads: 'Roads',
    railways: 'Railways',
    water: 'Water',
    green: 'Green',
    terrain: 'Terrain relief',
  },

  layer: {
    TERRAIN: 'Terrain',
    GREEN: 'Green',
    WATER: 'Water',
    BUILDING: 'Buildings',
    ROAD: 'Roads',
    RAILWAY: 'Railways',
  },

  viewer: {
    back: '← Back to map',
    wait3d: 'The 3D model is available once the task completes',
    wait2d: 'The 2D map is available once the task completes',
    loading: 'Loading task…',
  },

  tab: {
    model3d: '3D Model',
    map2d: '2D Map',
    exports: 'Downloads',
  },

  layerPanel: {
    title: 'Layers',
    view: 'View',
    perspective: 'Perspective',
    top: 'Top-down',
  },

  home: {
    panel: '☰ Panel',
    openSide: 'Show sidebar',
    closeSide: 'Hide sidebar',
  },

  conn: {
    ws: 'Live channel connected',
    sse: 'Live channel: fallback mode',
    offline: 'Connecting live channel…',
  },
} satisfies MessageSchema

export default messages
