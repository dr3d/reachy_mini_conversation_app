"""Command-line STT adapter for the local voice bridge using faster-whisper."""

from __future__ import annotations
import os
import logging
import argparse
from pathlib import Path


_DLL_DIRECTORY_HANDLES: list[object] = []


def _add_nvidia_dll_directories() -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return

    for parent in Path(__file__).resolve().parents:
        nvidia_dir = parent / ".venv" / "Lib" / "site-packages" / "nvidia"
        if not nvidia_dir.is_dir():
            continue
        path_entries = []
        for bin_dir in nvidia_dir.glob("*/*bin"):
            if bin_dir.is_dir():
                path_entries.append(str(bin_dir))
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(bin_dir)))
        if path_entries:
            os.environ["PATH"] = f"{os.pathsep.join(path_entries)}{os.pathsep}{os.environ.get('PATH', '')}"
        return


_add_nvidia_dll_directories()

from faster_whisper import WhisperModel  # noqa: E402


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
    parser.add_argument(
        "--language",
        default=os.getenv("LOCAL_BRIDGE_STT_LANGUAGE", "en"),
        help="Language hint, such as en. Use an empty value for auto-detect.",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=int(os.getenv("LOCAL_BRIDGE_STT_BEAM_SIZE", "5")),
        help="Beam size for decoding. Higher can improve accuracy at the cost of latency.",
    )
    parser.add_argument(
        "--best-of",
        type=int,
        default=int(os.getenv("LOCAL_BRIDGE_STT_BEST_OF", "5")),
        help="Number of candidates to sample when temperature is non-zero.",
    )
    parser.add_argument(
        "--hotwords",
        default=os.getenv("LOCAL_BRIDGE_STT_HOTWORDS", ""),
        help="Words or phrases to bias recognition toward.",
    )
    parser.add_argument(
        "--initial-prompt",
        default=os.getenv("LOCAL_BRIDGE_STT_INITIAL_PROMPT", ""),
        help="Context prompt to help recognition of local names and vocabulary.",
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
    language = args.language.strip() or None
    hotwords = args.hotwords.strip() or None
    initial_prompt = args.initial_prompt.strip() or None
    segments, _ = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        beam_size=args.beam_size,
        best_of=args.best_of,
        hotwords=hotwords,
        initial_prompt=initial_prompt,
    )
    transcript = " ".join(segment.text.strip() for segment in segments).strip()
    print(transcript)


if __name__ == "__main__":
    main()
