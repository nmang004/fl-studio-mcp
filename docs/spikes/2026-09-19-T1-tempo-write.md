# Spike T1: Tempo write

**Date:** 2026-09-19
**Status:** Open. The read half is resolved and measured; the write half is not
measured at all.
**Environment:** FL Studio 2026 (Producer Edition v26.1.6, build 5406), scripting
API version 45, macOS 26, Apple silicon. Stubs v37.0.1.

## The question

ROADMAP.md lists T1 as:

> **T1: Tempo write.** Half resolved. Reading works and the scaling is confirmed
> as thousandths of a BPM (`getCurrentTempo` returned 130000 at 130 BPM). What
> remains is the write path: `general.processRECEvent` with `midi.REC_Tempo` and
> the right flag combination, likely `REC_UpdateValue | REC_UpdateControl`.

That is two questions, and only one of them is answered:

1. **Read.** What unit does `mixer.getCurrentTempo()` use? Resolved by
   measurement: thousandths of a BPM.
2. **Write.** Is there a function that sets the project tempo, what event id and
   flag word does it need, and does the value stick? Unresolved. Nothing has been
   measured.

## Summary

- Reading is settled by measurement, not by inference.
- Writing has no dedicated API. Exactly one candidate path exists in the whole
  stub set, and that function's own stub tells you to avoid it.
- The event id and the value scaling are documented in the stubs, but documented
  is not measured. The flag semantics for the tempo event specifically are not
  documented anywhere.
- **Nothing about the write has been measured on live FL Studio.** The project's
  test harness models a plausible FL, and that model is not evidence.
- What landed is an instrument, not a feature: a `system.tempoProbe` controller
  action that performs one write and reports the numbers, plus `tests/test_tempo.py`
  covering its report shape and its refusals. No `fl_set_tempo` server tool was
  added, and none should be until the measurement exists.
- Recommendation: run the probe on a scratch project before anything depends on
  this. Tempo stays read only until a read-back in a later callback confirms the
  write.

## Verified by reading the stubs

### Reading: the only tempo function in the API

`mixer.getCurrentTempo(asInt=False)` (`mixer/__properties.py` line 80, "Included
since API version 1") is the only function in the entire stub package whose name
contains "tempo". Outside `midi`, where the `REC_Tempo` constant lives, the
remaining case-insensitive matches for "tempo" are the unrelated word "temporary",
in `channels/__ui.py` and `playlist/__performance.py`.

### Writing: no setter exists

A grep over every stub module finds no `setTempo`, `tempoSet` or equivalent in
`mixer`, `transport`, `general`, `ui`, `arrangement`, `patterns`, `playlist`,
`channels`, `plugins` or `device`. `channels.processRECEvent`
(`channels/__properties.py` line 835) exists, but its own docstring marks it
deprecated and moved to `general.processRECEvent` as of API version 7.

The path the roadmap assumed is therefore the only path, not merely the preferred
one.

### `general.processRECEvent` advises against itself

`general/__fl_state.py` line 98:

```py
def processRECEvent(eventId: int, value: int, flags: int) -> int:
```

"Included since API version 7", so it exists on API 45. Its docstring says,
verbatim:

> ## Try to achieve your task with other API functions first!
>
> This part of FL's scripting API is incomplete, poorly documented, and filled
> with hidden bugs. REC events expose more controls inside FL Studio, while being
> *much* more confusing than other parts of the API.

The same docstring carries an upstream HELP WANTED asking Image-Line for "More
details on what `flags` can do". The argument documentation points at the manual,
apart from one warning worth quoting in full:

- `eventId`: "Refer to the FL Studio manual".
- `value`: "value of even within a range" (sic), and "This range depends on the
  plugin, but you can specify for it to be between `0 - 2^30` by using the
  `midi.REC_MIDIController` flag. Note that providing an invalid value can lead to
  very strange behavior and sometimes crashes."
- `flags`: "Refer to the FL Studio manual".
- Returns: "int: Unknown."

Two consequences shape the probe. The crash warning is why it refuses a
non-positive or non-finite BPM rather than trying one out on a real project. The
unknown return is why it reports `process_rec_result` instead of interpreting it.

### The event id

`midi/__rec_events/ranges.py` defines `REC_ItemRange = 0x10000` (line 5) and
`REC_Global_First = 0x4000 * REC_ItemRange` (line 42).
`midi/__rec_events/global_properties.py` line 36 defines
`REC_Tempo = REC_Global_First + 5`, which is `0x40000005`, or `1073741829`.

The same file documents the scaling (line 37): "This is stored as `1000 * tempo`,
meaning that to set a tempo of `85 BPM`, you will need to set the value as
`85 * 1000`." That agrees with the one live reading, `130000` at 130 BPM.

The id being arithmetic over constants is not proof that FL accepts it.
`midi/__rec_events/process_flags.py` line 141 defines `REC_InvalidID = MaxInt`
with the docstring "ProcessRECEvent returns this when the ID is invalid", so there
is a documented way for the call to reject the id. The probe reports both the id it
sent and whatever the call returned.

### Candidate flag words, and why each is plausible

From `midi/__rec_events/process_flags.py`:

- `REC_UpdateValue = 1 << 0` (line 9): "Update the value associated with the event
  ID."
- `REC_UpdateControl = 1 << 4` (line 29): "Update the wheel/knob associated with
  the parameter. Without this, any changes won't be shown in FL Studio's UI."
- `REC_FromMIDI = 1 << 5` (line 35): "The given value is in the range `0` to
  `midi.FromMIDI_Max`. If this flag is specified, then FL Studio automatically
  converts the value into the required range for the parameter."
- `REC_SetAll` (line 125): `REC_UpdateValue | REC_UpdateControl | REC_InitStore |
  REC_SetChanged | REC_SetTouched`, commented "called externally".
- `REC_Control` (line 103, defined a second time with the same value at line 127):
  `REC_UpdateValue | REC_ShowHint | REC_InitStore | REC_SetChanged |
  REC_UpdatePlugLabel | REC_SetTouched`, documented as "Used for changing values
  from a MIDI controller, but where the value is already in the right units."

| Candidate | Value | Why it is plausible | What a failure would look like |
| --- | --- | --- | --- |
| `REC_UpdateValue \| REC_UpdateControl` | 17 | The smallest word that both stores a value and refreshes the UI. This is the probe's default. | Nothing moves |
| `REC_Control \| REC_UpdateControl` | 989 | The stubs' own worked example for this exact task, in the module docstring of `midi/__rec_events/global_properties.py`: set tempo to 80.5 BPM with these flags. The strongest evidence available without running it. | Nothing moves |
| `REC_SetAll` | 977 | The bundle commented "called externally", which is what a controller script is. | Nothing moves |
| `REC_UpdateValue` | 1 | The value changes but, per the `REC_UpdateControl` docstring, the UI does not follow. A working write could look like nothing happened. | Tempo changes with a stale display, which is itself a finding |
| `REC_MIDIController`, that is `REC_Control \| REC_FromMIDI` | 1005 | Included only to rule the value-conversion path out. | The raw thousandths are reinterpreted as a fraction of `FromMIDI_Max`, so the tempo lands somewhere unrelated |

The probe defaults to 17 and accepts an optional `flags` parameter, so one live
session can compare all of these without editing the script. The reply echoes the
flag word and names the bits it recognises.

One caveat applies to every row: those are documented semantics for REC events in
general, not for the tempo event. Nothing in the stubs says the tempo event honours
any of it.

### Not documented, and therefore not assumed

- Whether the write takes effect during the same callback or on a later idle pass.
  A read-back in the same callback could therefore show the old value on a write
  that actually worked, which is why the runbook below includes a second read in a
  separate command.
- Whether the value is stored exactly as written or quantised by the tempo
  control. A write of `140500` may read back as `140500` or as something nearby.
- The tempo's permitted range. The stubs give none for this event, and warn that
  an invalid value can crash FL.
- Whether the write creates an undo entry, and whether `general.undo()` reverses
  it.

There is a precedent in this repo for not trusting an inferred convention. The
pattern accessors turned out to mix 0-based and 1-based indexes with nothing in the
stubs saying so, which `_pattern_entry` in `fl_controller/device_FLStudioMCP.py`
now records as a measured fact. The REC constants and flag semantics are just as
capable of being inconsistent, and flagged as much by the stub's own HELP WANTED.
Treat the table above as candidates, not as a recipe.

## Not measured live

**No tempo write has been performed against FL Studio for this spike.** Everything
in the section above is reading, and reading is not measuring. The only live tempo
fact recorded anywhere in this repo remains the read: `mixer.getCurrentTempo()`
returned `130000` on a 130 BPM project, measured 2026-09-19 and recorded in
ROADMAP.md under "Verified against live FL Studio".

The probe was deliberately not run while writing this document. It changes the
tempo of whatever project is open, and its restore path is itself an unverified
write, so running it needs the project owner's explicit agreement. That agreement
has not been given.

### The exact commands to measure it

Preconditions:

- [ ] The controller at
      `~/Documents/Image-Line/FL Studio/Settings/Hardware/FLStudioMCP/device_FLStudioMCP.py`
      is this repo's `fl_controller/device_FLStudioMCP.py`, which contains
      `system.tempoProbe`. Copy it over. The controller hot-reloads, which was
      measured for T4, so no FL restart is needed.
- [ ] FL Studio is open, the controller is enabled, and FL is answering:
      `uv run python scripts/dev_verify_connection.py`.
- [ ] Use a scratch project, or save first, and note the current tempo in BPM so it
      can be set back by hand if every write path fails.

**Command 1: one shot, writes and restores.**

```bash
uv run python - <<'PY'
from fl_studio_mcp.utils.midi_connection import get_connection

conn = get_connection()
if not conn.connect():
    raise SystemExit(conn.connection_error)
reply = conn.send_command(
    "system.tempoProbe", {"bpm": 140.0, "restore": True}, timeout=5.0
)
print(reply)
PY
```

Read four fields: `tempo_before`, `tempo_after`, `write_verified` (the read-back
equals the value asked for) and `restore_verified` (the project is back at the
tempo it started with). If `write_verified` is false and `tempo_after` equals
`tempo_before`, the write did not land. If `write_verified` is true and
`restore_verified` is false, the tempo moved and did not come back, so set it back
by hand.

**Command 2: the decisive sequence, for whether the value persists.**

Command 1 reads back in the same callback, which is weak evidence. This one writes,
then reads in a separate round trip, then restores:

```bash
uv run python - <<'PY'
from fl_studio_mcp.utils.midi_connection import get_connection

conn = get_connection()
if not conn.connect():
    raise SystemExit(conn.connection_error)

# 1. Write, without restoring.
print("write  ", conn.send_command("system.tempoProbe", {"bpm": 140.0}, timeout=5.0))

# 2. Read in a later callback. This is the measurement.
info = conn.send_command("system.getInfo", {}, timeout=5.0)
print("later  ", info.get("capabilities", {}).get("getCurrentTempo"))

# 3. Put it back. Change 130.0 to the tempo noted before the run. This call has
#    restore false on purpose: with restore true the probe would put back
#    whatever it read first, which by now is the 140.0 being replaced.
print("restore", conn.send_command("system.tempoProbe", {"bpm": 130.0}, timeout=5.0))
PY
```

A `later` value of `140000` is a confirmed write. A `later` value of `130000` with
`write_verified: true` in step 1 means the value did not persist past the callback,
which is a different and equally useful finding.

**Command 3: the flag sweep, only if commands 1 and 2 do not settle it.**

```bash
uv run python - <<'PY'
import midi

from fl_studio_mcp.utils.midi_connection import get_connection

conn = get_connection()
if not conn.connect():
    raise SystemExit(conn.connection_error)

candidates = [
    ("update only", midi.REC_UpdateValue),
    ("update + control", midi.REC_UpdateValue | midi.REC_UpdateControl),
    ("stub example", midi.REC_Control | midi.REC_UpdateControl),
    ("set all", midi.REC_SetAll),
    ("midi controller", midi.REC_MIDIController),
]
for name, flags in candidates:
    reply = conn.send_command(
        "system.tempoProbe",
        {"bpm": 140.0, "restore": True, "flags": flags},
        timeout=5.0,
    )
    print(name, flags, reply.get("changed"), reply.get("write_verified"),
          reply.get("restore_verified"), reply.get("error"))
PY
```

Two warnings about this sweep. First, it is the one command that can leave the
project somewhere unexpected: the restore uses the same flag word as the write, so
a flag word that makes FL reinterpret the value can fail to restore the original.
Check `restore_verified` after every line, and set the tempo by hand if it is
false. Second, `REC_MIDIController` asks FL to convert the value from a range of 0
to `FromMIDI_Max`, so expect it to land somewhere unrelated; it is in the list only
to rule that conversion path out.

## The probe's reply shape

`system.tempoProbe` takes `bpm` (required, a number), `restore` (optional bool,
default false) and `flags` (optional int, default 17). It never raises: every
failure, including a refusal, comes back as an `error` field. The response
envelope adds `success` and the request `id`.

| Key | Meaning |
| --- | --- |
| `event_id` | The REC event id sent, `1073741829` from the stubs |
| `requested_bpm` | The BPM the caller asked for |
| `requested_value` | `int(bpm * 1000)`, the raw value sent |
| `tempo_before` | The read before the write |
| `bpm_before` | The same value divided by 1000, for reading |
| `flags` | The flag word used |
| `flag_names` | The bits of that word this repo can name |
| `process_rec_result` | Whatever `processRECEvent` returned, or null |
| `tempo_after` | The read immediately after the write |
| `bpm_after` | The same, divided by 1000 |
| `changed` | `tempo_after != tempo_before`, or null if unreadable |
| `write_verified` | `tempo_after == requested_value`, or null if unreadable |
| `restore` | Whether a restore was requested |
| `tempo_restored` | The read after the restore, else null |
| `bpm_restored` | The same, divided by 1000 |
| `restore_verified` | `tempo_restored == tempo_before`, else null |

`error` is absent from a report that reached the write, and present when the probe
refused, when a read failed, or when a call raised. A raised write is not a dead
end: the read-back and the restore still run, so one reply can carry both an
`error` and `write_verified: true`. Read the whole reply, not just `success`.

An example, and it matters where it came from: the reply below was produced by the
project's fake harness, with the fake configured to model a write that lands. It
shows the shape only. No live reply of this kind exists yet.

```json
{
  "success": true,
  "id": "t1",
  "event_id": 1073741829,
  "requested_bpm": 140.5,
  "requested_value": 140500,
  "tempo_before": 130000.0,
  "bpm_before": 130.0,
  "flags": 17,
  "flag_names": [
    "REC_UpdateValue",
    "REC_UpdateControl"
  ],
  "process_rec_result": null,
  "tempo_after": 140500.0,
  "bpm_after": 140.5,
  "changed": true,
  "write_verified": true,
  "restore": true,
  "tempo_restored": 130000.0,
  "bpm_restored": 130.0,
  "restore_verified": true
}
```

## What shipping a `fl_set_tempo` tool would require

1. **A live measurement.** Commands 1 and 2 above, on a real project, with the
   reply recorded in this document. Without it, a tool would encode a guess about
   an API whose own documentation says it is full of hidden bugs.
2. **A read-back that confirms the write, in a later callback.** The tool must
   verify rather than trust: call `processRECEvent`, read `mixer.getCurrentTempo()`
   again in a following command, and report failure when the value did not move. A
   tempo setter that silently does nothing is worse than no tool, because the
   caller has no way to tell the difference.
3. **An undo or restore path.** `general.undo()` is a toggle, measured and
   recorded in ROADMAP.md, so if the tempo write does not create an undo entry the
   tool cannot promise undo. Whether it does is unmeasured.
4. **A measured value range.** The stubs give the tempo event no range and warn
   that an invalid value can crash FL, so any range check has to come from a live
   build.
5. **A confirmed flag word**, or a documented default with the build it was
   measured on.

Until 1 and 2 hold, tempo stays read only. `mixer.getCurrentTempo()` and the tempo
field in `fl_get_version` already ship, and they are honest.

## What would change the conclusion

- **`write_verified: true` and a later `getCurrentTempo` of `140000`:** the write
  works. The conclusion changes from "unverified" to "possible", and the remaining
  work is choosing the flag word, the range and the error handling.
- **`write_verified: false` with `tempo_after == tempo_before` for every candidate
  flag word:** tempo is not writable through the scripting API on build 5406. That
  belongs next to "Loading VST/AU plugins" in ROADMAP.md's "Not possible" section.
- **`changed: true` with `write_verified: false` at a value near the requested
  one:** the tempo event quantises. The tool would need the quantum, and the
  read-back comparison would become a tolerance rather than an equality.
- **`process_rec_result` equal to `REC_InvalidID` (`MaxInt`, 2147483647):** the id
  is wrong for this build, so the arithmetic in `ranges.py` and
  `global_properties.py` does not describe the live event map. The next step would
  be the FL manual's event table or discovery through `device.getLinkedValue`.
- **`write_verified: true` with `restore_verified: false`:** the restore path is
  unreliable. The probe must not be run again, by anyone, until that is fixed,
  because it leaves the project changed.
- **A crash or a hung FL during a run:** the stub's warning about invalid values is
  live, the probe's range check needs tightening to the measured range, and this
  spike's status changes from "open" to "do not attempt".
- **A second measurement on another FL version that disagrees:** the flag word is
  build specific, and a tool needs a version gate before it ships.

## Artefacts

- `fl_controller/device_FLStudioMCP.py`: the `system.tempoProbe` action
  (`handle_system_tempo_probe`, with `TEMPO_REC_EVENT`, `TEMPO_WRITE_FLAGS` and
  `REC_FLAG_NAMES` above it). It is a research instrument, and no server tool
  calls it.
- `tests/test_tempo.py`: 20 tests covering the report shape and the refusals. They
  do not assert that a tempo write works, and the module docstring says so.
- `tests/fakes/modules/general.py`: `processRECEvent` records every call and moves
  the tempo only when `project.tempo_write_works` is set, which models one
  plausible FL without claiming anything about the real one.
- `tests/fakes/project.py`: the `tempo_write_works` flag, default false.

ROADMAP.md's T1 entry needs a follow-up edit once the measurement lands, and this
document is the input to that edit. Until then the entry stays open.
