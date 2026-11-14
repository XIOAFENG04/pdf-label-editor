"""Single-instance support: forward files to the window that is already open.

A named pipe is created by the first instance. Later launches connect, send
their file paths and exit, so a double-clicked PDF lands as a new tab instead
of a second application window. Nothing happens when the feature is disabled in
the settings, or when no listener is available.
"""
import os
import threading
from multiprocessing.connection import Client, Listener

AUTHKEY = b'PDFLabelEditor-pipe'
PIPE = r'\\.\pipe\PDFLabelEditor-%s' % (os.environ.get('USERNAME') or 'user')


def forward(paths, timeout=1.5):
    """Send paths to a running instance; False when nobody is listening."""
    try:
        client = Client(PIPE, family='AF_PIPE', authkey=AUTHKEY)
    except (OSError, EOFError):
        return False
    try:
        client.send({'paths': list(paths)})
        return True
    except (OSError, EOFError):
        return False
    finally:
        client.close()


def listen(messages):
    """Background thread: put every received path list on the queue."""
    def serve():
        try:
            listener = Listener(PIPE, family='AF_PIPE', authkey=AUTHKEY)
        except (OSError, EOFError):
            return
        while True:
            try:
                connection = listener.accept()
            except (OSError, EOFError):
                return
            try:
                message = connection.recv()
            except (OSError, EOFError):
                continue
            finally:
                connection.close()
            paths = message.get('paths') if isinstance(message, dict) else None
            if paths:
                messages.put(paths)

    threading.Thread(target=serve, daemon=True).start()
