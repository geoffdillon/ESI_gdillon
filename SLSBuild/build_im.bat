@echo off
rem build_im.bat
rem IM workspace builds
if "%1"=="" goto usage

set BASE=%1
set IM_PATH=%BASE%\dcsg5-im\software\embedded\nxp_lpc_18xx\source

echo *************Building bootloader
call build_mcu.bat %IM_PATH%\bootloader bootloader Release

echo *************Building FailSafeImage_IM
call build_mcu.bat %IM_PATH%\fs_op_image FailSafeImage_IM Release

echo *************Building OpImage_IM
call build_mcu.bat %IM_PATH%\fs_op_image OpImage_IM Release

goto:eof

:usage
echo Usage:
echo     build_im.bat "basepath of BC repo"
echo Example:
echo     build_im.bat c:\work