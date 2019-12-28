#!/usr/bin/env python

import logging
import threading

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
        # mainly for baud rate
        ser.open(_async=True)
        # just poll read forever
        ser.read_dump_forever()
    finally:
        ser.close()


if __name__ == "__main__":
    # https://wiki.termux.com/wiki/Termux-usb
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname).1s] %(name)s: %(message)s"
    )
    logging.getLogger(__name__).setLevel(logging.DEBUG)
    logging.getLogger("usblib").setLevel(logging.DEBUG)
    logging.getLogger("usb").setLevel(logging.DEBUG)

    # grab fd number from args
    #   (from termux wrapper)
    import sys

    LOGGER.debug("args: %s", sys.argv)

    fd = int(sys.argv[1])
    main(fd)
