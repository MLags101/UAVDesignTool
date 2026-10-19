"""Model Context Protocol server exposing the UAV design calculators and solver.

:mod:`uav_mcp.service` holds the protocol-independent logic and only needs the
same dependencies as ``uavlib``. :mod:`uav_mcp.server` wires it to MCP and is
the only module that imports the ``mcp`` package.
"""
