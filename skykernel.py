"""Star plotting and point projection for the picostellar demo, pure Python.

This is the reference for skyviper.py (the @micropython.viper build of the same
functions) and what the desktop simulator runs. Both work in integers on
the same buffers, so a device render matches a host render bit for bit.

Coordinates: the catalogue holds unit vectors in J2000 equatorial coordinates
as Q15 int16. `params` (an array('i')) carries the view:

  P_W, P_H       pixel buffer size
  P_CX, P_CY     screen centre of the projection, pixels
  P_K            projection scale in pixels: a point 90 deg from the view
                 centre lands K pixels from (cx, cy)  (stereographic)
  P_ZMIN         Q15 cosine of the largest angle from the centre still drawn
  P_R2           squared pixel radius of the drawn disc around (cx, cy); make
                 it huge for a rectangular view
  P_MAG_LIMIT    faintest magnitude drawn, times 10
  P_MAG_OFFSET   added to a star's magnitude*10 before its size class is picked
  P_M00..P_M22   rotation matrix rows (right, up, view direction) in Q15
  P_UX..P_UZ     the zenith in Q15; P_HMIN: a star with up . v below it is
                 underground and skipped (project_stars, project_pick)

The pixel buffer is RGB565 in the byte order the Canvas uses; `lut` holds
18 colours in that order: 6 colour classes (B-V bins) x 3 brightness levels.
"""
import array
import struct

from micropython import const

from skyparams import *  # noqa: F401,F403  (P_*, CULLED, new_params)

STAR_BYTES = const(8)
VERT_BYTES = const(6)

# magnitude*10 thresholds of the size classes, brightest first
SIZE_CLASSES = (10, 25, 40, 50)


def bv_class(bv):
    """B-V * 10 -> colour column 0..5; 127 marks an unknown colour."""
    if bv == 127:
        return 1
    if bv < -1:
        return 0
    if bv < 3:
        return 1
    if bv < 6:
        return 2
    if bv < 10:
        return 3
    if bv < 15:
        return 4
    return 5


def plot_stars(cat, n, params, pixels, lut):
    """Draw the first n catalogue stars into pixels. Returns the number drawn."""
    w = params[P_W]
    h = params[P_H]
    cx = params[P_CX]
    cy = params[P_CY]
    k = params[P_K]
    zmin = params[P_ZMIN]
    r2 = params[P_R2]
    mag_limit = params[P_MAG_LIMIT]
    mag_offset = params[P_MAG_OFFSET]
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = params[P_M00:P_M22 + 1]
    px = memoryview(pixels).cast("H")
    drawn = 0
    for i in range(n):
        x, y, z, mag, bv = struct.unpack_from("<hhhbb", cat, i * STAR_BYTES)
        if mag > mag_limit:
            break                       # the catalogue is sorted by magnitude
        zz = (m20 * x + m21 * y + m22 * z) >> 15
        if zz < zmin:
            continue
        xx = (m00 * x + m01 * y + m02 * z) >> 15
        yy = (m10 * x + m11 * y + m12 * z) >> 15
        d = 32768 + zz
        sx = cx + (xx * k) // d
        sy = cy - (yy * k) // d
        dx = sx - cx
        dy = sy - cy
        if dx * dx + dy * dy > r2:
            continue
        m = mag + mag_offset
        col = bv_class(bv)
        if m < SIZE_CLASSES[0]:
            size = 4
        elif m < SIZE_CLASSES[1]:
            size = 3
        elif m < SIZE_CLASSES[2]:
            size = 2
        elif m < SIZE_CLASSES[3]:
            size = 1
        else:
            size = 0
        drawn += 1
        if size == 0:
            if 0 <= sx < w and 0 <= sy < h:
                px[sy * w + sx] = lut[col * 3 + 2]
            continue
        if size == 1:
            if 0 <= sx < w and 0 <= sy < h:
                px[sy * w + sx] = lut[col * 3 + 1]
            continue
        bright = lut[col * 3]
        mid = lut[col * 3 + 1]
        if size == 2:                   # plus shape
            if 0 <= sx < w and 0 <= sy < h:
                px[sy * w + sx] = bright
            if 1 <= sx < w - 1 and 1 <= sy < h - 1:
                px[sy * w + sx - 1] = mid
                px[sy * w + sx + 1] = mid
                px[(sy - 1) * w + sx] = mid
                px[(sy + 1) * w + sx] = mid
            continue
        if 1 <= sx < w - 1 and 1 <= sy < h - 1:
            for yy2 in (sy - 1, sy, sy + 1):
                base = yy2 * w + sx
                px[base - 1] = mid
                px[base] = bright
                px[base + 1] = mid
            px[sy * w + sx] = bright
            if size == 4 and 2 <= sx < w - 2 and 2 <= sy < h - 2:
                px[sy * w + sx - 2] = mid
                px[sy * w + sx + 2] = mid
                px[(sy - 2) * w + sx] = mid
                px[(sy + 2) * w + sx] = mid
    return drawn


def project(vecs, n, params, out):
    """Project n Q15 unit vectors (6 bytes each) to screen; out gets int16 pairs
    sx, sy per point, or CULLED, CULLED for a point behind the view limit."""
    cx = params[P_CX]
    cy = params[P_CY]
    k = params[P_K]
    zmin = params[P_ZMIN]
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = params[P_M00:P_M22 + 1]
    for i in range(n):
        x, y, z = struct.unpack_from("<hhh", vecs, i * VERT_BYTES)
        zz = (m20 * x + m21 * y + m22 * z) >> 15
        if zz < zmin:
            out[2 * i] = CULLED
            out[2 * i + 1] = CULLED
            continue
        xx = (m00 * x + m01 * y + m02 * z) >> 15
        yy = (m10 * x + m11 * y + m12 * z) >> 15
        d = 32768 + zz
        sx = cx + (xx * k) // d
        sy = cy - (yy * k) // d
        out[2 * i] = max(-32767, min(32767, sx))
        out[2 * i + 1] = max(-32767, min(32767, sy))


def segment_bounds(lines, n, scr, out):
    """Screen y range (ymin, ymax) of every segment as int16 pairs; a culled
    segment gets (32767, -32768) so no strip ever matches it."""
    for i in range(n):
        a = lines[2 * i]
        b = lines[2 * i + 1]
        if scr[2 * a] == CULLED or scr[2 * b] == CULLED:
            out[2 * i] = 32767
            out[2 * i + 1] = -32768
            continue
        y0 = scr[2 * a + 1]
        y1 = scr[2 * b + 1]
        out[2 * i] = y0 if y0 < y1 else y1
        out[2 * i + 1] = y1 if y0 < y1 else y0


def draw_lines(lines, n, scr, bounds, pixels, w, h, colour, oy):
    """Draw n segments (uint16 vertex index pairs) whose projected ends are in
    scr (int16 sx, sy pairs) and y ranges in bounds (from segment_bounds) into
    pixels, a w x h buffer whose first row is screen row oy. Returns the
    segments drawn. The reference the bucket drawing is tested against; the
    app draws through draw_bucket."""
    px = memoryview(pixels).cast("H")
    drawn = 0
    for i in range(n):
        if bounds[2 * i + 1] < oy or bounds[2 * i] >= oy + h:
            continue
        a = lines[2 * i]
        b = lines[2 * i + 1]
        x0 = scr[2 * a]
        x1 = scr[2 * b]
        y0 = scr[2 * a + 1] - oy
        y1 = scr[2 * b + 1] - oy
        if (x0 < 0 and x1 < 0) or (x0 >= w and x1 >= w) or (y0 < 0 and y1 < 0) or (y0 >= h and y1 >= h):
            continue
        drawn += 1
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            if 0 <= x0 < w and 0 <= y0 < h:
                px[y0 * w + x0] = colour
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
                if (y0 >= h and sy > 0) or (y0 < 0 and sy < 0):
                    break               # left the strip for good
    return drawn


LIST_WORDS = const(4)              # one display-list record: sx, sy, size, colour class


def project_stars(cat, n, params, out, max_out):
    """Project the first n catalogue stars into a display list of int16 records
    (sx, sy, size 0-4, colour class 0-5), the same culling as plot_stars.
    Returns the record count, at most max_out."""
    cx = params[P_CX]
    cy = params[P_CY]
    k = params[P_K]
    zmin = params[P_ZMIN]
    r2 = params[P_R2]
    mag_limit = params[P_MAG_LIMIT]
    mag_offset = params[P_MAG_OFFSET]
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = params[P_M00:P_M22 + 1]
    ux, uy, uz, hmin = params[P_UX], params[P_UY], params[P_UZ], params[P_HMIN]
    count = 0
    for i in range(n):
        if count >= max_out:
            break
        x, y, z, mag, bv = struct.unpack_from("<hhhbb", cat, i * STAR_BYTES)
        if mag > mag_limit:
            break
        zz = (m20 * x + m21 * y + m22 * z) >> 15
        if zz < zmin:
            continue
        if ((ux * x + uy * y + uz * z) >> 15) < hmin:
            continue                    # below the horizon
        xx = (m00 * x + m01 * y + m02 * z) >> 15
        yy = (m10 * x + m11 * y + m12 * z) >> 15
        d = 32768 + zz
        sx = cx + (xx * k) // d
        sy = cy - (yy * k) // d
        dx = sx - cx
        dy = sy - cy
        if dx * dx + dy * dy > r2:
            continue
        m = mag + mag_offset
        if m < SIZE_CLASSES[0]:
            size = 4
        elif m < SIZE_CLASSES[1]:
            size = 3
        elif m < SIZE_CLASSES[2]:
            size = 2
        elif m < SIZE_CLASSES[3]:
            size = 1
        else:
            size = 0
        o = count * LIST_WORDS
        out[o] = max(-32767, min(32767, sx))
        out[o + 1] = max(-32767, min(32767, sy))
        out[o + 2] = size
        out[o + 3] = bv_class(bv)
        count += 1
    return count


# Star stamps for sizes 2, 3 and 4: (dx + 2, dy + 2, level) with level 0 bright, 1 mid, 2 dim.
STAMPS = bytes((2, 2, 0, 1, 2, 1, 3, 2, 1, 2, 1, 1, 2, 3, 1,                       # size 2: a round dot
                1, 1, 2, 3, 1, 2, 1, 3, 2, 3, 3, 2,
                2, 2, 0, 1, 2, 0, 3, 2, 0, 2, 1, 0, 2, 3, 0,                       # size 3: radius 2
                1, 1, 1, 3, 1, 1, 1, 3, 1, 3, 3, 1, 0, 2, 2, 4, 2, 2, 2, 0, 2, 2, 4, 2,
                1, 1, 0, 2, 1, 0, 3, 1, 0, 1, 2, 0, 2, 2, 0, 3, 2, 0, 1, 3, 0, 2, 3, 0,  # size 4: a disc
                3, 3, 0, 0, 2, 1, 4, 2, 1, 2, 0, 1, 2, 4, 1,
                0, 1, 2, 0, 3, 2, 4, 1, 2, 4, 3, 2, 1, 0, 2, 3, 0, 2, 1, 4, 2, 3, 4, 2))
STAMP_END = (0, 0, 9, 22, 43)          # size s uses entries STAMP_END[s - 1]..STAMP_END[s]


def lighten(px, i, colour):
    """Pixel i becomes the per-channel maximum of itself and colour (both wire-order RGB565)."""
    d = px[i]
    d = ((d >> 8) | (d << 8)) & 0xFFFF
    c = ((colour >> 8) | (colour << 8)) & 0xFFFF
    v = max(d & 0xF800, c & 0xF800) | max(d & 0x07E0, c & 0x07E0) | max(d & 0x001F, c & 0x001F)
    px[i] = ((v >> 8) | (v << 8)) & 0xFFFF


def plot_list(lst, count, pixels, w, h, oy, lut):
    """Draw display-list records into pixels, a w x h buffer whose first row is
    screen row oy; every pixel is clipped on its own, so dots straddling a strip
    boundary are drawn in both strips. A dot only brightens what is under it, so
    stars go on top of the lines without cutting them. Returns the records touched."""
    px = memoryview(pixels).cast("H")
    drawn = 0
    for i in range(count):
        o = i * LIST_WORDS
        sy = lst[o + 1] - oy
        if sy < -2 or sy >= h + 2:
            continue
        sx = lst[o]
        if sx < -2 or sx >= w + 2:
            continue
        size = lst[o + 2]
        col = lst[o + 3] * 3
        drawn += 1
        if size < 2:
            if 0 <= sx < w and 0 <= sy < h:
                lighten(px, sy * w + sx, lut[col + 2 - size])
            continue
        for e in range(STAMP_END[size - 1], STAMP_END[size]):
            x = sx + STAMPS[3 * e] - 2
            y = sy + STAMPS[3 * e + 1] - 2
            if 0 <= x < w and 0 <= y < h:
                lighten(px, y * w + x, lut[col + STAMPS[3 * e + 2]])
    return drawn


def sort_list(lst, count, rows, nstrips, offsets, out):
    """Counting sort of display-list records by strip (sy // rows) into out;
    offsets[k] .. offsets[k+1] is strip k's range (nstrips + 1 entries, rows
    above the screen go to strip 0 and below it to the last one)."""
    for k in range(nstrips + 1):
        offsets[k] = 0
    for i in range(count):
        k = lst[4 * i + 1] // rows
        k = 0 if k < 0 else (nstrips - 1 if k >= nstrips else k)
        offsets[k + 1] += 1
    for k in range(nstrips):
        offsets[k + 1] += offsets[k]
    for i in range(count):
        o = 4 * i
        k = lst[o + 1] // rows
        k = 0 if k < 0 else (nstrips - 1 if k >= nstrips else k)
        pos = offsets[k] * 4
        out[pos] = lst[o]
        out[pos + 1] = lst[o + 1]
        out[pos + 2] = lst[o + 2]
        out[pos + 3] = lst[o + 3]
        offsets[k] += 1
    for k in range(nstrips, 0, -1):     # the fill moved every offset one strip up
        offsets[k] = offsets[k - 1]
    offsets[0] = 0


def project_pick(cat, n, params, mag_limit, base, out, max_out):
    """Screen positions of the stars a cursor can jump to: the first n catalogue
    stars down to mag_limit (magnitude*10) that land on the screen, as int16
    records (sx, sy, star index); base is the index of cat's first star.
    Returns the record count, at most max_out."""
    w = params[P_W]
    h = params[P_H]
    cx = params[P_CX]
    cy = params[P_CY]
    k = params[P_K]
    zmin = params[P_ZMIN]
    r2 = params[P_R2]
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = params[P_M00:P_M22 + 1]
    ux, uy, uz, hmin = params[P_UX], params[P_UY], params[P_UZ], params[P_HMIN]
    count = 0
    for i in range(n):
        if count >= max_out:
            break
        x, y, z, mag, bv = struct.unpack_from("<hhhbb", cat, i * STAR_BYTES)
        if mag > mag_limit:
            break
        zz = (m20 * x + m21 * y + m22 * z) >> 15
        if zz < zmin:
            continue
        if ((ux * x + uy * y + uz * z) >> 15) < hmin:
            continue                    # below the horizon
        xx = (m00 * x + m01 * y + m02 * z) >> 15
        yy = (m10 * x + m11 * y + m12 * z) >> 15
        d = 32768 + zz
        sx = cx + (xx * k) // d
        sy = cy - (yy * k) // d
        dx = sx - cx
        dy = sy - cy
        if dx * dx + dy * dy > r2 or not (0 <= sx < w and 0 <= sy < h):
            continue
        out[3 * count] = sx
        out[3 * count + 1] = sy
        out[3 * count + 2] = base + i
        count += 1
    return count


def pick_dir(pick, n, cx, cy, dx, dy, cone):
    """Index of the pick record (x, y, star) nearest to (cx, cy) in direction
    (dx, dy), scored along + 3 * across inside |across| <= cone * along, or -1."""
    best = -1
    best_score = 0x3FFFFFFF               # a small int, so viper keeps it a machine word
    for i in range(n):
        ox = pick[3 * i] - cx
        oy = pick[3 * i + 1] - cy
        along = ox * dx + oy * dy
        if along <= 2:
            continue
        across = ox * dy - oy * dx
        if across < 0:
            across = -across
        if across > along * cone:
            continue
        score = along + 3 * across
        if score < best_score:
            best_score = score
            best = i
    return best


def pick_near(pick, n, x, y, r2):
    """Index of the pick record closest to (x, y) within squared radius r2, or -1."""
    best = -1
    best_d = r2 + 1
    for i in range(n):
        ox = pick[3 * i] - x
        oy = pick[3 * i + 1] - y
        d = ox * ox + oy * oy
        if d < best_d:
            best_d = d
            best = i
    return best


def bucket_lines(bc, nc, be, bh, nr, flags, rows, nstrips, offsets, out, max_out):
    """Index the line segments by the render strips they cross, so a strip
    draws only its own. bc, be, bh are the (ymin, ymax) pairs from
    segment_bounds of the nc constellation segments and the nr ecliptic and
    horizon segments; flags bit 0 keeps the constellations, bit 1 the
    ecliptic (the horizon is always kept). out gets uint16 entries
    segment | class << 12 (0 constellation, 2 ecliptic, 3 horizon); strip k's
    are out[offsets[k]:offsets[k + 1]]. Returns the entry count, or -1 when
    more than max_out would be needed (draw with draw_lines then)."""
    for k in range(nstrips + 1):
        offsets[k] = 0
    for p in range(2):
        for i in range(nc + 2 * nr):
            if i < nc:
                if not flags & 1:
                    continue
                b, j, cls = bc, i, 0
            elif i < nc + nr:
                if not flags & 2:
                    continue
                b, j, cls = be, i - nc, 2
            else:
                b, j, cls = bh, i - nc - nr, 3
            ymin = b[2 * j]
            ymax = b[2 * j + 1]
            if ymin > ymax:
                continue                # culled
            s0 = ymin // rows
            s1 = ymax // rows
            if s0 < 0:
                s0 = 0
            if s1 > nstrips - 1:
                s1 = nstrips - 1
            for st in range(s0, s1 + 1):
                if p == 0:
                    offsets[st + 1] += 1
                else:
                    out[offsets[st]] = j | (cls << 12)
                    offsets[st] += 1
        if p == 0:
            for st in range(nstrips):
                offsets[st + 1] += offsets[st]
            if offsets[nstrips] > max_out:
                return -1
    total = offsets[nstrips - 1]
    for st in range(nstrips, 0, -1):    # the fill moved every offset one strip up
        offsets[st] = offsets[st - 1]
    offsets[0] = 0
    return total


def blend(px, i, cr, cg, cb, wgt):
    """Mix the colour (cr, cg, cb: 5, 6 and 5 bits) into wire-order pixel i with weight wgt of 256."""
    d = px[i]
    d = ((d >> 8) | (d << 8)) & 0xFFFF
    r = d >> 11
    g = (d >> 5) & 63
    b = d & 31
    v = ((r + ((cr - r) * wgt >> 8)) << 11) | ((g + ((cg - g) * wgt >> 8)) << 5) | (b + ((cb - b) * wgt >> 8))
    px[i] = ((v >> 8) | (v << 8)) & 0xFFFF


def wu_line(px, w, h, x0, y0, x1, y1, colour):
    """An anti-aliased line (Xiaolin Wu): each step covers two pixels across the
    line, weighted by its distance to them. Only the part inside the w x h strip
    is walked."""
    c = ((colour >> 8) | (colour << 8)) & 0xFFFF
    cr = c >> 11
    cg = (c >> 5) & 63
    cb = c & 31
    steep = abs(y1 - y0) > abs(x1 - x0)
    if steep:                           # walk along the longer axis
        x0, y0, x1, y1 = y0, x0, y1, x1
    if x0 > x1:
        x0, y0, x1, y1 = x1, y1, x0, y0
    dx = x1 - x0
    dy = y1 - y0
    m = max(dx, abs(y0), abs(y1))
    s = 16                              # fraction bits: fewer for far-off ends, so nothing overflows
    while m >> (30 - s):
        s -= 1
    grad = (dy << s) // dx if dx else 0
    lo = x0
    hi = x1
    if steep:                           # the walk runs over rows: only the strip's
        lim = h
    else:
        lim = w
        if grad:                        # and over columns: only those whose y is in the strip
            xa = x0 + ((-2 - y0) << s) // grad
            xb = x0 + ((h + 1 - y0) << s) // grad
            if xa > xb:
                xa, xb = xb, xa
            lo = max(lo, xa)
            hi = min(hi, xb)
        elif y0 < -1 or y0 > h:
            return
    lo = max(lo, 0)
    hi = min(hi, lim - 1)
    yf = (y0 << s) + grad * (lo - x0)
    for x in range(lo, hi + 1):
        yi = yf >> s
        f = (yf >> (s - 8)) & 0xFF
        if steep:                       # x is the row, yi the column
            if 0 <= yi < w:
                blend(px, x * w + yi, cr, cg, cb, 256 - f)
            if f and 0 <= yi + 1 < w:
                blend(px, x * w + yi + 1, cr, cg, cb, f)
        else:
            if 0 <= yi < h:
                blend(px, yi * w + x, cr, cg, cb, 256 - f)
            if f and 0 <= yi + 1 < h:
                blend(px, (yi + 1) * w + x, cr, cg, cb, f)
        yf += grad


def draw_bucket(entries, start, end, pc, sc, pr, se, sh, pixels, sp):
    """Draw the bucketed segments entries[start:end] into pixels, a strip of
    SP_W x SP_BAND pixels whose first row is screen row SP_OY (sp is the SP_*
    block of skyparams, which also carries the colours, the highlighted
    constellation's segment range and the anti-aliasing switch). pc/sc are the
    constellation pairs and screen points, pr the ring pairs, se/sh the
    ecliptic and horizon screen points."""
    px = memoryview(pixels).cast("H")
    w, h, oy = sp[SP_W], sp[SP_BAND], sp[SP_OY]
    for e in range(start, end):
        v = entries[e]
        cls = v >> 12
        j = v & 0xFFF
        if cls == 0:
            pairs, scr = pc, sc
            colour = sp[SP_HILITE] if sp[SP_HL_FIRST] <= j < sp[SP_HL_END] else sp[SP_LINE]
        elif cls == 2:
            pairs, scr, colour = pr, se, sp[SP_ECLIPTIC]
        else:
            pairs, scr, colour = pr, sh, sp[SP_HORIZON]
        a = pairs[2 * j]
        b = pairs[2 * j + 1]
        x0 = scr[2 * a]
        x1 = scr[2 * b]
        y0 = scr[2 * a + 1] - oy
        y1 = scr[2 * b + 1] - oy
        if (x0 < 0 and x1 < 0) or (x0 >= w and x1 >= w):
            continue
        if sp[SP_SMOOTH]:
            wu_line(px, w, h, x0, y0, x1, y1, colour)
            continue
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            if 0 <= x0 < w and 0 <= y0 < h:
                px[y0 * w + x0] = colour
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
                if (y0 >= h and sy > 0) or (y0 < 0 and sy < 0):
                    break


def ring(table, n, axes, out):
    """Points of a great circle into out (n Q15 vectors, 6 bytes each, as
    project() reads them): point i is c * a + s * b, with (c, s) the Q15
    cosine and sine pair i of table and a, b the Q15 axes in axes[0:3] and
    axes[3:6]."""
    ax, ay, az, bx, by, bz = axes[0], axes[1], axes[2], axes[3], axes[4], axes[5]
    for i in range(n):
        c = table[2 * i]
        s = table[2 * i + 1]
        x = max(-32767, min(32767, (c * ax + s * bx) >> 15))
        y = max(-32767, min(32767, (c * ay + s * by) >> 15))
        z = max(-32767, min(32767, (c * az + s * bz) >> 15))
        struct.pack_into("<hhh", out, i * VERT_BYTES, x, y, z)


def draw_strip(segs, seg_off, pc, sc, pr, se, sh, stars, star_off, lut, pixels, sp):
    """A whole strip in one call: the line buckets its rows cross (when
    SP_BUCKETS is set), then the star buckets its rows can see, on top. sp is
    the SP_* block of skyparams; seg_off and star_off are the bucket offsets
    of segs and stars."""
    rows = sp[SP_ROWS]
    last = sp[SP_NSTRIPS] - 1
    band = sp[SP_BAND]
    oy = sp[SP_OY]
    if sp[SP_BUCKETS]:
        k0 = min(max(oy // rows, 0), last)
        k1 = min(max((oy + band - 1) // rows, 0), last)
        start = seg_off[k0]
        end = seg_off[k1 + 1]
        if end > start:
            draw_bucket(segs, start, end, pc, sc, pr, se, sh, pixels, sp)
    k0 = min(max((oy - 2) // rows, 0), last)     # dots reach 2 px past a boundary
    k1 = min(max((oy + rows + 1) // rows, 0), last)
    start = star_off[k0]
    end = star_off[k1 + 1]
    if end > start:
        plot_list(memoryview(stars)[LIST_WORDS * start:], end - start, pixels, sp[SP_W], band, oy, lut)


def visible(scr, n, x1, y1, out, max_out):
    """Indices of the first n projected points (int16 pairs in scr) that lie on
    0 <= x < x1, 0 <= y < y1, in order, into out (at most max_out). Returns the
    count; culled points are never on screen."""
    c = 0
    for i in range(n):
        x = scr[2 * i]
        if x < 0 or x >= x1:
            continue
        y = scr[2 * i + 1]
        if y < 0 or y >= y1:
            continue
        if c == max_out:
            break
        out[c] = i
        c += 1
    return c
