"""Chargement du contrat partagé contracts/profiles.json (validé une fois, au démarrage)."""

import json

import pytest

from api.profiles import Profile, load_profiles

VALID = {
    "profiles": [
        {"id": "noe", "label": "Téléphone de Noé", "position_m": {"x": 2.06, "y": 9.66, "z": 0}},
        {
            "id": "tristan",
            "label": "Téléphone de Tristan",
            "position_m": {"x": 4, "y": 10.76, "z": 0},
        },
    ]
}


def write(tmp_path, obj):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def test_the_shared_contract_lists_the_three_team_phones_with_positions():
    assert load_profiles() == (
        Profile(id="noe", label="Téléphone de Noé", x_m=2.06, y_m=9.66, z_m=0.0),
        Profile(id="tristan", label="Téléphone de Tristan", x_m=4.0, y_m=10.76, z_m=0.0),
        Profile(id="maxence", label="Téléphone de Maxence", x_m=2.06, y_m=11.86, z_m=0.0),
    )


def test_a_valid_file_is_parsed_in_order_with_float_positions(tmp_path):
    profiles = load_profiles(write(tmp_path, VALID))
    assert [p.id for p in profiles] == ["noe", "tristan"]
    assert profiles[1].x_m == 4.0 and isinstance(profiles[1].x_m, float)
    assert profiles[1].z_m == 0.0 and isinstance(profiles[1].z_m, float)


def test_profiles_file_env_var_points_to_another_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_FILE", str(write(tmp_path, VALID)))
    assert len(load_profiles()) == 2


def profile(**overrides):
    base = {"id": "noe", "label": "Téléphone de Noé", "position_m": {"x": 1.0, "y": 2.0, "z": 0.0}}
    return {**base, **overrides}


@pytest.mark.parametrize(
    ("obj", "detail"),
    [
        ([], "object"),
        ({"profiles": []}, "non-empty"),
        ({"profiles": "noe"}, "non-empty"),
        ({"profiles": [profile(id="Noé")]}, "id"),
        ({"profiles": [profile(id="")]}, "id"),
        ({"profiles": [profile(id=3)]}, "id"),
        ({"profiles": [profile(label="")]}, "label"),
        ({"profiles": [profile(label=None)]}, "label"),
        ({"profiles": [profile(position_m=None)]}, "position_m"),
        ({"profiles": [profile(position_m={"x": 1.0})]}, "position_m.y"),
        ({"profiles": [profile(position_m={"x": 1.0, "y": 2.0})]}, "position_m.z"),
        ({"profiles": [profile(position_m={"x": 1.0, "y": 2.0, "z": "0"})]}, "position_m.z"),
        ({"profiles": [profile(position_m={"x": "1", "y": 2.0})]}, "position_m.x"),
        ({"profiles": [profile(position_m={"x": True, "y": 2.0})]}, "position_m.x"),
        ({"profiles": [profile(), profile(label="Autre")]}, "duplicate"),
        ({"profiles": ["noe"]}, "object"),
    ],
)
def test_an_invalid_contract_refuses_to_start(tmp_path, obj, detail):
    with pytest.raises(ValueError, match=detail):
        load_profiles(write(tmp_path, obj))
