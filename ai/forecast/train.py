"""Trains the expected-flow model and writes model.json for the control-room app.

    cd ai && python -m forecast.train            # about one minute

One gradient boosting model per target (scikit-learn HistGradientBoostingRegressor, Poisson loss:
https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html),
trained on the simulated history of simulate.py and evaluated on crossings it has never seen. The trees are
exported as plain arrays and re-read with the pure-Python predictor of model.py: the script refuses to write
the file unless the two give the same numbers.
"""
import argparse
import datetime
import json
import math

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import d2_tweedie_score, mean_absolute_error

from .features import FEATURES, TARGETS, WINDOW_S
from .model import MODEL_PATH, Model
from .simulate import simulate

PARAMS = dict(loss="poisson", learning_rate=0.1, max_iter=90, max_leaf_nodes=14, min_samples_leaf=60,
              l2_regularization=1.0, early_stopping=False, random_state=0)


def export_trees(est):
    """Fitted estimator -> {"baseline", "trees"} in the format of model.py.

    Reads the fitted trees from `_predictors` and `_baseline_prediction`: they are private attributes, which is
    why main() checks the exported model against est.predict before writing anything.
    """
    trees = []
    for (predictor,) in est._predictors:
        nodes = predictor.nodes
        leaf = nodes["is_leaf"].astype(bool)
        if nodes["is_categorical"].any():
            raise ValueError("categorical splits are not supported by model.py")
        trees.append({
            "f": [int(v) for v in np.where(leaf, 0, nodes["feature_idx"])],
            "t": [0 if lf else round(float(v), 6) for v, lf in zip(nodes["num_threshold"], leaf)],
            "l": [int(v) for v in np.where(leaf, -1, nodes["left"].astype(np.int64))],     # unsigned in scikit-learn
            "r": [int(v) for v in np.where(leaf, -1, nodes["right"].astype(np.int64))],
            "v": [float("%.6g" % v) if lf else 0 for v, lf in zip(nodes["value"], leaf)],
            "m": [int(v) for v in np.where(leaf, 0, nodes["missing_go_to_left"])],
        })
    return {"baseline": float(np.ravel(est._baseline_prediction)[0]), "trees": trees}


def naive_profile(X, y):
    """Baseline to beat: the average count of each quarter of an hour of the week, over all crossings."""
    hour, dow = FEATURES.index("hour"), FEATURES.index("dow")
    slot = lambda A: (A[:, dow] * 96 + np.floor(A[:, hour] * 4)).astype(int)
    table = np.bincount(slot(X), weights=y, minlength=7 * 96) / np.maximum(np.bincount(slot(X), minlength=7 * 96), 1)
    return lambda A: table[slot(A)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", type=int, default=240)
    ap.add_argument("--test-sites", type=int, default=60, help="crossings kept out of training, for the metrics")
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=MODEL_PATH)
    a = ap.parse_args()

    X, Y, site = simulate(a.sites, a.days, a.seed)
    test = site >= a.sites - a.test_sites
    print("rows: %d train, %d test (%d crossings never seen in training)" % ((~test).sum(), test.sum(), a.test_sites))
    data = {"version": 1, "trained_on": "simulated", "trained_at": datetime.date.today().isoformat(),
            "window_s": WINDOW_S, "sklearn": sklearn.__version__, "params": PARAMS,
            "sites_train": a.sites - a.test_sites, "sites_test": a.test_sites, "rows_train": int((~test).sum()),
            "features": list(FEATURES), "metrics": {}, "targets": {}}
    estimators = {}
    for k, target in enumerate(TARGETS):
        est = HistGradientBoostingRegressor(**PARAMS).fit(X[~test], Y[~test, k])
        pred, naive = est.predict(X[test]), naive_profile(X[~test], Y[~test, k])(X[test])
        data["metrics"][target] = {
            "mean": round(float(Y[test, k].mean()), 2),
            "mae": round(float(mean_absolute_error(Y[test, k], pred)), 2),
            "mae_naive": round(float(mean_absolute_error(Y[test, k], naive)), 2),
            "d2": round(float(d2_tweedie_score(Y[test, k], pred, power=1)), 3),
            "d2_naive": round(float(d2_tweedie_score(Y[test, k], np.maximum(naive, 1e-6), power=1)), 3),
        }
        data["targets"][target] = export_trees(est)
        estimators[target] = est
        print("%-9s %s" % (target, data["metrics"][target]))

    # the pure-Python predictor must reproduce scikit-learn on rows it has never seen, missing values included
    model = Model(data)
    rows = np.random.default_rng(1).choice(np.flatnonzero(test), 2000, replace=False)
    worst = 0.0
    for i in rows:
        mine = model.predict({name: None if math.isnan(v) else float(v) for name, v in zip(FEATURES, X[i])})
        for target, est in estimators.items():
            ref = float(est.predict(X[i:i + 1])[0])
            worst = max(worst, abs(mine[target] - ref) / max(ref, 1e-9))
    print("pure-Python predictor vs scikit-learn: worst relative difference %.2e on %d rows" % (worst, len(rows)))
    if worst > 1e-3:
        raise SystemExit("the exported model does not match scikit-learn: model.json not written")

    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")
    n_nodes = sum(len(t["l"]) for m in data["targets"].values() for t in m["trees"])
    print("written %s (%d trees, %d nodes)" % (a.out, sum(len(m["trees"]) for m in data["targets"].values()), n_nodes))


if __name__ == "__main__":
    main()
