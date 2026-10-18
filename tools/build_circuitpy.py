#!/usr/bin/env python3
"""Build CIRCUITPY/, the folder whose contents go onto the board's drive.

    python3 tools/build_circuitpy.py [--picogame-libs DIR]

CIRCUITPY/
  code.py                     a three-line stub that imports and runs the app
  sky.bin, icon.bmp           the catalogue and the launcher icon
  lib/picostellar.mpy         the app (code.py), compiled with mpy-cross -O2
  lib/sky*.mpy                the six modules, compiled the same way
  lib/skyviper.<arch>.mpy     the native kernels, copied from lib/
  lib/picogame_*.mpy          the three helpers; refreshed from DIR/mpy (or compiled
                              from DIR/*.py) when --picogame-libs is given, else kept

mpy-cross comes from $MPY_CROSS or PATH (build it in a CircuitPython tree with
`make -C mpy-cross`). Anything else found in CIRCUITPY/ is deleted, so a rename
leaves no stale module behind.

The app ships compiled because an RP2040 compiling the 47 KB source on the board
pays about a second at start and 4 KB of heap, and a compile that runs after the
sky buffers are allocated fails outright.
"""
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "CIRCUITPY")
MODULES = ("skyastro", "skybuffer", "skycatalog", "skykernel", "skyparams", "skyview")
HELPERS = ("picogame_game", "picogame_input", "picogame_clock")
NATIVE = ("skyviper.armv6m.mpy", "skyviper.armv7emsp.mpy")
COPIES = ("sky.bin", "icon.bmp")
STUB = ("import skybuffer      # the hot buffers first, while SRAM is free\n"
        "import picostellar    # the app, lib/picostellar.mpy\n"
        "picostellar.App().run()\n")


def mpy_cross():
    path = os.environ.get("MPY_CROSS") or shutil.which("mpy-cross")
    if not path or not os.access(path, os.X_OK):
        sys.exit("mpy-cross not found: put it on PATH or in MPY_CROSS")
    return path


def compile_to(mpyc, src, dst):
    # -s records only the file name, so tracebacks and the .mpy carry no build-machine path
    subprocess.run([mpyc, "-O2", "-s", os.path.basename(src), "-o", dst, src], check=True)


def main(argv):
    libs = None
    if "--picogame-libs" in argv:
        libs = os.path.abspath(argv[argv.index("--picogame-libs") + 1])
    mpyc = mpy_cross()
    lib = os.path.join(OUT, "lib")
    os.makedirs(lib, exist_ok=True)
    keep = set()

    for name in COPIES:
        shutil.copyfile(os.path.join(REPO, name), os.path.join(OUT, name))
        keep.add(name)
    with open(os.path.join(OUT, "code.py"), "w") as f:
        f.write(STUB)
    keep.add("code.py")
    compile_to(mpyc, os.path.join(REPO, "code.py"), os.path.join(lib, "picostellar.mpy"))
    keep.add("lib/picostellar.mpy")
    for name in NATIVE:
        shutil.copyfile(os.path.join(REPO, "lib", name), os.path.join(lib, name))
        keep.add("lib/" + name)
    for mod in MODULES:
        compile_to(mpyc, os.path.join(REPO, mod + ".py"), os.path.join(lib, mod + ".mpy"))
        keep.add("lib/" + mod + ".mpy")
    for mod in HELPERS:
        dst = os.path.join(lib, mod + ".mpy")
        if libs:
            ready = os.path.join(libs, "mpy", mod + ".mpy")
            if os.path.exists(ready):
                shutil.copyfile(ready, dst)
            else:
                compile_to(mpyc, os.path.join(libs, mod + ".py"), dst)
        elif not os.path.exists(dst):
            sys.exit("missing %s: pass --picogame-libs DIR (a picogame-libs checkout)" % dst)
        keep.add("lib/" + mod + ".mpy")

    for root, dirs, files in os.walk(OUT):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), OUT).replace(os.sep, "/")
            if rel not in keep:
                os.remove(os.path.join(root, f))
                print("removed", rel)

    total = 0
    for rel in sorted(keep):
        size = os.path.getsize(os.path.join(OUT, rel))
        total += size
        print("%7d  %s" % (size, rel))
    print("%7d  total" % total)


if __name__ == "__main__":
    main(sys.argv[1:])
