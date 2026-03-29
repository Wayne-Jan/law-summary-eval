@echo off
setlocal EnableExtensions

REM Daily snapshot runner for law-summary-eval.
REM Writes one YYYY-MM-DD snapshot every time it is run.

set "ROOT_DIR=%~dp0.."
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

set "DEFAULT_VENV_PY=D:\venvs\law-summary-eval\Scripts\python.exe"
set "DEFAULT_SERVICE_ACCOUNT=D:\secrets\firebase\law-eval-2f86e-firebase-adminsdk-fbsvc-09d9ce2185.json"
set "DEFAULT_BACKUP_DIR=D:\law-summary-eval-backups"

if not "%LAW_SUMMARY_EVAL_PYTHON%"=="" (
  set "PYTHON_EXE=%LAW_SUMMARY_EVAL_PYTHON%"
) else if exist "%DEFAULT_VENV_PY%" (
  set "PYTHON_EXE=%DEFAULT_VENV_PY%"
) else (
  set "PYTHON_EXE="
)

if "%GOOGLE_APPLICATION_CREDENTIALS%"=="" (
  if exist "%DEFAULT_SERVICE_ACCOUNT%" (
    set "GOOGLE_APPLICATION_CREDENTIALS=%DEFAULT_SERVICE_ACCOUNT%"
  )
)

if "%LAW_SUMMARY_EVAL_BACKUP_DIR%"=="" (
  set "LAW_SUMMARY_EVAL_BACKUP_DIR=%DEFAULT_BACKUP_DIR%"
)

if "%PYTHON_EXE%"=="" (
  where py >nul 2>nul && set "PYTHON_EXE=py -3"
)
if "%PYTHON_EXE%"=="" (
  where python >nul 2>nul && set "PYTHON_EXE=python"
)

if "%PYTHON_EXE%"=="" (
  echo [ERROR] 找不到 Python。
  echo         請安裝 Python，或設定 LAW_SUMMARY_EVAL_PYTHON，或建立 %DEFAULT_VENV_PY%
  exit /b 1
)

if "%GOOGLE_APPLICATION_CREDENTIALS%"=="" (
  echo [ERROR] 找不到 Firebase service account JSON。
  echo         請設定 GOOGLE_APPLICATION_CREDENTIALS，或把檔案放在：
  echo         %DEFAULT_SERVICE_ACCOUNT%
  exit /b 1
)

if not exist "%GOOGLE_APPLICATION_CREDENTIALS%" (
  echo [ERROR] service account 不存在：
  echo         %GOOGLE_APPLICATION_CREDENTIALS%
  exit /b 1
)

if not exist "%LAW_SUMMARY_EVAL_BACKUP_DIR%" (
  mkdir "%LAW_SUMMARY_EVAL_BACKUP_DIR%" >nul 2>nul
)

echo [INFO] ROOT_DIR=%ROOT_DIR%
echo [INFO] PYTHON=%PYTHON_EXE%
echo [INFO] GOOGLE_APPLICATION_CREDENTIALS=%GOOGLE_APPLICATION_CREDENTIALS%
echo [INFO] LAW_SUMMARY_EVAL_BACKUP_DIR=%LAW_SUMMARY_EVAL_BACKUP_DIR%

pushd "%ROOT_DIR%"
call %PYTHON_EXE% scripts\backup_eval_firestore.py --service-account "%GOOGLE_APPLICATION_CREDENTIALS%" --local-dir "%LAW_SUMMARY_EVAL_BACKUP_DIR%"
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
  echo [ERROR] 每日快照執行失敗，exit code=%EXIT_CODE%
  exit /b %EXIT_CODE%
)

echo [OK] 每日快照完成
exit /b 0
