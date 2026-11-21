"""Chargement d'un bundle de release (contrat d'intégration ML v2) : validé, sinon refusé."""

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
    assert release.name == "test.48k-w100.r0"
    assert release.windowing == Windowing(48000, 4800, 960, 24000, 1920, 24000)
    assert release.threshold == manifest["detection"]["threshold"]
    assert (release.window_ms, release.recompute) == (100, manifest["features"]["recompute"])


def test_an_unknown_contract_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m.update(contract="edth.model-release.v3"))
    refused(bundle, "contract")


def test_a_v1_release_is_refused_since_the_loader_follows_contract_v2(bundle):
    edit(bundle, "manifest.json", lambda m: m.update(contract="edth.model-release.v1"))
    refused(bundle, "contract")


def test_a_transport_other_than_48_khz_mono_s16le_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["input"]["transport"].update(rate_hz=44100))
    refused(bundle, "transport")


def test_a_model_rate_unknown_to_the_frozen_dsp_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["input"].update(model_rate_hz=22050))
    refused(bundle, "model_rate_hz")


def test_a_fir_announced_at_48_khz_where_the_frozen_dsp_filters_nothing_is_refused(bundle):
    fir = {"coefficients_sha256": "0" * 64}
    edit(bundle, "manifest.json", lambda m: m["input"].update(fir=fir))
    refused(bundle, "FIR")


def test_no_fir_at_a_rate_where_the_frozen_dsp_filters_is_refused():
    with pytest.raises(ValueError, match="FIR"):
        parse_manifest(manifest_with(lambda m: m["input"].update(model_rate_hz=24000)))


def test_a_release_whose_features_are_not_window_local_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["features"].update(local_only=False))
    refused(bundle, "local_only")


def test_a_recompute_argument_unknown_to_window_features_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["features"]["recompute"].update(per_take=True))
    refused(bundle, "per_take")


def test_a_band_group_unknown_to_the_frozen_dsp_is_refused(bundle):
    edit(bundle, "manifest.json",
         lambda m: m["features"]["recompute"].update(band_level_group="band_levels_avg7"))
    refused(bundle, "band_levels_avg7")


@pytest.mark.parametrize("model", ["detection", "distance"])
def test_columns_that_are_not_the_pickled_model_columns_are_refused(bundle, model):
    edit(bundle, "manifest.json", lambda m: m[model]["columns"].reverse())
    refused(bundle, f"{model}.columns")


def test_window_samples_inconsistent_with_their_duration_are_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["input"]["window"].update(samples=12000))
    refused(bundle, "window")


def test_windows_not_aligned_on_the_step_are_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["input"]["qc"].update(start_guard_ms=10))
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
    assert load_release(snapshot).name == "test.48k-w100.r0"


def test_a_model_file_outside_the_bundle_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["detection"].update(file="../model.joblib"))
    refused(bundle, "hors du bundle")


def test_a_release_built_on_other_frozen_code_than_the_app_copy_is_refused(bundle):
    edit(bundle, "manifest.json", lambda m: m["frozen"]["files"].update({"frozen/ml.py": "0" * 64}))
    refused(bundle, "frozen/ml.py")


def test_a_frozen_file_that_does_not_match_its_manifest_fingerprint_is_refused(bundle):
    (bundle / "frozen" / "dsp.py").write_text("# modifié\n")
    refused(bundle, "frozen/dsp.py")


@pytest.mark.parametrize("name", ["frozen/dsp.py", "frozen/features.py", "frozen/ml.py"])
def test_a_release_must_list_the_three_frozen_files(bundle, name):
    edit(bundle, "manifest.json", lambda m: m["frozen"]["files"].pop(name))
    refused(bundle, name)


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
        m["input"]["window"].update(step_ms=30, step_samples=1440)
        m["input"]["qc"].update(start_guard_ms=20)

    assert parse_manifest(manifest_with(change)).windowing == Windowing(
        48000, 4800, 1440, 960, 1920, 24000
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

    manifest = parse_manifest(manifest_with(lambda m: None))
    window = np.ones(manifest.windowing.samples, dtype=np.int16)

    def release(score):
        return Release("r", manifest.windowing, 0.5, Constant(score), Constant(2.5),
                       manifest.window_ms, manifest.recompute)

    decision = release(0.5).decide(window)
    assert (decision.score, decision.distance_m) == (0.5, 2.5)
    assert release(0.4999).decide(window).distance_m is None


# ---------------------------------------------------------------- lot de parité (format v2)


def present_case(f):
    return next(c for c in f["cases"] if c["expected"]["present"])


def absent_case(f):
    return next(c for c in f["cases"] if not c["expected"]["present"])


def nudge_first_feature(flat, delta):
    first = next(iter(flat))
    flat[first] += delta


def zeroed_pcm(b64):
    return base64.b64encode(bytes(len(base64.b64decode(b64)))).decode()


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda f: present_case(f)["expected"].update(score=0.999), id="score"),
        pytest.param(lambda f: nudge_first_feature(f["cases"][0]["expected"]["flat"], 1e-6),
                     id="tiny-flat-difference"),
        pytest.param(lambda f: f["cases"][0]["expected"]["flat"].update(rms_db=-30.0),
                     id="feature-not-produced-live"),
        pytest.param(lambda f: f["cases"][0]["expected"].update(window_ms=1000), id="window-ms"),
        pytest.param(lambda f: f["cases"][0]["expected"]["recompute"].update(include_rms=True),
                     id="recompute"),
        pytest.param(lambda f: absent_case(f)["expected"].update(present=True), id="presence"),
        pytest.param(lambda f: present_case(f)["expected"].update(
            distance_m=present_case(f)["expected"]["distance_m"] + 0.01), id="distance"),
        pytest.param(lambda f: f["cases"][0]["expected"].update(
            window_pcm_b64=zeroed_pcm(f["cases"][0]["expected"]["window_pcm_b64"])),
            id="decimated-window"),
        pytest.param(lambda f: f["cases"][0]["excerpt"].update(window_start_offset=24960),
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
    assert load_release(bundle).name == "test.48k-w100.r0"


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
