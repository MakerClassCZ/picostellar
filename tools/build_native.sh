#!/usr/bin/env bash
# Compile skyviper.py to native .mpy files for the boards picogame runs on:
#   lib/skyviper.armv7emsp.mpy   RP2350, SAMD51, nRF52 (Cortex-M4F / M33)
#   lib/skyviper.armv6m.mpy      RP2040 (Cortex-M0+)
# CircuitPython loads skyviper.<microcontroller.cpu.architecture>.mpy; a board
# with no matching file falls back to skykernel.py.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
MPYC="${MPY_CROSS:-$(command -v mpy-cross || true)}"
[ -n "$MPYC" ] && [ -x "$MPYC" ] || { echo "mpy-cross not found: build it from the CircuitPython tree (make -C mpy-cross) and put it on PATH or in MPY_CROSS"; exit 1; }
mkdir -p "$HERE/lib"
for arch in armv7emsp armv6m; do
  "$MPYC" -march=$arch -O3 -s skyviper.py -o "$HERE/lib/skyviper.$arch.mpy" "$HERE/skyviper.py"
  echo "lib/skyviper.$arch.mpy $(stat -c %s "$HERE/lib/skyviper.$arch.mpy") B"
done
