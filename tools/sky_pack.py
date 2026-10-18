#!/usr/bin/env python3
"""Build sky.bin, the flash-mapped sky catalogue of the picostellar demo.

Sources, in SOURCE_DIR under these names (data/ in the repository; bsc5 may be gzipped):
  bsc5.catalog               Yale Bright Star Catalogue 5 (Hoffleit & Warren 1991), public domain:
                             https://cdsarc.cds.unistra.fr/ftp/V/50/catalog.gz (gunzip it)
  constellations.json,       d3-celestial by Olaf Frohn, BSD-3-Clause:
  constellations.lines.json  https://github.com/ofrohn/d3-celestial/tree/master/data
  IAU-CSN.txt                IAU Working Group on Star Names, CC BY 4.0:
                             https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt
Needs pyephem (each star's constellation).

Everything the device reads is little-endian and at an even offset, so a viper
kernel can walk it with ptr16 straight from storage.map_file():

  header 48 B   b"SKY1", counts and section offsets (see HEADER)
  stars  8 B    x, y, z int16 (unit vector, J2000 equatorial, Q15), mag int8
                (Vmag * 10), bv int8 (B-V * 10, 127 = unknown); sorted by Vmag
  verts  6 B    x, y, z int16 of the constellation line vertices
  lines  4 B    a, b uint16 vertex indices, grouped by constellation
  const 18 B    x, y, z int16 label position, first_line u16, n_lines u16,
                abbr 4 B (3 letters + NUL), name_off u16, name_len u8,
                rank u8 (1 = the most prominent, 3 = the faintest, d3-celestial)
  names  6 B    star u16, name_off u16, name_len u8, pad
  strings       ASCII, referenced by (off, len) from const and names
  star_const 1 B per star: index of the star's constellation in the const
                table (IAU boundaries via pyephem); its offset is the header's
                last field, 0 in files without the section

Usage: sky_pack.py [SOURCE_DIR] [OUT_FILE] [--max-mag M]   (defaults: data/ and sky.bin next to it)
"""
import json
import math
import struct
import sys
import unicodedata

import ephem                          # host only: constellation membership from the IAU boundaries

HEADER = "<4sHHHHHHIIIIIIII"      # magic, n_stars, n_verts, n_lines, n_const, n_names, reserved, 8 offsets/lengths
HEADER_SIZE = struct.calcsize(HEADER)
assert HEADER_SIZE == 48


def unit(ra_deg, dec_deg):
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    c = math.cos(dec)
    return (c * math.cos(ra), c * math.sin(ra), math.sin(dec))


def q15(v):
    return max(-32767, min(32767, int(round(v * 32767))))


def read_bsc5(path, max_mag):
    """-> list of (vmag, ra_deg, dec_deg, bv, hr, hd) for stars with a J2000 position."""
    stars = []
    import gzip, os
    if not os.path.exists(path) and os.path.exists(path + ".gz"):
        path += ".gz"
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="latin-1") as f:
        for line in f:
            hr = int(line[0:4])
            vmag = line[102:107].strip()
            rah = line[75:77].strip()
            if not vmag or not rah:
                continue                      # novae and non-stellar entries have no position
            vmag = float(vmag)
            if vmag > max_mag:
                continue
            ra = (int(line[75:77]) + int(line[77:79]) / 60 + float(line[79:83]) / 3600) * 15
            sign = -1 if line[83] == "-" else 1
            dec = sign * (int(line[84:86]) + int(line[86:88]) / 60 + int(line[88:90]) / 3600)
            bv = line[109:114].strip()
            bv = float(bv) if bv else None
            hd = line[25:31].strip()
            stars.append((vmag, ra, dec, bv, hr, int(hd) if hd else None))
    stars.sort(key=lambda s: s[0])
    return stars


def read_lines(path):
    """-> {abbr: [((ra, dec), (ra, dec)), ...]} with RA in 0..360."""
    out = {}
    for feat in json.load(open(path))["features"]:
        segs = []
        for part in feat["geometry"]["coordinates"]:
            for (ra0, de0), (ra1, de1) in zip(part, part[1:]):
                segs.append(((ra0 % 360, de0), (ra1 % 360, de1)))
        out.setdefault(feat["id"], []).extend(segs)   # Serpens comes in two parts
    return out


def read_constellations(path):
    """-> {abbr: (Latin name, ra, dec, rank)}"""
    out = {}
    for feat in json.load(open(path))["features"]:
        ra, dec = feat["geometry"]["coordinates"]
        props = feat["properties"]
        out[feat["id"]] = (props["name"], ra % 360, dec, int(props.get("rank", 3)))
    return out


def read_names(path):
    """-> {("HR", n) | ("HD", n): name}; the IAU file is fixed-width."""
    out = {}
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        name = line[0:18].strip()
        desig = line[36:49].strip()
        hd = line[100:104].strip()
        if desig.startswith("HR "):
            out[("HR", int(desig[3:]))] = name
        elif hd.isdigit():
            out[("HD", int(hd))] = name
    return out


def main(src, out_path, max_mag=6.5):
    stars = read_bsc5(src + "/bsc5.catalog", max_mag)   # or bsc5.catalog.gz
    lines = read_lines(src + "/constellations.lines.json")
    consts = read_constellations(src + "/constellations.json")
    iau = read_names(src + "/IAU-CSN.txt")

    # stars
    star_bytes = bytearray()
    for vmag, ra, dec, bv, hr, hd in stars:
        x, y, z = unit(ra, dec)
        mag = max(-128, min(127, int(round(vmag * 10))))
        bvb = 127 if bv is None else max(-127, min(126, int(round(bv * 10))))
        star_bytes += struct.pack("<hhhbb", q15(x), q15(y), q15(z), mag, bvb)

    # line vertices, shared between segments that meet in one star
    verts = []
    vert_index = {}

    def vert(radec):
        key = (round(radec[0], 2), round(radec[1], 2))
        if key not in vert_index:
            vert_index[key] = len(verts)
            verts.append(unit(*radec))
        return vert_index[key]

    strings = bytearray()

    def string(text):
        data = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
        off = len(strings)
        strings.extend(data)
        return off, len(data)

    line_bytes = bytearray()
    const_bytes = bytearray()
    n_lines = 0
    for abbr in sorted(consts):
        name, ra, dec, rank = consts[abbr]
        segs = lines.get(abbr, [])
        first = n_lines
        for a, b in segs:
            line_bytes += struct.pack("<HH", vert(a), vert(b))
            n_lines += 1
        x, y, z = unit(ra, dec)
        off, ln = string(name)
        const_bytes += struct.pack("<hhhHH4sHBB", q15(x), q15(y), q15(z), first, len(segs),
                                   abbr[:3].encode("ascii").ljust(4, b"\0"), off, ln, rank)
    vert_bytes = bytearray()
    for x, y, z in verts:
        vert_bytes += struct.pack("<hhh", q15(x), q15(y), q15(z))

    # proper names, by HR first, then HD
    name_bytes = bytearray()
    n_names = 0
    for i, (vmag, ra, dec, bv, hr, hd) in enumerate(stars):
        name = iau.get(("HR", hr)) or (iau.get(("HD", hd)) if hd else None)
        if name:
            off, ln = string(name)
            name_bytes += struct.pack("<HHBx", i, off, ln)
            n_names += 1

    # the constellation each star lies in, as an index into the const table
    const_index = {abbr: i for i, abbr in enumerate(sorted(consts))}
    star_const = bytearray()
    for vmag, ra, dec, bv, hr, hd in stars:
        abbr = ephem.constellation((math.radians(ra), math.radians(dec)))[0]
        abbr = {"Se1": "Ser", "Se2": "Ser"}.get(abbr, abbr)      # pyephem splits Serpens in two
        star_const.append(const_index[abbr])

    off = HEADER_SIZE
    sections = []
    len_str = len(strings)
    blobs = (star_bytes, vert_bytes, line_bytes, const_bytes, name_bytes, strings, star_const)
    for blob in blobs:
        if len(blob) & 1:
            blob.append(0)
        sections.append(off)
        off += len(blob)
    header = struct.pack(HEADER, b"SKY1", len(stars), len(verts), n_lines, len(consts), n_names, 0,
                         sections[0], sections[1], sections[2], sections[3], sections[4], sections[5],
                         len_str, sections[6])
    with open(out_path, "wb") as f:
        f.write(header)
        for blob in blobs:
            f.write(blob)
    print("stars %d (%d B)  verts %d  lines %d  const %d  names %d  strings %d B  total %d B" % (
        len(stars), len(star_bytes), len(verts), n_lines, len(consts), n_names, len(strings), off))
    missing = [abbr for abbr in lines if abbr not in consts]
    if missing:
        print("line groups without a constellation entry:", missing)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    max_mag = 6.5
    if "--max-mag" in sys.argv:
        max_mag = float(sys.argv[sys.argv.index("--max-mag") + 1])
        args = [a for a in args if a != sys.argv[sys.argv.index("--max-mag") + 1]]
    import os
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = args[0] if args else os.path.join(repo, "data")
    out = args[1] if len(args) > 1 else os.path.join(repo, "sky.bin")
    main(src, out, max_mag)
