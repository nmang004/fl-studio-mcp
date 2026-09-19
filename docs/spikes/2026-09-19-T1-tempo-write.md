# Spike T1: Tempo write

**Date:** 2026-09-19
**Status:** Resolved, and positive. Both halves are now measured: reading returns
thousandths of a BPM, and writing works through `general.processRECEvent` with
`midi.REC_Tempo` and flags `REC_UpdateValue | REC_UpdateControl`.
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
- **The write was measured on live FL Studio 2026 on 2026-09-19 and it works.**
  See "Measured live" below for the full reply. The value stuck, the read-back
  agreed, and the restore came back to the original tempo.
- What landed first was an instrument rather than a feature: a `system.tempoProbe`
  controller action that performs one write and reports the numbers, plus
  `tests/test_tempo.py` covering its report shape and its refusals.
- A `fl_set_tempo` tool ships on the strength of that measurement. It writes, reads
  back, and reports failure when the value did not move, which is requirement 2
  from the shipping list further down.

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

## Measured live

Measured 2026-09-19 against FL Studio 2026 (Producer Edition v26.1.6, build 5406),
scripting API version 45, on macOS 26, Apple silicon, on the project that was open,
with the owner's explicit agreement. The project tempo was 130 BPM before and 130
BPM after.

One write, with the default flag word, and a restore:

```json
{
  "event_id": 1073741829,
  "requested_bpm": 128.0,
  "requested_value": 128000,
  "tempo_before": 130000,
  "bpm_before": 130.0,
  "flags": 17,
  "flag_names": ["REC_UpdateValue", "REC_UpdateControl"],
  "process_rec_result": 128000,
  "tempo_after": 128000,
  "bpm_after": 128.0,
  "changed": true,
  "write_verified": true,
  "restore": true,
  "tempo_restored": 130000,
  "bpm_restored": 130.0,
  "restore_verified": true
}
```

An independent read afterwards, through `system.getInfo` rather than the probe,
returned `130000`, so the restore is confirmed outside the probe's own report.

What this establishes:

| Question | Answer |
| --- | --- |
| Is `REC_Tempo` accepted at all? | Yes. `processRECEvent` returned `128000` rather than raising or reporting an error. |
| Does the write move the tempo? | Yes, in the same call. `tempo_after` read `128000` immediately, and an independent read agreed. |
| Which flag word works? | `17`, which is `REC_UpdateValue` combined with `REC_UpdateControl`. This is the word the probe defaults to. |
| Is the value stored exactly? | Yes at this value. `128000` in and `128000` out, with no quantisation. |
| Does the write create an undo entry? | Not measured. The probe does not read the undo history, and that remains unknown. |
| Is the permitted value range documented? | No. The stubs give the tempo event no range and warn that an invalid value can crash FL, so any range check comes from the tool rather than from FL. |
| Does the write need a later callback? | Not here, because it worked in the same call. The two step sequence in the commands below remains available if a future build behaves differently. |

Two caveats this measurement does not remove:

- One flag word was tested. The others in the candidate table are untested, and
  there is no reason to prefer them now that `17` is measured to work.
- One build, one platform, one project. `processRECEvent` carries a HELP WANTED
  note for a reason, and a single positive result on build 5406 is exactly that.

### The exact commands to reproduce it

The probe remains the instrument to use, and it takes an optional `flags` override,
so a different flag word can be compared without editing the controller.

```bash
uv run python - <<'SCRIPT'
import json
from fl_studio_mcp.utils.midi_connection import get_connection

conn = get_connection()
conn.connect()
result = conn.send_command("system.tempoProbe", {"bpm": 128.0, "restore": True}, timeout=10.0)
print(json.dumps(result, indent=2))
info = conn.send_command("system.getInfo", {}, timeout=3.0)
print("independent read:", info.get("capabilities", {}).get("getCurrentTempo"))
SCRIPT
```

Expected on a build that behaves like 5406: `write_verified` and `restore_verified`
both true, and the independent read showing the original tempo.

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
