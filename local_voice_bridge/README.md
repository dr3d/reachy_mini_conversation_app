# Local Voice Bridge

Sidecar prototype for running the Reachy Mini conversation app against a local LLM server without modifying the app.

The delivered app already knows how to connect to an OpenAI-compatible realtime websocket at `HF_REALTIME_WS_URL`. This bridge provides that websocket and forwards language-model turns to LM Studio.

## What This Does

- Accepts the subset of OpenAI Realtime websocket events used by this repo.
- Calls LM Studio (`/v1/chat/completions`) for text reasoning.
- Forwards tool calls back to the Reachy app in the event shape it already handles.
- Forwards camera images from the app to LM Studio vision-capable chat models.
- Maps common assistant emoji to the app's existing `play_emotion` tool and strips them from TTS.
- Converts assistant text to PCM audio through a pluggable TTS provider.

## Important Limitation

LM Studio is a good fit for the LLM part, but its documented API is not a full speech-to-speech realtime API. You still need STT and TTS around it:

- STT: mic audio to text
- LLM: text reasoning and tool selection
- TTS: text to robot audio

This bridge includes a command-based STT hook and a command-based TTS hook. On Windows it can use SAPI for TTS automatically. STT must be configured with your preferred transcription command.

Your LM Studio server may list ASR/TTS-looking models, but the bridge does not assume LM Studio can serve OpenAI audio endpoints. In this environment, `/v1/audio/transcriptions` and `/v1/audio/speech` did not behave as usable audio APIs, so STT/TTS stay as explicit adapters.

## Install Bridge Dependencies

From this repo's existing virtual environment you already have these dependencies. For a standalone environment:

```powershell
cd local_voice_bridge
python -m pip install -r requirements.txt
```

## Run

Start LM Studio's server, load your chat model, then:

```powershell
cd local_voice_bridge
python server.py
```

The bridge automatically loads `local_voice_bridge/.env` first. The checked-in example shows the available values; your local `.env` can hold the working Windows command paths.

## Configure STT

Set `LOCAL_BRIDGE_STT_COMMAND` to a command that receives a WAV file path and prints the transcript to stdout. Use `{wav}` as the placeholder.

Recommended local STT path:

```powershell
cd local_voice_bridge
python -m pip install -r requirements-stt.txt
$env:LOCAL_BRIDGE_STT_MODEL = "base.en"
$env:LOCAL_BRIDGE_STT_DEVICE = "auto"
$env:LOCAL_BRIDGE_STT_COMMAND = "python stt_faster_whisper.py --audio `"{wav}`""
```

Generic command shape:

```powershell
$env:LOCAL_BRIDGE_STT_COMMAND = "python transcribe.py --audio `"{wav}`""
```

## Configure TTS

This setup can use Piper directly:

```powershell
$env:LOCAL_BRIDGE_TTS_PROVIDER = "piper"
$env:LOCAL_BRIDGE_PIPER_EXE = "D:\_PROJECTS\reachy_mini_conversation_app\local_voice_bridge\piper\piper\piper.exe"
$env:LOCAL_BRIDGE_PIPER_MODEL = "D:\_PROJECTS\reachy_mini_conversation_app\local_voice_bridge\piper\voices\en_US-lessac-high.onnx"
```

The local `.env` already points to the downloaded `en_US-lessac-high` voice.

On Windows, TTS falls back to SAPI if no provider is configured. For another TTS engine, set `LOCAL_BRIDGE_TTS_COMMAND` to a command that receives text and an output WAV path:

```powershell
$env:LOCAL_BRIDGE_TTS_COMMAND = "python speak.py --text `"{text}`" --out `"{wav}`""
```

On Linux robot hardware, Piper or eSpeak-NG can be wrapped this way.

## Point The Existing App At The Bridge

In the existing app environment:

```env
HF_REALTIME_CONNECTION_MODE=local
HF_REALTIME_WS_URL=ws://127.0.0.1:8765/v1/realtime
```

Then launch the app normally:

```powershell
reachy-mini-conversation-app --ui
```

No delivered app code changes are required.
