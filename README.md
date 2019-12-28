
Termux (Android) LibUSB-1.0 adapter (?)
=======================================

See USB infos in termux wiki;
- [example code and termux-usb reference](https://wiki.termux.com/wiki/Termux-usb)

List connected USB devices and get ID:

```bash
termux-usb -l
```

Run script (test) with selected device:

```bash
termux-usb -r -e ./usbtest_rw1.py.sh /dev/bus/usb/001/002
```

## Setup

Create environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Why?

- Android restricts device access, [see comments on libusb](https://sourceforge.net/p/libusb/mailman/message/36486446/)
- Termux only provides a file descriptor (probably queried from Android)
- device handles etc. have to be retrieved from a single file descriptor
- my module `usblib.py` provides a function `device_from_fd(fd)` that extends the [`pyusb`](https://github.com/pyusb/pyusb) library to provide a `Device` object from a file descriptor number that can be used as usual

## CP210x Serial module

- own implementation, guided by:
  - [pySerial](https://github.com/pyserial/pyserial), Timeout object, inspiration for `read_until` etc., only CP2110 handling (with another backend library `hid`)
  - [UsbSerial](https://github.com/felHR85/UsbSerial), command codes & logic flow, adopted from java implementation; flow control untested (_how?_)
- only tested with _cp2102 usb-ttl board v4.2_ device
  - throughput, performance unknown, (seems to work for me)
  - flow control (RTS/CTS, DTR/DSR, Xon/Xoff) untested
  - does transmission have to be in chunks, with size reported in endpoint info or does the libusb1 library handles this? - works fine with chunks, but may drop in performance for heavy use?
  - sync writing?, can a chunk be transmitted in part only (read/write)?
  - no interrupting of transmissions
- test scripts supplied for various _simple_ situations; tests currently only with connected device
- example usage script for _DSO138mini_ data dumps

## Copyright and License Information

Hopefully my _fix_ can be adopted in the original PyUSB library. Else, free for all. :-)

Copyright (c) 2019 Querela. All rights reserved.

See the file "LICENSE" for information on the history of this software, terms & conditions for usage, and a DISCLAIMER OF ALL WARRANTIES.

All trademarks referenced herein are property of their respective holders.
