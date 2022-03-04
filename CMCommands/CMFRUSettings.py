#!/usr/bin/python3
# For AMC C6600 Chassis ONLY!!!
# To reset the CM Configuration Properties after a FRU UPdate, edit the following script and execute this 
#  script from a workstation on the local network where the target iDRACs are connected.
#  Geoff Dillon 2/25/2022   geoff_dillon@dell.com

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

# used to identify supported Chassis
CMBoardPN = {
    '0R8Y73': "Hubble",
    '05V6V5': "Lake Austin",
}
CMHubblePN = "0R8Y73"
CMLkAustinPN = "05V6V5"

# The names of the properties that will be captured or reset for FRU Update repairs
ReconfigProperties = {
    'ConfigProperties': ['RedundantPSUsN', 'ChassisServiceTag', 'BpPresent', 'ChassisPowerLimit', 'ChassisPowerCap', 'FTREnable', 'CableAmpLimit'],
    'FRUSettings': ['ChassisPartNumber', 'ChassisSerialNumber', 'ChassisBoardPartNumber', 'ChassisBoardSerialNumber'],
}


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
}

# enumeration dictionaries used from displaying human-readable output
enabdisab = {0: 'Disabled (0)', 1: 'Enabled (1)'}

lockenum = {0: 'Unlocked (0)', 1: 'Locked (1)'}
fanctlenum = {
    0: 'Manual (0)',
    1: 'Openloop (1)',
    2: 'Closedloop (2)'
}

fanctlschemeenum = {
    '00': 'Emergency',
    '04': 'Openloop',
    '08': 'Closedloop'
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
    '00': 'Unknown',
    '01': 'FullWidth',
    '02': 'HalfWidth',
    '03': 'ThirdWidth',
    '04': 'DblHighHalf',
    '05': 'G5.5 Half',
    '06': 'G5.5 Full',
}
chassisenum = {
    '00': 'Not Set (0)',
    '1c': 'Mercury (0x1c)',
    '56': 'Roadster (0x56)',
    '57': 'Steeda (0x57)',
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

# Defines the range of valid properties per CM version
# main key is CM major version
# second key is CM minor version
# * matches all minor versions.
CMValidConfigSettings = {
    '1': {'>=70': range(1,30)},
    '2': {'*': range(1,30)},
    '3': {'*': range(1,30)},
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
CMLkAustinConfigSettings[9] = CMConfigSet("ReserveByte1", 9, 1, None, 0, False)
CMLkAustinConfigSettings[10] = CMConfigSet("ReserveByte2", 10, 1, None, 0, False)
CMLkAustinConfigSettings[11] = CMConfigSet("ReserveByte3", 11, 1, None, 0, False)
CMLkAustinConfigSettings[18] = CMConfigSet("ReservedWord1", 18, 2, None, 0, False)
CMLkAustinConfigSettings[19] = CMConfigSet("ReservedWord2", 19, 2, None, 0, False)
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

CMAMCFRUSettings = {
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

def CMGetConfig(args, ini_output = False):
    # Get the FRU CM Board PN/Rev to determine the chassis type and HW level (UT/PT/ST)
    if (ini_output):
        verbose("CMGetConfig: Using INI style output.")
    
    boardpn, boardrev = BoardPNAndRev()
    platname = ""
    
    
    verbose("Chassis Board PN = {}, rev = {}".format(boardpn, boardrev))
    if (boardpn == CMHubblePN):
        CMConfigSettings = CMHubbleConfigSettings
        platname = "Hubble C6400"
        verbose("Using Hubble Config Settings")
    elif (boardpn == CMLkAustinPN):
        CMConfigSettings = CMLkAustinConfigSettings
        platname = "Lake Austin C6600"
        verbose("Using Lake Austin Config Settings")
    else:
        return "CM Board PN {} is not implemented.".format(boardpn)

    # get all the config items, don't care about the args
    stdout = call_ipmitool("{} 0xa0 0x0 0xff {}".format(config_preamble, ending))
    
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
    return output

def CMSetConfig(arglist):
    cmdhelp = CMCommandHelpDetailed['SetConfig'.lower()]
    property = None
    propval = None
    errmsg = ""
    
    boardpn, boardrev = BoardPNAndRev()
    platname = ""
    verbose("Chassis Board PN = {}, rev = {}".format(boardpn, boardrev))
    if (boardpn == CMHubblePN):
        CMConfigSettings = CMHubbleConfigSettings
        platname = "Hubble C6400"
        verbose("Using Hubble Config Settings")
    elif (boardpn == CMLkAustinPN):
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
    # Get the FRU CM Board PN/Rev to determine the chassis type and HW level (UT/PT/ST)
    boardpn, boardrev = BoardPNAndRev()
    platname = ""
    
    verbose("Chassis Board PN = {}, rev = {}".format(boardpn, boardrev))
    if (boardpn == CMHubblePN):
        CMFRUSettings = CMHubbleFRUSettings
        platname = "Hubble C6400"
        verbose("Using Hubble FRU Settings")
    elif (boardpn == CMLkAustinPN):
        CMFRUSettings = CMAMCFRUSettings
        platname = "Lake Austin C6600"
        verbose("Using Lake Austin FRU Settings")
    else:
        return "CM Board PN {} is not implemented.".format(boardpn)    
    
    #Have to loop through all the addresses since there isn't one command to get all data
    if (ini_output):
        output = "[FRUSettings]\n"
        output += "Board PN = {}\nPlatform Name = {}\n".format(boardpn, platname)
    else:
        output = "CM FRU Settings: Board PN {} Platform Name {}\n".format(boardpn, platname)

    for fru in CMFRUSettings:
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
    'getconfig': CMGetConfig,
    'setconfig': CMSetConfig,
    'getfru': CMGetFRU,
    'setfru': CMSetFRU,
    'saveconfig': CMSaveConfig,
    'reconfigure': CMReconfig,
    'help': CMCommandHelpFunc,
}

CMCommandHelp = {
    'getversion': 'Gets the CM Config Info.',
    'getconfig': 'Gets the CM Configuration Properties',
    'setconfig': 'Set ONE CM Config property. Use -a help for arguments.',
    'getfru': 'Gets all the FRU data.',
    'setfru': 'Sets one FRU item. Use -a help for arguments.',
    'reconfigure': 'Sets all CM CONfig Properties and FRU items using this script data.',
    'help': 'List Detailed Command help information',
}

CMCommandHelpDetailed = {
    'getversion': """
The GetVersion command does not take any extra arguments.""",
    'getconfig': """
The GetConfig command lists the names and values of all the known CM Configuration Properties.""",
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
    
