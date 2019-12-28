#!/usr/bin/env python

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
        # mainly for baud rate
        ser.open(_async=True)
        # just poll read forever
        # ser.read_dump_forever()

        # testing ------
        buf_test(ser)
    finally:
        ser.close()


def buf_test(ser):
    stop = False

    def writer(delay):
        i = 0
        abc = "abcdefghijklmnopqrstuvwxyz"
        while not stop:
            ch = abc[i % len(abc)]
            nl = "\n" if i % 10 == 0 else " "
            data = "{}={}{}".format(ch, i, nl).encode("ascii")
            i += 1

            ser._buf_in.write(data)
            time.sleep(delay)
        print("write stopped")

    def dumper():
        delay = 400.0 / 1000.0
        chunk_size = 100
        while not stop:
            if not ser._buf_in:
                print("wait ...")
                with ser._buf_in.changed:
                    notified = ser._buf_in.changed.wait(delay)
                    print("  notify:", notified)

            data = ser._buf_in.read(chunk_size)
            if not data:
                print("    no data")
                continue
            text = "".join([chr(v) for v in data])
            print("    data:", text, end="\n", flush=True)
        print("read stopped")

    def buf_reads(delay, chunk_size, timeout):
        while not stop:
            if not ser._buf_in:
                with ser._buf_in.changed:
                    notified = ser._buf_in.changed.wait(200 / 1000.0)

            data = ser.read(chunk_size, timeout)
            print(
                "read({}, {}): len:{}, data:{}".format(
                    chunk_size, timeout, len(data), bytes(data)
                )
            )
            time.sleep(delay)
        print("read stopped")

    def buf_read_util(delay, expected, chunk_size, timeout):
        while not stop:
            if not ser._buf_in:
                with ser._buf_in.changed:
                    notified = ser._buf_in.changed.wait(200 / 1000.0)

            data = ser.read_until(expected, chunk_size, timeout)
            print(
                "read_until({}, {}, {}): len:{}, data:{}".format(
                    expected, chunk_size, timeout, len(data), bytes(data)
                )
            )
            time.sleep(delay)
        print("read stopped")

    def buf_read_util2(delay, expected, chunk_size, timeout):
        while not stop:
            if not ser._buf_in:
                with ser._buf_in.changed:
                    notified = ser._buf_in.changed.wait(200 / 1000.0)

            data = ser.read_until_or_none(expected, chunk_size, timeout)
            if data is None:
                print(
                    "read_until({}, {}, {}): {}".format(
                        expected, chunk_size, timeout, data
                    )
                )
            else:
                print(
                    "read_until({}, {}, {}): len:{}, data:{}".format(
                        expected, chunk_size, timeout, len(data), bytes(data)
                    )
                )
            time.sleep(delay)
        print("read stopped")

    #  dump all, shows locking+notificationd
    tr = threading.Thread(target=dumper)

    #  buf reads, no-block
    # tr = threading.Thread(target=buf_reads, args=(10.0 / 1000.0, 100, 0))

    #  buf reads, block, hangs on Stop ...
    # tr = threading.Thread(target=buf_reads, args=(10.0 / 1000.0, 25, None))

    #  buf reads, timeout 3 sec, 25 chars
    # tr = threading.Thread(target=buf_reads, args=(10.0 / 1000.0, 25, 3000.0 / 1000.0))

    #  buf reads, timeout 3 sec, any char len, mostly empty?
    # tr = threading.Thread(target=buf_reads, args=(10.0 / 1000.0, None, 3000.0 / 1000.0))

    #  until char \n, 3 sec, any size
    # tr = threading.Thread(target=buf_read_util, args=(10.0 / 1000.0, b"\n", None, 3000.0 / 1000.0))

    #  until char \n, block, any size
    # tr = threading.Thread(target=buf_read_util, args=(10.0 / 1000.0, b"\n", None, None))

    #  until char \n, block, 17 chars
    # tr = threading.Thread(target=buf_read_util, args=(10.0 / 1000.0, b"\n", 17, None))

    #  until char \n, no-block, 17 chars
    # tr = threading.Thread(target=buf_read_util, args=(10.0 / 1000.0, b"\n", 17, 0))

    #  until no char, 4 sec, 17 chars - always returns
    # tr = threading.Thread(target=buf_read_util, args=(10.0 / 1000.0, b"", 17, 4000.0 / 1000.0))

    #  until char "0\n", 4 sec, 17 chars
    # tr = threading.Thread(target=buf_read_util, args=(10.0 / 1000.0, b"0\n", 17, 4000.0 / 1000.0))

    #  until char \n or none, 3 sec, any size
    # tr = threading.Thread(target=buf_read_util2, args=(10.0 / 1000.0, b"\n", None, 3000.0 / 1000.0))

    #  until char \n or none, no-block, 17 chars - will always return if too
    #  much data and immediate
    # tr = threading.Thread(target=buf_read_util2, args=(10.0 / 1000.0, b"\n", 17, 0))

    #  until char \n or none, 3 sec, 33 chars,
    #  fast return if size limit reached
    # tr = threading.Thread(target=buf_read_util2, args=(10.0 / 1000.0, b"\n", 33, 3000.0 / 1000.0))

    #  until char \n or none, no-block, any size
    #  fast return with None but sometimes result
    # tr = threading.Thread(target=buf_read_util2, args=(10.0 / 1000.0, b"\n", None, 0))

    #  until char \n or none, block, any size
    #  block until result or forever
    # tr = threading.Thread(target=buf_read_util2, args=(10.0 / 1000.0, b"\n", None, None))

    tw = threading.Thread(target=writer, args=(1000.0 / 1000.0,))

    tr.start()
    tw.start()

    # ser._buf_out.write(b"test\n")
    # time.sleep(1)
    # ser._buf_out.write(b"test 1\n")
    # time.sleep(1)
    # ser._buf_out.write(b"test 2\n")
    # time.sleep(1)

    try:
        time.sleep(30)
    except KeyboardInterrupt:
        pass

    stop = True
    tw.join()
    tr.join()
    print("test done")


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
