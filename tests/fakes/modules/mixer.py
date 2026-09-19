"""Fake mixer module.

mixer.getTrackVolume takes a mode: 0 returns 0.0 to 1.0, 1 returns decibels. The
decibel conversion here is monotonic but is not FL's curve, which the stubs do not
document and which has not been measured. Tests use it to tell a value from
another value, never to predict a decibel reading.

Per-track EQ has seven bands in FL, which is what getEqBandCount reports.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject, clamp

# From the stubs: getTrackVolume modes.
VOLUME_LINEAR = 0
VOLUME_DB = 1

# From the stubs: mixer.getTrackPeaks modes.
PEAK_L = 0
PEAK_R = 1
PEAK_LR = 2

# Measured on live FL Studio 2026, build 5406: a mixer insert EQ reports three
# bands, not the seven a naive reading of "multi-band EQ" would suggest. The
# handler reads this from FL rather than assuming either number.
EQ_BAND_COUNT = 3


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("mixer")

    def trackCount() -> int:
        return len(project.tracks)

    def trackNumber() -> int:
        return project.selected_mixer_track

    def getTrackName(index: int) -> str:
        return project.track(index).name

    def setTrackName(index: int, name: str) -> None:
        project.track(index).name = name
        project.record_undo("set track name")

    def getTrackColor(index: int) -> int:
        return project.track(index).color

    def setTrackColor(index: int, color: int) -> None:
        project.track(index).color = int(color)
        project.record_undo("set track color")

    def getTrackVolume(index: int, mode: int = VOLUME_LINEAR) -> float:
        track = project.track(index)
        if mode == VOLUME_DB:
            return track.volume_db()
        return track.volume

    def setTrackVolume(index: int, volume: float, pickupMode: int = 0) -> None:
        project.track(index).volume = clamp(volume, 0.0, 1.0)
        project.record_undo("set track volume")

    def getTrackPan(index: int) -> float:
        return project.track(index).pan

    def setTrackPan(index: int, pan: float, pickupMode: int = 0) -> None:
        project.track(index).pan = clamp(pan, -1.0, 1.0)
        project.record_undo("set track pan")

    def getTrackStereoSep(index: int) -> float:
        return project.track(index).stereo_sep

    def setTrackStereoSep(index: int, separation: float, pickupMode: int = 0) -> None:
        project.track(index).stereo_sep = clamp(separation, -1.0, 1.0)

    def isTrackMuted(index: int) -> bool:
        return project.track(index).muted

    def muteTrack(index: int, value: int = -1) -> None:
        track = project.track(index)
        if value == -1:
            track.muted = not track.muted
        else:
            track.muted = bool(value)

    def isTrackSolo(index: int) -> bool:
        return project.track(index).solo

    def soloTrack(index: int, value: int = -1, mode: int = -1) -> None:
        track = project.track(index)
        if value == -1:
            track.solo = not track.solo
        else:
            track.solo = bool(value)

    def isTrackArmed(index: int) -> bool:
        return project.track(index).armed

    def armTrack(index: int) -> None:
        track = project.track(index)
        track.armed = not track.armed

    def getCurrentTempo(asInt: bool = False):
        """Thousandths of a BPM. Live FL Studio returned 130000 at 130 BPM."""
        if asInt:
            return project.tempo
        return float(project.tempo)

    def getTrackPeaks(index: int, mode: int):
        project.track(index)
        return 0.0

    def getLastPeakVol(section: int) -> float:
        return 0.0

    def getEqBandCount() -> int:
        return EQ_BAND_COUNT

    def _band(index: int, band: int) -> int:
        project.track(index)
        if not 0 <= band < EQ_BAND_COUNT:
            raise IndexError(f"EQ band {band} out of range")
        return band

    def getEqGain(index: int, band: int, mode: int = 0) -> float:
        _band(index, band)
        return project.track(index).eq_gains[band]

    def setEqGain(index: int, band: int, value: float) -> None:
        _band(index, band)
        project.track(index).eq_gains[band] = value

    def getEqFrequency(index: int, band: int, mode: int = 0) -> float:
        _band(index, band)
        return project.track(index).eq_freqs[band]

    def setEqFrequency(index: int, band: int, value: float) -> None:
        _band(index, band)
        project.track(index).eq_freqs[band] = clamp(value, 0.0, 1.0)

    def getEqBandwidth(index: int, band: int) -> float:
        _band(index, band)
        return project.track(index).eq_bandwidths[band]

    def setEqBandwidth(index: int, band: int, value: float) -> None:
        _band(index, band)
        project.track(index).eq_bandwidths[band] = clamp(value, 0.0, 1.0)

    def setRouteTo(index: int, destIndex: int, value: bool, returnToZero: bool = False) -> None:
        project.track(index)
        routes = project.track(index).routes
        if value:
            routes.setdefault(destIndex, 1.0)
        else:
            routes.pop(destIndex, None)

    def getRouteSendActive(index: int, destIndex: int) -> bool:
        return destIndex in project.track(index).routes

    def setRouteToLevel(index: int, destIndex: int, level: float) -> None:
        project.track(index).routes[destIndex] = clamp(level, 0.0, 1.0)

    def getRouteToLevel(index: int, destIndex: int) -> float:
        return project.track(index).routes.get(destIndex, 0.0)

    def linkChannelToTrack(index: int, trackIndex: int, updateGlobal: bool = False) -> None:
        project.channel(index).target_fx_track = trackIndex

    def linkTrackToChannel(mode: int) -> None:
        pass

    def getSongStepPos() -> int:
        return 0

    def getRecPPS() -> int:
        return project.ppq * 4

    def selectTrack(index: int) -> None:
        project.track(index)
        project.selected_mixer_track = index

    module.trackCount = trackCount
    module.trackNumber = trackNumber
    module.getTrackName = getTrackName
    module.setTrackName = setTrackName
    module.getTrackColor = getTrackColor
    module.setTrackColor = setTrackColor
    module.getTrackVolume = getTrackVolume
    module.setTrackVolume = setTrackVolume
    module.getTrackPan = getTrackPan
    module.setTrackPan = setTrackPan
    module.getTrackStereoSep = getTrackStereoSep
    module.setTrackStereoSep = setTrackStereoSep
    module.isTrackMuted = isTrackMuted
    module.muteTrack = muteTrack
    module.isTrackSolo = isTrackSolo
    module.soloTrack = soloTrack
    module.isTrackArmed = isTrackArmed
    module.armTrack = armTrack
    module.getCurrentTempo = getCurrentTempo
    module.getTrackPeaks = getTrackPeaks
    module.getLastPeakVol = getLastPeakVol
    module.getEqBandCount = getEqBandCount
    module.getEqGain = getEqGain
    module.setEqGain = setEqGain
    module.getEqFrequency = getEqFrequency
    module.setEqFrequency = setEqFrequency
    module.getEqBandwidth = getEqBandwidth
    module.setEqBandwidth = setEqBandwidth
    module.setRouteTo = setRouteTo
    module.getRouteSendActive = getRouteSendActive
    module.setRouteToLevel = setRouteToLevel
    module.getRouteToLevel = getRouteToLevel
    module.linkChannelToTrack = linkChannelToTrack
    module.linkTrackToChannel = linkTrackToChannel
    module.getSongStepPos = getSongStepPos
    module.getRecPPS = getRecPPS
    module.selectTrack = selectTrack

    module.VOLUME_LINEAR = VOLUME_LINEAR
    module.VOLUME_DB = VOLUME_DB
    module.PEAK_L = PEAK_L
    module.PEAK_R = PEAK_R
    module.PEAK_LR = PEAK_LR
    return module
