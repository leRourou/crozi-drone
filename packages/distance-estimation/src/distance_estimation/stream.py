"""Chemin live du modèle : flux 48 kHz d'une session → fenêtres au taux modèle, contrôle qualité.

Reproduit dsp.iter_windows (préparation hors ligne) par blocs : décimation continue sur toute la
session (état FIR et phase conservés), fenêtres glissantes sur le flux décimé, contrôle qualité sur
le flux 48 kHz AVANT filtrage (suite d'échantillons exactement nuls ≥ zero_run → fenêtres touchées
exclues, et celles qui commencent moins de guard après sa fin).

Seul écart possible, causal : une suite de zéros encore en cours à la fin d'une fenêtre et pas
encore assez longue n'invalide pas cette fenêtre, alors que hors ligne elle est vue en entier.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from dsp import Decimator

TRANSPORT_RATE = 48000


@dataclass(frozen=True)
class Windowing:
    """Fenêtrage d'une release. rate, samples, step, start : au taux modèle ; zero_run, guard :
    48 kHz. Invariant (vérifié au chargement) : la fin de chaque fenêtre tombe sur un pas, donc à la
    fin de tout bloc d'un nombre entier de pas."""

    rate: int
    samples: int
    step: int
    start: int
    zero_run: int
    guard: int

    @property
    def factor(self) -> int:
        return TRANSPORT_RATE // self.rate

    @property
    def chunk_frames(self) -> int:
        """Un pas, en échantillons 48 kHz : la plus petite taille de bloc acceptée par push."""
        return self.step * self.factor


@dataclass(frozen=True)
class Ready:
    """Fenêtre valide : index de départ (taux modèle, depuis le début de la session) et PCM16."""

    start: int
    pcm: np.ndarray


@dataclass(frozen=True)
class Skipped:
    """Bloc sans fenêtre analysable : warmup (pas encore de fenêtre complète) ou dropout."""

    reason: str


class Stream:
    """Une instance par session, jamais réutilisée : une nouvelle session repart d'un état neuf."""

    def __init__(self, windowing: Windowing) -> None:
        self._w = windowing
        self._decimator = Decimator(windowing.rate)
        self._window = np.empty(0, dtype=np.int16)
        self._decimated = 0  # échantillons décimés reçus
        self._received = 0  # échantillons 48 kHz reçus
        self._run_start: int | None = None  # suite de zéros encore ouverte en fin de bloc
        self._last_gap_end = -math.inf  # fin de la dernière coupure (≥ zero_run) terminée

    def push(self, pcm48: np.ndarray) -> Ready | Skipped:
        """pcm48 : un nombre entier de pas ; renvoie la dernière fenêtre complétée par le bloc."""
        self._track_zeros(pcm48)
        y = self._decimator.process(pcm48)
        self._decimated += len(y)
        self._window = np.concatenate((self._window, y))[-self._w.samples :]
        if self._decimated < self._w.start + self._w.samples:
            return Skipped("warmup")
        start = self._decimated - self._w.samples
        if self._in_dropout(start):
            return Skipped("dropout")
        return Ready(start, self._window)

    def _track_zeros(self, x: np.ndarray) -> None:
        offset = self._received
        self._received += len(x)
        runs = np.flatnonzero(np.diff(x == 0, prepend=False, append=False)).reshape(-1, 2) + offset
        if self._run_start is not None:
            if len(runs) and runs[0, 0] == offset:
                runs[0, 0] = self._run_start
            else:  # la suite ouverte s'est arrêtée pile à la frontière du bloc
                runs = np.vstack(([[self._run_start, offset]], runs))
            self._run_start = None
        if len(runs) and runs[-1, 1] == self._received:
            self._run_start = int(runs[-1, 0])
            runs = runs[:-1]
        gaps = runs[runs[:, 1] - runs[:, 0] >= self._w.zero_run]
        if len(gaps):
            self._last_gap_end = int(gaps[-1, 1])

    def _in_dropout(self, start: int) -> bool:
        ongoing = self._run_start is not None
        if ongoing and self._received - self._run_start >= self._w.zero_run:
            return True
        return self._last_gap_end + self._w.guard > self._w.factor * start
