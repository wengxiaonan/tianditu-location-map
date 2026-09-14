# tianditu-location-map

用**天地图**（国家地理信息公共服务平台）在线底图编绘论文**区位图 / 研究区位置图**的技能包。

一条命令产出可直接用于学位论文的双面板区位图：全国幅（含南海断续线十段线、研究区红框）
＋ 研究区幅（省/市县界、样点标注），两幅等大图框，各带经纬度刻度、比例尺、指北针。

## 为什么需要它

论文区位图常被评审挑三类问题，本技能逐条对着解决：

| 评审常挑的问题 | 做法 |
|---|---|
| 「区位图要图审 / 审图号是多少」 | 不用境外底图；边界用自有矢量叠加；出图后跑合规自检 |
| 「南海诸岛 / 十段线不全」 | 全国幅强制覆盖到 3.4°N 以内，十段线作为独立境界要素叠加，出图后核对**恰好 10 段** |
| 「图上路网干扰主题」 | 默认底图组合 `ter`（地形晕渲）+ `cva`（中文注记），实测不含路网 |

## 安装

把本目录放进你的技能目录即可（例如 `~/.dsh/skills/tianditu-location-map/`）。

依赖：

```bash
pip install Pillow numpy shapely      # 必需
pip install opencv-python             # 可选：仅「擦除底图自带小字」用到
```

## 密钥

天地图服务需要 tk，在 <https://console.tianditu.com.cn/api/key> 免费申请。

```bash
export TDT_TK="你的密钥"        # Linux/macOS
$env:TDT_TK = "你的密钥"        # PowerShell
```

也可以写在配置的 `"tk"` 字段里。**瓦片已缓存时不需要密钥**。

## 快速开始

```bash
# 1) 复制样例配置
cp assets/example-config-hainan.json my-figure.json

# 2) 准备你自己的边界数据（GeoJSON），放到 ./data/ 并改 boundary.file
#    注意：全国幅的边界数据必须含完整的南海断续线要素

# 3) 出图
python scripts/build_locator.py --config my-figure.json

# 4) 自检（合规 + 成品）
python scripts/check_map.py --config my-figure.json --image 图1.2-区位图.png

# 5) 查地名的经纬度
python scripts/build_locator.py --config my-figure.json --geocode "海南省陵水黎族自治县南平农场"
```

## 目录结构

```
├── SKILL.md                       技能主文件：工作流、全字段配置表、常见改动对照表
├── scripts/
│   ├── tianditu.py                核心库：投影换算 / 瓦片缓存拼接 / 静态图 / 地理编码 / 十段线识别
│   ├── build_locator.py           出图主程序（读 JSON 配置）
│   └── check_map.py               出图前后自检（带结论分级）
├── references/
│   ├── layers.md                  图层清单、路网判断、缩放级别选择、密钥
│   ├── compliance.md              地图合规：审图号、十段线、边界来源、自检清单
│   └── pitfalls.md                实际踩过的坑（改代码前必读）
└── assets/
    └── example-config-hainan.json 完整实战配置样例
```

## ⚠️ 合规提示（重要）

**天地图是「服务」，不是「标准地图」。**

国家地理信息公共服务平台（天地图）提供的是在线底图服务；而
[标准地图服务系统](http://bzdt.ch.mnr.gov.cn) 提供的是经审核、自带**审图号**的标准样图。
两者不是一回事。

从天地图瓦片自行编绘出来的图，其边界画法是否与标准样图完全一致、**是否需要另行送审，
没有可以一句话说死的权威依据**——取决于省份、用途与所在单位口径。
使用本技能产出的图，**请务必与导师 / 学院确认合规口径**，必要时向省级自然资源主管部门咨询。

本技能不判断某张图是否需要送审，不提供审图号，不分发行政区划数据，也不生成边界数据。

详见 [`references/compliance.md`](references/compliance.md)。

## 实测

配置样例（双面板、全国幅 z=5、研究区幅 z=8）产出 **3219×1509** 的 PNG，
自检脚本对十段线、红框、样点、底图层级的检查全部通过。

## 许可

本仓库为技能包与代码；**不含**任何行政区划边界数据、天地图瓦片或受版权材料。
使用者需自行申请天地图密钥并自备边界数据。
