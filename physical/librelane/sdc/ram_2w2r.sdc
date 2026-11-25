create_clock -name clk -period 20.0 [get_ports clk]
set_clock_uncertainty 1.0 [get_clocks clk]
set_clock_uncertainty -hold 0.1 [get_clocks clk]

set_driving_cell -lib_cell sg13g2_buf_16 -pin A [get_ports clk]

set sync_inputs [all_inputs]
foreach p {clk nrst} {
    set idx [lsearch $sync_inputs [get_port $p]]
    if {$idx >= 0} {
        set sync_inputs [lreplace $sync_inputs $idx $idx]
    }
}
set_driving_cell -lib_cell sg13g2_buf_1 -pin A $sync_inputs
set_input_delay 4.0 -clock clk $sync_inputs
set_output_delay 4.0 -clock clk [all_outputs]

set_false_path -from [get_ports nrst]
