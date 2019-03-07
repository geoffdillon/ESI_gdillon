@echo off
rem Batch file to build MCUXpresso projects from command line

if "%1"=="" goto usage
if "%2"=="" goto usage
if "%3"=="" (
	set BUILDCONFIG=Release
	goto begin
)
set BUILDCONFIG=%3

:begin
echo BUILDCONFIG is %BUILDCONFIG%
SET NXP_HOME=c:\nxp
if exist "%NXP_HOME%" (
	for /F "tokens=* USEBACKQ" %%F in (`dir /AD /b %NXP_HOME%`) DO (set MCU=%%F) 
	SET MCUX=%MCU%
	echo Found MCUXpresso in "%NXP_HOME%\%MCUX%"
) else (
	echo ERROR: MCUXpresso is not installed under %NXP_HOME%
	goto:eof
)

set TOOLCHAIN_PATH=%NXP_HOME%\%MCUX%\ide\tools\bin

set IDE=%NXP_HOME%\%MCUX%\ide\mcuxpressoidec.exe

echo %PATH%|findstr /i /c:"%TOOLCHAIN_PATH:"=%">nul ||set PATH=%PATH%;%TOOLCHAIN_PATH%

set LOGFILE=%2_%BUILDCONFIG%.log
echo Begin build, logging to %LOGFILE%
%IDE% -nosplash --launcher.suppressErrors -application org.eclipse.cdt.managedbuilder.core.headlessbuild -data "%1" -cleanBuild "%2/%BUILDCONFIG%" 2>&1 %LOGFILE%

goto:eof

:usage
echo Usage:
echo     build_mcu.bat workspacefile projectname config
echo Example:
echo     build_mcu.bat c:\work\dcsg5-bc\software\embedded\nxp_lpc_18xx\source\fs_op_image OpImage_BC Release