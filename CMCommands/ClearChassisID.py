#!/usr/bin/python3
# Geoff Dillon geoff_dillon@dell.com
# Copyright Dell, Inc 2022
# FOR INTERNAL USE ONLY.  DO NOT distribute to customers or partners/vendors.
# This script automates certain IPMI raw commands to the C6400/C6600 CM through the iDRAC.
# REQUIRES python 3.8 or higher
# REQUIRES ipmitool

# This will call CMCommand.py to set the hidden property Chassis ID to 0 so that the next AC cycle will reset it to 
#  whatever sled is inserted first

import os
import sys
import subprocess
import argparse
import base64
import configparser

# global set by arguments
use_raw_output = False
print_verbose = False
clear_chassis_id = False


def check_CMCommand_py():
    # expect CMCommand.py to be in the same folder
    if (os.name == 'nt'):
        command = 'where CMCommand.py'
    else:
        command = 'which CMCommand.py'

    child = subprocess.Popen(command, cwd='.', shell=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    stdout, stderr = child.communicate()
    if (child.returncode != 0):
        print (stdout)
        print (stderr)
        return False
    return True
    
def call_CMCommand_py(testonly, command, arguments):
    textargs = ''
    if (arguments):
        if (type(arguments) is list):
            for a in arguments:
                textargs += " -a {} ".format(a)
            verbose("Textargs = " + textargs)
        elif (type(arguments) is str):
            textargs = " -a {}".format(arguments)
        else:
            print("arguments to call_CMCommand_py() must be list of strings or a single string")
            return ""
    
    if (args.wmi):
        cmdline = "python CMCommand.py -W -C {} {}".format(command, textargs)
    elif (args.host):
        cmdline = "python CMCommand.py -H {} -u {} -p {} -C {} {}".format(args.host, args.user, args.password, command, textargs)
    else:
        print("If --wmi is not specified then the --host parameter is required")
        return ""
        
    verbose("CMCommand_py = {}".format(cmdline))
    if (not testonly):
        child = subprocess.Popen(cmdline,cwd='.',shell=True,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE, stdin=subprocess.PIPE)
        stdout, stderr = child.communicate()
        if (child.returncode == 0):
            return stdout.decode('utf-8')
        print(stderr.decode('utf-8'))
    else:
        print("TESTONLY: {}".format(cmdline))
    return ""  # no return bytes means a failed connection

def ClearChassisID():
    
    # step 0, check for the key
    if (not args.key):
        print("ERROR: You must provide the key with the -k option to access the hidden properties.")
        return
    keyarg = "key={}".format(args.key)
    
    # only clear if the parameter is explicitly set
    if (clear_chassis_id):
        # step 1 get the CM temporary passcode
        command = "GetPasscode"
        arglist = [keyarg]
        verbose("Getting the passcode from the CM")
        stdout = call_CMCommand_py(False, command, arglist)
        if (stdout.startswith("Passcode")):
            # get the passcode text 
            passcode = stdout.split('=')[1].strip()
            verbose("Temp passcode = {}".format(passcode))
        else:
            print("Failed to get the passcode: ", stdout)
            return
        # step 2 change the Chassis ID Hidden property to 0
        verbose("Setting the Chassis ID to 0")
        command = "SetHiddenConfig"
        arglist.append( "passcode={}".format(passcode))
        arglist.append( "ChassisID=00" )
        stdout = call_CMCommand_py(False, command, arglist)
        verbose("Result from call_CMCommand_py = .{}.".format(stdout))
        if (stdout.strip() == "Success"):
            print("The Chassis ID Has been cleared.  To reset to a new sled type, remove all sleds and insert the desired sleds.")
        else:
            print("The Chassis ID has not been cleared. Error: {}".format(stdout))
    else:
        print("The -c or --clear option was not set. Returning current Hidden Properties only.")
    
    # step 3 get another passcode
    command = "GetPasscode"
    arglist = [keyarg]
    verbose("Getting the passcode from the CM")
    stdout = call_CMCommand_py(False, command, arglist)
    if (stdout.startswith("Passcode")):
        # get the passcode text 
        passcode = stdout.split('=')[1].strip()
        verbose("Temp passcode = {}".format(passcode))
    else:
        print("Failed to get the passcode: ", stdout)
        return    
    # step 4 read back the hidden properties
    verbose("Reading back the hidden properties")
    command = "GetHiddenConfig"
    arglist.append( "passcode={}".format(passcode))
    stdout = call_CMCommand_py(False, command, arglist)
    print (stdout)
    
    return


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
    PARSER.add_argument('-k', '--key', help="The secret key code for CM hidden properties.")
    PARSER.add_argument('-c', '--clear', action='store_true', default=False, help="Set the Chassis ID to 0. If not set, this command only reads the current value.")
    PARSER.add_argument('-r', '--raw_output', action='store_true', default=False, help="Print the hex codes from the response without interpretation.")
    PARSER.add_argument('-v', '--verbose', action='store_true', default=False, help="Print more messages.")
    
    args = PARSER.parse_args()

    if (sys.version_info.major < 3):
        print("This script requires Python version 3 or higher.  You are running {}.{}".format(sys.version_info.major, sys.version_info.minor))
        sys.exit(1)
   
    if (not check_CMCommand_py()):
        print("You must place CMCommand.py in the same folder as this script.")
        sys.exit(1)
    
    if (args.raw_output):
        use_raw_output = True
    if (args.verbose):
        print_verbose = True
    if (args.clear):
        clear_chassis_id = True
        
    verbose("wmi = {} host = {}  user = {}  password = {}".format(args.wmi, args.host, args.user, args.password))
        
    ClearChassisID()
    
    sys.exit(0)