#!/bin/bash
#

BMCIP=$1
BMCUser=$2
BMCPass=$3
Iterations=$4

usage() {
  printf "This script $0 requires 4 parameters.\n"
  printf "$0 [BMCIP] [BMCUser] [BMCPassword] [Number of Stress test iterations]\n"
  printf "Based on the number of iterations, the script will perform the IST Mode Enable and Disable on each GPU on the target system once per cycle.\n"
  printf "Make sure the host OS is powered on and that the system has had some time to fully initialize.\n"
}


if [ $# -lt 4 ]; then
  usage
  exit 1 
elif [ "$Iterations" -le 0 ]; then
  usage
  exit 1
fi

printf "Stress testing IST enable disable on %s\n" $BMCIP

iter=1
while [ $iter -le $Iterations ]; do
	printf "Stresstest iteration %i\n" $iter 
	./change-IST.sh "$BMCIP" "$BMCUser" "$BMCPass" enable 
	printf "Sleeping 10 secs\n"
	sleep 10
	./change-IST.sh "$BMCIP" "$BMCUser" "$BMCPass" disable
	printf "Sleeping 10 secs\n"
	sleep 10
	((iter++))
done

