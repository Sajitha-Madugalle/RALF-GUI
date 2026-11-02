# RALF Layout Workbench

Native Qt 6 desktop GUI (PySide6) running inside the existing IIC-OSIC-TOOLS
container. Source: `gui` in this clone.

## Start

Inside the container:

```sh
bash launch.sh  # from the repository root
```

The window appears on the same Linux desktop shown in the localhost browser.
Run `bash setup.sh` at the repository root first. Setup asks for local paths;
Tool settings can update the RALF source and SKY130A PDK later.

## Layout generation

The window has three resizable columns: a narrow file tree, a wider middle
workflow column, and a persistent Messages / Errors column on the right.
The middle workflow stacks teal **Netlist â†’ GDS**, amber **DRC**, and purple
**LVS** sections. Use the top Layout / DRC / LVS jump buttons or scroll the
middle column; the log and file tree stay visible.

**Reset session** at the top restarts the GUI process and clears input paths,
netlist details, file lists, results and logs. Placement trials and seed return
to their defaults. Tool settings and the file-tree root are kept. Generated
files are never deleted. If a job is running, Reset asks before cancelling it
and waits for it to exit before restarting. Independent Magic windows are left
open to avoid losing unsaved edits. Reset releases this GUI process's session
memory; it does not clear Docker's memory or close other applications.

1. Browse to a self-contained SKY130 netlist.
2. Check the inferred top-cell name and external ports. Both are editable.
3. Select the output parent folder and enter a **new** run folder name.
4. Click **Generate layout + GDS**. Progress and executable output appear below.
5. Click **Open in Magic** for an expanded, fitted view.

Each run creates:

```
<chosen output>/<chosen run name>/
  00_Work/          isolated RALF source snapshot, placement data and caches
  01_Netlist/       original netlist, normalized RALF input and LVS reference
  02_Placement/    placed Magic cells and placement scripts/logs
  03_Devices/      generated PDK device cells and scripts/logs
  04_Routing/      routing Tcl, routed Magic layout and replay log
  05_Verification/ full DRC reports, subsequent LVS reports and generation log
  06_GDS/          GDS and export script/log
  manifest.json    output paths, DRC result and matching LVS result when run
  run_config.json input paths and placement parameters
```

Existing run folders are refused. Each job uses its own RALF working copy;
the GUI does not modify the source repository or overwrite earlier examples.
The source repository must include the previously installed routing export
fixes (`MagicCleanup.py`, via-only labels and the `port_names` argument).

## DRC

If placement has DRC violations, generation pauses and displays **DRC found**.
Choose **Stop** to retain the placement/reports without routing, or **Continue
anyway** to route and export despite those placement violations. Closing the
prompt is treated as Stop. Continuing does not waive rules or label the result
clean: final routing DRC still runs, and LVS still requires a clean layout.

Select a `.mag` file and click **Run DRC**. The table lists rule descriptions
and error rectangles. Magic's region count and the number of rule rectangles
can differ. Select a row and click **Locate selected error in Magic**, or
double-click it. A new Magic window opens with the error box and a local zoom.
Coordinates are converted using explicit Magic internal units.

Checks operate on the saved file on disk. Save your Magic edits before
rechecking. Empty layouts and missing subcell dependencies are rejected.
DRC uses the full installed SKY130A Magic rules. Errors are displayed, not
automatically waived. The GUI does not promise to repair every possible
RALF routing failure.

## LVS

**Run LVSâ€¦** opens a separate selection window for the reference netlist,
clean `.mag` layout, top cell, external ports and reports folder. A fresh
full DRC check gates extraction. Netgen compares devices, connectivity,
ports and the installed setup's device properties. A successful process
exit alone is not treated as a match; the final report must explicitly
state that circuits match uniquely without property errors.

Generated placement and routed files are published immediately, before DRC
passes or the run finishes. If the run stops or fails, existing partial layouts
stay selected and listed for inspection, DRC and LVS. Their availability does
not imply that they passed verification.

The DRC section has its own layout Browse field. The LVS section now has
visible Browse fields for both the reference netlist and layout; these also
populate the Run LVS dialog. You can check existing files without generating
a new layout first. In that dialog, **Run diagnostic LVS even if DRC violations
remain** optionally permits connectivity comparison on an unclean layout.
The default still requires zero DRC errors. Diagnostic results retain the
DRC error count; an LVS match never clears DRC violations.

Extraction files and netlists stay in the selected report folder. A fresh
timestamped subfolder is used for every DRC/LVS request. The reference is
normalized in a copy; the original schematic netlist is not edited.

## Files and messages

The left **FILES** tree has expandable folder arrows and a root-folder browser.
Double-click a Magic/GDS file to view it, or a text file to open CAT. The tree
is read-only. The **VIEW DESIGN** bar also lets you browse independently for
`.mag`, `.gds` or `.gdsii` files and open them in Magic.

The terminal-style log uses white text on black, red for errors, amber for
warnings, green for passes and cyan for stages. **Expand â†—** opens a separate
larger scrollable live log. It follows new output while you are at the bottom;
scrolling up lets you inspect older output. This is an output console, not a
command-entry shell. The **ERRORS** block below it contains a numbered list of
DRC rule boxes and runtime failures from the current job. The error list resets
when a new job starts. Resize the panel divider or scroll the process panels
when working on a smaller desktop.

Each section lists its relevant input/output files. **CAT** opens an editable
text window; **Save As** writes a copy. Right-click a file list and choose
**Add text / Tcl filesâ€¦** to attach other
files for inspection only; selecting a Tcl file does not execute it.

The bottom panel includes custom validation messages, command lines, standard
output/error and Python exceptions. **Save logâ€¦** exports the visible log;
complete worker logs and job requests also remain in `gui/jobs`. **Cancel run**
stops that job's process group; partial outputs are retained for diagnosis.
**Load runâ€¦** loads a saved `manifest.json`.

## Supported input and limits

- This is a SKY130A RALF frontend, not a general multi-PDK synthesis tool.
- Supports RALF's device-only SPICE netlists, xschem commented top `.subckt`
  headers, or a selected real top `.subckt` wrapper. Internal subcircuits
  are preserved. External port names must be provided or inferred.
- `.include`, `.lib`, simulator control decks and ambiguous top definitions
  are rejected with instructions to supply a self-contained device netlist.
- RALF's existing supported devices/placement/routing limits still apply.
  A generated GDS can have DRC errors; the status explicitly reports them,
  and LVS is blocked until the selected layout is DRC clean.
- GUI generation uses simulated annealing, not trained RL placement.
- Full DRC/LVS here is not analog simulation, PEX, matching verification,
  antenna verification or foundry signoff.
- If you manually edit a layout after GDS export, the old GDS does not update
  automatically. Export your revised layout from Magic before using that GDS.
- Magic view windows are independent; closing the workbench leaves them open.

## Source and testing

- `gui/app.py`: user interface and asynchronous jobs.
- `gui/flow.py`: normalization, isolated flow, DRC, extraction and LVS.
- Root `launch.sh`: container desktop launcher.
- Root `doctor.py`: installation and GUI construction checks.
- Root `verify.py`: CCLatch generation, DRC, LVS and GDS readback.

Run `.venv/bin/python verify.py` with PYTHONPATH/PYTHONHOME unset inside the
container after setup. Temporary verification outputs are deleted automatically.
