@echo off
rem Build one self-contained executable: dist\Deadlock FOV Tool.exe
cd /d "%~dp0"

python -m pip install --quiet --disable-pip-version-check --upgrade pyinstaller PySide6
if errorlevel 1 (
    echo Could not install PyInstaller / PySide6.
    exit /b 1
)

rem The .spec file packs everything into one exe and drops the Qt pieces this
rem widget-only app never loads (software OpenGL, Qt Quick, PDF, translations).
rem The exe unpacks itself to a temp folder at launch, so the first window
rem takes a couple of seconds.
python -m PyInstaller --noconfirm --clean "Deadlock FOV Tool.spec"

if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

rem Drop the old folder build so there is no confusion about which one is current.
if exist "dist\Deadlock FOV Tool\" rmdir /s /q "dist\Deadlock FOV Tool"

echo.
echo Built: dist\Deadlock FOV Tool.exe
