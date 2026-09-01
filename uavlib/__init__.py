"""Shared physics and formatting library for UAV Design Organizer tools.

Every bundled tool imports from here rather than carrying its own copy of the
standard atmosphere, drag polar or propeller model. A copy of this package is
placed in each project's ``Tools/`` folder so the tools remain runnable outside
the application.

All functions work in SI units. Conversion happens at the edges, in
:mod:`uavlib.units`.
"""

__version__ = "1.0.0"

G = 9.80665  # standard gravity, m/s^2
