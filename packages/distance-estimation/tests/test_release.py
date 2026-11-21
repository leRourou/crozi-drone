"""Chargement d'un bundle de release (contrat d'intégration ML V1) : validé, sinon refusé."""

import base64
import json
import shutil

import numpy as np
import pytest

from conftest import bundle_manifest
from distance_estimation.release import Release, load_release, parse_manifest
from distance_estimation.stream import Windowing


@pytest.fixture
def bundle(model_bundle, tmp_path):
    return shutil.copytree(model_bundle, tmp_path / "bundle")


def edit(bundle, name, change):
    path = bundle / name
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def refused(bundle, match):
    with pytest.raises(ValueError, match=match):
        load_release(bundle)


def test_a_valid_bundle_gives_its_name_windowing_and_threshold(model_bundle):
    release = load_release(model_bundle)
    manifest = json.loads((model_bundle / "manifest.json").read_text())
    assert release.name == "test.24k-1s.r0"
    assert release.windowing == Windowing(24000, 24000, 6000, 12000, 1920, 24000)
    assert release.threshold == manifest["detection"]["threshold"]


def test_an_unknown_contract_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m.update(contract="edth.model-release.v2"))
    refused(bundle, "contract")


def test_a_transport_other_than_48_khz_mono_s16le_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["input"]["transport"].update(rate_hz=44100))
    refused(bundle, "transport")


def test_a_model_rate_unknown_to_the_frozen_dsp_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["input"].update(model_rate_hz=22050))
    refused(bundle, "model_rate_hz")


def test_a_fir_fingerprint_that_does_not_match_the_frozen_dsp_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["input"]["fir"].update(coefficients_sha256="0" * 64))
    refused(bundle, "FIR")


def test_window_samples_inconsistent_with_their_duration_are_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["input"]["window"].update(samples=12000))
    refused(bundle, "window")


def test_windows_not_aligned_on_the_step_are_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["input"]["qc"].update(start_guard_ms=100))
    refused(bundle, "pas")


def test_a_threshold_outside_0_1_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["detection"].update(threshold=1.5))
    refused(bundle, "threshold")


def test_a_missing_field_is_named(bundle):
    edit(bundle, "manifest.json", lambda m: m["input"].pop("qc"))
    refused(bundle, "input.qc")


def test_a_missing_model_file_is_refused(bundle):
    (bundle / "distance" / "model.joblib").unlink()
    refused(bundle, "distance/model.joblib")


def test_a_bundle_of_symlinks_like_the_hugging_face_cache_loads(model_bundle, tmp_path):
    """Le cache HF range les fichiers d'un snapshot en liens vers des blobs hors du dossier."""
    blobs, snapshot = tmp_path / "blobs", tmp_path / "snapshot"
    shutil.copytree(model_bundle, blobs)
    for blob in blobs.rglob("*"):
        if blob.is_file():
            link = snapshot / blob.relative_to(blobs)
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(blob)
    assert load_release(snapshot).name == "test.24k-1s.r0"


def test_a_model_file_outside_the_bundle_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["detection"].update(file="../model.joblib"))
    refused(bundle, "hors du bundle")


def test_a_release_built_on_other_frozen_code_than_the_app_copy_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["frozen"]["files"].update({"frozen/ml.py": "0" * 64}))
    refused(bundle, "frozen/ml.py")


def test_a_frozen_file_that_does_not_match_its_manifest_fingerprint_is_refused(bundle):
    (bundle / "frozen" / "dsp.py").write_text("# modifié\n")
    refused(bundle, "frozen/dsp.py")


def test_a_release_must_list_both_frozen_files(bundle):
    edit(bundle, "manifest.json", lambda m: m["frozen"]["files"].pop("frozen/dsp.py"))
    refused(bundle, "frozen/dsp.py")


def test_a_bundle_without_parity_set_is_refused(bundle):
    (bundle / "parity" / "fixture.json").unlink()
    refused(bundle, "parity/fixture.json")


# ---------------------------------------------------------------- manifeste seul (sans pickles)


def manifest_with(change):
    data = bundle_manifest(threshold=0.5)
    change(data)
    return data


def test_windows_need_not_be_a_multiple_of_the_step_when_they_end_on_it():
    def change(m):
        m["input"]["window"].update(step_ms=300, step_samples=7200)
        m["input"]["qc"].update(start_guard_ms=200)

    assert parse_manifest(manifest_with(change)).windowing == Windowing(
        24000, 24000, 7200, 4800, 1920, 24000
    )


def test_a_zero_guard_is_a_valid_setting():
    manifest = parse_manifest(manifest_with(lambda m: m["input"]["qc"].update(guard_ms=0)))
    assert manifest.windowing.guard == 0


@pytest.mark.parametrize(
    "change, match",
    [
        (lambda m: m["input"]["qc"].update(guard_ms="500"), "qc.guard_ms"),
        (lambda m: m["input"]["qc"].update(guard_ms=-500), "qc.guard_ms"),
        (lambda m: m["input"]["qc"].update(zero_run_ms=0.01), "qc.zero_run_ms"),
        (lambda m: m["input"]["window"].update(step_ms=0, step_samples=0), "window.step_ms"),
        (lambda m: m["input"]["window"].update(ms=0, samples=0), "window.ms"),
        (lambda m: m["detection"].update(threshold=0), "threshold"),
        (lambda m: m["detection"].update(threshold=1), "threshold"),
        (lambda m: m["detection"].update(threshold=True), "threshold"),
    ],
)
def test_invalid_values_are_refused_by_name(change, match):
    with pytest.raises(ValueError, match=match):
        parse_manifest(manifest_with(change))


def test_a_score_exactly_at_the_threshold_means_a_drone():
    class Constant:
        def __init__(self, value):
            self.value = value

        def predict(self, d):
            return np.full(len(d), self.value)

    windowing = parse_manifest(manifest_with(lambda m: None)).windowing
    release = Release("r", windowing, 0.5, Constant(0.5), Constant(2.5))
    decision = release.decide(np.ones(windowing.samples, dtype=np.int16))
    assert (decision.score, decision.distance_m) == (0.5, 2.5)
    below = Release("r", windowing, 0.5, Constant(0.4999), Constant(2.5)).decide(
        np.ones(windowing.samples, dtype=np.int16)
    )
    assert below.distance_m is None


# ---------------------------------------------------------------- lot de parité (format r0)


def present_case(f):
    return next(c for c in f["cases"] if c["expected"]["present"])


def absent_case(f):
    return next(c for c in f["cases"] if not c["expected"]["present"])


def zeroed_pcm(b64):
    return base64.b64encode(bytes(len(base64.b64decode(b64)))).decode()


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda f: present_case(f)["expected"].update(score=0.999), id="score"),
        pytest.param(lambda f: f["cases"][0]["expected"]["flat"].update(
            f0=f["cases"][0]["expected"]["flat"]["f0"] + 1e-6), id="tiny-flat-difference"),
        pytest.param(lambda f: f["cases"][0]["expected"]["logmel"].__setitem__(
            5, f["cases"][0]["expected"]["logmel"][5] + 1e-3), id="logmel"),
        pytest.param(lambda f: absent_case(f)["expected"].update(present=True), id="presence"),
        pytest.param(lambda f: present_case(f)["expected"].update(
            distance_m=present_case(f)["expected"]["distance_m"] + 0.01), id="distance"),
        pytest.param(lambda f: f["cases"][0]["expected"].update(
            window_pcm24_b64=zeroed_pcm(f["cases"][0]["expected"]["window_pcm24_b64"])),
            id="decimated-window"),
        pytest.param(lambda f: f["cases"][0]["excerpt"].update(window_start_offset_24k=18000),
                     id="window-position"),
    ],
)
def test_a_case_the_live_path_does_not_reproduce_breaks_parity(bundle, change):
    edit(bundle, "parity/fixture.json", change)
    refused(bundle, "parité")


def test_the_distance_of_an_absent_case_is_not_compared(bundle):
    """La distance n'est produite que si la présence est établie (contrat §4) : hors ligne, le
    lot la donne quand même pour les cas absents, sans que le chemin live ait à la reproduire."""
    edit(bundle, "parity/fixture.json", lambda f: absent_case(f)["expected"].update(distance_m=9.9))
    assert load_release(bundle).name == "test.24k-1s.r0"


def test_an_empty_parity_set_is_refused(bundle):
    edit(bundle, "parity/fixture.json", lambda f: f.update(cases=[]))
    refused(bundle, "parité")


def test_an_excerpt_that_is_not_whole_chunks_is_refused(bundle):
    def change(f):
        excerpt = f["cases"][0]["excerpt"]
        pcm = base64.b64decode(excerpt["pcm48_b64"])
        excerpt["pcm48_b64"] = base64.b64encode(pcm[:-2]).decode()

    edit(bundle, "parity/fixture.json", change)
    refused(bundle, "parité")
