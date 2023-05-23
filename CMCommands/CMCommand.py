#!/usr/bin/python3
# Geoff Dillon geoff_dillon@dell.com
# Copyright Dell, Inc 2023
# FOR INTERNAL USE ONLY.  DO NOT distribute to customers or partners/vendors.
# This script automates certain IPMI raw commands to the C6400/C6600 CM through the iDRAC.
# REQUIRES python 3.8 or higher
# REQUIRES ipmitool

"""
This is a convenience utility to compose IPMI raw commands to the C6400/C6600 Chassis Manager
via a sled's iDrac and to parse the results into human-readable format.

Use the command '-C help' to see the list of supported commands.
    python CMCommand.py -C help

You can obtain ipmitool for Windows from Dell at
    https://www.dell.com/support/home/en-us/drivers/driversdetails?driverid=w9nmr
Setup the system path to include
    "C:\Program Files (x86)\Dell\SysMgt\bmc"

To enable IPMI commands over LAN through the iDRAC, be sure to Enable the IPMI Over LAN
    racadm set idrac.ipmilan.enable 1

For iDRAC v5.00.10.00 ++
A permissions allowance is required to run commands that bridge to the CM from the iDRAC.
	racadm set idrac.security.allowipmii2ccommands 1
"""

import os
import sys
import subprocess
import argparse
import base64
import configparser

# global set by arguments
use_raw_output = False
print_verbose = False

# global constants
#These are used to setup the header for the SendMessage command 0x6 0x34 through the iDRAC to the CM
generic_preamble = "0x06 0x34 0x45 0x70 {} 0xc8 0x20 0x0"
config_preamble = generic_preamble.format('0xc0')  # for OEM NetFN 0x30
hidden_config_preamble = generic_preamble.format('0xc8')  # OEM private NetFN 0x32
log_preamble = generic_preamble.format('0x28')  # for NetFN Storage 0x0A
app_preamble = generic_preamble.format('0x18')  # for NetFN Application 0x06
chassis_preamble = generic_preamble.format('0x00')  # of NetFN Chassis 0x00

ending = '0xd8'  # this is a placeholder for the final checksum in the request
notimp = "Not Implemented"
completion_code_idx = 6  # 6th byte in the response is the completion code
CMLogOffsetIncrement = 64
CMLogMaxLines = 999

# used to identify supported Chassis
CMBoardPN = {
    'Hubble': ['0R8Y73', '0W3N19', '07NN9G'],
    'Lake Austin': ['05V6V5'],
}
SptChassisHubble = 'Hubble'
SptChassisLkAustin = 'Lake Austin'


PlainCmdResponseOffset = 3  # number of response header bytes for a 0x30 0x?? type command
SendMsgCmdResponseOffset = 7  # number of resp header bytes for a Send msg command

# The names of the properties that will be captured or reset for FRU Update repairs
ReconfigProperties = {
    'ConfigProperties': ['RedundantPSUsN', 'ChassisServiceTag', 'BpPresent', 'ChassisPowerLimit', 'ChassisPowerCap', 'FTREnable', 'CableAmpLimit'],
    'FRUSettings': ['ChassisPartNumber', 'ChassisSerialNumber', 'ChassisBoardPartNumber', 'ChassisBoardSerialNumber'],
}

# Classes used in data structures
class CMInfoSet:
    """An instance of a single CM Config Setting"""
    name = ''
    len = 1
    data = ""
    
    def __init__(self, name, id, len, data, enum={}):
        self.name = name # should be a string
        self.id = "{:02x}".format(id) # should be string lc hex like '01', '1a'
        self.len = len   # should be an int        
        self.data = data # should be a string that describes how to handle the value
        self.enum = enum  # dictionary defines allowed values and interpretations

    def get_value(self, bytes):
        if (not (len(bytes) == self.len)):
            return ("Wrong number of bytes in {}: Got {} expecting {}".format(self.name, len(bytes), self.len))
        if ((self.data == 'ver') and (len(bytes) == 2)):
            major = int(bytes[0], 16)
            minor = int(bytes[1], 16)
            return ("{}.{}".format(major, minor))
        elif ((self.data == 'ver') and (len(bytes) == 4)):
            aux1 = int(bytes[0], 16)
            aux2 = int(bytes[1], 16)
            aux3 = int(bytes[2], 16)
            aux4 = int(bytes[3], 16)
            return ("{}.{}.{}.{}".format(aux1, aux2, aux3, aux4))
        elif (self.data == 'int'):
            if (self.len == 2):
                return (str(int(bytes[1] + bytes[0], 16)))
            return (str(int(bytes[0], 16)))
        elif (self.data =='signint'):
            sb = int(bytes[0], 16)
            if ((sb & 0x80) == 0x80):
                return (str(sb - 256))
            return (str(sb))
        elif (self.data == 'bit'):
            # for a bitmask just return the hex
            return bytes[0]
        elif (self.data == 'enum'):
            return "{} ({})".format(self.enum.get(bytes[0], 'Unknown'), bytes[0])
        return "Type??"

class CMConfigSet:
    """An instance of a single CM Config Setting"""
    name = ''
    len = 1
    enum = {}
    default = None
    writable = False
    
    def __init__(self, name, id, len, enum, default, writable):
        self.name = name # should be a string
        self.id = hex(id) # should be string lc hex like '01', '1a'
        self.len = len   # should be an int        
        self.enum = enum # should be a dict or a range
        self.default = default 
        self.writable = writable
        
    def get_enum_val(self, index):
        """Get the translation from the numerical value"""
        outstr = str(index)  # the default return
        if (isinstance(index, str)):
            if (index.isnumeric()):
                checkvalue = int(index)
            else:
                # can't check the enum with a string
                return outstr
        else:
            checkvalue = index
        if self.enum:
            if (isinstance(self.enum, dict)):
                outstr = self.enum.get(checkvalue, str(index)) # returns the value itself if no key match
        if (checkvalue == self.default):
            outstr += " (Default)"
        return outstr
    
    def iswritable(self):
        return self.writable
        
    def check_value(self, value):
        """Validate the input value against the property's settings. Use to check a Set command input."""
        checkval = None
        
        # is it a writable property 
        if (not self.writable):
            return ("The property {} is not writable.".format(self.name))
        # first is it an int value
        if (value.isnumeric()):
            checkval = int(value)
        else:
            checkval = value  # will be a string
            
        # is the value in the enumerated set of keys?
        if (self.enum):
            # there is a defined range of values
            if isinstance(self.enum, range):
                if (not (checkval in self.enum)):
                    return ("The value {} is not valid for {}.\nIt must be in a {}.\n".format(checkval, self.name, self.enum))
                else:
                    return "OK"
            if isinstance(self.enum, dict):
                if (not self.enum.get(checkval, False)):  
                    return ("The value {} is not valid for {}.\nIt must be one of {}.\n".format(checkval, self.name, self.enum))
                else:
                    return "OK"
        # if there are no defined bounds, use the field byte size to check
        # one or two bytes must be an integer type. Check value type and range
        if (self.len <= 2):
            maxval = 2**(self.len * 8) - 1
            if ((not isinstance(checkval, int)) or (checkval >= maxval)):  
                return("The value {} is not valid for {}.\nIt must be an unsigned integer between 0 and {}.\n".format(checkval, self.name, maxval))
        # the one case where it has to be a string
        if (self.len == 8):
            if (not isinstance(value, str)):
                return("The value {} is not valid for {}.\nIt must be a string of less than {} characters.".format(checkval, self.name, self.len))
        return "OK"

class CMFRUSet:
    """An instance of a single FRU value """
    name = ''
    address = 0  # starting offset in FRU area
    len = 1
    default = None
    datatype = 'int'
    addr_lsb = ''
    addr_msb = ''
    
    def __init__(self, name, address, len, default):
        self.name = name # should be a string
        self.address = address # should be a hex number
        self.addr_msb = hex(self.address >> 8)
        self.addr_lsb = hex(self.address & 0x00FF)
        self.len = len   # should be an int        
        self.default = default 
        if len > 1:
            self.datatype = 'str'
    
 
# Lake Austin (AMC) BP types
LABPEnum = {
    0: 'No Backplane (0)',
    0x0025: '4x2.5 SAS/SATA Backplane (0x0025)',
    0x0045: '4x2.5 NVME Backplane (0x0045)',
    0x0185: '8xEDSFF NVME Backplane (0x0185)',
    0x0385: 'Universal SATA/NVME Backplane (0x0385)',
}

# enumeration dictionaries used for displaying human-readable output
enabdisab = {0: 'Disabled (0)', 1: 'Enabled (1)'}

lockenum = {0: 'Unlocked (0)', 1: 'Locked (1)'}
fanctlenum = {
    0: 'Manual (0)',
    1: 'Openloop (1)',
    2: 'Closedloop (2)'
}

fanctlschemeenum = {
    '00': 'FixedByUser',
    '02': 'Emergency',
    '04': 'Openloop',
    '08': 'Closedloop',
    '0b': 'Closed + Fixed',
    '0c': 'Closed + Open',
    
}
sledconfenum = {2: 'Half-width', 4: 'Double-high half-width'}
redpsuenum = {0: '2+0 Nonredundant', 1: '1+1 Redundant'}
powercapenum = {
    0: 'Disabled (0)', 
    1: 'Static, Spread equal (1)', 
    2: 'Reserved (2)', 
    3: 'Reserved (3)', 
    4: 'Reserved (4)', 
    5: 'Static, SledPowerLimit (5)'
}

fantypecfgenum = {
    0x09: 'Nine-fans, 3 Zones (0x09)',
    0x13: 'Four-fans, 1 Zone (0x13)',
    0x14: 'Five-fans, 2 Zones (+1 for PSU) (0x14)',
    0x15: 'Four-fans, 2 Zones (0x15)',
}

bppresenum = {0: 'No Backplane (0)', 1: 'Backplane Present (1)'}

reqpsusxenum = {1: '1 PSU Required', 2: '2 PSUs Required'}

bpenum = {
    0: 'No Backplane (0)',
    0x303D: '3x3.5 SAS/SATA Backplane (0x303D)',
    0x303E: '6x2.5 SAS/SATA Backplane (0x303E)',
    0x303B: '6x2.5 4xSAS/SATA +2x NVME/Universal Backplane (0x303B)',
    0x303F: '6x2.5 2x2 NVME only Backplane (0x303F)',
}

sledcfgenum = {
    0x0: 'Unknown',
    0x1: 'FullWidth',
    0x2: 'HalfWidth',
    0x3: 'ThirdWidth',
    0x4: 'DblHighHalf',
    0x5: 'G5.5 Half',
    0x6: 'G5.5 Full',
}
hubblechassisenum = {
    0x00: 'Not Set (0)',
    0x1c: 'Mercury (0x1c)',
    0x56: 'Roadster (0x56)',
    0x57: 'Steeda (0x57)',
}
lkaustinchassisenum = {
    0x00: 'Not Set (0)',
    0x65: 'Marine Creek (0x65)',
    0xC4: 'Buffalo Creek ((0xC4)',
}

fwupdatestateenum = {
    '00': "No Status. FW is OK",
    '01': "FW Image Corrupted",
    '02': "Fan Table image corrupted",
    '03': "Firmware update failed",
    '04': "Fan Table update failed",
    '05': "CM FW Update in progress",
    '06': "PSU FW Update in progress",
    '07': "CM FW Downgrade blocked.",
    '08': "PSU Update-Sleds are not powered off.",
    'ff': "No update action",
}

# Definition structures for system value lookup

# CMConfigInfo is different from the ConfigSettings 
# since there is no ID byte for each value
# the ID is the byte position in the response data
# the enum value is 
CMConfigInfo = {
    3: CMInfoSet("CM FW Version", 3, 2, 'ver'),
    5: CMInfoSet("Temp Table Version", 5, 2, 'ver'),
    7: CMInfoSet("Rack ID", 7, 1, 'int'),
    8: CMInfoSet("Chassis ID", 8, 1, 'int'),
    9: CMInfoSet("Sled ID", 9, 1, 'int'),
    10: CMInfoSet("Sled Conf", 10, 1, 'enum', sledcfgenum),
    11: CMInfoSet("LED Support", 11, 1, 'bit'),
    12: CMInfoSet("Temp Sensor Support", 12, 1, 'bit'),    
    13: CMInfoSet("Inlet Temp UNC Th", 13, 1, 'int'),
    14: CMInfoSet("Inlet Temp UC Th", 14, 1, 'int'),
    15: CMInfoSet("Exhaust Temp UNC Th", 15, 1, 'int'),
    16: CMInfoSet("Exhaust Temp UC Th", 16, 1, 'int'),
    17: CMInfoSet("Power Mon Support", 17, 1, 'bit'),
    18: CMInfoSet("PSU Info Support", 18, 1, 'bit'),
    19: CMInfoSet("HDD Status Support", 19, 1, 'bit'),
    20: CMInfoSet("HDD Num Support", 20, 1, 'int'),
    21: CMInfoSet("Fan Control Support", 21, 1, 'bit'),
    22: CMInfoSet("ChasID/ThermThrt Spt", 22, 1, 'bit'),
    23: CMInfoSet("Fan Types", 23, 1, 'int'),
    24: CMInfoSet("Number of Type1 Fans", 24, 1, 'int'),
    25: CMInfoSet("Type1Fan Nrm Read", 25, 1, 'int'),
    26: CMInfoSet("Type1Fan Nrm Max Read", 26, 1, 'int'),
    27: CMInfoSet("Type1Fan Nrm Min Read", 27, 1, 'int'),
    28: CMInfoSet("Type1Fan UC Threshold", 28, 1, 'int'),
    29: CMInfoSet("Type1Fan LC Threshold", 29, 1, 'int'),
}

CMSensorInfo = {
    3: CMInfoSet("FW Update Status", 3, 1, 'enum', fwupdatestateenum),
    4: CMInfoSet("Chassis Inlet Temp", 4, 1, 'signint'),
    5: CMInfoSet("Chassis Exhaust Temp", 5, 1, 'signint'),
    6: CMInfoSet("Sled Power Reading", 6, 2, 'int'),
    8: CMInfoSet("Sled Iin Amps Reading", 8, 1, 'int'),
    9: CMInfoSet("Sled Vin Volt Reading", 9, 1, 'int'),
    10: CMInfoSet("PSU Presence", 10, 1, 'bit'),
    11: CMInfoSet("PSU Fault", 11, 1, 'bit'),
    12: CMInfoSet("PSU1 Pout", 12, 2, 'int'),
    14: CMInfoSet("PSU2 Pout", 14, 2, 'int'), 
    16: CMInfoSet("PSU3 Pout", 16, 2, 'int'), 
    18: CMInfoSet("PSU4 Pout", 18, 2, 'int'), 
    20: CMInfoSet("PSU5 Pout", 20, 2, 'int'), 
    22: CMInfoSet("PSU6 Pout", 22, 2, 'int'), 
    24: CMInfoSet("PSU7 Pout", 24, 2, 'int'), 
    26: CMInfoSet("PSU8 Pout", 26, 2, 'int'), 
    28: CMInfoSet("Chass ID LED Sts", 28, 1, 'int'), 
    29: CMInfoSet("Chass Fault LED Sts", 29, 1, 'int'), 
    30: CMInfoSet("PSU AC Loss", 30, 1, 'bit'), 
    31: CMInfoSet("Reserved", 31, 1, 'int'),
    32: CMInfoSet("Fan Control Scheme", 32, 1, 'enum', fanctlschemeenum),
    # leave off the fan speeds for now
}

CMPSUInfo = {
    3: CMInfoSet("PSU Mismatch Snsr", 3, 1, 'bit'),
    4: CMInfoSet("PSU Redund Snsr", 4, 1, 'bit'), 
    5: CMInfoSet("PSU Config - X", 5, 1, 'int'),
    6: CMInfoSet("PSU Config - N", 6, 1, 'int'),
    7: CMInfoSet("PSU1 MAX_POUT", 7, 2, 'int'),
    9: CMInfoSet("PSU2 MAX_POUT", 9, 2, 'int'),
    11: CMInfoSet("PSU3 MAX_POUT", 11, 2, 'int'),
    13: CMInfoSet("PSU4 MAX_POUT", 13, 2, 'int'),
    15: CMInfoSet("PSU5 MAX_POUT", 15, 2, 'int'),
    17: CMInfoSet("PSU6 MAX_POUT", 17, 2, 'int'),
    19: CMInfoSet("PSU7 MAX_POUT", 19, 2, 'int'),
    21: CMInfoSet("PSU8 MAX_POUT", 21, 2, 'int'),
    # more PSUs are possible but no systems have that many
}

# another byte position type of data structure,
# these are returned from Get Device Info
CMDeviceIDInfo = {
    7: CMInfoSet("Device ID", 7, 1, 'int'),
    8: CMInfoSet("Device Rev", 8, 1, 'int'),
    9: CMInfoSet("FW Main Version", 9, 2, 'ver'),
    11: CMInfoSet("IPMI Version", 11, 1, 'int'),
    12: CMInfoSet("Addl Device Support", 12, 1, 'bit'),
    13: CMInfoSet("Mfg ID", 13, 3, 'int'),
    16: CMInfoSet("Product ID", 16, 2, 'int'),
    18: CMInfoSet("FW Aux Version", 18, 4, 'ver'),
}

# Defines the range of valid properties per CM version
# main key is CM major version
# second key is CM minor version
# * matches all minor versions.
CMValidConfigSettings = {
    '1': {'>=70': range(1,30)},
    '2': {'*': range(1,30)},
    '3': {'*': range(1,30)},
}

CMValidHiddenConfigSettings = {
    '1': {'<70': range(1,2), '>=70': range(1,3)},
    '2': {'<40': range(1,5), '>=40': range(1,6)},
    '3': {'<5': range(1,5), '>=5': range(1,6)},
}

CMHubbleConfigSettings = {
    1: CMConfigSet("LockInternalUseArea", 1, 1, lockenum, 0, True),
    2: CMConfigSet("FanControlMode", 2, 1, fanctlenum, 2, True),
    3: CMConfigSet("FanSpeedSetting", 3, 1, range(0,101), 80, True),
    4: CMConfigSet("FanTypeConfig", 4, 1, fantypecfgenum, 0x13, False),
    5: CMConfigSet("SledConfig", 5, 1, sledconfenum, 2, False),
    6: CMConfigSet("FanZones", 6, 1, {1: 'One zone (1)'}, 1, False),
    7: CMConfigSet("RequiredPSUsX", 7, 1, reqpsusxenum, 2, False),
    8: CMConfigSet("RedundantPSUsN", 8, 1, redpsuenum, 0, True),
    9: CMConfigSet("MaxFanPwr", 9, 1, None, 100, False),  # only for Cosmos
    10: CMConfigSet("MaxHddChasPwr", 10, 1, None, 200, False),  # only for Cosmos
    11: CMConfigSet("MaxCmChasPower", 11, 1, None, 50, False),  # only for Cosmos
    12: CMConfigSet("InletTempUpNCthres", 12, 1, None, 45, True),
    13: CMConfigSet("InletTempUpCCritThres", 13, 1, None, 55, True),
    14: CMConfigSet("MaxSledCount", 14, 1, range(1,5), 4, True),
    15: CMConfigSet("FanNormalReading", 15, 1, None, 0x10, True),
    16: CMConfigSet("FanUpCritReading", 16, 1, None, 0xfa, True),
    17: CMConfigSet("FanLowCritReading", 17, 1, None, 1, True),
    18: CMConfigSet("SledPowerLimit1", 18, 2, range(0,1001), 500, True),
    19: CMConfigSet("SledPowerLimit2", 19, 2, range(0,1001), 500, True),
    20: CMConfigSet("SledPowerLimit3", 20, 2, range(0,1001), 500, True),
    21: CMConfigSet("SledPowerLimit4", 21, 2, range(0,1001), 500, True),
    22: CMConfigSet("ChassisPowerLimit", 22, 2, range(0,4001), 2000, True),
    23: CMConfigSet("PowerCapActions", 23, 1, None, 0, False),  # not supported by iDrac
    24: CMConfigSet("ChassisPowerCap", 24, 1, powercapenum, 0, True),
    25: CMConfigSet("ChassisServiceTag", 25, 8, None, "", True),
    26: CMConfigSet("FTREnable", 26, 1, enabdisab, 1, True),
    27: CMConfigSet("BpPresent", 27, 1, bppresenum, 0, True),
    28: CMConfigSet("BpId", 28, 2, bpenum, 0x303F, True),
    29: CMConfigSet("BVMSetting", 29, 1, enabdisab, 1, True),
    30: CMConfigSet("CableAmpLimit", 30, 1, range(0,20), 0, False),  # added in v3.23, made read-only in v3.30
}

CMLkAustinConfigSettings = CMHubbleConfigSettings.copy()
CMLkAustinConfigSettings[4] = CMConfigSet("FanTypeConfig", 4, 1, fantypecfgenum, 0x14, False)
CMLkAustinConfigSettings[9] = CMConfigSet("GridChassisICLEnable", 9, 1, enabdisab, 0, False)
CMLkAustinConfigSettings[10] = CMConfigSet("ReserveByte2", 10, 1, None, 0, False)
CMLkAustinConfigSettings[11] = CMConfigSet("ReserveByte3", 11, 1, None, 0, False)
CMLkAustinConfigSettings[18] = CMConfigSet("GridICL", 18, 2, None, 0, False)
CMLkAustinConfigSettings[19] = CMConfigSet("ChassisICL", 19, 2, None, 0, False)
CMLkAustinConfigSettings[20] = CMConfigSet("ReservedWord3", 20, 2, None, 0, False)
CMLkAustinConfigSettings[21] = CMConfigSet("ReservedWord4", 21, 2, None, 0, False)
CMLkAustinConfigSettings[28] = CMConfigSet("BpId", 28, 2, LABPEnum, 0, True)
CMLkAustinConfigSettings[30] = CMConfigSet("CableAmpLimit", 30, 1, range(0,20), 0, True)  # writable in AMC still


CMHubbleFRUSettings = {
    0x54: CMFRUSet('ChassisPartNumber', 0x54, 9, '0KJDD7X01'),
    0x5E: CMFRUSet('ChassisSerialNumber', 0x5E, 9, ''),
    0x77: CMFRUSet('ChassisBoardManufacturer', 0x77, 32, 'Dell'),
    0x98: CMFRUSet('ChassisBoardProductName', 0x98, 16, 'C6400 CM Board'),
    0xAA: CMFRUSet('ChassisBoardPartNumber', 0xAA, 9, '07NN9GX01'),
    0xB5: CMFRUSet('ChassisBoardSerialNumber', 0xB5, 23, ''),
    0xCD: CMFRUSet('ChassisFirstPowerOn', 0xCD, 8, ''),
    0xDC: CMFRUSet('ChassisManufacturer', 0xDC, 32, 'Dell'),
    0xFD: CMFRUSet('ChassisModel', 0xFD, 24, 'PowerEdge C6400'),
    0x116: CMFRUSet('ChassisDescription', 0x116, 30, 'PH4A88H-PWREDG,CE,C6400'),
    0x135: CMFRUSet('ChassisProductVersion', 0x135, 3, 'A00'),
    0x139: CMFRUSet('ChassisServiceTag', 0x139, 9, ''),
    0x143: CMFRUSet('ChassisAssetTag', 0x143, 20, ''),
}

CMLkAustinFRUSettings = {
    0x54: CMFRUSet('ChassisPartNumber', 0x54, 9, '0KJDD7X01'),
    0x5E: CMFRUSet('ChassisSerialNumber', 0x5E, 9, ''),
    0x77: CMFRUSet('ChassisBoardManufacturer', 0x77, 32, 'Dell'),
    0x98: CMFRUSet('ChassisBoardProductName', 0x98, 16, 'C6600 CM Board'),
    0xAA: CMFRUSet('ChassisBoardPartNumber', 0xAA, 9, '05V6V5X01'),
    0xB5: CMFRUSet('ChassisBoardSerialNumber', 0xB5, 23, ''),
    0xCD: CMFRUSet('ChassisFirstPowerOn', 0xCD, 8, ''),
    0xDC: CMFRUSet('ChassisManufacturer', 0xDC, 32, 'Dell'),
    0xFD: CMFRUSet('ChassisModel', 0xFD, 24, 'PowerEdge C6600'),
    0x116: CMFRUSet('ChassisDescription', 0x116, 30, 'PH2671E-PWREDG,CE,C6600'),
    0x135: CMFRUSet('ChassisProductVersion', 0x135, 3, 'A00'),
    0x139: CMFRUSet('ChassisServiceTag', 0x139, 9, ''),
    0x143: CMFRUSet('ChassisAssetTag', 0x143, 20, ''),
}


CMHubbleHiddenSettings = {
    1: CMConfigSet('ChassisID', 1, 1, hubblechassisenum, 0x1C, True),
    2: CMConfigSet('AllowFWDowngrade', 2, 1, enabdisab, 0, True),
    3: CMConfigSet('Connector_Max_Threshold', 3, 2, {}, 0, False),
    4: CMConfigSet('GoldenChassis', 4, 1, enabdisab, 0, True),
    5: CMConfigSet('Fixed_FTB', 5, 1, enabdisab, 0, True),
    6: CMConfigSet('Manifest_Index_Number', 6, 1, None, 0, True),
}

CMLkAustinHiddenSettings = {
    1: CMConfigSet('ChassisID', 1, 1, lkaustinchassisenum, 0x65, True),
    2: CMConfigSet('AllowFWDowngrade', 2, 1, enabdisab, 0, True),
    3: CMConfigSet('Connector_Max_Threshold', 3, 2, {}, 0, False),
    4: CMConfigSet('GoldenChassis', 4, 1, enabdisab, 0, True),
    5: CMConfigSet('Fixed_FTB', 5, 1, enabdisab, 0, True),
    6: CMConfigSet('Manifest_Index_Number', 6, 1, None, 0, True),
}


# completion code lookup tables for select commands
CMChasCfgCompCodes = {
    '00': 'Success',
    '80': 'BMC has not received Set Chassis Configuration.',
    '81': 'CM has been offline for 10 secs or more.',
}

CMConfigCompCodes = {
    '00': 'Success',
    '80': 'Version does not match request',
    '81': 'Invalid Property ID or value sent in request',
    '82': 'Invalid Static Key',
    '83': 'Invalid Passcode'
}


# search the list of Hidden Config Properties for the given name.
def FindHiddenConfigByName(HiddenSettings, name):
    for id in HiddenSettings:
        if (HiddenSettings[id].name.lower() == name.lower()):
            return HiddenSettings[id]
    return None
    
# search the list of Config Properties for the given name.
def FindConfigByName(ConfigSettings, name):
    for id in ConfigSettings:
        if (ConfigSettings[id].name.lower() == name.lower()):
            return ConfigSettings[id]
    return None   

#Search the list of FRU Properties for the name match
def FindFRUByName(FRUSettings, name):
    for id in FRUSettings:
        if (FRUSettings[id].name.lower() == name.lower()):
            return FRUSettings[id]
    return None

def ConvertKey(key):
    bytekey = ""
    for c in key:
        bytekey += hex(ord(c)) + ' '
    bytekey = bytekey.strip()
    return bytekey

def ConvertPasscode(passbytes):
    bytepasscode = ""
    for c in passbytes:
        if (not c.startswith('0x')):
            bytepasscode += '0x' + c + ' '
        else:
            bytepasscode += c + ' '
    bytepasscode = bytepasscode.strip()
    return bytepasscode

# Each function that implements an interaction with the CM much handle the request and response.
# Actually calls GetChassisConfiguration
def CMGetVersion(args):
    """  Example
     01 cc 1b 01 46 01 00 00 00 01 02 00 01 2d 37 ff
     ff 08 c2 00 00 00 08 01 08 10 64 23 fa 01
    """
    # don't care what args are
    stdout = call_ipmitool('0x30 0x12')
    
    if (use_raw_output):
        return stdout

    outbytes = stdout.split()
    # check the completion code.  first byte but only if error
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"
        
    if ((len(outbytes) == 1) and (not (outbytes[0] == '01'))):  # there was an error completion code
        completion = CMChasCfgCompCodes.get(outbytes[0], 'Unknown response')
        return "Unsuccessful reponse: {} = {} ".format(outbytes[0], completion)
        
    # now parse the data
    output = "Chassis Info:\n"
    
    bytecnt = int(outbytes[2], 16)
    pos = 3 # next byte after the byte count
    value = ""
    fmtline = "{:22} = {:8}\n"
    while (pos < bytecnt + 3):
        cinfo = CMConfigInfo.get(pos, None)
        if (not cinfo):
            # for the undefined ones
            output += fmtline.format("Unknown", outbytes[pos])
            pos += 1
        else:
            value = cinfo.get_value(outbytes[pos:pos+cinfo.len])
            output += fmtline.format(cinfo.name, value)
            pos += cinfo.len
            if (cinfo.len > 2):
                output += "Invalid value definition: {}  Length: {}\n".format(cinfo.name, cinfo.len)
                pos += 1
    return output

def CMGetSensorInfo(args):
    """  Example
    01 d7 2a ff 19 00 00 00 00 00 03 00 00 00 20 00
    00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
    08 38 2c 37 2d 37 2c 37 2d 6b 19 48 61
    """
    # don't care what args are
    stdout = call_ipmitool('0x30 0x16')
    
    if (use_raw_output):
        return stdout

    outbytes = stdout.split()
    # check the completion code.  first byte but only if error
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"
        
    if ((len(outbytes) == 1) and (not (outbytes[0] == '01'))):  # there was an error completion code
        completion = CMChasCfgCompCodes.get(outbytes[0], 'Unknown response')
        return "Unsuccessful reponse: {} = {} ".format(outbytes[0], completion)
        
    # now parse the data
    output = "Get Sensor Info:\n"
    
    bytecnt = int(outbytes[2], 16)
    pos = 3 # next byte after the byte count
    value = ""
    fmtline = "{:22} = {:8}\n"
    while (pos < len(outbytes)):
        cinfo = CMSensorInfo.get(pos, None)
        if (not cinfo):
            # for the undefined ones
            output += fmtline.format("Unknown", outbytes[pos])
            pos += 1
        else:
            verbose("GetSensorInfo: pos = {}".format(pos))
            value = cinfo.get_value(outbytes[pos:pos+cinfo.len])
            output += fmtline.format(cinfo.name, value)
            pos += cinfo.len
            if (cinfo.len > 2):
                output += "Invalid value definition: {}  Length: {}\n".format(cinfo.name, cinfo.len)
                pos += 1
    return output


def BoardPNAndRev():
    boardpn = ""
    boardrev = ""
    boardpndata = call_ipmitool("{} 0x11 0x0 0xaa 0x0 0x09 {}".format(log_preamble, ending))
    
    databytes = boardpndata.split(" ")
    if (len(databytes) == 0):
        return "Unknown", "Unknown"
    for ch in databytes[8:15]:
        boardpn += chr(int(ch, 16))
    for ch in databytes [15:-1]:
        boardrev += chr(int(ch, 16))
        
    return boardpn.strip(), boardrev.strip()


def CMGetConfig(args, ini_output=False):
    # Get the FRU CM Board PN/Rev to determine the chassis type and HW level (UT/PT/ST)
    if (ini_output):
        verbose("CMGetConfig: Using INI style output.")
    
    boardpn, boardrev = BoardPNAndRev()
    platname = ""
    progressstring = "Getting Configuration Properties"
    
    print(progressstring, end='\r')
    verbose("Chassis Board PN = {}, rev = {}".format(boardpn, boardrev))
    if (boardpn in CMBoardPN[SptChassisHubble]):
        CMConfigSettings = CMHubbleConfigSettings
        platname = "Hubble C6400"
        verbose("Using Hubble Config Settings")
    elif (boardpn in CMBoardPN[SptChassisLkAustin]):
        CMConfigSettings = CMLkAustinConfigSettings
        platname = "Lake Austin C6600"
        verbose("Using Lake Austin Config Settings")
    else:
        return "CM Board PN {} is not implemented.".format(boardpn)

    # get all the config items, don't care about the args
    stdout = call_ipmitool("{} 0xa0 0x0 0xff {}".format(config_preamble, ending))
    
    print(progressstring + '.', end='\r')
    if (use_raw_output):
        return stdout

    outbytes = stdout.split()
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"
   
    # check the completion code
    completion = CMConfigCompCodes.get(outbytes[completion_code_idx], 'Unknown response')
    if (not (completion == 'Success')):
        return "Unsuccessful reponse: {} = {} ".format(outbytes[completion_code_idx], completion)
    print(progressstring + '..', end='\r')
    # now parse the config data
    if (ini_output):
        output = "[ConfigProperties]\n"
        output += "Board PN = {}\nPlatform Name = {}\n".format(boardpn, platname)
    else:
        output = "CM Config Properties: Board PN {} Platform Name {}\n".format(boardpn, platname)
    settingscount = int(outbytes[8], 16)
    position = 9  # byte after the number of properties
    for id in range(1, settingscount + 1):
        if (id != int(outbytes[position], 16)):
            print("---IDs not aligned at position {}".format(position))
            break
        else:
            position += 1  # increment past the ID byte
            if (CMConfigSettings[id].len == 1):
                numvalue = int(outbytes[position], 16)
                if (ini_output):
                    value = numvalue
                else:
                    value = CMConfigSettings[id].get_enum_val(numvalue)
            elif (CMConfigSettings[id].len == 2):
                # LSB is first in all of these
                numvalue = int(outbytes[position], 16) + int(outbytes[position+1], 16) * 0x100
                if (ini_output):
                    value = numvalue
                else:
                    value = CMConfigSettings[id].get_enum_val(numvalue)
            elif (CMConfigSettings[id].len == 8):
                # must be svctag, therefore string
                val = ""
                value = ""
                for offset in range(0,7): # 8th byte is a 00
                    val += bytes.fromhex(outbytes[position+offset]).decode('ascii')
                value = val.strip().strip('\0')
            else:
                value = ""
            #end if
            position += CMConfigSettings[id].len
            output += "{:22} = {:8}\n".format(CMConfigSettings[id].name, value)
        #end if
    #end for
    print(progressstring + '...')
    return output
    
def CMGetDeviceId(args):
    """ Example response
    20 1c c4 70 00 01 00 11 
    <BMC addr> <NetFN 0x7> ck1> <CMaddr> <rslun> <cmd> <CC> <devid 0x11 - 17> 
    00 03 17 02 00 a2
    <dev rev> <fw maj> <fw min> <IPMI ver> <Add DEv Spt bitflags> 
    02 00 00 00 00 00 00 00 be
    <Mf id 0, Mf id 1, mf id 2> <prodid 0, prodid 1> <auxfw 0, auxfw 1, auxfw 2, auxfw3> 
    """
    # get all the config items, don't care about the args
    stdout = call_ipmitool("{} 0x1 {}".format(app_preamble, ending))
    
    if (use_raw_output):
        return stdout

    outbytes = stdout.split()
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"
   
    # check the completion code
    completion = CMChasCfgCompCodes.get(outbytes[completion_code_idx], 'Unknown response')
    if (not (completion == 'Success')):
        return "Unsuccessful reponse: {} = {} ".format(outbytes[completion_code_idx], completion)
        
    # now parse the data
    output = "Device ID Info:\n"
    
    pos = SendMsgCmdResponseOffset # first byte of response data
    value = ""
    fmtline = "{:22} = {:8}\n"
    while (pos < (len(outbytes) - 1)):
        cinfo = CMDeviceIDInfo.get(pos, None)
        if (not cinfo):
            # for the undefined ones
            output += fmtline.format("Unknown", outbytes[pos])
            pos += 1
        else:
            value = cinfo.get_value(outbytes[pos:pos+cinfo.len])
            output += fmtline.format(cinfo.name, value)
            pos += cinfo.len
    return output

def CMGetPasscode(arglist):
    cmdhelp = CMCommandHelpDetailed['GetPasscode'.lower()]
    key = ""
    if (arglist and (len(arglist) > 0)):
        for arg in arglist:
            if ('key=' in arg):
                value = arg.split('=')[1]
                key = value
            else:
                return(cmdhelp)
        
    if ((not key) or (not (len(key) == 8))):
        return(cmdhelp)
    bytekey = ""
    for c in key:
        bytekey += hex(ord(c)) + ' '
           
    command = "{} 0x01 {} {}".format(hidden_config_preamble, bytekey, ending)
    stdout = call_ipmitool(command)

    if (use_raw_output):
        return stdout

    outbytes = stdout.split()
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"
    
    # check the completion code
    completion = CMConfigCompCodes.get(outbytes[completion_code_idx], 'Unknown response')
    if (not (completion == 'Success')):
        return "Unsuccessful reponse: {} = {} ".format(outbytes[completion_code_idx], completion)

    # get the passcode bytes
    output = "Passcode =  "    
    # output the passcode as 0x hex
    for i in range(7,15):
        output += "0x{},".format(outbytes[i])
    output = output.strip(',')
    
    return output
    
# Get ALL hidden config values
def CMGetHiddenConfig(arglist):
    cmdhelp = CMCommandHelpDetailed['GetHiddenConfig'.lower()]
    key = ""
    passcode = ""
    boardpn, boardrev = BoardPNAndRev()
    platname = ""
    
    verbose("Chassis Board PN = {}, rev = {}".format(boardpn, boardrev))
    if (boardpn in CMBoardPN[SptChassisHubble]):
        CMHiddenSettings = CMHubbleHiddenSettings
        platname = "Hubble C6400"
        verbose("Using Hubble Hidden Config Settings")
    elif (boardpn in CMBoardPN[SptChassisLkAustin]):
        CMHiddenSettings = CMLkAustinHiddenSettings
        platname = "Lake Austin C6600"
        verbose("Using Lake Austin Hiden Config Settings")
    else:
        return "CM Board PN {} is not implemented.".format(boardpn)
    
    if (arglist and (len(arglist) > 0)):
        for arg in arglist:
            if ('key=' in arg):
                value = arg.split('=')[1]
                key = value
            elif ('passcode=' in arg):
                value = arg.split('=')[1]
                passcode = value
            else:
                return(cmdhelp)
        
    if ((not key) or (not passcode)):
        return(cmdhelp)
        
    #print("Static key = {}.  Passcode = {}".format(arglist[0], arglist[1]))
    if (not (len(key) == 8)):
        return("The static key must be exactly 8 characters")
    bytekey = ConvertKey(key)

    passbytes = passcode.strip(',').split(',')
    if (not (len(passbytes) == 8)):
        return("The passcode must have must be exactly 8 bytes, separated by commas with '0x' preceding each byte in hex.")
    bytepasscode = ConvertPasscode(passbytes)
    
    # Cmd = 0x02  ConfigStructVersion = 0x00  NumberofProperties = 0xff (ALL)
    command = "{} 0x02 0x00 {} {} 0xff {}".format(hidden_config_preamble, bytekey, bytepasscode, ending)
    stdout = call_ipmitool(command)

    if (use_raw_output):
        return stdout
    
    # check the completion codes
    outbytes = stdout.split()
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"
    
    completion = CMConfigCompCodes.get(outbytes[completion_code_idx], 'Unknown response')
    if (not (completion == 'Success')):
        return "Unsuccessful reponse: {} = {} ".format(outbytes[completion_code_idx], completion)
    
    # now parse the config data
    output = "CM Hidden Config Settings:\n"
    settingscount = int(outbytes[8], 16)
    position = 9  # byte after the number of properties
    for id in range(1, settingscount + 1):
        if (id != int(outbytes[position], 16)):
            print("---IDs not aligned at position {}".format(position))
            break
        else:
            position += 1  # increment past the ID byte
            if (CMHiddenSettings[id].len == 1):
                numvalue = int(outbytes[position], 16)
                value = CMHiddenSettings[id].get_enum_val(numvalue)
            elif (CMHiddenSettings[id].len == 2):
                # LSB is first in all of these
                numvalue = int(outbytes[position], 16) + int(outbytes[position+1], 16) * 0x100
                value = CMHiddenSettings[id].get_enum_val(numvalue)
            else:
                value = ""
            #end if
            position += CMHiddenSettings[id].len
            output += "{:22} = {:8}\n".format(CMHiddenSettings[id].name, value)
        #end if
    #end for
    return output

def CMGetLog(arglist):
    cmdhelp = CMCommandHelpDetailed['GetLog'.lower()]
    offset = 0
    tail = 0
    outfilename = ""
    if (arglist and (len(arglist) >= 1)):
        for arg in arglist:
            if ('offset=' in arg):
                value = arg.split('=')[1]
                offset = int(value) * CMLogOffsetIncrement
            elif ('outfile=' in arg):
                value = arg.split('=')[1]
                outfilename = value
            elif ('tail=' in arg):  # start from tail blocks from the end
                value = arg.split('=')[1]
                tail = int(value) * CMLogOffsetIncrement
            else:
                print(cmdhelp)
                return ""
    
    #result = []
    # get the number of 64-byte log blocks
    stdout = call_ipmitool("{} 0x10 0x1 0xff".format(log_preamble))
    if (len(stdout) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"
    
    log_cnt = (int((stdout[25:27]) + (stdout[22:24]),16))
    if ((log_cnt / CMLogOffsetIncrement) >= CMLogMaxLines):
        log_cnt -= CMLogOffsetIncrement   # subtract one line to suppress the beginning of the circular log if the log is full
    verbose("Got {} log bytes, {} lines of {} bytes.".format(log_cnt, log_cnt / CMLogOffsetIncrement, CMLogOffsetIncrement))
    if (tail):
        offset = log_cnt - tail
        
    outfile = None
    if (outfilename):
        print("Writing CM Log to {} Starting from offset byte {}.".format(outfilename, offset))
        outfile = open(outfilename, 'w+')
        
    while (offset < log_cnt):
        offsetlsb = "0x" + (format(offset,'04x'))[2:]
        offsetmsb = "0x" + str(format(offset,'04x'))[:-2]  # make sure it comes out as string
        stdout = call_ipmitool("{} 0x11 0x1 {} {} 0x40 0xff".format(log_preamble, offsetlsb, offsetmsb))
        
        # combine into one line of hex bytes, no spaces or newlines
        line1 = ""
        for line in stdout:
            line1 += line.replace(' ','').replace('\n', '').replace('\\r\\n\'','').replace('b\'','')
        # remove remaining bad chars
        line2 = line1.replace('n','').replace('\\','').replace("'",'').upper()
        line3 = line2[16:-2]   # cut out header and tailer bytes, just data is left
        ascii_string = str(base64.b16decode(line3))[2:-1]
        
        #output to console
        print (ascii_string)
        if (outfile):
            outfile.write(ascii_string + '\n')
        offset += CMLogOffsetIncrement
    
    if (outfile):
        outfile.close()
        
    return ""

# used by the ParseLog funbction to process the data from string containing 0xXX bytes to actual ASCII data
def ParseLogLine(line):
    # need to cut off the first 2 bytes which is just the number of bytes returned
    leadbytes = '0x00 0x40'
    firstcut = line.find(leadbytes)
    if (firstcut > -1):
        firstcut = len(leadbytes)
    # take the slice after and remove '0x' from all
    dataline = line[(firstcut+1):].replace('0x','')
    try:
        output = bytes.fromhex(dataline).decode()
        print(output)
    except:
        print("can't process this line to ascii")
        return ""
    return output + '\n'
        
def CMParseLog(arglist):
    cmdhelp = CMCommandHelpDetailed['ParseLog'.lower()]
    logfile = None
    outfile = None
    errmsg = ""
    outfilename = ""
    logfilename = ""
    if (arglist and (len(arglist) >= 1)):
        for arg in arglist:
            if ('logfile=' in arg):
                value = arg.split('=')[1]
                logfilename = value
            elif ('outfile=' in arg):
                value = arg.split('=')[1]
                outfilename = value
            else:
                print("Invalid Argument: {}".format(arg.split('=')[0]))
                print(cmdhelp)
                return ""
                
    if (logfilename):
        try:
            logfile = open(logfilename, 'r')
        except:
            print("Unable to open logfile {} for reading.".format(logfilename))
            return ""
    else:
        print("The logfile parameter is required for this command.")
        return ""
    
    if (outfilename):
        try:
            outfile = open(outfilename,  'w+')
        except:
            print("Unable to open output file  {} for writing".format(outputfilename))
            return ""   
    line = logfile.readline()
    section = ''
    while (line):
        # build a section with the lines up to the one that is only '\n'
        if (line.startswith('Sending') or line.startswith('Sent') or line.startswith('Response') or line.startswith('Data')):
            section = ''
        elif (line.startswith('scbmctestfunc: Error')):
            outfile.write('Line missing due to comm error\n')
            section = ''
        elif (line != '\n'):
            section += line.strip() + ' '
        else:
            # parse the section as one output line
            if (section):
                outfile.write(ParseLogLine(section))
                section = ''
        line = logfile.readline()
    if (section):
        #write the last bit of data out
        outfile.write(ParseLogLine(section))
        
    #close out
    if (logfile):
        logfile.close()
    if (outfile):
        outfile.close()
    return ""
    
def CMSetConfig(arglist):
    cmdhelp = CMCommandHelpDetailed['SetConfig'.lower()]
    property = None
    propval = None
    errmsg = ""
    
    boardpn, boardrev = BoardPNAndRev()
    platname = ""
    verbose("Chassis Board PN = {}, rev = {}".format(boardpn, boardrev))
    if (boardpn in CMBoardPN[SptChassisHubble]):
        CMConfigSettings = CMHubbleConfigSettings
        platname = "Hubble C6400"
        verbose("Using Hubble Config Settings")
    elif (boardpn in CMBoardPN[SptChassisLkAustin]):
        CMConfigSettings = CMLkAustinConfigSettings
        platname = "Lake Austin C6600"
        verbose("Using Lake Austin Config Settings")
    else:
        return "CM Board PN {} is not implemented.".format(boardpn)

    if (arglist and (len(arglist) > 0)):
        for arg in arglist:
            if (len(arg.split('=')) < 2):  # argument is not well-formed
                errmsg = "The argument name and value must be separated by an = sign -> '{}'\n".format(arg)
                return (errmsg + cmdhelp)
            propname,propval = arg.strip().split('=')
            property = FindConfigByName(CMConfigSettings, propname)
            if (not property):
                errmsg = "No Config Property named {} was found\n".format((arg.split('='))[0])
                return (errmsg + cmdhelp)
            errmsg = property.check_value(propval)
            if (not (errmsg == "OK")):
                return (errmsg + cmdhelp)
    else:
        return (cmdhelp)
    
    verbose("Config Property {} will be set to {}".format(property.name, property.get_enum_val(propval)))
    if (property.len == 1):
        setval = int(propval)
        lsb = "0x" + (format(setval,'04x'))[2:]  # just make sure we only get lower byte
        propvalbytes = lsb
    elif (property.len == 2):
        setval = int(propval)
        lsb = "0x" + (format(setval,'04x'))[2:]
        msb = "0x" + str(format(setval,'04x'))[:-2]  # make sure it comes out as string
        propvalbytes = "{} {}".format(lsb, msb)   # lsb goes first I think
    elif (property.len == 8):
        # service tag is special
        tag = propval.upper()
        propvalbytes = ""
        for i in range(0,len(tag)):
            propvalbytes += hex(ord(tag[i])) + ' '
        for i in range(len(tag), 8):
            propvalbytes += '0x20 '  # pad with spaces
        propvalbytes = propvalbytes.strip()
    else:
        return ("The property {} has an invalid byte length defined: {}.".format(property.name, property.len))
        
    stdout = call_ipmitool("{} 0xa1 0x1 0x1 {} {} {}".format(config_preamble, property.id, propvalbytes, ending))
    
    if (use_raw_output):
        return stdout

    outbytes = stdout.split()
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"

    # check the completion code
    completion = CMConfigCompCodes.get(outbytes[completion_code_idx], 'Unknown response')
    if (not (completion == 'Success')):
        return "Unsuccessful reponse: {} = {} ".format(outbytes[completion_code_idx], completion)
    
    return completion


def CMGetFRU(args, ini_output = False):
    cmdhelp = CMCommandHelpDetailed['GetFRU'.lower()]
    property = None
    propval = None
    errmsg = ""
    progressstring = "Getting FRU Settings"
    
    print(progressstring, end='\r')
    
    # Get the FRU CM Board PN/Rev to determine the chassis type and HW level (UT/PT/ST)
    boardpn, boardrev = BoardPNAndRev()
    platname = ""
    
    verbose("Chassis Board PN = {}, rev = {}".format(boardpn, boardrev))
    if (boardpn in CMBoardPN[SptChassisHubble]):
        CMFRUSettings = CMHubbleFRUSettings
        platname = "Hubble C6400"
        verbose("Using Hubble Config Settings")
    elif (boardpn in CMBoardPN[SptChassisLkAustin]):
        CMFRUSettings = CMLkAustinFRUSettings
        platname = "Lake Austin C6600"
        verbose("Using Lake Austin Config Settings")
    else:
        return "CM Board PN {} is not implemented.".format(boardpn)
    
    progressstring += '.'
    print(progressstring, end='\r')
    #Have to loop through all the addresses since there isn't one command to get all data
    if (ini_output):
        output = "[FRUSettings]\n"
        output += "Board PN = {}\nPlatform Name = {}\n".format(boardpn, platname)
    else:
        output = "CM FRU Settings: Board PN {} Platform Name {}\n".format(boardpn, platname)

    for fru in CMFRUSettings:
        progressstring += '.'
        print(progressstring, end='\r')
    
        stdout = call_ipmitool("{} 0x11 0x0 {} {} {} {}".format(log_preamble, CMFRUSettings[fru].addr_lsb, CMFRUSettings[fru].addr_msb, CMFRUSettings[fru].len, ending))
    
        outbytes = stdout.split()
        if (len(outbytes) == 0):
            # bad connection, message in stderr
            return "Ipmitool Error.  Verify HOST, user, and password are correct"
       
        # check the completion code
        completion = CMConfigCompCodes.get(outbytes[completion_code_idx], 'Unknown response')
        if (not (completion == 'Success')):
            return "Unsuccessful reponse: {} = {} ".format(outbytes[completion_code_idx], completion)    
      
        position = 8  # byte after the number of bytes
        
        # parse the data into ASCII string
        outstr = ''
        for mybyte in outbytes[position:-1]:
            outstr += bytes.fromhex(mybyte).decode('ascii')
        output += "{:26} = {}\n".format(CMFRUSettings[fru].name, outstr)
    #end for
    print(progressstring)

    return output    

def CMSetFRU(arglist):
    cmdhelp = CMCommandHelpDetailed['SetFRU'.lower()]
    property = None
    propval = None
    errmsg = ""
    CMFRUSettings = CMAMCFRUSettings
    
    if (arglist and (len(arglist) > 0)):
        for arg in arglist:
            if (len(arg.split('=')) < 2):  # argument is not well-formed
                errmsg = "The argument name and value must be separated by an = sign -> '{}'\n".format(arg)
                return (errmsg + cmdhelp)
            propname,propval = arg.split('=')
            property = FindFRUByName(CMFRUSettings, propname)
            if (not property):
                errmsg = "No FRU Value named {} was found\n".format((arg.split('='))[0])
                return (errmsg + cmdhelp)
    else:
        return (cmdhelp)

    # pad or trunc the string to fit required length
    setval = propval.ljust(property.len)
    if (len(propval) > property.len):
        verbose("Trimming the length of {} to {} characters".format(propval, property.len))
        setval = propval[0:property.len]
    verbose("CM FRU Property {} will be set to {}".format(property.name, setval))
    hexsetval = ''
    for letter in setval:
        hexsetval += hex(ord(letter)) + ' '
    stdout = call_ipmitool("{} 0x12 0x0 {} {} {} {}".format(log_preamble, property.addr_lsb, property.addr_msb, hexsetval, ending))    
    
    if (use_raw_output):
        return stdout

    outbytes = stdout.split()
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"

    # check the completion code
    completion = CMConfigCompCodes.get(outbytes[completion_code_idx], 'Unknown response')
    if (not (completion == 'Success')):
        return "Unsuccessful reponse: {} = {} ".format(outbytes[completion_code_idx], completion)
    return completion

def CMSaveConfig(arglist):
    # walk a list of CM Config properties andFRU Properties and set each one using SetConfig and SetFRU
    cmdhelp = CMCommandHelpDetailed['SaveConfig'.lower()]
    inifile = None
    completion = 'Success'
    
    # process arguments
    if (arglist and (len(arglist) > 0)):
        for arg in arglist:
            if (len(arg.split('=')) < 2):  # argument is not well-formed
                errmsg = "The argument name and value must be separated by an = sign -> '{}'\n".format(arg)
                return (errmsg + cmdhelp)
            argname,inifilename = arg.split('=')
            if (argname == 'inifile'):
                try:
                    inifile = open(inifilename, "wt")
                except:
                    return "Unable to open {} for writing.".format(inifilename)
                    
                if (not inifile):
                    return "Unable to open {} for writing.".format(inifilename)
            else:
                return (cmdhelp)
            #end if
        #end for
    else:
        return (cmdhelp)
    
    ini_output = True
    tempargs = []
    allconfigs = configparser.ConfigParser()
    verbose("Calling CMGetConfig with ini_output = True and parsing in ConfigParser")
    configout = CMGetConfig(tempargs, True)
    verbose(configout)
    allconfigs.read_string(configout)
    verbose("Calling CMGetFRU with ini_output = True and parsing in ConfigParser")
    fruout = CMGetFRU(tempargs, True)
    verbose(fruout)
    allconfigs.read_string(fruout)
    
    
    # make a new empty INI file parser
    reconfigprops = configparser.ConfigParser()
    # now loop through the dict of desired output settings and select the ones to save in reconfigprops
    for key in ReconfigProperties:
        if (not reconfigprops.has_section(key)):
            reconfigprops.add_section(key)
            verbose("Adding section {}".format(key))
        for prop in ReconfigProperties[key]:
            if (not allconfigs.has_section(key)):
                return ("The config data read from the system is missing the Section named {}.\n".format(key))
            propval = allconfigs.get(key, prop)
            verbose("Adding option {} to section {} with value {}".format(prop, key, propval))
            reconfigprops.set(key, prop, propval)
            
    verbose("Writing Config Properties and FRU Settings to {}".format(inifile))
    reconfigprops.write(inifile)
    
    return completion

    
def CMReconfig(arglist):
    # walk a list of CM Config properties and FRU Properties and set each one using SetConfig and SetFRU
    cmdhelp = CMCommandHelpDetailed['Reconfigure'.lower()]
    reconfigprops = None
    inifile = None
    completion = ''
    
    # process arguments
    if (arglist and (len(arglist) > 0)):
        for arg in arglist:
            if (len(arg.split('=')) < 2):  # argument is not well-formed
                errmsg = "The argument name and value must be separated by an = sign -> '{}'\n".format(arg)
                return (errmsg + cmdhelp)
            argname,inifilename = arg.split('=')
            if (argname == 'inifile'):
                try:
                    inifile = open(inifilename)
                except:
                    return "Unable to open {} for reading.".format(inifilename)
                    
                if (not inifile):
                    return "Unable to open {} for reading.".format(inifilename)
            else:
                return (cmdhelp)
            #end if
        #end for
    else:
        return (cmdhelp)

    # Validate the ini file format
    try:
        reconfigprops = configparser.ConfigParser()
        reconfigprops.read(inifilename)
    except:
        return("Unable to parse the INI file {}.\n".format(inifilename))
    
    verbose("reconfigprops Sections = {}".format(reconfigprops.sections()))
    # look for expected settings from ReconfigProperties and call the appropriate Set function
    for key in ReconfigProperties:
        if (not reconfigprops.has_section(key)):
            return("The INI file is missing the required section named {}.".format(key))
        for opt in ReconfigProperties[key]:
            try:
                optval = reconfigprops.get(key, opt)
            except:
                return("The INI file is missing the required option named {}".format(opt))
            myarg = ["{}={}".format(opt, optval)]
            if ('config' in key.lower()):
                verbose("Calling CMSetConfig with {}".format(myarg))
                completion = CMSetConfig(myarg)
            elif ('fru' in key.lower()):
                verbose("Calling CMSetFRU with {}".format(myarg))
                completion = CMSetFRU(myarg)               
            else:
                verbose("The key {} is unknown, ignoring these options.")
        # end for
    #end for
    
    return completion
    
def CMSetHiddenConfig(arglist):
    cmdhelp = CMCommandHelpDetailed['SetHiddenConfig'.lower()]
    key = ""
    passcode = ""
    
    boardpn, boardrev = BoardPNAndRev()
    platname = ""
    
    verbose("Chassis Board PN = {}, rev = {}".format(boardpn, boardrev))
    if (boardpn in CMBoardPN[SptChassisHubble]):
        CMHiddenSettings = CMHubbleHiddenSettings
        platname = "Hubble C6400"
        verbose("Using Hubble Hidden Config Settings")
    elif (boardpn in CMBoardPN[SptChassisLkAustin]):
        CMHiddenSettings = CMLkAustinHiddenSettings
        platname = "Lake Austin C6600"
        verbose("Using Lake Austin Hiden Config Settings")
    else:
        return "CM Board PN {} is not implemented.".format(boardpn)

    property = None
    propval = None
    if (arglist and (len(arglist) > 0)):
        for arg in arglist:
            if ('key=' in arg):
                value = arg.split('=')[1]
                key = value
            elif ('passcode=' in arg):
                value = arg.split('=')[1]
                passcode = value
            else:
                if (len(arg.split('=')) < 2):  # argument is not well-formed
                    errmsg = "The argument name and value must be separated by an = sign -> '{}'\n".format(arg)
                    return (errmsg + cmdhelp)
                propname,propval = arg.split('=')
                property = FindHiddenConfigByName(CMHiddenSettings, propname)
                if (not property):
                    errmsg = "No Hidden Config Property named {} was found\n".format((arg.split('='))[0])
                    return (errmsg + cmdhelp)
                errmsg = property.check_value(propval)
                if (not (errmsg == "OK")):
                    return (errmsg + cmdhelp)
    else:
        return (cmdhelp)
                
    # already checked the property name and value
    if ((not key) or (not passcode)):
        return(cmdhelp)

    if (not (len(key) == 8)):
        return("The static key must be exactly 8 characters.")
    bytekey = ConvertKey(key)

    passbytes = passcode.strip(',').split(',')
    if (not (len(passbytes) == 8)):
        return("The passcode must have must be exactly 8 bytes, separated by commas with '0x' preceding each byte in hex.")
    bytepasscode = ConvertPasscode(passbytes)
    
    verbose("Hidden Config Property {} will be set to {}".format(property.name, property.get_enum_val(propval)))
    
    if (property.len == 1):
        setval = int(propval)
        lsb = "0x" + (format(setval,'04x'))[2:]  # just make sure we only get lower byte
        propvalbytes = lsb
    elif (property.len == 2):
        setval = int(propval)
        lsb = "0x" + (format(setval,'04x'))[2:]
        msb = "0x" + str(format(setval,'04x'))[:-2]  # make sure it comes out as string
        #lsb = propval & 0x00FF
        #msb = (propval >> 8) & 0x00FF  # mask upper bytes just to make sure
        propvalbytes = "{} {}".format(lsb, msb)   # lsb goes first I think
    else:
        return ("The property {} has an invalid byte length defined: {}.".format(property.name, property.len))

    # Cmd = 0x03  ConfigStructVersion = 0x01, only one property to set
    command = "{} 0x03 0x01 {} {} 0x01 {} {} {}".format(hidden_config_preamble, bytekey, bytepasscode, property.id, propvalbytes, ending)
    stdout = call_ipmitool(command)

    if (use_raw_output):
        return stdout
    
    # check the completion codes
    outbytes = stdout.split()
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"

    completion = CMConfigCompCodes.get(outbytes[completion_code_idx], 'Unknown response')
    if (not (completion == 'Success')):
        return "Unsuccessful reponse: {} = {} ".format(outbytes[completion_code_idx], completion)

    return (completion)
    
def CMGetPSUInfo(arglist):
    """  Example output with 2 PSUs
    01 d9 08 00 00 02 00 1d 00 00 00
    """
    # don't care what args are
    stdout = call_ipmitool('0x30 0x1f')
    
    if (use_raw_output):
        return stdout

    outbytes = stdout.split()
    # check the completion code.  first byte but only if error
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"
        
    if ((len(outbytes) == 1) and (not (outbytes[0] == '01'))):  # there was an error completion code
        completion = CMChasCfgCompCodes.get(outbytes[0], 'Unknown response')
        return "Unsuccessful reponse: {} = {} ".format(outbytes[0], completion)
        
    # now parse the data
    output = "Get PSU Info:\n"
    
    bytecnt = int(outbytes[2], 16)
    pos = 3 # next byte after the byte count
    value = ""
    fmtline = "{:22} = {:8}\n"
    while (pos < bytecnt + 3):
        cinfo = CMPSUInfo.get(pos, None)
        if (not cinfo):
            # for the undefined ones
            output += fmtline.format("Unknown", outbytes[pos])
            pos += 1
        else:
            value = cinfo.get_value(outbytes[pos:pos+cinfo.len])
            output += fmtline.format(cinfo.name, value)
            pos += cinfo.len
            if (cinfo.len > 2):
                output += "Invalid value definition: {}  Length: {}\n".format(cinfo.name, cinfo.len)
                pos += 1
    return output   

def CMPowerCycle(arglist):
    cmdhelp = CMCommandHelpDetailed['PowerCycle'.lower()]
    errmsg = ""
    target = 0
    if (arglist and (len(arglist) > 0)):
        for arg in arglist:
            if ('target=' in arg):
                value = arg.split('=')[1]
                target = value
    
    if (target > 4):
        errmsg = "The target {} is not valid.\n".format(target)
        return (errmsg + cmdhelp)
        
    verbose("PowerCycle will be sent to target {}".format(target))
    # CMd = 0x02    0x6 0x34 0x45 0x70 0x00 0xc8 0x20 0x0 0x02 0x02 0xd8
    tgtbyte = hex((target << 4) | 2)
    command = "{} 0x02 {} {}".format(chassis_preamble, tgtbyte, ending)
    stdout = call_ipmitool(command)

    if (use_raw_output):
        return stdout
    
    # check the completion codes
    outbytes = stdout.split()
    if (len(outbytes) == 0):
        # bad connection, message in stderr
        return "Ipmitool Error.  Verify HOST, user, and password are correct"

    completion = CMConfigCompCodes.get(outbytes[completion_code_idx], 'Unknown response')
    if (not (completion == 'Success')):
        return "Unsuccessful reponse: {} = {} ".format(outbytes[completion_code_idx], completion)
    
    return notimp
    
def CMCommandHelpFunc(arglist):
    output = "CMCommand Detailed Help\n"
    if (arglist and (len(arglist) > 0)):
        # list details for each named command
        for arg in arglist:
            output += arg + CMCommandHelpDetailed.get(arg.lower(), "\n{} is an unknown command".format(arg))    
    else:
        # list all commands if non specified
        for cmdname in list(CMCommandHelpDetailed):
            output += cmdname + CMCommandHelpDetailed[cmdname] + '\n\n'
    return output
    
# Commands lookup tables.  Must define these AFTER the function defs
CMCommands = {
    'getversion': CMGetVersion,
    'getsensorinfo': CMGetSensorInfo,
    'getconfig': CMGetConfig,
    'getdeviceid': CMGetDeviceId,
    'getpasscode': CMGetPasscode,
    'gethiddenconfig': CMGetHiddenConfig,
    'getlog': CMGetLog,
    'parselog': CMParseLog,
    'setconfig': CMSetConfig,
    'getfru': CMGetFRU,
    'setfru': CMSetFRU,
    'saveconfig': CMSaveConfig,
    'reconfigure': CMReconfig,
    'sethiddenconfig': CMSetHiddenConfig,
    'getpsuinfo': CMGetPSUInfo,
    'powercycle': CMPowerCycle,
    'help': CMCommandHelpFunc,
}

CMCommandHelp = {
    'getversion': 'Gets the CM Config Info.',
    'getsensorinfo': "Gets the data from last Set Sensor Info, fan speeds not implemented yet.",
    'getconfig': 'Gets the CM Configuration Properties.',
    'getdeviceid': 'Gets full CM info.', 
    'getpasscode': 'Gets the Passcode for Hidden Config Operations. Use -a help for arguments',
    'gethiddenconfig': 'Lists the Hidden Configuration Properties. Use -a help for arguments',
    'getlog': 'Lists the log entries from the CM EEPROM memory. Use -a help for arguments.',
    'parselog': 'Parse a provided log file from an iDRAC TSR package (named CMLogs.log).',
    'setconfig': 'Set ONE CM Config property. Use -a help for arguments.',
    'getfru': 'Gets all the FRU data.',
    'setfru': 'Sets one FRU item. Use -a help for arguments.',
    'saveconfig': 'Saves relevant CM Propertis and FRU Settings to an INI File for reconfigure.',
    'reconfigure': 'Sets all CM Config Properties and FRU items using an INI file.',
    'sethiddenconfig':'Set ONE CM Hidden Config Property. Use -a help for arguments.',
    'getpsuinfo':'Get the current PSU mismatch status, redundancy configuration, and power output.',
    'powercycle':'Send a powercycle command to the Chassis or a single Sled. Use -a help for arguments.',
    'help': 'List Detailed Command help information',
}

CMCommandHelpDetailed = {
    'getversion': """
The GetVersion command does not take any extra arguments.""",
    'getsensorinfo': """
The GetSensorInfo command does not take any arguments.""",
    'getconfig': """
The GetConfig command lists the names and values of all the known CM Configuration Properties.""",
    'getdeviceid' : """
The GetDeviceId command does not take any extra arguments.""",
    'getpasscode': """
The GetPasscode command takes the following required named arguments (with -a):
    -a key=<str>      - The 8-byte static key in ascii text.""",
    'gethiddenconfig': """
The GetHiddenConfig command takes the following required named arguments (with -a):
    -a key=<str>      - The 8-byte static key in ascii text.
    -a passcode=<str> - The 8-byte passcode copied from GetPasscode output.""",
    'getlog': """
The GetLog command takes the following optional named arguments (with -a):
    -a offset=<int> - Start output <int> lines from the start of the log.
    -a tail=<int>   - Start output <int> lines from the end of the log.
    -a outfile=<filename> - Write to the filename specified.""",
    'parselog': """
The ParseLog command takes a single log file captured from an iDRAC TSR and converys the text Hex codes to readable log data.
    -a logfile=<filename> - The log file from the TSR dump
    -a outfile=<filename> - An optional output filename.  If not provided will dump to command prompt.
    """,
    'setconfig': """
The SetConfig command takes the following required named arguments (with -a):
    -a <propertyname>=<value> - set the given property by name to the value.  
        Use the GetConfig command to see the list of property names.""",
    'getfru': """
The GetFRU comnmand will return the names and values of all the known FRU data from the CM.""",
    'setfru': """
The SetFRU command takes the following required named arghuments (with -a):
    -a <frupropertyname>=<value> - set the given FRU property to the value.
        Use the GetFRU command to see the list of FRU property names""",
    'saveconfig': """
The SaveConfig command takes the name of a target output INI file as input and will write out an INI file
with the CM Config Properties and FRU Settings and their current values.   This only collects
settings that would be set back to defaults by a FRU reflash update.
    -a inifile=<ini file path> - the path to a target output ini file
    """,
    'reconfigure': """
The Reconfigure command takes the name of an INI file as input and will apply the CM COnfig propery
and FRU Settings values to the target system based on the file input to reset properties that 
were erased by a CM update. 
    -a inifile=<ini file path>  The path to an INI input file.
    """,
    'sethiddenconfig': """
The SetHiddenConfig command takes the following required named arguments (with -a):
    -a key=<str>      - The 8-byte static key in ascii text.
    -a passcode=<str> - The 8-byte passcode copied from GetPasscode output.
    -a <propertyname>=<value> - set the given property by name to the value.  
        Use the GetHiddenConfig command to see the list of property names.""",
    'getpsuinfo':"""
The GetPSUInfo command does not take any extra arguments.""",
    'powercycle':"""
The PowerCycle command takes the following named arguments (with -a):
    -a target=<id> - Send the PowerCycle command to the target. If not defined, id = 0. 
    If id==0, powercycle the chassis, else powercycle the sled number <id>.  <id> must be 0-4.""",
    'help': """
The Help command may take arguments with -a to name specific commands.
    Ex:    -a GetVersion -a GetConfig
    If no args are specified it will list command details for all current commands.""",
}

def check_ipmitool():
    if (os.name == 'nt'):
        command = 'where ipmitool'
    else:
        command = 'which ipmitool'

    child = subprocess.Popen(command, cwd='.', shell=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    stdout, stderr = child.communicate()
    if (child.returncode != 0):
        print (stdout)
        print (stderr)
        return False
    return True
    
def call_ipmitool(arguments):
    if (args.wmi):
        cmdline = "ipmitool -I wmi raw {}".format(arguments)
    elif (args.host):
        cmdline = "ipmitool -I lanplus -H {} -U {} -P {} raw {}".format(args.host, args.user, args.password, arguments)
    else:
        print("If --wmi is not specified then the --host parameter is required")
        return ""
        
    verbose("ipmi cmd = {}".format(cmdline))
    child = subprocess.Popen(cmdline,cwd='.',shell=True,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    stdout, stderr = child.communicate()
    if (child.returncode == 0):
        return stdout.decode('utf-8')
    print(stderr.decode('utf-8'))
    return ""  # no return bytes means a failed connection

def CallCommand(command, arglist):
    func = CMCommands.get(command.lower(), None)
    result = ""
    if func:
        result = func(arglist)
    else:
        print ("No such command: {}".format(command))
        print ("Valid commands are:")
        for cmdname in CMCommands.keys():
            print("{} - {}".format(cmdname, CMCommandHelp[cmdname]))
    return result

def verbose(*args):
    if print_verbose:
        for arg in args:
            print(arg)

if __name__ == "__main__":
    PARSER = argparse.ArgumentParser(description=__doc__)
    PARSER.add_argument('-W', '--wmi',  action='store_true', default=False, help="Use the WMI interface to send the command. Overrides --host.")
    PARSER.add_argument('-H', '--host', help="Use the lanplus interface and send the command to the given iDrac host name/IP.")
    PARSER.add_argument('-u', '--user',  default='root', help="The user name to connect with.")
    PARSER.add_argument('-p', '--password', default='calvin', help="The password to connect with.")
    PARSER.add_argument('-r', '--raw_output', action='store_true', default=False, help="Print the hex codes from the response without interpretation.")
    PARSER.add_argument('-v', '--verbose', action='store_true', default=False, help="Print more messages.")
    PARSER.add_argument('-C', '--command', type=str, required=True, help="The name of the IPMI command to send. Use -C Help for details." )
    PARSER.add_argument('-a', '--arg', type=str, action='append', help="Optional argument for command, append as many as required.")
    
    args = PARSER.parse_args()

    if (sys.version_info.major < 3):
        print("This script requires Python version 3 or higher.  You are running {}.{}".format(sys.version_info.major, sys.version_info.minor))
        sys.exit(1)
   
    if (not check_ipmitool()):
        print("You must install ipmitool on this system.")
        sys.exit(1)
    if (not args.command):
        print("You must provide a command name")
        sys.exit(1)
    
    if (args.raw_output):
        use_raw_output = True
    if (args.verbose):
        print_verbose = True
        
    verbose("wmi = {} host = {}  user = {}  password = {}  command = {}  args = {}".format(args.wmi, args.host, args.user, args.password, args.command, args.arg))
        
    print(CallCommand(args.command, args.arg))
    sys.exit(0)