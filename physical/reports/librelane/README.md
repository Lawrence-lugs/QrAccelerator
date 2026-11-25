# LibreLane top-level reports

Generated from the hardened top by `make report` in `physical/librelane/`.

| File | Contents |
| --- | --- |
| `top/in2reg.setup.rpt` | Inputs to registers, setup |
| `top/in2reg.hold.rpt` | Inputs to registers, hold |
| `top/reg2out.setup.rpt` | Registers to outputs, setup |
| `top/reg2out.hold.rpt` | Registers to outputs, hold |
| `top/reg2reg.setup.rpt` | Registers to registers, setup |
| `top/reg2reg.hold.rpt` | Registers to registers, hold |
| `top/feedthrough.setup.rpt` | Inputs to outputs, setup |
| `top/feedthrough.hold.rpt` | Inputs to outputs, hold |
| `top/summary.rpt` | Worst setup/hold slack and TNS |

The reports use the typ corner and the final routed netlist. `make report`
requires a completed `make top` run. Regenerate after any RTL, macro, SDC or
constraint change.
