"""Local speech-to-text (faster-whisper) and optional chunked Groq fallback; deletes media in `finally`.

REQ-F-04, REQ-F-05, REQ-L-01
"""

import os
import subprocess
import tempfile
from functools import cache
from pathlib import Path
from types import SimpleNamespace

MODEL = os.environ.get("STT_MODEL", "large-v3-turbo")


@cache
def _model():
    from faster_whisper import WhisperModel  # lazy: heavy import, loaded once

    return WhisperModel(MODEL, device="cpu", compute_type="int8")


def _groq():
    from openai import OpenAI  # lazy; Groq speaks the OpenAI protocol

    return OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"], max_retries=0, timeout=60)


def _chunks(path, out_dir, seconds=600) -> list[Path]:
    """Extract 16 kHz mono mp3 and split it into <= `seconds` chunks (Groq limit is 25 MB)."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
         "-f", "segment", "-segment_time", str(seconds), "-c:a", "libmp3lame",
         str(Path(out_dir) / "c%03d.mp3")],
        check=True,
    )  # fmt: skip
    return sorted(Path(out_dir).glob("c*.mp3"))


def _groq_segments(chunks, seconds) -> list:
    client, segs, prev = _groq(), [], ""
    for i, c in enumerate(chunks):
        with open(c, "rb") as f:
            r = client.audio.transcriptions.create(
                model="whisper-large-v3", file=f, language="pt",
                prompt=prev[-200:], response_format="verbose_json",
            )  # fmt: skip
        got = [
            SimpleNamespace(
                start=s.start + i * seconds,
                end=s.end + i * seconds,
                text=s.text,
                avg_logprob=getattr(s, "avg_logprob", -10.0),  # missing → worst case, never "perfect audio"
                no_speech_prob=getattr(s, "no_speech_prob", 1.0),
            )
            for s in r.segments or []
        ]
        segs += got
        prev = " ".join(s.text.strip() for s in got)
    return segs


def _result(segs, model) -> dict:
    n = len(segs) or 1
    # No segments = no speech: worst case on every metric, never perfect audio (D-034).
    empty = not segs
    return {
        "segments": [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs],
        "text": " ".join(s.text.strip() for s in segs),
        "quality": {
            "avg_logprob": -10.0 if empty else sum(s.avg_logprob for s in segs) / n,
            "no_speech_prob": 1.0 if empty else sum(s.no_speech_prob for s in segs) / n,
            # pct_inaudible = share of segments with no_speech_prob > 0.5
            "pct_inaudible": 1.0 if empty else sum(s.no_speech_prob > 0.5 for s in segs) / n,
        },
        "model": model,
    }


def transcribe(path, chunk_seconds=600, allow_cloud=False) -> dict:
    """Transcribe `path` locally; Groq fallback only if ALLOW_CLOUD_STT=1 AND the candidate consented to it
    (`allow_cloud`, consent v1-groq, L-04). Media is ALWAYS deleted (REQ-L-01)."""
    path = Path(path)
    try:
        try:
            gen, _info = _model().transcribe(
                str(path), language="pt", vad_filter=True, word_timestamps=True
            )
            return _result(list(gen), f"faster-whisper/{MODEL}")  # consume before the file goes away
        except Exception:
            if not (allow_cloud and os.environ.get("ALLOW_CLOUD_STT") == "1"):
                raise
        with tempfile.TemporaryDirectory(dir=path.parent) as tmp:  # chunks stay next to the upload, never orphaned in /tmp
            segs = _groq_segments(_chunks(path, tmp, chunk_seconds), chunk_seconds)
        return _result(segs, "groq/whisper-large-v3")
    finally:
        path.unlink(missing_ok=True)
