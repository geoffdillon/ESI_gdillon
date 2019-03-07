rem build_im.bat
rem IM workspace builds
if "%1"=="" goto usage

set BASE=%1
set IM_PATH=$BASE%\dcsg5-im\software\embedded\nxp_lpc_18xx\source

echo Building BC
call build_mcu.bat %IM_PATH%\bootloader bootloader Release
call build_mcu.bat %IM_PATH%\fs_op_image FailSafeImage_IM Release
call build_mcu.bat %IM_PATH%\fs_op_image OpImage_IM Release

goto:eof

:usage
echo Usage:
echo     build_bc.bat "basepath of BC repo"
echo Example:
echo     build_bc.bat c:\work