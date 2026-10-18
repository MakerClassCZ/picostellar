"""The picostellar demo's kernels as @micropython.viper machine code.

Same contract as skykernel.py (the pure Python reference), function by function;
skykernel's plot_stars (the host renderer) and draw_lines (the test reference)
have no native twin.
Build with

    mpy-cross -march=armv7emsp -O3 -o skyviper.armv7emsp.mpy skyviper.py

and put the .mpy in lib/ (armv6m for an RP2040). The app imports skykernel when
no native build matches the board.
"""
import micropython
from micropython import const

P_W = const(0)
P_H = const(1)
P_CX = const(2)
P_CY = const(3)
P_K = const(4)
P_ZMIN = const(5)
P_R2 = const(6)
P_MAG_LIMIT = const(7)
P_MAG_OFFSET = const(8)
P_M00 = const(9)
P_M01 = const(10)
P_M02 = const(11)
P_M10 = const(12)
P_M11 = const(13)
P_M12 = const(14)
P_M20 = const(15)
P_M21 = const(16)
P_M22 = const(17)
P_UX = const(18)
P_UY = const(19)
P_UZ = const(20)
P_HMIN = const(21)
SP_W = const(0)                    # the per-strip block, see skyparams
SP_BAND = const(1)
SP_OY = const(2)
SP_LINE = const(3)
SP_HILITE = const(4)
SP_ECLIPTIC = const(5)
SP_HORIZON = const(6)
SP_HL_FIRST = const(7)
SP_HL_END = const(8)
SP_SMOOTH = const(9)
SP_ROWS = const(10)
SP_NSTRIPS = const(11)
SP_BUCKETS = const(12)


@micropython.viper
def project(vecs: ptr16, n: int, params: ptr32, out: ptr16):
    cx = params[P_CX]
    cy = params[P_CY]
    k = params[P_K]
    zmin = params[P_ZMIN]
    m00 = params[P_M00]
    m01 = params[P_M01]
    m02 = params[P_M02]
    m10 = params[P_M10]
    m11 = params[P_M11]
    m12 = params[P_M12]
    m20 = params[P_M20]
    m21 = params[P_M21]
    m22 = params[P_M22]
    for i in range(n):
        x = int(vecs[i * 3])
        if x >= 32768:
            x -= 65536
        y = int(vecs[i * 3 + 1])
        if y >= 32768:
            y -= 65536
        z = int(vecs[i * 3 + 2])
        if z >= 32768:
            z -= 65536
        zz = (m20 * x + m21 * y + m22 * z) >> 15
        if zz < zmin:
            out[2 * i] = 32768          # -32768 as uint16
            out[2 * i + 1] = 32768
            continue
        xx = (m00 * x + m01 * y + m02 * z) >> 15
        yy = (m10 * x + m11 * y + m12 * z) >> 15
        d = 32768 + zz
        sx = cx + (xx * k) // d
        sy = cy - (yy * k) // d
        if sx > 32767:
            sx = 32767
        elif sx < -32767:
            sx = -32767
        if sy > 32767:
            sy = 32767
        elif sy < -32767:
            sy = -32767
        out[2 * i] = sx & 0xFFFF
        out[2 * i + 1] = sy & 0xFFFF


@micropython.viper
def segment_bounds(lines: ptr16, n: int, scr: ptr16, out: ptr16):
    for i in range(n):
        a = int(lines[2 * i])
        b = int(lines[2 * i + 1])
        if int(scr[2 * a]) == 32768 or int(scr[2 * b]) == 32768:     # CULLED
            out[2 * i] = 32767
            out[2 * i + 1] = 32768          # -32768 as uint16
            continue
        y0 = int(scr[2 * a + 1])
        if y0 >= 32768:
            y0 -= 65536
        y1 = int(scr[2 * b + 1])
        if y1 >= 32768:
            y1 -= 65536
        if y0 < y1:
            out[2 * i] = y0 & 0xFFFF
            out[2 * i + 1] = y1 & 0xFFFF
        else:
            out[2 * i] = y1 & 0xFFFF
            out[2 * i + 1] = y0 & 0xFFFF


@micropython.viper
def project_stars(cat: ptr8, n: int, params: ptr32, out: ptr16, max_out: int) -> int:
    cx = params[P_CX]
    cy = params[P_CY]
    k = params[P_K]
    zmin = params[P_ZMIN]
    r2 = params[P_R2]
    mag_limit = params[P_MAG_LIMIT]
    mag_offset = params[P_MAG_OFFSET]
    m00 = params[P_M00]
    m01 = params[P_M01]
    m02 = params[P_M02]
    m10 = params[P_M10]
    m11 = params[P_M11]
    m12 = params[P_M12]
    m20 = params[P_M20]
    m21 = params[P_M21]
    m22 = params[P_M22]
    ux = params[P_UX]
    uy = params[P_UY]
    uz = params[P_UZ]
    hmin = params[P_HMIN]
    cat16 = ptr16(cat)
    count = 0
    for i in range(n):
        if count >= max_out:
            break
        b = i * 8
        mag = int(cat[b + 6])
        if mag >= 128:
            mag -= 256
        if mag > mag_limit:
            break
        x = int(cat16[(b >> 1)])
        if x >= 32768:
            x -= 65536
        y = int(cat16[(b >> 1) + 1])
        if y >= 32768:
            y -= 65536
        z = int(cat16[(b >> 1) + 2])
        if z >= 32768:
            z -= 65536
        zz = (m20 * x + m21 * y + m22 * z) >> 15
        if zz < zmin:
            continue
        if ((ux * x + uy * y + uz * z) >> 15) < hmin:
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
        bv = int(cat[b + 7])
        if bv >= 128:
            bv -= 256
        if bv == 127:
            col = 1
        elif bv < -1:
            col = 0
        elif bv < 3:
            col = 1
        elif bv < 6:
            col = 2
        elif bv < 10:
            col = 3
        elif bv < 15:
            col = 4
        else:
            col = 5
        m = mag + mag_offset
        if m < 10:
            size = 4
        elif m < 25:
            size = 3
        elif m < 40:
            size = 2
        elif m < 50:
            size = 1
        else:
            size = 0
        if sx > 32767:
            sx = 32767
        elif sx < -32767:
            sx = -32767
        if sy > 32767:
            sy = 32767
        elif sy < -32767:
            sy = -32767
        o = count * 4
        out[o] = sx & 0xFFFF
        out[o + 1] = sy & 0xFFFF
        out[o + 2] = size
        out[o + 3] = col
        count += 1
    return count


# Star stamps for sizes 2, 3 and 4: (dx + 2, dy + 2, level), as in skykernel.
_STAMPS = bytes((2, 2, 0, 1, 2, 1, 3, 2, 1, 2, 1, 1, 2, 3, 1,
                 1, 1, 2, 3, 1, 2, 1, 3, 2, 3, 3, 2,
                 2, 2, 0, 1, 2, 0, 3, 2, 0, 2, 1, 0, 2, 3, 0,
                 1, 1, 1, 3, 1, 1, 1, 3, 1, 3, 3, 1, 0, 2, 2, 4, 2, 2, 2, 0, 2, 2, 4, 2,
                 1, 1, 0, 2, 1, 0, 3, 1, 0, 1, 2, 0, 2, 2, 0, 3, 2, 0, 1, 3, 0, 2, 3, 0,
                 3, 3, 0, 0, 2, 1, 4, 2, 1, 2, 0, 1, 2, 4, 1,
                 0, 1, 2, 0, 3, 2, 4, 1, 2, 4, 3, 2, 1, 0, 2, 3, 0, 2, 1, 4, 2, 3, 4, 2))


@micropython.viper
def plot_list(lst: ptr16, count: int, pixels: ptr16, w: int, h: int, oy: int, lut: ptr16) -> int:
    st = ptr8(_STAMPS)
    drawn = 0
    for i in range(count):
        o = i * 4
        sy = int(lst[o + 1])
        if sy >= 32768:
            sy -= 65536
        sy -= oy
        if sy < -2 or sy >= h + 2:
            continue
        sx = int(lst[o])
        if sx >= 32768:
            sx -= 65536
        if sx < -2 or sx >= w + 2:
            continue
        size = int(lst[o + 2])
        col = int(lst[o + 3]) * 3
        drawn += 1
        if size < 2:                        # one pixel: dim (size 0) or mid (size 1)
            e0 = 0
            e1 = 1
        elif size == 2:
            e0 = 0
            e1 = 9
        elif size == 3:
            e0 = 9
            e1 = 22
        else:
            e0 = 22
            e1 = 43
        e = e0
        while e < e1:
            if size < 2:
                x = sx
                y = sy
                c = int(lut[col + 2 - size])
            else:
                x = sx + int(st[3 * e]) - 2
                y = sy + int(st[3 * e + 1]) - 2
                c = int(lut[col + int(st[3 * e + 2])])
            e += 1
            if x >= 0 and x < w and y >= 0 and y < h:
                k = y * w + x                       # the brighter of pixel and dot, per channel
                d = int(pixels[k])
                d = ((d >> 8) | (d << 8)) & 0xFFFF
                c = ((c >> 8) | (c << 8)) & 0xFFFF
                v = d & 0xF800
                if c & 0xF800 > v:
                    v = c & 0xF800
                if c & 0x07E0 > d & 0x07E0:
                    v |= c & 0x07E0
                else:
                    v |= d & 0x07E0
                if c & 0x001F > d & 0x001F:
                    v |= c & 0x001F
                else:
                    v |= d & 0x001F
                pixels[k] = ((v >> 8) | (v << 8)) & 0xFFFF
    return drawn


@micropython.viper
def sort_list(lst: ptr16, count: int, rows: int, nstrips: int, offsets: ptr16, out: ptr16):
    for k in range(nstrips + 1):
        offsets[k] = 0
    for i in range(count):
        sy = int(lst[4 * i + 1])
        if sy >= 32768:
            sy -= 65536
        k = sy // rows
        if k < 0:
            k = 0
        elif k >= nstrips:
            k = nstrips - 1
        offsets[k + 1] += 1
    for k in range(nstrips):
        offsets[k + 1] += offsets[k]
    for i in range(count):
        o = 4 * i
        sy = int(lst[o + 1])
        if sy >= 32768:
            sy -= 65536
        k = sy // rows
        if k < 0:
            k = 0
        elif k >= nstrips:
            k = nstrips - 1
        pos = int(offsets[k]) * 4
        out[pos] = lst[o]
        out[pos + 1] = lst[o + 1]
        out[pos + 2] = lst[o + 2]
        out[pos + 3] = lst[o + 3]
        offsets[k] += 1
    k = nstrips
    while k > 0:
        offsets[k] = offsets[k - 1]
        k -= 1
    offsets[0] = 0


@micropython.viper
def project_pick(cat: ptr8, n: int, params: ptr32, mag_limit: int, base: int, out: ptr16, max_out: int) -> int:
    w = params[P_W]
    h = params[P_H]
    cx = params[P_CX]
    cy = params[P_CY]
    k = params[P_K]
    zmin = params[P_ZMIN]
    r2 = params[P_R2]
    m00 = params[P_M00]
    m01 = params[P_M01]
    m02 = params[P_M02]
    m10 = params[P_M10]
    m11 = params[P_M11]
    m12 = params[P_M12]
    m20 = params[P_M20]
    m21 = params[P_M21]
    m22 = params[P_M22]
    ux = params[P_UX]
    uy = params[P_UY]
    uz = params[P_UZ]
    hmin = params[P_HMIN]
    cat16 = ptr16(cat)
    count = 0
    for i in range(n):
        if count >= max_out:
            break
        b = i * 8
        mag = int(cat[b + 6])
        if mag >= 128:
            mag -= 256
        if mag > mag_limit:
            break
        x = int(cat16[(b >> 1)])
        if x >= 32768:
            x -= 65536
        y = int(cat16[(b >> 1) + 1])
        if y >= 32768:
            y -= 65536
        z = int(cat16[(b >> 1) + 2])
        if z >= 32768:
            z -= 65536
        zz = (m20 * x + m21 * y + m22 * z) >> 15
        if zz < zmin:
            continue
        if ((ux * x + uy * y + uz * z) >> 15) < hmin:
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
        if sx < 0 or sx >= w or sy < 0 or sy >= h:
            continue
        out[3 * count] = sx
        out[3 * count + 1] = sy
        out[3 * count + 2] = base + i
        count += 1
    return count


@micropython.viper
def pick_dir(pick: ptr16, n: int, cx: int, cy: int, dx: int, dy: int, cone: int) -> int:
    best = -1
    best_score = 0x3FFFFFFF               # a small int, so viper keeps it a machine word
    for i in range(n):
        x = int(pick[3 * i])
        if x >= 32768:
            x -= 65536
        y = int(pick[3 * i + 1])
        if y >= 32768:
            y -= 65536
        ox = x - cx
        oy = y - cy
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


@micropython.viper
def pick_near(pick: ptr16, n: int, x: int, y: int, r2: int) -> int:
    best = -1
    best_d = r2 + 1
    for i in range(n):
        px = int(pick[3 * i])
        if px >= 32768:
            px -= 65536
        py = int(pick[3 * i + 1])
        if py >= 32768:
            py -= 65536
        ox = px - x
        oy = py - y
        d = ox * ox + oy * oy
        if d < best_d:
            best_d = d
            best = i
    return best


@micropython.viper
def bucket_lines(bc: ptr16, nc: int, be: ptr16, bh: ptr16, nr: int, flags: int, rows: int, nstrips: int,
                 offsets: ptr16, out: ptr16, max_out: int) -> int:
    for k in range(nstrips + 1):
        offsets[k] = 0
    p = 0
    while p < 2:
        for i in range(nc + 2 * nr):
            if i < nc:
                if not (flags & 1):
                    continue
                ymin = int(bc[2 * i])
                ymax = int(bc[2 * i + 1])
                j = i
                cls = 0
            elif i < nc + nr:
                if not (flags & 2):
                    continue
                j = i - nc
                ymin = int(be[2 * j])
                ymax = int(be[2 * j + 1])
                cls = 2
            else:
                j = i - nc - nr
                ymin = int(bh[2 * j])
                ymax = int(bh[2 * j + 1])
                cls = 3
            if ymin >= 32768:
                ymin -= 65536
            if ymax >= 32768:
                ymax -= 65536
            if ymin > ymax:
                continue
            s0 = ymin // rows
            s1 = ymax // rows
            if s0 < 0:
                s0 = 0
            if s1 > nstrips - 1:
                s1 = nstrips - 1
            st = s0
            while st <= s1:
                if p == 0:
                    offsets[st + 1] += 1
                else:
                    pos = int(offsets[st])
                    out[pos] = j | (cls << 12)
                    offsets[st] = pos + 1
                st += 1
        if p == 0:
            for st in range(nstrips):
                offsets[st + 1] += offsets[st]
            if int(offsets[nstrips]) > max_out:
                return -1
        p += 1
    total = int(offsets[nstrips - 1])
    st = nstrips
    while st > 0:
        offsets[st] = offsets[st - 1]
        st -= 1
    offsets[0] = 0
    return total


@micropython.viper
def draw_bucket(entries: ptr16, start: int, end: int, pc: ptr16, sc: ptr16, pr: ptr16, se: ptr16, sh: ptr16,
                pixels: ptr16, sp: ptr32):
    w = sp[SP_W]
    h = sp[SP_BAND]
    oy = sp[SP_OY]
    aa = sp[SP_SMOOTH]
    for e in range(start, end):
        v = int(entries[e])
        cls = v >> 12
        j = v & 0xFFF
        if cls == 0:
            a = int(pc[2 * j])
            b = int(pc[2 * j + 1])
            x0 = int(sc[2 * a])
            y0 = int(sc[2 * a + 1])
            x1 = int(sc[2 * b])
            y1 = int(sc[2 * b + 1])
            if j >= sp[SP_HL_FIRST] and j < sp[SP_HL_END]:
                colour = sp[SP_HILITE]
            else:
                colour = sp[SP_LINE]
        else:
            a = int(pr[2 * j])
            b = int(pr[2 * j + 1])
            if cls == 2:
                x0 = int(se[2 * a])
                y0 = int(se[2 * a + 1])
                x1 = int(se[2 * b])
                y1 = int(se[2 * b + 1])
                colour = sp[SP_ECLIPTIC]
            else:
                x0 = int(sh[2 * a])
                y0 = int(sh[2 * a + 1])
                x1 = int(sh[2 * b])
                y1 = int(sh[2 * b + 1])
                colour = sp[SP_HORIZON]
        if x0 >= 32768:
            x0 -= 65536
        if x1 >= 32768:
            x1 -= 65536
        if y0 >= 32768:
            y0 -= 65536
        if y1 >= 32768:
            y1 -= 65536
        y0 -= oy
        y1 -= oy
        if (x0 < 0 and x1 < 0) or (x0 >= w and x1 >= w):
            continue
        if aa:                              # anti-aliased (Wu), the same steps as skykernel.wu_line
            c = ((colour >> 8) | (colour << 8)) & 0xFFFF
            cr = c >> 11
            cg = (c >> 5) & 63
            cb = c & 31
            ax = x1 - x0
            if ax < 0:
                ax = -ax
            ay = y1 - y0
            if ay < 0:
                ay = -ay
            steep = ay > ax
            if steep:
                t = x0
                x0 = y0
                y0 = t
                t = x1
                x1 = y1
                y1 = t
            if x0 > x1:
                t = x0
                x0 = x1
                x1 = t
                t = y0
                y0 = y1
                y1 = t
            dx = x1 - x0
            dy = y1 - y0
            m = dx
            t = y0 if y0 >= 0 else -y0
            if t > m:
                m = t
            t = y1 if y1 >= 0 else -y1
            if t > m:
                m = t
            s = 16
            while m >> (30 - s):
                s -= 1
            grad = 0
            if dx:
                grad = (dy << s) // dx
            lo = x0
            hi = x1
            lim = h
            if not steep:
                lim = w
                if grad:
                    xa = x0 + ((-2 - y0) << s) // grad
                    xb = x0 + ((h + 1 - y0) << s) // grad
                    if xa > xb:
                        t = xa
                        xa = xb
                        xb = t
                    if xa > lo:
                        lo = xa
                    if xb < hi:
                        hi = xb
                elif y0 < -1 or y0 > h:
                    continue
            if lo < 0:
                lo = 0
            if hi > lim - 1:
                hi = lim - 1
            yf = (y0 << s) + grad * (lo - x0)
            x = lo
            while x <= hi:
                yi = yf >> s
                f = (yf >> (s - 8)) & 0xFF
                q = 0
                while q < 2:                # the pixel at yi (weight 256 - f), then at yi + 1 (f)
                    if q == 0:
                        wgt = 256 - f
                        yy = yi
                    else:
                        wgt = f
                        yy = yi + 1
                    q += 1
                    if wgt == 0:
                        continue
                    if steep:
                        if yy < 0 or yy >= w:
                            continue
                        k = x * w + yy
                    else:
                        if yy < 0 or yy >= h:
                            continue
                        k = yy * w + x
                    d = int(pixels[k])
                    d = ((d >> 8) | (d << 8)) & 0xFFFF
                    r = d >> 11
                    g = (d >> 5) & 63
                    b = d & 31
                    v = ((r + (((cr - r) * wgt) >> 8)) << 11) | ((g + (((cg - g) * wgt) >> 8)) << 5) | \
                        (b + (((cb - b) * wgt) >> 8))
                    pixels[k] = ((v >> 8) | (v << 8)) & 0xFFFF
                yf += grad
                x += 1
            continue
        dx = x1 - x0
        if dx < 0:
            dx = -dx
        dy = y1 - y0
        if dy < 0:
            dy = -dy
        dy = -dy
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            if x0 >= 0 and x0 < w and y0 >= 0 and y0 < h:
                pixels[y0 * w + x0] = colour
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


@micropython.viper
def ring(table: ptr16, n: int, axes: ptr32, out: ptr16):
    ax = axes[0]
    ay = axes[1]
    az = axes[2]
    bx = axes[3]
    by = axes[4]
    bz = axes[5]
    for i in range(n):
        c = int(table[2 * i])
        if c >= 32768:
            c -= 65536
        s = int(table[2 * i + 1])
        if s >= 32768:
            s -= 65536
        x = (c * ax + s * bx) >> 15
        y = (c * ay + s * by) >> 15
        z = (c * az + s * bz) >> 15
        if x > 32767:
            x = 32767
        if x < -32767:
            x = -32767
        if y > 32767:
            y = 32767
        if y < -32767:
            y = -32767
        if z > 32767:
            z = 32767
        if z < -32767:
            z = -32767
        out[3 * i] = x
        out[3 * i + 1] = y
        out[3 * i + 2] = z


@micropython.viper
def draw_strip(segs, seg_off, pc, sc, pr, se, sh, stars, star_off, lut, pixels, sp):
    p = ptr32(sp)
    w = p[SP_W]
    band = p[SP_BAND]
    oy = p[SP_OY]
    rows = p[SP_ROWS]
    last = p[SP_NSTRIPS] - 1
    if p[SP_BUCKETS]:
        so = ptr16(seg_off)
        k0 = oy // rows
        k1 = (oy + band - 1) // rows
        if k0 < 0:
            k0 = 0
        if k0 > last:
            k0 = last
        if k1 < 0:
            k1 = 0
        if k1 > last:
            k1 = last
        start = int(so[k0])
        end = int(so[k1 + 1])
        if end > start:
            draw_bucket(segs, start, end, pc, sc, pr, se, sh, pixels, sp)
    ko = ptr16(star_off)
    k0 = (oy - 2) // rows
    k1 = (oy + rows + 1) // rows
    if k0 < 0:
        k0 = 0
    if k0 > last:
        k0 = last
    if k1 < 0:
        k1 = 0
    if k1 > last:
        k1 = last
    start = int(ko[k0])
    end = int(ko[k1 + 1])
    if end > start:
        plot_list(int(ptr16(stars)) + 8 * start, end - start, pixels, w, band, oy, lut)


@micropython.viper
def visible(scr: ptr16, n: int, x1: int, y1: int, out: ptr16, max_out: int) -> int:
    c = 0
    for i in range(n):
        x = int(scr[2 * i])
        if x >= 32768:
            x -= 65536
        if x < 0 or x >= x1:
            continue
        y = int(scr[2 * i + 1])
        if y >= 32768:
            y -= 65536
        if y < 0 or y >= y1:
            continue
        if c == max_out:
            break
        out[c] = i
        c += 1
    return c
