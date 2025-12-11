#!/bin/bash
#

BMCIP=$1
BMCUser=$2
BMCPass=$3
Mode=$4

usage() {
  printf "This script $0 requires 4 parameters.\n"
  printf "$0 [BMCIP] [BMCUser] [BMCPassword] [ISTMode to Set (enable or disable)]\n"
}

if [ $# -lt 4 ]; then
  usage
  exit 1
elif [ "$Mode" != "enable" ] && [ "$Mode" != "disable" ]; then
  usage
  exit 1
fi

if [ "$Mode" = "enable" ]; then
   Arg1="0x05"
else 
   Arg1="0x00"
fi

printf "Checking if $BMCIP is powered on....\n"
powerstate=`curl -skLu "$BMCUser:$BMCPass" https://$BMCIP/redfish/v1/Systems/System.Embedded.1 | jq .PowerState`

if [ $powerstate != "\"On\"" ]; then
  printf "The system must be powered on to access the GPUs to set IST Mode.\n"
  exit 1
fi

for gpu in $(seq 1 8);
do
  printf "Change IST Mode on host %s gpu %s to %s\n" $BMCIP $gpu $Mode
  URL="https://$BMCIP/redfish/v1/Managers/HGX_BMC_0/Actions/Oem/NvidiaManager.SyncOOBRawCommand"

  printf "URL  = %s\n" $URL
  printf "data = %s\n" '{"TargetType": "GPU","TargetInstanceId": '$gpu',"Opcode": "0x2A","Arg1": "'$Arg1'","Arg2": "0x00","DataIn": ["FF", "FF", "FF", "FF"]}'

  time curl -skLu "$BMCUser:$BMCPass" \
    -X POST $URL \
    -H "Content-Type: application/json" \
    --data '{"TargetType": "GPU","TargetInstanceId": '$gpu',"Opcode": "0x2A","Arg1": "'$Arg1'","Arg2": "0x00","DataIn": ["FF", "FF", "FF", "FF"]}'
  printf "\n"
done

