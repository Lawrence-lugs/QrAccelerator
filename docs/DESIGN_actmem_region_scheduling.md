# DESIGN — ACTMEM resident-region scheduling

Status: approved design direction; **R1/R2/R3 metadata implemented, R4-R5 pending.**
The scheduling unit is a **DAG-shaped resident region**, not a Concat view.

Implemented now:

* `TensorView`, `ResidentRegion`, `RegionPlan` metadata in `compile.py`;
* region entry/exit derivation from producers/consumers;
* Slice-view lifetime propagation and Concat group views;
* live-range peak over all live groups (MBV2 peak 49152 B);
* `traverse` readout decisions from region exits, replacing the
  next-consumer heuristic;
* deterministic recursive region splitting at legal comp-node boundaries,
  with protection against cutting a supported Concat group;
* compiler-only tests for the MBV2 DAG, entries/exits, views, budget, linear
  splitting, and group-preserving splitting.

Still pending:

* explicit per-group output bases and allocator reuse;
* RTL decode/use of the output-view CSR (R4).

This redesign replaces `DESIGN_internal_concat_actmem.md`.
It records two explicit decisions:

* regions may contain fanout and Concat joins (DAGs, not just strings);
* a region that exceeds the 256 kB ACTMEM budget is split into smaller feasible
  regions, rather than forcing the whole region external.

## 1. Intent

The compiler decides which producer–consumer subgraphs can execute entirely
on the accelerator.  Each such subgraph has an execution schedule, a layout
plan, and a proof that all tensors live at each execution point fit ACTMEM.

External/L2 remains the model for unsupported operations and storage overflow:
uncompilable nodes are executed externally, and the testbench L2 may be
rearranged.  ACTMEM, not the 2 MB testbench L2, is the physical memory budget.

A normal non-branching chain can still be described as one read-in followed by
one final readout.  The more general form is a DAG with one or more external
entry tensors and one or more external exit tensors.

## 2. Approach decision

| approach | evaluation |
|---|---|
| Concat-specific planning | Narrow: mixes an address-layout operation with scheduling and does not generalize to fanout, joins, or region splitting. Useful prototype, not the final abstraction. |
| **DAG resident regions** | **Chosen.** Separates scheduling, tensor views, and memory liveness; directly covers Slice/Concat, multi-entry and multi-exit cases. |
| Globally optimal scheduler | Better theoretical placement/traffic, but too complex and unnecessary for MBV2 now. Retreat to a deterministic legal-boundary search. |

A strictly single-entry/single-exit string was rejected: it forces unnecessary
external boundaries at every fanout or join.  Forcing the whole oversized
region external was also rejected: legal smaller regions may still fit.

## 3. Concepts and invariants

### 3.1 `ResidentRegion`

A connected DAG containing:

* compilable compute nodes;
* eligible zero-copy view nodes (`Slice`, supported channel `Concat`).

Fields:

```text
nodes                topologically ordered node ids
entry_tensors        inputs with no producer inside the region
exit_tensors         outputs needed outside, plus graph outputs
schedule             legal per-node order
live_ranges          tensor first-read .. last-use
memory_plan          per-slot base, stride, channel offset, bytes
peak_live_bytes      maximum bytes simultaneously live
supported / reason   eligibility result
```

A region is not a `Concat`.  A Concat may be a member of a region, and a
region may contain several Slice/Concat groups.  An unsupported ONNX node is
not a member and produces an external boundary instead.

### 3.2 `TensorView`

Per-tensor physical addressing, independent of scheduling:

```text
shape, base, pixel_stride, channel_offset, channel_stride
```

For a Slice consumer:

```text
address = parent_base + pixel*parent_channel_stride
        + slice_offset + c
```

For a supported channel Concat group:

```text
producer k: group_base + pixel*group_channels + input_offset_k + c
consumer:   group_base + pixel*group_channels + c
```

`Concat` is therefore a layout/view operation.  `Slice` and Concat never own
ACTMEM capacity: their backing slots do.

### 3.3 `RegionPlan`

The compiler-side artifact joining region, schedule, and layout:

```text
region, views, external_entries, external_exits,
node_commands, memory_plan, peak_live_bytes, fallback_reason
```

A `CommandPlan` is emitted only after a feasible `RegionPlan` exists.  No
partially valid region commands may be emitted.

## 4. Read-in/read-out definitions

Read-in and readout are properties of **boundary tensors**, not of particular
node types:

```text
entry: tensor producer is outside the region
exit:  tensor has a consumer outside the region or is a graph output
```

A DAG can therefore have several external inputs and several readouts.  A
consumer whose producer is internal reads from ACTMEM.  Intermediate
Slice/Concat values do not cause external readout merely because the Tensor
Operation opcode itself is unsupported.

Intermediate outputs with another external or graph-output consumer remain
readouts as well.  The `result_start_addr` for readout is the base of the
contiguous region output group backing that exit tensor.

`l2_mem_addr = 0` before every external readout remains mandatory: several exit
readouts overwrite the testbench output view rather than append invisibly.

## 5. Region formation

1. Build producer/consumer and shape relations for the selected graph range.
2. Form candidate connected DAGs from compilable nodes plus eligible view
   nodes.
3. Mark external entries where an input has no resident producer and exits at
   any external consumer or graph output.
4. Topologically schedule compute nodes.
5. Construct the tensor views and live ranges.
6. Compute the actual peak live bytes at every schedule point.
7. If feasible, emit node commands; otherwise split the candidate.

Unsupported operations create external producer outputs.  These are loaded as
post-operation tensors: if such a tensor is already sliced externally, load
the compact slice with channel stride `slice_channels`, offset 0, and no
`preserve_ifmap`.

## 6. Memory accounting

Physical ACTMEM: **262144 bytes**, byte-addressable.

At schedule point `k`:

```text
live(k) = { input/output/parent/group tensors whose first-read <= k <= last-use }
peak    = max_k sum(bytes(t) for t in live(k)) + reserved scratch bytes
```

The budget includes all of these simultaneously:

* the input group(s) being read;
* the output group(s) being written;
* parents retained for Slice/fanout;
* Concat groups;
* any other exits still awaiting readout;
* explicit reserved slots required by the implementation.

For a simple split/Concat block this is at least:

```text
bytes(parent) + bytes(concat_group) + bytes(consumer_output) + other_live
```

A 3x3 depthwise split cannot alias parent and Concat output: convolution reuse
means later windows still need the parent.  Separate slots are required.
One-dimensional/projection in-place placement may be added only after proving
window-safety.

A monotonically increasing `ofmap_start_addr` is an insufficient proof of
within-budget placement: dead parents must become reusable.  Use consumer
counts and last-use intervals, then first-fit with free ranges (or a measured
monotonic high-water fallback for the unrefactored compiler).

## 7. Splitting oversized regions

Use a deterministic bounded heuristic, not global optimization:

1. Evaluate the maximal candidate DAG.
2. If `peak > ACTMEM_BYTES`, pick a legal external boundary that eliminates or
   externalizes a large still-live group (edge between a group and its
   consumer is preferred).
3. Re-form internal subregions and evaluate liveness from scratch.
4. Stop when every subregion fits.
5. If a single compute operation or unavoidable live group cannot fit, fall
   back that operation/tensor externally.

The selected boundary must be a point that the controller can realize as an
output write followed by a later external read-in.  The fallback decision is
made before emitting any group writes; partially emitted Concat groups are not
allowed.

For large theoretical shapes, consider:

```text
256x32x32 = 262144 B
```

That single tensor consumes the entire ACTMEM.  Any live input plus output
therefore forces external fallback or a future streaming design.

## 8. Supported eligibility and fallback

### Supported internal view now

* channel-axis Slice of a resident parent;
* channel-axis Concat of compilable producers, same spatial shape, contiguous
  input offsets, base and stride representable, no unsafe alias.

### External fallback

* H/W-axis Concat;
* unknown/non-4D shape;
* non-uniform Concat spatial shape;
* non-compilable input producer;
* graph input, constant, or external output whose layout cannot be realized;
* unsafe aliasing;
* budget or address-width overflow;
* unhandled shape-changing operation between view and consumer.

If the parent of a Slice was unsupported, evicted, or externally produced,
there is no internal view: read the already-post-split tensor from L2
compactly.

## 9. Required RTL contracts after compiler refactor

Compiler addresses become explicit rather than inferred from sequential
`ofmap_start_addr` advancement:

* input stride/channel offset for parent views;
* output stride/channel offset for each device group;
* output base for each region output slot;
* readout base per exit group;
* optionally an explicit group/region identifier.

`CSR_REG_OUTPUT_VIEW` is only a first step.  It carries stride and channel
offset but has no RTL decode/use yet, and does not carry an arbitrary output
base or define reclaimable slots.  The compiler/RTL base-address interface is
still an open implementation item.

## 10. Migration plan

### Phase R1 — data model and current-command preservation

* introduce `TensorView`, `ResidentRegion`, `RegionPlan`;
* wrap the current Concat-specific planner as a layout provider, not a
  scheduler;
* normalize `readout` from region exits;
* preserve all MBV2 command-stream offsets (96 and 0/32/64) and gate results.

### Phase R2 — liveness and budget

* derive first-read/last-use from producer/consumer relations;
* compute peak live bytes for all groups at every point;
* add a deterministic allocator and reject unplaceable plans before emitting.

### Phase R3 — scheduling and split fallback

* partition maximal DAG candidates;
* implement legal-boundary splitting;
* add external post-split input handling and fanout/multiple-exit boundaries.

### Phase R4 — RTL group base/decode

* decode output-view CSR;
* drive per-group output base, pixel stride, and channel offset;
* update result/readout base to the emitted region plan;
* add allocation/free semantics compatible with controller state.

### Phase R5 — validation and cleanup

* MBV2 full multi-slice chain with poisoned L2 Concat data;
* fanout, multiple entry, multiple exit and Concat join tests;
* oversized DAG split, unavoidable external fallback, unsafe axis/shape;
* retire Concat-only names from planning APIs.

## 11. Compiler-only acceptance tests

1. **MBV2 DAG:** node0...split0/1/2...Concat...projection schedules as one
   region; splits have group stride 96, offsets 0/32/64; projection reads the
   group and no split is read out.
2. **Multi-exit DAG:** two external consumers/readouts for one producer group;
   every exit is scheduled and each L2 read starts at pointer 0.
3. **Fanout and join:** multiple consumers and Concat producers share a region;
   parent live until its last Slice consumer.
4. **Unsupported join producer:** if any Concat input was produced externally,
   choose explicit external fallback rather than issuing a wrong base/stride.
5. **Non-channel axis:** fallback.
6. **Capacity:** >256 kB candidate splits at a legal boundary; an irreducible
   oversized op/tensor goes external.
7. **Split after unsupported:** compact stride equals sliced channels, offset
   zero, no preserve.
8. **Backward compatibility:** existing 3/4/5/7-node command decisions and
   current RTL regressions remain unchanged until R4 intentionally changes
   output bases.

## 12. Non-goals

* globally optimal register allocation or L2 traffic minimization;
* globally optimal op fusion;
* streaming partial activations through ACTMEM;
* arbitrary ONNX layout/Concat axes;
* hardware/RTL changes before compiler-side scheduling tests pass.

## 13. Reference MBV2 facts

Current works-and-must-preserve examples:

| tensor | bytes |
|---|---:|
| 96x16x16 parent | 24576 |
| 96x16x16 Concat group | 24576 |
| 24x16x16 projection output | 6144 |
| three 32x16x16 split outputs | 8192 each |

The current 7-node high-water is about 81–82 kB, leaving room within 256 kB.
`split_4_concat_out`: channels `(32,32,32)`, offsets `(0,32,64)`, group stride
96. The conservative parent+group+projection sum is 55296 B; the measured
simultaneous peak from live ranges is 49152 B because the projection output is
written after the parent's last use.

## 14. Current state versus target

| area | today | target |
|---|---|---|
| scheduling | linear `current_loaded_ifmap_name` tracker | DAG region scheduler |
| memory model | Concat-specific live-byte estimate | all-entry/all-exit live-range plan |
| Slice/Concat | internal views | layout nodes inside candidate regions |
| readout | per-node heuristic | region boundary property |
| output layout | CSR output-view word | per-group base/stride/offset RTL contract |
| fallback | eligibility reject | split to smaller legal regions, then externalize |
