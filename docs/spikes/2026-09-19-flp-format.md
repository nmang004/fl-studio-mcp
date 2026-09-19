# The `.flp` container, and why the index reads it itself

Measured 2026-09-19 on macOS 26, Apple silicon, FL Studio 2026 Producer Edition
v26.1.6 build 5406. Read-only: the five project files under
`~/Documents/Image-Line/FL Studio/Projects/Backup/` were copied to `/tmp` before
anything was parsed, and nothing was written under the home directory.

This document exists because Phase 6 wants to index a folder of projects, the obvious
route is the PyFLP library, and the measurements say that route does not work on these
files. Everything below is either an observation with the command that produced it or
is labelled as documentation.

## What was observed

**The corpus.** `find ~/Documents/Image-Line -type f -name '*.flp'` returns exactly
five files, all in `Projects/Backup/`, all autosaves of one untitled project, 53309 to
53646 bytes. Nothing else on the machine holds a project. This is a thin corpus and it
is recorded as a limit, not just as a convenience.

**The container.** `xxd -l 256` on a copy shows:

| Offset | Bytes | Reading |
| --- | --- | --- |
| 0x00 | `FLhd` | magic |
| 0x04 | uint32 LE 6 | header length |
| 0x08 | uint16 LE 0 | format |
| 0x0A | uint16 LE 5 | channel count |
| 0x0C | uint16 LE 96 | PPQ |
| 0x0E | `FLdt` | data magic |
| 0x12 | uint32 LE 53624 | data length |

53646 is 22 + 53624 exactly, and the same arithmetic holds for all five files
(53309 - 22 = 53287, 53502 - 22 = 53480). So the file is two length-prefixed chunks and
the second covers the rest of the file byte for byte. That exact-fit property is the
first integrity check the reader uses.

**Not compressed.** `zlib.decompress` fails with "incorrect header check" and a raw
deflate attempt with "invalid block type". The strings inside are plain UTF-16LE with
NUL terminators.

**The fields, read out of a real file.** With a corrected walk: tempo at file offset
0x80, bytes `9c d0 fb 01 00`, which is event 156 followed by 130000, so 130.000 BPM.
Time signature at 0x8F and 0x91, `11 04 12 04`, so numerator 4 and denominator 4. Title
at 0x9D, `c2 02 00`, an empty string, which matches a file called "untitled". The
version string is "26.1.6.5406". The channels are 808 Kick, 808 Clap, 808 HiHat and 808
Snare as samplers, plus a factory FLEX instance named "808 Astronomic", which agrees
with what the running project reports through the API.

## The finding that decides the design

The event size rule is published in the Kaitai spec `flp.ksy` and implemented
identically in PyFLP: the size field is 1 byte for an id below 64, 2 bytes below 128,
4 bytes below 192, and a base-128 little-endian varint above that.

A reimplementation of that rule, byte for byte the same rule PyFLP uses, walked four of
the five files exactly and desynced on the fifth, reading 1,065,338 bytes from a 53,287
byte section. Worse, on all five files it produced **zero** tempo, zero title and zero
time signature events while still landing exactly on EOF, so a caller checking only
"did the walk finish" sees a clean parse and an empty result.

The offending bytes are `AC 01 01 00 C0 36` followed by a 54 byte UTF-16 string,
"FL Studio 26.1.6.5406.5406". The published rule reads the `AC` event as 4 bytes and
then reads that string as about 27 junk one-byte events. Because the string is UTF-16,
most of those junk lengths are small and even, so the walk stays on the grid, re-syncs,
and hides the damage. Reading the `AC` event as 3 bytes instead, so that `C0` becomes
id 192 with a varint length of 54, produces a coherent header and walks all five files
exactly.

Confidence: high that the four fields exist, are plain little-endian or UTF-16LE, and
sit in the first 200 bytes of the payload. High that the payload is uncompressed.
Medium-high that a small reader with integrity checks works on FL 26. Low that any
reader survives a future FL release, because the failure mode is silence. Not
determined: the general FL 26 rule for the 128 to 191 id band, whether any FLP variant
is compressed, and VST plugin names, which live inside a plugin blob that none of these
projects contains.

The musical key is not in the format at all. It appears in neither the roughly 200 tag
ids of `flp.ksy` nor PyFLP's `Project` class, so the index does not report a key, and
the live FL path (`score.snap_root_note`, `score.snap_scale_helper`) stays the only
source for it.

## Why not PyFLP

| Question | Answer |
| --- | --- |
| Does it read these files | No. Its size rule returns zero tempo, title and time signature events for all five FL 2026 projects, measured by reimplementing the rule from its source |
| Licence | GPL-3.0. This repository is MIT, so vendoring or depending on it is a licensing decision, not only a technical one |
| Maintained | Latest release 2.2.1 on 2023-06-05, default branch untouched since 2023-07-10, 39 open issues |
| Dependencies | Four, one of which (`construct-typing`) shipped breaking changes in 2026 while PyFLP pins only a lower bound from 2023 |
| Read-only use | Yes, `parse()` only reads, though a bogus varint length makes its loop exit without raising |

It would add a licence problem, four dependencies and a dormant project, and still need
the hand written path for the fields it misses.

## What the reader therefore does

It reads the header, walks the events with the corrected size rule, and then refuses to
trust the walk unless it lands exactly at the end of the payload. It checks both
magics, checks that the declared data length is exactly the file size minus 22, and
rejects an out-of-range tempo rather than reporting it. Every failure is a status and a
reason per file, never an exception and never a guessed number, which is what an index
of somebody's work has to do.

The ongoing cost is honest and worth stating: the failure mode is silent, so each FL
Studio release needs the reader re-verified against a real project, and the local
corpus for that is five autosaves of one project with no VSTs in it.
