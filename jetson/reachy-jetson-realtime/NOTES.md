# Probe Notes

This folder is a Jetson Orin Nano proof project for a future local realtime endpoint. It is not ESP32 firmware and
it is not part of the installed conversation app package.

Run on the Jetson:

```bash
cd /home/scott/Developer/reachy-jetson-realtime
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
pytest -v
python -m jetson_realtime_probe.server
```

Point the conversation app at it for a protocol smoke test:

```env
HF_REALTIME_CONNECTION_MODE=local
HF_REALTIME_WS_URL=ws://jetson.local:8765/v1/realtime
HF_REALTIME_WS_PING_INTERVAL_S=60
HF_REALTIME_WS_PING_TIMEOUT_S=60
```

Live hardware/Ollama checks are skipped unless `JETSON_REALTIME_RUN_LIVE_TESTS=1` is set.

## 2026-08-22

Created the first Jetson-side proof folder at `/home/scott/Developer/reachy-jetson-realtime`.

What passed:

- Python 3.12 venv creation works after installing `python3-venv` and `python3-pip`.
- The `codex` SSH user can write inside this project folder through a scoped ACL.
- Local Ollama is reachable at `127.0.0.1:11434`.
- The default probe model `qwen3:4b` is installed in Ollama.
- A minimal OpenAI/HF-style realtime websocket can run locally and round-trip through Ollama.

Test result:

```text
5 passed, 2 warnings in 68.06s
```

Warnings are from the `websockets` legacy API and are not a blocker for the proof.

What this proves:

- A Jetson-hosted realtime endpoint is not a dead end.
- The app can keep using `HF_REALTIME_CONNECTION_MODE=local` plus `HF_REALTIME_WS_URL` while we swap the backend implementation.
- Ollama-backed LLM routing works on the Nano, although the 4B model is not fast enough to judge final latency yet.

Still missing for the real speech-to-speech bridge:

- Streaming synthesized audio events.
- STT provider selection and benchmarking.
- TTS provider selection and benchmarking.
- Tool-call event support copied from the existing local bridge.
- Swap configuration before heavier local model work.
- A decision on whether to install the full CUDA toolkit/dev stack or avoid it initially with CPU/ONNX/llama.cpp-style paths.

Additional network check:

- Started the probe server on `0.0.0.0:18765`.
- Connected from the Windows development machine to `ws://jetson.local:18765/v1/realtime`.
- Received `session.created`, `session.updated`, `response.output_audio_transcript.done`, `response.output_text.done`, and `response.done`.
- Ollama answered through the websocket path with: `Jetson bridge online`.

This proves the LAN path from the conversation-app machine to the Jetson websocket works.

## PC Ollama Split

Configured the probe to use the RTX 5090 PC Ollama server for LLM inference:

```env
JETSON_REALTIME_OLLAMA_URL=http://192.168.0.150:11434
JETSON_REALTIME_OLLAMA_MODEL=qwen3.6:27b
```

The Jetson can reach `http://192.168.0.150:11434/api/tags` over the LAN and sees the PC model roster, including `qwen3.6:27b`.

The first PC-backed test run proved connectivity but timed out once at 60 seconds on a cold `qwen3.6:27b` request. The probe now uses a 180 second Ollama timeout and caps short probe replies with `JETSON_REALTIME_OLLAMA_NUM_PREDICT=64`.

Qwen thinking mode returned empty `message.content` when the generation cap was small. The probe now sends `think: false` via `JETSON_REALTIME_OLLAMA_THINK=0`, which returned `jetson ready` quickly from `qwen3.6:27b`.

End-to-end split check:

- Windows client connected to `ws://jetson.local:18765/v1/realtime`.
- Jetson endpoint called PC Ollama at `http://192.168.0.150:11434`.
- PC model was `qwen3.6:27b` with `think: false`.
- Response returned: `RTX Jetson bridge online`.
- Warm round trip took about 2.9 seconds from Windows client start to `response.done`.


## Qwen3-TTS Bridge Contract

Added the first Qwen3-TTS-shaped audio layer on the Jetson endpoint. It supports `JETSON_REALTIME_TTS_PROVIDER=qwen3tts_http`, posts an OpenAI-style payload to `/v1/audio/speech`, reads returned WAV bytes, converts them to 16 kHz mono int16 PCM, and emits `response.output_audio.delta` plus `response.output_audio.done` events.

The default remains `JETSON_REALTIME_TTS_PROVIDER=none` until the RTX-side Qwen3-TTS server is running. Tests fake the TTS HTTP response and verify the event contract.

Test result after this step:

```text
8 passed, 3 warnings in 0.81s
```
