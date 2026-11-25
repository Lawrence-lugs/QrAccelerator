# shift_add_tree is purely combinational. Use a virtual clock so the
# feedthrough paths still get a 50 MHz input/output budget.
create_clock -name virt -period 20.0
set_clock_uncertainty 1.0 [get_clocks virt]

set_driving_cell -lib_cell sg13g2_buf_1 -pin A [all_inputs]
set_input_delay 4.0 -clock virt [all_inputs]
set_output_delay 4.0 -clock virt [all_outputs]
