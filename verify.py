"""Run a real example in disposable output, then delete it even on failure."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from runtime import ROOT, environment

config = environment()
with tempfile.TemporaryDirectory(prefix='ralf-example-') as folder:
    folder = Path(folder)
    run = folder/'CCLatch run'
    job = dict(action='layout', repo=config['repo'], pdk=config['pdk'],
               netlist=str(Path(config['repo'])/'Circuits/Examples/CCLatch.spice'),
               output=str(run), top='CCLatch', ports='Vdd Vss in inn clk outn out',
               placements=2, seed=42, result_file=str(folder/'result.json'))
    path = folder/'job.json'
    path.write_text(json.dumps(job))
    subprocess.run([sys.executable, str(ROOT/'gui/flow.py'), str(path)], check=True, input='stop\n', text=True)
    sys.path.insert(0, str(ROOT/'gui'))
    from flow import drc, lvs, magic, tcl
    manifest = json.loads((run/'manifest.json').read_text())
    layouts = list((run/'04_Routing').glob('*_Routed.mag'))
    assert layouts
    assert drc(layouts[0], folder/'drc', config['pdk'])['count'] == 0
    comparison = lvs(dict(layout=str(layouts[0]), report_dir=str(folder/'lvs'),
                          pdk=config['pdk'], netlist=str(run/'01_Netlist/reference.spice'),
                          top='CCLatch', ports=job['ports']))
    assert comparison['passed'], comparison
    gds = next((run/'06_GDS').glob('*.gds'))
    readback = folder/'readback'
    readback.mkdir()
    output = magic('gds read '+tcl(gds)+'\nload CCLatch_Routed\nwriteall force\nputs "READBACK_OK"\nquit -noprompt\n', readback, config['pdk'], 'readback')
    assert 'READBACK_OK' in output
    assert drc(readback/'CCLatch_Routed.mag', folder/'gds-drc', config['pdk'])['count'] == 0
    print('PASS: netlist to GDS, routed DRC=0, LVS unique match, GDS readback DRC=0')
print('Temporary verification outputs deleted.')
