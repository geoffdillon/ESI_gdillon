#!/usr/bin/bash
# RMTK Crash Reporter Generator
# Usage: bash rmtk_crash_report.sh >> report.txt

# Quickly prints various types of system information to stdout
# Output can be redirected to store information in a text file
# Later, the information can be parsed and analysed
# The goal here is to collect information quickly, NOT VALIDATION
echo "== Table of Contents ================================================="
echo "Each section is tagged with one of the following strings."
echo "Temporary files are created to show progress when redirecting stdout."
echo "  == HW Info"
echo "  == Network Info"
echo "  == OS Info"
echo "  == Install Info"
echo "  == SW Info"
echo "  == Service Info"
echo "  == Configs"
echo "  == Logs"
echo "== HW Info ========================================================"
touch "[0:7]RMTK_Crashreporter:HW_Info"
# Verify the SRMBIOS Version
dmidecode -t 0

# Verify Switch FW version
# Run the command from the RM: curl -D- -H "Content-Type:application/json" -X GET -k http://10.253.X.XX/G5SwitchRestApi/v1/System
# 
# Verify bootloader version
# Run the command from the RM: curl -D /dev/stdout -H "Content-Type:application/json" -X GET -k http://10.253.X.XX/G5SwitchRestApi/v1/System/BootVersion

# Verify all switches, all nodes, Port status
RMadmin getswitchlist
RMadmin getnodelist
RMadmin getMgmtPortStatus

ipmitool -I lan -H 10.253.0.30 -U sv -P sv fru
ipmitool -h 
echo "== Network Info ======================================================"
touch "[1:7]RMTK_Crashreporter:Network_Info"
ip netns list
ip route
ip addr
ip netns exec nsmgmt1 ip addr
ip netns exec nsmgmt2 ip addr
echo "The uBMC at: "
ping -c 3 10.253.0.30
echo "The MC at: "
ping -c 3 10.253.0.11
echo "The IM at: "
ping -c 3 10.253.0.17
echo "The block1 BC at: "
ping -c 3 10.253.0.1
echo "The block2 BC at: "
ping -c 3 10.253.0.2
echo "The block3 BC at: "
ping -c 3 10.253.0.3
echo "== OS Info ==========================================================="
touch "[2:7]RMTK_Crashreporter:OS_Info"
cat /etc/centos-release
rpm -qa | grep kernel
history
echo "== Install Info ======================================================"
touch "[3:7]RMTK_Crashreporter:Install_Info"
yum list installed
scl enable rh-python34 "pip list"
echo "== SW Info ==========================================================="
touch "[4:7]RMTK_Crashreporter:SW_Info"
RMversion
echo "== Service Info ======================================================"
touch "[5:7]RMTK_Crashreporter:Service_Info"
systemctl status RMG5MCPortMapService
systemctl status RMMgmtPortMonitor
systemctl status RMNamespaceMonitor
systemctl status RMNodeDiscoveryService
systemctl status RMNodePortMapService
systemctl status RMRackConfigService
systemctl status RMRedfishService
systemctl status RMSSDPService
systemctl status RMTimeService
echo "== Configs =============================================================="
touch "[6:7]RMTK_Crashreporter:Configs"
# @TODO: Gather config data for various services (DHCP)
echo "== Logs =============================================================="
touch "[7:7]RMTK_Crashreporter:Logs"
cat /var/log/messages
cat /var/log/rackmanager/*

# Delete the progress markers
touch "[0:7]RMTK_Crashreporter:HW_Info"
rm -f "[1:7]RMTK_Crashreporter:Network_Info"
rm -f "[2:7]RMTK_Crashreporter:OS_Info"
rm -f "[3:7]RMTK_Crashreporter:Install_Info"
rm -f "[4:7]RMTK_Crashreporter:SW_Info"
rm -f "[5:7]RMTK_Crashreporter:Service_Info"
rm -f "[6:7]RMTK_Crashreporter:Configs"
rm -f "[7:7]RMTK_Crashreporter:Logs"

