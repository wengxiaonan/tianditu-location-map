# -*- coding: utf-8 -*-
"""
build_locator.py —— 用天地图底图出「区位图 / 研究区位置图」

一条命令产出论文可用的双面板区位图：
    左幅：全国（含南海断续线十段线、研究区红框）
    右幅：研究区（省/市县界、试点标注）
两幅图框等大、各自带经纬度刻度、比例尺、指北针与图幅标题。

用法：
    py -3 build_locator.py --config config.json
    py -3 build_locator.py --config config.json --out 图1.2-区位图.png
    py -3 build_locator.py --config config.json --geocode "海南省陵水黎族自治县南平农场"

配置样例见 assets/example-config-hainan.json，字段说明见 SKILL.md。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tianditu import (DEFAULT_BASEMAP, TileCache, bbox_size_px, fit_lat_span,
                      geocode, lat2y, load_geojson, lon2x, tk_from_env_or, warm_ratio)

try:
    from shapely.geometry import shape
    from shapely.ops import unary_union
except Exception:                                    # shapely 缺失时降级为不画界
    shape = unary_union = None


# ==================================================================== 工具
def pick_font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    for p in ([path] if path else []) + [
            r'C:\Windows\Fonts\simhei.ttf', r'C:\Windows\Fonts\msyh.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
            '/System/Library/Fonts/PingFang.ttc']:
        if p and os.path.exists(p):
            try:
                return ImageFont.truetype(p, max(8, int(size)))
            except Exception:
                continue
    return ImageFont.load_default()


def poly_parts(geom):
    """把 (Multi)Polygon 统一拆成 Polygon 列表。"""
    if geom is None:
        return []
    if geom.geom_type == 'Polygon':
        return [geom]
    if geom.geom_type == 'MultiPolygon':
        return list(geom.geoms)
    if geom.geom_type == 'GeometryCollection':
        out = []
        for g in geom.geoms:
            out.extend(poly_parts(g))
        return out
    return []


def line_parts(geom):
    if geom is None:
        return []
    if geom.geom_type == 'LineString':
        return [geom]
    if geom.geom_type == 'MultiLineString':
        return list(geom.geoms)
    if geom.geom_type == 'GeometryCollection':
        out = []
        for g in geom.geoms:
            out.extend(line_parts(g))
        return out
    return []


# ==================================================================== 面板
class Panel:
    """一块带图框、刻度、图幅标题、指北针、比例尺的地图面板。"""

    def __init__(self, img, bbox, z, cfg, font_cn=None):
        self.map, self.bbox, self.z, self.cfg = img, bbox, z, cfg
        mw, mh = img.size
        self.fs = max(11, int(round(mw / cfg.get('tick_font_div', 42.0))))
        self.f = pick_font(font_cn, self.fs)
        self.lw = max(2, int(round(self.fs / 9.0)))
        self.tick = max(6, int(round(self.fs * 0.42)))
        self.ml = self.mr = int(self.fs * 2.9) + 12
        self.mt = self.mb = int(self.fs * 2.1) + 12
        self.canvas = Image.new('RGB', (mw + self.ml + self.mr, mh + self.mt + self.mb),
                                (255, 255, 255))
        self.canvas.paste(img, (self.ml, self.mt))
        self.d = ImageDraw.Draw(self.canvas)
        self._ticks()
        if cfg.get('scalebar'):
            self._scalebar(cfg['scalebar'])
        if cfg.get('north'):
            self._north()
        if cfg.get('title'):
            self._title(cfg['title'], cfg.get('title_size', 51),
                        cfg.get('title_corner', 'left'))

    # ---------- 经纬度 → 画布像素 ----------
    def xy(self, lon, lat):
        return (lon2x(lon, self.z) - lon2x(self.bbox[0], self.z) + self.ml,
                lat2y(lat, self.z) - lat2y(self.bbox[3], self.z) + self.mt)

    # ---------- 图框与刻度 ----------
    def _ticks(self):
        d, f = self.d, self.f
        x0, y0 = self.ml, self.mt
        x1, y1 = self.ml + self.map.size[0], self.mt + self.map.size[1]
        d.rectangle([x0 - self.lw // 2, y0 - self.lw // 2, x1 + self.lw // 2, y1 + self.lw // 2],
                    outline=(60, 60, 60), width=self.lw)
        side = self.cfg.get('tick_side', 'left')
        for lat in self.cfg.get('lat_ticks', []):
            _, y = self.xy(self.bbox[0], lat)
            if not (y0 <= y <= y1):
                continue
            txt = ('%g' % lat) + '°N'
            bb = d.textbbox((0, 0), txt, font=f)
            if side == 'left':
                d.line([x0 - self.tick, y, x0, y], fill=(60, 60, 60), width=self.lw)
                d.text((x0 - self.tick - 6 - (bb[2] - bb[0]), y - (bb[3] + bb[1]) / 2),
                       txt, font=f, fill=(0, 0, 0))
            else:
                d.line([x1, y, x1 + self.tick, y], fill=(60, 60, 60), width=self.lw)
                d.text((x1 + self.tick + 6, y - (bb[3] + bb[1]) / 2), txt, font=f, fill=(0, 0, 0))
        for lon in self.cfg.get('lon_ticks', []):
            x, _ = self.xy(lon, self.bbox[1])
            if not (x0 <= x <= x1):
                continue
            d.line([x, y1, x, y1 + self.tick], fill=(60, 60, 60), width=self.lw)
            txt = ('%g' % lon) + '°E'
            bb = d.textbbox((0, 0), txt, font=f)
            d.text((x - (bb[2] + bb[0]) / 2, y1 + self.tick + 5), txt, font=f, fill=(0, 0, 0))

    # ---------- 图幅标题（默认左上，可改右上）----------
    def _title(self, text, fs, corner='left'):
        d = self.d
        ft = pick_font(self.cfg.get('_font_cn'), fs)
        bb = d.textbbox((0, 0), text, font=ft)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        pad = int(fs * 0.42)
        y0 = self.mt + pad
        if corner == 'right':
            x0 = self.ml + self.map.size[0] - pad - (tw + pad * 2)
        else:
            x0 = self.ml + pad
        d.rectangle([x0, y0, x0 + tw + pad * 2, y0 + th + pad * 2],
                    fill=(255, 255, 255), outline=(60, 60, 60), width=self.lw)
        d.text((x0 + pad - bb[0], y0 + pad - bb[1]), text, font=ft, fill=(0, 0, 0))

    # ---------- 指北针（默认右上）----------
    def _north(self):
        d, f, fs = self.d, self.f, self.fs
        cx = self.ml + self.map.size[0] - int(fs * 2.6)
        cy = self.mt + int(fs * 3.6)
        L, w2 = int(fs * 2.0), int(fs * 0.66)
        # 暗色底图（影像）上黑色指北针几乎不可见，故颜色可配置
        fc = tuple(self.cfg.get('north_fill', (20, 20, 20)))
        tc = tuple(self.cfg.get('north_text_fill', (0, 0, 0)))
        d.polygon([(cx, cy - L), (cx - w2, cy + int(fs * 0.8)),
                   (cx, cy + int(fs * 0.2)), (cx + w2, cy + int(fs * 0.8))],
                  fill=fc, outline=fc)
        bb = d.textbbox((0, 0), '北', font=f)
        d.text((cx - (bb[2] + bb[0]) / 2, cy - L - int(fs * 0.5) - bb[3]), '北',
               font=f, fill=tc,
               stroke_width=int(self.cfg.get('north_text_stroke', 0)),
               stroke_fill=tuple(self.cfg.get('north_text_stroke_fill', (255, 255, 255))))

    # ---------- 比例尺 ----------
    def _scalebar(self, sb):
        d, fs = self.d, self.fs
        ticks = sb.get('ticks', [0, 25, 50, 75])
        corner = sb.get('corner', 'left')
        fsr = sb.get('fs_ratio', 1.0)
        f = pick_font(self.cfg.get('_font_cn'), fs * fsr)
        lat_c = (self.bbox[1] + self.bbox[3]) / 2
        pxkm = self.map.size[0] / ((self.bbox[2] - self.bbox[0]) * 111.32
                                  * math.cos(math.radians(lat_c)))
        tot = (ticks[-1] - ticks[0]) * pxkm
        bh = max(4, int(fs * sb.get('thick', 0.42)))
        padx = int(fs * sb.get('pad', 0.9))
        kmw = d.textbbox((0, 0), 'km', font=f)[2]
        box_h = bh + int(fs * sb.get('boxh', 1.9))
        if sb.get('inset') is not None:                    # 距图框留白，保证不压框
            ins = int(fs * sb['inset'])
            y = self.mt + self.map.size[1] - ins - box_h
            box_w = tot + padx * 3 + kmw + int(fs * 0.5)
            x = (self.ml + self.map.size[0] - ins - box_w + padx) if corner == 'right' \
                else (self.ml + ins + padx)
        elif corner == 'right':
            x = self.ml + self.map.size[0] - padx - kmw - int(fs * 1.4) - tot
            y = self.mt + self.map.size[1] - bh - padx - int(fs * 1.1)
        else:
            x = self.ml + int(fs * 1.4) + padx
            y = self.mt + self.map.size[1] - bh - int(fs * 3.4)
        d.rectangle([x - padx, y - int(fs * 0.7),
                     x + tot + padx * 2 + kmw + int(fs * 0.5), y + box_h],
                    fill=(255, 255, 255), outline=(60, 60, 60), width=self.lw)
        n = len(ticks) - 1
        seg = tot / n
        for i in range(n):
            col = (30, 30, 30) if i % 2 == 0 else (255, 255, 255)
            d.rectangle([x + i * seg, y, x + (i + 1) * seg, y + bh], fill=col,
                        outline=(30, 30, 30))
        label_all = sb.get('label_all', True)
        for i, k in enumerate(ticks):
            txt = '%g' % k
            bb = d.textbbox((0, 0), txt, font=f)
            cx = x + (i * seg if label_all else (0 if i == 0 else tot))
            d.text((cx - (bb[2] + bb[0]) / 2, y + bh + int(fs * sb.get('labdy', 0.30))),
                   txt, font=f, fill=(0, 0, 0))
        d.text((x + tot + padx + int(fs * (sb.get('kmdx', 0.3) if label_all else 1.2)),
                y + bh + int(fs * sb.get('labdy', 0.30))), 'km', font=f, fill=(0, 0, 0))
        self.scalebar_box = (x - padx, y - int(fs * 0.7),
                             x + tot + padx * 2 + kmw + int(fs * 0.5), y + box_h)


# ==================================================================== 出图
def overlay_boundaries(img, bbox, z, ml, mt, bcfg):
    """在底图上叠加国界/省界/境界线；返回 (图象, 统计串)。"""
    if shape is None:
        return img, 'shapely 缺失，未画边界'
    feats, _ = load_geojson(bcfg['file'])
    name_field = bcfg.get('name_field', 'name')
    line_names = tuple(bcfg.get('line_names', ['境界线']))
    polys, lines = [], []
    for f in feats:
        nm = str((f.get('properties') or {}).get(name_field, ''))
        (lines if nm in line_names else polys).append(f)
    xy = lambda lon, lat: (lon2x(lon, z) - lon2x(bbox[0], z) + ml,
                           lat2y(lat, z) - lat2y(bbox[3], z) + mt)
    d = ImageDraw.Draw(img)
    excl = set(bcfg.get('union_exclude', []))
    geoms_all = [shape(f['geometry']) for f in polys] if shape else []
    geoms = [shape(f['geometry']) for f in polys
             if str((f.get('properties') or {}).get(name_field, '')) not in excl] if shape else []
    if bcfg.get('nation_width') and geoms:
        nat = unary_union(geoms)
        for pg in poly_parts(nat):
            if pg.area >= bcfg.get('min_area', 0.0):
                d.line([xy(*c) for c in pg.exterior.coords],
                       fill=(0, 0, 0), width=bcfg['nation_width'])
    for g in geoms_all:
        for pg in poly_parts(g):
            d.line([xy(*c) for c in pg.exterior.coords],
                   fill=(90, 90, 90), width=bcfg.get('prov_width', 1))
    nseg = 0
    for f in lines:                                     # 境界线（十段线）
        for ln in line_parts(shape(f['geometry'])):
            if len(ln.coords) < 2:
                continue                            # 剔除 1 点、0 长要素
            d.line([xy(*c) for c in ln.coords], fill=(0, 0, 0),
                   width=bcfg.get('line_width', 4))
            nseg += 1
    return img, '面 %d 线 %d（有效线段 %d）' % (len(polys), len(lines), nseg)


def erase_regions(img, bbox, z, regions):
    """
    擦除底图自带的小字注记（如天地图 cva 在图框内已有的「海南省」小字）。
    配置形如 "erase": [{"bbox": [lon0,lat0,lon1,lat1], "radius": 5}]。
    优先用 cv2.inpaint；没有 OpenCV 时退化为「用四周环带中值色填充」。
    """
    import numpy as np
    arr = np.asarray(img.convert('RGB')).copy()
    mask = np.zeros(arr.shape[:2], np.uint8)
    for r in regions:
        rb = r['bbox']
        x0 = int(lon2x(rb[0], z) - lon2x(bbox[0], z))
        x1 = int(lon2x(rb[2], z) - lon2x(bbox[0], z))
        y0 = int(lat2y(rb[3], z) - lat2y(bbox[3], z))
        y1 = int(lat2y(rb[1], z) - lat2y(bbox[3], z))
        x0, x1 = max(0, min(x0, x1)), min(arr.shape[1], max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(arr.shape[0], max(y0, y1))
        mask[y0:y1, x0:x1] = 255
    if mask.sum() == 0:
        return img
    try:
        import cv2
        out = cv2.inpaint(arr[:, :, ::-1], mask, int(regions[0].get('radius', 5)),
                          cv2.INPAINT_TELEA)
        return Image.fromarray(out[:, :, ::-1])
    except Exception:
        ys, xs = np.where(mask > 0)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        ring = np.concatenate([
            arr[max(0, y0 - 6):y0, x0:x1].reshape(-1, 3),
            arr[y1:y1 + 6, x0:x1].reshape(-1, 3),
            arr[y0:y1, max(0, x0 - 6):x0].reshape(-1, 3),
            arr[y0:y1, x1:x1 + 6].reshape(-1, 3)]) if y0 > 0 or x0 > 0 else arr.reshape(-1, 3)
        arr[y0:y1, x0:x1] = np.median(ring, axis=0).astype(arr.dtype)
        return Image.fromarray(arr)


def draw_points(img, bbox, z, ml, mt, points, font_cn, size=15):
    xy = lambda lon, lat: (lon2x(lon, z) - lon2x(bbox[0], z) + ml,
                           lat2y(lat, z) - lat2y(bbox[3], z) + mt)
    d = ImageDraw.Draw(img)
    f = pick_font(font_cn, size)
    for p in points:
        x, y = xy(p['lon'], p['lat'])
        d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(220, 20, 20),
                  outline=(255, 255, 255), width=2)
        if not p.get('name'):
            continue
        bb = d.textbbox((0, 0), p['name'], font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        tx, ty = x + 9, y - th / 2 - 2
        d.rectangle([tx - 3, ty - 2, tx + tw + 3, ty + th + 4],
                    fill=(255, 255, 255), outline=(120, 120, 120))
        d.text((tx, ty), p['name'], font=f, fill=(0, 0, 0))


def _named_polys(bcfg):
    """读边界文件，返回 [(名称, shapely 几何)] 只含面要素。"""
    if shape is None:
        raise SystemExit('绘制/自动取景需要 shapely（pip install shapely）')
    feats, _ = load_geojson(bcfg['file'])
    name_field = bcfg.get('name_field', 'name')
    line_names = tuple(bcfg.get('line_names', ['境界线']))
    out = []
    for f in feats:
        nm = str((f.get('properties') or {}).get(name_field, ''))
        if nm in line_names:
            continue
        out.append((nm, shape(f['geometry'])))
    return out


def auto_bbox_from_boundary(bcfg, pad=0.10):
    """
    由面要素并集范围自动定 bbox。
    union_exclude 里的要素（如「三沙市」）不参与——否则研究区取景会把南海诸岛
    一起框进去，导致主体被压成一小块。
    """
    excl = set(bcfg.get('union_exclude', []))
    geoms = [g for nm, g in _named_polys(bcfg) if nm not in excl]
    if not geoms:
        raise SystemExit('边界文件里没有可用的面要素，无法 auto 计算 bbox')
    x0, y0, x1, y1 = unary_union(geoms).bounds
    return (x0 - (x1 - x0) * pad, y0 - (y1 - y0) * pad,
            x1 + (x1 - x0) * pad, y1 + (y1 - y0) * pad)


def build(cfg, out_override=None):
    # 瓦片全部命中缓存时无需 tk；真正要下载时才报错
    tk = tk_from_env_or(cfg.get('tk'), required=False)
    cache = TileCache(cfg.get('cache_dir', '.tdt_cache'), tk)
    font_cn = cfg.get('font_cn')
    base_layers = tuple(cfg.get('basemap', DEFAULT_BASEMAP))
    panels = cfg['panels']
    layout = cfg.get('layout', {})
    target_h = layout.get('panel_height', 1300)
    gap = layout.get('gap', 90)
    top = layout.get('top', 20)

    # ① 先定各幅 bbox（支持 auto，并按 aspect 归一化，保证两框等大）
    aspect = layout.get('aspect')
    info = []
    for i, pc in enumerate(panels):
        bb = pc.get('bbox')
        if bb in (None, 'auto'):
            bb = list(auto_bbox_from_boundary(pc['boundary'], pc.get('bbox_pad', 0.10)))
        bb = list(bb)
        z = int(pc['zoom'])
        if aspect or pc.get('fit_aspect'):
            asp = pc.get('fit_aspect') or aspect
            bb[1], bb[3] = fit_lat_span(bb[0], bb[2], bb[1], bb[3], z, asp)
        pc['_bbox'], pc['_z'] = bb, z
        info.append((bb, z))

    # ② 拼底图 + 叠矢量
    imgs = []
    for pc in panels:
        bb, z = pc['_bbox'], pc['_z']
        layers = tuple(pc.get('layers', base_layers))
        img = cache.stitch(bb, z, layers)
        img = img.convert('RGB')
        warm = warm_ratio(img)
        note = ''
        if pc.get('erase'):
            img = erase_regions(img, bb, z, pc['erase'])
            note += '擦除 %d 处 ' % len(pc['erase'])
        if pc.get('boundary'):
            img, note2 = overlay_boundaries(img, bb, z, 0, 0, pc['boundary'])
            note += note2
        if pc.get('redbox'):
            d = ImageDraw.Draw(img)
            rb = pc['redbox']
            x0 = lon2x(rb[0], z) - lon2x(bb[0], z)
            y0 = lat2y(rb[3], z) - lat2y(bb[3], z)
            x1 = lon2x(rb[2], z) - lon2x(bb[0], z)
            y1 = lat2y(rb[1], z) - lat2y(bb[3], z)
            d.rectangle([x0, y0, x1, y1], outline=(230, 20, 20),
                        width=pc.get('redbox_width', 4))
        if pc.get('points'):
            draw_points(img, bb, z, 0, 0, pc['points'], font_cn,
                        pc.get('point_font', 15))
        cl = pc.get('center_label')
        if cl:
            d = ImageDraw.Draw(img)
            cx = cl.get('x', img.size[0] / 2)
            cy = cl.get('y', img.size[1] / 2)
            d.text((cx, cy), cl['text'], font=pick_font(font_cn, cl.get('size', 96)),
                   fill=tuple(cl.get('fill', [15, 15, 15])), anchor='mm',
                   stroke_width=cl.get('stroke', 7), stroke_fill=(255, 255, 255))
        sy = pc.get('side_label')          # 图框下方追加省名（如红色「海南省」）
        if sy:
            d = ImageDraw.Draw(img)
            bb2 = pc['redbox']
            x = (lon2x((bb2[0] + bb2[2]) / 2, z) - lon2x(bb[0], z))
            y = lat2y(bb2[1], z) - lat2y(bb[3], z) + sy.get('dy', 26)
            d.text((x, y), sy['text'], font=pick_font(font_cn, sy.get('size', 44)),
                   fill=tuple(sy.get('fill', [210, 20, 20])), anchor='mm',
                   stroke_width=sy.get('stroke', 2), stroke_fill=(255, 255, 255))
        print('  幅%d bbox=%s z=%d 图层=%s 暖色占比=%.3f%%  %s'
              % (len(imgs) + 1, ['%.4f' % v for v in bb], z, layers, warm * 100, note))
        imgs.append(img)

    # ③ 套图框装饰
    made = []
    for pc, img in zip(panels, imgs):
        pcfg = dict(pc)
        pcfg['_font_cn'] = font_cn
        made.append(Panel(img, pc['_bbox'], pc['_z'], pcfg, font_cn))

    # ④ 缩放拼版（两框等高）
    scaled = []
    for p in made:
        s = target_h / p.map.size[1]
        scaled.append(p.canvas.resize(
            (int(p.canvas.size[0] * s), int(p.canvas.size[1] * s)), Image.LANCZOS))
    W = sum(c.size[0] for c in scaled) + gap * (len(scaled) - 1)
    H = max(c.size[1] for c in scaled) + top
    canvas = Image.new('RGB', (W, H), (255, 255, 255))
    x = 0
    for c in scaled:
        canvas.paste(c, (x, top))
        x += c.size[0] + gap
    out = out_override or cfg['out']
    if not os.path.isabs(out):
        out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    canvas.save(out)
    print('\n成品 %s  %s  宽高比 %.4f  %.1f MB  瓦片 %d 张（失败 %d）'
          % (out, canvas.size, canvas.size[0] / canvas.size[1],
             os.path.getsize(out) / 1048576, cache.fetched, cache.failed))
    return out


def main():
    ap = argparse.ArgumentParser(description='用天地图底图出区位图')
    ap.add_argument('--config', required=True, help='JSON 配置')
    ap.add_argument('--out', help='覆盖配置里的输出路径')
    ap.add_argument('--geocode', help='只做地理编码查询（不加载配置）')
    a = ap.parse_args()
    if a.geocode:
        r = geocode(a.geocode)
        print(json.dumps(r, ensure_ascii=False, indent=2) if r else '未查到')
        return
    with open(a.config, encoding='utf-8') as fh:
        cfg = json.load(fh)
    build(cfg, a.out)


if __name__ == '__main__':
    main()
