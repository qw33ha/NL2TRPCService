#!/bin/bash
set -euo pipefail

if ! command -v trpc >/dev/null 2>&1; then
  echo "trpc command not found. Install trpc-cmdline first, for example:"
  echo "  go install trpc.group/trpc-go/trpc-cmdline/trpc@latest"
  exit 1
fi

mkdir -p pb
trpc create -p proto/{{ proto_output_name }} -o pb --rpconly --mock=false --nogomod=true -f
