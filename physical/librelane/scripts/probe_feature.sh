#!/usr/bin/env bash
set -euo pipefail

goal=$1
pin_run=$2
shift 2
case "$goal" in
    pins|grt) ;;
    *) echo "PROBE_TO must be pins or grt" >&2; exit 2 ;;
esac

# Geometry experiment. Keep the baseline layer derates and isolate the pin
# geometry from the extra buffers inserted by post-GPL repair.
tag="feature_loader_probe_$(date -u +%Y%m%dT%H%M%S)_$$"
config=(
    --override-config FP_CORE_UTIL=35
    --override-config FP_ASPECT_RATIO=1.0
    --override-config PL_TARGET_DENSITY_PCT=35
    --override-config RUN_POST_GPL_DESIGN_REPAIR=false
)
if [[ -z $pin_run ]]; then
    pin_run=$tag
    echo "Feature loader probe: runs/$pin_run"
    "$@" "${config[@]}" --run-tag "$pin_run" --to Odb.CustomIOPlacement \
        configs/feature_loader.yaml
elif [[ $goal != grt || ! $pin_run =~ ^feature_loader_probe_[0-9]{8}T[0-9]{6}_[0-9]+$ ]]; then
    echo "PIN_RUN must be a pin-probe run tag and requires PROBE_TO=grt" >&2
    exit 2
fi
pin_steps=(runs/"$pin_run"/*-odb-customioplacement)
if [[ ${#pin_steps[@]} -ne 1 || ! -f ${pin_steps[0]}/feature_loader.def ]]; then
    echo "Missing CustomIOPlacement DEF in runs/$pin_run" >&2
    exit 1
fi
python3 scripts/check_feature_probe.py pins "${pin_steps[0]}/feature_loader.def"

if [[ $goal == grt ]]; then
    route_tag="${tag}_grt"
    echo "Feature loader global routing probe: runs/$route_tag"
    "$@" --run-tag "$route_tag" \
        --with-initial-state "${pin_steps[0]}/state_out.json" \
        --from Odb.ApplyDEFTemplate --to OpenROAD.GlobalRouting \
        "runs/$pin_run/resolved.json"
    route_steps=(runs/"$route_tag"/*-openroad-globalrouting)
    if [[ ${#route_steps[@]} -ne 1 || ! -f ${route_steps[0]}/openroad-globalrouting.log ]]; then
        echo "Missing global routing log in runs/$route_tag" >&2
        exit 1
    fi
    python3 scripts/check_feature_probe.py grt "${route_steps[0]}/openroad-globalrouting.log"
fi
