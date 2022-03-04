import time
import base64
import sys
import re 

line1 = ''
line = 0
line2 = ''
offset = 0
log_cnt = 0

import subprocess
import string

result = []
win_cmd = "ipmitool -I lanplus -H "+ sys.argv[1] +" -U "+ sys.argv[2] +" -P "+ sys.argv[3] +" raw 0x6 0x34 0x45 0x70 0x28 0xc8 0x20 0x0 0x10 0x1 0xff"
process = subprocess.Popen(win_cmd,
shell=True,
stdout=subprocess.PIPE,
stderr=subprocess.PIPE )
for line in process.stdout:
    print (line)

log_cnt = (int((line[25:27]) + (line[22:24]),16))

f= open("CM_log.txt","w+")

while (offset < log_cnt):
    #win_cmd = "ipmitool -I lanplus -H 192.168.9.21 -U root -P calvin raw 0x6 0x34 0x45 0x70 0x28 0xc8 0x20 0x0 0x11 0x1 0x" + (format(offset,'04x'))[2:] + " 0x" + str(format(offset,'04x'))[:-2] + " 0x40 0xff"
    win_cmd = "ipmitool -I lanplus -H "+ sys.argv[1] +" -U "+ sys.argv[2] +" -P "+ sys.argv[3] +" raw 0x6 0x34 0x45 0x70 0x28 0xc8 0x20 0x0 0x11 0x1 0x" + (format(offset,'04x'))[2:] + " 0x" + str(format(offset,'04x'))[:-2] + " 0x40 0xff"

    process = subprocess.Popen(win_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE )
    stdout, stderr = process.communicate()
    
    for line in stdout.decode('utf-8'):
        line1 = str(line)
        line1 = line1.replace(' ','')
        line1 = line1.replace('\n','')
        line1 = line1.replace('\\r\\n\'','')
        line1 = line1.replace('b\'','')
        line1 = str(line1)
        line2 += line1


    line2 = line2.replace("n","")
    line2 = line2.replace("\\","")
    line2 = line2.replace("'","")
    line2 = line2.upper()
    line2 = line2[16:-2] 
    
    ascii_string = ""
    ascii_string = str(base64.b16decode(line2))[2:-1]
    line2 = ("")
    print (ascii_string)
    f.write(ascii_string)
    f.write("\n")
    offset += 64


