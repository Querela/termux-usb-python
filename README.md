
Termux (Android) LibUSB-1.0 adapter (?)
=======================================

List connected USB devices and get ID:

```bash
termux-usb -l
```

Run script (test) with selected device:

```bash
termux-usb -r -e ./usbtest_rw1.py.sh /dev/bus/usb/001/002
```

Create environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
