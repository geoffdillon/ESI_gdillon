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

ExecuteDup 1 5 "BIOS_TJDKF_LN_1.6.11.BIN" "" "" "REBOOT"
ExecuteDup 2 5 "iDRAC-with-Lifecycle-Controller_Firmware_FDMV1_LN_3.21.26.22_A00.BIN" "" "" ""
ExecuteDup 3 5 "CPLD_Firmware_5GDF4_LN_1.0.7_A00.BIN" "" "" "REBOOT"
ExecuteDup 4 5 "Network_Firmware_YHF9V_LN_18.8.9_A00.BIN" "" "" "REBOOT"
ExecuteDup 5 5 "SAS-RAID_Firmware_F675Y_LN_25.5.5.0005_A13.BIN" "" "" "REBOOT"
#ExecuteDup 5 8 "SAS-Drive_Firmware_37RKK_LN_KT37_A00.BIN" "" "" ""
#ExecuteDup 6 8 "SAS-Drive_Firmware_95C83_LN_DSF2_A00.BIN" "" "" ""
#ExecuteDup 7 8 "SAS-Drive_Firmware_NFXW0_LN_ST31_A00.BIN" "" "" ""
#ExecuteDup 8 8 "SAS-Drive_Firmware_MG2X8_LN_EA04.BIN" "" "" ""

mytime=`date`
echo End time: $mytime | tee -a $logFile
echo Please see log, located at $logFile for details of the script execution
echo script exited with status $RETURN_STATUS
echo $rebootMessage
exit $RETURN_STATUS
