#!/usr/bin/env python
#Development based on Bluegiga BGAPI/BGLib

""" Bluegiga BGAPI/BGLib demo: ecg collector from laboratory ICGECGMONITOR

Changelog:
    2016-03-28 - Initial release

============================================
Bluegiga BGLib Python interface library test ecg collector
2016-03-28 by YangZheng
Updates should (hopefully) always be available at https://github.com/zhengyangtongxie/ecg_ble

============================================

"""

__author__ = "Yang Zheng"
__license__ = "IECAS"
__version__ = "2016-03-28"
__email__ = "zhengyang14@mails.ucas.ac.cn"

"""
BASIC ARCHITECTURAL OVERVIEW:
    The program starts, initializes the dongle to a known state, then starts
    scanning. Each time an advertisement packet is found, a scan response
    event packet is generated. These packets are read by polling the serial
    port to which the BLE(D)11x is attached.

    The basic process is as follows:
      a. Scan for devices
      b. If the desired device name is found in an ad packet, connect to that device
      c. Search for all "service" descriptors to find the target service handle range
      d. Search through the target service to find the ECG measurement attribute handle and ECG switch handle 
      e. Enable ECG switch and measurement attribute notifications
      f. Read and display incoming ECG values until terminated (Ctrl+C)

FUNCTION ANALYSIS:

1. __main__:
    Initializes the serial port and BGLib object to attach event handlers,
    then sends commands to cause the device to disconnect, stop advertising,
    and stop scanning (i.e. return to a known idle/standby state). Some of
    these commands will fail since the device cannot be doing all of these
    things at the same time, but this is not a problem. __main__ finishes
    by setting scan parameters and initiating a scan with the "gap_discover"
    command.

2. my_ble_evt_gap_scan_response:
    Raised during scanning whenever an advertisement packet is detected. The
    data provided includes the MAC address, RSSI, and ad packet data payload.
    This payload includes fields which contain any services being advertised,
    which allows us to scan for a specific service. In this demo, the service
    we are searching for has a name which is contained in the
    "name_ecg_service" variable. Once a match is found, the script initiates
    a connection request with the "gap_connect_direct" command.

3. my_ble_evt_connection_status
    Raised when the connection status is updated. This happens when the
    connection is first established, and the "flags" byte will contain 0x05 in
    this instance. However, it will also happen if the connected devices bond
    (i.e. pair), or if encryption is enabled (e.g. with "sm_encrypt_start").
    Once a connection is established, the script begins a service discovery
    with the "attclient_read_by_group_type" command.

4. my_ble_evt_attclient_group_found
    Raised for each group found during the search started in #3. If the right
    service is found (matched by UUID), then its start/end handle values are
    stored for usage later. We cannot use them immediately because the ongoing
    read-by-group-type procedure must finish first.

5. my_ble_evt_attclient_find_information_found
    Raised for each attribute found during the search started after the service
    search completes. We look for two specific attributes during this process;
    the first is the ECG measurement attribute which has a
    standard 128-bit UUID (contained in the "uuid_ecg_measurement_characteristic"
    variable), and the second is the corresponding "client characteristic
    configuration" attribute with a UUID of 0x2902. The correct attribute here
    will always be the first 0x2902 attribute after the measurement attribute
    in question. Typically the CCC handle value will be either +1 or +2 from
    the original handle. Besides, we also should write 0x01to handle 0x29 
    with a 128-bit UUID(f000aa12-0451-4000-b000-000000000000) to open
    ECG switch which is down by default for low energy..

6. my_ble_evt_attclient_procedure_completed
    Raised when an attribute client procedure finishes, which in this script
    means when the "attclient_read_by_group_type" (service search) or the
    "attclient_find_information" (descriptor search) completes. Since both
    processes terminate with this same event, we must keep track of the state
    so we know which one has actually just finished. The completion of the
    service search will (assuming the service is found) trigger the start of
    the descriptor search, and the completion of the descriptor search will
    (assuming the attributes are found) trigger enabling indications on the
    measurement characteristic.

7. my_ble_evt_attclient_attribute_value
    Raised each time the remote device pushes new data via notifications or
    indications. (Notifications and indications are basically the same, except
    that indications are acknowledged while notifications are not--like TCP vs.
    UDP.) In this script, the remote slave device pushes ECG measurements out 
    as notifications approximately once per second. These values are displayed
    to the console.

"""

import bglib, serial, time, datetime, optparse, signal,struct
from matplotlib.pyplot import plot,ion,figure,subplots_adjust,grid,xlim,xlabel,pause
from threading import Thread

ble = 0
ser = 0
peripheral_list = []
connection_handle = 0
att_handle_start = 0
att_handle_end = 0
att_handle_measurement = 0
att_handle_measurement_ccc = 0

uuid_service = [0x28, 0x00] # 0x2800
uuid_client_characteristic_configuration = [0x29, 0x02] # 0x2902
uuid_client_characteristic_switch = [0xf0, 0x00,0xaa,0x12,0x04,0x51,0x40,0x00,0xb0,0x00,0x00,0x00,0x00,0x00,0x00,0x00] 

#uuid_hr_service = [0x18, 0x0d] # 0x180D
name_ecg_service = ["ECGICGMONITOR"]
uuid_ecg_service = [0xf0, 0x00,0xaa,0x10,0x04,0x51,0x40,0x00,0xb0,0x00,0x00,0x00,0x00,0x00,0x00,0x00]  
uuid_ecg_characteristic = [0xf0, 0x00,0xaa,0x11,0x04,0x51,0x40,0x00,0xb0,0x00,0x00,0x00,0x00,0x00,0x00,0x00] 

ecg_package_counter = []
ecg_received_value = []

STATE_STANDBY = 0
STATE_CONNECTING = 1
STATE_FINDING_SERVICES = 2
STATE_FINDING_ATTRIBUTES = 3
STATE_LISTENING_MEASUREMENTS = 4
state = STATE_STANDBY

# handler to notify of an API parser timeout condition
def my_timeout(sender, args):
    # might want to try the following lines to reset, though it probably
    # wouldn't work at this point if it's already timed out:
    #ble.send_command(ser, ble.ble_cmd_system_reset(0))
    #ble.check_activity(ser, 1)
    print "BGAPI parser timed out. Make sure the BLE device is in a known/idle state."

# gap_scan_response handler
def my_ble_evt_gap_scan_response(sender, args):
    global state, ble, ser, name_ecg_service

    # pull all advertised service info from ad packet
    ad_services = []
    this_field = []
    bytes_left = 0
    for b in args['data']:
        if bytes_left == 0:
            bytes_left = b
            this_field = []
        else:
            this_field.append(b)
            bytes_left = bytes_left - 1
            if bytes_left == 0:
                if this_field[0] == 0x09:
                    ad_services.append([b"".join([chr(x) for x in this_field[1:]])])
                    
    # check for  "ICGECGMONITOR"(laboratory ICGECGMONITOR name)
    if name_ecg_service in ad_services:
        if not args['sender'] in peripheral_list:
            peripheral_list.append(args['sender'])
            #print "%s" % ':'.join(['%02X' % b for b in args['sender'][::-1]])

            # connect to this device
            ble.send_command(ser, ble.ble_cmd_gap_connect_direct(args['sender'], args['address_type'], 0x20, 0x30, 0x100, 0))
            ble.check_activity(ser, 1)
            state = STATE_CONNECTING

# connection_status handler
def my_ble_evt_connection_status(sender, args):
    global state, ble, ser, connection_handle

    if (args['flags'] & 0x05) == 0x05:
        # connected, now perform service discovery
        print "Connected to %s" % ':'.join(['%02X' % b for b in args['address'][::-1]])
        connection_handle = args['connection']
        ble.send_command(ser, ble.ble_cmd_attclient_read_by_group_type(args['connection'], 0x0001, 0xFFFF, list(reversed(uuid_service))))
        ble.check_activity(ser, 1)
        state = STATE_FINDING_SERVICES

# attclient_group_found handler
def my_ble_evt_attclient_group_found(sender, args):
    global ble, ser, att_handle_start, att_handle_end

    # found "service" attribute groups (UUID=0x2800), check for ECG service
    if args['uuid'] == list(reversed(uuid_ecg_service)):
        print "Found attribute group for service w/UUID=0xf000aa10: start=%d, end=%d" % (args['start'], args['end'])
        att_handle_start = args['start']
        att_handle_end = args['end']

# attclient_find_information_found handler
def my_ble_evt_attclient_find_information_found(sender, args):
    global state, ble, ser, att_handle_measurement, att_handle_measurement_ccc,att_handle_measurement_switch

    # check for ECG measurement characteristic
    if args['uuid'] == list(reversed(uuid_ecg_characteristic)):
        print "Found attribute w/UUID=0xf000aa11...: handle=%d" % args['chrhandle']
        att_handle_measurement = args['chrhandle']

    # check for subsequent client characteristic configuration
    elif args['uuid'] == list(reversed(uuid_client_characteristic_configuration)) and att_handle_measurement > 0:
        print "Found attribute w/UUID=0x2902: handle=%d" % args['chrhandle']
        att_handle_measurement_ccc = args['chrhandle']

    elif args['uuid'] == list(reversed(uuid_client_characteristic_switch)) and att_handle_measurement_ccc > 0:
        print "Found attribute w/UUID=0xf000aa12...: handle=%d" % args['chrhandle']
        att_handle_measurement_switch = args['chrhandle']

# attclient_procedure_completed handler
def my_ble_evt_attclient_procedure_completed(sender, args):
    global state, ble, ser, connection_handle, att_handle_start, att_handle_end, att_handle_measurement, att_handle_measurement_ccc,att_handle_measurement_switch

    # check if we just finished searching for services
    if state == STATE_FINDING_SERVICES:
        if att_handle_end > 0:
            print "Found 'ECG' service with UUID 0xf000aa10...."

            # found the ECG service, so now search for the attributes inside
            state = STATE_FINDING_ATTRIBUTES
            ble.send_command(ser, ble.ble_cmd_attclient_find_information(connection_handle, att_handle_start, att_handle_end))
            ble.check_activity(ser, 1)
        else:
            print "Could not find 'ECG' service with UUID 0xf000aa10"

    # check if we just finished searching for attributes within the ECG service
    elif state == STATE_FINDING_ATTRIBUTES:
        if att_handle_measurement_switch > 0:
            print "Found 'ECG' switch with UUID 0xf000aa12..."

            # found the measurement + client characteristic configuration, so enable notifications
            # (this is done by writing 0x01 to the client characteristic configuration attribute)
            state = STATE_LISTENING_MEASUREMENTS
            ble.send_command(ser, ble.ble_cmd_attclient_attribute_write(connection_handle, att_handle_measurement_switch, [0x01]))
            time.sleep(0.2)
            ble.send_command(ser, ble.ble_cmd_attclient_attribute_write(connection_handle, att_handle_measurement_ccc, [0x01, 0x00]))
            
            ble.check_activity(ser, 1)
        else:
            print "Could not find 'ECG' switch with UUID 0xf000aa12..."

# attclient_attribute_value handler
def my_ble_evt_attclient_attribute_value(sender, args):
    global state, ble, ser, connection_handle, att_handle_measurement,ecg_package_counter,ecg_received_value

    # check for a new value from the connected peripheral's ECG measurement attribute
    if args['connection'] == connection_handle and args['atthandle'] == att_handle_measurement:
        if ble.counter: # check the package counter mode
            ecg_package_counter.append(struct.unpack("<H",b"".join([chr(b) for b in args['value'][:2]]))[0])
            if len(ecg_package_counter)>= 250:
                print "Lost %d packages" % (ecg_package_counter[-1]-ecg_package_counter[0]+1-250),"\nRaw counter value:\n",ecg_package_counter                
                ecg_package_counter = []

        for i in range(2):
            ecgValue = struct.unpack("<f","00".decode("hex")+b"".join([chr(b) for b in args['value'][9*i+5:9*i+8]]))[0]
            if len(ecg_received_value) < 1000: # the buffer length
                ecg_received_value.append(ecgValue)
            else:
                ecg_received_value.pop(0)
                ecg_received_value.append(ecgValue)
        

class plotThread(Thread):
    def __init__(self):
        super(plotThread,self).__init__()
    def run(self):
        global ecg_received_value,state

        fig1 = figure(1,figsize=(10,5))
        ax1 = fig1.add_subplot(111)
        grid('on')
        #xlabel('t[s]')
        while True:
            if state == STATE_LISTENING_MEASUREMENTS:
                ax1.plot(ecg_received_value,'b')
                if len(ax1.lines) >= 2:
                    ax1.lines.pop(0)
                pause(0.4)
            else:
                time.sleep(0.1)

def main():
    global ble, ser, pThread

    # create option parser
    p = optparse.OptionParser(description='BGLib Demo: ECG Collector v' + __version__)

    # set defaults for options
    p.set_defaults(port="/dev/ttyACM0", baud=115200, packet=False, debug=False,counter=False,threadplot=False)

    # create serial port options argument group
    group = optparse.OptionGroup(p, "Connection Options")
    group.add_option('--port', '-p', type="string", help="Serial port device name (default /dev/ttyACM0)", metavar="PORT")
    group.add_option('--baud', '-b', type="int", help="Serial port baud rate (default 115200)", metavar="BAUD")
    group.add_option('--packet', '-k', action="store_true", help="Packet mode (prefix API packets with <length> byte)")
    group.add_option('--debug', '-d', action="store_true", help="Debug mode (show raw RX/TX API packets)")
    group.add_option('--counter', '-c', action="store_true", help="Counter mode (show raw packets counter by notification)")
    group.add_option('--threadplot', '-t', action="store_true", help="Plot mode (must have installed matplotlib module)")
    p.add_option_group(group)

    # actually parse all of the arguments
    options, arguments = p.parse_args()

    # create and setup BGLib object
    ble = bglib.BGLib()
    ble.packet_mode = options.packet
    ble.debug = options.debug
    ble.counter = options.counter
    ble.threadplot = options.threadplot

    # add handler for BGAPI timeout condition (hopefully won't happen)
    ble.on_timeout += my_timeout

    # add handlers for BGAPI events
    ble.ble_evt_gap_scan_response += my_ble_evt_gap_scan_response
    ble.ble_evt_connection_status += my_ble_evt_connection_status
    ble.ble_evt_attclient_group_found += my_ble_evt_attclient_group_found
    ble.ble_evt_attclient_find_information_found += my_ble_evt_attclient_find_information_found
    ble.ble_evt_attclient_procedure_completed += my_ble_evt_attclient_procedure_completed
    ble.ble_evt_attclient_attribute_value += my_ble_evt_attclient_attribute_value

    # create serial port object
    try:
        ser = serial.Serial(port=options.port, baudrate=options.baud, timeout=1, writeTimeout=1)
    except serial.SerialException as e:
        print "\n================================================================"
        print "Port error (name='%s', baud='%ld'): %s" % (options.port, options.baud, e)
        print "================================================================"
        exit(2)

    # flush buffers
    ser.flushInput()
    ser.flushOutput()

    # disconnect if we are connected already
    ble.send_command(ser, ble.ble_cmd_connection_disconnect(0))
    ble.check_activity(ser, 1)

    # stop advertising if we are advertising already
    ble.send_command(ser, ble.ble_cmd_gap_set_mode(0, 0))
    ble.check_activity(ser, 1)

    # stop scanning if we are scanning already
    ble.send_command(ser, ble.ble_cmd_gap_end_procedure())
    ble.check_activity(ser, 1)

    # set scan parameters
    ble.send_command(ser, ble.ble_cmd_gap_set_scan_parameters(0xC8, 0xC8, 1))
    ble.check_activity(ser, 1)

    # start scanning now
    print "Scanning for BLE peripherals..."
    ble.send_command(ser, ble.ble_cmd_gap_discover(1))
    ble.check_activity(ser, 1)

    # start plot thread and wait for data
    if ble.threadplot:
        pThread = plotThread()
        pThread.setDaemon(True) # exit with main thread
        pThread.start()

    while (1):
        # check for all incoming data (no timeout, non-blocking)
        ble.check_activity(ser)

        # don't burden the CPU
        time.sleep(0.01)

# gracefully exit without a big exception message if possible
def ctrl_c_handler(signal, frame):
    print 'Goodbye!'
    exit(0)

signal.signal(signal.SIGINT, ctrl_c_handler)

if __name__ == '__main__':
    main()
