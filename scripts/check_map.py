# -*- coding: utf-8 -*-
"""
check_map.py —— 区位图出图前后自检（能自动查的自动查，查不了的明确说"需人工"）

用法：
    py -3 check_map.py --config config.json
    py -3 check_map.py --config config.json --image 图1.2-区位图.png

退出码：0 = 全部通过；1 = 有问题项。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tianditu import bbox_size_px, load_geojson, warm_ratio

PASS, WARN, FAIL, MANUAL = '通过', '注意', '不通过', '需人工'
_marks = {PASS: '✓', WARN: '!', FAIL: '✗', MANUAL: '?'}


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, item, detail=''):
        self.rows.append((level, item, detail))

    def dump(self):
        print('%-6s %-34s %s' % ('结论', '检查项', '说明'))
        print('-' * 100)
        for lv, it, dt in self.rows:
            print('%-6s %-34s %s' % ('%s %s' % (_marks[lv], lv), it, dt))
        bad = sum(1 for lv, _, _ in self.rows if lv == FAIL)
        warn = sum(1 for lv, _, _ in self.rows if lv == WARN)
        man = sum(1 for lv, _, _ in self.rows if lv == MANUAL)
        print('-' * 100)
        print('不通过 %d · 注意 %d · 需人工确认 %d' % (bad, warn, man))
        return 1 if bad else 0


def line_segments(features, name_field, line_names):
    from tianditu import count_line_segments
    return count_line_segments(
        [f for f in features
         if str((f.get('properties') or {}).get(name_field, '')) in tuple(line_names)])

def check_config(cfg, rep):
    base = tuple(cfg.get('basemap', ()))
    risky = [l for l in base if l in ('vec', 'cta')]
    if risky:
        rep.add(WARN, '底图图层是否含路网',
                'basemap 含 %s，可能带路网/路名；论文区位图一般应改用 ter+cva' % risky)
    else:
        rep.add(PASS, '底图图层是否含路网', 'basemap = %s（无路网取向）' % (base,))

    saw_ten = False
    for i, pc in enumerate(cfg['panels'], 1):
        tag = '幅%d' % i
        bb = pc.get('bbox')
        bc = pc.get('boundary')
        if bc:
            feats, _ = load_geojson(bc['file'])
            nf = bc.get('name_field', 'name')
            ln = bc.get('line_names', ['境界线'])
            n_all = line_segments(feats, nf, ln)
            from tianditu import ten_dash_features
            cands, n_reg, n_all2 = ten_dash_features(feats, nf, ln)
            n_ten = line_segments(cands, nf, ln)
            is_nation = isinstance(bb, list) and bb[1] < 12
            if is_nation:
                saw_ten = True
                if n_ten == 10:
                    rep.add(PASS, '%s 十段线段数' % tag,
                            '识别出的南海断续线实测 %d 段，符合（南海框内另有 %d 条'
                            '境界要素，已排除；境界线要素合计 %d 条）'
                            % (n_ten, max(0, n_reg - len(cands)), n_all2))
                elif n_ten == 0:
                    rep.add(FAIL, '%s 十段线段数' % tag,
                            '该幅覆盖南海，但边界数据在南海海域内没有任何境界线要素'
                            '——十段线会缺失。请换用含完整十段线的边界数据')
                else:
                    rep.add(FAIL, '%s 十段线段数' % tag,
                            '南海断续线实测 %d 段（必须恰好 10 段）——请核对边界数据是否完整'
                            % n_ten)
            else:
                rep.add(PASS, '%s 境界线要素' % tag,
                        '实测 %d 段（非全国幅，不要求等于 10）' % n_all)
            if bc.get('union_exclude'):
                rep.add(PASS, '%s 自动取景排除项' % tag,
                        '已排除 %s，避免被南海诸岛撑大取景' % bc['union_exclude'])
        # 红框是否在幅内
        rb = pc.get('redbox')
        if rb and isinstance(bb, list):
            ok = bb[0] <= rb[0] and bb[1] <= rb[1] and rb[2] <= bb[2] and rb[3] <= bb[3]
            rep.add(PASS if ok else FAIL, '%s 研究区红框在幅内' % tag,
                    '红框 %s vs 幅面 %s' % (rb, ['%.2f' % v for v in bb]))
        elif rb:
            rep.add(MANUAL, '%s 研究区红框在幅内' % tag, 'bbox 为 auto，请出图后看图确认')
        # 点位是否在幅内
        pts = pc.get('points') or []
        if pts and isinstance(bb, list):
            out = [p['name'] for p in pts
                   if not (bb[0] <= p['lon'] <= bb[2] and bb[1] <= p['lat'] <= bb[3])]
            rep.add(PASS if not out else FAIL, '%s 样点落在幅面内' % tag,
                    '共 %d 点' % len(pts) if not out else '越界: %s' % out)
        # 幅面尺寸是否够大
        if isinstance(bb, list) and 'zoom' in pc:
            w, h = bbox_size_px(bb, int(pc['zoom']))
            lv = PASS if min(w, h) >= 400 else WARN
            rep.add(lv, '%s 幅面像素量' % tag,
                    'z=%s 时约 %.0f×%.0f px；过小则印刷发虚' % (pc['zoom'], w, h))
        if not pc.get('north'):
            rep.add(WARN, '%s 指北针' % tag, '未配置 north=true')
        if not pc.get('scalebar'):
            rep.add(WARN, '%s 比例尺' % tag, '未配置 scalebar')
    if not saw_ten:
        rep.add(WARN, '全国幅（含南海）', '没有任何一幅覆盖到 12°N 以南，'
                                         '若研究主题需要全国区位图，应包含南海与十段线')
    rep.add(MANUAL, '合规口径', '本图是否需送审、是否应改用标准地图服务系统样图，'
                                '须与导师/学院确认（见 references/compliance.md）')
    rep.add(MANUAL, '图注', '须写明底图来源、边界来源、点位定位方式、"不作界址依据"')


def check_image(path, cfg, rep):
    img = Image.open(path).convert('RGB')
    w, h = img.size
    rep.add(PASS, '成品尺寸', '%d×%d，宽高比 %.4f，%.2f MB'
            % (w, h, w / h, os.path.getsize(path) / 1048576))
    if min(w, h) < 800:
        rep.add(WARN, '成品分辨率', '最短边 %d px，印刷可能不足 300 dpi' % min(w, h))
    warm = warm_ratio(img)
    rep.add(PASS if warm < 0.01 else WARN, '成品暖色占比',
            '%.3f%%（偏高时可能是路网或大面积红色标注；'
            '本项仅作提示，需与底图组合横向比较）' % (warm * 100))
    import numpy as np
    a = np.asarray(img.resize((min(w, 900), min(h, 900)))).astype(int)
    red = int(((a[:, :, 0] > 180) & (a[:, :, 1] < 80) & (a[:, :, 2] < 80)).sum())
    rep.add(PASS if red > 20 else FAIL, '红色要素存在（红框/样点）',
            '检出红色像素 %d 个' % red)


def main():
    ap = argparse.ArgumentParser(description='区位图自检')
    ap.add_argument('--config', required=True)
    ap.add_argument('--image', help='出图后的 PNG，可选')
    a = ap.parse_args()
    with open(a.config, encoding='utf-8') as fh:
        cfg = json.load(fh)
    rep = Report()
    check_config(cfg, rep)
    if a.image:
        check_image(a.image, cfg, rep)
    sys.exit(rep.dump())


if __name__ == '__main__':
    main()
