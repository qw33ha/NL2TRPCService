#!/bin/bash
set -e

{% if rpc_enabled %}bash scripts/generate_stub.sh
{% endif %}sh devops_build.sh
