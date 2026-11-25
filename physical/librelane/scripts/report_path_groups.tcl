# Report setup/hold paths separately for the four requested path classes.
#
# Environment:
#   TOP      top module name
#   NETLIST  final Verilog netlist
#   SDC      final SDC
#   LIBS     colon-separated Liberty files (stdcell + macro typ corners)
#   OUT_DIR  report directory
#
# OpenSTA 2.7 has no set_path_group command, so each class is a separate
# from/to query instead of a named timing path group.

set top $::env(TOP)
set netlist $::env(NETLIST)
set sdc $::env(SDC)
set out_dir $::env(OUT_DIR)

file mkdir $out_dir

foreach lib [split $::env(LIBS) ":"] {
    if {$lib ne ""} {
        read_liberty $lib
    }
}
read_verilog $netlist
link_design $top
read_sdc $sdc
set_propagated_clock [all_clocks]

set inputs [all_inputs]
foreach p {clk nrst} {
    set idx [lsearch $inputs [get_port $p]]
    if {$idx >= 0} {
        set inputs [lreplace $inputs $idx $idx]
    }
}
set registers [all_registers]
set outputs [all_outputs]

proc report_class {name from to out_dir} {
    foreach delay {max min} {
        if {$delay eq "max"} {
            set suffix setup
        } else {
            set suffix hold
        }
        set path "$out_dir/${name}.${suffix}.rpt"
        set fh [open $path w]
        puts $fh "Path class: $name ($suffix)"
        close $fh
        report_checks -from $from -to $to -path_delay $delay \
            -group_path_count 1 -endpoint_path_count 1 -format summary >> $path
    }
}

report_class in2reg    $inputs   $registers $out_dir
report_class reg2out   $registers $outputs  $out_dir
report_class reg2reg   $registers $registers $out_dir
report_class feedthrough $inputs  $outputs  $out_dir

set summary "$out_dir/summary.rpt"
set fh [open $summary w]
foreach {label cmd} {
    "TNS max" report_tns
    "TNS min" report_tns
    "WNS max" report_worst_slack
    "WNS min" report_worst_slack
} {
    if {$label eq "TNS max" || $label eq "WNS max"} {
        set value [{*}$cmd -max]
    } else {
        set value [{*}$cmd -min]
    }
    puts $fh "$label: $value"
}
close $fh
