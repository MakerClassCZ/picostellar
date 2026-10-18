#!/usr/bin/env python3
"""Render the sky on the host with the pure-Python kernel, to check the data
and the view maths as a picture before anything runs on a board.

    tools/render_host.py OUT.png [--zoom CONST] [--date Y-M-D-H]

Draws the full visible sky from Prague (disc) or, with --zoom, a 60-degree
field centred on a constellation, with lines, names and the planets.
"""
import array
import math
import os
import struct
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "sim"))   # micropython shim
import skyastro  # noqa: E402
import skykernel  # noqa: E402
import skyview  # noqa: E402

W, H = 320, 240
PRAGUE = (50.09, 14.42)


def rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


# 6 B-V classes x (bright, mid, dim)
COLOURS = [(170, 190, 255), (255, 255, 255), (255, 245, 220), (255, 225, 160), (255, 190, 120), (255, 150, 110)]
LUT = array.array("H")
for r, g, b in COLOURS:
    LUT.append(rgb565(r, g, b))
    LUT.append(rgb565(r * 2 // 3, g * 2 // 3, b * 2 // 3))
    LUT.append(rgb565(r // 3, g // 3, b // 3))


class Sky:
    def __init__(self, path):
        self.data = open(path, "rb").read()
        (magic, self.n_stars, self.n_verts, self.n_lines, self.n_const, self.n_names, _,
         self.o_stars, self.o_verts, self.o_lines, self.o_const, self.o_names, self.o_str,
         self.len_str, _) = struct.unpack_from("<4sHHHHHHIIIIIIII", self.data, 0)
        assert magic == b"SKY1"

    def string(self, off, ln):
        return self.data[self.o_str + off:self.o_str + off + ln].decode()

    def const(self, i):
        return struct.unpack_from("<hhhHH4sHBx", self.data, self.o_const + i * 18)

    def line(self, i):
        return struct.unpack_from("<HH", self.data, self.o_lines + i * 4)

    def name(self, i):
        return struct.unpack_from("<HHBx", self.data, self.o_names + i * 6)

    def star_vec(self, i):
        return struct.unpack_from("<hhh", self.data, self.o_stars + i * 8)


def main():
    out = sys.argv[1]
    zoom = sys.argv[sys.argv.index("--zoom") + 1] if "--zoom" in sys.argv else None
    date = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else "2026-10-14-20"
    y, mo, d, h = (int(v) for v in date.split("-"))
    day, frac = skyastro.from_calendar(y, mo, d, h)
    sky = Sky(os.path.join(HERE, "..", "sky.bin"))
    view = skyview.View(*PRAGUE)
    view.set_time(day, frac)
    params = skykernel.new_params()
    if zoom:
        for i in range(sky.n_const):
            rec = sky.const(i)
            if rec[5][:3].decode() == zoom:
                vx, vy, vz = rec[0] / 32767, rec[1] / 32767, rec[2] / 32767
                break
        else:
            raise SystemExit("no constellation " + zoom)
        ra = math.degrees(math.atan2(vy, vx)) % 360
        dec = math.degrees(math.asin(vz))
        az, alt = skyastro.equatorial_to_horizontal(ra, dec, view.lst, PRAGUE[0])
        print("%s at az %.1f alt %.1f" % (zoom, az, alt))
        k = int(H / 2 / math.tan(math.radians(60) / 4))   # 60 deg field top to bottom
        view.fill_params(params, az, alt, k, W, H, disc=False)
        params[skykernel.P_MAG_LIMIT] = 65
        params[skykernel.P_MAG_OFFSET] = -10
    else:
        view.fill_params(params, 180, 90, H // 2 - 2, W, H, disc=True)   # az 180 + alt 90: north at the top
        params[skykernel.P_MAG_LIMIT] = 50
        params[skykernel.P_MAG_OFFSET] = 0
    pixels = bytearray(W * H * 2)
    cat = memoryview(sky.data)[sky.o_stars:sky.o_stars + sky.n_stars * 8]
    drawn = skykernel.plot_stars(cat, sky.n_stars, params, pixels, LUT)
    print("stars drawn", drawn)

    img = Image.new("RGB", (W, H))
    px = img.load()
    hw = memoryview(pixels).cast("H")
    for yy in range(H):
        for xx in range(W):
            v = hw[yy * W + xx]
            px[xx, yy] = (((v >> 11) & 31) << 3, ((v >> 5) & 63) << 2, (v & 31) << 3)
    draw = ImageDraw.Draw(img)

    # constellation lines through the kernel's project()
    verts = memoryview(sky.data)[sky.o_verts:sky.o_verts + sky.n_verts * 6]
    scr = array.array("h", [0] * (2 * sky.n_verts))
    skykernel.project(verts, sky.n_verts, params, scr)
    for i in range(sky.n_lines):
        a, b = sky.line(i)
        if scr[2 * a] == skykernel.CULLED or scr[2 * b] == skykernel.CULLED:
            continue
        draw.line((scr[2 * a], scr[2 * a + 1], scr[2 * b], scr[2 * b + 1]), fill=(40, 70, 110))
    for i in range(sky.n_const):
        rec = sky.const(i)
        p = view.project((rec[0] / 32767, rec[1] / 32767, rec[2] / 32767), params)
        if p:
            draw.text((p[0] - 6, p[1] - 4), rec[5][:3].decode(), fill=(90, 110, 150))
    for i in range(sky.n_names):
        star, off, ln = sky.name(i)
        if star > 60:
            continue
        v = sky.star_vec(star)
        p = view.project((v[0] / 32767, v[1] / 32767, v[2] / 32767), params)
        if p:
            draw.text((p[0] + 3, p[1] - 10), sky.string(off, ln), fill=(200, 200, 120))
    for name, (ra, dec, extra) in skyastro.bodies(day, frac).items():
        p = view.project(view.equatorial(ra, dec), params)
        if p:
            r = 5 if name in ("Sun", "Moon") else 2
            draw.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), outline=(255, 120, 0))
            draw.text((p[0] + 6, p[1] - 4), name, fill=(255, 120, 0))
    if not zoom:
        k = params[skykernel.P_K]
        cx, cy = params[skykernel.P_CX], params[skykernel.P_CY]
        draw.ellipse((cx - k, cy - k, cx + k, cy + k), outline=(60, 60, 60))
        for label, az in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
            p = view.project(view.horizontal(az, 0), params)
            draw.text((p[0] - 3, p[1] - 5), label, fill=(120, 120, 120))
    img.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
