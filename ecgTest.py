#!/usr/bin/env python
# Yang Zheng. March 2016   
# 
#

import pexpect
import sys
import time

from struct import unpack

def floatfromhex(h):
    t = float.fromhex(h)
    if t > float.fromhex('7FFF'):
        t = -(float.fromhex('FFFF') - t)
        pass
    return t


# This algorithm borrowed from 
# http://processors.wiki.ti.com/index.php/SensorTag_User_Guide#Gatt_Server
# which most likely took it from the datasheet.  I've not checked it, other
# than noted that the temperature values I got seemed reasonable.
#
def calcEcg(ecgValue1, ecgValue2):
    ecgValue1Decode=unpack('!f',ecgValue1.decode('hex'))[0]
    ecgValue2Decode=unpack('!f',ecgValue2.decode('hex'))[0]
    print "%.2f %.2f" % (ecgValue1Decode,ecgValue2Decode)


bluetooth_adr = sys.argv[1]
tool = pexpect.spawn('gatttool -b ' + bluetooth_adr + ' --interactive')
tool.expect('\[LE\]>')
print "Preparing to connect. You might need to press the side button..."
tool.sendline('connect')
# test for success of connect
#tool.expect('\[CON\].*>')  # earlier version of gatttool
tool.expect('Connection successful')
tool.sendline('char-write-cmd 0x29 01')
tool.expect('\[LE\]>')
while True:
    #time.sleep(1)
    tool.sendline('char-read-hnd 0x25')
    tool.expect('descriptor: .*') 
    rval = tool.after.split()
    #counter = floatfromhex(rval[2] + rval[1])
    counter = unpack('!H',(rval[2]+rval[1]).decode('hex') )[0]
    print counter
    ecgValue1 = rval[8] + rval[7] + rval[6] + "00"
    ecgValue2 = rval[17] + rval[16] + rval[15] + "00"
    #calcEcg(ecgValue1, ecgValue2)


