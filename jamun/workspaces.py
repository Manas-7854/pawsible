import ctypes

from PySide6.QtWidgets import QApplication


class _ClientMessage(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [("client", _ClientMessage), ("padding", ctypes.c_long * 24)]


def exclude_from_focus(window):
    if QApplication.platformName() != "xcb" or not window.isVisible():
        return False
    x11 = ctypes.CDLL("libX11.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XGetWMProtocols.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_int)]
    x11.XGetWMProtocols.restype = ctypes.c_int
    x11.XSetWMProtocols.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.c_int]
    x11.XSetWMProtocols.restype = ctypes.c_int
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        return False
    try:
        protocols = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_int()
        if not x11.XGetWMProtocols(display, int(window.winId()), ctypes.byref(protocols), ctypes.byref(count)):
            return False
        try:
            take_focus = x11.XInternAtom(display, b"WM_TAKE_FOCUS", 0)
            retained = [protocols[index] for index in range(count.value) if protocols[index] != take_focus]
        finally:
            x11.XFree(protocols)
        array = (ctypes.c_ulong * len(retained))(*retained)
        changed = x11.XSetWMProtocols(display, int(window.winId()), array, len(retained))
        x11.XFlush(display)
        return bool(changed)
    finally:
        x11.XCloseDisplay(display)


def show_on_all_workspaces(window):
    if QApplication.platformName() != "xcb" or not window.isVisible():
        return False
    x11 = ctypes.CDLL("libX11.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.POINTER(_XEvent)]
    x11.XSendEvent.restype = ctypes.c_int
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        return False
    try:
        event = _XEvent()
        event.client.type = 33
        event.client.window = int(window.winId())
        event.client.message_type = x11.XInternAtom(display, b"_NET_WM_DESKTOP", 0)
        event.client.format = 32
        event.client.data[0] = 0xFFFFFFFF
        event.client.data[1] = 1
        mask = (1 << 19) | (1 << 20)
        sent = x11.XSendEvent(display, x11.XDefaultRootWindow(display), 0, mask, ctypes.byref(event))
        x11.XFlush(display)
        return bool(sent)
    finally:
        x11.XCloseDisplay(display)
