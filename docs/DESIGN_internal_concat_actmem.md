# DESIGN — internal Concat views in ACTMEM

Status: design evaluation, not implemented.
Scope: extend the internal channel-Slice view to channel Concat, and define
when the compiler must fall back to the external/L2 "black hole" model.

## 1. Current model

Unsupported ONNX nodes are not executed by the accelerator. The testbench L2 is
a modelling convenience: external hardware may gather, slice, concatenate, or
materialise a tensor there. That is why an unsupported node in the middle does
not break the compile flow.

For internal Slice views we already rely on ACTMEM continuity:

```text
consumer address = parent_base
                 + pixel * parent_channel_stride
                 + channel_offset
                 + c
```

The current `n_nodes=7` split chain still externally reads each 32-channel
split output because the immediate consumer is a `Concat`. The next 1x1
projection is currently fed from an ONNX-computed `split_4_concat_out` in
external memory, not from the three ACTMEM slots.

## 2. MBV2 split: concrete sizes

Physical ACTMEM: **256 kB = 262144 bytes** (byte-addressable).

For the first residual block:

| tensor | shape | bytes |
|---|---|---|
| node3 output (parent) | 96×16×16 | 24576 |
| each split output | 32×16×16 | 8192 |
| concat group | 96×16×16 | 24576 |
| 1x1 projection output | 24×16×16 | 6144 |

The current 7-node high-water mark is around 81 kB, so a separate 24 kB concat
slot plus the live 24 kB parent is comfortably inside 256 kB.

Later MBV2 tensors are smaller in space:

| tensor | bytes |
|---|---|
| 144×8×8 | 9216 |
| 192×8×8 | 12288 |
| 256×4×4 | 4096 |

So **MBV2 fits** an internal concat slot for this block, with room for the
parent and output.

## 3. Proposed internal Concat form

Only support a **channel-axis Concat of one or more internally resident
producers**, with the group written directly by each producer:

```text
concat_base
producer k writes at concat_base + input_offset_k + pixel * concat_channels + c
consumer reads  at concat_base + pixel * concat_channels + c
```

Requirements:

* each input's producer writes into the same group base, at its input channel
  offset;
* the consumer's `ifmap_channel_stride = sum(input_channels)`;
* split inputs keep their parent base live while writing into the group;
* the group is allocated for `max_pixels * concat_channels` bytes;
* no external readout/readback for the inputs unless they are also graph
  outputs or have other consumers.

This needs an **output channel offset** (and an output pixel stride) in the
CSR/controller. The current 8-bit `ifmap_channel_offset` is too narrow for
256-channel tensors and is an *input* field; add a 16-bit output offset and a
16-bit output stride/group width.

## 4. Supported vs fallback

Support only when all of these hold:

1. Concat axis is channels.
2. All inputs are produced by compilable nodes and are resident in ACTMEM at
   the time the group is written.
3. All inputs are contiguous channel slices of the group and have uniform
   spatial dimensions.
4. Total group bytes fit in the remaining ACTMEM budget.
5. Channel offsets and group width fit the widened fields.
6. The group does not alias a live tensor.

Otherwise fall back to the existing external/L2 model and force the inputs and
consumer to be external:

* H/W-axis Concat;
* inputs from graph inputs, constants, or non-compilable producers;
* mixed producers that are not already at the right group base;
* non-uniform spatial shapes;
* group larger than ACTMEM or larger than the remaining live budget;
* offsets/width exceeding the fields;
* Concat followed by a shape-changing op that cannot be composed as a view.

## 5. Memory edge cases

### 5.1 Group larger than ACTMEM

If `bytes(concat) > 262144`, external fallback is mandatory. A 256-channel
32×32 tensor alone is 262144 bytes, leaving no room for the parent, output, or
scratch. This is a realistic theoretical order (ResNet-style 256×32×32).

### 5.2 Group fits but peak liveness does not

Fitting the group alone is insufficient. The compiler must account for:

```text
live parents + concat group + producer outputs + consumer output + readout
```

A monotonic `ofmap_start_addr` allocator can still exceed 256 kB. A liveness /
reference-count allocator is required before claiming support. If the peak
exceeds the budget, fall back externally or stream.

### 5.3 Allocation granularity and aliasing

The group needs a byte base and a pixel stride. Address arithmetic is byte
based; channel counts need not be powers of two (96, 144, 192, 256). Ensure:

* the group base is within the 18-bit physical range;
* the last pixel's last channel is within 256 kB;
* no split overwrites a parent still needed by another split;
* no split writes into a slot that a later op still reads as a different view.

### 5.4 Readout pressure

If every split is still marked `readout=True`, the L2 traffic can hide a
missing internal view. For certification, suppress readout for internal concat
inputs and, in one test, poison L2 to prove the consumer never reads it.

## 6. Split-after-unsupported / split-after-overflow

This is the main edge case introduced by the split work.

A Slice consumer may be internal only if its parent is resident:

```python
internal = (input_parent == current_loaded_ifmap_name)
```

When the parent was produced by an unsupported node, was read from L2, or was
evicted because the tensor did not fit, the slice data is already **post-split**
in external memory. In that case:

* `include_ifmap_writes = True` for the consumer;
* `ifmap_channel_stride = slice_channels`, **not** the parent channel count;
* `ifmap_channel_offset = 0` for the loaded compact slice;
* `preserve_ifmap = False`;
* no internal-view readout suppression.

The current code sets `stride` to the parent channel count whenever a Slice is
resolved, even when `input_loaded` is false. That is wrong for an external
post-split tensor and must be fixed before claiming arbitrary graph support.

## 7. Theoretical node-order cases to test

| case | expected |
|---|---|
| Concat of three splits of one parent | internal group, no readout |
| Concat of two splits + one direct tensor | fallback |
| Concat axis=2 or 3 | fallback |
| Concat with one input | alias, no copy |
| Concat of graph inputs/constants | fallback |
| nested Concat | flatten if channel-axis, else fallback |
| Concat output consumed by two nodes | keep group live; fanout |
| Concat output also graph output | internal group + final readout |
| split after unsupported op | external post-split load, compact stride |
| split after overflowed parent | external post-split load |
| split whose parent was evicted | external post-split load |
| 256×32×32 concat | external fallback at 256 kB |
| 96×16×16 MBV2 block | internal group |
| non-32-aligned channels (e.g. 24, 96, 144) | internal if fields/width allow |
| channel offset >255 | requires widened field or fallback |

## 8. Recommended implementation order

1. Add output channel offset + group stride to `qracc_config_t`/CSR.
2. Add a compiler "concat group" descriptor and liveness allocator; compute
   high-water bytes against a configurable 256 kB budget.
3. Emit internal group writes for MBV2 split0/1/2; suppress their readouts.
4. Poison the L2 concat tensor in a test and verify the projection still
   passes.
5. Add the split-after-external/overflow path, with compact stride.
6. Add fallback tests for axis, mixed producers, and >256 kB.
7. Only then extend beyond the MBV2 block.

## 9. Invariants

* Internal view: `consumer_base + pixel*stride + offset + c` addresses exactly
  the bytes written by the producer.
* External post-split load: `stride == ifmap.shape[1]`, offset 0.
* Peak live bytes <= 262144 for the physical implementation.
* Internal concat inputs must not require an L2 readback for correctness.
* A failed support decision must degrade to external, never to a wrong view.
