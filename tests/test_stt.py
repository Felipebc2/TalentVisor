from types import SimpleNamespace as S

import pytest

from talentvisor import stt


class FakeModel:
    def transcribe(self, path, **kw):
        assert kw["language"] == "pt" and kw["vad_filter"] and kw["word_timestamps"]
        segs = [
            S(start=0.0, end=1.0, text=" ola ", avg_logprob=-0.2, no_speech_prob=0.1),
            S(start=1.0, end=2.0, text=" mundo ", avg_logprob=-0.4, no_speech_prob=0.7),
        ]
        return iter(segs), S()


def test_happy_path(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(stt, "_model", lambda: FakeModel())
    r = stt.transcribe(f)
    assert r["segments"][0] == {"start": 0.0, "end": 1.0, "text": "ola"}
    assert r["text"] == "ola mundo"
    q = r["quality"]
    assert q["avg_logprob"] == pytest.approx(-0.3)
    assert q["no_speech_prob"] == pytest.approx(0.4)
    assert q["pct_inaudible"] == 0.5
    assert r["model"].startswith("faster-whisper/")
    assert not f.exists()


def test_video_deleted_even_on_error(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")

    def boom():
        raise RuntimeError("model failed")

    monkeypatch.setattr(stt, "_model", boom)
    with pytest.raises(RuntimeError):
        stt.transcribe(f)
    assert not f.exists()


def _sine(path, secs=25):
    import subprocess

    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=duration={secs}", str(path)],
        check=True,
    )


def test_chunks_under_25mb(tmp_path):
    import subprocess

    src = tmp_path / "a.wav"
    _sine(src)
    out = tmp_path / "out"
    out.mkdir()
    chunks = stt._chunks(src, out, seconds=10)
    assert len(chunks) == 3
    for c in chunks:
        assert c.suffix == ".mp3" and c.stat().st_size < 25 * 1024 * 1024
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels",
             "-of", "csv=p=0", str(c)],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        assert p.stdout.strip() == "16000,1"


class FakeGroq:
    def __init__(self):
        self.calls = []
        self.audio = S(transcriptions=S(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        n = len(self.calls)
        seg = S(start=0.0, end=1.0, text=f" chunk{n} ", avg_logprob=-0.5, no_speech_prob=0.2)
        return S(segments=[seg])


def _boom():
    raise RuntimeError("local failed")


def test_cloud_fallback_offsets_and_prompt(tmp_path, monkeypatch):
    f = tmp_path / "v.wav"
    _sine(f)
    fake = FakeGroq()
    seen = []
    monkeypatch.setenv("ALLOW_CLOUD_STT", "1")
    monkeypatch.setattr(stt, "_model", _boom)
    monkeypatch.setattr(stt, "_groq", lambda: fake)
    real = stt._chunks
    monkeypatch.setattr(stt, "_chunks", lambda *a: seen.extend(real(*a)) or seen)
    r = stt.transcribe(f, chunk_seconds=10, allow_cloud=True)
    assert [s["start"] for s in r["segments"]] == [0.0, 10.0, 20.0]
    assert [s["end"] for s in r["segments"]] == [1.0, 11.0, 21.0]
    assert r["model"] == "groq/whisper-large-v3"
    assert r["quality"]["avg_logprob"] == pytest.approx(-0.5)
    assert fake.calls[0]["prompt"] == ""
    assert fake.calls[1]["prompt"] == "chunk1"
    assert fake.calls[0]["model"] == "whisper-large-v3" and fake.calls[0]["language"] == "pt"
    assert fake.calls[0]["response_format"] == "verbose_json"
    assert not f.exists()
    assert len(seen) == 3 and not any(c.exists() for c in seen)


def test_no_fallback_when_flag_off(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    monkeypatch.delenv("ALLOW_CLOUD_STT", raising=False)
    monkeypatch.setattr(stt, "_model", _boom)
    monkeypatch.setattr(stt, "_groq", lambda: pytest.fail("cloud must not be called"))
    with pytest.raises(RuntimeError, match="local failed"):
        stt.transcribe(f, allow_cloud=True)
    assert not f.exists()


def test_cloud_needs_groq_consent(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    monkeypatch.setenv("ALLOW_CLOUD_STT", "1")
    monkeypatch.setattr(stt, "_model", _boom)
    monkeypatch.setattr(stt, "_groq", lambda: pytest.fail("cloud needs consent v1-groq"))
    with pytest.raises(RuntimeError, match="local failed"):
        stt.transcribe(f)  # allow_cloud defaults to False
    assert not f.exists()


def test_groq_missing_fields_worst_case(tmp_path, monkeypatch):
    f = tmp_path / "v.wav"
    _sine(f, secs=5)
    fake = S(audio=S(transcriptions=S(create=lambda **kw: S(segments=[S(start=0.0, end=1.0, text=" oi ")]))))
    monkeypatch.setenv("ALLOW_CLOUD_STT", "1")
    monkeypatch.setattr(stt, "_model", _boom)
    monkeypatch.setattr(stt, "_groq", lambda: fake)
    q = stt.transcribe(f, chunk_seconds=10, allow_cloud=True)["quality"]
    assert q["no_speech_prob"] == 1.0 and q["avg_logprob"] == -10.0


def test_zero_segments_is_not_perfect_audio(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")

    class Empty:
        def transcribe(self, path, **kw):
            return iter([]), S()

    monkeypatch.setattr(stt, "_model", lambda: Empty())
    q = stt.transcribe(f)["quality"]
    assert q["no_speech_prob"] == 1.0 and q["pct_inaudible"] == 1.0 and q["avg_logprob"] == -10.0
