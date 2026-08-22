# Local Voice Bridge

Experimental sidecar for running the Reachy Mini conversation app against a local LLM server without modifying
the app.

The app already knows how to connect to an OpenAI-compatible realtime websocket at `HF_REALTIME_WS_URL`. This
bridge provides that websocket and forwards language-model turns to LM Studio.

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

Your LM Studio server may list ASR/TTS-looking models, but the bridge does not assume LM Studio can serve OpenAI
audio endpoints. STT/TTS stay as explicit adapters so this sidecar remains independent of any one local audio
stack.

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

The bridge automatically loads `local_voice_bridge/.env` first. Start from `config.example.env`; your local
`.env` can hold machine-specific command paths.

## Configure STT

Set `LOCAL_BRIDGE_STT_COMMAND` to a command that receives a WAV file path and prints the transcript to stdout. Use `{wav}` as the placeholder.

Recommended local STT path:

```powershell
cd local_voice_bridge
python -m pip install -r requirements-stt.txt
$env:LOCAL_BRIDGE_STT_MODEL = "small.en"
$env:LOCAL_BRIDGE_STT_DEVICE = "auto"
$env:LOCAL_BRIDGE_STT_LANGUAGE = "en"
$env:LOCAL_BRIDGE_STT_BEAM_SIZE = "5"
$env:LOCAL_BRIDGE_STT_COMMAND = "python stt_faster_whisper.py --audio `"{wav}`""
```

For better recognition of local project vocabulary, optionally set:

```powershell
$env:LOCAL_BRIDGE_STT_HOTWORDS = "Reachy Mini Eric chassis eyes ESP32 Piper LM Studio"
$env:LOCAL_BRIDGE_STT_INITIAL_PROMPT = "Reachy Mini robot conversation about Eric, chassis, eyes, ESP32, Piper, and LM Studio."
```

`base.en` is faster but noticeably weaker. `small.en` is a better default for conversation; `medium.en` can be tried if latency is still acceptable.

Generic command shape:

```powershell
$env:LOCAL_BRIDGE_STT_COMMAND = "python transcribe.py --audio `"{wav}`""
```

## Configure TTS

This setup can use Piper directly:

```powershell
$env:LOCAL_BRIDGE_TTS_PROVIDER = "piper"
$env:LOCAL_BRIDGE_PIPER_EXE = "local_voice_bridge\piper\piper\piper.exe"
$env:LOCAL_BRIDGE_PIPER_MODEL = "local_voice_bridge\piper\voices\en_US-lessac-high.onnx"
```

Your local `.env` can point to any downloaded Piper voice.

Kokoro is also supported as a local neural TTS provider:

```powershell
python -m pip install -r local_voice_bridge\requirements-tts-kokoro.txt
New-Item -ItemType Directory -Force local_voice_bridge\kokoro
Invoke-WebRequest -Uri "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx" -OutFile "local_voice_bridge\kokoro\kokoro-v1.0.onnx"
Invoke-WebRequest -Uri "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin" -OutFile "local_voice_bridge\kokoro\voices-v1.0.bin"
$env:LOCAL_BRIDGE_TTS_PROVIDER = "kokoro"
$env:LOCAL_BRIDGE_KOKORO_VOICE = "am_eric"
```

The Kokoro voices are bundled in `voices-v1.0.bin`; switch voices by changing `LOCAL_BRIDGE_KOKORO_VOICE`.
Good first picks: `am_eric`, `am_liam`, `am_michael`, `af_sarah`, `af_bella`, `bf_emma`, `bf_alice`,
`bm_daniel`, and `bm_george`.

### Qwen3-TTS Notes

Qwen3-TTS is not wired in yet, but the bridge is shaped for it: add a `qwen3tts` provider next to Piper and Kokoro,
then return normal WAV/PCM through the existing `_read_wav_as_16khz_mono_pcm` path.

What we learned:

- LM Studio listing a Qwen3-TTS model is not enough; the bridge should not assume LM Studio serves TTS audio endpoints.
- The installed `Serveurperso/Qwen3-TTS-GGUF/qwen-tokenizer-12hz-Q8_0.gguf` is only the tokenizer/vocoder side.
- Qwen3-TTS GGUF needs two GGUFs loaded together: `qwen-talker-{size}-{mode}-{variant}.gguf` plus
  `qwen-tokenizer-12hz-{variant}.gguf`.
- Start with `qwen-talker-0.6b-base-Q8_0.gguf` or `Q4_K_M` before trying the 1.7B models.
- Prefer a hot local server first, such as `faster-qwen3-tts` server/OpenAI-compatible `/v1/audio/speech`, instead of
  spawning the model once per utterance.
- A likely first bridge config would be:

```env
LOCAL_BRIDGE_TTS_PROVIDER=qwen3tts
LOCAL_BRIDGE_QWEN_TTS_BACKEND=server
LOCAL_BRIDGE_QWEN_TTS_URL=http://127.0.0.1:8000/v1/audio/speech
LOCAL_BRIDGE_QWEN_TTS_MODEL=Qwen/Qwen3-TTS-12Hz-0.6B-Base
LOCAL_BRIDGE_QWEN_TTS_LANGUAGE=English
LOCAL_BRIDGE_QWEN_TTS_SPEAKER=aiden
```

Expected effort: 1-2 hours for a smoke test, 3-5 hours for a bridge provider that calls a hot local HTTP server, and
1-2 days for a polished native in-process provider if Windows/CUDA dependencies need taming.

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

No additional app code changes are required.
