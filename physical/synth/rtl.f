# Synthesised RTL for qr_acc_top, relative to the repository root.
#
# Deliberately absent: ts_qracc.sv, ts_qracc_multibank.sv, ts_column.sv and
# column_wrapper.sv (behavioural analog models / testbench wrappers), the stale
# qr_acc_top_wrapper.sv, and activation_buffer.sv + sram_32bank_8b.sv (the
# non-MODEL_MEM path, whose SRAM placeholder is empty).
#
# ram_2w2r.sv is read so Yosys knows the macro ports, then converted to a
# blackbox in synth/elaborate.ys.
rtl/qracc_pkg.svh
rtl/control/qracc_csr.sv
rtl/control/qracc_controller.sv
rtl/seq_acc.sv
rtl/qr_acc_wrapper.sv
rtl/wr_controller.sv
rtl/shift_add_tree.sv
rtl/twos_to_bipolar.sv
rtl/bipolar_bias_sub.sv
rtl/wsacc/wsacc_pe.sv
rtl/wsacc/wsacc_pe_cluster.sv
rtl/memory/ram_2w2r.sv
rtl/feature_loader/padder.sv
rtl/feature_loader/feature_loader.sv
rtl/activation_buffer/mm_output_aligner.sv
rtl/activation_buffer/piso_write_queue.sv
rtl/output_scaler/output_scaler.sv
rtl/output_scaler/output_scaler_set.sv
rtl/qr_acc_top.sv
