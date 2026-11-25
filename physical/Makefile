PDK_ROOT ?= /foss/pdks
PDK ?= ihp-sg13g2
FRONTEND ?= auto
BLOCK ?= output_scaler
BLOCKS ?= output_scaler padder qracc_csr wr_controller wsacc_pe bipolar_bias_sub
ACTMEM_DEPTH ?= 256
ACTMEM_MACRO_ROWS ?= 256
ACTMEM_SIM_DIR = build/actmem-sim-$(ACTMEM_DEPTH)
ACTMEM_SRAM = $(PDK_ROOT)/$(PDK)/libs.ref/sg13g2_sram/verilog
ACTMEM_LIBERTY = $(PDK_ROOT)/$(PDK)/libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib

.PHONY: elaborate generic ihp ihp-blocks checks actmem-sim actmem-sim-256k actmem-check actmem-area actmem-sweep clean

elaborate:
	FRONTEND=$(FRONTEND) PDK_ROOT=$(PDK_ROOT) PDK=$(PDK) bash synth/synth.sh elaborate

generic:
	FRONTEND=$(FRONTEND) PDK_ROOT=$(PDK_ROOT) PDK=$(PDK) bash synth/synth.sh generic

ihp:
	FRONTEND=$(FRONTEND) PDK_ROOT=$(PDK_ROOT) PDK=$(PDK) BLOCK=$(BLOCK) bash synth/synth.sh block

ihp-blocks:
	@for b in $(BLOCKS); do \
		FRONTEND=$(FRONTEND) PDK_ROOT=$(PDK_ROOT) PDK=$(PDK) BLOCK=$$b \
			bash synth/synth.sh block || exit $$?; \
	done

checks: generic ihp

actmem-sim:
	verilator --binary --timing -DFUNCTIONAL -Wno-fatal \
		-GDEPTH=$(ACTMEM_DEPTH) -GMACRO_ROWS=$(ACTMEM_MACRO_ROWS) \
		--Mdir $(ACTMEM_SIM_DIR) -o actmem_sim \
		$(ACTMEM_SRAM)/RM_IHPSG13_2P_core_behavioral_bm_bist_ideal.v \
		$(ACTMEM_SRAM)/RM_IHPSG13_2P_256x32_c2_bm_bist.v \
		$(ACTMEM_SRAM)/RM_IHPSG13_2P_1024x32_c2_bm_bist.v \
		actmem/actmem_2w2r_ihp.sv actmem/tb_actmem_2w2r.sv \
		../rtl/memory/ram_2w2r.sv ../rtl/qracc_pkg.svh \
		--top tb_actmem_2w2r
	$(ACTMEM_SIM_DIR)/actmem_sim

actmem-sim-256k:
	$(MAKE) actmem-sim ACTMEM_DEPTH=262144 ACTMEM_MACRO_ROWS=1024

actmem-check:
	yosys -p 'read_verilog -sv actmem/ihp_sram_2p_256x32_bb.v actmem/ihp_sram_2p_1024x32_bb.v actmem/actmem_2w2r_ihp.sv; hierarchy -check -top actmem_2w2r_ihp -chparam depth $(ACTMEM_DEPTH) -chparam MACRO_ROWS $(ACTMEM_MACRO_ROWS); synth -run begin:fine; check -assert; stat'

actmem-area:
	yosys -p 'read_verilog -sv actmem/ihp_sram_2p_256x32_bb.v actmem/ihp_sram_2p_1024x32_bb.v actmem/actmem_2w2r_ihp.sv; hierarchy -check -top actmem_2w2r_ihp -chparam depth $(ACTMEM_DEPTH) -chparam MACRO_ROWS $(ACTMEM_MACRO_ROWS); synth -run begin:fine; techmap; opt; dfflibmap -liberty $(ACTMEM_LIBERTY); abc -liberty $(ACTMEM_LIBERTY); opt; stat -liberty $(ACTMEM_LIBERTY)'

actmem-sweep:
	@for d in 256 8192 16384; do \
		$(MAKE) actmem-sim ACTMEM_DEPTH=$$d || exit $$?; \
	done

clean:
	rm -rf build
