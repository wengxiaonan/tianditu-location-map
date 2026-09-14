# -*- coding: utf-8 -*-
"""
tianditu.py —— 天地图取图与坐标换算核心库

用途：为「用天地图底图编绘论文区位图」提供可复用底座。
只依赖标准库 + Pillow；边界绘制需要 shapely。

天地图服务（均为公开的「国家地理信息公共服务平台」服务，使用需申请 tk 密钥）：
  · WMTS 瓦片： http://t{0..7}.tianditu.gov.cn/{layer}_w/wmts?...      （_w=Web Mercator，_c=经纬度）
  · 静态图  ： http://api.tianditu.gov.cn/staticimage?center=&width=&height=&zoom=&layers=&tk=
  · 地理编码： http://api.tianditu.gov.cn/geocoder?ds={"keyWord":"..."}&tk=

⚠️ 合规提示：天地图是「服务」，不是标准地图服务系统的样图。
   用它编绘并公开发表的地图是否需另行送审，请先读 references/compliance.md。
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request

from PIL import Image

TILE = 256
UA = {'User-Agent': 'Mozilla/5.0'}

# ---------------------------------------------------------------- 图层名录
# 「不含道路」是本技能默认取向：论文区位图上的路网常被评审视为与主题无关，
# 且路网注记（G98 之类）噪声大。实测暖色像素占比见 references/layers.md。
LAYERS = {
    'vec': '矢量底图（z>=10 起出现明显路网，慎用）',
    'cva': '矢量注记（中文地名注记；实测不含路网）',
    'img': '影像底图（卫星影像）',
    'cia': '影像注记（英文注记）',
    'ter': '地形晕渲（纯地形，无道路）',
    'cta': '矢量注记（含道路注记/路网，勿用于「无路网」要求）',
    'ibo': '境界（国界、省界、争议区界线）',
}
# 默认底图组合：地形晕渲 + 中文注记 → 有地形层次、无路网
DEFAULT_BASEMAP = ('ter', 'cva')


def tk_from_env_or(value: str | None = None, required: bool = True) -> str:
    """
    取得天地图 tk：参数 > 环境变量 TDT_TK。
    required=False 时允许为空——瓦片已全部命中缓存的情况下无需密钥。
    """
    tk = value or os.environ.get('TDT_TK') or ''
    if not tk and required:
        raise SystemExit('缺少天地图 tk：请设置环境变量 TDT_TK，或在配置文件中写 "tk"。\n'
                         '申请地址 https://console.tianditu.com.cn/api/key')
    return tk


# ---------------------------------------------------------------- 投影换算
def lon2x(lon: float, z: int) -> float:
    """经度 → Web Mercator 全局像素 X。"""
    return (lon + 180.0) / 360.0 * (TILE * 2 ** z)


def lat2y(lat: float, z: int) -> float:
    """纬度 → Web Mercator 全局像素 Y。"""
    r = math.radians(lat)
    return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * (TILE * 2 ** z)


def bbox_px(bbox, z: int):
    """(lon0,lat0,lon1,lat1) → 该范围在 z 级下的全局像素框 (X0,Y0,X1,Y1)。"""
    lon0, lat0, lon1, lat1 = bbox
    return lon2x(lon0, z), lat2y(lat1, z), lon2x(lon1, z), lat2y(lat0, z)


def bbox_size_px(bbox, z: int):
    X0, Y0, X1, Y1 = bbox_px(bbox, z)
    return abs(X1 - X0), abs(Y1 - Y0)


def fit_lat_span(lon0, lon1, lat0, lat1, z: int, aspect: float, iters: int = 240):
    """
    在保持经度范围不变的前提下，上下对称微调纬度范围，
    使 (宽:高) 逼近目标 aspect。用于「两个图框等大」。
    返回调整后的 (lat0, lat1)。
    """
    cy = (lat0 + lat1) / 2.0
    for _ in range(iters):
        Wd, Hd = bbox_size_px((lon0, lat0, lon1, lat1), z)
        if Hd == 0 or abs(Wd / Hd - aspect) < 0.002:
            break
        dlat = ((Hd - Wd / aspect) / 2.0) * (360.0 / (TILE * 2 ** z)) * math.cos(math.radians(cy))
        lat0 += dlat
        lat1 -= dlat
    return lat0, lat1


# ---------------------------------------------------------------- 瓦片下载
class TileCache:
    def __init__(self, cache_dir: str, tk: str, retries: int = 3, timeout: int = 30):
        self.dir = cache_dir
        self.tk = tk
        self.retries = retries
        self.timeout = timeout
        os.makedirs(cache_dir, exist_ok=True)
        self.fetched = 0
        self.failed = 0

    def path(self, layer: str, z: int, x: int, y: int) -> str:
        return os.path.join(self.dir, '%s_%d_%d_%d.png' % (layer, z, x, y))

    def get(self, layer: str, z: int, x: int, y: int):
        p = self.path(layer, z, x, y)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return p
        if not self.tk:
            raise SystemExit('瓦片缓存未命中，且未提供天地图 tk：'
                             '请设置环境变量 TDT_TK，或把已下载的瓦片放进 cache_dir。')
        url = ('http://t%d.tianditu.gov.cn/%s_w/wmts?SERVICE=WMTS&REQUEST=GetTile'
               '&VERSION=1.0.0&LAYER=%s&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles'
               '&TILEMATRIX=%d&TILEROW=%d&TILECOL=%d&tk=%s'
               % (x % 8, layer, layer, z, y, x, self.tk))
        for k in range(self.retries):
            try:
                b = urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=self.timeout).read()
                with open(p, 'wb') as fh:
                    fh.write(b)
                self.fetched += 1
                return p
            except Exception:
                if k == self.retries - 1:
                    self.failed += 1
                    return None
                time.sleep(0.6 * (k + 1))
        return None

    def stitch(self, bbox, z: int, layers=DEFAULT_BASEMAP) -> Image.Image:
        """
        拼接 bbox 范围内的瓦片，按 layers 顺序叠加（先底图后注记）。
        返回已按 bbox 精确裁切的 RGBA 图像（背景补白，避免透明）。
        """
        X0, Y0, X1, Y1 = bbox_px(bbox, z)
        tx0, tx1 = int(X0 // TILE), int((X1 - 1e-9) // TILE)
        ty0, ty1 = int(Y0 // TILE), int((Y1 - 1e-9) // TILE)
        W, H = (tx1 - tx0 + 1) * TILE, (ty1 - ty0 + 1) * TILE
        base = Image.new('RGBA', (W, H), (255, 255, 255, 255))
        canvas = base
        for layer in layers:
            lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            for ty in range(ty0, ty1 + 1):
                for tx in range(tx0, tx1 + 1):
                    p = self.get(layer, z, tx, ty)
                    if p:
                        lay.paste(Image.open(p).convert('RGBA'),
                                  ((tx - tx0) * TILE, (ty - ty0) * TILE))
            canvas = Image.alpha_composite(canvas, lay)
        box = (int(round(X0 - tx0 * TILE)), int(round(Y0 - ty0 * TILE)),
               int(round(X1 - tx0 * TILE)), int(round(Y1 - ty0 * TILE)))
        out = canvas.crop(box)
        # 再补一层白底，保证无透明通道
        return Image.alpha_composite(Image.new('RGBA', out.size, (255, 255, 255, 255)), out)

    def make_mapper(self, bbox, z: int, offset=(0, 0)):
        """返回 lon/lat → 图内像素 的映射函数（可用于在图上叠加矢量）。"""
        ox, oy = offset
        X0, Y0, _, _ = bbox_px(bbox, z)
        def f(lon, lat):
            return lon2x(lon, z) - X0 + ox, lat2y(lat, z) - Y0 + oy
        return f


# ---------------------------------------------------------------- 静态图 API
def static_image(center, width, height, zoom, layers=('ter', 'cva'),
                 tk=None, out=None, retries=3):
    """
    天地图静态图 API。⚠️ 实测最大 1024×1024，超出会被服务端截断/报错，
    大幅面出图请改用 TileCache.stitch()。
    """
    tk = tk_from_env_or(tk)
    if width > 1024 or height > 1024:
        raise ValueError('静态图 API 上限 1024×1024，请改用 TileCache.stitch()')
    q = {'center': '%s,%s' % (center[0], center[1]), 'width': width, 'height': height,
         'zoom': zoom, 'layers': ','.join(layers), 'tk': tk}
    url = 'http://api.tianditu.gov.cn/staticimage?' + urllib.parse.urlencode(q)
    last = None
    for k in range(retries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
            if out:
                with open(out, 'wb') as fh:
                    fh.write(b)
                return out
            import io
            return Image.open(io.BytesIO(b)).convert('RGB')
        except Exception as e:
            last = e
            time.sleep(0.8 * (k + 1))
    raise RuntimeError('静态图请求失败: %s' % last)


# ---------------------------------------------------------------- 地理编码
def geocode(keyword: str, tk=None, retries=4, sleep=1.3):
    """
    天地图地理编码。⚠️ 两点经验：
      1) keyWord 需带「省+市县」前缀才有高分（如「海南省陵水黎族自治县南平农场」）；
      2) 连续调用会触发限流（HTTP 429），故内置退避重试。
    返回 dict：{'lon':…, 'lat':…, 'score':…, 'level':…, 'raw':…}；失败返回 None。
    """
    tk = tk_from_env_or(tk)
    ds = json.dumps({'keyWord': keyword}, ensure_ascii=False)
    url = 'http://api.tianditu.gov.cn/geocoder?' + urllib.parse.urlencode({'ds': ds, 'tk': tk})
    for k in range(retries):
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=30).read().decode('utf-8')
            j = json.loads(raw)
            loc = (j.get('location') or {})
            if 'lon' not in loc or 'lat' not in loc:
                return None
            return {'lon': float(loc['lon']), 'lat': float(loc['lat']),
                    'score': j.get('score'), 'level': j.get('level'), 'raw': raw}
        except Exception:
            time.sleep(sleep * (k + 1))
    return None


# ---------------------------------------------------------------- 边界数据
def load_geojson(path: str):
    """读 GeoJSON，返回 (要素列表, crs 名称或 None)。"""
    with open(path, encoding='utf-8') as fh:
        gj = json.load(fh)
    return gj.get('features', []), (gj.get('crs') or {}).get('properties', {}).get('name')


def split_features(features, line_names=('境界线',), name_field='name'):
    """
    按 name 字段把要素分成 (面要素, 线要素)。
    注意：不同来源的「境界线」字段名不一（name / 类型 / TYPE），必要时用 line_field 指定。
    """
    polys, lines, names = [], [], []
    for f in features:
        nm = str((f.get('properties') or {}).get(name_field, ''))
        names.append(nm)
        geom = f.get('geometry') or {}
        t = geom.get('type', '')
        if nm in line_names or t in ('LineString', 'MultiLineString'):
            lines.append(f)
        else:
            polys.append(f)
    return polys, lines, names


def count_line_segments(features):
    """统计要素集合里的线段总数（用于核对「十段线」是否 10 段）。"""
    n = 0
    for f in features:
        g = (f.get('geometry') or {})
        t, c = g.get('type'), g.get('coordinates') or []
        if t == 'LineString':
            n += 1
        elif t == 'MultiLineString':
            n += len(c)
        elif t == 'GeometryCollection':
            n += count_line_segments([{'geometry': x} for x in (g.get('geometries') or [])])
    return n


def feature_bbox(f):
    """要素的经纬度包围盒 (lon0,lat0,lon1,lat1)；无坐标返回 None。"""
    xs, ys = [], []

    def walk(c):
        if isinstance(c, (list, tuple)):
            if len(c) >= 2 and all(isinstance(v, (int, float)) for v in c[:2]):
                xs.append(c[0]); ys.append(c[1])
            else:
                for x in c:
                    walk(x)
    walk((f.get('geometry') or {}).get('coordinates') or [])
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def ten_dash_features(features, name_field='name', line_names=('境界线',),
                      region=(105.0, 0.0, 126.0, 26.0), south_limit=8.0):
    """
    从境界线要素里识别「南海断续线（十段线）」。判据（按优先级）：

      1) 要素包围盒整体落在南海海域框 region 内；
      2) 其中**向南延伸最低**（min_lat < south_limit）的那一条即十段线。
         实测经验：同一份数据里的其它南海境界要素（琼州海峡、闽粤海域、
         浙闽海域等）都停在 20°N 以北，只有十段线下探到 3.4°N；
      3) 若没有要素满足 2)，退化为取经度跨度最大的一条并给出提示。

    返回 (选中的要素列表, 南海框内候选数, 全部境界线要素数)。
    """
    in_region, n_all = [], 0
    for f in features:
        nm = str((f.get('properties') or {}).get(name_field, ''))
        geom = f.get('geometry') or {}
        if nm not in tuple(line_names) and geom.get('type') not in ('LineString', 'MultiLineString'):
            continue
        n_all += 1
        bb = feature_bbox(f)
        if bb and bb[0] >= region[0] and bb[1] >= region[1] \
                and bb[2] <= region[2] and bb[3] <= region[3]:
            in_region.append((f, bb))
    if not in_region:
        return [], 0, n_all
    deep = [p for p in in_region if p[1][1] < south_limit]
    if deep:
        return [f for f, _ in deep], len(in_region), n_all
    widest = max(in_region, key=lambda p: p[1][2] - p[1][0])
    return [widest[0]], len(in_region), n_all


def warm_ratio(img: Image.Image, box=None):
    """
    统计「暖色（道路常用橙黄/红）」像素占比——用于判断底图是否含路网。

    ⚠️ 只做**同区域、同缩放级别、不同图层组合之间的横向比较**才有意义；
    绝对值会随地形色调变化。经验参考（海南岛同范围 z=8）：
    ter≈0、cva≈0、vec 约 0.17%(z8)/2.15%(z10)、cta 约 2.77%。
    """
    import numpy as np
    im = img.convert('RGB')
    if box:
        im = im.crop(box)
    im = im.resize((min(im.size[0], 600), min(im.size[1], 600)))
    a = np.asarray(im).astype(int)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    warm = int(((r > 150) & (g > 60) & (g < 210) & (b < 120) & ((r - b) > 55)).sum())
    return warm / max(1, a.shape[0] * a.shape[1])
