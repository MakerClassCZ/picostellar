"""The star catalogue (sky.bin), mapped from flash when the firmware can.

storage.map_file() returns one memoryview per contiguous run of the file's
clusters. The star table is used run by run (records are 8 bytes and runs are
multiples of 512, so no record straddles two); the small tables are read once,
copied only when a run boundary cuts through them. The file layout is in
tools/sky_pack.py.
"""
import struct

import storage


class Sky:
    """sky.bin, mapped from flash when the firmware can.

    storage.map_file() returns one memoryview per contiguous run of the file's
    clusters. The star table is used run by run (records are 8 bytes and runs
    are multiples of 512, so no record straddles two); the small tables are
    read once, copied only when a run boundary cuts through them."""

    def __init__(self, path):
        f = open(path, "rb")
        runs = storage.map_file(f) if hasattr(storage, "map_file") else ()
        self.mapped = len(runs) > 0
        if not self.mapped:
            f.seek(0)
            runs = (memoryview(f.read()),)
        f.close()
        self.runs = []                       # (file offset, memoryview)
        pos = 0
        for v in runs:
            self.runs.append((pos, v))
            pos += len(v)
        (magic, self.n_stars, self.n_verts, self.n_lines, self.n_const, self.n_names, _,
         self.o_stars, self.o_verts, self.o_lines, self.o_const, self.o_names, self.o_str,
         self.len_str, o_star_const) = struct.unpack_from("<4sHHHHHHIIIIIIII", self.section(0, 48), 0)
        if magic != b"SKY1":
            raise ValueError("not a sky.bin")
        self.star_chunks = []                # (memoryview of whole records, count), in order
        left = self.n_stars
        pos = self.o_stars
        for start, v in self.runs:
            end = start + len(v)
            if left == 0 or pos >= end:
                continue
            take = min(left, (end - pos) // 8)
            self.star_chunks.append((v[pos - start:pos - start + take * 8], take))
            pos += take * 8
            left -= take
        self.verts = self.section(self.o_verts, self.n_verts * 6)
        self.lines = self.section(self.o_lines, self.n_lines * 4)
        self.star_const = self.section(o_star_const, self.n_stars) if o_star_const else None
        strings = self.section(self.o_str, self.len_str)
        self.strings = strings
        # label positions as a vertex array the kernel can project in one call
        self.const_vecs = bytearray(self.n_const * 6)
        self.const_names = []                # (abbreviation, name)
        self.const_lines = []                # (first segment, segment count)
        const = self.section(self.o_const, self.n_const * 18)
        for i in range(self.n_const):
            x, y, z, first, n, abbr, off, ln, rank = struct.unpack_from("<hhhHH4sHBB", const, i * 18)
            struct.pack_into("<hhh", self.const_vecs, i * 6, x, y, z)
            self.const_names.append((abbr[:3].decode(), bytes(strings[off:off + ln]).decode()))
            self.const_lines.append((first, n))
        self.name_recs = self.section(self.o_names, self.n_names * 6)
        self.name_vecs = bytearray(self.n_names * 6)
        self.name_mags = bytearray(self.n_names)         # magnitude*10 + 20, names are sorted by it
        for i in range(self.n_names):
            star, off, ln = struct.unpack_from("<HHBx", self.name_recs, i * 6)
            x, y, z, mag, bv = self.star(star)
            struct.pack_into("<hhh", self.name_vecs, i * 6, x, y, z)
            self.name_mags[i] = mag + 20

    def star(self, i):
        """(x, y, z, mag*10, bv*10) of catalogue star i."""
        return struct.unpack_from("<hhhbb", self.section(self.o_stars + i * 8, 8), 0)

    def name(self, i):
        star, off, ln = struct.unpack_from("<HHBx", self.name_recs, i * 6)
        return bytes(self.strings[off:off + ln]).decode()

    def star_name(self, star):
        """The IAU name of catalogue star `star`, or None. Names are stored in star order."""
        lo, hi = 0, self.n_names
        while lo < hi:
            mid = (lo + hi) // 2
            if struct.unpack_from("<H", self.name_recs, mid * 6)[0] < star:
                lo = mid + 1
            else:
                hi = mid
        if lo < self.n_names and struct.unpack_from("<H", self.name_recs, lo * 6)[0] == star:
            return self.name(lo)
        return None

    def section(self, off, ln):
        """Bytes [off, off+ln) of the file: a flash view when one run holds them, else a copy."""
        for start, v in self.runs:
            if start <= off and off + ln <= start + len(v):
                return v[off - start:off - start + ln]
        out = bytearray(ln)
        done = 0
        for start, v in self.runs:
            lo = max(off, start)
            hi = min(off + ln, start + len(v))
            if lo < hi:
                out[lo - off:hi - off] = v[lo - start:hi - start]
                done += hi - lo
        if done != ln:
            raise ValueError("sky.bin is short")
        return out
