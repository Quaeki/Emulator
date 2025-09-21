#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "Emulator_3.py" --vfs "vfs_multifile.csv" --startup "startup_stage3_ok.txt"
