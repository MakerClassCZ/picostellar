"""picostellar: the night sky on a 320x240 picogame screen.

Three things carry the demo:
  picogame   a Scene with one StripDraw layer: the frame is drawn strip by strip
             into the engine's own render buffers, so no screen-sized buffer
             exists; the cursor is a Sprite, so moving it repaints only its
             rectangle. The same code runs on a DVI framebuffer board (Fruit
             Jam), SPI panels (PicoPad, RP2040 or RP2350) and the simulator
  turbo      skyviper.<arch>.mpy: the star projection, the strip bucketing, the
             dot plotting and the line drawing run as machine code; without a
             native build the same loops run as plain Python (skykernel)
  xip_map    storage.map_file() hands the kernels the 90 KB catalogue straight
             from flash, run by run, so no RAM holds the star data

Controls: four modes, B always goes back, A always goes in, Y walks
LOOK/SELECT -> TIME -> MENU -> back.
  LOOK    D-pad turns the chart (whole sky) or pans, A zooms in towards the
          direction you face (the bottom of the chart), B zooms out, X select,
          Y time
  SELECT  a cursor on a star or planet: the D-pad jumps to the nearest object
          that way, hold it to move freely; A centres and zooms in, X zooms
          out, B back, Y time. The card names the object, a star's
          constellation and magnitude, and the constellation is drawn brighter
  TIME    left/right an hour, up/down a day (hold to run), A now, X tonight
          22:00, B back, Y menu
  MENU    up/down pick, A switch, B or Y close
Animation level: zooms glide and the sky moves with the D-pad held; while it
moves, frames are drawn lighter (no names; "light" and "smooth" only the
bright stars), and the full chart follows when it stops. "auto" picks the
level from the first frame's time.
settings.toml: PICOSTELLAR_LAT, PICOSTELLAR_LON, PICOSTELLAR_TZ (the observer, default
Prague) and PICOSTELLAR_TIME ("YYYY-MM-DD HH:MM" local, a fixed start instead of the
board's clock).
"""
import array
import gc
import math
import os
import struct
import sys
import time

import skybuffer            # the hot buffers first, while the heap still has SRAM (see skybuffer)
import terminalio
import picogame as pg
import picogame_game
import picogame_input
import picogame_clock
import skyastro
import skycatalog
import skyview
import skyparams
from skyparams import (SP_W, SP_BAND, SP_OY, SP_LINE, SP_HILITE, SP_ECLIPTIC, SP_HORIZON, SP_HL_FIRST,
                       SP_HL_END, SP_SMOOTH, SP_ROWS, SP_NSTRIPS, SP_BUCKETS)

try:
    import skyviper as kernel                  # lib/skyviper.<arch>.mpy, native code
    TURBO = True
except Exception:                            # no native build for this board: bytecode
    import skykernel as kernel
    TURBO = False
# anti-aliased lines: with the native kernels, or in the desktop simulator (too slow for
# the Python kernels on a board)
SMOOTH = TURBO or sys.implementation.name != "circuitpython"

W, H, ROWS = skybuffer.W, skybuffer.H, skybuffer.ROWS
MAX_STARS, MAX_SEGS = skybuffer.MAX_STARS, skybuffer.MAX_SEGS

FONT = terminalio.FONT
TEXT_H = 12
HUD_H = 26                                   # two text lines at the bottom

# ---------------------------------------------------------------------------
# colours: one table of roles, rebuilt for the red night mode
# ---------------------------------------------------------------------------

ROLES = {"NIGHT": (2, 4, 14), "TWILIGHT": (24, 30, 70), "DAY": (70, 130, 220),
         "LINE": (40, 70, 120), "HILITE": (110, 180, 255), "HORIZON": (90, 90, 90),
         "ECLIPTIC": (110, 60, 60), "LABEL": (110, 130, 170), "STAR_NAME": (210, 200, 130),
         "HUD_INK": (200, 200, 200), "MOON_DARK": (50, 50, 60), "SUN_GLOW": (120, 100, 30),
         "CURSOR": (255, 150, 40), "MENU_BG": (16, 22, 44), "MENU_SEL": (50, 70, 130)}
BODIES = {"Sun": (255, 230, 80), "Moon": (230, 230, 220), "Mercury": (200, 190, 170),
          "Venus": (255, 250, 210), "Mars": (255, 120, 70), "Jupiter": (255, 220, 170),
          "Saturn": (240, 220, 150), "Uranus": (150, 230, 230), "Neptune": (110, 140, 255)}
# 6 B-V classes x (bright, mid, dim), see skykernel
STAR_COLOURS = ((170, 190, 255), (255, 255, 255), (255, 245, 220), (255, 225, 160),
                (255, 190, 120), (255, 150, 110))
LUT = array.array("H", [0]) * 18
# cos and sin of every 10 degrees, Q15: the horizon and the ecliptic are drawn as 36-point loops
RING = array.array("h", [0]) * 72
for _i in range(36):
    RING[2 * _i] = int(round(math.cos(math.radians(10 * _i)) * 32767))
    RING[2 * _i + 1] = int(round(math.sin(math.radians(10 * _i)) * 32767))


class C:
    """The colours in use; apply_theme() fills it."""
    BODY = {}


def shade(rgb, red):
    r, g, b = rgb
    if red:                                  # night vision: brightness kept, colour dropped
        return pg.rgb565(max(r, g, b), 0, 0)
    return pg.rgb565(r, g, b)


def apply_theme(red):
    for name, value in ROLES.items():
        setattr(C, name, shade(value, red))
    C.BODY = {name: shade(value, red) for name, value in BODIES.items()}
    i = 0
    for r, g, b in STAR_COLOURS:
        for num, den in ((1, 1), (2, 3), (1, 3)):
            LUT[i] = shade((r * num // den, g * num // den, b * num // den), red)
            i += 1


# field of view (deg, top to bottom; 180 = the whole sky as a disc), faintest magnitude*10,
# magnitude offset for the dot sizes, faintest star the cursor jumps to
ZOOM = ((180, 50, 0, 35), (90, 55, -5, 40), (60, 60, -10, 45), (40, 65, -13, 50),
        (25, 65, -17, 55), (15, 65, -22, 60))
LOOK, SELECT, TIME, MENU = 0, 1, 2, 3
STAR, BODY = 0, 1                            # what a selection (kind, star index or body name) is
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
DIRS = ((picogame_input.LEFT, -1, 0), (picogame_input.RIGHT, 1, 0),
        (picogame_input.UP, 0, -1), (picogame_input.DOWN, 0, 1))
HOLD = 8                                     # frames a direction is held before the cursor glides
SNAP_R = 10                                  # px: the cursor locks onto an object this close
MAX_PICK = 400
CUR = 17                                     # cursor sprite size
BRIGHTNESS = (1.0, 0.4, 0.15)
MENU_W = 216
MENU = (("lines", "Constellation lines"), ("smooth", "Smooth lines"), ("names", "Star names"),
        ("ecliptic", "Ecliptic"), ("red", "Night mode (red)"), ("anim", "Animation"),
        ("bright", "Brightness"))
ANIM_NAMES = ("off", "light", "smooth", "full")
ANIM_FRAMES = (0, 4, 8, 8)                   # frames of a zoom glide, per animation level
LOD_MAG = 40                                 # faintest star of a frame drawn while moving, magnitude*10


def setting(name, default=None):
    """A settings.toml value, or default (the simulator has no os.getenv)."""
    try:
        return os.getenv(name) or default
    except AttributeError:
        return default


def setting_float(name, default):
    try:
        return float(setting(name, default))
    except ValueError:
        return default


def board_time(tz):
    """(day, frac) from the board's clock, or None when it was never set."""
    now = time.localtime()
    if now[0] < 2024:
        return None
    day, frac = skyastro.from_calendar(now[0], now[1], now[2], now[3], now[4], now[5])
    return day, frac - tz / 24.0


def parse_time(text, tz):
    """"YYYY-MM-DD HH:MM" local time -> (day, frac), or None when malformed."""
    try:
        y, mo, d = (int(v) for v in text[:10].split("-"))
        h, mi = (int(v) for v in text[11:16].split(":"))
    except ValueError:
        return None
    day, frac = skyastro.from_calendar(y, mo, d, h, mi)
    return day, frac - tz / 24.0


def brightness_works(display):
    """A DVI display has a brightness attribute that raises when read."""
    try:
        display.brightness = display.brightness
        return True
    except (AttributeError, RuntimeError, ValueError, NotImplementedError):
        return False


def compass(az):
    return COMPASS[int((az % 360.0 + 22.5) // 45) % 8]


def view_k(fov):
    """Stereographic scale (px for 90 deg off centre) of a field of view, top to bottom."""
    if fov >= 180:
        return H // 2 - 4                    # the whole-sky disc, a little inside the screen
    return (H / 2) / math.tan(math.radians(fov) / 4)


class Glide:
    """A zoom or turn in a few frames: the view centre moves along the shorter
    way round, the scale grows geometrically, with an ease-in-out curve."""

    def __init__(self, a0, h0, k0, a1, h1, k1, frames, zoom):
        self.a0 = a0
        self.da = (a1 - a0 + 540.0) % 360.0 - 180.0
        self.h0 = h0
        self.dh = h1 - h0
        self.lk0 = math.log(k0)
        self.dlk = math.log(k1) - self.lk0
        self.frames = frames
        self.i = 0
        self.zoom = zoom                     # the level the glide ends in
        self.end_az = a1 % 360.0

    def view(self):
        t = (self.i + 1) / self.frames
        t = t * t * (3.0 - 2.0 * t)
        return (self.a0 + self.da * t) % 360.0, self.h0 + self.dh * t, math.exp(self.lk0 + self.dlk * t)


class App:
    def __init__(self):
        apply_theme(False)
        self.scene = picogame_game.setup(background=C.NIGHT)[0]
        self.display = picogame_game.display()
        gc.collect()
        self.sky = skycatalog.Sky("/sky.bin" if "sky.bin" in os.listdir("/") else "sky.bin")
        self._layers()
        self._buffers()
        self._read_settings()
        self._init_state()
        self.set_time()
        self.update()
        if self.anim_auto:
            self.anim_level = self.auto_level()
        gc.collect()

    def _layers(self):
        """The scene: one StripDraw for the sky and a Sprite for the cursor."""
        self.rows = ROWS
        # the kernels draw into this strip-sized scratch; the StripDraw callback blits it
        self.scratch = skybuffer.SCRATCH
        self.scratch_cv = pg.Canvas(W, self.rows, buffer=self.scratch)
        self.scratch_bm = pg.Bitmap(self.scratch, W, self.rows)
        self.layer = pg.StripDraw(self.strip, 0, 0, W, H, always_dirty=False)
        self.scene.add(self.layer)
        self.cursor_px = bytearray(CUR * CUR * 2)   # a bytearray: the sim aliases only those
        self.cursor_cv = pg.Canvas(CUR, CUR, buffer=self.cursor_px)
        self.cursor = pg.Sprite(pg.Bitmap(self.cursor_px, CUR, CUR, transparent=0), 0, 0)
        self.cursor.visible = False
        self.scene.add(self.cursor)
        self.paint_cursor()

    def _buffers(self):
        """Everything the kernels read and write, allocated once."""
        sky = self.sky
        self.star_list = skybuffer.STAR_LIST
        self.star_sorted = skybuffer.STAR_SORTED                         # bucketed by strip
        self.segs = skybuffer.SEGS                                       # line segments, bucketed by strip
        self.scr = skybuffer.SCR if sky.n_verts <= skybuffer.MAX_VERTS else array.array("h", [0]) * (2 * sky.n_verts)
        self.params = skyparams.new_params()
        self.sp = skyparams.new_strip_params()
        self.line_pairs = memoryview(sky.lines).cast("H")
        self.nstrips = (H + self.rows - 1) // self.rows
        self.offsets = array.array("h", [0]) * (self.nstrips + 2)
        self.seg_off = array.array("h", [0]) * (self.nstrips + 2)
        self.n_list = 0
        self.n_segs = 0
        self.pick = array.array("h", [0]) * (3 * MAX_PICK)           # (x, y, star) the cursor can jump to
        self.n_pick = 0
        self.pick_valid = False
        self.pick_limit = 0
        self.bounds = array.array("h", [0]) * (2 * sky.n_lines)
        self.bounds_horizon = array.array("h", [0]) * 72
        self.bounds_ecliptic = array.array("h", [0]) * 72
        self.scr_horizon = array.array("h", [0]) * 72
        self.scr_ecliptic = array.array("h", [0]) * 72
        self.scr_const = array.array("h", [0]) * (2 * sky.n_const)
        self.scr_names = array.array("h", [0]) * (2 * sky.n_names)
        self.vis = array.array("H", [0]) * 100                       # the names on screen, by index
        self.name_text = [None] * sky.n_names                         # star names, decoded when first shown
        self.name_counts = {}
        self.point_vecs = bytearray((4 + 9) * 6)    # N E S W + the nine bodies, as Q15 vectors
        self.scr_points = array.array("h", [0]) * (2 * 13)
        self.body_names = []
        self.bodies = {}
        self.horizon = bytearray(36 * 6)
        self.ecliptic = bytearray(36 * 6)
        self.ring_axes = array.array("i", [0]) * 6
        self.ring_pairs = array.array("H")          # a closed 36-point loop as line segments
        for i in range(36):
            self.ring_pairs.append(i)
            self.ring_pairs.append((i + 1) % 36)
        self.sp[SP_W] = W
        self.sp[SP_ROWS] = self.rows
        self.sp[SP_NSTRIPS] = self.nstrips
        self.strip_args = (self.segs, self.seg_off, self.line_pairs, self.scr, self.ring_pairs,
                           self.scr_ecliptic, self.scr_horizon, self.star_sorted, self.offsets, LUT,
                           self.scratch, self.sp)

    def _read_settings(self):
        """The observer, the view, the time and the animation level from settings.toml."""
        self.lat = setting_float("PICOSTELLAR_LAT", 50.09)
        self.lon = setting_float("PICOSTELLAR_LON", 14.42)
        self.tz = setting_float("PICOSTELLAR_TZ", 2.0)
        self.view = skyview.View(self.lat, self.lon)
        self.zoom = 0
        self.az = 180.0            # the direction you face: the bottom of the whole-sky chart
        self.alt = 45.0
        self.live = False
        fixed = setting("PICOSTELLAR_TIME")         # "YYYY-MM-DD HH:MM" local time for a scripted demo
        when = parse_time(fixed, self.tz) if fixed else None
        if fixed and when is None:
            print("picostellar: PICOSTELLAR_TIME ignored:", fixed)
        if when is None:
            when = board_time(self.tz)
            self.live = when is not None
        if when is None:           # no clock on the board: a demo evening
            when = skyastro.from_calendar(2026, 10, 14, 20)
        self.day, self.frac = skyastro.normalize(*when)
        self.anim_auto = True      # the level comes from the first chart's time; the menu overrides
        self.anim_level = 0

    def _init_state(self):
        """Input, mode, selection, menu and the frame flags."""
        try:
            self.btn = picogame_input.Buttons()
        except Exception as e:             # no pad on this board: the sky still turns
            print("picostellar: no input:", e)
            self.btn = None
        self.clock = picogame_clock.Clock(30)
        self.dt = 0.0
        self.mode = LOOK
        self.back_mode = LOOK      # where B returns to from TIME and MENU
        self.sel = None            # (STAR, catalogue index) or (BODY, name)
        self.sel_on = False        # the selected object is on screen
        self.cur_x = W // 2
        self.cur_y = H // 2
        self.hl_const = -1         # constellation drawn brighter
        self.held = [0, 0, 0, 0]
        self.edge_wait = 0
        self.show_lines = True
        self.smooth = SMOOTH                   # anti-aliased lines (menu)
        self.show_names = True
        self.show_ecliptic = True
        self.red = False
        self.bright_i = 0
        self.has_brightness = brightness_works(self.display)
        self.menu_rows = [row for row in MENU if row[0] != "bright" or self.has_brightness]
        self.menu_i = 0
        self.menu_h = 14 * len(self.menu_rows) + 12
        self.menu_x = (W - MENU_W) // 2
        self.menu_y = (H - HUD_H - self.menu_h) // 2
        self.menu_text = ()        # the rows' text, formatted when the menu changes
        # animation: a glide in progress, the lighter frames while moving
        self.glide = None
        self.lod = False
        self.moved = False
        self.settle = 0
        # what to repaint at the end of a frame
        self.need_full = True
        self.need_part = False
        self.menu_dirty = False
        self.last_redraw = -1e9
        self.labels = []           # (x, y, text, colour) on screen
        self.marks = []            # (name, x, y, extra) of the bodies on screen
        self.hud = ("", "")
        self.bg = C.NIGHT
        self.disc = True
        self.frame_ms = 0          # the last full chart, for the animation level

    def auto_level(self):
        """The animation level this board can carry, from how long the full chart took."""
        if not TURBO or self.frame_ms > 220:   # light frames skip the smoothing: far cheaper
            return 0
        if self.frame_ms <= 50:
            return 3
        return 2 if self.frame_ms <= 75 else 1

    # -- time and view --------------------------------------------------------

    def set_time(self):
        self.day, self.frac = skyastro.normalize(self.day, self.frac)
        view = self.view
        view.set_time(self.day, self.frac)
        self.bodies = skyastro.bodies(self.day, self.frac)
        # the horizon and the ecliptic of date are fixed circles: each is its two axes in the
        # catalogue frame, and a kernel turns the 36 points (no trigonometry per point)
        e = math.radians(skyastro.obliquity(skyastro.day_number(self.day, self.frac)))
        q = self.ring_axes
        for out, a, b in ((self.horizon, view.cat_north, view.cat_east),
                          (self.ecliptic, view.to_catalogue((1.0, 0.0, 0.0)),
                           view.to_catalogue((0.0, math.cos(e), math.sin(e))))):
            for j in range(3):
                q[j] = int(round(a[j] * 32767))
                q[3 + j] = int(round(b[j] * 32767))
            kernel.ring(RING, 36, q, out)
        sun_az, self.sun_alt = skyastro.equatorial_to_horizontal(
            self.bodies["Sun"][0], self.bodies["Sun"][1], view.lst, self.lat)
        for i, point in enumerate((0, 9, 18, 27)):         # N E S W: azimuth 0, 90, 180, 270
            self.point_vecs[i * 6:i * 6 + 6] = self.horizon[point * 6:point * 6 + 6]
        self.body_names = list(self.bodies.keys())
        for i, name in enumerate(self.body_names):
            x, y, z = view.equatorial(self.bodies[name][0], self.bodies[name][1])
            struct.pack_into("<hhh", self.point_vecs, (4 + i) * 6, int(x * 32767), int(y * 32767), int(z * 32767))
        self.need_full = True

    def view_now(self):
        """(centre azimuth, centre altitude, scale) of what is on screen; the
        whole-sky disc is centred on the zenith with the facing direction at
        the bottom."""
        if self.glide is not None:
            return self.glide.view()
        if self.zoom == 0:
            return self.az, 90.0, view_k(180)
        return self.az, self.alt, view_k(ZOOM[self.zoom][0])

    def fill_view(self):
        fov, mag_limit, mag_offset, pick = ZOOM[self.zoom]
        p = self.params
        az, alt, k = self.view_now()
        self.disc = self.glide is None and self.zoom == 0
        self.view.fill_params(p, az, alt, k, W, H, disc=self.disc)
        if self.sun_alt > 0:
            mag_limit = -30            # daylight: no stars
        elif self.sun_alt > -6:
            mag_limit = min(mag_limit, 15)
        elif self.sun_alt > -12:
            mag_limit = min(mag_limit, 35)
        self.pick_limit = min(pick, mag_limit)
        if self.lod and self.anim_level < 3:   # "full" keeps every star while moving
            mag_limit = min(mag_limit, LOD_MAG)
        p[skyparams.P_MAG_LIMIT] = mag_limit
        p[skyparams.P_MAG_OFFSET] = mag_offset

    def set_zoom(self, zoom, az=None, alt=None):
        """Zoom to a level, gliding when the animation level allows; az/alt aim
        the new view (default: from the chart, the direction you face)."""
        zoom = min(max(zoom, 0), len(ZOOM) - 1)
        if zoom == self.zoom and az is None:
            return
        a0, h0, k0 = self.view_now()
        if az is None:
            az = a0
            alt = self.alt if self.zoom > 0 else 45.0
        alt = min(max(alt, -10.0), 89.0)
        h1 = 90.0 if zoom == 0 else alt
        k1 = view_k(180 if zoom == 0 else ZOOM[zoom][0])
        frames = ANIM_FRAMES[self.anim_level]
        if frames:
            self.glide = Glide(a0, h0, k0, az, h1, k1, frames, zoom)
            self.moved = True
        else:
            self.zoom = zoom
            self.az = az % 360.0
        if zoom:
            self.alt = alt                     # at once, even while gliding: pan() and the HUD read it
        self.need_full = True

    def advance_glide(self):
        """After a glide frame is on screen: the next one, or arrive."""
        g = self.glide
        g.i += 1
        if g.i >= g.frames:                    # arrived: the level and view are now real
            self.glide = None
            self.zoom = g.zoom
            self.az = g.end_az
        self.need_full = True

    def pan(self, dx, dy, f=1.0):
        fov = ZOOM[self.zoom][0]
        if fov >= 180:
            self.az = (self.az + 15.0 * dx * f) % 360.0    # turn yourself: the chart turns
        else:
            step = fov / 12.0 * f
            self.az = (self.az + step * dx) % 360.0
            self.alt = min(89.0, max(-10.0, self.alt - step * dy))
        self.moved = True
        self.need_full = True

    # -- the per-redraw part: project everything once -----------------------

    def redraw(self):
        sky = self.sky
        p = self.params
        rows = self.rows
        self.fill_view()
        pick_limit = self.pick_limit
        self.bg = C.NIGHT if self.sun_alt < -12 else (C.DAY if self.sun_alt > 0 else C.TWILIGHT)
        want_pick = self.mode == SELECT and not self.lod
        self.n_list = 0
        self.n_pick = 0
        base = 0
        for chunk, n in sky.star_chunks:   # sorted by magnitude: chunks past the limit return at once
            if self.n_list < MAX_STARS:
                self.n_list += kernel.project_stars(chunk, n, p, memoryview(self.star_list)[4 * self.n_list:],
                                                  MAX_STARS - self.n_list)
            if want_pick and self.n_pick < MAX_PICK:
                self.n_pick += kernel.project_pick(chunk, n, p, pick_limit, base,
                                                 memoryview(self.pick)[3 * self.n_pick:], MAX_PICK - self.n_pick)
            base += n
        self.pick_valid = want_pick
        kernel.sort_list(self.star_list, self.n_list, rows, self.nstrips, self.offsets, self.star_sorted)
        # lines: projected, then indexed by strip so each strip draws only its own
        lines = self.show_lines and not (self.lod and self.anim_level < 2)
        flags = (1 if lines else 0) | (2 if self.show_ecliptic else 0)
        if lines:
            kernel.project(sky.verts, sky.n_verts, p, self.scr)
            kernel.segment_bounds(self.line_pairs, sky.n_lines, self.scr, self.bounds)
        kernel.project(self.ecliptic, 36, p, self.scr_ecliptic)
        kernel.segment_bounds(self.ring_pairs, 36, self.scr_ecliptic, self.bounds_ecliptic)
        kernel.project(self.horizon, 36, p, self.scr_horizon)
        kernel.segment_bounds(self.ring_pairs, 36, self.scr_horizon, self.bounds_horizon)
        self.n_segs = kernel.bucket_lines(self.bounds, sky.n_lines, self.bounds_ecliptic, self.bounds_horizon, 36,
                                        flags, rows, self.nstrips, self.seg_off, self.segs, MAX_SEGS)
        sp = self.sp
        sp[SP_LINE] = C.LINE
        sp[SP_HILITE] = C.HILITE
        sp[SP_ECLIPTIC] = C.ECLIPTIC
        sp[SP_HORIZON] = C.HORIZON
        sp[SP_HL_FIRST] = sp[SP_HL_END] = 0
        sp[SP_SMOOTH] = 1 if self.smooth and not (self.lod and self.anim_level < 2) else 0
        sp[SP_BUCKETS] = 1 if self.n_segs >= 0 else 0    # over MAX_SEGS (never seen): no lines this frame
        if self.hl_const >= 0:
            first, n = sky.const_lines[self.hl_const]
            sp[SP_HL_FIRST] = first
            sp[SP_HL_END] = first + n
        # labels and bodies on screen; each strip draws those that touch its rows
        labels = []
        marks = []
        kernel.project(self.point_vecs, 4 + len(self.body_names), p, self.scr_points)
        pts = self.scr_points
        for i, label in enumerate("NESW"):
            x, y = pts[2 * i], pts[2 * i + 1]
            if x != skyparams.CULLED and -8 < x < W + 2 and -8 < y < H + 2:
                labels.append((min(max(x - 3, 0), W - 7), min(max(y - 6, 0), H - 13), label, C.HORIZON))
        for i, name in enumerate(self.body_names):
            x, y = pts[2 * (4 + i)], pts[2 * (4 + i) + 1]
            if x != skyparams.CULLED and -6 <= x < W + 6 and -6 <= y < H + 6:
                marks.append((name, x, y, self.bodies[name][2]))
                if self.show_names and not self.lod:
                    labels.append((x + 5, y - 6, name, C.BODY[name]))
        if self.show_names and not self.lod:
            self.collect_names(labels)
        self.labels = labels
        self.marks = marks
        self.last_redraw = time.monotonic()

    def collect_names(self, labels):
        """Constellation and star names on screen: a kernel picks the visible
        points, so Python only touches the few labels that get drawn."""
        fov = ZOOM[self.zoom][0]
        sky = self.sky
        p = self.params
        vis = self.vis
        if fov <= 90:
            scr = self.scr_const
            kernel.project(sky.const_vecs, sky.n_const, p, scr)
            for j in range(kernel.visible(scr, sky.n_const, W - 20, H - 12, vis, len(vis))):
                i = vis[j]
                abbr, full = sky.const_names[i]
                labels.append((scr[2 * i], scr[2 * i + 1], full if fov <= 40 else abbr,
                               C.HILITE if i == self.hl_const else C.LABEL))
        n = self.names_to(15 if fov >= 180 else (25 if fov > 40 else 40))
        scr = self.scr_names
        kernel.project(sky.name_vecs, n, p, scr)
        for j in range(kernel.visible(scr, n, W - 10, H - 12, vis, len(vis))):
            i = vis[j]
            name = self.name_text[i]
            if name is None:                   # decoded once, then kept
                name = self.name_text[i] = sky.name(i)
            labels.append((scr[2 * i] + 4, scr[2 * i + 1] - 10, name, C.STAR_NAME))

    def names_to(self, limit):
        """How many star names are as bright as magnitude limit/10 (they are sorted by magnitude)."""
        n = self.name_counts.get(limit)
        if n is None:
            mags = self.sky.name_mags
            n = 0
            while n < self.sky.n_names and mags[n] - 20 <= limit:
                n += 1
            self.name_counts[limit] = n
        return n

    def build_pick(self):
        """The cursor's targets for the view on screen, when the last redraw skipped them."""
        p = self.params
        pick_limit = self.pick_limit
        self.n_pick = 0
        base = 0
        for chunk, n in self.sky.star_chunks:
            if self.n_pick < MAX_PICK:
                self.n_pick += kernel.project_pick(chunk, n, p, pick_limit, base,
                                                 memoryview(self.pick)[3 * self.n_pick:], MAX_PICK - self.n_pick)
            base += n
        self.pick_valid = True

    # -- painting -----------------------------------------------------------

    def update(self):
        """Repaint what the frame changed: everything, or only the cursor, the
        card and the menu (sprites and the rectangles under them)."""
        full = self.need_full
        t0 = time.monotonic_ns()
        if full:
            self.redraw()
            if self.mode == SELECT and self.sel is not None:
                self.relocate()
        old_hud = self.hud
        self.make_hud()
        if self.mode == MENU and (full or self.menu_dirty):
            self.menu_text = self.menu_lines()
        self.cursor.visible = self.mode == SELECT and self.sel is not None and self.sel_on
        if self.mode == SELECT:
            self.cursor.x = self.cur_x - CUR // 2
            self.cursor.y = self.cur_y - CUR // 2
        if full:
            self.layer.invalidate()
        else:                                  # only the rectangles whose content changed
            if self.hud != old_hud:
                self.layer.invalidate(0, H - HUD_H, W, HUD_H)
            if self.menu_dirty:
                self.layer.invalidate(self.menu_x, self.menu_y, MENU_W, self.menu_h)
        self.menu_dirty = False
        self.scene.refresh()
        if full and not self.lod:
            self.frame_ms = (time.monotonic_ns() - t0) // 1000000
        self.need_full = False
        self.need_part = False

    def strip(self, view, vx, vy, vw, vh):
        """StripDraw callback: a full-width strip, or any smaller dirty rectangle."""
        if (self.mode == MENU and vx >= self.menu_x and vx + vw <= self.menu_x + MENU_W
                and vy >= self.menu_y and vy + vh <= self.menu_y + self.menu_h):
            self.draw_menu(view, vx, vy, vh)  # the box is opaque: no sky under it
            return
        cv = self.scratch_cv
        sp = self.sp
        y0 = 0
        while y0 < vh:
            oy = vy + y0
            band = min(self.rows, vh - y0)     # a framebuffer target hands out lower bands
            cv.fill_rect(0, 0, W, band, C.NIGHT if self.disc else self.bg)
            if self.disc and self.bg != C.NIGHT:        # a lit sky inside the horizon circle
                cv.fill_circle(W // 2, H // 2 - oy, H // 2 - 4, self.bg)
            sp[SP_BAND] = band
            sp[SP_OY] = oy
            kernel.draw_strip(*self.strip_args)  # the line buckets, then the stars on top
            view.blit(self.scratch_bm, -vx, y0)
            y0 += band
        bottom = vy + vh
        for x, y, text, colour in self.labels:
            if y < bottom and y + TEXT_H > vy:
                view.text(x - vx, y - vy, text, colour, FONT)
        for name, x, y, extra in self.marks:
            if y - 10 < bottom and y + 10 > vy:
                self.draw_body(view, name, x - vx, y - vy, extra)
        if self.mode == MENU and vy < self.menu_y + self.menu_h and bottom > self.menu_y:
            self.draw_menu(view, vx, vy, vh)
        if bottom > H - HUD_H:
            for i, line in enumerate(self.hud):
                y = H - HUD_H + 13 * i
                if line and y + TEXT_H > vy and y < bottom:
                    view.text(2 - vx, y - vy, line, C.HUD_INK, FONT, C.NIGHT)

    def draw_body(self, cv, name, x, y, extra):
        colour = C.BODY[name]
        if name == "Sun":
            cv.fill_circle(x, y, 4, colour)
            cv.circle(x, y, 6, C.SUN_GLOW)
        elif name == "Moon":
            # lit disc with the dark disc slid over it: right for crescents, close enough for gibbous
            r = 4
            f = abs(extra)
            cv.fill_circle(x, y, r, colour)
            shift = int(round(2 * r * f))
            cv.fill_circle(x - shift if extra >= 0 else x + shift, y, r, C.MOON_DARK)
            cv.circle(x, y, r, C.MOON_DARK)
        else:
            cv.fill_circle(x, y, 2 if name in ("Venus", "Jupiter") else 1, colour)

    def paint_cursor(self):
        """A ring with four ticks; the gap in the middle keeps the object visible."""
        cv = self.cursor_cv
        c = CUR // 2
        cv.clear(0)
        cv.ring(c, c, 6, 1, C.CURSOR)
        for x, y, w, h in ((c, 0, 1, 3), (c, CUR - 3, 1, 3), (0, c, 3, 1), (CUR - 3, c, 3, 1)):
            cv.fill_rect(x, y, w, h, C.CURSOR)
        self.cursor.touch()

    def menu_value(self, key):
        on = ("off", "on")
        if key == "lines":
            return on[self.show_lines]
        if key == "smooth":
            return on[self.smooth]
        if key == "names":
            return on[self.show_names]
        if key == "ecliptic":
            return on[self.show_ecliptic]
        if key == "red":
            return on[self.red]
        if key == "anim":
            return ("auto: " if self.anim_auto else "") + ANIM_NAMES[self.anim_level]
        return "%3d%%" % int(BRIGHTNESS[self.bright_i] * 100)

    def menu_lines(self):
        """The rows' text: formatted once per change, drawn once per strip."""
        return ["%-22s%s" % (label, self.menu_value(key)) for key, label in self.menu_rows]

    def draw_menu(self, view, vx, vy, vh):
        """The menu box, only the rows that fall inside this view."""
        x0 = self.menu_x - vx
        y0 = self.menu_y - vy
        view.fill_rect(x0, y0, MENU_W, self.menu_h, C.MENU_BG)
        view.rect(x0, y0, MENU_W, self.menu_h, C.LABEL)
        for i, line in enumerate(self.menu_text):
            y = y0 + 6 + 14 * i
            if y + 13 <= 0 or y - 1 >= vh:
                continue
            if i == self.menu_i:
                view.fill_rect(x0 + 3, y - 1, MENU_W - 6, 14, C.MENU_SEL)
            view.text(x0 + 8, y, line, C.HUD_INK, FONT)

    def make_hud(self):
        y, mo, d, h, mi, s = skyastro.calendar(self.day, self.frac + self.tz / 24.0)
        when = "%04d-%02d-%02d %02d:%02d %s" % (y, mo, d, h, mi, "live" if self.live else "paused")
        if self.mode == LOOK:
            fov = ZOOM[self.zoom][0]
            line1 = when if fov >= 180 else "%s  az %d %s alt %d" % (when, self.az, compass(self.az), self.alt)
            line2 = "A zoom+ B zoom- X select Y time"
        elif self.mode == SELECT:
            line1, where = self.card()
            line2 = "%-20s A go X out B back" % where
        elif self.mode == TIME:
            line1 = "TIME  " + when
            line2 = "<> hour ^v day A now X 22:00 B back"
        else:
            line1 = when
            line2 = "^v pick  A switch  B close"
        self.hud = (line1, line2)

    # -- selection ------------------------------------------------------------

    def card(self):
        """Two strings about the selected object: what it is, and where."""
        if self.sel is None:
            return "move onto a star or planet", ""
        kind, ref = self.sel
        if kind == BODY:
            ra, dec, extra = self.bodies[ref]
            if ref == "Moon":
                what = "Moon  %d%% lit, %s" % (int(abs(extra) * 100 + 0.5), "waxing" if extra >= 0 else "waning")
            elif ref == "Sun":
                what = "Sun"
            else:
                what = "%s  %.2f AU" % (ref, extra)
            vec = self.view.equatorial(ra, dec)
        else:
            x, y, z, mag, bv = self.sky.star(ref)
            name = self.sky.star_name(ref) or "Star"
            const = ""
            if self.sky.star_const is not None:
                const = self.sky.const_names[self.sky.star_const[ref]][1]
            what = "%s  %s  mag %.1f" % (name, const, mag / 10)
            vec = (x / 32767, y / 32767, z / 32767)
        az, alt = self.view.az_alt(vec)
        return what, "alt %d az %d %s" % (alt, az, compass(az))

    def bodies_on_screen(self):
        for name, x, y, extra in self.marks:
            if 0 <= x < W and 0 <= y < H - HUD_H:
                yield x, y, (BODY, name)

    def star_pick(self, i):
        pk = self.pick
        return (STAR, pk[3 * i + 2]), pk[3 * i], pk[3 * i + 1]

    def select(self, sel, x, y):
        self.sel = sel
        self.sel_on = sel is not None
        self.cur_x = x
        self.cur_y = y
        hl = -1
        if sel is not None and sel[0] == STAR and self.sky.star_const is not None:
            hl = self.sky.star_const[sel[1]]
        if hl != self.hl_const:
            self.hl_const = hl
            self.need_full = True              # the brighter lines span the screen
        self.need_part = True

    def ensure_pick(self):
        if not self.pick_valid:                # the last frames were drawn on the move
            self.build_pick()

    def nearest(self, x, y, radius):
        """(selection, x, y) of the object closest to (x, y) within radius, or None:
        the stars through the pick kernel, the few bodies in Python."""
        self.ensure_pick()
        best = None
        best_d = radius * radius + 1
        i = kernel.pick_near(self.pick, self.n_pick, x, y, radius * radius)
        if i >= 0:
            best = self.star_pick(i)
            best_d = (best[1] - x) * (best[1] - x) + (best[2] - y) * (best[2] - y)
        for cx, cy, sel in self.bodies_on_screen():
            d = (cx - x) * (cx - x) + (cy - y) * (cy - y)
            if d < best_d:
                best_d = d
                best = (sel, cx, cy)
        return best

    def jump(self, dx, dy):
        """Move the selection to the nearest object in direction (dx, dy), inside
        a cone of about 60 degrees each side; the score favours the straight line."""
        self.ensure_pick()
        best = None
        best_score = 1 << 30
        i = kernel.pick_dir(self.pick, self.n_pick, self.cur_x, self.cur_y, dx, dy, 2)
        if i >= 0:
            best = self.star_pick(i)
            ox = best[1] - self.cur_x
            oy = best[2] - self.cur_y
            best_score = ox * dx + oy * dy + 3 * abs(ox * dy - oy * dx)
        for x, y, sel in self.bodies_on_screen():
            ox = x - self.cur_x
            oy = y - self.cur_y
            along = ox * dx + oy * dy
            across = abs(ox * dy - oy * dx)
            if along <= 2 or across > along * 2:
                continue
            if along + 3 * across < best_score:
                best_score = along + 3 * across
                best = (sel, x, y)
        if best is not None and best[2] < H - HUD_H:
            self.select(*best)
        elif self.zoom > 0:                    # nothing that way on screen: turn the sky
            self.pan(dx, dy)

    def drift(self, dx, dy, speed):
        x = self.cur_x + dx * speed
        y = self.cur_y + dy * speed
        top = H - HUD_H - 1
        if self.zoom > 0 and (x < 0 or x >= W or y < 0 or y > top):
            self.edge_wait += 1
            if self.edge_wait >= 6:            # pushing on an edge turns the sky, a step at a time
                self.edge_wait = 0
                self.pan(dx, dy)
        x = min(max(x, 0), W - 1)
        y = min(max(y, 0), top)
        found = self.nearest(x, y, SNAP_R)
        sel = found[0] if found else None
        if sel != self.sel:
            self.select(sel, x, y)
        self.cur_x = x
        self.cur_y = y
        self.need_part = True

    def sel_vector(self):
        kind, ref = self.sel
        if kind == BODY:
            ra, dec, extra = self.bodies[ref]
            return self.view.equatorial(ra, dec)
        x, y, z, mag, bv = self.sky.star(ref)
        return (x / 32767, y / 32767, z / 32767)

    def relocate(self):
        """After the sky moved: put the cursor on the selected object again; off
        screen, the selection stays and the cursor hides."""
        pt = self.view.project(self.sel_vector(), self.params)
        self.sel_on = pt is not None and 0 <= pt[0] < W and 0 <= pt[1] < H - HUD_H
        if self.sel_on:
            self.cur_x = int(pt[0])
            self.cur_y = int(pt[1])

    def enter_select(self):
        if self.sel is None:
            found = self.nearest(self.cur_x, self.cur_y, 400)
            if found:
                self.select(*found)
        self.need_part = True

    def go_to_selection(self):
        if self.sel is None:
            return
        az, alt = self.view.az_alt(self.sel_vector())
        self.set_zoom(max(self.zoom + 1, 1), az, alt)

    # -- input ----------------------------------------------------------------

    def handle_input(self):
        btn = self.btn
        if btn is None:
            return
        btn.poll()
        if self.mode == LOOK:
            self.input_look(btn)
        elif self.mode == SELECT:
            self.input_select(btn)
        elif self.mode == TIME:
            self.input_time(btn)
        else:
            self.input_menu(btn)

    def to_mode(self, mode):
        if mode in (TIME, MENU) and self.mode in (LOOK, SELECT):
            self.back_mode = self.mode
        if MENU in (mode, self.mode):
            self.menu_dirty = True             # the box appears or goes
        self.mode = mode
        if mode == SELECT:
            self.enter_select()
        self.need_part = True                  # the card, the cursor and the menu box change

    def input_look(self, btn):
        for mask, dx, dy in DIRS:
            if ZOOM[self.zoom][0] >= 180 and dy:
                continue                       # the whole-sky disc only turns
            if self.anim_level:                # glide while held: half a field per second
                if btn.is_pressed(mask):
                    self.pan(dx, dy, min(self.dt, 0.2) * 6.0)
            elif btn.repeat(mask, 8, 2):
                self.pan(dx, dy)
        if btn.just_pressed(picogame_input.A):
            self.set_zoom(self.zoom + 1)
        if btn.just_pressed(picogame_input.B):
            self.set_zoom(self.zoom - 1)
        if btn.just_pressed(picogame_input.X):
            self.to_mode(SELECT)
        if btn.just_pressed(picogame_input.Y):
            self.to_mode(TIME)

    def input_select(self, btn):
        for i, (mask, dx, dy) in enumerate(DIRS):
            if btn.is_pressed(mask):
                self.held[i] += 1
            else:
                if self.held[i] > HOLD:        # end of a glide: lock onto what is under the cursor
                    found = self.nearest(self.cur_x, self.cur_y, SNAP_R)
                    if found:
                        self.select(*found)
                self.held[i] = 0
                continue
            if btn.just_pressed(mask):
                self.jump(dx, dy)
            elif self.held[i] > HOLD:
                self.drift(dx, dy, 2 if self.held[i] < HOLD + 20 else 5)
        if btn.just_pressed(picogame_input.A):
            self.go_to_selection()
        if btn.just_pressed(picogame_input.X):
            self.set_zoom(self.zoom - 1)
        if btn.just_pressed(picogame_input.B):
            self.mode = LOOK
            self.select(None, self.cur_x, self.cur_y)
        if btn.just_pressed(picogame_input.Y):
            self.to_mode(TIME)

    def input_time(self, btn):
        step = 0.0
        if btn.repeat(picogame_input.RIGHT, 10, 2):
            step += 1 / 24.0
        if btn.repeat(picogame_input.LEFT, 10, 2):
            step -= 1 / 24.0
        if btn.repeat(picogame_input.UP, 10, 3):
            step += 1.0
        if btn.repeat(picogame_input.DOWN, 10, 3):
            step -= 1.0
        if step:
            self.frac += step
            self.set_time()
            self.moved = True
        if btn.just_pressed(picogame_input.A):
            when = board_time(self.tz)
            if when:                           # the board knows the time: follow it
                self.day, self.frac = when
                self.live = True
            else:                              # no clock: run on from the time shown
                self.live = not self.live
            self.set_time()
        if btn.just_pressed(picogame_input.X):
            y, mo, d, h, mi, s = skyastro.calendar(self.day, self.frac + self.tz / 24.0)
            self.day, self.frac = skyastro.from_calendar(y, mo, d, 22, 0)
            self.frac -= self.tz / 24.0
            self.live = False
            self.set_time()
        if btn.just_pressed(picogame_input.B):
            self.to_mode(self.back_mode)
        if btn.just_pressed(picogame_input.Y):
            self.to_mode(MENU)

    def input_menu(self, btn):
        n = len(self.menu_rows)
        if btn.repeat(picogame_input.UP, 10, 3):
            self.menu_i = (self.menu_i - 1) % n
            self.need_part = self.menu_dirty = True
        if btn.repeat(picogame_input.DOWN, 10, 3):
            self.menu_i = (self.menu_i + 1) % n
            self.need_part = self.menu_dirty = True
        if btn.just_pressed(picogame_input.A):
            item = self.menu_rows[self.menu_i][0]
            if item == "lines":
                self.show_lines = not self.show_lines
            elif item == "smooth":
                self.smooth = not self.smooth
            elif item == "names":
                self.show_names = not self.show_names
            elif item == "ecliptic":
                self.show_ecliptic = not self.show_ecliptic
            elif item == "red":
                self.red = not self.red
                apply_theme(self.red)
                self.paint_cursor()
            elif item == "anim":                # auto -> off -> light -> smooth -> full -> auto
                if self.anim_auto:
                    self.anim_auto = False
                    self.anim_level = 0
                elif self.anim_level < len(ANIM_NAMES) - 1:
                    self.anim_level += 1
                else:
                    self.anim_auto = True
                    self.anim_level = self.auto_level()
            elif item == "bright":
                self.bright_i = (self.bright_i + 1) % len(BRIGHTNESS)
                try:
                    self.display.brightness = BRIGHTNESS[self.bright_i]
                except (AttributeError, ValueError, RuntimeError):
                    self.has_brightness = False
            self.need_full = self.menu_dirty = True
        if btn.just_pressed(picogame_input.B) or btn.just_pressed(picogame_input.Y):
            self.to_mode(self.back_mode)

    def run(self, hook=None):
        """The frame loop; `hook` is called once a frame before input (a scripted demo uses it)."""
        while True:
            self.dt = self.clock.tick()
            if hook is not None:
                hook()
            self.handle_input()
            if self.glide is not None:
                self.moved = True
                self.need_full = True
            if self.live:
                self.frac += self.dt / 86400.0
                # the sky turns 1 px per ~10 s at the tightest zoom, slower when wide
                interval = 60 if ZOOM[self.zoom][0] >= 90 else 10
                if time.monotonic() - self.last_redraw > interval:
                    self.set_time()
            # while the sky moves the frames are lighter; the full chart follows when it stops
            if self.moved and self.anim_level:
                self.lod = True
                self.settle = 3
            elif self.settle:
                self.settle -= 1
                if self.settle == 0 and self.lod:
                    self.lod = False
                    self.need_full = True
            self.moved = False
            if self.need_full or self.need_part:
                self.update()
            if self.glide is not None:
                self.advance_glide()


if __name__ == "__main__":
    App().run()
