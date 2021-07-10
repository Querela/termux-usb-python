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
        # ser.read_dump_forever()

        # testing ------
        dump_test(ser)
    finally:
        ser.close()


def dump_test(ser):
    stop = False

    def dumper():
        while not stop:
            data = ser._buf_in.read(100)
            text = "".join(chr(v) for v in data)
            print(text, end="", flush=True)

    t = threading.Thread(target=dumper)
    t.start()

    import time

    ser._buf_out.write(b"test\n")
    time.sleep(1)
    ser._buf_out.write(b"test 1\n")
    time.sleep(1)
    ser._buf_out.write(b"test 2\n")
    time.sleep(2)

    endp_in, endp_out = CP210xSerial.get_endpoints(ser.device)
    print(ser.device.write(endp_out, bytearray(100)))
    print(ser.device.read(endp_in, 100))
    # print(ser.device.read(endp_in, 100))
    # print(ser.device.read(endp_in, 100))
    time.sleep(2)
    time.sleep(1)
    stop = True
    t.join()
    print("test done")


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
