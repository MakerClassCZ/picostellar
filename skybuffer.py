"""The demo's hot buffers, allocated before anything else.

code.py imports this module first, while the heap still has room in SRAM: on a
Fruit Jam the heap runs on into PSRAM once SRAM is taken, and PSRAM writes
several times slower. The order below is the order of importance."""
import array
import gc

import picogame as pg
import picogame_game

picogame_game.open_framebuffer(320, 240)     # Fruit Jam DVI; a no-op on a fixed panel
W, H = picogame_game.screen()
FB_BAND_H = 16                               # the engine's PICOGAME_FB_SCRATCH_H: a framebuffer display
                                             # is composed in bands this tall (not exposed by the API)
ROWS = pg.STRIP_H                            # a panel: the render strips picogame_game.setup() builds
if getattr(picogame_game.display(), "framebuffer", None) is not None:
    ROWS = FB_BAND_H


gc.collect()
# Display-list records are 8 B (two lists, the faintest stars past the limit are dropped);
# line-bucket entries 2 B (past the limit the lines are drawn without buckets). The busiest
# view holds about 1,000 stars and 700 entries.
MAX_STARS = 1500
MAX_SEGS = 2500
MAX_VERTS = 800                              # sky.bin has 757 line vertices
SCRATCH = bytearray(W * ROWS * 2)            # written and blitted in every strip
STAR_SORTED = array.array("h", [0]) * (4 * MAX_STARS)    # read in every strip
SEGS = array.array("H", [0]) * MAX_SEGS                  # read in every strip
SCR = array.array("h", [0]) * (2 * MAX_VERTS)            # projected vertices, read in every strip
STAR_LIST = array.array("h", [0]) * (4 * MAX_STARS)      # written once a frame
