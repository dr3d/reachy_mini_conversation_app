"""Command-line STT adapter for the local voice bridge using faster-whisper."""

from __future__ import annotations
import os
import logging
import argparse
from pathlib import Path

from faster_whisper import WhisperModel


def main() -> None:
    """Transcribe one WAV file and print the transcript to stdout."""
    parser = argparse.ArgumentParser(description="Transcribe a WAV file for local_voice_bridge.")
    parser.add_argument("--audio", required=True, help="Path to the input WAV file.")
    parser.add_argument(
        "--model",
        default=os.getenv("LOCAL_BRIDGE_STT_MODEL", "base.en"),
        help="faster-whisper model name or local model path.",
    )
    parser.add_argument(
        "--device",
        default=os.getenv("LOCAL_BRIDGE_STT_DEVICE", "auto"),
        choices=("auto", "cpu", "cuda"),
        help="Inference device.",
    )
    parser.add_argument(
        "--compute-type",
        default=os.getenv("LOCAL_BRIDGE_STT_COMPUTE_TYPE", "default"),
        help="faster-whisper compute type, such as int8, float16, or default.",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.is_file():
        raise FileNotFoundError(audio_path)

    logging.basicConfig(level=logging.WARNING)
    model_kwargs = {"device": args.device}
    if args.compute_type != "default":
        model_kwargs["compute_type"] = args.compute_type

    model = WhisperModel(args.model, **model_kwargs)
    segments, _ = model.transcribe(str(audio_path), vad_filter=True, beam_size=1)
    transcript = " ".join(segment.text.strip() for segment in segments).strip()
    print(transcript)


if __name__ == "__main__":
    main()
