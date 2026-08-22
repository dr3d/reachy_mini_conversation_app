---
title: Reachy Mini Conversation App
emoji: 🎤
colorFrom: red
colorTo: blue
sdk: static
pinned: false
short_description: Talk with Reachy Mini!
suggested_storage: large
tags:
 - reachy_mini
 - reachy_mini_python_app
---

# Reachy Mini conversation app

Conversational app for the Reachy Mini robot combining realtime voice, vision, personality-aware tools, and choreographed motion.

![Reachy Mini Dance](docs/assets/reachy_mini_dance.gif)

## Table of contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the app](#running-the-app)
- [Hardware extension sandboxes](#hardware-extension-sandboxes)
- [Firmware sandbox](#firmware-sandbox)
- [ESP32 chassis firmware](#esp32-chassis-firmware)
- [ESP32 camera firmware](#esp32-camera-firmware)
- [Local voice bridge](#local-voice-bridge)
- [ESP32 eyes HTTP API](#esp32-eyes-http-api)
- [LLM tools](#llm-tools-exposed-to-the-assistant)
- [Creating and adding tools](#creating-and-adding-tools)
- [Advanced features](#advanced-features)
- [Contributing](#contributing)
- [License](#license)

## Overview

- Low-latency audio conversation through the Hugging Face realtime backend, using the built-in server or a local endpoint.
- Vision is handled by the realtime backend when the `camera` tool is used.
- Layered motion system queues primary moves (dances, emotions, goto poses, breathing) while blending speech-reactive wobble.
- Async tools integrate motion, camera capture, and MCP Tool Spaces. The optional web UI (`--ui`) manages conversations, personalities, tools, and settings.

## Architecture

The app connects the user, AI services, and robot hardware:

<p align="center">
  <img src="docs/assets/conversation_app_arch.svg" alt="Architecture Diagram" width="600"/>
</p>

## Installation

> [!IMPORTANT]
> Install [Reachy Mini's SDK](https://github.com/pollen-robotics/reachy_mini/) before using this app.<br>
> Windows support is currently experimental and has not been extensively tested. Use with caution.

<details open>
<summary>Using uv (recommended)</summary>

Set up with [uv](https://docs.astral.sh/uv/):

```bash
# macOS (Homebrew)
uv venv --python /opt/homebrew/bin/python3.12 .venv

# Linux / Windows (Python in PATH)
uv venv --python python3.12 .venv

source .venv/bin/activate
uv sync
```

Include dev dependencies:
```bash
uv sync --group dev
```

</details>

> [!NOTE]
> Run `uv sync --frozen` to install the exact dependency set from `uv.lock` without re-resolving versions.

<details>
<summary>Using pip</summary>

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Install dev dependencies:
```bash
pip install -e .[dev]                   # Development tools
```

</details>

## Configuration

The default setup uses the Hugging Face backend and does not require an API key.

Copy `.env.example` to `.env` when you want to point Hugging Face at your own local endpoint.

| Variable | Description |
|----------|-------------|
| `REALTIME_TRANSCRIPTION_LANGUAGE` | Optional input transcription language for the realtime backend. Defaults to `en`; set to a backend-supported code such as `zh` for Chinese. |
| `HF_REALTIME_CONNECTION_MODE` | Hugging Face connection selector: `deployed` uses the built-in Hugging Face server; `local` uses `HF_REALTIME_WS_URL`. Defaults to `deployed`. |
| `HF_REALTIME_WS_URL` | Direct websocket endpoint for your own Hugging Face backend. Accepts either a base URL like `ws://127.0.0.1:8765/v1` or the full websocket URL `ws://127.0.0.1:8765/v1/realtime`. Used when `HF_REALTIME_CONNECTION_MODE=local`. |
| `HF_TOKEN` | Optional token for Hugging Face access. Local endpoints receive only this explicitly configured token. |
| `REACHY_MINI_APP_TIMEOUT_MINUTES` | Minutes of inactivity before Reachy goes to sleep and the app stops. Defaults to `1440` (one day); set to `0` to disable. |
| `REACHY_MINI_EYES_BASE_URL` | Optional HTTP base URL for ESP32/RP5 eye-display control, for example `http://192.168.4.1/` or `http://esp32-eyes.local/`. |
| `REACHY_MINI_EYES_TIMEOUT_S` | HTTP timeout for optional eye-display control. Defaults to `0.8`. |
| `REACHY_MINI_CHASSIS_BASE_URL` | Optional HTTP base URL for ESP32 tracked chassis control, for example `http://esp32-chassis.local/`. |
| `REACHY_MINI_CHASSIS_TIMEOUT_S` | HTTP timeout for optional chassis control. Defaults to `0.8`. |

When `HF_REALTIME_CONNECTION_MODE=deployed`, the realtime model runs through the Hugging Face session proxy, but
hardware tools still execute inside this local app process. Keep `REACHY_MINI_EYES_BASE_URL` and
`REACHY_MINI_CHASSIS_BASE_URL` pointed at LAN-reachable ESP32 devices; those private hardware endpoints are never
called directly from the cloud backend.

### Hugging Face Connection Modes

Use the built-in Hugging Face server through the app-managed Space proxy. This is the default for a new install; set it explicitly only when you want to switch back from a saved local endpoint:

```env
HF_REALTIME_CONNECTION_MODE=deployed
```

Deployed session allocation falls back to cached `hf auth login` credentials and reports the daemon-provided hardware ID when available. Cached credentials and the hardware ID are not sent to local endpoints.

Run your own realtime voice backend using [speech-to-speech](https://github.com/huggingface/speech-to-speech) on the same machine as the conversation app:

```env
HF_REALTIME_CONNECTION_MODE=local
HF_REALTIME_WS_URL=ws://127.0.0.1:8765/v1/realtime
```

Run your own Hugging Face backend on your laptop and connect to it from Reachy Mini Wireless over the same Wi-Fi network:

```env
HF_REALTIME_CONNECTION_MODE=local
HF_REALTIME_WS_URL=ws://<your-laptop-lan-ip>:8765/v1/realtime
```

For that LAN setup, make sure the backend listens on an address reachable from the robot, not only on `127.0.0.1`.

If the backend stays bound to loopback on your laptop, you can forward it into the robot over SSH instead:

```bash
ssh -N -R 8765:127.0.0.1:8765 <robot-user>@<robot-host>
```

Then set this on the robot:

```env
HF_REALTIME_CONNECTION_MODE=local
HF_REALTIME_WS_URL=ws://127.0.0.1:8765/v1/realtime
```

In the web UI's Settings view, the Connection section lets you choose either the built-in server or a local `host:port` target. The UI writes `HF_REALTIME_CONNECTION_MODE` for you, and the local path writes `HF_REALTIME_WS_URL` with a default of `localhost:8765`.

## Running the app

Activate your virtual environment, then launch:

```bash
reachy-mini-conversation-app
```

> [!TIP]
> Make sure the Reachy Mini daemon is running before launching the app. If you see a `TimeoutError`, it means the daemon isn't started. See [Reachy Mini's SDK](https://github.com/pollen-robotics/reachy_mini/) for setup instructions.

The app runs in console mode. Add `--ui` to serve the web interface at http://127.0.0.1:7860/.

### CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--no-camera` | `False` | Run without camera capture. |
| `--ui` | `False` | Serve the web UI at http://127.0.0.1:7860/, in addition to console mode. |
| `--robot-name` | `None` | Optional. Connect to a specific robot by name when running multiple daemons on the same subnet. See [Multiple robots on the same subnet](#advanced-features). |
| `--debug` | `False` | Enable verbose logging for troubleshooting. |

### Examples

```bash
# Audio-only conversation (no camera)
reachy-mini-conversation-app --no-camera

# Launch with the minimal web UI for personality/mic/settings control
reachy-mini-conversation-app --ui
```

## Hardware extension sandboxes

Hardware experiments that are useful with this app but not part of the core Reachy Mini SDK live in contained
subdirectories. Keep these integrations optional, documented through examples, and wired into the app through
stable runtime interfaces so additional devices such as displays, bases, or chassis controllers can evolve
without becoming required dependencies.

## Firmware sandbox

`firmware/esp32-eyes/` contains the ESP32-S3 eye-display firmware imported from the sibling
`reachy_eyes/esp32-eyes` project so it can evolve alongside the conversation app integration work.
This is an experimental hardware sandbox, not required for the default conversation app.

The firmware drives two 240x240 GC9A01 round eye displays plus an optional third mouth display, and renders
gaze, blinks, moods, mouth shapes, sleep, idle beats, and flipped orientation on-device. Build and
upload it with PlatformIO:

```bash
cd firmware/esp32-eyes
pio run
pio run -t upload
pio device monitor
```

The conversation app integrates with eye displays through the HTTP API used by the ESP32/RP5 eye runtimes.
Configure the base URL in `.env`:

```env
REACHY_MINI_EYES_BASE_URL=http://esp32-eyes.local/
```

The app sends eye requests from the machine running the conversation app, even when the realtime model is using
the deployed Hugging Face backend. The ESP32 eyes board only needs to be reachable from that machine on the local
network.

The bundled firmware starts the `ReachyEyes-S3` setup access point only when LAN Wi-Fi credentials are missing or
the LAN join fails. The AP password is `reachyeyes`, and its URL is usually `http://192.168.4.1/`. Open that page
to save LAN Wi-Fi credentials through the built-in test panel, then the board reboots and joins your network. For
compile-time credentials instead, copy `firmware/esp32-eyes/include/reachy_config_private.example.h` to
`firmware/esp32-eyes/include/reachy_config_private.h`, fill in `REACHY_WIFI_SSID` and
`REACHY_WIFI_PASSWORD`, then rebuild and flash. The private header is ignored by git.
After the first USB flash, the same test panel can upload future PlatformIO `firmware.bin` builds over Wi-Fi.

The app uses `GET /state`, `/moods`, `/emotions`, `/beats`, `/styles`, `/mouth_shapes`, and `/mouth_styles`
plus `POST /control`, `/release`, `/mood`, `/emotion`, `/expression`, `/beat`, `/style`, `/mouth`, `/gaze`,
`/blink`, `/wink`, `/sleep`, and `/ota` for high-level cues and firmware updates. The HTTP API is layered onto the same full
mood/gaze/blink/beat/style/mouth implementation as the USB serial commands.
Current ESP32-S3 display pins are defined in `firmware/esp32-eyes/include/reachy_config.h`. The three-display
layout shares GPIO4/5/6/7 for SCLK/MOSI/DC/RST, with GPIO15/16/17 reserved for left-eye/right-eye/mouth CS.
The firmware owns animation timing, so the conversation app sends high-level HTTP intents rather than streaming
frames.

## ESP32 chassis firmware

`firmware/esp32-chassis/` contains the ESP32-S3 tracked chassis firmware imported from the sibling
`reachy_eyes/esp32-chassis` project. It is an optional mobility sandbox for a two-track base, not a required
conversation app dependency.

The chassis firmware owns the motor loop and safety limits on-device: normalized tank/twist commands, duty cap,
slew limiting, watchdog stop, serial commands, UDP drive commands, a browser drive pad, HTTP endpoints, and OTA.
Build and upload it with PlatformIO:

```bash
cd firmware/esp32-chassis
pio run
pio run -t upload
pio device monitor
```

For local Wi-Fi credentials, copy `firmware/esp32-chassis/include/chassis_config_private.example.h` to
`firmware/esp32-chassis/include/chassis_config_private.h`, fill in `CHASSIS_WIFI_SSID` and
`CHASSIS_WIFI_PASSWORD`, then rebuild and flash. The private header is ignored by git. If Wi-Fi is left empty,
the firmware stays serial-only.

The board listens for UDP text commands on port `4210` (`T <left> <right>`, `D <v> <w>`, `S`, `E`, `C`) and
serves a browser pad plus JSON API at `/api/status`, `/api/tank`, `/api/twist`, `/api/stop`, `/api/estop`, and
`/api/clear` when connected to Wi-Fi. Current ESP32-S3 motor pins and safety constants are defined in
`firmware/esp32-chassis/include/chassis_config.h`.

The conversation app can integrate with the chassis through the same HTTP API. Configure the base URL in `.env`:

```env
REACHY_MINI_CHASSIS_BASE_URL=http://esp32-chassis.local/
```

Like the eyes integration, chassis control is a local hardware tool: the deployed Hugging Face backend may decide
to call `set_chassis`, but the HTTP request to the ESP32 board is made by this app on your LAN.

The app then exposes `set_chassis` for explicit drive-base requests. The tool supports status, stop, e-stop,
clear, tank drive, and twist drive. Short-duration drive commands pass a bounded `duration_ms` to the firmware so
the ESP32 owns the timed stop, then the app sends a final stop as a belt-and-suspenders cleanup.

## ESP32 camera firmware

`firmware/esp32-cam/` contains TimerCam firmware imported from the sibling `reachy_eyes/esp32-cam` project. It is
an optional chassis-view camera, not a required conversation app dependency.

The camera firmware serves a compact browser view at `/`, a single JPEG at `/jpg`, plain text status at `/status`,
and an MJPEG stream on port `81` at `/stream`. Build and upload it with PlatformIO:

```bash
cd firmware/esp32-cam
pio run
pio run -t upload
pio device monitor
```

For local Wi-Fi credentials, copy `firmware/esp32-cam/include/cam_config_private.example.h` to
`firmware/esp32-cam/include/cam_config_private.h`, fill in `CAM_WIFI_SSID` and `CAM_WIFI_PASSWORD`, then rebuild
and flash. The private header is ignored by git. If Wi-Fi is left empty or fails to connect, the board starts the
`ReachyCam` access point with URL `http://192.168.4.1/`.

The default hostname is `esp32-cam`, so the camera page is normally:

```text
http://esp32-cam.local/
```

The chassis browser pad's Camera toggle defaults to `esp32-cam.local` and loads:

```text
http://esp32-cam.local:81/stream
```

After the first USB flash, future updates can be sent over Wi-Fi with:

```bash
pio run -e timer-cam-ota -t upload
```

## Local voice bridge

`local_voice_bridge/` is an experimental sidecar for running the app against a local OpenAI-compatible realtime
websocket backed by LM Studio plus explicit STT/TTS adapters. It is useful for local voice experiments, but it is
not required for the default Hugging Face realtime backend. See `local_voice_bridge/README.md` for setup details.

## ESP32 eyes HTTP API

The ESP32 eyes API is intentionally high-level. The app sends semantic cues over HTTP; the firmware owns
rendering, easing, blinking, idle beats, gaze projection, and display orientation. Query these
endpoints on a running board to get the firmware's current value lists:

Open the board root URL in a browser, such as `http://esp32-eyes.local/` or `http://192.168.4.1/`, for a
small built-in test panel. It gives direct controls for eye style, mood/expression, idle beats, mouth
style/shape/talking energy, gaze, blink/wink, sleep, release, and display flip.
Eye style, mouth style, idle mode, and display flip are saved as reusable firmware preferences and restored after
reboot; expressions, gaze, blinks, winks, sleep, and one-off mouth shapes remain temporary.

```bash
EYES_URL=http://esp32-eyes.local
curl "$EYES_URL/state"
curl "$EYES_URL/styles"
curl "$EYES_URL/emotions"
curl "$EYES_URL/moods"
curl "$EYES_URL/mouth_shapes"
curl "$EYES_URL/mouth_styles"
curl "$EYES_URL/beats"
```

The conversation app uses `REACHY_MINI_EYES_BASE_URL` to reach the board and exposes `set_eyes` for direct
face requests. Most normal robot behavior should not require the model to call `set_eyes`: existing
conversation and motion choreography cue the eyes and mouth automatically.

| App event or tool | Face cue |
|-------------------|---------|
| User starts speaking | `emotion=curious`, mouth neutral |
| Assistant starts speaking | `emotion=happy`, mouth talking |
| Assistant finishes / idle release | `release` |
| `play_emotion` | Matching eye emotion, such as `afraid`, `angry`, `sleepy`, `bashful`, or `happy` |
| `dance` | `beat=goofy` |
| `move_head` | Matching normalized gaze direction |
| `sweep_look` | Focused eyes with explicit left-center-right-center gaze sequence |
| `go_to_sleep` | `sleep` |
| `stop_dance` / `stop_emotion` | `release` |

Direct face commands still use the `set_eyes` tool or the HTTP API. Eye holdoffs keep explicit requests and
routine choreography visible briefly so automatic speaking/listening cues do not immediately undo them.

Common HTTP examples:

```bash
EYES_URL=http://esp32-eyes.local

curl -X POST "$EYES_URL/style" \
  -H "Content-Type: application/json" \
  -d '{"name":"robot"}'

curl -X POST "$EYES_URL/expression" \
  -H "Content-Type: application/json" \
  -d '{"name":"suspicious","duration":4}'

curl -X POST "$EYES_URL/control" \
  -H "Content-Type: application/json" \
  -d '{"gaze":{"x":1,"y":0,"duration":0,"move_ms":300}}'

curl -X POST "$EYES_URL/mouth" \
  -H "Content-Type: application/json" \
  -d '{"style":"human","shape":"smirk_right","talking":true,"energy":0.65,"duration":3}'

curl -X POST "$EYES_URL/release" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Canonical renderer styles:

| Style | Basic look |
|-------|------------|
| `friendly` | Default natural iris. |
| `classic` | Classic blue/gray iris. |
| `cartoony` | Larger, brighter cartoon iris. |
| `robot` | Big simple dot/robot eyes. |
| `sinister` | Red slit/cat-like pupil style. |
| `sleepy` | Muted steel-blue sleepy renderer. |

Accepted style aliases include `cartoon -> cartoony`, `dot`/`big_dot`/`row_body -> robot`,
`red`/`slit`/`slits`/`cat_eye -> sinister`, and `steel -> sleepy`. Keep `robot` and `robotic`
distinct: `robot` is a renderer style, while `robotic` is a mood with rigid, quantized motion.

Mouth renderer styles:

| Style | Basic look |
|-------|------------|
| `human` | Oversized blue glowing 790-style lips viewed through the round display; lip corners may sit outside the visible circle. |
| `robot` | Simple cyan bar mouth for debugging or a more synthetic look. |

Mouth shapes:

```text
neutral, smile, smirk_left, smirk_right, open, wide, frown, grimace, sneer, sleep
```

`POST /mouth` accepts `style`, `shape`, `talking`, `energy`, and `duration`. Talking is energy-based in v1:
it varies mouth opening rhythmically during assistant speech rather than doing phoneme lip sync.

Eye moods and emotions:

| Emotion | What to look for |
|---------|------------------|
| `calm` | Neutral open eyes, soft stable gaze. |
| `curious` | Slightly lifted/open, attentive tilt, small lively jitter. |
| `surprised` | Wide open eyes, larger pupils. |
| `suspicious` | Narrowed lids, side-eye/skeptical squint. |
| `afraid` | Wide tense eyes with more jitter/tremble. |
| `angry` | Downward slanted top lids, sharper glare. |
| `sleepy` | Heavy drooping lids, gaze sits lower. |
| `sleep` | Eyes close/blank. |
| `goofy` | Asymmetric playful gaze offsets. |
| `robotic` | Rigid, quantized gaze movement. |
| `wonder` | Wide open, soft amazed look. |
| `glitchy` | Jittery, twitchy offsets. |
| `happy` | Soft smile-like lid curve, gaze lifted slightly. |
| `delighted` | Wide happy eyes, sparkle accents, lively motion. |
| `bashful` | Soft shy lids, gaze drifts downward. |
| `bored` | Heavy flat lids, low-energy gaze. |
| `focused` | Narrower, centered, reduced gaze range. |
| `confused` | Asymmetric lids, uneven puzzled look. |
| `proud` | Slightly narrowed, upward/confident gaze. |
| `mischief` | Narrow sly squint, angled lids. |
| `affection` | Soft open lids, warm rounded shape, slight sparkle. |

`/mood` and `/emotion` both apply longer-lived mood presets. `/expression` applies the same visual vocabulary
as a shorter overlay. `fear`, `frighten`, `frightened`, and `scared` are accepted app aliases for `afraid`.

Idle beats:

```text
slow_smile, affection, inspect, thoughtful, daydream, mischief, confused,
focus_lock, double_take, goofy, drowsy, robot_scan, wary, startle
```

Gaze accepts either normalized app coordinates or full firmware target coordinates. With normalized gaze,
omit `z` and send `x`/`y` in `-1..1`; `x=1` means Reachy's right, `x=-1` means Reachy's left, `y=1` means
down, and `y=-1` means up. The current ESP32 calibration maps full normalized gaze to a strong off-axis
target and renders it with 75 px horizontal travel and 50 px vertical travel. If `z` is included, `x`/`y`/`z`
are treated as raw firmware target coordinates instead of normalized app coordinates.

Other control fields:

| Field or route | Effect |
|----------------|--------|
| `POST /blink` or `/control` with `blink=true` | Trigger blink. |
| `POST /wink` or `/control` with `wink=true` | Trigger wink; optional `eye` can select `left` or `right`. |
| `flip` | Flip display orientation; `"toggle"` is accepted by `/control`. |
| `idle` / `autonomous` | Re-enable or disable autonomous firmware idle behavior. |
| `release` or `POST /release` | Clear app/manual overrides and return to firmware idle behavior. |

## LLM tools exposed to the assistant

The default profile exposes these tools. Use Tools → Tool access to customize any profile.
Every bundled profile enables `head_tracking` by default; users can still disable it per personality.

| Tool | Action | Dependencies |
|------|--------|--------------|
| `dance` | Queue a dance from `reachy_mini_dances_library`. | Core install only. |
| `stop_dance` | Clear queued dances. | Core install only. |
| `play_emotion` | Play a recorded emotion clip via Hugging Face datasets. | Core install only. Uses the default open emotions dataset: [`pollen-robotics/reachy-mini-emotions-library`](https://huggingface.co/datasets/pollen-robotics/reachy-mini-emotions-library). |
| `stop_emotion` | Clear queued emotions. | Core install only. |
| `camera` | Capture the latest camera frame and analyze it with the selected realtime backend. | Core install only. Requires the camera (disable with `--no-camera`). |
| `idle_do_nothing` | Explicitly remain idle during an idle turn. Not intended for normal conversation turns. | Core install only. |
| `move_head` | Queue a head pose change (left/right/up/down/front). | Core install only. |
| `set_eyes` | Control optional ESP32/RP5 face displays through their HTTP API. | Requires `REACHY_MINI_EYES_BASE_URL`. |
| `set_chassis` | Control optional ESP32 tracked chassis through its HTTP API. | Requires `REACHY_MINI_CHASSIS_BASE_URL`. |
| `head_tracking` | Follow the user's face with the head, or stop following. | Core install only. Requires a daemon with the `vision` extra and a camera. |
| `go_to_sleep` | Run Reachy's sleep movement and stop the current app after an explicit user request. | Core install only. |
| `sweep_look` | Sweep Reachy's head left, right, and back to center. | Shared tool, enabled by default in the default profile. |
| `remember` | Save one short, stable fact about the user for future sessions. | Core install only. Stored in the app instance data directory. |
| `forget` | Remove a saved memory fact by matching a short query. | Core install only. |
| `pollen_robotics_reachy_mini_search_tool__search_web` | Search the web and return a short list of results. | Preinstalled MCP Space: `pollen-robotics/reachy-mini-search-tool`. |
| `pollen_robotics_reachy_mini_weather_tool__get_weather` | Report today's weather for a place: current conditions, high and low temperature, and rain chance. | Preinstalled MCP Space: `pollen-robotics/reachy-mini-weather-tool`. |
| `pollen_robotics_reachy_mini_time_tool__get_time` | Report the current time for a timezone or the user's local time, or the difference between two timezones. | Preinstalled MCP Space: `pollen-robotics/reachy-mini-time-tool`. |

> [!NOTE]
> `remember`/`forget` facts are stored in `memory.v1.json` inside the app's instance data directory (`~/.local/share/reachy_mini_conversation_app/` by default, or the instance path used by the desktop launcher). `forget` only removes facts matched by query. To reset all remembered facts, delete this file.

## Creating and adding tools

Tools can run locally as Python code or remotely in an MCP-compatible Hugging Face Space. Keep robot, camera, and local-data operations in local tools. A Space is a better fit for shareable, stateless services such as search and external API lookups.

### Local tools

Create one Python module per tool, with the file name matching the tool's unique `name`. See [`idle_do_nothing.py`](src/reachy_mini_conversation_app/tools/idle_do_nothing.py) for a minimal implementation.

Each tool subclasses `Tool` and defines `name`, a model-facing `description`, an object-shaped JSON Schema in `parameters_schema`, and an async `__call__` method. Use `ToolDependencies` for runtime services, and set `needs_response = False` for actions that should not trigger a spoken follow-up. Catch expected operational failures, log them with the module logger, and return `{"error": "..."}` so the conversation can continue.

Restart the app after adding the module. Use Tools → Tool access to enable it for a personality, or add its name to that profile's `default_tools` in `profile.md`. See [External profiles and tools](#external-profiles-and-tools) for external directories and autoload behavior.

### Hugging Face Space tools

To publish a remote tool, create a Gradio Space, expose its API as MCP with `mcp_server=True`, and give each function clear type hints and docstrings. Verify that `https://<space-subdomain>.hf.space/gradio_api/mcp/schema` lists the expected tools before installing the Space.

Use the maintained [weather](https://huggingface.co/spaces/pollen-robotics/reachy-mini-weather-tool), [time](https://huggingface.co/spaces/pollen-robotics/reachy-mini-time-tool), and [search](https://huggingface.co/spaces/pollen-robotics/reachy-mini-search-tool) Spaces as examples. See Gradio's [MCP server guide](https://www.gradio.app/guides/building-mcp-server-with-gradio) for additional publishing guidance and [Installing Hugging Face Space tools](#installing-hugging-face-space-tools) for this app's installation steps.

## Advanced features

Built-in motion content is published as open Hugging Face datasets:

- Emotions: [`pollen-robotics/reachy-mini-emotions-library`](https://huggingface.co/datasets/pollen-robotics/reachy-mini-emotions-library)
- Dances: [`pollen-robotics/reachy-mini-dances-library`](https://huggingface.co/datasets/pollen-robotics/reachy-mini-dances-library)

<details>
<summary>Custom profiles</summary>

Create custom profiles with dedicated instructions and per-profile tool access.

Select and save a startup profile in the UI. The choice is stored in `startup_settings.json`. Before one is saved, `REACHY_MINI_CUSTOM_PROFILE=<name>` can select `profiles/<name>/`; otherwise the app uses `default`.

Every profile directory contains one strict schema-version-1 `profile.md`. TOML metadata is enclosed by `+++`; the remaining Markdown body is the realtime assistant prompt:

```markdown
+++
schema_version = 1
voice = "Aiden"
greeting = "Greet me warmly in one sentence, in character, and vary the wording each time."
hidden = false
default_tools = [
  "dance",
  "camera",
  "sweep_look",
]
+++

## Identity

You are a concise, friendly robot guide.
```

`schema_version`, `default_tools`, and a non-empty Markdown body are required. `voice`, `greeting`, and `hidden` are optional. Set `hidden = true` to omit a profile from the UI. An empty `default_tools` list is valid and inherits nothing.

`default_tools` is the authored baseline. Tools → Tool access stores overrides in instance-local `profile_toolsets.json` without changing bundled profiles. Restoring defaults removes the override. Active-profile changes reconnect the conversation; other changes apply when selected.

Profile directories are data-only. Python tool implementations belong in `src/reachy_mini_conversation_app/tools/`, or in `REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY` for external tools. Each enabled tool ID must resolve to a shared tool, an external tool, or a tool from an installed Hugging Face Space.

See [Creating and adding tools](#creating-and-adding-tools) for the local tool interface and a maintained example.

To manage personalities in the UI:

With `--ui`, Home lists the available profiles and the built-in default:

- Tap a card to apply that personality and start talking.
- Tap "Manage tools" on a saved personality to open its tool access directly.
- Tap "Custom" to create a personality with a name, instructions, and optional greeting. It inherits the default tools, which can be changed under "Manage tools". Managed instances store it at `user_personalities/<name>/profile.md`; standalone runs use `external_content/user_personalities/<name>/profile.md`.

Switching a personality reloads its prompt and effective tools through a quick backend reconnect. Editing `profile.md` directly requires re-selecting the profile or restarting the app.

</details>

<details>
<summary>Locked profile mode</summary>

To create a locked variant of the app that cannot switch profiles, edit `src/reachy_mini_conversation_app/config.py` and set the `LOCKED_PROFILE` constant to the desired profile name:
```python
LOCKED_PROFILE: str | None = "mars_rover"  # Lock to this profile
```
When set, the app ignores saved startup settings, `REACHY_MINI_CUSTOM_PROFILE`, and UI selection. The UI marks the profile as locked and disables editing.

</details>

<a id="external-profiles-and-tools"></a>

<details>
<summary>External profiles and tools</summary>

You can extend the app with profiles/tools stored outside the repository defaults.

- Core profiles are under `profiles/`.
- Core tools are under `src/reachy_mini_conversation_app/tools/`.

Recommended layout:

```text
external_content/
├── external_profiles/
│   └── my_profile/
│       └── profile.md
├── external_tools/
│   └── my_custom_tool.py
├── user_personalities/
│   └── my_custom_profile/
│       └── profile.md
├── installed_tool_spaces.json
└── profile_toolsets.json
```

Environment variables:

Set these values in your `.env` when you want env-driven external profile/tool selection:

```env
# Optional fallback/manual profile selector:
REACHY_MINI_CUSTOM_PROFILE=my_profile
REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY=./external_content/external_profiles
REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY=./external_content/external_tools
# Optional convenience mode:
# AUTOLOAD_EXTERNAL_TOOLS=1
```

Loading rules:

- Profiles: each directory requires a schema-version-1 `profile.md` with explicit `default_tools`; there is no cross-profile fallback.
- Default mode: enabled IDs must resolve to a shared, external, or installed Tool Space tool.
- Autoload: `AUTOLOAD_EXTERNAL_TOOLS=1` adds every valid `*.py` module from `REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY`.
- Web UI: Tools → Tool access enables external modules per profile; it does not upload or edit Python.
- Separation: profile directories contain data only; external Python belongs in `REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY`.
- Tool names: every loaded class needs a unique `Tool.name`; duplicates fail fast.

</details>

<a id="installing-hugging-face-space-tools"></a>

<details>
<summary>Installing Hugging Face Space tools</summary>

You can install MCP-compatible Hugging Face Spaces as remote tool sources for this app. Private Spaces work too, as long as `HF_TOKEN` is set (or you have run `hf auth login`) for an account that can access them. To publish a new Space, follow [Creating and adding tools](#hugging-face-space-tools).

Tools → Tool Spaces installs or refreshes a global source. Its tools then appear under Tools → Tool access for per-profile selection. Removing a Space removes its tools from every profile. Active-profile changes reconnect the conversation; other changes apply when selected.

The app accepts Hugging Face Spaces exposing the standard `/gradio_api/mcp/` endpoint, not arbitrary MCP URLs. Installation discovers the Space's tools and assigns namespaced local IDs, so do not guess or hard-code those IDs beforehand.

```bash
# install + enable in active profile
reachy-mini-conversation-app tool-spaces add <owner/space-name>

# enable in a specific profile
reachy-mini-conversation-app tool-spaces add <owner/space-name> --profile NAME

# install without enabling
reachy-mini-conversation-app tool-spaces add <owner/space-name> --install-only

# list installed spaces
reachy-mini-conversation-app tool-spaces list

# remove an installed space
reachy-mini-conversation-app tool-spaces remove owner/space-name
```

Bundled Pollen Spaces use static specs and are enabled by the default profile. Custom Spaces are validated through the Hugging Face Hub; HF tokens are sent only to private Spaces. Tool metadata is cached in:

- `installed_tool_spaces.json` in the managed app instance directory
- `external_content/installed_tool_spaces.json` in terminal mode

Startup and profile switching read this cache without discovery or MCP probing. Network access occurs only during install, refresh, or remote tool calls. Per-profile access is stored in `profile_toolsets.json` beside the manifest, or under `external_content/` in terminal mode.

Recommended tags for discoverability on Hugging Face:

- `reachy-mini-tool`
- `mcp`

Tags are advisory; installation still requires successful MCP validation.

> [!NOTE]
> Preinstalled Pollen Spaces can be removed like any other (`tool-spaces remove pollen-robotics/reachy-mini-weather-tool`). To restore access, reinstall the Space and restore or update the relevant profile under "Tool access".

</details>

<details>
<summary>Multiple robots on the same subnet</summary>

If you run multiple Reachy Mini daemons on the same network, use:

```bash
reachy-mini-conversation-app --robot-name <name>
```

`<name>` must match the daemon's `--robot-name` value so the app connects to the correct robot.

</details>

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and [`AGENTS.md`](AGENTS.md) for coding-agent standards.

## License

Apache 2.0
