"""The layout of the kernels' parameter block and the culled-point marker.

Shared by skykernel, skyview and the app, so a board running the native kernels
(skyviper, which keeps its own copies as compile-time constants) never loads
the Python kernels just for these numbers. The block itself is described in
skykernel.
"""
import array

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
P_UX = const(18)                   # the zenith in catalogue coordinates, Q15: stars below the
P_UY = const(19)                   # horizon (up . v < P_HMIN) are not drawn
P_UZ = const(20)
P_HMIN = const(21)
P_COUNT = const(22)

CULLED = const(-32768)             # project() writes it for a point behind the view limit

# the per-strip block draw_strip() and draw_bucket() take (an array('i'))
SP_W = const(0)                    # strip width
SP_BAND = const(1)                 # rows in this band
SP_OY = const(2)                   # screen row of the band's first row
SP_LINE = const(3)                 # colours: constellation lines, the highlighted constellation,
SP_HILITE = const(4)               #   the ecliptic, the horizon
SP_ECLIPTIC = const(5)
SP_HORIZON = const(6)
SP_HL_FIRST = const(7)             # the highlighted constellation's segment range
SP_HL_END = const(8)
SP_SMOOTH = const(9)               # anti-aliased lines
SP_ROWS = const(10)                # rows per bucket
SP_NSTRIPS = const(11)             # bucket count
SP_BUCKETS = const(12)             # line buckets valid (0: no lines this frame)
SP_COUNT = const(13)


def new_params():
    return array.array("i", [0]) * P_COUNT


def new_strip_params():
    return array.array("i", [0]) * SP_COUNT
