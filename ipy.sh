#!/bin/bash

echo ""
echo "USB file descriptor: $@"
echo ""

cd /data/data/com.termux/files/home/tools/usb
source venv/bin/activate

ipython

deactivate
