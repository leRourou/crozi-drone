"""Chargement d'un bundle de release (contrat d'intégration ML V1) : validé, sinon refusé."""

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


def test_a_score_that_the_live_path_does_not_reproduce_is_refused(bundle):
    edit(bundle, "parity/fixture.json", lambda f: f["windows"][3].update(score=0.999))
    refused(bundle, "parité")


def test_features_that_the_live_path_does_not_reproduce_are_refused(bundle):
    edit(bundle, "parity/fixture.json", lambda f: f["windows"][0]["flat"].__setitem__(0, -1.0))
    refused(bundle, "parité")


def test_a_different_set_of_valid_windows_is_refused(bundle):
    edit(bundle, "parity/fixture.json", lambda f: f["windows"].pop())
    refused(bundle, "parité")


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


def test_a_tiny_feature_difference_breaks_parity(bundle):
    def change(f):
        f["windows"][0]["flat"][0] += 1e-6

    edit(bundle, "parity/fixture.json", change)
    refused(bundle, "parité")


def test_a_distance_given_where_offline_said_no_drone_breaks_parity(bundle):
    def change(f):
        absent = next(w for w in f["windows"] if w["distance_m"] is None)
        absent["distance_m"] = 3.0

    edit(bundle, "parity/fixture.json", change)
    refused(bundle, "parité")


def test_a_different_distance_breaks_parity(bundle):
    def change(f):
        present = next(w for w in f["windows"] if w["distance_m"] is not None)
        present["distance_m"] += 0.01

    edit(bundle, "parity/fixture.json", change)
    refused(bundle, "parité")
