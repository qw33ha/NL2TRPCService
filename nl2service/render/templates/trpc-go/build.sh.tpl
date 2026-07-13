#!/bin/bash
set -e

bash scripts/generate_stub.sh
sh devops_build.sh
