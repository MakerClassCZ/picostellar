"""View setup for the picostellar demo: where the observer looks, as the
rotation matrix and projection constants the kernels in skykernel/skyviper take.

A view is a centre direction (azimuth, altitude) and a scale. Scale K is the
pixel distance of a point 90 degrees away from the centre (stereographic), so
the whole visible sky from the zenith is a disc of radius K.

Every vector a View hands out is in the catalogue's J2000 frame: horizontal()
and equatorial() rotate their of-date result back by the precession matrix, so
the kernels project J2000 stars and of-date planets with one matrix and the
catalogue needs no per-star precession.
"""
import math

import skyastro
import skyparams

RAD = math.pi / 180.0


def _unit(ra, dec):
    ra *= RAD
    dec *= RAD
    c = math.cos(dec)
    return (c * math.cos(ra), c * math.sin(ra), math.sin(dec))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _scale(v, s):
    return (v[0] * s, v[1] * s, v[2] * s)


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


class View:
    """Observer's frame at (latitude, longitude) and local sidereal time."""

    def __init__(self, latitude, longitude):
        self.latitude = latitude
        self.longitude = longitude
        self.lst = 0.0
        self.up = (0.0, 0.0, 1.0)
        self.north = (1.0, 0.0, 0.0)
        self.east = (0.0, 1.0, 0.0)
        self.set_time(0, 0.0)

    def set_time(self, day, frac):
        self.day = day
        self.frac = frac
        self.prec = skyastro.precession_matrix(day, frac)
        self.lst = (skyastro.gmst(day, frac) + self.longitude) % 360.0
        # the horizon frame in equatorial coordinates
        self.up = _unit(self.lst, self.latitude)
        self.north = _unit(self.lst + 180.0, 90.0 - self.latitude)
        # (north, east, up) is left-handed inside the celestial sphere, hence the order
        self.east = _cross(self.north, self.up)
        # the same frame in catalogue coordinates, for az_alt()
        self.cat_up = self.to_catalogue(self.up)
        self.cat_north = self.to_catalogue(self.north)
        self.cat_east = self.to_catalogue(self.east)

    def to_catalogue(self, v):
        """An of-date equatorial vector in the catalogue's J2000 frame (P transposed)."""
        p = self.prec
        return (p[0][0] * v[0] + p[1][0] * v[1] + p[2][0] * v[2],
                p[0][1] * v[0] + p[1][1] * v[1] + p[2][1] * v[2],
                p[0][2] * v[0] + p[1][2] * v[1] + p[2][2] * v[2])

    def horizontal(self, az, alt):
        """Unit vector of a horizontal direction, in the catalogue's J2000 frame."""
        c = math.cos(alt * RAD)
        return self.to_catalogue(_add(_add(_scale(self.north, c * math.cos(az * RAD)),
                                           _scale(self.east, c * math.sin(az * RAD))),
                                      _scale(self.up, math.sin(alt * RAD))))

    def az_alt(self, v):
        """(azimuth, altitude) in degrees of a catalogue-frame unit vector."""
        up = v[0] * self.cat_up[0] + v[1] * self.cat_up[1] + v[2] * self.cat_up[2]
        n = v[0] * self.cat_north[0] + v[1] * self.cat_north[1] + v[2] * self.cat_north[2]
        e = v[0] * self.cat_east[0] + v[1] * self.cat_east[1] + v[2] * self.cat_east[2]
        return math.atan2(e, n) / RAD % 360.0, math.asin(max(-1.0, min(1.0, up))) / RAD

    def equatorial(self, ra, dec):
        """Unit vector of an of-date RA/Dec (Sun, Moon, planets), in the catalogue's J2000 frame."""
        return self.to_catalogue(_unit(ra, dec))

    def fill_params(self, params, az, alt, k, width, height, cx=None, cy=None, disc=False):
        """Point the view at (az, alt) with scale k and write everything the
        kernels need into params. With disc=True only the circle of radius k
        around the centre is drawn (the full-sky view); otherwise the whole
        rectangle."""
        centre = self.horizontal(az, alt)
        up = self.horizontal(az, alt + 90.0)        # zenith-ward on screen
        right = _cross(centre, up)            # seen from inside the sphere
        if cx is None:
            cx = width // 2
        if cy is None:
            cy = height // 2
        params[skyparams.P_W] = width
        params[skyparams.P_H] = height
        params[skyparams.P_CX] = cx
        params[skyparams.P_CY] = cy
        params[skyparams.P_K] = int(k)
        if disc:
            # the horizon itself lies at depth 0: keep its points despite Q15 rounding
            # (stars just below it still fall outside r2 and stay hidden)
            params[skyparams.P_ZMIN] = -200
            params[skyparams.P_R2] = int(k) * int(k)
        else:
            # the farthest screen corner, as an angle from the centre
            far = max(cx, width - cx) ** 2 + max(cy, height - cy) ** 2
            theta = 2.0 * math.atan(math.sqrt(far) / k)
            params[skyparams.P_ZMIN] = max(-16000, int(math.cos(theta) * 32767))
            params[skyparams.P_R2] = 0x3FFFFFFF
        for row, vec in enumerate((right, up, centre)):
            for col in range(3):
                params[skyparams.P_M00 + row * 3 + col] = int(round(vec[col] * 32767))
        params[skyparams.P_UX] = int(round(self.cat_up[0] * 32767))
        params[skyparams.P_UY] = int(round(self.cat_up[1] * 32767))
        params[skyparams.P_UZ] = int(round(self.cat_up[2] * 32767))
        params[skyparams.P_HMIN] = -300          # about -0.5 deg: stars on the horizon line stay
        self.right = right
        self.view_up = up
        self.centre = centre

    def project(self, vec, params):
        """Screen position of one unit vector (floats), or None when culled."""
        zz = vec[0] * self.centre[0] + vec[1] * self.centre[1] + vec[2] * self.centre[2]
        if zz * 32767 < params[skyparams.P_ZMIN] - 1:    # -1: horizon points sit exactly on the limit
            return None
        xx = vec[0] * self.right[0] + vec[1] * self.right[1] + vec[2] * self.right[2]
        yy = vec[0] * self.view_up[0] + vec[1] * self.view_up[1] + vec[2] * self.view_up[2]
        k = params[skyparams.P_K] / (1.0 + zz)
        return params[skyparams.P_CX] + xx * k, params[skyparams.P_CY] - yy * k
