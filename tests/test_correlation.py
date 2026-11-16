"""Measure actual synchronization error against known offsets (no fabricated results)."""
import numpy as np
import pytest

from core.synchronization.correlate import correlate_pair
from tests import synth

SR = 16000
TOL = 0.0005   # 0.5 ms; far below one video frame (33 ms)


@pytest.fixture(scope="module")
def master():
    return synth.speechlike(300, SR, seed=1)


def run(tmp_path, ref, tgt, **kw):
    r = tmp_path / "ref.wav"; t = tmp_path / "tgt.wav"
    synth.write(r, ref, SR); synth.write(t, tgt, SR)
    return correlate_pair(r, t, **kw)


@pytest.mark.parametrize("off", [0.0, 12.3456, 97.0123, 150.5])
def test_positive_offsets_exact(tmp_path, master, off):
    res = run(tmp_path, master, synth.cut(master, SR, off, 120))
    print(f"true={off} measured={res.offset:.6f} err={abs(res.offset-off)*1000:.4f}ms conf={res.confidence}")
    assert res.ok and abs(res.offset - off) < TOL and res.confidence == "High"


def test_negative_offset(tmp_path, master):
    res = run(tmp_path, master[: 200 * SR], synth.pad_start(synth.cut(master, SR, 0, 150), SR, 7.25))
    assert res.ok and abs(res.offset - (-7.25)) < TOL, res.offset


def test_different_durations(tmp_path, master):
    # target much shorter than reference, and a long target against a short reference
    res = run(tmp_path, master, synth.cut(master, SR, 40.0, 25))
    assert abs(res.offset - 40.0) < TOL
    res2 = run(tmp_path, synth.cut(master, SR, 30, 60), synth.cut(master, SR, 0, 200))
    assert abs(res2.offset - (-30.0)) < TOL and res2.confidence in ("Medium", "High")


def test_background_noise(tmp_path, master):
    tgt = synth.add_noise(synth.cut(master, SR, 55.5, 120) * 0.2, snr_db=0)   # quieter + 0 dB SNR
    res = run(tmp_path, master, tgt)
    assert abs(res.offset - 55.5) < TOL and res.confidence in ("High", "Medium")


def test_silent_sections(tmp_path):
    x = synth.speechlike(200, SR, seed=3)
    x[40 * SR:90 * SR] = 0   # 50 s of digital silence in the middle
    res = run(tmp_path, x, synth.cut(x, SR, 20.0, 150))
    assert abs(res.offset - 20.0) < TOL and res.confidence == "High"


def test_fully_silent_target_fails_cleanly(tmp_path, master):
    res = run(tmp_path, master, np.zeros(60 * SR, dtype=np.float32))
    assert not res.ok and res.confidence == "Failed" and "silent" in res.notes[0].lower()


def test_repetitive_audio_not_falsely_matched(tmp_path):
    t = np.arange(120 * SR) / SR
    loop = (np.sin(2 * np.pi * 440 * t) * (np.sin(2 * np.pi * 2 * t) > 0)).astype(np.float32) * 0.4  # periodic tone bursts
    res = run(tmp_path, loop, loop[10 * SR + 1234:][: 60 * SR])
    # ambiguous by construction: must NOT claim High confidence
    assert res.confidence in ("Failed", "Low")


def test_unrelated_audio_is_not_claimed(tmp_path, master):
    other = synth.speechlike(120, SR, seed=77)
    res = run(tmp_path, master, other)
    assert res.confidence in ("Failed", "Low")


def test_drift_detected_and_offset_at_start(tmp_path, master):
    ppm = 100.0
    seg = synth.cut(master, SR, 10.0, 240)
    # target clock runs fast by `ppm`: it holds (1+ppm*1e-6) times more samples per master second
    n = len(seg)
    src_t = np.arange(int(n * (1 + ppm * 1e-6))) / (1 + ppm * 1e-6)
    tgt = np.interp(src_t, np.arange(n), seg).astype(np.float32)
    res = run(tmp_path, master, tgt)
    # reference_time = target_time*(1 - ppm*1e-6) + 10  -> slope = -ppm
    assert res.confidence == "High"
    assert abs(res.drift_ppm - (-ppm)) < 10, res.drift_ppm
    assert abs(res.offset - 10.0) < 0.002


def test_cancellation(tmp_path, master):
    from app.errors import Cancelled
    from workers.base import CancelToken
    tok = CancelToken(); tok.cancel()
    with pytest.raises(Cancelled):
        run(tmp_path, master, synth.cut(master, SR, 5, 60), token=tok)
