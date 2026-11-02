"""RALF workbench backend. Each job runs in a separate process and directory."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
import uuid


HERE = Path(__file__).resolve().parent


def tcl(value):
    """One literal Tcl word, including paths containing spaces/metacharacters."""
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('[', '\\[').replace(']', '\\]').replace('\n', '\\n') + '"'


def emit(message):
    print(message, flush=True)


def placement_decision(result):
    """Pause only on an explicit DRC result; never reinterpret tool failures."""
    emit('WORKBENCH_DECISION '+json.dumps(result))
    answer=sys.stdin.readline().strip()
    if answer != 'continue':
        raise RuntimeError('Stopped at placement DRC by user decision. Placement and reports were retained.')
    emit('WARNING — Continuing with placement DRC violations at user request. Final DRC/LVS still required.')


def run(args, cwd, logfile, timeout=1200):
    emit('Running: ' + ' '.join(map(str, args)))
    # Parent worker is its own process group; GUI cancellation kills descendants.
    with open(logfile, 'w') as log:
        p = subprocess.Popen(list(map(str, args)), cwd=cwd, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors='replace')
        import threading
        timer = threading.Timer(timeout, p.kill)
        timer.start()
        text = []
        try:
            for line in p.stdout:
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
                text.append(line)
            code = p.wait()
        finally:
            timer.cancel()
        if code:
            raise RuntimeError(f'{Path(args[0]).name} exited with code {code}. See {logfile}')
    return ''.join(text)


def magic(script, folder, pdk, name):
    folder = Path(folder)
    path = folder / (name + '.tcl')
    path.write_text(script)
    output = run([os.environ.get('RALF_MAGIC','magic'), '-dnull', '-noconsole', '-rcfile',
                  Path(pdk)/'libs.tech/magic/sky130A.magicrc', path], folder, folder/(name+'.log'))
    fatal = ['No cell being edited', 'Could not write file', 'invalid command name',
             'The current cell is not editable', "Couldn't find file", 'error in script',
             'Error parsing', 'Unknown layer', "couldn't be read", 'could not be expanded',
             'Failure to read in entire subtree', 'nothing here to extract']
    if any(x.lower() in output.lower() for x in fatal):
        raise RuntimeError(f'Magic reported an error; inspect {folder/(name+".log")}')
    return output


def normalize_netlist(path, top='', ports=''):
    """Accept RALF/xschem flat exports or a selected top .subckt wrapper.

    Include files are explicitly rejected instead of silently losing dependencies.
    Nested subcircuits are kept; only the selected wrapper is removed for RALF.
    """
    text = Path(path).read_text()
    if re.search(r'^\s*\.(include|inc|lib)\b', text, re.I | re.M):
        raise ValueError('Use a self-contained device netlist: .include/.lib files are not supported yet.')
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith('+') and lines:
            lines[-1] += ' ' + line.lstrip()[1:].strip()
        else:
            lines.append(line)
    comment = next((re.match(r'^\s*\*+\s*\.subckt\s+(\S+)\s+(.+)', x, re.I) for x in lines
                    if re.match(r'^\s*\*+\s*\.subckt\s+', x, re.I)), None)
    blocks, flat, current = {}, [], None
    for line in lines:
        m = re.match(r'^\s*\.subckt\s+(\S+)\s*(.*)', line, re.I)
        if m:
            if current:
                raise ValueError('Nested .subckt definitions are not supported.')
            current = [m[1], m[2].split(), []]
        elif re.match(r'^\s*\.ends\b', line, re.I):
            if not current:
                raise ValueError('Unmatched .ends in netlist.')
            blocks[current[0]] = current
            current = None
        elif not re.match(r'^\s*\.end\s*$', line, re.I):
            (current[2] if current else flat).append(line)
    if current:
        raise ValueError('Missing .ends in netlist.')
    inferred = comment[1] if comment else (next(iter(blocks)) if blocks else Path(path).stem)
    top = top.strip() or inferred
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', top):
        raise ValueError('Top cell must start with a letter/underscore and use only letters, digits and underscores.')
    if top in blocks:
        _, declared, body = blocks.pop(top)
        outside = [x for x in flat if x.strip() and not x.lstrip().startswith('*')]
        if outside:
            raise ValueError('Top-level devices/directives outside the selected .subckt are ambiguous. Use a device-only netlist.')
    else:
        body = flat
        declared = comment[2].split() if comment else []
    declared = ports.split() if ports.strip() else declared
    if not declared or len(set(declared)) != len(declared):
        raise ValueError('Specify the unique external ports in order (or include a .subckt header).')
    if not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', n) for n in declared):
        raise ValueError('Port names must use letters, digits and underscores, starting with a letter/underscore.')
    devices = [x for x in body if x.strip() and not x.lstrip().startswith('*')]
    if not devices:
        raise ValueError('No devices found for the selected top cell.')
    if any(x.lstrip().startswith('.') for x in devices):
        raise ValueError('Simulation/control directives are not supported. Export a device-only netlist.')
    defs = '\n'.join('\n'.join(['.subckt '+name+' '+' '.join(b[1]), *b[2], '.ends '+name]) for name,b in blocks.items())
    flat_text = '\n'.join(body) + '\n' + defs + '\n.end\n'
    ref = '.subckt '+top+' '+' '.join(declared)+'\n'+'\n'.join(body)+'\n.ends '+top+'\n'+defs+'\n.end\n'
    return top, declared, flat_text, ref


def resolve_paths(layout):
    """Resolve hierarchy from a MAG file and neighbouring standard run folders."""
    layout = Path(layout).resolve()
    search = [layout.parent, layout.parent.parent/'03_Devices', layout.parent.parent/'02_Placement']
    # Include explicit subcell directories stored by Magic.
    for line in layout.read_text().splitlines():
        fields = line.split()
        if fields and fields[0] == 'use' and len(fields) > 3:
            p = Path(fields[3])
            search.append(p if p.is_absolute() else layout.parent/p)
    return list(dict.fromkeys(p.resolve() for p in search if p.is_dir()))


def load_script(layout):
    return ''.join('path search '+tcl('+'+str(p))+'\n' for p in resolve_paths(layout)) + 'load '+tcl(Path(layout).resolve())+'\nselect top cell\nexpand\n'


AREA_SCRIPT = '''select top cell
puts "WORKBENCH_AREA [select bbox] [cif scale out]"
'''


def parse_area(output):
    match = re.search(r'^WORKBENCH_AREA (.+)$', output, re.M)
    if not match:
        raise RuntimeError('Magic did not return layout dimensions.')
    x1, y1, x2, y2, scale = map(float, match[1].split())
    width, height = (x2-x1)*scale, (y2-y1)*scale
    if width <= 0 or height <= 0 or scale <= 0:
        raise ValueError('Layout has no measurable area.')
    return {'width_um':width, 'height_um':height, 'area_um2':width*height,
            'definition':'Top-cell bounding rectangle including hierarchy'}


def measure_area(layout, folder, pdk):
    if Path(layout).suffix.lower() != '.mag':
        raise ValueError('Select a Magic (.mag) layout to measure area.')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    output = magic(load_script(layout)+AREA_SCRIPT+'quit -noprompt\n', folder, pdk, 'area')
    if re.search(r"(cannot|could not|couldn't|unable to).*?(read|find|load)", output, re.I):
        raise RuntimeError('A layout dependency is missing; area is invalid.')
    result = {'layout':str(Path(layout).resolve()), 'area':parse_area(output)}
    (folder/'area.json').write_text(json.dumps(result, indent=2))
    return result


def drc(layout, folder, pdk):
    data = Path(layout).read_text()
    layers = re.findall(r'^<< (.+) >>$',data,re.M)
    if not re.search(r'^use ',data,re.M) and not any(x not in ('checkpaint','error_s','labels','properties','end') for x in layers):
        raise ValueError('Layout is empty. An empty cell is not a valid DRC pass.')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    script = load_script(layout) + AREA_SCRIPT + '''drc style drc(full)
drc check
drc catchup
select top cell
box values {*}[select bbox]
puts "WORKBENCH_DRC_COUNT [drc list count total]"
foreach {reason boxes} [drc listall why] {
    foreach bounds $boxes {puts "WORKBENCH_DRC_ERROR\\t$reason\\t$bounds"}
}
puts "WORKBENCH_DRC_DONE"
quit -noprompt
'''
    output = magic(script, folder, pdk, 'drc')
    match = re.search(r'^WORKBENCH_DRC_COUNT (\d+)\s*$', output, re.M)
    if not match or 'WORKBENCH_DRC_DONE' not in output:
        raise RuntimeError('DRC did not complete. See the Magic log.')
    if re.search(r"(cannot|could not|couldn't|unable to).*?(read|find|load)", output, re.I):
        raise RuntimeError('A layout dependency could not be loaded. DRC result is invalid.')
    errors = []
    for reason, coords in re.findall(r'^WORKBENCH_DRC_ERROR\t([^\n\t]+)\t([^\n]+)', output, re.M):
        box = [float(x) for x in coords.split()]
        if len(box) == 4:
            errors.append({'rule':reason,'box':box})
    result = {'count':int(match[1]),'errors':errors,'layout':str(Path(layout).resolve()),'report':str(folder/'drc.log')}
    result['area'] = parse_area(output)
    (folder/'drc.json').write_text(json.dumps(result, indent=2))
    return result


def check_tools(cfg):
    for tool in ('magic', 'netgen'):
        if not shutil.which(os.environ.get('RALF_'+tool.upper(),tool)):
            raise ValueError(f'{tool} is not on PATH. Start the GUI with launch.sh inside IIC-OSIC-TOOLS.')
    pdk = Path(cfg['pdk']).resolve()
    for f in ('libs.tech/magic/sky130A.magicrc', 'libs.tech/netgen/sky130A_setup.tcl'):
        if not (pdk/f).is_file():
            raise ValueError(f'Missing SKY130A technology file: {pdk/f}')


def lvs(cfg):
    layout = Path(cfg['layout']).resolve()
    folder = Path(cfg['report_dir']).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    gate = drc(layout, folder/'pre_lvs_drc', cfg['pdk'])
    emit('WORKBENCH_DRC_RESULT '+json.dumps(gate))
    if gate['count'] and not cfg.get('allow_dirty_lvs',False):
        raise ValueError(f"LVS requires a DRC-clean layout; {gate['count']} violations remain. See {gate['report']}")
    if gate['count']:
        emit('WARNING — Diagnostic LVS on a layout with DRC violations; an LVS match does not clear DRC.')
    top, ports, flat, reference = normalize_netlist(cfg['netlist'], cfg.get('top',''), cfg.get('ports',''))
    ref = folder/'reference.spice'
    ref.write_text(reference)
    script = load_script(layout) + '''extract path .
extract all
ext2spice lvs
ext2spice subcircuit top on
'''+'ext2spice -o extracted.spice '+tcl(layout.stem+'.ext')+'''
puts "WORKBENCH_EXTRACT_DONE"
quit -noprompt
'''
    output = magic(script, folder, cfg['pdk'], 'extract')
    extracted = folder/'extracted.spice'
    if 'WORKBENCH_EXTRACT_DONE' not in output or not extracted.is_file():
        raise RuntimeError('Extraction did not produce a netlist.')
    # Tcl-safe list syntax for Netgen's "file cell" operands.
    out = run([os.environ.get('RALF_NETGEN','netgen'),'-batch','lvs',tcl(extracted)+' '+tcl(layout.stem),
               tcl(ref)+' '+tcl(top),Path(cfg['pdk'])/'libs.tech/netgen/sky130A_setup.tcl',
               folder/'lvs_report.txt'], folder, folder/'netgen.log')
    report = (folder/'lvs_report.txt').read_text()
    passed = 'Final result: Circuits match uniquely.' in report and 'property errors' not in report.lower()
    return {'passed':passed,'report':str(folder/'lvs_report.txt'), 'reference':str(ref), 'extracted':str(extracted),'drc_count':gate['count']}


def layout_flow(cfg):
    source = Path(cfg['netlist']).resolve()
    repo = Path(cfg['repo']).resolve()
    destination = Path(cfg['output']).resolve()
    if destination.exists():
        raise ValueError('Output folder already exists. Choose a new run name to preserve previous results.')
    if not (repo/'Routing_v2/utils.py').is_file():
        raise ValueError('Select the IIC-RALF source folder in Tool settings.')
    top, ports, flat, reference = normalize_netlist(source,cfg.get('top',''),cfg.get('ports',''))
    destination.mkdir(parents=True)
    dirs = {name:destination/name for name in ('00_Work','01_Netlist','02_Placement','03_Devices','04_Routing','05_Verification','06_GDS')}
    for d in dirs.values():
        d.mkdir()
    (destination/'run_config.json').write_text(json.dumps(cfg,indent=2))
    shutil.copy2(source, dirs['01_Netlist']/source.name)
    net = dirs['01_Netlist']/'ralf_input.spice'
    net.write_text(flat)
    (dirs['01_Netlist']/'reference.spice').write_text(reference)
    work = dirs['00_Work']
    # Snapshot source, excluding potentially huge trained models and prior outputs.
    for item in repo.iterdir():
        if item.is_file() and item.suffix in ('.py','.json','.md','.txt'):
            shutil.copy2(item,work/item.name)
        elif item.is_dir() and item.name in ('Magic','PDK','SchematicCapture','Rules','Routing_v2',
                  'rectangle_packing_placement','rectangle_packing_solver','Environment','NetRules',
                  'Circuits','Network','lef_def_parser'):
            shutil.copytree(item,work/item.name,ignore=shutil.ignore_patterns('__pycache__','*.pkl','*.pt','*.pth',
                           '*.mag','*.ext','*.png','*.gds','*.data','*.index'))
    for d in ('Logs/Stats','Logs/Routing','Images','PlacementCircuits','RTreeObstacles'):
        (work/d).mkdir(parents=True,exist_ok=True)
    os.chdir(work)
    sys.path.insert(0,str(work))
    os.environ['PDKPATH'] = str(Path(cfg['pdk']).resolve())
    os.environ['MPLBACKEND'] = 'Agg'
    import random
    import numpy as np
    random.seed(int(cfg.get('seed',42)))
    np.random.seed(int(cfg.get('seed',42)))
    from SchematicCapture.utils import setup_circuit, include_primitives_hierarchical, get_top_down_topology
    from SchematicCapture.RString import include_RStrings_hierarchical
    from Magic.Magic import Magic
    import Magic.utils as mu
    from Magic.MagicDie import MagicDie
    from rectangle_packing_placement.utils import do_bottom_up_placement
    from Routing_v2.Obstacles import DieObstacles
    from Routing_v2.utils import route
    emit('STAGE 1/5 — Read netlist and generate devices')
    circuit = setup_circuit(str(net),top,[],net_rules_file=cfg.get('rules') or None)
    include_primitives_hierarchical(circuit)
    include_RStrings_hierarchical(circuit)
    for i, (_, c) in enumerate(sorted(get_top_down_topology(circuit),key=lambda x:x[0])):
        magic('\n'.join(Magic(c).gen_devices()),dirs['03_Devices'],cfg['pdk'],f'devices_{i}')
    mu.add_cells(circuit,str(dirs['03_Devices']))
    die = MagicDie(circuit=circuit,def_file=None)
    emit('STAGE 2/5 — Place devices')
    do_bottom_up_placement(die,n_placements=int(cfg.get('placements',300)),simanneal_steps=100,
                           fig_path=str(work/'Images'),show_stats=True)
    # Keep RALF's hierarchical placement logic, but capture each Magic invocation.
    original_place = mu.place_circuit
    def place(name, Circuit, path='Magic/Placement', debug=False, clean_path=True):
        original_place(name,Circuit,path=path,debug=True,clean_path=False)
        script = (Path(path)/'place_devs.tcl').read_text()
        # RALF emits bare directory names; quote the entire Tcl word for user paths.
        script = '\n'.join('path search '+tcl('+'+os.path.relpath(line[len('path search +'):],path))
                           if line.startswith('path search ') else line for line in script.splitlines())
        magic(script,path,cfg['pdk'],'place_'+name)
    mu.place_circuit = place
    mu.place_circuit_hierachical(top,circuit,path=str(dirs['02_Placement']),clean_path=False)
    import pickle
    (work/'PlacementCircuits'/f'{top}_placement.pkl').write_bytes(pickle.dumps(die))
    placement = dirs['02_Placement']/(top+'.mag')
    emit('WORKBENCH_ARTIFACT '+json.dumps({'layout':str(placement),'output':str(destination),'stage':'Placement'}))
    pcheck = drc(placement,dirs['05_Verification']/'placement_drc',cfg['pdk'])
    emit('WORKBENCH_DRC_RESULT '+json.dumps(pcheck))
    if pcheck['count']:
        placement_decision(pcheck)
    emit('STAGE 3/5 — Route connections')
    die_obstacles = DieObstacles(die)
    import io
    from contextlib import redirect_stdout
    class RoutingLog(io.StringIO):
        def write(self, text):
            sys.__stdout__.write(text)
            sys.__stdout__.flush()
            return super().write(text)
    routing_log = RoutingLog()
    with redirect_stdout(routing_log):
        route(circuit,top,plan_wires=True,planning_iterations=15,gcell_length=150,
              use_layers=['m1','m2','m3','m4'],destination_path=str(dirs['04_Routing']),
              show_stats=True,port_names=tuple(ports))
    if re.search(r'failed with error|Trying next route',routing_log.getvalue(),re.I):
        raise RuntimeError('RALF could not route every net. Partial routing retained; review the log.')
    routed = dirs['04_Routing']/(top+'_Routed.mag')
    shutil.copy2(placement,routed)
    routing = dirs['04_Routing']/(top+'_routing.tcl')
    script = load_script(routed)+'source '+tcl(routing)+'\nsave '+tcl(routed.name)+'\nputs "WORKBENCH_BUILD_DONE"\nquit -noprompt\n'
    output = magic(script,dirs['04_Routing'],cfg['pdk'],'build_routed')
    if 'WORKBENCH_BUILD_DONE' not in output:
        raise RuntimeError('Magic did not complete routing replay.')
    # Normalize subcell paths so the exported MAG opens independently of cwd.
    for magfile in list(dirs['02_Placement'].glob('*.mag'))+[routed]:
        rows = []
        for line in magfile.read_text().splitlines():
            f = line.split()
            if f and f[0]=='use':
                for search in (dirs['03_Devices'],dirs['02_Placement']):
                    if (search/(f[1]+'.mag')).exists():
                        line = ' '.join(f[:3])+' '+os.path.relpath(search,magfile.parent)
                        break
            rows.append(line)
        magfile.write_text('\n'.join(rows)+'\n')
    emit('STAGE 4/5 — Full routing DRC')
    emit('WORKBENCH_ARTIFACT '+json.dumps({'layout':str(routed),'output':str(destination),'stage':'Routing'}))
    result = drc(routed,dirs['05_Verification']/'routing_drc',cfg['pdk'])
    emit('WORKBENCH_DRC_RESULT '+json.dumps(result))
    emit('STAGE 5/5 — Export GDS')
    gds = dirs['06_GDS']/(top+'.gds')
    magic(load_script(routed)+'gds write '+tcl(gds.name)+'\nputs "WORKBENCH_GDS_DONE"\nquit -noprompt\n',
          dirs['06_GDS'],cfg['pdk'],'export_gds')
    if not gds.exists() or gds.stat().st_size < 10:
        raise RuntimeError('GDS output is missing or empty.')
    result.update({'output':str(destination),'gds':str(gds),'routing':str(routing),'netlist':str(source),
                   'top':top,'ports':' '.join(ports),'placement':str(placement),
                   'placement_drc_count':pcheck['count'],'continued_after_placement_drc':bool(pcheck['count'])})
    result['status'] = 'DRC clean; LVS not run' if result['count']==0 else 'Generated with DRC errors; review required'
    (destination/'manifest.json').write_text(json.dumps(result,indent=2))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('job')
    args=parser.parse_args()
    os.setsid()
    cfg=json.loads(Path(args.job).read_text())
    try:
        check_tools(cfg)
        if cfg['action']=='layout':
            result=layout_flow(cfg)
        elif cfg['action']=='area':
            result=measure_area(cfg['layout'],cfg['report_dir'],cfg['pdk'])
        elif cfg['action']=='drc':
            result=drc(cfg['layout'],cfg['report_dir'],cfg['pdk'])
        elif cfg['action']=='lvs':
            result=lvs(cfg)
        else:
            raise ValueError('Unknown action')
        Path(cfg['result_file']).write_text(json.dumps(result,indent=2))
        emit('DONE — '+cfg['action'])
    except BaseException as exc:
        emit('ERROR — '+str(exc))
        traceback.print_exc()
        sys.exit(1)


if __name__=='__main__':
    main()
