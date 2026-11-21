"""Vrai estimateur de ② : modèle d'une release (contrat d'intégration ML V1), même interface
que le simulateur.

Chaque AudioWindow est un bloc contigu d'un pas ; il complète au plus une fenêtre du modèle. Sorties
(§4 du contrat) : fenêtre non analysable (warmup, coupure) ou score sous le seuil → range None ;
sinon Range(distance bornée par le modèle, uncertainty_rel fixée par l'application).
"""

from __future__ import annotations

import logging

import numpy as np

from distance_estimation.estimator import AudioWindow, DistanceEstimate, Range
from distance_estimation.release import Release
from distance_estimation.stream import Skipped, Stream

log = logging.getLogger("crozidrone.model")


class ModelEstimator:
    def __init__(self, release: Release, uncertainty_rel: float) -> None:
        self._release = release
        self._uncertainty_rel = uncertainty_rel
        # Un flux par téléphone, remplacé quand sa session change : jamais de recollage, et la
        # mémoire reste bornée par le nombre de profils.
        self._streams: dict[str, tuple[str, Stream]] = {}
        self._skipped: dict[str, str | None] = {}

    @property
    def chunk_frames(self) -> int:
        return self._release.windowing.chunk_frames

    def estimate(self, window: AudioWindow) -> DistanceEstimate:
        pcm = np.frombuffer(window.pcm, "<i2")
        if len(pcm) != self.chunk_frames:
            raise ValueError(f"bloc de {len(pcm)} échantillons, attendu {self.chunk_frames}")
        step = self._stream(window).push(pcm)
        self._log_skip(window.profile, step.reason if isinstance(step, Skipped) else None)
        if isinstance(step, Skipped):
            return DistanceEstimate(window.profile, window.t, None)
        distance = self._release.decide(step.pcm).distance_m
        rng = None if distance is None else Range(distance, self._uncertainty_rel)
        return DistanceEstimate(window.profile, window.t, rng)

    def _stream(self, window: AudioWindow) -> Stream:
        current = self._streams.get(window.profile)
        if current is None or current[0] != window.session_id:
            current = (window.session_id, Stream(self._release.windowing))
            self._streams[window.profile] = current
        return current[1]

    def _log_skip(self, profile: str, reason: str | None) -> None:
        if reason is not None and reason != self._skipped.get(profile):
            log.info("event=model_window_skipped profile=%s reason=%s", profile, reason)
        self._skipped[profile] = reason
