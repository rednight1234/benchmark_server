#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
bash "$SCRIPT_DIR/stop.sh"
sleep 2
bash "$SCRIPT_DIR/start.sh"