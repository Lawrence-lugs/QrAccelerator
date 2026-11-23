# P7i diagnostic: scale-aligned SNR between captured oscaler_input (pre-scale)
# and the same-B reference.  Reads the capture files produced by tb_qracc_top
# when run with +cap_file=/workspaces/QrAccelerator/capdir/cap_B{b}.txt.
# Runs ONLY inside the container (verilator).  No product-code edits, no commits.
#
# Per B in {2,4,8}:
#   raw SNR       = 10*log10(var(ref)/var(ref - cap))
#   best scale s  = <cap,ref>/<cap,cap>   (least-squares, minimises ||s*cap-ref||)
#   best-scale SNR= 10*log10(var(ref)/var(ref - s*cap))
#   scale factor  = s
#   correlation   = corrcoef(cap, ref)
#
# If best-scale SNR > 8 dB, the raw values are correct and the failure is an
# output-scale mismatch (the -7..-8 dB failures).  Otherwise the values
# themselves are wrong.

import numpy as np
import os
import sys

CAP_DIR = "capdir"
REF_DIR = "tests/multibit_ref"
SAFE = "features_features.0_features.0.0_Conv_quant"
OUT_SHAPE = (1, 32, 16, 16)  # node output shape (N, C, H, W)
OUT_SIZE = int(np.prod(OUT_SHAPE))  # 8192

results = {}


def snr_db(expected, actual):
    expected = np.asarray(expected, dtype=np.float64).ravel()
    actual = np.asarray(actual, dtype=np.float64).ravel()
    var_ref = float(np.var(expected))
    var_err = float(np.var(expected - actual))
    if var_err <= 0:
        return float("inf")
    return 10.0 * np.log10(var_ref / var_err)


for b in (2, 4, 8):
    cap_path = os.path.join(CAP_DIR, f"cap_B{b}.txt")
    ref_path = os.path.join(REF_DIR, f"{SAFE}_B{b}.npy")

    print(f"===== B={b} =====")
    print(f"cap_file : {cap_path}")
    print(f"ref_file : {ref_path}")

    if not os.path.exists(cap_path):
        print("ERROR: capture file missing")
        results[b] = None
        continue

    cap_flat = np.loadtxt(cap_path, dtype=int)
    n_cap = int(cap_flat.size)
    print(f"capture lines: {n_cap}")

    if n_cap == 0:
        print("ERROR: capture file empty")
        results[b] = None
        continue

    if n_cap != OUT_SIZE:
        print(f"ERROR: element count {n_cap} does not match output size {OUT_SIZE}; "
              f"not reshaping to {OUT_SHAPE}")
        results[b] = (n_cap, None)
        continue

    cap = cap_flat.reshape(OUT_SHAPE).astype(np.float64)
    ref = np.load(ref_path).astype(np.float64)  # (N, C, H, W), no transpose
    if ref.shape != OUT_SHAPE:
        print(f"WARNING: ref shape {ref.shape} != {OUT_SHAPE}; flattening both")
        ref = ref.ravel()
        cap = cap.ravel()
    else:
        ref = ref.reshape(OUT_SHAPE)

    raw = snr_db(ref, cap)

    hw = cap.ravel()
    golden = ref.ravel()
    denom = float(np.sum(hw * hw))
    s = float(np.sum(hw * golden) / denom) if denom > 0 else float("nan")
    scaled = s * hw
    best = snr_db(golden, scaled)
    corr = float(np.corrcoef(hw, golden)[0, 1]) if n_cap > 1 else float("nan")

    print(f"raw SNR        : {raw:.4f} dB")
    print(f"best scale s   : {s:.6f}")
    print(f"best-scale SNR : {best:.4f} dB")
    print(f"correlation    : {corr:.6f}")
    print(f"best-scale SNR > 8 dB: {best > 8}")
    results[b] = (n_cap, raw, s, best, corr)

print("===== SUMMARY =====")
for b in (2, 4, 8):
    r = results.get(b)
    if r is None:
        print(f"B={b}: MISSING/EMPTY")
    elif r[1] is None:
        print(f"B={b}: count={r[0]} (mismatch, no reshape)")
    else:
        n_cap, raw, s, best, corr = r
        print(f"B={b}: lines={n_cap} raw={raw:.4f} dB s={s:.6f} best={best:.4f} dB corr={corr:.6f} >8dB={best > 8}")

sys.exit(0)
