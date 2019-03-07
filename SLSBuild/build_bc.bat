rem build_bc.bat
rem BC bootloader workspace
if "%1"=="" goto usage

set BASE=%1
set BC_PATH=$BASE%\dcsg5-bc\software\embedded\nxp_lpc_18xx\source

echo Building BC
call build_mcu.bat %BC_PATH%\bootloader bootloader Release
call build_mcu.bat %BC_PATH%\fs_op_image FailSafeImage_BC Release
call build_mcu.bat %BC_PATH%\fs_op_image OpImage_BC Release

goto:eof

:usage
echo Usage:
echo     build_bc.bat "basepath of BC repo"
echo Example:
echo     build_bc.bat c:\work