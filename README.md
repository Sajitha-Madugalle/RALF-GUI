# RALF + GUI

Portable SKY130A analog layout workbench: patched IIC-RALF source plus a Qt GUI
for netlist â†’ placement â†’ routing â†’ GDS, DRC and LVS.

## Install and play

Run these commands **inside the Linux desktop terminal of an IIC-OSIC-TOOLS
Docker container**, not Windows PowerShell. The container must have internet
access, Python 3.10â€“3.12 with venv/pip, Magic, Netgen and the SKY130A PDK.
Use the container's browser/VNC desktop so Qt and Magic can display windows.

```bash
git clone https://github.com/Sajitha-Madugalle/RALF-GUI.git
cd RALF-GUI
bash setup.sh
bash launch.sh
```

Setup creates a local `.venv`, installs Python dependencies (CPU PyTorch),
and asks where these files live:

| Prompt | Select |
| --- | --- |
| repo | Press Enter for the bundled `ralf` source |
| pdk | Your SKY130A folder containing `libs.tech/magic/sky130A.magicrc` and `libs.tech/netgen/sky130A_setup.tcl` |
| magic | The Magic executable, normally detected automatically |
| netgen | The Netgen executable, normally detected automatically |

Paths are saved only on your computer in ignored `paths.json`. No PDK or
proprietary files are bundled. A different container's default PDK may be IHP;
this workbench specifically requires SKY130A.

To repair paths later:

```bash
.venv/bin/python configure.py
.venv/bin/python doctor.py
```

For the exact tested Python 3.12 dependency set, install with
`PIP_CONSTRAINT="$PWD/requirements-tested.txt" bash setup.sh`.
The default version ranges also allow compatible packages on older Python.

For unattended setup, provide your own actual PDK path:

```bash
bash setup.sh --non-interactive --pdk /your/pdks/sky130A
```

The bundled RALF path stays relative to the clone. After moving a clone,
rerun setup to recreate the virtual environment at its new location. Use
`RALF_PYTHON=/path/to/python3 bash setup.sh` to select an interpreter.

## Use

1. Browse to a self-contained SKY130 SPICE netlist. Examples are in
   `ralf/Circuits/Examples`.
2. Check the inferred top cell and port names.
3. Choose an output parent and a new run folder name.
4. Generate layout and GDS; inspect DRC results before continuing.
5. Open the layout in Magic, or use the DRC/LVS sections to verify it.

Output folders contain independent working snapshots and reports. Existing
run folders are refused. Full usage and flow limitations are described in
[the workbench guide](gui/WORKBENCH.md). Use this README's launcher and configuration instructions.

Routing can fail for some circuits, and a completed export does not imply
DRC/LVS success. The GUI reports actual results and preserves partial output.

## Troubleshooting

- Missing display: launch from the container's VNC desktop terminal; preserve
  its DISPLAY setting. Do not use offscreen Qt for interactive work.
- Missing PDK/tool: rerun `configure.py` and select the files in this container.
- Installation failure: check internet access and available disk space. No
  Windows virtual environment can be reused inside Linux.
- `doctor.py` checks imports, headless Magic with SKY130A, Netgen and Qt window
  construction. It does not certify every input circuit.

## Verified

Tested on 3 November 2026 in the installed Ubuntu IIC-OSIC-TOOLS container,
using a new isolated Python 3.12 environment at a different location:

- Dependency installation and GUI construction passed.
- CCLatch placement, routing and GDS export passed in a path containing spaces.
- Routed layout: DRC zero; LVS circuits match uniquely.
- Exported GDS readback: DRC zero.
- Temporary example outputs were automatically deleted.

To repeat the example check after setup:

```bash
env -u PYTHONPATH -u PYTHONHOME .venv/bin/python verify.py
```

The existing container was used; this does not claim testing on every
IIC-OSIC-TOOLS image version or every circuit.

## Source and license

RALF originates from [iic-jku/IIC-RALF](https://github.com/iic-jku/IIC-RALF).
Its Apache 2.0 license and citation are retained in `ralf/LICENSE.txt` and
`ralf/CITATION.cff`. This distribution includes local routing/export fixes and
the layout workbench; it is not an official upstream release.
