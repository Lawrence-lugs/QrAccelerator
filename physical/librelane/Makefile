SHELL := /bin/bash
.DEFAULT_GOAL := fix-librelane

PDK_ROOT ?= /foss/pdks
PDK ?= ihp-sg13g2
SCL ?= sg13g2_stdcell

BUILD := ../build/librelane
PREPROCESSED := $(BUILD)/preprocessed
MACROS := $(BUILD)/macros
STA_CORNER ?= /usr/local/lib/python3.12/dist-packages/librelane/scripts/openroad/sta/corner.tcl

LIBRELANE_BIN ?= /usr/local/bin/librelane
FLOW_TIMEOUT ?= 10m
FLOW_JOBS ?= 4
HARDEN_TO ?=
HARDEN_LIMIT := $(if $(HARDEN_TO),--to $(HARDEN_TO))
PROBE_TO ?= pins
PIN_RUN ?=
FLOW_LOCK := .flow.lock

LIBRELANE := stdbuf -oL -eL env -u PYTHONPATH PYTHONUNBUFFERED=1 \
	PDK_ROOT=$(PDK_ROOT) $(LIBRELANE_BIN) --jobs $(FLOW_JOBS) --full \
	--manual-pdk --pdk $(PDK) --pdk-root $(PDK_ROOT) --scl $(SCL) \
	--design-dir .

.PHONY: fix-librelane preprocess-scaler preprocess-scaler-group preprocess-feature preprocess-tree preprocess-ram preprocess-top check-macros report clean

BOUNDED_TARGETS := harden-scaler-whole harden-scaler-group harden-feature \
	harden-tree harden-ram probe-feature probe-ram top

.PHONY: $(BOUNDED_TARGETS) $(addprefix _,$(BOUNDED_TARGETS))

$(BOUNDED_TARGETS):
	@mkdir -p runs
	@[[ "$(FLOW_TIMEOUT)" =~ ^[1-9][0-9]*[smhd]?$$ ]] || \
		{ echo "FLOW_TIMEOUT must be a positive duration (e.g. 10m)" >&2; exit 2; }
	timeout --kill-after=10s "$(FLOW_TIMEOUT)" \
		flock --nonblock --no-fork --conflict-exit-code 75 $(FLOW_LOCK) $(MAKE_COMMAND) -j1 _$@ || { \
		status=$$?; \
		case $$status in \
			75) echo "Another physical flow or clean is active" >&2 ;; \
			124|137) echo "$@ exceeded FLOW_TIMEOUT=$(FLOW_TIMEOUT). See the logs in runs/." >&2 ;; \
		esac; \
		exit $$status; \
	}

_probe-feature: $(if $(PIN_RUN),,preprocess-feature) fix-librelane
	bash scripts/probe_feature.sh "$(PROBE_TO)" "$(PIN_RUN)" $(LIBRELANE)

fix-librelane:
	sed -i \
		-e 's/{slew cap input net fanout}/{slew capacitance input_pin net fanout}/g' \
		-e 's/slew cap input net fanout/slew capacitance input_pin net fanout/g' \
		$(STA_CORNER)

preprocess-scaler:
	mkdir -p $(PREPROCESSED)
	sv2v -I ../../rtl \
		../../rtl/qracc_pkg.svh \
		../../rtl/output_scaler/output_scaler_set.sv \
		../../rtl/output_scaler/output_scaler.sv \
		-w $(PREPROCESSED)/output_scaler_set.v

_harden-scaler-whole: preprocess-scaler fix-librelane
	@echo "WARNING: hardening the whole 256-lane output_scaler_set exceeds ABC; kept for reference only."
	mkdir -p $(MACROS)
	$(LIBRELANE) --run-tag output_scaler_set --overwrite \
		--save-views-to $(abspath $(MACROS)/output_scaler_set) \
		configs/output_scaler_set.yaml

preprocess-scaler-group:
	mkdir -p $(PREPROCESSED)
	sv2v -I ../../rtl \
		../../rtl/qracc_pkg.svh \
		../../rtl/output_scaler/output_scaler.sv \
		src/output_scaler_group.sv \
		-w $(PREPROCESSED)/output_scaler_group.v

_harden-scaler-group: preprocess-scaler-group fix-librelane
	mkdir -p $(MACROS)
	$(LIBRELANE) --run-tag output_scaler_group --overwrite $(HARDEN_LIMIT) \
		$(if $(HARDEN_TO),,--save-views-to $(abspath $(MACROS)/output_scaler_group)) \
		configs/output_scaler_group.yaml

preprocess-feature:
	mkdir -p $(PREPROCESSED)
	sv2v -I ../../rtl \
		../../rtl/qracc_pkg.svh \
		../../rtl/feature_loader/feature_loader.sv \
		-w $(PREPROCESSED)/feature_loader_core.v
	sed -i 's/^module feature_loader /module feature_loader_core /' \
		$(PREPROCESSED)/feature_loader_core.v
	sv2v -I ../../rtl src/feature_loader_phys.sv \
		-w $(PREPROCESSED)/feature_loader.v

_harden-feature: preprocess-feature fix-librelane
	mkdir -p $(MACROS)
	$(LIBRELANE) --run-tag feature_loader --overwrite $(HARDEN_LIMIT) \
		$(if $(HARDEN_TO),,--save-views-to $(abspath $(MACROS)/feature_loader)) \
		configs/feature_loader.yaml

preprocess-tree:
	mkdir -p $(PREPROCESSED)
	sv2v -I ../../rtl \
		../../rtl/shift_add_tree.sv \
		-w $(PREPROCESSED)/shift_add_tree.v

_harden-tree: preprocess-tree fix-librelane
	mkdir -p $(MACROS)
	$(LIBRELANE) --run-tag shift_add_tree --overwrite \
		--save-views-to $(abspath $(MACROS)/shift_add_tree) \
		configs/shift_add_tree.yaml

preprocess-ram:
	mkdir -p $(PREPROCESSED)
	sv2v -I ../../rtl \
		../actmem/actmem_2w2r_ihp.sv \
		../actmem/ram_2w2r_ihp.sv \
		-w $(PREPROCESSED)/ram_2w2r.v

_probe-ram: preprocess-ram fix-librelane
	tag="actmem_floorplan_$$(date -u +%Y%m%dT%H%M%S)_$$$$"; \
	$(LIBRELANE) --run-tag "$$tag" --to OpenROAD.GeneratePDN configs/ram_2w2r.yaml

_harden-ram: preprocess-ram fix-librelane
	mkdir -p $(MACROS)
	$(LIBRELANE) --run-tag ram_2w2r --overwrite $(HARDEN_LIMIT) \
		$(if $(HARDEN_TO),,--save-views-to $(abspath $(MACROS)/ram_2w2r)) \
		configs/ram_2w2r.yaml

preprocess-top:
	mkdir -p $(PREPROCESSED)
	sv2v -I ../../rtl \
		../../rtl/qracc_pkg.svh \
		../../rtl/control/qracc_csr.sv \
		../../rtl/control/qracc_controller.sv \
		../../rtl/seq_acc.sv \
		../../rtl/qr_acc_wrapper.sv \
		../../rtl/wr_controller.sv \
		../../rtl/twos_to_bipolar.sv \
		../../rtl/bipolar_bias_sub.sv \
		../../rtl/wsacc/wsacc_pe.sv \
		../../rtl/wsacc/wsacc_pe_cluster.sv \
		../../rtl/feature_loader/padder.sv \
		../../rtl/activation_buffer/mm_output_aligner.sv \
		../../rtl/activation_buffer/piso_write_queue.sv \
		../../rtl/shift_add_tree.sv \
		../../rtl/qr_acc_top.sv \
		src/output_scaler_set_phys.sv \
		src/qr_acc_top_phys.sv \
		-w $(PREPROCESSED)/qr_acc_top_phys.v

check-macros:
	@for f in \
		$(MACROS)/output_scaler_group/lef/output_scaler_group.lef \
		$(MACROS)/feature_loader/lef/feature_loader.lef \
		$(MACROS)/ram_2w2r/lef/ram_2w2r.lef; do \
		test -f "$$f" || { echo "missing macro view: $$f"; exit 1; }; \
	done

TOP_RUN := runs/qr_acc_top_phys
TOP_REPORTS := ../reports/librelane/top
STDCELL_LIB := $(PDK_ROOT)/$(PDK)/libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib
TOP_LIBS := $(STDCELL_LIB):$(MACROS)/output_scaler_group/lib/nom_typ_1p20V_25C/output_scaler_group.lib:$(MACROS)/feature_loader/lib/nom_typ_1p20V_25C/feature_loader.lib:$(MACROS)/ram_2w2r/lib/nom_typ_1p20V_25C/ram_2w2r.lib

report:
	mkdir -p $(TOP_REPORTS)
	TOP=qr_acc_top_phys \
	NETLIST=$(TOP_RUN)/final/nl/qr_acc_top_phys.nl.v \
	SDC=$(TOP_RUN)/final/sdc/qr_acc_top_phys.sdc \
	LIBS="$(TOP_LIBS)" \
	OUT_DIR=$(TOP_REPORTS) \
	/foss/tools/bin/sta scripts/report_path_groups.tcl

_top: preprocess-top fix-librelane check-macros
	mkdir -p $(MACROS)
	$(LIBRELANE) --run-tag qr_acc_top_phys --overwrite \
		--save-views-to $(abspath $(MACROS)/qr_acc_top_phys) \
		configs/qr_acc_top_phys.yaml

clean:
	flock --nonblock --no-fork $(FLOW_LOCK) rm -rf runs $(BUILD)
