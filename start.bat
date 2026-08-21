@echo off
setlocal
cd /d "%~dp0"

REM --- sanity check: are we in the right folder? ---
if not exist "main.py" (
  echo.
  echo  ERROR: This file must be in the C:\NTC-App folder,
  echo  next to main.py and telco.db - not in Downloads.
  echo  Move start.bat into C:\NTC-App and run it again.
  echo.
  pause
  exit /b
)

if not exist "venv\Scripts\activate.bat" (
  echo.
  echo  ERROR: The 'venv' folder is missing in this PC.
  echo  Set it up once with:
  echo     python -m venv venv
  echo     venv\Scripts\activate
  echo     pip install -r requirements.txt
  echo.
  pause
  exit /b
)

call venv\Scripts\activate

REM open the browser once the server answers (runs quietly in background)
REM Opens straight into the new /app UI (not the classic one at the bare
REM root) -- same URL the packaged .exe opens, so testing here matches
REM testing there.
start "" /min cmd /c "for /L %%i in (1,1,90) do (curl -s -o nul http://127.0.0.1:8000/app/login && (start http://127.0.0.1:8000/app/login & exit) || (timeout /t 1 >nul))"

echo Starting NTC Telco Database...
echo Keep this window open while using the app. Close it to stop.
echo Other PCs on this network can reach it too - see NETWORK_ACCESS.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
