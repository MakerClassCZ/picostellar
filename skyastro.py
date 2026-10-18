"""Sun, Moon, planets and sidereal time for the picostellar demo, in degrees.

Keplerian elements and perturbation terms follow Paul Schlyter's "How to
compute planetary positions" (stjarnhimlen.se), sidereal time follows Meeus.
Positions are geocentric, ecliptic of date, accurate to a few arc minutes,
which is below one pixel on a 320 px sky. Only `math` is used, so it runs on
CircuitPython and in the desktop simulator alike.

Time is a pair (day, frac): whole days since 2000-01-01 0h UT as an int and
the fraction of the day as a float. CircuitPython floats are 32-bit, so a
Julian day held in one float would be rounded to six hours.
"""
import math

RAD = math.pi / 180.0
EPOCH_JD = 2451544.5                  # 2000-01-01 0h UT, day 0
PLANETS = ("Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune")


def from_calendar(year, month, day, hour=0, minute=0, second=0):
    """UT calendar date (Gregorian) -> (day, frac)."""
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    jdn = int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + b - 1524   # JD at 12h
    return jdn - 2451545, (hour * 3600 + minute * 60 + second) / 86400.0


def normalize(day, frac):
    """Carry a fraction that left [0, 1) into the day count."""
    if frac < 0.0 or frac >= 1.0:
        shift = int(frac // 1.0)
        day += shift
        frac -= shift
    return day, frac


def calendar(day, frac):
    """Inverse of from_calendar -> (year, month, day, hour, minute, second)."""
    day, frac = normalize(day, frac)
    z = 2451545 + day
    f = frac
    alpha = int((z - 1867216.25) / 36524.25)
    a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e)
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    secs = int(round(f * 86400))
    return year, month, day, secs // 3600, (secs // 60) % 60, secs % 60


def gmst(day, frac):
    """Greenwich mean sidereal time in degrees (Meeus 12.4).

    The 360 deg per day part of the rate is dropped exactly, so the float work
    only ever sees small angles."""
    dd = day - 0.5 + frac                 # days since J2000.0 (12h), for the tiny secular terms
    t = dd / 36525.0
    g = (280.46061837 + 180.0 + 0.98564736629 * (day - 0.5) + 360.98564736629 * frac
         + 0.000387933 * t * t - t * t * t / 38710000.0)
    return g % 360.0


def day_number(day, frac):
    """Schlyter's day number (days since 1999-12-31 0h) as one float."""
    return day + 1.0 + frac


def precession_matrix(day, frac):
    """Precession of the mean equator from J2000 to the date (IAU 1976, Lieske):
    rows of P with v_date = P v_J2000. The star catalogue is J2000; the Sun, the
    Moon, the planets and the sidereal time are of date."""
    t = (day - 0.5 + frac) / 36525.0     # Julian centuries since J2000.0
    arcsec = RAD / 3600.0
    zeta = (2306.2181 + (0.30188 + 0.017998 * t) * t) * t * arcsec
    z = (2306.2181 + (1.09468 + 0.018203 * t) * t) * t * arcsec
    theta = (2004.3109 - (0.42665 + 0.041833 * t) * t) * t * arcsec
    cze, sze = math.cos(zeta), math.sin(zeta)
    cz, sz = math.cos(z), math.sin(z)
    ct, st = math.cos(theta), math.sin(theta)
    return ((cze * cz * ct - sze * sz, -sze * cz * ct - cze * sz, -cz * st),
            (cze * sz * ct + sze * cz, -sze * sz * ct + cze * cz, -sz * st),
            (cze * st, -sze * st, ct))


def obliquity(d):
    return 23.4393 - 3.563e-7 * d


def _elements(name, d):
    """Mean orbital elements at day number d: (N, i, w, a, e, M) in degrees / AU."""
    if name == "Sun":
        return (0.0, 0.0, 282.9404 + 4.70935e-5 * d, 1.0, 0.016709 - 1.151e-9 * d,
                356.0470 + 0.9856002585 * d)
    if name == "Moon":
        return (125.1228 - 0.0529538083 * d, 5.1454, 318.0634 + 0.1643573223 * d, 60.2666,
                0.054900, 115.3654 + 13.0649929509 * d)
    if name == "Mercury":
        return (48.3313 + 3.24587e-5 * d, 7.0047 + 5.00e-8 * d, 29.1241 + 1.01444e-5 * d, 0.387098,
                0.205635 + 5.59e-10 * d, 168.6562 + 4.0923344368 * d)
    if name == "Venus":
        return (76.6799 + 2.46590e-5 * d, 3.3946 + 2.75e-8 * d, 54.8910 + 1.38374e-5 * d, 0.723330,
                0.006773 - 1.302e-9 * d, 48.0052 + 1.6021302244 * d)
    if name == "Mars":
        return (49.5574 + 2.11081e-5 * d, 1.8497 - 1.78e-8 * d, 286.5016 + 2.92961e-5 * d, 1.523688,
                0.093405 + 2.516e-9 * d, 18.6021 + 0.5240207766 * d)
    if name == "Jupiter":
        return (100.4542 + 2.76854e-5 * d, 1.3030 - 1.557e-7 * d, 273.8777 + 1.64505e-5 * d, 5.20256,
                0.048498 + 4.469e-9 * d, 19.8950 + 0.0830853001 * d)
    if name == "Saturn":
        return (113.6634 + 2.38980e-5 * d, 2.4886 - 1.081e-7 * d, 339.3939 + 2.97661e-5 * d, 9.55475,
                0.055546 - 9.499e-9 * d, 316.9670 + 0.0334442282 * d)
    if name == "Uranus":
        return (74.0005 + 1.3978e-5 * d, 0.7733 + 1.9e-8 * d, 96.6612 + 3.0565e-5 * d,
                19.18171 - 1.55e-8 * d, 0.047318 + 7.45e-9 * d, 142.5905 + 0.011725806 * d)
    if name == "Neptune":
        return (131.7806 + 3.0173e-5 * d, 1.7700 - 2.55e-7 * d, 272.8461 - 6.027e-6 * d,
                30.05826 + 3.313e-8 * d, 0.008606 + 2.15e-9 * d, 260.2471 + 0.005995147 * d)
    raise ValueError(name)


def _position(name, d):
    """Heliocentric (geocentric for Sun/Moon) ecliptic rectangular position and the
    mean anomaly, before perturbations: (x, y, z, M, lon, lat, r)."""
    n, i, w, a, e, m = _elements(name, d)
    m %= 360.0
    ecc = m + e / RAD * math.sin(m * RAD) * (1.0 + e * math.cos(m * RAD))
    for _ in range(5):
        ecc -= (ecc - e / RAD * math.sin(ecc * RAD) - m) / (1.0 - e * math.cos(ecc * RAD))
    xv = a * (math.cos(ecc * RAD) - e)
    yv = a * math.sqrt(1.0 - e * e) * math.sin(ecc * RAD)
    v = math.atan2(yv, xv) / RAD
    r = math.sqrt(xv * xv + yv * yv)
    vw = (v + w) * RAD
    nr = n * RAD
    ir = i * RAD
    x = r * (math.cos(nr) * math.cos(vw) - math.sin(nr) * math.sin(vw) * math.cos(ir))
    y = r * (math.sin(nr) * math.cos(vw) + math.cos(nr) * math.sin(vw) * math.cos(ir))
    z = r * math.sin(vw) * math.sin(ir)
    lon = math.atan2(y, x) / RAD % 360.0
    lat = math.atan2(z, math.sqrt(x * x + y * y)) / RAD
    return x, y, z, m, lon, lat, r


def _sun(d):
    x, y, z, m, lon, lat, r = _position("Sun", d)
    return lon, r, m


def _moon(d, sun_m, sun_w):
    x, y, z, mm, lon, lat, r = _position("Moon", d)
    n, i, w, a, e, m = _elements("Moon", d)
    ls = (sun_m + sun_w) % 360.0            # Sun's mean longitude
    lm = (mm + w + n) % 360.0               # Moon's mean longitude
    dd = (lm - ls) * RAD                    # mean elongation
    f = (lm - n) * RAD                      # argument of latitude
    ms = sun_m * RAD
    mm *= RAD
    lon += (-1.274 * math.sin(mm - 2 * dd) + 0.658 * math.sin(2 * dd) - 0.186 * math.sin(ms)
            - 0.059 * math.sin(2 * mm - 2 * dd) - 0.057 * math.sin(mm - 2 * dd + ms)
            + 0.053 * math.sin(mm + 2 * dd) + 0.046 * math.sin(2 * dd - ms)
            + 0.041 * math.sin(mm - ms) - 0.035 * math.sin(dd) - 0.031 * math.sin(mm + ms)
            - 0.015 * math.sin(2 * f - 2 * dd) + 0.011 * math.sin(mm - 4 * dd))
    lat += (-0.173 * math.sin(f - 2 * dd) - 0.055 * math.sin(mm - f - 2 * dd)
            - 0.046 * math.sin(mm + f - 2 * dd) + 0.033 * math.sin(f + 2 * dd)
            + 0.017 * math.sin(2 * mm + f))
    r += -0.58 * math.cos(mm - 2 * dd) - 0.46 * math.cos(2 * dd)
    return lon % 360.0, lat, r


def _perturb(name, lon, lat, d):
    """Jupiter, Saturn and Uranus pull each other by up to a degree."""
    mj = _elements("Jupiter", d)[5] * RAD
    ms = _elements("Saturn", d)[5] * RAD
    mu = _elements("Uranus", d)[5] * RAD
    s = math.sin
    c = math.cos
    deg = RAD
    if name == "Jupiter":
        lon += (-0.332 * s(2 * mj - 5 * ms - 67.6 * deg) - 0.056 * s(2 * mj - 2 * ms + 21 * deg)
                + 0.042 * s(3 * mj - 5 * ms + 21 * deg) - 0.036 * s(mj - 2 * ms)
                + 0.022 * c(mj - ms) + 0.023 * s(2 * mj - 3 * ms + 52 * deg)
                - 0.016 * s(mj - 5 * ms - 69 * deg))
    elif name == "Saturn":
        lon += (0.812 * s(2 * mj - 5 * ms - 67.6 * deg) - 0.229 * c(2 * mj - 4 * ms - 2 * deg)
                + 0.119 * s(mj - 2 * ms - 3 * deg) + 0.046 * s(2 * mj - 6 * ms - 69 * deg)
                + 0.014 * s(mj - 3 * ms + 32 * deg))
        lat += -0.020 * c(2 * mj - 4 * ms - 2 * deg) + 0.018 * s(2 * mj - 6 * ms - 49 * deg)
    elif name == "Uranus":
        lon += (0.040 * s(ms - 2 * mu + 6 * deg) + 0.035 * s(ms - 3 * mu + 33 * deg)
                - 0.015 * s(mj - mu + 20 * deg))
    return lon, lat


def ecliptic_to_equatorial(lon, lat, d):
    """Ecliptic longitude/latitude of date -> (ra, dec) in degrees; d is the
    day number from day_number (0 for the J2000 ecliptic)."""
    e = obliquity(d) * RAD
    lon *= RAD
    lat *= RAD
    x = math.cos(lon) * math.cos(lat)
    y = math.sin(lon) * math.cos(lat)
    z = math.sin(lat)
    ye = y * math.cos(e) - z * math.sin(e)
    ze = y * math.sin(e) + z * math.cos(e)
    return math.atan2(ye, x) / RAD % 360.0, math.atan2(ze, math.sqrt(x * x + ye * ye)) / RAD


def equatorial_to_horizontal(ra, dec, lst, lat):
    """-> (azimuth from north through east, altitude) in degrees."""
    h = (lst - ra) * RAD
    dec *= RAD
    lat *= RAD
    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(h)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    y = -math.cos(dec) * math.sin(h)
    x = math.sin(dec) * math.cos(lat) - math.cos(dec) * math.sin(lat) * math.cos(h)
    return math.atan2(y, x) / RAD % 360.0, alt / RAD


def bodies(day, frac):
    """Geocentric positions of the Sun, the Moon and the planets at (day, frac).

    -> dict name -> (ra, dec, extra): extra is the Moon's illuminated fraction
    (0..1, positive when waxing, negative when waning), otherwise the distance
    from Earth in AU.
    """
    d = day_number(day, frac)
    sun_lon, sun_r, sun_m = _sun(d)
    sun_w = _elements("Sun", d)[2]
    out = {}
    ra, dec = ecliptic_to_equatorial(sun_lon, 0.0, d)
    out["Sun"] = (ra, dec, sun_r)

    lon, lat, r = _moon(d, sun_m, sun_w)
    ra, dec = ecliptic_to_equatorial(lon, lat, d)
    elong = (lon - sun_lon) % 360.0
    fraction = (1.0 - math.cos(elong * RAD)) / 2.0
    out["Moon"] = (ra, dec, fraction if elong < 180.0 else -fraction)

    xs = sun_r * math.cos(sun_lon * RAD)
    ys = sun_r * math.sin(sun_lon * RAD)
    for name in PLANETS:
        x, y, z, m, lon, lat, r = _position(name, d)
        lon, lat = _perturb(name, lon, lat, d)
        xh = r * math.cos(lon * RAD) * math.cos(lat * RAD)
        yh = r * math.sin(lon * RAD) * math.cos(lat * RAD)
        zh = r * math.sin(lat * RAD)
        xg = xh + xs
        yg = yh + ys
        dist = math.sqrt(xg * xg + yg * yg + zh * zh)
        glon = math.atan2(yg, xg) / RAD % 360.0
        glat = math.atan2(zh, math.sqrt(xg * xg + yg * yg)) / RAD
        ra, dec = ecliptic_to_equatorial(glon, glat, d)
        out[name] = (ra, dec, dist)
    return out


def moon_age_days(day, frac):
    """Days since new Moon, from the Sun-Moon elongation."""
    d = day_number(day, frac)
    sun_lon, sun_r, sun_m = _sun(d)
    lon, lat, r = _moon(d, sun_m, _elements("Sun", d)[2])
    return ((lon - sun_lon) % 360.0) / 360.0 * 29.530589
