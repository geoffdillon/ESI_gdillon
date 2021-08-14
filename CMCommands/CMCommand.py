#!/usr/bin/python3
# script to help automate IPMI rawcommands to the C6400 CM
# REQUIRES ipmitool
"""
This is a convenience utility to compose IPMI raw commands to the C6400 Chassis Managerand
via a sled's iDrac and to parse the results into readable format.
"""

import os
import sys
import subprocess
import argparse
import base64

# global set by arguments
use_raw_output = False
print_verbose = False

# global constants
generic_preamble = "0x06 0x34 0x45 0x70 {} 0xc8 0x20 0x0"
config_preamble = generic_preamble.format('0xc0')
hidden_config_preamble = generic_preamble.format('0xc8')
log_preamble = generic_preamble.format('0x28')
powercycle_preamble = generic_preamble.format('0x00')

ending = '0xd8'
notimp = "Not Implemented"
completion_code_idx = 6  # 6th byte in the response is the completion codes
CMLogOffsetIncrement = 64

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
        elif (self.data == 'int'):
            return (str(int(bytes[0], 16)))
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

    
# enumeration dictionaries
enabdisab = {0: 'Disabled (0)', 1: 'Enabled (1)'}

lockenum = {0: 'Unlocked (0)', 1: 'Locked (1)'}
fanctlenum = {
    0: 'Manual (0)',
    1: 'Openloop (1)',
    2: 'Closedloop (2)'
}
sledconfenum = {2: 'Half-width (2)', 4: 'Double-high half-width (4)'}
redpsuenum = {0: '2+0 Nonredundant (0)', 1: '1+1 Redundant (1)'}
powercapenum = {
    0: 'Disabled (0)', 
    1: 'Static, Spread equal (1)', 
    2: 'Reserved (2)', 
    3: 'Reserved (3)', 
    4: 'Reserved (4)', 
    5: 'Static, SledPowerLimit (5)'
}

fantypecfgenum = {0x13: 'Four-fan, Dual-rotor'}

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
    0: 'Not Set (0)',
    0x1c: 'Mercury (0x1c)',
    0x56: 'Roadster (0x56)',
    0x57: 'Steeda (0x57)',
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
    22: CMInfoSet("Reserved", 22, 1, 'bit'),
    23: CMInfoSet("Fan Types", 23, 1, 'int'),
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

CMConfigSettings = {
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

CMHiddenSettings = {
    1: CMConfigSet('ChassisID', 1, 1, chassisenum, 0x1C, True),
    2: CMConfigSet('AllowFWDowngrade', 2, 1, enabdisab, 0, True),
    3: CMConfigSet('Connector_Max_Threshold', 3, 2, {}, 0, False),
    4: CMConfigSet('GoldenChassis', 4, 1, enabdisab, 0, True),
    5: CMConfigSet('Fixed_FTB', 5, 1, enabdisab, 0, True),
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
def FindHiddenConfigByName(name):
    for id in CMHiddenSettings:
        if (CMHiddenSettings[id].name == name):
            return CMHiddenSettings[id]
    return None
    
# search the list of Config Properties for the given name.
def FindConfigByName(name):
    for id in CMConfigSettings:
        if (CMConfigSettings[id].name == name):
            return CMConfigSettings[id]
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

def CMGetConfig(args):
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
    output = "CM Config Settings:\n"
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
                value = CMConfigSettings[id].get_enum_val(numvalue)
            elif (CMConfigSettings[id].len == 2):
                # LSB is first in all of these
                numvalue = int(outbytes[position], 16) + int(outbytes[position+1], 16) * 0x100
                value = CMConfigSettings[id].get_enum_val(numvalue)
            elif (CMConfigSettings[id].len == 8):
                # must be svctag, therefore string
                value = ""
                for offset in range(0,7): # 8th byte is a 00
                    value += bytes.fromhex(outbytes[position+offset]).decode('ascii')
            else:
                value = ""
            #end if
            position += CMConfigSettings[id].len
            output += "{:22} = {:8}\n".format(CMConfigSettings[id].name, value)
        #end if
    #end for
    return output
    
def CMGetPasscode(arglist):
    cmdhelp = CMCommandHelpDetailed['GetPasscode']
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
    cmdhelp = CMCommandHelpDetailed['GetHiddenConfig']
    key = ""
    passcode = ""
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
            position += CMConfigSettings[id].len
            output += "{:22} = {:8}\n".format(CMHiddenSettings[id].name, value)
        #end if
    #end for
    return output

def CMGetLog(arglist):
    cmdhelp = CMCommandHelpDetailed['GetLog']
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
    
    log_cnt = (int((stdout[25:27]) + (stdout[22:24]),16)) - CMLogOffsetIncrement  # subtract one line to suppress the beginning of the circular log
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

    return ""

def CMSetConfig(arglist):
    cmdhelp = CMCommandHelpDetailed['SetConfig']
    property = None
    propval = None
    errmsg = ""
    if (arglist and (len(arglist) > 0)):
        for arg in arglist:
            if (len(arg.split('=')) < 2):  # argument is not well-formed
                errmsg = "The argument name and value must be separated by an = sign -> '{}'\n".format(arg)
                return (errmsg + cmdhelp)
            propname,propval = arg.split('=')
            property = FindConfigByName(propname)
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
        #lsb = propval & 0x00FF
        #msb = (propval >> 8) & 0x00FF  # mask upper bytes just to make sure
        propvalbytes = "{} {}".format(lsb, msb)   # lsb goes first I think
    elif (property.len == 8):
        # service tag is special
        tag = propval.upper()
        propvalbytes = ""
        for i in range(0,len(tag)):
            propvalbytes += hex(ord(tag[i])) + ' '
        for i in range(len(tag), 8):
            propvalbytes += '0x00 '
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
    
def CMSetHiddenConfig(arglist):
    cmdhelp = CMCommandHelpDetailed['SetHiddenConfig']
    key = ""
    passcode = ""
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
                property = FindHiddenConfigByName(propname)
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
    
def CMPowerCycle(arglist):
    cmdhelp = CMCommandHelpDetailed['PowerCycle']
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
    command = "{} 0x02 {} {}".format(powercycle_preamble, tgtbyte, ending)
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
            output += arg + CMCommandHelpDetailed.get(arg, "\n{} is an unknown command".format(arg))    
    else:
        # list all commands if non specified
        for cmdname in list(CMCommandHelpDetailed):
            output += cmdname + CMCommandHelpDetailed[cmdname] + '\n\n'
    return output
    
# Commands lookup tables.  Must define these AFTER the function defs
CMCommands = {
    'GetVersion': CMGetVersion,
    'GetConfig': CMGetConfig,
    'GetPasscode': CMGetPasscode,
    'GetHiddenConfig': CMGetHiddenConfig,
    'GetLog': CMGetLog,
    'SetConfig': CMSetConfig,
    'SetHiddenConfig': CMSetHiddenConfig,
    'PowerCycle': CMPowerCycle,
    'Help': CMCommandHelpFunc,
}

CMCommandHelp = {
    'GetVersion': 'Gets the CM Config Info.',
    'GetConfig': 'Lists the CM Configuration Properties.',
    'GetPasscode': 'Gets the Passcode for Hidden Config Operations. Use -a help for arguments',
    'GetHiddenConfig': 'Lists the Hidden Configuration Properties. Use -a help for arguments',
    'GetLog': 'Lists the log entries from the CM EEPROM memory. Use -a help for arguments.',
    'SetConfig': 'Set ONE CM Config property. Use -a help for arguments.',
    'SetHiddenConfig':'Set ONE CM Hidden Config Property. Use -a help for arguments.',
    'PowerCycle':'Send a powercycle command to the Chassis or a single Sled. Use -a help for arguments.',
    'Help': 'List Detailed Command help information',
}

CMCommandHelpDetailed = {
    'GetVersion': """
The GetVersion command does not take any extra arguments.""",
    'GetConfig': """
The GetConfig command does not take any extra arguments.""",
    'GetPasscode': """
The GetPasscode command takes the following required named arguments (with -a):
    -a key=<str>      - The 8-byte static key in ascii text.""",
    'GetHiddenConfig': """
The GetHiddenConfig command takes the following required named arguments (with -a):
    -a key=<str>      - The 8-byte static key in ascii text.
    -a passcode=<str> - The 8-byte passcode copied from GetPasscode output.""",
    'GetLog': """
The GetLog command takes the following optional named arguments (with -a):
    -a offset=<int> - Start output <int> lines from the start of the log.
    -a tail=<int>   - Start output <int> lines from the end of the log.
    -a outfile=<filename> - Write to the filename specified.""",
    'SetConfig': """
The SetConfig command takes the following required named arguments (with -a):
    -a <propertyname>=<value> - set the given property by name to the value.  
        Use the GetConfig command to see the list of property names.""",
    'SetHiddenConfig': """
The SetHiddenConfig command takes the following required named arguments (with -a):
    -a key=<str>      - The 8-byte static key in ascii text.
    -a passcode=<str> - The 8-byte passcode copied from GetPasscode output.
    -a <propertyname>=<value> - set the given property by name to the value.  
        Use the GetHiddenConfig command to see the list of property names.""",
    'PowerCycle':"""
The PowerCycle command takes the following named arguments (with -a):
    -a target=<id> - Send the PowerCycle command to the target. If not defined, id = 0. 
    If id==0, powercycle the chassis, else powercycle the sled number <id>.  <id> must be 0-4.""",
    'Help': """
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
    cmdline = "ipmitool -I lanplus -H {} -U {} -P {} raw {}".format(args.host, args.user, args.password, arguments)
    verbose("ipmi cmd = {}".format(cmdline))
    child = subprocess.Popen(cmdline,cwd='.',shell=True,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    stdout, stderr = child.communicate()
    if (child.returncode == 0):
        return stdout.decode('utf-8')
    print(stderr.decode('utf-8'))
    return ""  # no return bytes means a failed connection

def CallCommand(command, arglist):
    func = CMCommands.get(command, None)
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
    PARSER.add_argument('-H', '--host',  required=True, help="The iDrac host to send the IPMI command to.")
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
        
    verbose("host = {}  user = {}  password = {}  command = {}  args = {}".format(args.host, args.user, args.password, args.command, args.arg))
        
    print(CallCommand(args.command, args.arg))
    sys.exit(0)
    