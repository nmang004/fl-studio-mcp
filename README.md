# FL Studio MCP Server

An MCP (Model Context Protocol) server that enables AI assistants to control FL Studio through MIDI communication and Piano Roll scripts.

### Quick Demo
dont mind the scuffed audio, i had to clip with my mic bc apple wouldnt let me record desktop audio lol

https://github.com/user-attachments/assets/d4fc668f-9fe5-4ab4-9f18-76cd661029c6

### Original Audio
If you wanted to hear the better audio

https://github.com/user-attachments/assets/c2b1a5e7-1640-41fa-82bc-18ca7cbae9e8

## Features

### Transport Control

- Play, pause, stop playback
- Toggle recording
- Set playback position
- Get song length and position
- Control loop mode (pattern/song)
- Adjust playback speed
- Read the project tempo, which FL reports in thousandths of a BPM, so a 130 BPM project reads 130000 (`fl_get_version`)

### Mixer Control

- Get/set track volume and pan
- Mute/solo tracks
- Arm tracks for recording
- Set track names and colors
- Stereo separation control
- Read and write every EQ band of a track in one call

### Channel Rack Control

- List all channels
- Get/set channel properties (volume, pan, name, color)
- Mute/solo channels
- Route channels to mixer tracks
- Trigger MIDI notes in real-time
- Step sequencer control (get/set grid bits)

### Pattern Control

- List every pattern with its name, color, length and whether it is current
- Rename, recolor, select or clone a pattern
- Create a new empty pattern and make it current

### Plugin Control

- List plugin parameters
- Get/set parameter values
- Navigate presets (next/previous)
- Query plugin info

### Piano Roll Control

- **Add notes** to a named channel's piano roll with precise timing
- **Add chords** with a single command
- **Delete specific notes** by MIDI number and time
- **Clear all notes** from the piano roll
- **Read piano roll state** to see all existing notes, refreshed from FL Studio
- **Verify a write** by reading the notes back, rather than trusting the script's own report
- Auto-triggering via keystroke (Cmd+Opt+Y on macOS, Ctrl+Alt+Y on Windows)

### Undo and Batching

- Run several commands as one edit, stopping at the first failure
- Undo one or more steps
- Check how deep the undo history is before or after an edit

## Limitations And Corrections

### Cannot Load Plugins

The FL Studio scripting API does **not** support loading new VST/AU plugins. You can only control parameters of plugins that are already loaded in your project.

### Patterns Can Be Created

There is no single API function that creates a pattern outright.
`patterns.findFirstNextEmptyPat()` exists in FL's official scripting API stubs,
and selecting the next empty pattern slot and writing into it is pattern creation
in practice. The claim this README used to make, that patterns cannot be created,
was overstated. The server now has `fl_create_pattern`, which selects the next
empty pattern, reuses it when it is already empty, and makes it current so the
next write lands where you meant it to.

### Cannot Place Clips In The Playlist

The `playlist` module has no add, insert or create function. Markers and live
clips in performance mode are the ceiling, so building a full arrangement
programmatically is out. Confirmed against the stubs, and enforced by a test that
fails if the fake `playlist` module ever grows such a function.

The parts of the playlist that do exist are covered: `fl_get_playlist_tracks`,
`fl_set_playlist_track`, `fl_get_markers` and `fl_add_marker` handle track names,
mute and solo state, and arrangement markers.

### Tempo Is Readable, Writing It Is Not Solved

`mixer.getCurrentTempo()` reads the project tempo, and it returns thousandths of
a BPM: measured live, a 130 BPM project reports 130000.

Writing tempo is still under investigation. There is no dedicated tempo setter in
the API. `general.processRECEvent` with `midi.REC_Tempo` is the only path, and
that function's own stub advises trying other API functions first, because that
part of the API is incomplete, poorly documented and full of hidden bugs. There
is no tempo write tool yet, and this README does not claim one.

### The API Stubs Are Incomplete

FL's official scripting API stubs contain entries marked "HELP WANTED" and
parameters documented as "???", so a function existing is not proof that it
works. Where the server can read a value from FL Studio rather than assume it, it
does: the EQ band count is read from `mixer.getEqBandCount()` instead of being
hardcoded, and live FL Studio 2026 reports three bands for an insert.

## Requirements

- **FL Studio 20.7+** (MIDI Controller Scripting API)
- **Python 3.10+**
- **macOS** or **Windows**
  - macOS: nothing extra, the server creates its own virtual MIDI port
  - Windows: [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html), because Windows has no virtual MIDI API

## Which AI Clients Work With This?

This is a standard [MCP](https://modelcontextprotocol.io) server that talks to clients over stdio, and it isn't hardcoded to any one AI vendor. In principle, **any MCP-compatible client can connect**: Claude Desktop, Claude Code, Cursor, Windsurf, Gemini CLI/Gemini's MCP support, OpenAI's Codex CLI/Agents SDK MCP support, etc.

**What's actually tested and auto-configured:** only **Claude Desktop** and **Claude Code**, via `scripts/install_mcp_for_claude.sh` (macOS/Linux) and `scripts/install_mcp_for_claude.ps1` (Windows). Other clients (Gemini, OpenAI-based tools, etc.) are not tested against this server and have no installer support; you'd need to manually add an equivalent MCP server entry to that client's own config, pointing at:

```json
{
  "command": "uv",
  "args": ["run", "--directory", "/path/to/fl-studio-mcp", "fl-studio-mcp"]
}
```

(adjust `/path/to/fl-studio-mcp` to your local clone). If you try this with a non-Claude client, please open an issue with what worked/didn't. The protocol should support it, but it hasn't been verified here.

## Quick Installation

The easiest way to install is using the provided setup script for your platform.

### macOS / Linux

```bash
# Clone the repository
git clone https://github.com/karl-andres/fl-studio-mcp.git
cd fl-studio-mcp

# Run the one-command installer
./install.sh
```

### Windows

```powershell
# Clone the repository
git clone https://github.com/karl-andres/fl-studio-mcp.git
cd fl-studio-mcp

# Allow running local scripts for this user (one-time)
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force

# Run the one-command installer
.\install.ps1
```

`install.ps1` is the Windows counterpart to `install.sh`: same steps, PowerShell instead of bash, and it installs Python 3.12 specifically (required for prebuilt `python-rtmidi` wheels on Windows).

Both installers will:

1. Install [uv](https://github.com/astral-sh/uv) if not present
2. Install Python dependencies
3. Guide you through the MIDI setup: nothing on macOS, where the server creates its own virtual port, and a loopMIDI port on Windows
4. Install the FL Studio MIDI controller script
5. Install the Piano Roll script (ComposeWithLLM)
6. Configure Claude Desktop or Claude Code automatically (`scripts/install_mcp_for_claude.sh` / `scripts/install_mcp_for_claude.ps1`)

> **Windows piano-roll auto-trigger note:** the Piano Roll script is launched by sending FL Studio a keystroke (`Ctrl+Alt+Y`). On Windows this requires briefly foregrounding the FL Studio window, so **FL Studio will pop to the front for a moment** each time a tool like `fl_send_notes` runs. This is expected. See [Piano Roll script not triggering](#piano-roll-script-not-triggering) if it doesn't fire at all.

## Manual Installation

### 1. Install Python Dependencies

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

### 2. Virtual MIDI Ports

#### macOS

Nothing to do. The server creates its own virtual MIDI port named **FL Studio
MCP** when it starts, and FL Studio sees it as an ordinary MIDI input. The IAC
Driver is not needed and nothing here asks you to enable it. If an IAC port is
already present, the server will use it rather than create a second port;
otherwise it creates its own.

A virtual port exists only while the process that created it is running, and only
that process can send to it. That is why the server owns the port rather than
looking for one: it has to be the sender.

#### Windows

Windows has no virtual MIDI API, so you need a loopback driver:

1. Download and install [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html)
2. Create a port, and name it **FL Studio MCP** so the server finds it
3. Keep loopMIDI running while using FL Studio

Set `FL_STUDIO_MCP_MIDI_PORT` to match a differently named port. The server will
not fall back to the first available port, because on a typical machine that is
real hardware and the trigger note would be sent to your keyboard or interface.

### 3. Install FL Studio Scripts

Copy the controller script to FL Studio's Hardware folder:

```bash
# macOS
mkdir -p ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP
cp fl_controller/device_FLStudioMCP.py ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/

# Windows
mkdir "%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudioMCP"
copy fl_controller\device_FLStudioMCP.py "%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudioMCP\"
```

Copy the Piano Roll script:

```bash
# macOS
cp scripts/ComposeWithLLM.pyscript ~/Documents/Image-Line/FL\ Studio/Settings/Piano\ roll\ scripts/

# Windows
copy scripts\ComposeWithLLM.pyscript "%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Piano roll scripts\"
```

Later edits to either script only need the file copied again: the controller
script hot-reloads, so FL Studio does not have to restart. The first install does.

### 4. Configure FL Studio

1. **Restart FL Studio** (if it's running)
2. Go to **Options > MIDI Settings**
3. Under **Input**, find **FL Studio MCP** (macOS) or your loopMIDI port (Windows)
4. Set the **Controller type** to **FL Studio MCP Controller**
5. Enable the port (click to highlight it)

### 5. Configure Claude (or another MCP client)

Add to your Claude Desktop config:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "fl-studio": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/fl-studio-mcp", "fl-studio-mcp"]
    }
  }
}
```

Or for Claude Code, add to your MCP settings (`~/.claude.json`, or run `claude mcp add`).

Using a different MCP-compatible client (Gemini, an OpenAI-based tool, Cursor, etc.)? The same `command`/`args` pair above is all any MCP host needs. Add it to that client's own MCP config in whatever format it expects. See [Which AI Clients Work With This?](#which-ai-clients-work-with-this) for what's actually been tested.

## Usage

### Running the Server Manually

```bash
# Using uv
uv run fl-studio-mcp

# Or after installation
fl-studio-mcp
```

### Piano Roll Workflow

1. Open FL Studio and select a channel
2. Open the Piano Roll (F7 or double-click the channel)
3. The first time, manually run the script: **Tools > Scripting > ComposeWithLLM**
4. After that, the MCP tools will auto-trigger the script

## Available Tools

### Connection

| Tool | Description |
|------|-------------|
| `fl_connect` | Connect/reconnect to FL Studio |
| `fl_connection_status` | Get connection status |
| `fl_get_version` | Report the FL Studio version, the scripting API version and the project tempo |

### Transport

| Tool | Description |
|------|-------------|
| `fl_play` | Start/pause playback |
| `fl_stop` | Stop playback |
| `fl_record` | Toggle recording |
| `fl_get_transport_status` | Get playback/recording state |
| `fl_set_song_position` | Set playback position |
| `fl_get_song_length` | Get song duration |
| `fl_set_loop_mode` | Switch between pattern/song mode |
| `fl_set_playback_speed` | Adjust playback speed (0.25x-4x) |

### Mixer

| Tool | Description |
|------|-------------|
| `fl_get_mixer_track_count` | Get number of mixer tracks |
| `fl_get_mixer_track_info` | Get track details |
| `fl_get_all_mixer_tracks` | List all tracks |
| `fl_set_track_volume` | Set track volume |
| `fl_set_track_pan` | Set track pan |
| `fl_mute_track` | Mute/unmute track |
| `fl_solo_track` | Solo/unsolo track |
| `fl_arm_track` | Arm track for recording |
| `fl_set_track_name` | Rename track |
| `fl_set_track_color` | Set track color |
| `fl_set_stereo_separation` | Adjust stereo width |

### Mixer EQ

| Tool | Description |
|------|-------------|
| `fl_get_eq` | Read every EQ band of a mixer track at once |
| `fl_set_eq` | Set several EQ bands and report the result read back |

### Channels

| Tool | Description |
|------|-------------|
| `fl_get_channel_count` | Get number of channels |
| `fl_get_channel_info` | Get channel details |
| `fl_get_all_channels` | List all channels |
| `fl_get_selected_channel` | Get selected channel |
| `fl_select_channel` | Select/deselect channel |
| `fl_select_one_channel` | Select channel exclusively |
| `fl_trigger_note` | Trigger MIDI note (real-time) |
| `fl_set_channel_volume` | Set channel volume |
| `fl_set_channel_pan` | Set channel pan |
| `fl_mute_channel` | Mute/unmute channel |
| `fl_solo_channel` | Solo/unsolo channel |
| `fl_set_channel_name` | Rename channel |
| `fl_set_channel_color` | Set channel color |
| `fl_route_channel_to_mixer` | Route to mixer track |
| `fl_get_grid_bit` | Get step sequencer step |
| `fl_set_grid_bit` | Set step sequencer step |
| `fl_get_step_sequence` | Get full pattern |
| `fl_set_step_sequence` | Set full pattern |

### Patterns

| Tool | Description |
|------|-------------|
| `fl_get_patterns` | List every pattern with its name, color, length and which one is current |
| `fl_set_pattern` | Rename, recolor, select or clone a pattern |
| `fl_create_pattern` | Make a new empty pattern current |

### Plugins

| Tool | Description |
|------|-------------|
| `fl_is_plugin_valid` | Check if plugin exists |
| `fl_get_plugin_name` | Get plugin name |
| `fl_get_plugin_param_count` | Get parameter count |
| `fl_get_plugin_params` | List all parameters |
| `fl_get_plugin_param_value` | Get parameter value |
| `fl_set_plugin_param_value` | Set parameter value |
| `fl_get_preset_count` | Get preset count |
| `fl_next_preset` | Next preset |
| `fl_prev_preset` | Previous preset |
| `fl_get_plugin_color` | Get plugin color |

### Piano Roll

Every piano roll tool that reads or writes notes takes a `channel` argument. The
piano roll window shows whichever channel is selected in the Channel Rack, so
without naming a channel the notes land wherever focus happens to be. When
targeting a channel fails, the tool refuses rather than running the script
against the wrong piano roll.

| Tool | Description |
|------|-------------|
| `fl_send_notes` | Write notes into a named channel's piano roll, optionally verifying them by read-back |
| `fl_send_chord` | Write a chord into a named channel's piano roll |
| `fl_delete_notes` | Delete specific notes |
| `fl_clear_piano_roll` | Clear all notes |
| `fl_get_piano_roll_state` | Read the notes currently in a piano roll |
| `fl_get_piano_roll_info` | Report the piano roll integration status |

### Undo and Batching

| Tool | Description |
|------|-------------|
| `fl_batch` | Run several commands as one edit that stops at the first failure |
| `fl_undo` | Undo one or more steps |
| `fl_undo_history` | Report how deep the undo history is |

## Example Workflows

### Adjusting a Mix

```text
"Set the volume of mixer track 1 to 80% and pan it slightly left"
```

### Creating a Drum Pattern

```text
"Create a basic kick pattern on channel 0 with kicks on steps 0, 4, 8, and 12"
```

### Adding a Melody to Piano Roll

```text
"Add a C major arpeggio starting at beat 0: C4, E4, G4, C5 - each note quarter duration"
```

### Adding Chords

```text
"Add a C major chord at beat 0, then F major at beat 2, then G major at beat 4"
```

### Automating Plugin Parameters

```text
"List the parameters of the plugin on channel 0 and set the filter cutoff to 50%"
```

## Troubleshooting

### "Not connected to FL Studio"

1. Ensure FL Studio is running
2. Check that the FL Studio MCP Controller is enabled in MIDI Settings
3. On macOS, give FL Studio a few seconds: it takes 2.0 to 2.3 seconds to bind a
   newly created virtual MIDI port, and commands sent before that are dropped
4. On Windows, verify loopMIDI is running and the port is named **FL Studio MCP**,
   or set `FL_STUDIO_MCP_MIDI_PORT` to match
5. Restart FL Studio after enabling the controller for the first time

### "Timeout waiting for FL Studio response"

1. Make sure FL Studio is in focus
2. Check the Script output window in FL Studio (View > Script output)
3. Verify the controller is receiving MIDI (look for activity in MIDI Settings)

### Piano Roll script not triggering

1. First time: manually run **Tools > Scripting > ComposeWithLLM** in FL Studio
2. On macOS: grant Accessibility permissions when prompted
3. On Windows: the MCP server foregrounds the FL Studio window automatically before sending the hotkey. If FL Studio isn't running or is minimized to the system tray, the trigger can't find it and will fall back to a warning telling you to press the hotkey manually
4. Try pressing Cmd+Opt+Y (macOS) or Ctrl+Alt+Y (Windows) manually to confirm the hotkey itself is bound to the script in FL Studio
5. If you just updated the server code (e.g. pulled a fix to the trigger logic), **fully restart** your MCP client (Claude Desktop/Code); reconnecting the MCP server alone does not respawn the underlying process, so it can keep running stale code

### No MIDI ports available

- **macOS**: this should not happen, because the server creates its own port. If
  it does, another process may already hold a port named "FL Studio MCP". Quit it,
  or set `FL_STUDIO_MCP_VIRTUAL_PORT_NAME` to a different name and enable that
  name in FL Studio's MIDI Settings.
- **Windows**: install and run loopMIDI, and name the port **FL Studio MCP**, or
  set `FL_STUDIO_MCP_MIDI_PORT` to match the name you used.

## Architecture

This MCP server uses a hybrid approach:

```text
┌─────────────────┐     ┌─────────────────────────────────────────┐
│   MCP Client    │────▶│           FastMCP Server                │
│  (Claude, etc)  │     │                                         │
└─────────────────┘     │  ┌─────────────────┐  ┌──────────────┐  │
                        │  │ MIDI + JSON     │  │ Piano Roll   │  │
                        │  │ Tools           │  │ Tools (JSON) │  │
                        │  └────────┬────────┘  └──────┬───────┘  │
                        └───────────┼──────────────────┼──────────┘
                                    │                  │
                               MIDI + JSON        JSON Files +
                                    │              Keystroke
                                    ▼                  ▼
                        ┌─────────────────────────────────────────┐
                        │              FL Studio                   │
                        │  ┌──────────────┐  ┌──────────────────┐ │
                        │  │FLStudioMCP   │  │ Piano Roll Script│ │
                        │  │(MIDI Ctrl)   │  │ (ComposeWithLLM) │ │
                        │  └──────────────┘  └──────────────────┘ │
                        └─────────────────────────────────────────┘
```

### How It Works

1. **Transport, Mixer (including EQ), Channels, Patterns, Plugins, batch and undo**:
   - MCP server writes command to JSON file
   - Sends MIDI trigger note to FL Studio
   - FL Studio controller script reads JSON, executes API, writes response
   - MCP server reads response

2. **Piano Roll**:
   - MCP server writes note requests to JSON file
   - Sends keystroke (Cmd+Opt+Y on macOS, Ctrl+Alt+Y on Windows) to trigger FL Studio script. On Windows, the FL Studio window is foregrounded first so the keystroke actually reaches it
   - Piano Roll script reads JSON and modifies notes

## Development

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended)

### Setup

```bash
# Install all dependencies including dev extras
uv sync --dev

# Or with pip
pip install -e ".[dev]"
```

### Available Commands

| Command | Description |
|---------|-------------|
| `uv run fl-studio-mcp` | Run the MCP server |
| `uv run ruff check .` | Lint the codebase |
| `uv run ruff check --fix .` | Lint and auto-fix |
| `uv run pytest` | Run tests |

### Project Structure

```
fl-studio-mcp/
├── fl_controller/
│   └── device_FLStudioMCP.py    # FL Studio MIDI controller script (runs inside FL Studio)
├── scripts/
│   ├── setup.sh                  # FL Studio script installer
│   ├── install_mcp_for_claude.sh # Claude config installer (macOS/Linux)
│   ├── install_mcp_for_claude.ps1 # Claude config installer (Windows)
│   └── ComposeWithLLM.pyscript   # Piano Roll script (runs inside FL Studio)
├── src/fl_studio_mcp/
│   ├── server.py                # FastMCP server entry point
│   ├── tools/                   # MCP tool implementations
│   │   ├── batch.py
│   │   ├── channels.py
│   │   ├── eq.py
│   │   ├── mixer.py
│   │   ├── patterns.py
│   │   ├── piano_roll.py
│   │   ├── plugins.py
│   │   └── transport.py
│   └── utils/
│       ├── connection.py        # FL Studio connection wrapper
│       ├── fl_trigger.py        # Piano roll keystroke trigger
│       └── midi_connection.py   # MIDI + JSON communication layer
├── install.sh                   # One-command installer (macOS/Linux)
└── install.ps1                  # One-command installer (Windows)
```

## Credits

- [FL Studio API Stubs](https://github.com/IL-Group/FL-Studio-API-Stubs) - API documentation
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server framework
- [mido](https://github.com/mido/mido) - MIDI library for Python
- [calvinw/fl-studio-mcp](https://github.com/calvinw/fl-studio-mcp) - Piano Roll integration approach
- [Image-Line](https://www.image-line.com/) - FL Studio

## License

MIT
