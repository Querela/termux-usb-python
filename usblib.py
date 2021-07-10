#!/usr/bin/env python

import logging
import struct
import threading
import time

import usb.backend.libusb1 as libusb1
import usb.control
import usb.core
import usb.util

# from pyftdi.misc import hexdump
from pyftdi.misc import hexline


LOGGER = logging.getLogger(__name__)
RXTXLOGGER = logging.getLogger("{}.RXTX".format(__name__))

# ----------------------------------------------------------------------------


CP210x_PURGE = 0x12
CP210x_IFC_ENABLE = 0x00
CP210x_SET_BAUDDIV = 0x01
CP210x_SET_LINE_CTL = 0x03
CP210x_GET_LINE_CTL = 0x04
CP210X_SET_BREAK = 0x05
CP210x_SET_MHS = 0x07
CP210x_SET_BAUDRATE = 0x1E
CP210x_SET_FLOW = 0x13
CP210x_SET_XON = 0x09
CP210x_SET_XOFF = 0x0A
CP210x_SET_CHARS = 0x19
CP210x_GET_MDMSTS = 0x08
CP210x_GET_COMM_STATUS = 0x10

CP210x_REQTYPE_HOST2DEVICE = 0x41
CP210x_REQTYPE_DEVICE2HOST = 0xC1

# ------------------------------------

CP210x_BREAK_ON = 0x0001
CP210x_BREAK_OFF = 0x0000

CP210x_MHS_RTS_ON = 0x202
CP210x_MHS_RTS_OFF = 0x200
CP210x_MHS_DTR_ON = 0x101
CP210x_MHS_DTR_OFF = 0x100

CP210x_PURGE_ALL = 0x000F

SILABSER_FLUSH_REQUEST_CODE = 0x12
FLUSH_READ_CODE = 0x0A
FLUSH_WRITE_CODE = 0x05

CP210x_UART_ENABLE = 0x0001
CP210x_UART_DISABLE = 0x0000
CP210x_LINE_CTL_DEFAULT = 0x0800
CP210x_MHS_DEFAULT = 0x0000
CP210x_MHS_DTR = 0x0001
CP210x_MHS_RTS = 0x0010
CP210x_MHS_ALL = 0x0011
CP210x_XON = 0x0000
CP210x_XOFF = 0x0000

DEFAULT_BAUDRATE = 9600

# ------------------------------------

DATA_BITS_5 = 5
DATA_BITS_6 = 6
DATA_BITS_7 = 7
DATA_BITS_8 = 8

STOP_BITS_1 = 1
STOP_BITS_15 = 3
STOP_BITS_2 = 2

PARITY_NONE = 0
PARITY_ODD = 1
PARITY_EVEN = 2
PARITY_MARK = 3
PARITY_SPACE = 4

FLOW_CONTROL_OFF = 0
FLOW_CONTROL_RTS_CTS = 1
FLOW_CONTROL_DSR_DTR = 2
FLOW_CONTROL_XON_XOFF = 3


#: in msec
DEFAUL_TIMEOUT = 500

# ----------------------------------------------------------------------------


def device_from_fd(fd):
    # setup library
    backend = libusb1.get_backend()
    lib = backend.lib
    ctx = backend.ctx

    # extend c wrapper with android functionality
    lib.libusb_wrap_sys_device.argtypes = [
        libusb1.c_void_p,
        libusb1.c_int,
        libusb1.POINTER(libusb1._libusb_device_handle),
    ]

    lib.libusb_get_device.argtypes = [libusb1.c_void_p]
    lib.libusb_get_device.restype = libusb1._libusb_device_handle

    LOGGER.debug("usb fd: %s", fd)

    # get handle from file descriptor
    handle = libusb1._libusb_device_handle()
    libusb1._check(lib.libusb_wrap_sys_device(ctx, fd, libusb1.byref(handle)))
    LOGGER.debug("usb handle: %s", handle)

    # get device (id?) from handle
    devid = lib.libusb_get_device(handle)
    LOGGER.debug("usb devid: %s", devid)

    # device: devid + handle wrapper
    class DummyDevice:
        def __init__(self, devid, handle):
            self.devid = devid
            self.handle = handle

    dev = DummyDevice(devid, handle)

    # create pyusb device
    device = usb.core.Device(dev, backend)
    device._ctx.handle = dev

    # device.set_configuration()

    return device


def shell_usbdevice(fd, device):
    # interactive explore
    backend = device.backend
    lib = backend.lib
    ctx = backend.ctx
    dev = device._ctx.handle
    handle = dev.handle
    devid = dev.devid

    # query some information
    dev_desc = backend.get_device_descriptor(dev)
    config_desc = backend.get_configuration_descriptor(dev, 0)

    from IPython.terminal.embed import InteractiveShellEmbed
    from IPython.terminal.ipapp import load_default_config

    InteractiveShellEmbed.clear_instance()
    namespace = {
        "fd": fd,
        "handle": handle,
        "devid": devid,
        "dev": dev,
        "dev_desc": dev_desc,
        "config_desc": config_desc,
        "device": device,
        "libusb1": libusb1,
        "backend": backend,
        "lib": lib,
        "ctx": ctx,
    }
    banner = (
        "Variables:\n"
        + "\n".join(
            "{:>12}: {}".format(k, repr(v)) for k, v in namespace.items()
        )
    ) + "\n"

    shell = InteractiveShellEmbed.instance(banner1=banner, user_ns=namespace)
    shell()


# ----------------------------------------------------------------------------


class Buffer:
    # https://stackoverflow.com/a/57748513/9360161
    def __init__(self):
        self.buf = bytearray()
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        # TODO: max size? - dequeue? / ringbuffer

    def clear(self):
        with self.lock:
            self.buf[:] = b""
            self.changed.notify()

    def write(self, data):
        with self.lock:
            try:
                if isinstance(data, int):
                    self.buf.append(data)
                    return 1
                else:
                    self.buf.extend(data)
                    return len(data)
            finally:
                self.changed.notify()

    def read(self, size):
        with self.lock:
            try:
                # if size == 1:
                #     return self.buf.pop(0)

                if not size or size <= 0:
                    # None, 0, negative
                    size = len(self)

                data = self.buf[:size]
                self.buf[:size] = b""
                return data
            finally:
                self.changed.notify()

    def read_until(self, expected, size=-1):
        try:
            elen = len(expected)
        except TypeError:
            elen = 1

        with self.lock:
            pos = self.buf.find(expected)

            # not found, return max
            if pos == -1:
                return self.read(size)

            # found, compute total length
            elen = pos + elen
            # if len restriction then until limit
            if size > 0 and elen > size:
                return self.read(size)
            # return normal
            return self.read(elen)

    def contains(self, expected):
        with self.lock:
            return self.buf.find(expected) != -1

    def peek(self, size):
        return self.buf[:size]

    def __len__(self):
        return len(self.buf)


class Timeout:
    """\
    Abstraction for timeout operations. Using time.monotonic().
    The class can also be initialized with 0 or None, in order to support
    non-blocking and fully blocking I/O operations. The attributes
    is_non_blocking and is_infinite are set accordingly.
    """

    TIME = time.monotonic

    def __init__(self, duration):
        """Initialize a timeout with given duration."""
        self.is_infinite = duration is None
        self.is_non_blocking = duration == 0
        self.duration = duration
        self.target_time = self.TIME() + duration if duration is not None else None

    def expired(self):
        """Return a boolean, telling if the timeout has expired."""
        return self.target_time is not None and self.time_left() <= 0

    def time_left(self):
        """Return how many seconds are left until the timeout expires."""
        if self.is_non_blocking:
            return 0
        elif self.is_infinite:
            return None
        else:
            delta = self.target_time - self.TIME()
            if delta <= self.duration:
                return max(0, delta)

            # clock jumped, recalculate
            self.target_time = self.TIME() + self.duration
            return self.duration

    def restart(self, duration):
        """\
        Restart a timeout, only supported if a timeout was already set up
        before.
        """
        self.is_infinite = duration is None
        self.is_non_blocking = duration == 0
        self.duration = duration
        self.target_time = self.TIME() + duration

    # --------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        pass


class AbstractStoppableThread(threading.Thread):
    def __init__(self, serial, *args, **kwargs):
        super(AbstractStoppableThread, self).__init__(*args, **kwargs)
        self.serial = serial
        self.should_stop = False

    def stop(self):
        self.should_stop = True

    def shouldRun(self):
        if self.should_stop:
            return False

        if not self.serial.is_open:
            return False

        return True

    def run(self):
        while self.shouldRun():
            self.runOne()

    def runOne(self):
        raise NotImplementedError


# TODO: r/w may not need to happen in chunks?


class SerialBufferReadThread(AbstractStoppableThread):
    def __init__(self, serial, endpoint, buffer, timeout=None, *args, **kwargs):
        super(SerialBufferReadThread, self).__init__(serial, *args, **kwargs)
        self.endpoint = endpoint
        self.buffer = buffer
        self.timeout = timeout

    def runOne(self):
        ser = self.serial
        device = ser.device
        endp = self.endpoint
        buf = self.buffer

        data = None
        try:
            data = device.read(endp.bEndpointAddress, endp.wMaxPacketSize, self.timeout)
            RXTXLOGGER.debug("[RX] %s", hexline(data))
        except libusb1.USBError as ue:
            # 110/-7 for timeout
            if ue.errno != 110:
                raise
            RXTXLOGGER.debug(
                "RX Timeout: errno: %s, backend_error_code: %s",
                ue.errno,
                ue.backend_error_code,
            )
        if data is not None:
            buf.write(data)
        # TODO: event


class SerialBufferWriteThread(AbstractStoppableThread):
    def __init__(
        self, serial, endpoint, buffer, timeout=DEFAUL_TIMEOUT, *args, **kwargs
    ):
        super(SerialBufferWriteThread, self).__init__(serial, *args, **kwargs)
        self.endpoint = endpoint
        self.buffer = buffer
        self.timeout = timeout

    def runOne(self):
        ser = self.serial
        device = ser.device
        endp = self.endpoint
        buf = self.buffer

        if not buf:
            with buf.changed:
                buf.changed.wait(self.timeout / 1000.0)

        data = buf.read(endp.wMaxPacketSize)
        if not data:
            return

        RXTXLOGGER.debug("[TX] %s", hexline(data))
        num = device.write(endp.bEndpointAddress, data, self.timeout)

        if num < len(data):
            RXTXLOGGER.error(
                "TX data loss: wrote %s of %s bytes! data: %s",
                num,
                len(data),
                hexline(data),
            )

        # TODO: event


class CP210xSerial:
    def __init__(self, device, baudRate=DEFAULT_BAUDRATE):
        assert self.is_usb_cp210x(device), "Unknown CP210x device!"
        self._device = device
        self._intf = 0

        self._baudRate = baudRate
        self._rtsCts_enabled = False
        self._dtrDsr_enabled = False
        self._cts_state = False
        self._dsr_state = False
        self._thrd_flowControl = None

        self._is_open = False
        self._is_async = False
        self._buf_in = Buffer()
        self._buf_out = Buffer()
        self._thrd_buf_in = None
        self._thrd_buf_out = None

    @staticmethod
    def is_usb_cp210x(device):
        # https://github.com/felHR85/UsbSerial/blob/master/usbserial/src/main/java/com/felhr/deviceids/CP210xIds.java
        idVendor = device.idVendor
        idProduct = device.idProduct

        abbrev_cp210x_ids = [(0x10C4, 0xEA60)]

        return (idVendor, idProduct) in abbrev_cp210x_ids

    @staticmethod
    def is_endpoint_dir_in(endpoint):
        address = endpoint.bEndpointAddress
        endp_dir = usb.util.endpoint_direction(address)
        return endp_dir == usb.util.ENDPOINT_IN

    @staticmethod
    def get_endpoints(device):
        configuration = device.configurations()[0]
        interface = configuration.interfaces()[0]
        endpoints = interface.endpoints()

        # https://android.googlesource.com/platform/frameworks/base/+/master/core/java/android/hardware/usb/UsbEndpoint.java
        # https://android.googlesource.com/platform/frameworks/base/+/master/core/java/android/hardware/usb/UsbConstants.java

        endp_in, endp_out = endpoints
        if not CP210xSerial.is_endpoint_dir_in(endp_in):
            endp_in, endp_out = endp_out, endp_in

        return endp_in, endp_out

    # --------------------------------

    def send_ctrl_cmd(self, request, value=0, data=None, intf=0):
        return self._device.ctrl_transfer(
            CP210x_REQTYPE_HOST2DEVICE,
            request,
            wValue=value,
            wIndex=intf,
            data_or_wLength=data,
            timeout=None,
        )

    def recv_ctrl_cmd(self, request, blen, value=0, intf=0):
        buf = usb.util.create_buffer(blen)
        ret = self._device.ctrl_transfer(
            CP210x_REQTYPE_DEVICE2HOST,
            request,
            wValue=value,
            wIndex=intf,
            data_or_wLength=buf,
            timeout=None,
        )
        print("recv:", ret, buf)
        return buf

    # --------------------------------

    def set_baudRate(self, baudRate):
        data = struct.unpack("4B", struct.pack("<I", baudRate))
        ret = self.send_ctrl_cmd(CP210x_SET_BAUDRATE, 0, data)
        if ret >= 0:
            self._baudRate = baudRate
        return ret

    def set_flowControl(self, flowControl):
        assert flowControl == FLOW_CONTROL_OFF, "Others not implemented!"

        if flowControl == FLOW_CONTROL_OFF:
            dataOff = [
                0x01,
                0x00,
                0x00,
                0x00,
                0x40,
                0x00,
                0x00,
                0x00,
                0x00,
                0x80,
                0x00,
                0x00,
                0x00,
                0x20,
                0x00,
                0x00,
            ]
            self._rtsCts_enabled = False
            self._dtrDsr_enabled = False
            self._stop_thread_flowControl()
            return self.send_ctrl_cmd(CP210x_SET_FLOW, 0, dataOff)
        elif flowControl == FLOW_CONTROL_RTS_CTS:
            dataRtsCts = [
                0x09,
                0x00,
                0x00,
                0x00,
                0x40,
                0x00,
                0x00,
                0x00,
                0x00,
                0x80,
                0x00,
                0x00,
                0x00,
                0x20,
                0x00,
                0x00,
            ]
            self._rtsCts_enabled = True
            self._dtrDsr_enabled = False
            _ = self.send_ctrl_cmd(CP210x_SET_FLOW, 0, dataRtsCts)
            _ = self.send_ctrl_cmd(CP210x_SET_MHS, CP210x_MHS_RTS_ON, None)
            commStatusCTS = self.get_comm_status()
            self._cts_state = (commStatusCTS[4] & 0x01) == 0x00
            self._start_thread_flowControl()
        elif flowControl == FLOW_CONTROL_DSR_DTR:
            dataDsrDtr = [
                0x11,
                0x00,
                0x00,
                0x00,
                0x40,
                0x00,
                0x00,
                0x00,
                0x00,
                0x80,
                0x00,
                0x00,
                0x00,
                0x20,
                0x00,
                0x00,
            ]
            self._rtsCts_enabled = False
            self._dtrDsr_enabled = True
            _ = self.send_ctrl_cmd(CP210x_SET_FLOW, 0, dataDsrDtr)
            _ = self.send_ctrl_cmd(CP210x_SET_MHS, CP210x_MHS_DTR_ON, None)
            commStatusDSR = self.get_comm_status()
            self._dsr_state = (commStatusDSR[4] & 0x02) == 0x00
            self._start_thread_flowControl()
        elif flowControl == FLOW_CONTROL_XON_XOFF:
            dataXonXoff = [
                0x01,
                0x00,
                0x00,
                0x00,
                0x43,
                0x00,
                0x00,
                0x00,
                0x00,
                0x80,
                0x00,
                0x00,
                0x00,
                0x20,
                0x00,
                0x00,
            ]
            dataChars = [
                0x00,
                0x00,
                0x00,
                0x00,
                0x11,
                0x13,
            ]
            _ = self.send_ctrl_cmd(CP210x_SET_CHARS, 0, dataChars)
            _ = self.send_ctrl_cmd(CP210x_SET_FLOW, 0, dataXonXoff)
            # self._stop_thread_flowControl() # ?

        return 0

    def set_dataBits(self, dataBits):
        val = self.get_CTL()
        val &= ~0x0F00

        if dataBits not in (DATA_BITS_5, DATA_BITS_6, DATA_BITS_7, DATA_BITS_8):
            return

        val |= dataBits << 8

        self.send_ctrl_cmd(CP210x_SET_LINE_CTL, val, None)

    def set_stopBits(self, stopBits):
        val = self.get_CTL()
        val &= ~0x0003

        if stopBits == STOP_BITS_1:
            val |= 0x0000
        elif stopBits == STOP_BITS_15:
            val |= 0x0001
        elif stopBits == STOP_BITS_2:
            val |= 0x0002
        else:
            return

        self.send_ctrl_cmd(CP210x_SET_LINE_CTL, val, None)

    def set_parity(self, parity):
        val = self.get_CTL()
        val &= ~0x00F0

        if parity not in (
            PARITY_NONE,
            PARITY_ODD,
            PARITY_EVEN,
            PARITY_MARK,
            PARITY_SPACE,
        ):
            return

        val |= parity << 4

        self.send_ctrl_cmd(CP210x_SET_LINE_CTL, val, None)

    def set_break(self, on):
        if on:
            self.send_ctrl_cmd(CP210X_SET_BREAK, CP210x_BREAK_ON, None)
        else:
            self.send_ctrl_cmd(CP210X_SET_BREAK, CP210x_BREAK_OFF, None)

    def set_RTS(self, on):
        if on:
            self.send_ctrl_cmd(CP210x_SET_MHS, CP210x_MHS_RTS_ON, None)
        else:
            self.send_ctrl_cmd(CP210x_SET_MHS, CP210x_MHS_RTS_OFF, None)

    def set_DTR(self, on):
        if on:
            self.send_ctrl_cmd(CP210x_SET_MHS, CP210x_MHS_DTR_ON, None)
        else:
            self.send_ctrl_cmd(CP210x_SET_MHS, CP210x_MHS_DTR_OFF, None)

    def get_modem_state(self):
        return self.recv_ctrl_cmd(CP210x_GET_MDMSTS, 1)

    def get_comm_status(self):
        return self.recv_ctrl_cmd(CP210x_GET_COMM_STATUS, 19)

    def get_CTL(self):
        buf = self.recv_ctrl_cmd(CP210x_GET_LINE_CTL, 2)
        return struct.unpack("<H", buf.tobytes())[0]

    def purgeHWBuffer(self, rx, tx):
        # https://github.com/mik3y/usb-serial-for-android/blob/master/usbSerialForAndroid/src/main/java/com/hoho/android/usbserial/driver/Cp21xxSerialDriver.java#L304
        val = 0x00
        if rx:
            val |= FLUSH_READ_CODE
        if tx:
            val |= FLUSH_WRITE_CODE

        if not val:
            return

        self.send_ctrl_cmd(SILABSER_FLUSH_REQUEST_CODE, val, None)

    # --------------------------------

    @property
    def device(self):
        return self._device

    @property
    def is_open(self):
        return self._is_open

    @property
    def baudrate(self):
        return self._baudRate

    @baudrate.setter
    def baudrate(self, baudRate):
        self.set_baudRate(baudRate)

    # --------------------------------

    # r/w
    # - async on buffers/queue with threads

    def read(self, size=-1, timeout=None):
        """Read size bytes from RX buffer.

        If size is negative, zero or None then read all data.

        If timeout is None, then block read until size bytes read.
        If timeout is 0, then un-blocking, return as soon as read
        size bytes finished. Else timeout should be in seconds,
        with possible fractions.
        """
        # TODO: check async

        buf = self._buf_in
        if not size or size <= 0:
            return buf.read(size)

        with Timeout(timeout) as to:
            data = bytearray()
            data += buf.read(size)

            while not to.expired() and size > len(data):
                if not buf:
                    # wait for more, delay
                    delay = to.time_left()
                    if delay is None:
                        delay = 1000
                    with buf.changed:
                        buf.changed.wait(delay / 1000.0)
                rlen = size - len(data)
                chunk = buf.read(rlen)
                data += chunk

            # TODO: convert to single byte if array len is 1?

            return data

        # while buf:
        #     frag = buf.read(1024)
        #     if not len(frag):
        #         break
        #     data.extend(frag)
        # return data

    def read_until(self, expected=b"\n", size=None, timeout=None):
        """Read from RX buffer until chars found.

        This method may be helpful to read lines from a buffer, etc.

        expected is a single byte or a sequence of bytes (byte
        string, array, list, ...) that Python can use for
        bytearray.find(expected) .

        size gives an upper limit of how much bytes before the search
        string are to be read. A not positive number means infinite.

        timeout limits the time until the search string is found. A
        timeout of zero returns after the frist read regardless if
        search is successful. None means to block until found or size
        limit is reached.

        Note that a unlimited size (-1/None) and a blocking timeout
        (None) may never return if the search pattern is never found!
        """
        if not size or size <= 0:
            size = -1

        # isinstance(expected, (tuple, list, array.array, bytes, bytearray))
        try:
            expected_last = expected[-1]
        except:
            # TypeError, IndexError
            expected_last = expected

        buf = self._buf_in
        with Timeout(timeout) as to:
            data = bytearray()
            data += buf.read_until(expected, size)

            # read in loop, blocking
            while not to.expired() and data.find(expected) == -1:
                if size > 0 and size <= len(data):
                    break

                if not buf:
                    # wait for more, delay
                    delay = to.time_left()
                    if delay is None:
                        delay = DEFAUL_TIMEOUT
                    with buf.changed:
                        buf.changed.wait(delay / 1000.0)
                rlen = size - len(data) if size > 0 else size
                chunk = buf.read_until(expected_last, rlen)
                data += chunk

        return data

    def read_until_or_none(self, expected=b"\n", size=None, timeout=None):
        """Read from RX buffer until chars found, return None if not found.

        This method may be helpful to read lines from a buffer, etc.
        It will return None if the chars are not in the size
        restriction or if the operation timed out.

        expected is a single byte or a sequence of bytes (byte
        string, array, list, ...) that Python can use for
        bytearray.find(expected) .

        size gives an upper limit of how much bytes before the search
        string are to be read. A not positive number means infinite.

        timeout limits the time until the search string is found. A
        timeout of zero means an immediate result regardless if the
        search is successful. None means to block until found or size
        limit is reached.

        Note that a unlimited size (-1/None) and a blocking timeout
        (None) may never return if the search pattern is never found!
        """
        if not size or size <= 0:
            size = -1

        buf = self._buf_in
        with Timeout(timeout) as to:
            while not to.expired() and not buf.contains(expected):
                # check if in size limit
                if size > 0 and size < len(buf):
                    break

                # wait for more, delay
                delay = to.time_left()
                if delay is None:
                    delay = DEFAUL_TIMEOUT
                with buf.changed:
                    buf.changed.wait(delay / 1000.0)

        if not buf.contains(expected):
            return None

        # lock if parallel
        with buf.lock:
            # check if needle in size limit
            if size > 0 and size < len(buf):
                data_peek = buf.peek(size)
                if data_peek.find(expected) == -1:
                    return None

            # needle should be in limit
            data = bytearray()
            data += buf.read_until(expected, size)
            return data

    def wait_on_read_buffer(self, duration):
        """Wait for RX buffer to contain data.

        If RX buffer contains data return True.
        Wait on buffer until changed, if timeout return False, else
        True (on update, cut timeout short)."""
        if self._buf_in:
            return True

        with self._buf_in.changed:
            return self._buf_in.changed.wait(duration)

    def wait_on_write_buffer(self, duration):
        """Wait for TX buffer to empty.

        If buffer empty return True immediately.
        If TX buffer contains data after timeout return False, else
        True if empty.
        """
        if not self._buf_out:
            return True

        with self._buf_out.changed:
            self._buf_out.changed.wait(duration)

        return not self._buf_out

    def write(self, data):
        # TODO: check async

        self._buf_out.write(data)

    # - sync
    # note: better to use buffers above?

    # TODO: r/w may not need to happen in chunks?

    def read_sync_chunked(self, size):
        device = self._device
        endp_in = CP210xSerial.get_endpoints(device)[0]

        if not size or size <= 0:
            return None

        data = bytearray()
        while size > len(data):
            rlen = min(endp_in.wMaxPacketSize, size - len(data))
            chunk = device.read(endp_in.bEndpointAddress, rlen)
            if not chunk:
                break

            data += chunk

        return data

    def write_sync_chunked(self, data):
        device = self._device
        endp_out = CP210xSerial.get_endpoints(device)[1]

        if isinstance(data, int):
            data = bytearray([data])
        elif not data:
            return 0
        else:
            data = bytearray(data)

        total = len(data)

        while data:
            slen = min(endp_out.wMaxPacketSize, len(data))
            chunk = data[:slen]
            sent = device.write(endp_out.bEndpointAddress, chunk)
            if not sent:
                break

            data[:sent] = b""

        return total - len(data)

    def read_sync(self, size):
        device = self._device
        endp_in = CP210xSerial.get_endpoints(device)[0]

        if not size or size <= 0:
            return None

        # may time out and raise USBError ...
        return device.read(endp_in.bEndpointAddress, size)

    def write_sync(self, data):
        device = self._device
        endp_out = CP210xSerial.get_endpoints(device)[1]

        if isinstance(data, int):
            data = bytearray([data])
        elif not data:
            return 0
        else:
            data = bytearray(data)

        return device.write(endp_out.bEndpointAddress, data)

    # --------------------------------

    # TODO: threads + buffers

    class FlowControlThread(AbstractStoppableThread):
        def __init__(self, serial, delay=40, *args, **kwargs):
            super(CP210xSerial.FlowControlThread, self).__init__(
                serial, *args, **kwargs
            )
            # msec
            self.delay = delay

        def runOne(self):
            # wait delay

            ser = self.serial
            modemState = ser.get_modem_state()
            commStatus = ser.get_comm_status()

            if ser._rtsCts_enabled:
                new_cts_state = (modemState[0] & 0x10) == 0x10
                if ser._cts_state != new_cts_state:
                    ser._cts_state = new_cts_state
                    # TODO: cts callback

            if ser._dtrDsr_enabled:
                new_dsr_state = (modemState[0] & 0x20) == 0x20
                if ser._dsr_state != new_dsr_state:
                    ser._dsr_state = new_dsr_state
                    # TODO: dsr callback

            has_parity_error = (commStatus[0] & 0x10) == 0x10
            has_framinh_error = (commStatus[0] & 0x02) == 0x02
            is_break_interrupt = (commStatus[0] & 0x01) == 0x01
            has_overrun_error = ((commStatus[0] & 0x04) == 0x04) or (
                (commStatus[0] & 0x8) == 0x08
            )
            # TODO: callbacks

    def _start_thread_flowControl(self):
        if self._thrd_flowControl:
            if self._thrd_flowControl.is_alive():
                return
            self._stop_thread_flowControl()

        self._thrd_flowControl = CP210xSerial.FlowControlThread(self)
        self._thrd_flowControl.start()

    def _stop_thread_flowControl(self):
        if self._thrd_flowControl:
            self._thrd_flowControl.stop()
            self._thrd_flowControl = None

    def _start_threads_buffer_rw(self):
        start_in = start_out = True
        if self._thrd_buf_in:
            if self._thrd_buf_in.is_alive():
                start_in = False
            else:
                self._thrd_buf_in.stop()
                self._thrd_buf_in = None
        if self._thrd_buf_out:
            if self._thrd_buf_out.is_alive():
                start_out = False
            else:
                self._thrd_buf_out.stop()
                self._thrd_buf_out = None

        # TODO: stop anyway and join?

        endp_in, endp_out = CP210xSerial.get_endpoints(self.device)

        if start_in:
            self._thrd_buf_in = SerialBufferReadThread(self, endp_in, self._buf_in)
            self._thrd_buf_in.start()

        if start_out:
            self._thrd_buf_out = SerialBufferWriteThread(self, endp_out, self._buf_out)
            self._thrd_buf_out.start()

    def _stop_threads_buffer_rw(self):
        if self._thrd_buf_in:
            self._thrd_buf_in.stop()
            self._thrd_buf_in.join()
            self._thrd_buf_in = None
        if self._thrd_buf_out:
            self._thrd_buf_out.stop()
            self._thrd_buf_out.join()
            self._thrd_buf_out = None

    # --------------------------------

    def __enter__(self):
        if not self._is_open:
            self.open()
        return self

    def __exit__(self, *args, **kwargs):
        self.close()

    # --------------------------------

    def prepare_usb_cp210x(self, intf=0, baudRate=DEFAULT_BAUDRATE):
        backend = self._device.backend
        dev = self._device._ctx.handle

        # https://github.com/felHR85/UsbSerial/blob/master/usbserial/src/main/java/com/felhr/usbserial/CP2102SerialDevice.java

        backend.claim_interface(dev, intf)
        self._intf = intf

        # set defaults
        ret = self.send_ctrl_cmd(CP210x_IFC_ENABLE, CP210x_UART_ENABLE, None)
        if ret < 0:
            return False

        ret = self.set_baudRate(baudRate)
        if ret < 0:
            return False

        ret = self.send_ctrl_cmd(CP210x_SET_LINE_CTL, CP210x_LINE_CTL_DEFAULT, None)
        if ret < 0:
            return False

        ret = self.set_flowControl(FLOW_CONTROL_OFF)
        if ret < 0:
            return False

        ret = self.send_ctrl_cmd(CP210x_SET_MHS, CP210x_MHS_DEFAULT, None)
        return ret >= 0

    def open(self, _async=True):
        if self._is_open:
            return

        assert self.prepare_usb_cp210x(
            intf=self._intf, baudRate=self._baudRate
        ), "Error setting up defaults"
        self._is_open = True

        if _async:
            self._is_async = _async
            self._start_threads_buffer_rw()

    def read_dump_forever(self):
        device = self._device
        endp_in = CP210xSerial.get_endpoints(device)[0]

        while True:
            try:
                data = device.read(endp_in.bEndpointAddress, endp_in.wMaxPacketSize)
                text = "".join(chr(v) for v in data)
                print(text, end="", flush=True)
            except libusb1.USBError:
                pass
            except KeyboardInterrupt:
                break

    def close(self):
        if self._is_async:
            self._stop_threads_buffer_rw()
        self._stop_thread_flowControl()

        self.send_ctrl_cmd(CP210x_PURGE, CP210x_PURGE_ALL, None)
        self.send_ctrl_cmd(CP210x_IFC_ENABLE, CP210x_UART_DISABLE, None)

        backend = self._device.backend
        dev = self._device._ctx.handle
        backend.claim_interface(dev, self._intf)

        self._is_open = False


# ----------------------------------------------------------------------------


def main(fd, debug=True):
    if hasattr(usb.core, "device_from_fd"):
        device = usb.core.device_from_fd(fd)
    else:
        LOGGER.warning("Patch: device_from_fd")
        device = device_from_fd(fd)

    if debug:
        shell_usbdevice(fd, device)

        print("\n", "#" * 40, "\n")
        print(device)

    assert device.idVendor == 0x10C4 and device.idProduct == 0xEA60

    ser = CP210xSerial(device, baudRate=115200)
    try:
        # mainly for baud rate
        ser.open(_async=False)
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
    logging.getLogger("{}.RXTX".format(__name__)).setLevel(logging.INFO)

    # grab fd number from args
    #   (from termux wrapper)
    import sys

    LOGGER.debug("args: %s", sys.argv)

    fd = int(sys.argv[1])
    main(fd)
