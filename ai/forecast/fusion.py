"""Fusion of the model's expectation with the counts measured by the node. Standard library only.

Gamma-Poisson: a prior on a rate (mean `mu`, worth `strength` units of exposure); every measured window is a
Poisson count over an exposure, weighted down as it gets older. With no measurements the result is the prior;
with many it follows the node.
"""
from statistics import NormalDist

PRIOR_STRENGTH = 1.0        # default weight of the prior: one unit of exposure
HALF_LIFE_S = 1800.0        # a window 30 min old weighs half
SHRINK = 10.0               # counts of evidence needed before the node's own level outweighs the model
MIN_RATE = 1e-3


def gamma_quantile(shape, rate, p):
    """Quantile of a Gamma distribution, Wilson-Hilferty approximation (within a few % for shape >= 0.5)."""
    z = NormalDist().inv_cdf(p)
    k = max(shape, 1e-6)
    return max(0.0, k * (1 - 1 / (9 * k) + z / (3 * k ** 0.5)) ** 3) / rate


def posterior(mu, observations, strength=PRIOR_STRENGTH, half_life_s=HALF_LIFE_S, level=0.8):
    """Rate after seeing the node's counts.

    observations: [(count, exposure, age_s)]; the rate is in counts per unit of exposure.
    Returns {"mean", "lo", "hi", "weight"}; weight is the share of the estimate that comes from the node (0..1).
    """
    mu = max(mu, MIN_RATE)
    shape, rate = mu * strength, strength
    for count, exposure, age_s in observations:
        w = 0.5 ** (max(age_s, 0.0) / half_life_s)
        shape += w * count
        rate += w * exposure
    tail = (1 - level) / 2
    return {"mean": shape / rate, "lo": gamma_quantile(shape, rate, tail), "hi": gamma_quantile(shape, rate, 1 - tail),
            "weight": 1 - strength / rate}


def calibration(measured, expected, shrink=SHRINK, limits=(0.1, 10.0)):
    """How much this crossing differs from what its surroundings suggest: measured / expected, pulled towards 1
    while the counts are few. The model cannot know it (road layout, a school gate, the side the camera looks at)."""
    c = (measured + shrink) / (expected + shrink)
    return min(max(c, limits[0]), limits[1])

