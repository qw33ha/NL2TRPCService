#!/bin/bash
set -e

while true; do
  /usr/local/trpc/bin/{{ server_bin }} -conf=/usr/local/trpc/bin/trpc_go.yaml >> /root/start.log 2>&1
  sleep 3
done
