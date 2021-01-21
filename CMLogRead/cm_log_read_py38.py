import time
import base64
import sys
import re 
import platform
import os

line1 = ''
line = 0
line2 = ''
offset = 0
log_cnt = 0

import subprocess
if (len(sys.argv) < 3):
    print("Usage: cm_log_read <iDrac IP address> <username, eg root> <password>")
    sys.exit(1)
    
result = []

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
    cmdline = "ipmitool -I lanplus -H {} -U {} -P {} raw {}".format(sys.argv[1], sys.argv[2], sys.argv[3], arguments)
    #print("ipmi cmd = {}".format(cmdline))
    child = subprocess.Popen(cmdline,cwd='.',shell=True,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    stdout, stderr = child.communicate()
    if (child.returncode == 0):
        return stdout.decode('utf-8')
    print(stderr.decode('utf-8'))
    return ""  # no return bytes means a failed connection

if (not check_ipmitool()):
    print("ipmitool was not found in the system path.  Please install it and make sure it is in the path.")
    sys.exit(1)
    

cmdfirstget = "0x6 0x34 0x45 0x70 0x28 0xc8 0x20 0x0 0x10 0x1 0xff"
    
line = call_ipmitool(cmdfirstget)
if (not line):
    print ("Failed to execute ipmitool")
    sys.exit(0)
    
log_cnt = (int((line[25:27]) + (line[22:24]),16))
print("There are {} bytes in the CM log".format(log_cnt))

f= open("CM_log.txt","w+")

while (offset < log_cnt):
    #win_cmd = "ipmitool -I lanplus -H 192.168.9.21 -U root -P calvin raw 0x6 0x34 0x45 0x70 0x28 0xc8 0x20 0x0 0x11 0x1 0x" + (format(offset,'04x'))[2:] + " 0x" + str(format(offset,'04x'))[:-2] + " 0x40 0xff"
    cmdnextget = "0x6 0x34 0x45 0x70 0x28 0xc8 0x20 0x0 0x11 0x1 0x{} 0x{} 0x40 0xff".format((format(offset,'04x'))[2:], str(format(offset,'04x'))[:-2] )

    ipmiout = call_ipmitool(cmdnextget)
    line2 = ("")
    for line in ipmiout:
        line1 = str(line)
        line1 = line1.replace(' ','')
        line1 = line1.replace('\\r\\n','')
        line1 = line1.replace('b\'','')
        line1 = str(line1)
        line2 += line1
    line2 = line2.replace("n","")
    line2 = line2.replace("\\","")
    line2 = line2.replace("'","")
    line2 = line2.replace('\r', "")
    line2 = line2.replace('\n', "")
    line2 = line2.upper()
    line2 = line2[16:-2] 
    ascii_string = ""
    ascii_string = str(base64.b16decode(line2))[2:-1]
    line2 = ("")
    print (ascii_string)
    f.write(ascii_string)
    f.write("\n")
    offset += 64


