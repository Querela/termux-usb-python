#!/usr/bin/env python

import json
import logging
import threading
import time

from usblib import device_from_fd
from usblib import shell_usbdevice
from usblib import CP210xSerial


LOGGER = logging.getLogger(__name__)


# ----------------------------------------------------------------------------


def main(fd, debug=False):
    device = device_from_fd(fd)

    if debug:
        shell_usbdevice(fd, device)

        print("\n", "#" * 40, "\n")
        print(device)

    assert device.idVendor == 0x10C4 and device.idProduct == 0xEA60

    ser = CP210xSerial(device, baudRate=115200)
    try:
        ser.open(_async=True)

        data = grab_data(ser)

        fn = "dso138mini.grab.json"
        with open(fn, "w") as fp:
            json.dump(data, fp, indent=2)
    finally:
        ser.close()


def grab_data(ser):
    delay = 5000.0 / 1000.0
    header = None
    transfers = list()

    LOGGER.info("Trying to grab header for 30 sec ...")
    try:
        data = ser.read(16 * 1024, 30.0)
        if data:
            text = data.decode("utf-8").strip()
            header = text.splitlines()
    except KeyboardInterrupt:
        pass

    LOGGER.info("Waiting for dumps ...")
    while True:
        try:
            print("   Waiting", end="", flush=True)
            while not ser._buf_in:
                with ser._buf_in.changed:
                    notified = ser._buf_in.changed.wait(delay)
                    print(".", end="", flush=True)
                    if not notified:
                        continue
            print()

            # consume all to finish?
            # on mismatch?

            meta, rows = dict(), list()
            for i in range(19 + 1024):
                line = ser.read_until(b"\n", -1, 1.0)
                line = line.decode("utf-8").rstrip()
                if i < 19:
                    key, value = line.split(",")
                    key, value = key.strip(), value.strip()
                    meta[key] = value
                else:
                    idx, x, y = line.split(",")
                    x, y = x.strip(), y.strip()
                    x, y = int(x), float(y)
                    rows.append((x, y))

            transfers.append({"meta": meta, "data": rows})
            LOGGER.info("Got record.")
        except KeyboardInterrupt:
            break

    return {"header": header, "transfers": transfers}


if __name__ == "__main__":
    # https://wiki.termux.com/wiki/Termux-usb
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname).1s] %(name)s: %(message)s"
    )
    logging.getLogger(__name__).setLevel(logging.DEBUG)
    logging.getLogger("usblib").setLevel(logging.DEBUG)
    logging.getLogger("usblib.RXTX").setLevel(logging.INFO)
    logging.getLogger("usb").setLevel(logging.DEBUG)

    # grab fd number from args
    #   (from termux wrapper)
    import sys

    LOGGER.debug("args: %s", sys.argv)

    fd = int(sys.argv[1])
    main(fd)
