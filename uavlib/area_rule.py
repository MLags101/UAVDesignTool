"""Slender-body wave drag from a cross-sectional area distribution.

The supersonic area rule says zero-lift wave drag depends on how the
cross-sectional area S(x) varies along the body. For a smooth distribution that
starts and ends with zero slope (von Karman / Ward slender-body theory)::

    D/q = -1/(2 pi) * int int S''(x1) S''(x2) ln|x1 - x2| dx1 dx2

With x = l/2 (1 - cos t) and S'(x) = sum a_n sin(n t) this reduces to
D/q = pi/4 * sum n a_n^2 (the Eminton-Lord form), which is what is evaluated
here. The Sears-Haack body, S = S_max sin^3 t, is the minimum-drag shape for a
given length and volume; its single term gives D/q = 9 pi/2 (S_max/l)^2.

Cuts are normal to the axis (the Mach 1 area rule). Higher Mach numbers are
handled by an empirical correction in :mod:`uavlib.supersonic`.
"""

import math


def sears_haack_dq(max_area, length):
    """Wave drag D/q (m^2) of the Sears-Haack body with this maximum area and length."""
    if max_area <= 0 or length <= 0:
        raise ValueError("Maximum area and length must be positive.")
    return 4.5 * math.pi * (max_area / length) ** 2


def sears_haack_area(x, length, max_area):
    """Sears-Haack cross-sectional area at station x."""
    xi = min(max(x / length, 0.0), 1.0)
    return max_area * (4.0 * xi * (1.0 - xi)) ** 1.5


def sears_haack_volume(length, max_area):
    return 3.0 * math.pi * length * max_area / 16.0


def _validate(xs, areas):
    if len(xs) != len(areas) or len(xs) < 3:
        raise ValueError("Need at least three (x, area) stations.")
    if any(b <= a for a, b in zip(xs, xs[1:])):
        raise ValueError("Stations must be strictly increasing in x.")
    if any(a < 0 or not math.isfinite(a) for a in list(areas) + list(xs)):
        raise ValueError("Areas must be finite and non-negative.")


def pchip_slopes(xs, ys):
    """Fritsch-Carlson monotone cubic slopes: smooth, and no overshoot between stations."""
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    delta = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    d = [0.0] * n
    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            d[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])
    for i, j in ((0, 0), (n - 1, n - 2)):
        k = 1 if i == 0 else n - 3
        if n == 2:
            d[i] = delta[0]
            continue
        hk, hj = (h[0], h[1]) if i == 0 else (h[-1], h[-2])
        dk, dj = (delta[0], delta[1]) if i == 0 else (delta[-1], delta[-2])
        value = ((2 * hk + hj) * dk - hk * dj) / (hk + hj)
        if value * dk <= 0:
            value = 0.0
        elif dk * dj <= 0 and abs(value) > abs(3 * dk):
            value = 3 * dk
        d[i] = value
    return d


def pchip_derivative(xs, ys, slopes, x):
    """dS/dx of the monotone cubic at x."""
    j = min(max(_index(xs, x), 0), len(xs) - 2)
    h = xs[j + 1] - xs[j]
    t = (x - xs[j]) / h
    dh00 = (6 * t * t - 6 * t) / h
    dh10 = 3 * t * t - 4 * t + 1
    dh01 = (-6 * t * t + 6 * t) / h
    dh11 = 3 * t * t - 2 * t
    return dh00 * ys[j] + dh10 * slopes[j] + dh01 * ys[j + 1] + dh11 * slopes[j + 1]


def _index(xs, x):
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    return lo


def fourier_coefficients(xs, areas, terms=40, quad=720):
    """Coefficients a_n of S'(x) = sum a_n sin(n t), x = x0 + l/2 (1 - cos t)."""
    _validate(xs, areas)
    x0, length = xs[0], xs[-1] - xs[0]
    slopes = pchip_slopes(xs, areas)
    h = math.pi / quad
    thetas = [(i + 0.5) * h for i in range(quad)]
    values = [pchip_derivative(xs, areas, slopes, x0 + 0.5 * length * (1.0 - math.cos(t)))
              for t in thetas]
    return [2.0 / math.pi * h * sum(v * math.sin(n * t) for v, t in zip(values, thetas))
            for n in range(1, terms + 1)]


def wave_drag_dq(xs, areas, terms=40):
    """Zero-lift wave drag D/q (m^2) of an area distribution at Mach 1 cuts.

    The distribution should close (zero area slope at both ends, or a base
    filled by the exhaust); a blunt end violates slender-body theory.
    """
    coefficients = fourier_coefficients(xs, areas, terms)
    return math.pi / 4.0 * sum(n * a * a for n, a in enumerate(coefficients, start=1))


def equivalent_sears_haack(xs, areas):
    """Sears-Haack bodies with the same length and either the same maximum area or volume."""
    length = xs[-1] - xs[0]
    max_area = max(areas)
    volume = sum(0.5 * (a + b) * (x2 - x1) for a, b, x1, x2 in zip(areas, areas[1:], xs, xs[1:]))
    same_volume_area = 16.0 * volume / (3.0 * math.pi * length)
    return {"length": length, "max_area": max_area, "volume": volume,
            "dq_same_max_area": sears_haack_dq(max_area, length),
            "dq_same_volume": sears_haack_dq(same_volume_area, length),
            "max_area_same_volume": same_volume_area}
