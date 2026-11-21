"""Bibliothèque partagée des étapes 02 (classification) et 03 (distance).

Architectures gelées d'après l'HPO préliminaire (run RTX 3090) :
  - détection : CNN 2D sur le spectre FFT relatif en dB, un bloc conv 32 canaux,
    dropout 0.15, ~450 paramètres, seuil 0.5, sans one-hot téléphone ;
  - distance  : MLP 16 cachées, dropout 0.15, sur niveaux ABSOLUS pleine
    bande, sans one-hot téléphone, sortie bornée [1, 5] m.
Baselines : logistique (détection), ridge et constant 3 m (distance).
Tout poids d'apprentissage ou d'évaluation donne une masse égale par PRISE.
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, mean_absolute_error,
                             precision_score, recall_score)
from sklearn.preprocessing import StandardScaler

FROZEN = {("classification", "cnn"): dict(lr=7.7e-3, dropout=0.15),
          ("distance", "mlp"): dict(lr=3e-3, dropout=0.15)}
BATCH_CNN, BATCH_MLP = 512, 128
KEYS = ["sample_id", "device_id", "group_id", "split", "drone_present", "distance_m"]


def weights(d):
    return 1.0 / d.groupby("sample_id")["sample_id"].transform("size").to_numpy(float)


def logfft_array(d):
    bins = sum(name.startswith("fft_") for name in d.columns)
    arr = np.stack(d["logfft"].to_numpy()).astype(np.float32, copy=False)
    if not bins or arr.ndim != 2 or not arr.shape[1] or arr.shape[1] % bins or not np.isfinite(arr).all():
        raise ValueError("logfft invalide pour le nombre de bins FFT du cache")
    return arr.reshape(len(d), bins, -1)


def _flat_x(d, cols, relative):
    x = d[cols].to_numpy(float, copy=True)
    if relative:
        spectral = [i for i, c in enumerate(cols) if c.startswith(("fft_", "band_level_")) or c == "b4_8"]
        if spectral:
            if "rms_db" not in d:
                raise ValueError("rms_db est requis pour les niveaux relatifs.")
            x[:, spectral] -= d[["rms_db"]].to_numpy()
        x = np.delete(x, [i for i, c in enumerate(cols) if c == "rms_db"], axis=1)
    return x


def _bin_stats(x, w):
    wn = w / w.sum()
    mu = wn @ x.mean(axis=2, dtype=np.float64)
    second = np.einsum("i,ift,ift->f", wn, x, x) / x.shape[2]
    sd = np.sqrt(np.maximum(second - mu**2, 0.0))
    return mu.astype(np.float32), np.where(sd < 1e-6, 1.0, sd).astype(np.float32)


class CnnPresence:
    """Détection par CNN sur le spectre FFT relatif en dB."""
    task = "classification"

    def __init__(self, lr, dropout):
        self.lr, self.dropout = float(lr), float(dropout)
        self.curve, self.best_epoch, self.state = [], 0, None

    def _input(self, d):
        return logfft_array(d) - d["rms_db"].to_numpy(np.float32)[:, None, None]

    def _net(self):
        from torch import nn
        return nn.Sequential(nn.Conv2d(1, 32, 3, padding=1), nn.ReLU(),
                             nn.Dropout2d(self.dropout), nn.AdaptiveAvgPool2d((2, 2)),
                             nn.Flatten(), nn.Linear(128, 1))

    @staticmethod
    def _logits(net, x):
        import torch
        return torch.cat([net(batch.unsqueeze(1)).flatten() for batch in x.split(BATCH_CNN)])

    def fit(self, d, valid=None, device="cpu", epochs=60, patience=8, seed=42, cols=None):
        import torch
        from torch import nn
        if valid is not None and len(valid) == 0:
            valid = None
        w = weights(d)
        x = self._input(d)
        self.mu, self.sd = _bin_stats(x, w)
        tx = torch.as_tensor(self._scale(x), dtype=torch.float32, device=device)
        ty = torch.as_tensor(d.drone_present.to_numpy(np.float32), device=device)
        tw = torch.as_tensor(w / w.mean(), dtype=torch.float32, device=device)
        if valid is not None:
            vx = torch.as_tensor(self._scale(self._input(valid)), dtype=torch.float32, device=device)
            vy = torch.as_tensor(valid.drone_present.to_numpy(np.float32), device=device)
            vw = torch.as_tensor(weights(valid), dtype=torch.float32, device=device)
        torch.manual_seed(seed)
        net = self._net().to(device)
        optim = torch.optim.AdamW(net.parameters(), lr=self.lr, weight_decay=1e-4)
        criterion = nn.BCEWithLogitsLoss(reduction="none")
        gen = torch.Generator().manual_seed(seed)
        best = np.inf
        for epoch in range(1, epochs + 1):
            net.train()
            order = torch.randperm(len(tx), generator=gen)  # une permutation par époque
            epoch_loss = torch.zeros((), device=device)
            correct = torch.zeros((), device=device)
            for start in range(0, len(tx), BATCH_CNN):
                idx = order[start:start + BATCH_CNN]
                optim.zero_grad(set_to_none=True)
                logits = net(tx[idx].unsqueeze(1)).flatten()
                loss = (criterion(logits, ty[idx]) * tw[idx]).mean()
                loss.backward()
                optim.step()
                epoch_loss += loss.detach() * len(idx)
                correct += (((logits.detach() >= 0) == ty[idx].bool()) * tw[idx]).sum()
            net.eval()
            with torch.inference_mode():
                row = {"epoch": epoch, "train_loss": float(epoch_loss / len(tx)),
                       "train_accuracy": float(correct / len(tx))}
                score = row["train_loss"] if valid is None else None
                if valid is not None:
                    vp = self._logits(net, vx)
                    score = float((criterion(vp, vy) * vw).sum() / vw.sum())
                    row.update(val_loss=score, val_accuracy=float((((vp >= 0) == vy.bool()).float() * vw).sum() / vw.sum()))
            self.curve.append(row)
            print(f"époque {epoch}/{epochs}  loss = {score:.4f}", flush=True)
            if not np.isfinite(score):
                raise ValueError("loss non finie")
            if valid is None or score < best - 1e-6:
                best, self.best_epoch = score, epoch
                self.state = {k: v.detach().cpu().numpy().copy() for k, v in net.state_dict().items()}
            elif epoch - self.best_epoch >= patience:
                break
        if self.state is None:
            raise ValueError("aucun point de contrôle fini")
        return self

    def _scale(self, x):
        return ((x - self.mu[None, :, None]) / self.sd[None, :, None]).astype(np.float32)

    def predict(self, d, *, bounded=True):
        import torch
        if d.empty:
            return np.empty(0)
        net = self._net()
        net.load_state_dict({k: torch.from_numpy(np.ascontiguousarray(v)) for k, v in self.state.items()})
        net.eval()
        x = self._scale(self._input(d))
        with torch.inference_mode():
            return torch.sigmoid(self._logits(net, torch.from_numpy(x))).numpy()

    def parameter_count(self):
        return int(sum(v.size for v in self.state.values()))


class Mlp:
    """MLP à profondeur configurable pour l'une ou l'autre tâche."""

    def __init__(self, task, lr, dropout, relative=False, *,
                 hidden_units=16, depth=1, batch_size=BATCH_MLP, weight_decay=0.01):
        if depth not in (1, 2, 3) or hidden_units < 1:
            raise ValueError("depth must be 1, 2, or 3 and hidden_units must be positive")
        self.task, self.lr, self.dropout, self.relative = task, float(lr), float(dropout), bool(relative)
        self.hidden_units = hidden_units
        self.depth = depth
        self.batch_size = batch_size
        self.weight_decay = weight_decay
        self.curve, self.best_epoch, self.layers = [], 0, None

    def fit(self, d, valid=None, device="cpu", epochs=60, patience=8, seed=42, cols=None):
        import torch
        from torch import nn
        if cols is None:
            raise ValueError("préciser les colonnes de features")
        self.cols = list(cols)
        w = weights(d)
        x = _flat_x(d, self.cols, self.relative)
        self.scaler = StandardScaler().fit(x, sample_weight=w)
        x = self.scaler.transform(x)
        cls = self.task == "classification"
        y = d.drone_present.to_numpy(float) if cls else d.distance_m.to_numpy(float)
        torch.manual_seed(seed)
        hidden_units = getattr(self, "hidden_units", 16)
        batch_size = getattr(self, "batch_size", BATCH_MLP)
        weight_decay = getattr(self, "weight_decay", 0.01)
        layers = []
        inputs = x.shape[1]
        for _ in range(getattr(self, "depth", 1)):
            layers.extend((nn.Linear(inputs, hidden_units), nn.Dropout(self.dropout), nn.ReLU()))
            inputs = hidden_units
        layers.append(nn.Linear(inputs, 1))
        net = nn.Sequential(*layers).to(device)
        optim = torch.optim.AdamW(net.parameters(), lr=self.lr, weight_decay=weight_decay)
        criterion = nn.BCEWithLogitsLoss(reduction="none") if cls else nn.SmoothL1Loss(reduction="none")
        tx = torch.as_tensor(x, dtype=torch.float32, device=device)
        ty = torch.as_tensor(y, dtype=torch.float32, device=device)
        tw = torch.as_tensor(w / w.mean(), dtype=torch.float32, device=device)
        if valid is not None:
            vx = torch.as_tensor(self.scaler.transform(_flat_x(valid, self.cols, self.relative)),
                                 dtype=torch.float32, device=device)
            vy = torch.as_tensor(valid.drone_present.to_numpy(float) if cls else valid.distance_m.to_numpy(float),
                                 device=device)
            vw = torch.as_tensor(weights(valid), dtype=torch.float32, device=device)
        best = np.inf
        for epoch in range(1, epochs + 1):
            net.train()
            for idx in torch.randperm(len(y), device=device).split(batch_size):
                optim.zero_grad()
                (criterion(net(tx[idx]).flatten(), ty[idx]) * tw[idx]).mean().backward()
                optim.step()
            net.eval()
            with torch.no_grad():
                tp = net(tx).flatten()
                row = {"epoch": epoch, "train_loss": float((criterion(tp, ty) * tw).mean())}
                if cls:
                    row["train_accuracy"] = float((((tp >= 0) == ty.bool()).float() * tw).mean())
                else:
                    row["train_mae"] = float((abs(tp - ty) * tw).mean())
                score = row["train_loss"]
                if valid is not None:
                    vp = net(vx).flatten()
                    score = float((criterion(vp, vy) * vw).sum() / vw.sum())
                    row.update(val_loss=score, **({"val_accuracy": float((((vp >= 0) == vy.bool()).float() * vw).sum() / vw.sum())}
                                                  if cls else {"val_mae": float((abs(vp - vy) * vw).sum() / vw.sum())}))
            self.curve.append(row)
            if not np.isfinite(score):
                raise ValueError("loss non finie")
            if valid is None or score < best - 1e-6:
                best, self.best_epoch = score, epoch
                self.layers = [(l.weight.detach().cpu().numpy().copy(), l.bias.detach().cpu().numpy().copy())
                               for l in net if isinstance(l, nn.Linear)]
            elif epoch - self.best_epoch >= patience:
                break
        return self

    def predict(self, d, *, bounded=True):
        x = self.scaler.transform(_flat_x(d, self.cols, self.relative))
        for i, (w, b) in enumerate(self.layers):
            x = x @ w.T + b
            if i < len(self.layers) - 1:
                x = np.maximum(0, x)
        p = x.ravel()
        if self.task == "classification":
            return 1 / (1 + np.exp(-np.clip(p, -60, 60)))
        return np.clip(p, 1.0, 5.0) if bounded else p

    def parameter_count(self):
        return int(sum(w.size + b.size for w, b in self.layers))


class Linear:
    """Baseline : logistique (détection) ou ridge (distance)."""

    def __init__(self, task, kind, relative=False):
        if (task == "classification") != (kind == "logistic"):
            raise ValueError(f"{kind} ne convient pas à la tâche {task}")
        self.task, self.kind, self.relative = task, kind, bool(relative)
        self.curve, self.best_epoch = [], 0

    def fit(self, d, valid=None, device="cpu", epochs=0, patience=0, seed=0, cols=None):
        if cols is None:
            raise ValueError("préciser les colonnes de features")
        self.cols = list(cols)
        w = weights(d)
        x = _flat_x(d, self.cols, self.relative)
        self.scaler = StandardScaler().fit(x, sample_weight=w)
        cls = self.task == "classification"
        y = d.drone_present.to_numpy(int) if cls else d.distance_m.to_numpy(float)
        self.estimator = (LogisticRegression(C=1.0, max_iter=1000) if cls else Ridge(alpha=1.0))
        self.estimator.fit(self.scaler.transform(x), y, sample_weight=w)
        return self

    def predict(self, d, *, bounded=True):
        x = self.scaler.transform(_flat_x(d, self.cols, self.relative))
        if self.task == "classification":
            return self.estimator.predict_proba(x)[:, 1]
        return np.clip(self.estimator.predict(x), 1.0, 5.0) if bounded else self.estimator.predict(x)

    def parameter_count(self):
        return int(np.size(self.estimator.coef_) + np.size(self.estimator.intercept_))


class Constant:
    """Référence distance : toujours 3 m."""
    task = "distance"
    curve, best_epoch = [], 0

    def fit(self, d, valid=None, **kwargs):
        return self

    def predict(self, d, *, bounded=True):
        return np.full(len(d), 3.0)

    def parameter_count(self):
        return 0


def build(task, name, lr=None, dropout=None, relative=False, *, hidden_units=16, depth=1,
          batch_size=BATCH_MLP, weight_decay=0.01):
    """Construit un modèle ; lr/dropout par défaut = valeurs gelées de l'HPO."""
    frozen = FROZEN.get((task, name), dict(lr=3e-3, dropout=0.15))
    lr = frozen["lr"] if lr is None else float(lr)
    dropout = frozen["dropout"] if dropout is None else float(dropout)
    if name == "cnn":
        return CnnPresence(lr, dropout)  # relatif par conception, sans option
    if name == "mlp":
        return Mlp(task, lr, dropout, relative, hidden_units=hidden_units, depth=depth,
                   batch_size=batch_size, weight_decay=weight_decay)
    if name == "logistic":
        return Linear("classification", "logistic", relative)
    if name == "ridge":
        return Linear("distance", "ridge", relative)
    if name == "constant":
        return Constant()
    raise ValueError(f"modèle inconnu : {name!r} pour {task!r}")


# ---------------------------------------------------------------- données & métriques

def load(cache):
    """Lit le parquet et applique les contrôles d'intégrité."""
    d = pd.read_parquet(cache)
    missing = [c for c in KEYS if c not in d]
    if missing:
        raise ValueError(f"colonnes manquantes : {missing}")
    legacy = d.split.eq("dev").fillna(False)
    if legacy.any():
        if "fold" not in d:
            raise ValueError("ancienne partition dev sans colonne fold")
        folds = pd.to_numeric(d.loc[legacy, "fold"], errors="coerce")
        if not np.isfinite(folds).all() or (folds % 1 != 0).any():
            raise ValueError("plis de développement invalides")
        d.loc[legacy, "split"] = np.where(folds.eq(0), "validation", "train")
    ids = [c for c in KEYS if c != "distance_m"]  # distance_m est NaN pour les négatives
    if d[ids].isna().any().any() or not d.split.isin(["train", "validation", "test", "excluded"]).all():
        raise ValueError("identifiants, split ou étiquettes invalides")
    if (d.groupby("sample_id")[["group_id", "device_id", "drone_present", "distance_m"]].nunique(dropna=False) > 1).any().any():
        raise ValueError("métadonnées incohérentes au sein d'une prise")
    if (d.groupby("group_id").split.nunique() > 1).any():
        raise ValueError("un groupe temporel traverse plusieurs partitions")
    if d.loc[d.drone_present, "distance_m"].isna().any() or d.loc[~d.drone_present, "distance_m"].notna().any():
        raise ValueError("présence et distance incohérentes")
    return d


def task_frame(d, task):
    """La distance n'apprend que sur les présents à 1-5 m (la prise à 0,1 m reste
    disponible pour la détection, hors plage pour la régression)."""
    return d[d.drone_present & d.distance_m.between(1, 5)].copy() if task == "distance" else d.copy()


def metrics(d, task):
    pred, w = d.pred.to_numpy(), weights(d)
    out = dict(takes=int(d.sample_id.nunique()), windows=len(d))
    if task == "distance":
        out.update(mae_m=float(mean_absolute_error(d.distance_m, pred, sample_weight=w)),
                   bias_m=float(np.average(pred - d.distance_m, weights=w)))
    else:
        y, p = d.drone_present.to_numpy(), pred >= 0.5
        out.update(accuracy=float(accuracy_score(y, p, sample_weight=w)),
                   balanced_accuracy=float(balanced_accuracy_score(y, p, sample_weight=w)),
                   precision=float(precision_score(y, p, sample_weight=w, zero_division=0)),
                   recall=float(recall_score(y, p, sample_weight=w, zero_division=0)))
    return out


def report(d, pred, task):
    d = d.assign(pred=np.asarray(pred))
    out = {"overall": metrics(d, task), "by_device": {str(k): metrics(v, task) for k, v in d.groupby("device_id")}}
    if task == "distance":
        out["by_distance"] = {str(k): metrics(v, task) for k, v in d.groupby("distance_m")}
    return out


def selection_metric(task):
    return "mae_m" if task == "distance" else "balanced_accuracy"


# ---------------------------------------------------------------- expérience complète (étapes 02/03)

def plot_curves(out, rows, task):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if not rows:
        return
    metric = "val_accuracy" if task == "classification" else "val_mae"
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    epochs = [r["epoch"] for r in rows]
    axes[0].plot(epochs, [r["train_loss"] for r in rows], label="Train")
    axes[0].plot(epochs, [r["val_loss"] for r in rows], "--", label="Validation")
    axes[1].plot(epochs, [r[metric] for r in rows])
    axes[0].set(xlabel="Époque", title="Loss pondérée par prise")
    axes[0].legend(fontsize=8)
    axes[1].set(xlabel="Époque", title=metric)
    fig.savefig(out / "learning-curves.png")
    plt.close(fig)


def experiment(task, a):
    """Entraîne une fois, sélectionne sur la validation et évalue le holdout."""
    out = Path(a.out) / a.name
    if (out / "config.json").is_file():
        raise SystemExit(f"{out} existe déjà : choisir un autre --name.")
    frame = task_frame(load(a.input), task)
    if a.model == "cnn" and "logfft" not in frame:
        raise SystemExit("le modèle cnn exige la colonne 'logfft'. Relancer l'étape 01.")
    train, valid, test = (frame[frame.split == split] for split in ("train", "validation", "test"))
    if train.empty or valid.empty or test.empty:
        raise SystemExit("il faut des partitions train, validation et test non vides.")
    if task == "classification" and train.drone_present.nunique() != 2:
        raise SystemExit("l'entraînement doit contenir les deux classes.")
    # Hyperparamètres : valeurs gelées de l'HPO sauf surcharge explicite au CLI.
    frozen = FROZEN.get((task, a.model), dict(lr=3e-3, dropout=0.15))
    lr = frozen["lr"] if a.lr is None else float(a.lr)
    dropout = frozen["dropout"] if a.dropout is None else float(a.dropout)
    cols = None if a.model in ("cnn", "constant") else a.resolve_features(a.features)
    if cols and not set(cols).issubset(frame):
        raise SystemExit("cache incomplet pour les features demandées. Relancer l'étape 01.")
    model = build(task, a.model, lr, dropout, a.relative,
                  hidden_units=getattr(a, "hidden_units", 16), depth=getattr(a, "depth", 1),
                  batch_size=getattr(a, "batch_size", BATCH_MLP),
                  weight_decay=getattr(a, "weight_decay", 0.01))
    model.fit(train, valid, device=a.device, epochs=a.epochs, patience=a.patience, seed=a.seed, cols=cols)
    validation = report(valid, model.predict(valid), task)
    test_report = report(test, model.predict(test), task)
    if task == "distance":
        test_report["unbounded"] = metrics(test.assign(pred=model.predict(test, bounded=False)), task)

    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "model.joblib")
    best_epoch = getattr(model, "best_epoch", None)
    (out / "curves.json").write_text(json.dumps({"training": model.curve, "best_epoch": best_epoch}, indent=2))
    config = dict(task=task, model=a.model, cache=Path(a.input).name, rate=a.rate,
                  features="logfft,rms" if a.model == "cnn" else a.features,
                  columns=cols, lr=lr, dropout=dropout,
                  relative=True if a.model == "cnn" else bool(a.relative),
                  epochs=a.epochs, best_epoch=best_epoch, seed=a.seed, device=a.device,
                  parameters=model.parameter_count(), validation=validation["overall"])
    if a.model == "mlp":
        config.update(depth=model.depth, hidden_units=model.hidden_units,
                      batch_size=model.batch_size, weight_decay=model.weight_decay)
    (out / "config.json").write_text(json.dumps(config, indent=2, allow_nan=False) + "\n")
    (out / "metrics.json").write_text(json.dumps(
        {"task": task, "model": a.model, "cache": Path(a.input).name, "validation": validation,
         "test": test_report,
         "scope": "Holdout groupé de la même campagne ; seuil 0.5, pas de lissage ni hystérésis."},
        indent=2, allow_nan=False) + "\n")
    plot_curves(out, model.curve, task)
    metric = selection_metric(task)
    print(f"{task}/{a.model} : validation {metric} = {validation['overall'][metric]:.4f} ; "
          f"holdout {metric} = {test_report['overall'][metric]:.4f} -> {out}")
