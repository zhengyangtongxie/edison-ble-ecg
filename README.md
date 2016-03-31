# 1 Raspberry Pi 2B collect ECG data from ECG signal acquisition device through BLE (Python) 

The 'ecgTest.py' file is based on Bluez-5.32 (The version must >=5.0,a bluetooth stack based on linux OS)
The detailed install procedure was referred to http://www.elinux.org/RPi_Bluetooth_LE 

The hardware:
    Bluetooth4.0 Dongle,Raspberry Pi 2B
The software:
    Bluez>=5.0,Python2.7.3 (with module Pexpect)

# 2 Raspberry Pi 2B collect ECG data from ECG signal acquisition device through BLE (Python) 

The 'ble_test_ecg_collector.py' was based on bluetooth smart software and developed from the file "bglib.py". 
Other examples like Heart Rate etc could referred to https://github.com/jrowberg/bglib'

Note: you must know the UUID of ECG on your device.

The hardware:
    BLED11x Dongle,Raspberry Pi 2B
The software:
    Python2.7.3 (with module Matplotlib)