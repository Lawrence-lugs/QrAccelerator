#!/usr/bin/bash 
set -e
if [[$1 == ""]] 
then
    echo "No argument supplied"
    exit 1
fi
mkdir -p ~/tmp
mv tests/results/$1/*.txt ~/tmp -v
mkdir -p tests/results/$1
cp tb/qracc/inputs/adc_out_ams* tests/results/$1 -v
cp tb/seq_acc/inputs/mac_out_ams* tests/results/$1 -v