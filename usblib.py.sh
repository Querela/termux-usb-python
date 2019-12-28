#!/bin/bash

cd /data/data/com.termux/files/home/tools/usb
source venv/bin/activate

python3 usblib.py "$@"

deactivate
