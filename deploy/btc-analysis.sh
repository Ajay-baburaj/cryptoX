#!/bin/sh
set -eu
cd /opt/cryptox
mkdir -p data/btc_agents
snapshot=$(mktemp data/btc_agents/latest.XXXXXX)
trap 'rm -f "$snapshot"' EXIT
if [ -s data/btc_agents/derivatives.csv ]; then set -- --context data/btc_agents/derivatives.csv; else set --; fi
.venv/bin/python -m btc_agents signal --venue delta --live "$@" > "$snapshot"
mv "$snapshot" data/btc_agents/latest.json
