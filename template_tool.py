"""
Template Tool for UAV Design Organizer

Copy this file, fill in TOOL_METADATA and run(), then import it with
File > Import Tool Script (Ctrl+T).

The module stays a plain Python module -- it can be imported and called
directly from a script or notebook as well as from the GUI.
"""

# TOOL_METADATA is required. The GUI reads it to build the input form.
TOOL_METADATA = {
    "name": "Template Tool Name",
    "description": "A short description of what this tool calculates.",
    "inputs": [
        # "key":     the dict key passed to run()            (required)
        # "label":   text shown in the GUI                    (defaults to key)
        # "unit":    shown next to the label, used as a hint  (optional)
        # "default": value prefilled in the field             (optional)
        # "help":    tooltip text                             (optional)
        {"key": "input_1", "label": "First Input Parameter", "unit": "m/s"},
        {"key": "input_2", "label": "Second Input Parameter", "unit": "kg",
         "default": "1.0", "help": "Dry mass, excluding payload."},
    ],
}


def run(inputs):
    """Execute the tool.

    Args:
        inputs (dict): keys from TOOL_METADATA["inputs"]. Every value arrives
            as a string (possibly empty), so convert what you need.

    Returns:
        str: the text shown in the Output pane.
    """
    try:
        # 1. Retrieve and convert inputs. `or 0` keeps empty fields from
        #    raising before you can give a useful message.
        val1 = float(inputs.get("input_1") or 0)
        val2 = float(inputs.get("input_2") or 0)

        # 2. Perform the calculation.
        result = val1 * val2

        # 3. Format the output.
        return (
            "--- Calculation Results ---\n"
            f"Input 1: {val1}\n"
            f"Input 2: {val2}\n"
            f"Result:  {result:.4f}"
        )

    except ValueError:
        return "Error: please enter valid numeric values."
    except Exception as exc:
        return f"Error executing tool: {exc}"
