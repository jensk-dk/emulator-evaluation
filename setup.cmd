@echo off
rem Host setup for Windows. Runs setup.ps1, also where the PowerShell execution
rem policy does not allow scripts (the default on Windows). See setup.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
exit /b %errorlevel%
