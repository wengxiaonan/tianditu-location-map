---
name: tianditu-location-map
description: 用天地图（国家地理信息公共服务平台）在线底图编绘论文区位图／研究区位置图：双面板（全国＋研究区）、等大图框、南海断续线十段线、研究区红框、样点标注、比例尺、指北针、经纬度刻度；含 WMTS 瓦片拼接、地理编码取点、底图无路网选取、地图合规自查。Use when the user asks 画区位图、研究区位置图、区位图重做、用天地图做底图、把地图换成天地图的、study area map / location map with Tianditu basemap、地图审图号与地图合规、论文地图被评委要求改画法，或提到 ter/cva/vec 底图、十段线/南海断续线、WMTS 瓦片拼接、天地图密钥。
---

# 用天地图编绘论文区位图

## 一句话

**先用天地图瓦片拼出精确范围的底图 → 叠自有矢量边界 → 套图框／刻度／比例尺／指北针 → 拼成两幅等大的区位图。**
全流程一条命令，参数全在 JSON 配置里。

## 这个技能解决什么

论文里的区位图常被评审挑三类问题，本技能逐条对着解决：

| 评审常挑的问题 | 本技能的做法 |
|---|---|
| 「区位图要图审／审图号是多少」 | 不用境外底图；边界用自有矢量叠加；出图后跑合规自检（见 `references/compliance.md`） |
| 「南海诸岛／十段线不全」 | 全国幅强制覆盖到 3.4°N 以内，并把十段线作为独立境界要素叠加，出图后核对**恰好 10 段** |
| 「图上路网干扰主题」 | 默认底图组合 `ter`（地形晕渲）+ `cva`（中文注记），实测不含路网 |

## 何时用 / 何时不用

**用**：要出一张带地理底图的区位图／研究区位置图；要把已有区位图重做；要把百度/谷歌底图换成合规的天地图；要在一张图上同时给出全国区位与省域细节。

**不用**：纯统计图表（用 matplotlib 类技能）；不需要地理底图的示意图（用绘图/示意图类技能）；需要专业 GIS 分析（用 GIS 类技能）。

## 依赖

```bash
pip install Pillow numpy shapely      # 必需
pip install opencv-python             # 可选：仅"擦除底图自带小字"用到，缺了会退化处理
```

## 密钥

天地图服务需要 tk，在 <https://console.tianditu.com.cn/api/key> 申请。

```powershell
$env:TDT_TK = "你的密钥"        # 推荐：放环境变量，不写进代码
```

也可以写在配置的 `"tk"` 字段里。**瓦片已缓存时不需要密钥**（脚本只在真正要下载时才要求）。

## 快速开始

```bash
# 1) 复制样例配置，改 boundary.file 与 out 路径
cp assets/example-config-hainan.json my-figure.json

# 2) 出图
py -3 scripts/build_locator.py --config my-figure.json

# 3) 自检（合规 + 成品）
py -3 scripts/check_map.py --config my-figure.json --image 图1.2-区位图.png

# 4) 只要查一个地名的经纬度
py -3 scripts/build_locator.py --config my-figure.json --geocode "海南省陵水黎族自治县南平农场"
```

`assets/example-config-hainan.json` 是一个完整的实战样例（双面板·等大图框·十段线·样点标注），
把 `boundary.file` 换成你自己的边界数据即可出图。

## 工作流

1. **定幅面与层级**。全国幅用 `bbox [73, 3.4, 136, 54]` + `zoom 5`（必须覆盖南海，见合规）；
   省域幅用 `"bbox": "auto"` + `zoom 8`。层级选择见 `references/layers.md`。
2. **备边界数据**。国界／省界／市县界各一个 GeoJSON，明确来源。全国幅必须含**完整十段线**要素。
3. **取点位**。用 `--geocode` 查经纬度（关键词带「省+市县」前缀），把结果写进 `points`。
   **不要凭印象填坐标**；查不到就在图注里说明来源。
4. **调版式**。靠 `fit_aspect` + `layout.panel_height` 把两幅图框调成等大；
   比例尺／指北针／标题位置按下面的参数表调。
5. **自检与交付**。跑 `check_map.py`，再人工确认合规与图注（脚本会明确标出哪些必须人工看）。

## 配置字段

### 顶层

| 字段 | 说明 |
|---|---|
| `out` | 输出 PNG 路径 |
| `tk` | 天地图密钥（留空读 `TDT_TK`） |
| `cache_dir` | 瓦片缓存目录，默认 `.tdt_cache` |
| `font_cn` | 中文字体路径，默认自动找 `simhei.ttf` |
| `basemap` | 默认图层组合，建议 `["ter","cva"]` |
| `layout.panel_height` | 每幅地图的像素高（两幅等高即"等大图框"），1300 约对应 A4 页面 300+ dpi |
| `layout.gap` / `layout.top` | 两幅间距 / 顶部留白 |
| `panels` | 面板数组，按顺序从左到右 |

### 每个 panel

| 字段 | 说明 |
|---|---|
| `title` / `title_size` / `title_corner` | 图幅标题（如「（a）中国」）字号与位置 `left`/`right` |
| `bbox` | `[lon0,lat0,lon1,lat1]`，或 `"auto"` 由边界自动定 |
| `bbox_pad` | auto 时的外扩比例，默认 0.10 |
| `zoom` | 瓦片层级 |
| `fit_aspect` | 目标宽高比；**两幅给同一个值即可等大** |
| `layers` | 覆盖顶层 `basemap` |
| `lat_ticks` / `lon_ticks` / `tick_side` | 刻度值与刻度放哪侧（`left`/`right`） |
| `north` | 是否画指北针（默认右上角） |
| `boundary` | 见下 |
| `redbox` / `redbox_width` | 研究区红框 `[lon0,lat0,lon1,lat1]` |
| `center_label` | 图内居中大字：`{text,size,fill,stroke}` |
| `side_label` | 贴在红框下方的小字（如红色「海南省」）：`{text,size,fill,dy}` |
| `points` | 样点：`[{name,lon,lat}]`，自动画红点+白底标签 |
| `point_font` | 样点标签字号 |
| `erase` | 擦除底图自带小字：`[{bbox:[…], radius:5}]` |
| `scalebar` | 见下 |

### `boundary`

| 字段 | 说明 |
|---|---|
| `file` | GeoJSON 路径 |
| `name_field` | 取名称的属性字段，默认 `name` |
| `line_names` | 哪些名称视为「线要素」，默认 `["境界线"]` |
| `union_exclude` | **不参与并集与自动取景**的要素名（如 `["三沙市"]`） |
| `nation_width` | 并集外轮廓线宽（国界/省界），0 表示不画 |
| `prov_width` | 逐要素内轮廓线宽（省界/市县界） |
| `min_area` | 并集轮廓的最小面积阈值，用于滤掉碎岛，默认 0 |
| `line_width` | 境界线（十段线）线宽 |

### `scalebar`

| 字段 | 说明 |
|---|---|
| `ticks` | 刻度值，如 `[0,25,50,75]` |
| `corner` | `left` 或 `right` |
| `inset` | **距图框留白**（字高倍数）。用右下角时务必给，否则会压框，建议 `1.4` |
| `fs_ratio` / `thick` / `pad` / `boxh` / `labdy` / `kmdx` | 字号比例／条高／内边距／框高／标签下移／km 偏移，微调用 |

## 常见改动怎么做

| 想要的效果 | 怎么改 |
|---|---|
| 两幅图框一样大 | 两幅给**相同的 `fit_aspect`**，并让 `layout.panel_height` 统一控制高度 |
| 换底图（去掉路网） | `basemap` 用 `["ter","cva"]`；不要用 `vec`（z≥10 有路网）或 `cta`（含路名） |
| 研究区被南海诸岛撑大 | 在 `boundary` 里加 `"union_exclude": ["三沙市"]` |
| 比例尺压住右下框 | 给 `scalebar.inset`（如 `1.4`） |
| 底图自带的小字和自加标注重复 | 用 `erase` 指定经纬度框擦掉 |
| 图太大（嵌入 Word 后文档膨胀） | 降低 `layout.panel_height` 到约 800（≈300 dpi） |
| 某些刻度不显示 | 刻度画在图框内才显示，超出范围的值会被自动跳过，检查 `bbox` 是否覆盖该刻度 |

## 合规红线（务必读 `references/compliance.md`）

1. **天地图是「服务」，不是「标准地图」**。自行编绘的图是否需另行送审，**没有一句话能说死的权威依据**——
   必须与导师／学院确认，必要时咨询省级自然资源主管部门。本技能不替使用者下这个结论。
2. **十段线必须完整且恰好 10 段**，全国幅必须完整显示南海诸岛。老数据里常缺，出图后必须核对。
3. **边界只能来自矢量数据**，不得手绘、平滑、挪动。
4. **不用境外底图服务**（其边界画法与我国标准不一致）。
5. 图注必须写明底图来源、边界来源、点位定位方式，以及**"图中点位为示意位置，不作界址依据"**。

## 文件结构

```
tianditu-location-map/
├── SKILL.md                      ← 本文件
├── scripts/
│   ├── tianditu.py               ← 核心库：投影换算／瓦片缓存拼接／静态图／地理编码／边界读取／十段线识别
│   ├── build_locator.py          ← 出图主程序（读 JSON 配置）
│   └── check_map.py              ← 出图前后自检
├── assets/
│   └── example-config-hainan.json ← 实战配置样例（可直接复现论文图1.2）
└── references/
    ├── layers.md                 ← 图层清单、路网判断、缩放级别选择、密钥
    ├── compliance.md             ← 地图合规：审图号、十段线、边界来源、自检清单
    └── pitfalls.md               ← 13 个实际踩过的坑（改代码前必读）
```

## 已知限制

- 字体尺寸按**各幅自身像素宽**推算（`tick_font_div`，默认宽度/42），两幅像素尺寸差很多时
  `title_size` 需分别调——这不是 bug，是刻意留的微调口。
- `warm_ratio()` 判断路网是启发式，**只能同区域不同图层横向比较**，不能当绝对阈值。
- 拼版是栅格合成（PIL），不是 GIS 排版；图框之外的排版（图题、图注）请在 Word 里做。
- 不生成矢量输出（PDF/SVG）。
- 不判断某张图是否需要送审，也不提供审图号。
