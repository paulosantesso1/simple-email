@echo off
rem Gera o instalador completo: instalador\SimpleEmail-Setup.exe (nao precisa de Python no PC de destino).
rem Requer, so na maquina que gera: .venv com as dependencias + pyinstaller, e o Inno Setup 6.
cd /d "%~dp0"

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name SimpleEmail ^
  --distpath dist --workpath build --specpath build ^
  --paths "%~dp0." ^
  --copy-metadata keyring --collect-submodules keyring ^
  --hidden-import win32ctypes.pywin32.pywintypes --hidden-import win32ctypes.pywin32.win32cred ^
  --collect-all wx ^
  email_app.py
if errorlevel 1 exit /b 1

set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
"%ISCC%" SimpleEmail.iss
