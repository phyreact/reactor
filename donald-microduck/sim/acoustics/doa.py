#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Four-microphone planar direction estimator.

Accumulates PHAT cross spectra with fast and slow exponential averages,
weights frequency bins by coherence, and solves six pairwise delays with
least squares. Delay closure and residual checks detect inconsistent input.

Coordinates: zero degrees is +X, counterclockwise is positive, and
 tau_ij = d_j - d_i for arrival delays d. Elevation magnitude can be inferred
from the projected direction norm, but a planar array cannot resolve its sign.
Uncertainty estimates come from synthetic-signal calibration, not field tests.
This module uses NumPy and performs no device I/O.
"""
import math

import numpy as np

# Array geometry and signal parameters.
SR = 16000
C_SOUND = 343.0
# Square array coordinates in metres.
MIC_XY = np.array([[0.0333, -0.0333],
                   [0.0333, 0.0333],
                   [-0.0333, 0.0333],
                   [-0.0333, -0.0333]])
NMIC = len(MIC_XY)

NFFT = 512
HOP = NFFT // 2           # 50% overlap
HOP_MS = HOP / SR * 1000.0

# Restrict the band to reduce spatial aliasing: f <= c / (2d).
# The 94.2 mm diagonal gives a limit of about 1821 Hz.

FLO, FHI = 300, 1800

# Time constants in milliseconds; alpha = exp(-hop / tau).

TAU_FAST_MS = 60.0        # Tracks moving sources
TAU_SLOW_MS = 400.0       # Longer averaging for stationary sources
# Select the fast estimate when disagreement exceeds joint uncertainty.
K_MOVE = 3.0

# Search GCC peaks near the SRP prediction to reduce grating-lobe ambiguity.

SEARCH_US = 80.0
REFINE_US = 0.5           # Local refinement step

AZ_STEP = 2               # Display and initialization grid; final direction uses least squares.
AZ = np.arange(0, 360, AZ_STEP)

PAIRS = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
NPAIR = len(PAIRS)
PAIR_NAMES = ["Mic%d−Mic%d" % (i, j) for i, j in PAIRS]
PAIR_D = np.array([MIC_XY[i] - MIC_XY[j] for i, j in PAIRS])          # 6 x 2
PAIR_MAX_US = [float(np.hypot(*d) / C_SOUND * 1e6) for d in PAIR_D]

# Delay closure: tau_ij + tau_jk = tau_ik for each microphone triple.
# Closure does not require a far-field plane-wave assumption.
TRI = [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]
_PIDX = {p: k for k, p in enumerate(PAIRS)}
TRI_IDX = [(_PIDX[(a, b)], _PIDX[(b, c)], _PIDX[(a, c)]) for a, b, c in TRI]
TRI_NAMES = ["τ%d%d+τ%d%d−τ%d%d" % (a, b, b, c, a, c) for a, b, c in TRI]

WIN = np.hanning(NFFT).astype(np.float32)
_freqs = np.fft.rfftfreq(NFFT, 1.0 / SR)
BAND = (_freqs >= FLO) & (_freqs <= FHI)
FB = _freqs[BAND]                                                     # B
NBIN = len(FB)

# Predicted pairwise delay in seconds for each candidate direction.
_U = np.stack([np.cos(np.deg2rad(AZ)), np.sin(np.deg2rad(AZ))])        # 2 x C
TAU_TH = (PAIR_D @ _U) / C_SOUND                                       # 6 x C
# Pairwise SRP cross terms: 2 Re sum_p C_p exp(-j 2 pi f tau_p).
#   2·Re Σ_p C_p(b)·e^{-j2πf_b τ_p(c)}     （C_p = X_i conj(X_j) = e^{j2πf τ_ij}）
PSTEER = np.exp(-2j * np.pi * FB[:, None, None] * TAU_TH[None, :, :])  # B x 6 x C

# Global GCC grid includes the maximum diagonal delay.
TAU_US = np.arange(-320.0, 320.1, 8.0)
GCC_K = np.exp(-2j * np.pi * FB[:, None] * (TAU_US[None, :] * 1e-6))   # B x T
# Local delay-refinement steering kernel.
DELTA_US = np.arange(-SEARCH_US, SEARCH_US + 1e-9, REFINE_US)
REFINE_K = np.exp(-2j * np.pi * FB[:, None] * (DELTA_US[None, :] * 1e-6))  # B x D

# The square array has an isotropic pairwise Gram matrix.

_GRAM = PAIR_D.T @ PAIR_D
_GRAM_INV = np.linalg.inv(_GRAM)
# Convert delay noise in microseconds to angular uncertainty.
SIGMA_DEG_PER_US = math.degrees(1e-6 * C_SOUND * math.sqrt(_GRAM_INV[0, 0]))
SIGMA_TAU_FLOOR_US = 0.05

DF = SR / NFFT                     # Frequency-bin spacing for the CRLB integral
_CRLB_F2 = (2 * math.pi) ** 2 * 2.0 * (FB ** 2) * DF     # Per-bin information factor

# Estimate uncertainty from coherence, not from residuals.
#
# Residuals measure model mismatch and omit noise in the signal subspace.

#
# The coherence-based CRLB depends on bandwidth and integration time.
#     var(τ̂) = 1 / ( 8π² · T · Σ_b Δf · f_b² · γ_b²/(1−γ_b²) )

# PHAT whitening

# Synthetic-signal calibration supplies the efficiency factor below.
#   SNR      20    14    10     6     3     0  dB

# This factor covers algorithm efficiency, not room or microphone mismatch.

SIGMA_EFFICIENCY = 1.47

# Output validity gates.

#

#
# Combine independent checks; reject the result when any gate fails.

GATE_SIGMA_DEG = 15.0      # Upper practical angular-uncertainty limit
GATE_UMAG = (0.20, 1.25)   # Projected direction norm equals cos(elevation)
GATE_MISFIT_US = 25.0      # Model-mismatch limit
GATE_CLOSURE_US = 60.0     # Delay-closure limit
GATE_PEAK_RATIO = 0.15     # Loose contrast gate; residual checks also reject inconsistent input.

def theory_us(deg, elev_deg=0.0):
    """Return six far-field pairwise delays in microseconds.

    Elevation scales horizontal delays by cos(elevation)."""
    u = np.array([math.cos(math.radians(deg)), math.sin(math.radians(deg))])
    return (PAIR_D @ u) / C_SOUND * 1e6 * math.cos(math.radians(elev_deg))

def wrap180(d):
    """Wrap angular differences to [-180, 180)."""
    return (np.asarray(d, dtype=float) + 180.0) % 360.0 - 180.0

def _peak_parab(y, x0, dx, circular=False):
    """Interpolate a sampled peak with a parabola; optionally wrap the grid."""
    n = len(y)
    k = int(np.argmax(y))
    if circular:
        i0, i2 = (k - 1) % n, (k + 1) % n
    else:
        if k == 0 or k == n - 1:
            return float(x0 + k * dx)
        i0, i2 = k - 1, k + 1
    y0, y1, y2 = float(y[i0]), float(y[k]), float(y[i2])
    den = y0 - 2 * y1 + y2
    d = 0.0 if den == 0 else max(-1.0, min(1.0, 0.5 * (y0 - y2) / den))
    return float(x0 + (k + d) * dx)

class DoaEstimator:
    """Consume four-channel frames and expose the current direction estimate.

    Call push(frame) with shape (NFFT, 4), then call result()."""

    def __init__(self, tau_fast_ms=TAU_FAST_MS, tau_slow_ms=TAU_SLOW_MS):
        self.a_fast = math.exp(-HOP_MS / tau_fast_ms)
        self.a_slow = math.exp(-HOP_MS / tau_slow_ms)
        # Wait two slow time constants before applying coherence weights.
        self.warm_need = int(math.ceil(2 * tau_slow_ms / HOP_MS))
        self.reset()

    def reset(self):
        self.n = 0
        self.c_fast = np.zeros((NPAIR, NBIN), dtype=np.complex128)
        self.c_slow = np.zeros((NPAIR, NBIN), dtype=np.complex128)
        self.last = None

    # Input accumulation.
    def push(self, frame):
        """Accumulate one (NFFT, 4) frame; solving is deferred to result()."""
        x = np.asarray(frame, dtype=np.float64)
        X = np.fft.rfft(x * WIN[:, None], axis=0)[BAND]          # B x 4
        X = X / (np.abs(X) + 1e-12)                              # PHAT whitening
        cur = np.stack([X[:, i] * np.conj(X[:, j]) for i, j in PAIRS])  # 6 x B
        if self.n == 0:
            self.c_fast[:] = cur
            self.c_slow[:] = cur
        else:
            self.c_fast = self.a_fast * self.c_fast + (1 - self.a_fast) * cur
            self.c_slow = self.a_slow * self.c_slow + (1 - self.a_slow) * cur
        self.n += 1

    # Direction estimation.
    def _weights(self):
        """Return normalized weights, raw information weights, and a validity flag.

        Coherence weights use gamma^2 / (1-gamma^2). Before warm-up,
        use equal normalized weights and retain raw weights for the CRLB."""
        g = np.abs(self.c_slow).mean(axis=0)
        g = np.clip(g, 0.0, 0.9999)
        raw = g ** 2 / (1.0 - g ** 2)
        if self.n < self.warm_need:
            return np.ones(NBIN), raw, False
        s = raw.sum()
        if not np.isfinite(s) or s <= 0:
            return np.ones(NBIN), raw, False
        w = raw / s * NBIN
        # Cap each bin at ten times the mean to limit narrow-band interference.
        return np.minimum(w, 10.0), raw, True

    def _sigma_tau_us(self, w_raw, alpha):
        """Estimate delay uncertainty from coherence and effective EMA duration.

        The equivalent independent sample count is (1+alpha)/(1-alpha)."""
        n_eff = (1.0 + alpha) / (1.0 - alpha)
        t_int = n_eff * HOP / SR
        info = t_int * float(np.sum(_CRLB_F2 * w_raw))
        if not np.isfinite(info) or info <= 0:
            return float("inf")
        return max(SIGMA_EFFICIENCY / math.sqrt(info) * 1e6,
                   SIGMA_TAU_FLOOR_US)

    # Suppress spurious complex-matmul floating-point flags in NumPy 2.0.2.

    # Downstream finite-value checks still reject invalid numerical results.
    _NPERR = dict(divide="ignore", over="ignore", invalid="ignore")

    def _srp(self, C, w):
        """Compute the SRP map from accumulated cross spectra."""
        cw = C * w[None, :]                                      # 6 x B
        with np.errstate(**self._NPERR):
            return 2.0 * np.real(np.einsum("pb,bpc->c", cw, PSTEER))

    def _tdoa_global(self, C, w):
        """Find unconstrained pairwise GCC peaks for closure diagnostics."""
        cw = C * w[None, :]
        with np.errstate(**self._NPERR):
            g = np.real(cw @ GCC_K)                              # 6 x T
        gmax = np.abs(g).max(axis=1, keepdims=True)
        gn = g / np.where(gmax > 0, gmax, 1.0)
        tau = np.array([_peak_parab(row, TAU_US[0], TAU_US[1] - TAU_US[0])
                        for row in g])
        return tau, gn

    def _tdoa_local(self, C, w, tau_center_us):
        """Refine GCC peaks near predicted delays to reduce phase ambiguity."""
        ph = np.exp(-2j * np.pi * FB[None, :] * (tau_center_us[:, None] * 1e-6))
        cw = C * w[None, :] * ph                                 # 6 x B
        with np.errstate(**self._NPERR):
            g = np.real(cw @ REFINE_K)                           # 6 x D
        return np.array([tau_center_us[p]
                         + _peak_parab(g[p], DELTA_US[0], REFINE_US)
                         for p in range(NPAIR)])

    def _solve(self, tau_us):
        """Fit six delays to a plane-wave direction.

        Return azimuth, projected direction norm, direction vector and residuals."""
        b = C_SOUND * (tau_us * 1e-6)                            # Six pairwise path differences in metres
        u, *_ = np.linalg.lstsq(PAIR_D, b, rcond=None)
        resid_us = (PAIR_D @ u - b) / C_SOUND * 1e6
        deg = math.degrees(math.atan2(u[1], u[0])) % 360.0
        return deg, float(np.hypot(*u)), u, resid_us

    def _sigma_deg(self, sigma_tau_us, umag):
        """Propagate delay uncertainty to azimuth for the isotropic array."""
        if umag <= 1e-6:
            return float("inf")
        return float(sigma_tau_us * SIGMA_DEG_PER_US / umag)

    def _one(self, C, w):
        """Solve one accumulator using global initialization and local refinement.

        Scale the SRP direction with the global fit norm before local search."""
        srp = self._srp(C, w)
        deg_srp = _peak_parab(srp, 0.0, AZ_STEP, circular=True) % 360.0
        tau_g, _ = self._tdoa_global(C, w)
        _, umag0, _, _ = self._solve(tau_g)
        # Use the global norm for scale and the combined SRP map for direction.
        scale = min(max(umag0, 0.05), 1.2)
        th = np.deg2rad(deg_srp)
        u_c = scale * np.array([math.cos(th), math.sin(th)])
        center = (PAIR_D @ u_c) / C_SOUND * 1e6
        tau_loc = self._tdoa_local(C, w, center)
        deg, umag, u, resid = self._solve(tau_loc)
        return {"deg": deg, "deg_srp": deg_srp, "umag": umag, "u": u,
                "srp": srp, "tau": tau_loc, "resid_us": resid}

    def result(self):
        """Return the current estimate, or None until enough frames are available."""
        if self.n < 2:
            return None
        w, w_raw, w_ok = self._weights()
        fast = self._one(self.c_fast, w)
        slow = self._one(self.c_slow, w)

        # Estimate fast and slow uncertainty from coherence and integration time.

        sig_tau_f = self._sigma_tau_us(w_raw, self.a_fast)
        sig_tau_s = self._sigma_tau_us(w_raw, self.a_slow)
        sig_f = self._sigma_deg(sig_tau_f, fast["umag"])
        sig_s = self._sigma_deg(sig_tau_s, slow["umag"])

        # Significant fast/slow disagreement indicates motion and slow-path lag.
        gap = float(abs(wrap180(fast["deg"] - slow["deg"])))
        joint = math.hypot(sig_f, sig_s)
        moving = bool(np.isfinite(joint) and gap > K_MOVE * joint)
        pick = fast if moving else slow

        # Independent diagnostics without knowledge of the true direction.
        # Global delay closure tests whether a consistent wavefront exists.
        tau_g, gcc_n = self._tdoa_global(self.c_slow, w)
        closure = np.array([tau_g[a] + tau_g[b] - tau_g[c]
                            for a, b, c in TRI_IDX])
        # Measure peak contrast outside the broad main lobe.

        # Exclude +/-60 degrees to sample sidelobes rather than the main lobe.
        srp = pick["srp"]
        k = int(np.argmax(srp))
        mask = np.abs(wrap180(AZ - AZ[k])) > 60.0
        second = float(srp[mask].max()) if mask.any() else 0.0
        rng = float(srp.max() - srp.min()) or 1.0
        peak_ratio = float((srp.max() - second) / rng)
        # Compare least-squares direction with the SRP peak.
        ls_gap = float(abs(wrap180(pick["deg"] - pick["deg_srp"])))

        # Reject estimates that fail any validity gate.
        sig_pick = sig_f if moving else sig_s
        misfit = float(np.sqrt(np.mean(pick["resid_us"] ** 2)))
        closure_max = float(np.abs(closure).max())
        why = []
        if not np.isfinite(sig_pick) or sig_pick > GATE_SIGMA_DEG:
            why.append("σ_θ %.0f°>%.0f" % (sig_pick, GATE_SIGMA_DEG))
        if not (GATE_UMAG[0] <= pick["umag"] <= GATE_UMAG[1]):
            why.append("|u| %.2f∉[%.2f,%.2f]"
                       % (pick["umag"], GATE_UMAG[0], GATE_UMAG[1]))
        if misfit > GATE_MISFIT_US:
            why.append('misfit %.0fµs>%.0f' % (misfit, GATE_MISFIT_US))
        if closure_max > GATE_CLOSURE_US:
            why.append('closure %.0fµs>%.0f' % (closure_max, GATE_CLOSURE_US))
        if peak_ratio < GATE_PEAK_RATIO:
            why.append('peak ratio %.2f<%.2f' % (peak_ratio, GATE_PEAK_RATIO))
        valid = not why

        self.last = {
            # When invalid, keep the angle only for plotting or debugging.
            # Display "No valid direction" with the rejection reasons.
            "valid": valid,
            "reject": why,
            "deg": round(pick["deg"], 2),
            "sigma_deg": (round(sig_f if moving else sig_s, 2)
                          if np.isfinite(sig_f if moving else sig_s) else None),
            "deg_fast": round(fast["deg"], 2),
            "deg_slow": round(slow["deg"], 2),
            "moving": moving,
            # Norms above one can indicate non-plane-wave input.
            "umag": round(pick["umag"], 3),
            "elev_deg": (round(math.degrees(math.acos(min(1.0, pick["umag"]))), 1)
                         if pick["umag"] > 0 else None),
            "sigma_tau_us": round(sig_tau_f if moving else sig_tau_s, 3),
            # Residual RMS describes model mismatch, not angular uncertainty.

            "misfit_us": round(misfit, 2),
            "resid_us": [round(float(v), 1) for v in pick["resid_us"]],
            "closure_us": [round(float(v), 1) for v in closure],
            "peak_ratio": round(peak_ratio, 3),
            "ls_srp_gap": round(ls_gap, 2),
            "weighted": w_ok,
            "n": self.n,
            "srp": pick["srp"],
            "gcc": gcc_n,
            "tau_us": pick["tau"],
            "tau_th_us": theory_us(pick["deg"]),
            "coh": np.abs(self.c_slow).mean(axis=1),
            "w": w,
        }
        return self.last
