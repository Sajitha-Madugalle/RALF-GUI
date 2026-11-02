"""Fill sub-spacing Manhattan gaps in one net's emitted metal geometry.

This handles same-net notches ignored by inter-net obstacle checks. Final
Magic DRC and LVS remain required: added metal can approach another net.
"""
from itertools import combinations


def fill_same_net_gaps(commands, pdk):
    layers = {}
    for line in commands.splitlines():
        t = line.split()
        if len(t) < 8 or t[:2] != ['wire', 'segment']:
            continue
        layer = t[2]
        if layer not in pdk.metal_layers or layer == 'li':
            continue
        w, x0, y0, x1, y1 = map(float, t[3:8])
        h = w / 2
        cap = 0 if '-noendcap' in t else h
        if y0 == y1 and x0 != x1:
            rect = (min(x0, x1)-cap, y0-h, max(x0, x1)+cap, y0+h)
        elif x0 == x1 and y0 != y1:
            rect = (x0-h, min(y0, y1)-cap, x0+h, max(y0, y1)+cap)
        elif x0 == x1 and y0 == y1:
            rect = (x0-h, y0-h, x0+h, y0+h)
        else:
            raise ValueError('Non-Manhattan wire in Magic export')
        layers.setdefault(layer, set()).add(rect)
    result = []
    for layer, rectangles in layers.items():
        space = pdk.get_layer(layer).minSpace
        fills = set()
        for a, b in combinations(sorted(rectangles), 2):
            for horizontal in (True, False):
                i, j = (0, 1) if horizontal else (1, 0)
                left, right = (a, b) if a[i] <= b[i] else (b, a)
                gap = right[i] - left[i+2]
                lo, hi = max(a[j], b[j]), min(a[j+2], b[j+2])
                if 0 < gap < space and lo < hi:
                    r = (left[i+2], lo, right[i], hi)
                    if not horizontal:
                        r = (r[1], r[0], r[3], r[2])
                    fills.add(r)
        for r in sorted(fills):
            result.append('box ' + ' '.join(f'{v:g}' for v in r) + '\npaint ' + layer + '\n')
    return ''.join(result)
