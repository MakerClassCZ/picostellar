# Device check: the viper kernels must produce the same results as the Python
# reference, and this prints how long each takes. Needs sky.bin at the root,
# skykernel/skyview/skyastro and skyviper.<arch>.mpy in lib/. Works on an RP2040:
# the stars come from the first flash run only and the lists shrink to fit.
print("(first line is swallowed by the devagent runner)")
import array
import gc
import struct
import time

import storage
import skyastro
import skykernel
import skyview
import skyviper

W, H, ROWS = 320, 240, 8
gc.collect()
N_LIST = 1500 if gc.mem_free() < 200000 else 2500
f = open("/sky.bin", "rb")
views = storage.map_file(f)
f.close()
runs = []
pos = 0
for v in views:
    runs.append((pos, v))
    pos += len(v)


def section(off, ln):
    for start, v in runs:
        if start <= off and off + ln <= start + len(v):
            return v[off - start:off - start + ln]
    out = bytearray(ln)
    for start, v in runs:
        lo = max(off, start)
        hi = min(off + ln, start + len(v))
        if lo < hi:
            out[lo - off:hi - off] = v[lo - start:hi - start]
    return out


hdr = struct.unpack_from("<4sHHHHHHIIIIIIII", section(0, 48), 0)
n_stars, n_verts, n_lines, o_stars, o_verts, o_lines = hdr[1], hdr[2], hdr[3], hdr[7], hdr[8], hdr[9]
for start, v in runs:
    if start <= o_stars < start + len(v):
        n_cat = min(n_stars, (start + len(v) - o_stars) // 8)
        cat = v[o_stars - start:o_stars - start + n_cat * 8]
        break
verts = section(o_verts, n_verts * 6)
lines = memoryview(section(o_lines, n_lines * 4)).cast("H")
print("K runs", [len(v) for v in views], "stars checked", n_cat, "of", n_stars, "list", N_LIST)
lut = array.array("H", [0x1234 + i * 0x111 for i in range(18)])
view = skyview.View(50.09, 14.42)
view.set_time(*skyastro.from_calendar(2026, 10, 14, 20))
la = array.array("h", [0]) * (4 * N_LIST)
lb = array.array("h", [0]) * (4 * N_LIST)
qa = array.array("h", [0]) * (4 * N_LIST)
qb = array.array("h", [0]) * (4 * N_LIST)
sa = array.array("h", [0]) * (2 * n_verts)
sb = array.array("h", [0]) * (2 * n_verts)
ba = array.array("h", [0]) * (2 * n_lines)
bb = array.array("h", [0]) * (2 * n_lines)
pa = bytearray(W * ROWS * 2)
pb = bytearray(W * ROWS * 2)
pc = bytearray(W * ROWS * 2)
nstrips = H // ROWS
oa = array.array("h", [0]) * (nstrips + 2)
ob = array.array("h", [0]) * (nstrips + 2)
gc.collect()
print("K free with buffers", gc.mem_free())


def t(fn, n=3):
    best = None
    for _ in range(n):
        t0 = time.monotonic_ns()
        r = fn()
        dt = (time.monotonic_ns() - t0) // 1000
        best = dt if best is None else min(best, dt)
    return best, r


for label, az, alt, k, disc, lim, off in (("full", 180, 90, 116, True, 50, 0), ("zoom", 204, 50, 400, False, 65, -10)):
    params = skykernel.new_params()
    view.fill_params(params, az, alt, k, W, H, disc=disc)
    params[skykernel.P_MAG_LIMIT] = lim
    params[skykernel.P_MAG_OFFSET] = off
    tv, na = t(lambda: skyviper.project_stars(cat, n_cat, params, la, N_LIST))
    tp, nb = t(lambda: skykernel.project_stars(cat, n_cat, params, lb, N_LIST), 1)
    print("K %s project_stars viper %d us (%d) python %d us (%d) lists equal %s" % (
        label, tv, na, tp, nb, na == nb and la[:4 * na] == lb[:4 * nb]))
    tv, _ = t(lambda: skyviper.project(verts, n_verts, params, sa))
    tp, _ = t(lambda: skykernel.project(verts, n_verts, params, sb), 1)
    print("K %s project viper %d us python %d us equal %s" % (label, tv, tp, sa == sb))
    skyviper.segment_bounds(lines, n_lines, sa, ba)
    skykernel.segment_bounds(lines, n_lines, sb, bb)
    print("K %s segment_bounds equal %s" % (label, ba == bb))
    tsv, _ = t(lambda: skyviper.sort_list(la, na, ROWS, nstrips, oa, qa))
    tsp, _ = t(lambda: skykernel.sort_list(lb, nb, ROWS, nstrips, ob, qb), 1)
    print("K %s sort_list viper %d us python %d us offsets equal %s sorted equal %s" % (
        label, tsv, tsp, oa == ob, qa[:4 * na] == qb[:4 * nb]))
    strips_v = 0
    strips_p = 0
    equal = True
    bucket_equal = True
    for oy in range(0, H, ROWS):
        pa[:] = bytes(len(pa))
        pb[:] = bytes(len(pb))
        pc[:] = bytes(len(pc))
        k = oy // ROWS
        start = oa[k - 1 if k > 0 else 0]
        end = oa[k + 2 if k + 2 <= nstrips else nstrips]
        t0 = time.monotonic_ns()
        if end > start:
            skyviper.plot_list(memoryview(qa)[4 * start:], end - start, pa, W, ROWS, oy, lut)
        t1 = time.monotonic_ns()
        if end > start:
            skykernel.plot_list(memoryview(qb)[4 * start:], end - start, pb, W, ROWS, oy, lut)
        t2 = time.monotonic_ns()
        strips_v += t1 - t0
        strips_p += t2 - t1
        if pa != pb:
            equal = False
        skyviper.plot_list(la, na, pc, W, ROWS, oy, lut)          # unbucketed, for the dots
        if pa != pc:
            bucket_equal = False
    print("K %s dots x%d viper %d us python %d us pixels equal %s bucketed==full %s" % (
        label, nstrips, strips_v // 1000, strips_p // 1000, equal, bucket_equal))
# line buckets: one call per strip draws exactly what draw_lines draws over all segments
ring = array.array("H")
for i in range(36):
    ring.append(i)
    ring.append((i + 1) % 36)
ecl = array.array("h", [0]) * 72
hor = array.array("h", [0]) * 72
for i in range(36):                     # two arbitrary rings across the screen
    ecl[2 * i] = 20 + 8 * i
    ecl[2 * i + 1] = 30 + (i * 37) % 200
    hor[2 * i] = 300 - 8 * i
    hor[2 * i + 1] = 200 - (i * 23) % 180
be = array.array("h", [0]) * 72
bh = array.array("h", [0]) * 72
skyviper.segment_bounds(ring, 36, ecl, be)
skyviper.segment_bounds(ring, 36, hor, bh)
oa2 = array.array("h", [0]) * 32
ob2 = array.array("h", [0]) * 32
ga = array.array("H", [0]) * 3000
gb = array.array("H", [0]) * 3000
params = skykernel.new_params()
view.fill_params(params, 180, 90, 116, W, H, disc=True)
skyviper.project(verts, n_verts, params, sa)
skyviper.segment_bounds(lines, n_lines, sa, ba)
na = skyviper.bucket_lines(ba, n_lines, be, bh, 36, 3, ROWS, 30, oa2, ga, 3000)
nb = skykernel.bucket_lines(ba, n_lines, be, bh, 36, 3, ROWS, 30, ob2, gb, 3000)
print("K bucket_lines viper %d python %d entries, offsets equal %s, entries equal %s" % (
    na, nb, oa2[:31] == ob2[:31], na == nb and ga[:na] == gb[:nb]))
spa = array.array("i", [W, ROWS, 0, 0x4321, 0x7777, 0x1111, 0x2222, 100, 140, 0])   # SP_* order
same = True
tb = 0
for oy in range(0, H, ROWS):
    k = oy // ROWS
    pa[:] = bytes(len(pa))
    pb[:] = bytes(len(pb))
    pc[:] = bytes(len(pc))
    spa[2] = oy
    t0 = time.monotonic_ns()
    skyviper.draw_bucket(ga, oa2[k], oa2[k + 1], lines, sa, ring, ecl, hor, pa, spa)
    t1 = time.monotonic_ns()
    skykernel.draw_bucket(gb, ob2[k], ob2[k + 1], lines, sa, ring, ecl, hor, pb, spa)
    # the same picture from the Python draw_lines over everything (the highlight drawn over it)
    skykernel.draw_lines(lines, n_lines, sa, ba, pc, W, ROWS, 0x4321, oy)
    skykernel.draw_lines(memoryview(lines)[200:], 40, sa, memoryview(ba)[200:], pc, W, ROWS, 0x7777, oy)
    skykernel.draw_lines(ring, 36, ecl, be, pc, W, ROWS, 0x1111, oy)
    skykernel.draw_lines(ring, 36, hor, bh, pc, W, ROWS, 0x2222, oy)
    tb += t1 - t0
    same = same and pa == pb and pa == pc
print("K draw_bucket x30 viper %d us, pixels viper == python == draw_lines %s" % (tb // 1000, same))
# anti-aliased: viper and Python must agree pixel for pixel, over a starry background
spa[3] = 0x6a24                          # real colours (wire order), so the blend has work to do
spa[4] = 0x9f6d
spa[5] = 0xec69
spa[6] = 0xcb5a
spa[9] = 1
same = True
ta = 0
for oy in range(0, H, ROWS):
    k = oy // ROWS
    for i in range(0, len(pa), 2):       # the same non-flat background in both
        pa[i] = (i * 37) & 0xFF
        pa[i + 1] = (i * 11) & 0x1F
    pb[:] = pa
    spa[2] = oy
    t0 = time.monotonic_ns()
    skyviper.draw_bucket(ga, oa2[k], oa2[k + 1], lines, sa, ring, ecl, hor, pa, spa)
    ta += time.monotonic_ns() - t0
    skykernel.draw_bucket(gb, ob2[k], ob2[k + 1], lines, sa, ring, ecl, hor, pb, spa)
    same = same and pa == pb
print("K draw_bucket anti-aliased x30 viper %d us (plain %d us), pixels viper == python %s" % (
    ta // 1000, tb // 1000, same))
# a long line with far-off ends (fewer fraction bits) and a steep one, both ways round
far = array.array("h", [-9000, -30000, 9000, 31000, 160, -20000, 161, 20000, 30000, 4, -30000, 6, 5, 5, 300, 7])
fb = array.array("h", [0]) * 16
fp = array.array("H", [0, 1, 2, 3, 4, 5, 6, 7])
skyviper.segment_bounds(fp, 4, far, fb)
oo = array.array("h", [0]) * 32
ge = array.array("H", [0]) * 200
skyviper.bucket_lines(fb, 4, be, bh, 0, 1, ROWS, 30, oo, ge, 200)
spa[7] = spa[8] = 0
same = True
for oy in range(0, H, ROWS):
    k = oy // ROWS
    pa[:] = bytes(len(pa))
    pb[:] = bytes(len(pb))
    spa[2] = oy
    skyviper.draw_bucket(ge, oo[k], oo[k + 1], fp, far, ring, ecl, hor, pa, spa)
    skykernel.draw_bucket(ge, oo[k], oo[k + 1], fp, far, ring, ecl, hor, pb, spa)
    same = same and pa == pb
print("K anti-aliased far-off and steep lines viper == python %s" % same)
# ring: a great circle from two axes
tab = array.array("h", [0]) * 72
for i in range(36):
    tab[2 * i] = int(round(32767 * __import__("math").cos(i * 0.17453292)))
    tab[2 * i + 1] = int(round(32767 * __import__("math").sin(i * 0.17453292)))
axes = array.array("i", [23170, -16384, 10000, -5000, 20000, 25000])
ra_ = bytearray(36 * 6)
rb_ = bytearray(36 * 6)
tv, _ = t(lambda: skyviper.ring(tab, 36, axes, ra_))
skykernel.ring(tab, 36, axes, rb_)
print("K ring viper %d us, viper == python %s" % (tv, ra_ == rb_))
# draw_strip: one call per strip draws what draw_bucket + plot_list draw
sp13 = array.array("i", [W, ROWS, 0, 0x6a24, 0x9f6d, 0xec69, 0xcb5a, 100, 140, 1, ROWS, nstrips, 1])
same = True
same_old = True
tv = 0
for oy in range(0, H, ROWS):
    k = oy // ROWS
    sp13[1] = ROWS
    sp13[2] = oy
    pa[:] = bytes(len(pa))
    pb[:] = bytes(len(pb))
    pc[:] = bytes(len(pc))
    t0 = time.monotonic_ns()
    skyviper.draw_strip(ga, oa2, lines, sa, ring, ecl, hor, qa, oa, lut, pa, sp13)
    tv += time.monotonic_ns() - t0
    skykernel.draw_strip(gb, ob2, lines, sa, ring, ecl, hor, qa, oa, lut, pb, sp13)
    skyviper.draw_bucket(ga, oa2[k], oa2[k + 1], lines, sa, ring, ecl, hor, pc, sp13)
    k0 = max((oy - 2) // ROWS, 0)
    k1 = min((oy + ROWS + 1) // ROWS, nstrips - 1)
    if oa[k1 + 1] > oa[k0]:
        skyviper.plot_list(memoryview(qa)[4 * oa[k0]:], oa[k1 + 1] - oa[k0], pc, W, ROWS, oy, lut)
    same = same and pa == pb
    same_old = same_old and pa == pc
print("K draw_strip x%d viper %d us, viper == python %s, == draw_bucket + plot_list %s" % (
    nstrips, tv // 1000, same, same_old))
# visible: the projected points on screen (the star-name labels)
va = array.array("H", [0]) * 100
vb = array.array("H", [0]) * 100
same = True
for x1, y1, mx in ((W - 10, H - 12, 100), (W - 20, H - 12, 100), (W, H, 5), (100, 60, 100)):
    tv, na = t(lambda: skyviper.visible(sa, n_verts, x1, y1, va, mx))
    nb = skykernel.visible(sa, n_verts, x1, y1, vb, mx)
    same = same and na == nb and va[:na] == vb[:nb]
print("K visible viper %d us (%d of %d points), viper == python %s" % (tv, na, n_verts, same))
pa_ = array.array("h", [0]) * 1200
pb_ = array.array("h", [0]) * 1200
for label, az, alt, k, disc, lim in (("full", 180, 90, 116, True, 35), ("zoom", 204, 50, 400, False, 55)):
    params = skykernel.new_params()
    view.fill_params(params, az, alt, k, W, H, disc=disc)
    tv, na = t(lambda: skyviper.project_pick(cat, n_cat, params, lim, 7, pa_, 400))
    nb = skykernel.project_pick(cat, n_cat, params, lim, 7, pb_, 400)
    print("K %s project_pick viper %d us (%d) equal %s" % (label, tv, na, na == nb and pa_[:3 * na] == pb_[:3 * nb]))
    same = True
    for cx, cy in ((160, 120), (20, 30), (300, 200)):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            same = same and skyviper.pick_dir(pa_, na, cx, cy, dx, dy, 2) == skykernel.pick_dir(pb_, nb, cx, cy, dx, dy, 2)
        same = same and skyviper.pick_near(pa_, na, cx, cy, 400) == skykernel.pick_near(pb_, nb, cx, cy, 400)
    tv, _ = t(lambda: skyviper.pick_dir(pa_, na, 160, 120, 1, 0, 2))
    tp, _ = t(lambda: skykernel.pick_dir(pb_, nb, 160, 120, 1, 0, 2), 1)
    print("K %s pick_dir/pick_near equal %s, pick_dir viper %d us python %d us" % (label, same, tv, tp))
gc.collect()
print("K free after", gc.mem_free())
print("K DONE")
