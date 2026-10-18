#!/usr/bin/env python3
"""Check skyastro against pyephem (VSOP87/ELP based) on a spread of dates.

Run from anywhere: tools/test_skyastro.py. Needs `ephem` on the host only.
Tolerances: Sun 0.05 deg, Moon 0.25 deg, planets 0.3 deg, sidereal time 2 s (mean vs apparent).
"""
import math
import os
import sys

import ephem

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import skyastro  # noqa: E402

DATES = [(1992, 4, 12, 0, 0, 0), (2000, 1, 1, 12, 0, 0), (2013, 7, 21, 21, 30, 0),
         (2026, 10, 14, 20, 0, 0), (2030, 3, 1, 3, 15, 0), (1987, 4, 10, 0, 0, 0)]
BODIES = {"Sun": ephem.Sun, "Moon": ephem.Moon, "Mercury": ephem.Mercury, "Venus": ephem.Venus,
          "Mars": ephem.Mars, "Jupiter": ephem.Jupiter, "Saturn": ephem.Saturn,
          "Uranus": ephem.Uranus, "Neptune": ephem.Neptune}
TOL = {"Sun": 0.05, "Moon": 0.25}


def sep(ra1, dec1, ra2, dec2):
    r = math.radians
    c = (math.sin(r(dec1)) * math.sin(r(dec2))
         + math.cos(r(dec1)) * math.cos(r(dec2)) * math.cos(r(ra1 - ra2)))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def main():
    failures = 0
    worst = {}
    for y, mo, d, h, mi, s in DATES:
        day, frac = skyastro.from_calendar(y, mo, d, h, mi, s)
        date = ephem.Date((y, mo, d, h, mi, s))
        assert abs(skyastro.EPOCH_JD + day + frac - (date + 2415020.0)) < 1e-6, (day, frac, date + 2415020.0)
        # sidereal time
        obs = ephem.Observer()
        obs.lon = "0"
        obs.lat = "0"
        obs.date = date
        g_ref = math.degrees(float(obs.sidereal_time()))
        g = skyastro.gmst(day, frac)
        dg = abs((g - g_ref + 180) % 360 - 180)
        worst["gmst"] = max(worst.get("gmst", 0), dg)
        if dg > 15 / 3600 * 2.0:            # ephem gives apparent sidereal time: nutation adds up to 1.2 s
            failures += 1
            print("FAIL gmst %s: %.5f vs %.5f" % (date, g, g_ref))
        # bodies
        ours = skyastro.bodies(day, frac)
        for name, cls in BODIES.items():
            body = cls(date)                # geocentric apparent, equinox of date
            ra_ref = math.degrees(float(body.g_ra))
            dec_ref = math.degrees(float(body.g_dec))
            ra, dec, extra = ours[name]
            e = sep(ra, dec, ra_ref, dec_ref)
            worst[name] = max(worst.get(name, 0), e)
            if e > TOL.get(name, 0.3):
                failures += 1
                print("FAIL %-8s %s: %.3f deg off (%.3f,%.3f vs %.3f,%.3f)" % (
                    name, date, e, ra, dec, ra_ref, dec_ref))
            if name == "Moon":
                f_ref = body.phase / 100.0
                if abs(abs(extra) - f_ref) > 0.02:
                    failures += 1
                    print("FAIL Moon phase %s: %.3f vs %.3f" % (date, abs(extra), f_ref))
        # round trip of the calendar
        assert skyastro.calendar(day, frac)[:5] == (y, mo, d, h, mi), skyastro.calendar(day, frac)
    for k in sorted(worst):
        print("worst %-8s %.4f deg" % (k, worst[k]))
    # precession: J2000 catalogue places carried to the date match pyephem's mean place of date
    worst_prec = 0.0
    shift = 0.0
    for name, ra0, dec0 in (("Sirius", 101.287155, -16.71611), ("Polaris", 37.954561, 89.26410),
                            ("Vega", 279.234735, 38.783689), ("Acrux", 186.649563, -63.09909)):
        for y, mo, d, h, mi, s in DATES:
            day, frac = skyastro.from_calendar(y, mo, d, h, mi, s)
            pm = skyastro.precession_matrix(day, frac)
            r = math.radians
            v = (math.cos(r(dec0)) * math.cos(r(ra0)), math.cos(r(dec0)) * math.sin(r(ra0)), math.sin(r(dec0)))
            vd = [sum(pm[i][j] * v[j] for j in range(3)) for i in range(3)]
            ra = math.degrees(math.atan2(vd[1], vd[0])) % 360
            dec = math.degrees(math.asin(vd[2]))
            star = ephem.FixedBody()
            star._ra = r(ra0)
            star._dec = r(dec0)
            star._epoch = ephem.J2000
            date = ephem.Date((y, mo, d, h, mi, s))
            star.compute(date, epoch=date)
            e = sep(ra, dec, math.degrees(float(star.a_ra)), math.degrees(float(star.a_dec)))
            worst_prec = max(worst_prec, e)
            shift = max(shift, sep(ra, dec, ra0, dec0))
    print("worst precession %.5f deg (largest J2000 -> date shift %.3f deg)" % (worst_prec, shift))
    # the view hands out catalogue-frame vectors: an of-date place must land on its J2000 vector
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "sim"))
    import skyview
    view = skyview.View(50.09, 14.42)
    day, frac = skyastro.from_calendar(2026, 10, 14, 20)
    view.set_time(day, frac)
    r = math.radians
    v = (math.cos(r(-16.71611)) * math.cos(r(101.287155)), math.cos(r(-16.71611)) * math.sin(r(101.287155)),
         math.sin(r(-16.71611)))
    vd = [sum(view.prec[i][j] * v[j] for j in range(3)) for i in range(3)]
    back = view.equatorial(math.degrees(math.atan2(vd[1], vd[0])), math.degrees(math.asin(vd[2])))
    err = max(abs(back[i] - v[i]) for i in range(3))
    print("view round trip error %.2e" % err)
    if err > 1e-9:
        failures += 1
        print("FAIL view frame")
    if worst_prec > 0.002:
        failures += 1
        print("FAIL precession")
    # horizontal coordinates: Polaris from Prague is near the pole's altitude = latitude
    day, frac = skyastro.from_calendar(2026, 10, 14, 20)
    lst = (skyastro.gmst(day, frac) + 14.42) % 360
    az, alt = skyastro.equatorial_to_horizontal(37.95, 89.26, lst, 50.09)
    assert abs(alt - 50.09) < 0.8 and (az < 1.5 or az > 358.5), (az, alt)
    print("Polaris from Prague: az %.2f alt %.2f" % (az, alt))
    print("RESULT", "PASS" if failures == 0 else "FAIL %d" % failures)
    return failures


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
