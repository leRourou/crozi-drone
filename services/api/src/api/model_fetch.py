"""Où trouver le bundle de release du modèle : dossier local, sinon Hugging Face (révision fixée).

Au démarrage, make_estimation appelle resolve_bundle ; le cache Hugging Face (HF_HOME) évite de
retélécharger une révision déjà présente. Pour tirer le modèle au déploiement plutôt qu'au premier
démarrage : `python -m api.model_fetch` (mêmes variables d'environnement).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from api.settings import Settings, load_settings

Fetch = Callable[[str, str, "str | None", str], Path]


def fetch_release(repo: str, revision: str, token: str | None, release: str) -> Path:
    """Télécharge le seul dossier de la release ; renvoie la racine du snapshot."""
    from huggingface_hub import snapshot_download

    path = snapshot_download(
        repo_id=repo, revision=revision, token=token, allow_patterns=[f"{release}/*"]
    )
    return Path(path)


def resolve_bundle(settings: Settings, fetch: Fetch = fetch_release) -> Path:
    """settings validés : model_dir (le bundle lui-même), ou repo + révision (sha) + dossier de
    release ; le repo peut contenir plusieurs releases, une par dossier."""
    if settings.model_dir is not None:
        return Path(settings.model_dir)
    release = settings.model_release
    return fetch(settings.model_repo, settings.model_revision, settings.hf_token, release) / release


if __name__ == "__main__":
    print(resolve_bundle(load_settings()))
