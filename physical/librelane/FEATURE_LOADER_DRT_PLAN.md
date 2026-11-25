# Feature loader — why DRT starts at ~500k violations, and what to change

Status: the `feature_loader_40clean` 40 % / aspect 0.7 flow is **stopped**.
Run tag archived; nothing is running.

## 1. What the last two runs actually did

| | no repair | post-GPL repair (repair2, output buffering off) |
|---|---|---|
| instances | 317,879 | 344,574 (+26,223 "timing repair" + 318 input buffers + 359 cts) |
| cell area | 2,583,720 µm² | 2,796,361 µm² |
| GRT overflow | 0 | 0 |
| DRT iteration 0 | 331,464 | **486,257** |
| DRT progress | **0 at iteration 14** | 443 k → 431 k → 205 k → 185 k → 178 k → 173 k → 169 k → **167 k, plateau** |
| post-route slow WNS | **−43.9 ns** | +47.95 ns |

So the design *can* close: the un-repaired netlist routed to zero DRC. The repaired
netlist timings clean but never converges. Both outcomes are bad, and they are
symptoms of the same two defects below.

## 2. Root cause A — the east-edge pins have zero escape room

From `28-openroad-globalplacement/feature_loader.def`:

```
- data_o[0]    LAYER Metal3 ( -360 -100 ) ( 360 100 ) PLACED ( 3048855  534240 )
- data_o[2591] LAYER Metal3 ( -360 -100 ) ( 360 100 ) PLACED ( 3048855 1622460 )
```

* Die is **3049.215 × 2156.625 µm**.
* All **2,592** `data_o` pins are on **Metal3** (the horizontal layer), on the east edge.
* They occupy y = 534.24 … 1622.46 µm → a **contiguous 1088 µm band at 0.42 µm pitch**.
* Metal3 track pitch is **0.42 µm** → the pins consume **100 % of the Metal3 tracks**
  in that band, and **42 % of the edge height is completely unused** (533 µm dead
  at each end).

This is not a guess; it is exactly reproducible from LibreLane's placement maths
(`librelane/scripts/odbpy/io_place.py`):

```python
tracks_per_pin = floor(tracks / total_pin_count)      # 5131 // 2592 = 1
used_tracks    = tracks_per_pin * (N-1) + 1           # 2592
unused_tracks  = tracks - used_tracks                 # 2539, split evenly
```

`tracks_per_pin == 1` means **no free Metal3 track exists between any two adjacent
output pins** anywhere in that band. DRT therefore cannot jog, cannot detour around
a cell pin, and cannot break out of the band. The observed failure mode is exactly
this: **Metal2 shorts ~94 k and Metal2 spacing ~27 k persist across every DRT
iteration** while everything else slowly improves.

This is a hard geometric infeasibility, not a tuning problem.

### The knob

`tracks_per_pin` becomes 2 as soon as `tracks >= 2 × 2592 = 5184`, i.e.

```
H >= 5184 × 0.42 µm = 2177 µm
```

The current die is 2156.6 µm — **20 µm short**. One free Metal3 track between every
pin costs almost nothing in area and is the single highest-leverage change available.

Three free tracks (two lanes between pins) needs `H >= 3266 µm`.

`IO_PIN_V_THICKNESS_MULT` is *not* needed for this, and it is a trap: it is wired to
`--hor-width-mult` (LibreLane naming inversion), and it thickens the pin body rather
than creating gaps. Leave it at 1 and let `tracks_per_pin` do the work.

## 3. Root cause B — global routing leaves Metal3 at 76.5 %

`39-openroad-globalrouting`, adjustment 5 %:

```
Layer         Resource        Demand        Usage (%)    Overflow
Metal2         1670824        972459           58.20%     0
Metal3         2016868       1543118           76.51%     0
Metal4         1670824        417279           24.97%     0
Metal5         1993788        744533           37.34%     0
TopMetal1       247827         15859            6.40%     0
TopMetal2       126600         23748           18.76%     0
Total          7726731       3716996           48.11%     0
```

Total wire length 31.36 mm over 6.46 mm² of core. Globally there is plenty of room,
but **the router piles horizontal traffic onto Metal3 (76.5 %) while Metal5 sits at
37 %**, and vertical traffic onto Metal2 (58 %) while Metal4 sits at 25 %. Local
Metal3 saturation is what makes DRT's initial route explode.

`GRT_ADJUSTMENT: 0.05` is also the wrong direction: it tells GRT that capacity is
only 5 % lower than reality, so GRT packs guides right up to the limit. Overflows
were being *hidden*, not removed.

## 4. Why "2:1 wide" is the wrong reflex, and wider is actively harmful

For this block the east edge is the scarce resource, so:

* **Taller is better**: height *is* the output-pin edge. Wider shrinks it.
* **Taller is better again**: horizontal layers (Metal3/Metal5) carry 61 % of the
  demand, and horizontal run length scales with **width**. Narrowing the die
  shortens every eastward escape and every bus.
* Wider makes both problems worse on both axes.

The exception is Metal2/Metal4: they are vertical, so a much taller die pushes demand
onto Metal2. That is why the recommendation is "square-ish", not "extreme 2:1 tall".

## 5. Ranked strategies

Ordered by expected reduction in insertion-time DRT violations per hour of compute.
Cost is wall-clock on this machine.

### S1. Die height ≥ 2177 µm so `tracks_per_pin ≥ 2`  — do this first
* Cost: none (floorplan number). Verify in 30 min, before any DRT.
* Effect: removes a proven infeasibility. Expect the Metal2 short floor to drop by
  a large factor.
* Implementation: raise `FP_ASPECT_RATIO` and/or `FP_CORE_UTIL` until
  `H ≥ 2177 µm`. Square at 40 % util gives 2542 × 2542.

### S2. Rebalance GRT off Metal3/Metal2 onto Metal5/Metal4
* Cost: one run, config only.
* `GRT_LAYER_ADJUSTMENTS` derates per layer (order M1, M2, M3, M4, M5, TM1, TM2),
  positive = less capacity. e.g. `0.00 0.15 0.30 0.00 0.00 0.00 0.00` pushes traffic
  upward. Raising `GRT_ADJUSTMENT` from 0.05 toward 0.10-0.15 stops hiding overflow.
* Effect: target Metal3 ≤ 60 %. Watch that GRT still reports 0 overflow; if not, the
  die is genuinely short and S3 is required.

### S3. Utilization 40 % → 35 % (or 33 %)
* Cost: bigger die, one run.
* Effect: 16 % more whitespace for local detours. GRT says global capacity is fine,
  so this is the *secondary* lever — but it also raises H, which helps S1 for free.
* Detail: utilization is why the "too high" instinct is half right. It is not the
  global bottleneck; it is the local one.

### S4. Drop the post-GPL design repair for the geometry test
* Cost: none.
* Reasoning: at GPL the repaired *and* un-repaired designs both have +47.95 ns setup
  slack. The −43.9 ns only appeared **after routing**, on `addr_i[8] → flop` with
  fanout 109/169 nets. Repair "fixed" it by adding 26 k buffers between GPL and
  detailed placement, where they land in leftover gaps and create the hotspots that
  stop DRT converging.
* So: fix the routing (S1-S3) and the timing may recover on its own. If it does,
  the 26 k buffers disappear and so does the plateau.
* Keep `DESIGN_REPAIR_BUFFER_INPUT_PORTS: true` behaviour available — the 318 input
  buffers are cheap and target the real critical path.

### S5. Fewer, stronger buffers at synthesis
* Cost: one synthesis (≈1 h).
* 161,691 of 317,879 cells (**45 % of area**) are `sg13g2_buf_1`. The design is
  10 MHz — fanout 10 with the weakest buffer in the library is over-constrained.
* Try `SYNTH_BUFFER_CELL: sg13g2_buf_2/A/X` and `MAX_FANOUT_CONSTRAINT: 16`.
  Expect instance count and net count to fall noticeably, which cuts pin accesses
  (927 k of them) — the dominant Metal2 load.

### S6. Enable Metal1 routing (`RT_MIN_LAYER: Metal1`)
* Cost: one run, single line. High variance.
* Metal1 contributes **0** tracks today. Enabling it adds a whole horizontal layer,
  which is precisely what is saturated. Risk: Metal1 is the cell pin layer in
  sg13g2, so pin access and DRC may explode. Worth exactly one experiment.

### S7. Spread `data_o` across two edges, or split the macro
* Cost: high (pin order file, or a wrapper instantiating two 144-entry cores).
* East + north/south with 1296 pins each doubles the effective pitch and is the
  honest fix if 2592 pins on one edge cannot be made to work.
* Structural split (entries 0-143 / 144-287) duplicates only input buffering;
  each macro gets 1296 outputs. This mirrors the `output_scaler_group` decision.

### S8. Insert a second global placement after `RepairDesignPostGPL`
* Cost: custom flow step.
* If repair must stay, re-running GPL afterwards places those 26 k buffers
  congestion-aware instead of dropping them into gaps. This is the correct way to
  keep repair and still converge.

## 6. Recommended experiment sequence

**E1 — geometry only (do this now)**

```yaml
FP_CORE_UTIL: 35            # 40 -> 35
FP_ASPECT_RATIO: 1.0        # 0.7 -> 1.0  (2542 x 2717 um at 35 %)
PL_TARGET_DENSITY_PCT: 35
GRT_ADJUSTMENT: 0.10        # 0.05 -> 0.10
GRT_LAYER_ADJUSTMENTS: "0.00 0.15 0.30 0.00 0.00 0.00 0.00"
RUN_POST_GPL_DESIGN_REPAIR: false
DIODE_CELL: null
DRT_THREADS: 16
```

Pre-flight, **before** detailed routing (≈40 min, not 6 h):

1. stop after `Odb.CustomIOPlacement`, read the `data_o` pin ys and confirm the
   pitch is 0.84 µm and one Metal3 track is free between pins;
2. run to `OpenROAD.GlobalRouting`, confirm Metal3 ≤ 65 % and overflow 0.

Only then let DRT run, with `DRT_OPT_ITERS` capped so a bad start costs one hour
rather than eight.

**E2 — if Metal3 is still hot:** drop util to 30 % and aspect to 1.3
(2573 × 3345 µm, `tracks_per_pin = 3`, pitch 1.26 µm, two free tracks).

**E3 — if DRT still plateaus:** S5 (buffer cell / fanout) then S6 (Metal1).

**E4 — if 2592 pins on one edge remain the limit:** S7.

## 7. Pre-flight check (30 min, catches the problem before DRT)

After `Odb.CustomIOPlacement`, the DEF must show a `data_o` pin pitch of
0.84 µm (2 tracks) or 1.26 µm (3 tracks). If the pitch is 0.42 µm, **do not run
DRT** — the run cannot converge.

```powershell
$def = "<run>/26-odb-customioplacement/feature_loader.def"
$ys = (Select-String -Path $def -Pattern 'data_o\[\d+\].*\n.*PLACED' -AllMatches)
# easier: extract the PLACED y of every data_o pin and look at the min delta
```

Track budget to check by hand:

```
tracks            = floor(H_um / 0.42)
tracks_per_pin    = floor(tracks / 2592)
required H        = 2 * 2592 * 0.42 = 2177 um   (1 free track)
                  = 3 * 2592 * 0.42 = 3266 um   (2 free tracks)
```
