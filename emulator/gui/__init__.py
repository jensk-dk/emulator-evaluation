"""The launcher's windows: the emulator's display window with its toolbar,
the on-screen remote control, and the settings window.

They are built with Qt 6 through PySide6, the one part of the launcher that
is not Python's standard library; the setup scripts install it. Each window
is a program of its own (python -m emulator.gui.viewer, ...settings) that the
launcher starts with the Python that has PySide6 (emulator/window.py), so the
launcher itself runs without it.
"""
