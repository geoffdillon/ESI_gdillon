#!/bin/sh
RETURN_STATUS=0
mytime=`date`

rebootMessage=


echo Dell Inc. Auto-Generated Sample Bundle Execution Script
logFile="$LOGFILE"
if [ -z "$LOGFILE" ]; then logFile=/tmp/apply_components.log; fi
touch "$logFile" 2>/dev/null
if [ ! $? == 0 ]; then logFile=/tmp/apply_components.log; else ln -sf $logFile ./apply_components.log > /dev/null 2>&1; fi
echo Start time: $mytime | tee -a $logFile
REEBOOTSTDMESSAGE="Note: Some update requires machine reboot. Please reboot the machine and re-run the script if there are failed updates because of dependency..."
ExecuteDup()
{
   index=$1
        count=$2
        DUP=$3
        Options=
        force=$4
        dependency=$5
        reboot=$6

        if [ ! -z "$force" ];then
                Options="-f"
        fi
        echo [$index/$count] - Executing $DUP | tee -a $logFile
        sh "$DUP" -q $Options | tee -a $logFile
        DUP_STATUS=${PIPESTATUS[0]}
        if [ ! -z "$reboot" ];then
                echo "Note: $DUP update requires machine reboot ..."
                rebootMessage=$REEBOOTSTDMESSAGE
        fi
        if [ ${DUP_STATUS} -eq 1 ];
        then
                RETURN_STATUS=1
        fi
        if [ ${DUP_STATUS} -eq 9 ];
        then
                RETURN_STATUS=1
        fi
        if [ ${DUP_STATUS} -eq 127 ];
        then
                RETURN_STATUS=1
        fi
        return $RETURN_STATUS
}


ExecuteDup 1 12 "Serial-ATA_Firmware_J70MD_LN_GA39_A00.BIN" "" "" ""
ExecuteDup 2 12 "SAS-Drive_Firmware_8HJR8_LN_GS15_A00.BIN" "" "" ""
ExecuteDup 3 12 "Firmware_HYPYY_LN_3.35_A00-00.BIN" "" "" ""
ExecuteDup 4 12 "Network_Firmware_3W5Y5_LN_18.8.9_A00.BIN" "" "" "REBOOT"
ExecuteDup 5 12 "Network_Firmware_6FD9P_LN_16.5.20_A00.BIN" "" "" "REBOOT"
ExecuteDup 6 12 "Network_Firmware_3X5G0_LN64_21.40.16.60.BIN" "" "" "REBOOT"
ExecuteDup 7 12 "Network_Firmware_HKY6H_LN_21.40.2_01.BIN" "" "" "REBOOT"
ExecuteDup 8 12 "Firmware_FF4WY_LN_1.7_A02.BIN" "" "" "REBOOT"
ExecuteDup 9 12 "SAS-RAID_Firmware_F675Y_LN_25.5.5.0005_A13.BIN" "" "" "REBOOT"
ExecuteDup 10 12 "BIOS_2JFRF_LN_2.8.0.BIN" "" "" "REBOOT"
ExecuteDup 11 12 "Network_Firmware_YHF9V_LN_18.8.9_A00.BIN" "" "" "REBOOT"
ExecuteDup 12 12 "iDRAC-with-Lifecycle-Controller_Firmware_1HY5M_LN_2.61.60.60_A00.BIN" "" "" ""
mytime=`date`
echo End time: $mytime | tee -a $logFile
echo Please see log, located at $logFile for details of the script execution
echo script exited with status $RETURN_STATUS
echo $rebootMessage
exit $RETURN_STATUS
