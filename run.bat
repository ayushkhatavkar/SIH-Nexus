@echo off
echo Starting NEXUS...
if not exist data\fir.csv (
  echo Generating synthetic demo data...
  python generate_demo_data.py
)
echo.
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Launching server at http://localhost:4173
start http://localhost:4173
python server.py
pause
