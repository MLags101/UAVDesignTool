# AI design assistant: quick start

This guide connects an AI assistant (Claude Code, Claude Desktop or any MCP
client) to the UAV Design Tool, so it sizes and optimizes aircraft with the
tool's engineering models instead of guessing numbers.

**You do not need to start the desktop app.** The AI client starts the design
server in the background whenever it needs it.

---

## 1. One-time setup

Open a terminal in the `UAVDesignTool` folder.

1. Install the dependencies:

   ```bash
   python -m pip install -r requirements.txt
   python -m pip install mcp pymoo
   ```

   `pymoo` is only needed for multi-objective (Pareto) optimization.

2. Check that it works:

   ```bash
   python -m unittest tests.test_mcp_service
   ```

   You should see `OK` at the end.

## 2. Connect your AI client

Do the steps for the client you use.

### Claude Code (VS Code extension or terminal)

1. Open the `UAVDesignTool` folder in VS Code (or run `claude` in it).
2. When Claude Code asks whether to trust the project's MCP server
   **uav-design**, choose **Approve / Use this server**.
3. Type `/mcp` and confirm **uav-design** shows as **connected**.
   If it shows as disabled, select it and choose **Enable**.

To use it from any folder, not just this one, run this once:

```bash
claude mcp add --scope user uav-design -- python "C:/Users/Micha/Desktop/Other/Designs/UAVDesignTool/uav_mcp"
```

### Claude Desktop

1. Open **Settings → Developer → Edit Config**. This opens
   `%APPDATA%\Claude\claude_desktop_config.json`.
2. Add the server, then save:

   ```json
   {
     "mcpServers": {
       "uav-design": {
         "command": "python",
         "args": ["C:/Users/Micha/Desktop/Other/Designs/UAVDesignTool/uav_mcp"]
       }
     }
   }
   ```

3. Quit Claude Desktop completely (including from the system tray) and reopen it.
4. In a new chat, open the tools/connectors menu (the slider icon under the
   message box) and switch **uav-design** **on**.

### Other MCP clients (Cursor, Windsurf, etc.)

Add a stdio server with:

- **command:** `python`
- **args:** `C:/Users/Micha/Desktop/Other/Designs/UAVDesignTool/uav_mcp`

If you move the project folder, update the path in your client's config.

## 3. Give the AI a design brief

The easiest start is the built-in guided workflow:

- **Claude Code:** type `/mcp__uav-design__design_uav` and enter your mission.
- **Claude Desktop:** click **+** → **uav-design** → **design_uav**, then enter your mission.

Or just describe the job in plain language. The more of these you include, the
better the design:

| Include | Example |
| --- | --- |
| Payload | 1.2 kg camera gimbal |
| Endurance or range | 60 min, or 40 km round trip |
| Cruise speed | 18 m/s |
| Altitude | 120 m AGL, field at 1,500 m elevation |
| Takeoff and landing | Hand launch, belly landing / vertical takeoff |
| Size or mass limits | Under 2 m span, under 5 kg takeoff |
| Configuration (optional) | Fixed wing, quad, VTOL, or "recommend one" |
| Known hardware (optional) | 6S 5000 mAh pack, 2814 motor, 11x7 prop |

**Example prompts**

> Design a fixed-wing survey UAV: 1 kg payload, 90 min endurance, 18 m/s
> cruise, hand launched, under 2 m span. Use the uav-design tools for every
> number, then run sensitivity and uncertainty on the result.

> I have a 6S 5000 mAh battery and 4× 2814 880 kV motors with 12x4.5 props.
> Estimate hover endurance for a 2.5 kg quad and check the current budget.

> Run the constraint diagram for a 3 kg aircraft with 11 m/s stall and 22 m/s
> cruise, and show me the plot.

## 4. Review the results

Ask the AI to:

- **show margins and warnings:** any margin below 0 means a requirement is not met.
- **say what drives the design:** this uses sensitivity analysis.
- **test the assumptions:** for example, "what if drag is 20% higher or the
  battery 10% worse?" This uses uncertainty analysis.
- **check subsystems on the final design:** static margin, spar, V-n diagram,
  motor-prop match.

The optimizer is an **engineering preview**. Ask the AI to read the validation
status (`get_reference('validation')`) before treating results as final.

## 5. Open the AI's work in the desktop app (optional)

Tell the AI the path of your project folder, for example:

> Save this study and the optimization run to `C:/Users/Micha/Documents/MyUAV`.

Then start the desktop app (`python UAVDesignTool.py`), open that project and go
to **Optimization**. The study and run are listed there.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| uav-design shows **failed** in `/mcp` or Desktop | Run `python -c "import mcp"`. If it errors, run `python -m pip install mcp`. Make sure the same `python` is on your PATH. |
| Tools don't appear in Claude Desktop | Fully quit Claude Desktop from the tray and reopen it, and check that the JSON config is valid. |
| "No module named pymoo" | `python -m pip install pymoo` (only needed for 2–3 objectives). |
| A calculator says an input "is required" | Normal: the AI should call `describe_calculator` and supply it. |
| Optimization takes too long | Ask the AI to lower `max_evaluations` (each evaluation takes about 25 ms). |

**Optional limits** (set as environment variables in the client config):
`UAV_MCP_MAX_EVALUATIONS` (default 5000), `UAV_MCP_MAX_SAMPLES` (default 2000),
and `UAV_MCP_TOOL_DIRS` to add your own calculator folders.
