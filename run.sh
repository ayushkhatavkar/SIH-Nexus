#!/bin/bash
set -e
if [ ! -f data/fir.csv ]; then
  echo "Generating synthetic demo data..."
  python3 generate_demo_data.py
fi
echo "Installing dependencies..."
pip install -r requirements.txt --quiet
echo "Launching NEXUS at http://localhost:4173"
python3 server.py
