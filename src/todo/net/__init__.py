""""__init__.py

A small TCP socket reader with a simple progress bar.
"""

from PyQt5 import QtWidgets, QtCore


def recv_all(sock, size):
    """Read data from a socket until it's finished."""
    pd = QtWidgets.QProgressDialog("Sync To-Do lists", "Abort sync", 0, size, None)
    pd.setMinimumWidth(375)
    pd.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
    pd.setValue(0)
    pd.forceShow()
    data = bytearray()
    while chunk := sock.recv(1):
        data.extend(chunk)
        pd.setValue(len(data))
    return data
