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

ExecuteDup 1 5 "DCS1610_BIOS_R0WM3_LN_1.4.8.BIN" "" "" "REBOOT"
ExecuteDup 2 5 "iDRAC-with-Lifecycle-Controller_Firmware_387FW_LN_3.21.21.21_A00.BIN" "" "" ""
ExecuteDup 3 5 "DCS1610_CPLD_Firmware_GCY9R_LN_1.0.4_A00.BIN" "" "" "REBOOT"
ExecuteDup 4 5 "Network_Firmware_3W5Y5_LN_18.8.9_A00.BIN" "" "" "REBOOT"
ExecuteDup 5 5 "SAS-RAID_Firmware_F675Y_LN_25.5.5.0005_A13.BIN" "" "" "REBOOT"
#ExecuteDup 5 7 "Serial-ATA_Firmware_KRP53_LN_DL58_A00.BIN"  "" "" ""
#ExecuteDup 6 7 "Serial-ATA_Firmware_M5GJ1_LN_DB34_A00.BIN"  "" "" ""
#ExecuteDup 7 7 "Serial-ATA_Firmware_RJ5D9_LN_TA23_A00.BIN"  "" "" ""

mytime=`date`
echo End time: $mytime | tee -a $logFile
echo Please see log, located at $logFile for details of the script execution
echo script exited with status $RETURN_STATUS
echo $rebootMessage
exit $RETURN_STATUS
