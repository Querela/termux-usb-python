#!/usr/bin/env python

import logging

from usblib import device_from_fd
from usblib import shell_usbdevice


LOGGER = logging.getLogger(__name__)


# ----------------------------------------------------------------------------


def main(fd):
    device = device_from_fd(fd)

    shell_usbdevice(fd, device)

    print("\n", "#" * 40, "\n")
    print(device)


if __name__ == "__main__":
    # https://wiki.termux.com/wiki/Termux-usb
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname).1s] %(name)s: %(message)s"
    )
    logging.getLogger(__name__).setLevel(logging.DEBUG)
    logging.getLogger("usblib").setLevel(logging.DEBUG)

    # grab fd number from args
    #   (from termux wrapper)
    import sys

    LOGGER.debug("args: %s", sys.argv)

    fd = int(sys.argv[1])
    main(fd)
