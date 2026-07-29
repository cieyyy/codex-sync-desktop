"""Keep tkinter discoverable when a restricted build host cannot initialize Tcl.

The release command supplies verified Tcl/Tk runtime files explicitly. On a
normal host, PyInstaller's built-in hook remains preferable.
"""


def pre_find_module_path(_hook_api):
    return
