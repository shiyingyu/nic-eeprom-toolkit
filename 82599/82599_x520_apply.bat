@echo off
setlocal EnableExtensions

rem ================================================================
rem Intel 82599 / X520-DA2 EEPROM preset for the user's LED wiring
rem
rem SFP0: LED0 (AD14) = LINK_UP, LED2 (AB14) = LINK/ACTIVITY
rem SFP1: LED0 (AD13) = LINK_UP, LED2 (AB13) = LINK/ACTIVITY
rem All four LEDs are wired +3V3 -> LED -> 510R -> 82599 output,
rem therefore configure the LED outputs as active-low current sinks.
rem ALLOW_ANY_SFP is enabled to bypass the applicable SFP vendor-OUI
rem restriction in the Linux ixgbe driver; this does not guarantee compatibility.
rem
rem IMPORTANT: Replace the example MAC addresses below with the
rem unique MAC addresses assigned to this adapter before deployment.
rem ================================================================

set "MAC_SFP0=00:11:22:33:44:55"
set "MAC_SFP1=00:11:22:33:44:56"
set "ALLOW_ANY_SFP=on"

if "%~1"=="" goto :usage
if /i "%~1"=="/?" goto :usage
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage

set "INPUT=%~1"
set "OUTPUT=%~2"

if not "%~3"=="" (
    echo ERROR: Too many arguments.
    echo.
    goto :usage_error
)

if not exist "%INPUT%" (
    echo ERROR: Input EEPROM file not found: "%INPUT%"
    exit /b 2
)

if not exist "%~dp082599_eeprom_edit.py" (
    echo ERROR: 82599_eeprom_edit.py was not found.
    echo Please place this BAT file in the same directory as the Python script.
    exit /b 2
)

if "%OUTPUT%"=="" set "OUTPUT=%~dpn1_modified%~x1"

 echo.
echo Intel 82599 EEPROM configuration
 echo Input : "%INPUT%"
echo Output: "%OUTPUT%"
echo.
echo MAC SFP0: %MAC_SFP0%
echo MAC SFP1: %MAC_SFP1%
echo Allow any SFP vendor: %ALLOW_ANY_SFP%
echo.
echo Applying settings:
echo   SFP0 LED0 = LINK_UP, active-low
echo   SFP0 LED2 = LINK/ACTIVITY, active-low
echo   SFP1 LED0 = LINK_UP, active-low
echo   SFP1 LED2 = LINK/ACTIVITY, active-low
echo.

python "%~dp082599_eeprom_edit.py" "%INPUT%" ^
    --set "port0.mac=%MAC_SFP0%" ^
    --set "port0.led0.mode=link-up" ^
    --set "port0.led0.polarity=active-low" ^
    --set "port0.led2.mode=link-activity" ^
    --set "port0.led2.polarity=active-low" ^
    --set "port1.mac=%MAC_SFP1%" ^
    --set "port1.led0.mode=link-up" ^
    --set "port1.led0.polarity=active-low" ^
    --set "port1.led2.mode=link-activity" ^
    --set "port1.led2.polarity=active-low" ^
    --set "sfp.allow-any=%ALLOW_ANY_SFP%" ^
    -o "%OUTPUT%"

if errorlevel 1 (
    echo.
    echo ERROR: EEPROM modification failed. The input file was not modified.
    exit /b 1
)

echo.
echo EEPROM configuration completed successfully.
echo The original input file was not modified.
exit /b 0

:usage
 echo.
echo Usage:
echo   %~nx0 input.bin [output.bin]
echo.
echo Examples:
echo   %~nx0 X520-DA2.bin
echo   %~nx0 X520-DA2.bin X520-DA2_custom.bin
echo.
echo The output file defaults to input_modified.bin in the input directory.
echo Edit MAC_SFP0 and MAC_SFP1 near the top of this BAT file before use.
echo The BAT file and 82599_eeprom_edit.py must be in the same directory.
echo.
exit /b 0

:usage_error
 echo Usage: %~nx0 input.bin [output.bin]
exit /b 2
