# Data sources and their licences

`sky.bin` is built from these files by `tools/sky_pack.py`; the files are
redistributed here so the catalogue can be rebuilt.

| file | source | licence |
|---|---|---|
| `bsc5.catalog.gz` | Yale Bright Star Catalogue, 5th revised edition (Hoffleit & Warren 1991), CDS V/50, <https://cdsarc.cds.unistra.fr/ftp/V/50/catalog.gz> | public domain (NASA Astronomical Data Center) |
| `constellations.json`, `constellations.lines.json` | d3-celestial by Olaf Frohn, <https://github.com/ofrohn/d3-celestial/tree/master/data> | BSD-3-Clause, below |
| `IAU-CSN.txt` | IAU Working Group on Star Names, Catalog of Star Names, <https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt> | CC BY 4.0, <https://creativecommons.org/licenses/by/4.0/>; attribution: "IAU Working Group on Star Names" |

Each star's constellation is computed when `sky.bin` is built, with pyephem's
implementation of the IAU constellation boundaries.

## d3-celestial

Copyright (c) 2015, Olaf Frohn
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
