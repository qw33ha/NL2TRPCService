#!/bin/bash
set -e

go mod tidy
go build -gcflags=all="-N -l" -o {{ server_bin }} ./
