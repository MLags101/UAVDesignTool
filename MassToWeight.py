"""
Payload Mass to Weight Converter
"""

TOOL_METADATA = {
    "name": "Mass to Weight Converter",
    "description": "Converts a payload mass (kg) into weight Force (N) assuming standard gravity.",
    "inputs": [
        {"key": "mass", "label": "Payload Mass", "unit": "kg"},
        {"key": "gravity", "label": "Gravity (Optional)", "unit": "m/s^2"}
    ]
}

def run(inputs):
    try:
        # Get mass
        mass_str = inputs.get("mass", "")
        if not mass_str:
            return "Error: Payload Mass is required."
        mass = float(mass_str)

        # Get gravity (default to 9.81 if empty)
        grav_str = inputs.get("gravity", "")
        g = float(grav_str) if grav_str.strip() else 9.81

        # Calculate Weight: W = m * g
        weight = mass * g

        # Format Output
        output = "=== Weight Calculation ===\n\n"
        output += f"Mass (m): {mass} kg\n"
        output += f"Gravity (g): {g} m/s^2\n"
        output += "-" * 20 + "\n"
        output += f"Weight (W): {weight:.2f} N\n"
        
        return output

    except ValueError:
        return "Error: Please enter valid numeric values."
    except Exception as e:
        return f"System Error: {str(e)}"