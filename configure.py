"""Ask for local paths; no developer-specific paths are shipped."""
import argparse
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pdk', help='SKY130A directory containing libs.tech')
    parser.add_argument('--repo', help='Optional alternate patched RALF source')
    parser.add_argument('--magic', help='Magic executable')
    parser.add_argument('--netgen', help='Netgen executable')
    parser.add_argument('--non-interactive', action='store_true')
    args = parser.parse_args()
    config = {}
    candidates = [os.environ.get('RALF_PDK'), os.environ.get('PDKPATH'),
                  str(Path(os.environ.get('PDK_ROOT', '/foss/pdks'))/'sky130A')]
    default_pdk = next((p for p in candidates if p and (Path(p)/'libs.tech/magic/sky130A.magicrc').is_file()), '')
    defaults = {'repo': str(ROOT/'ralf'), 'pdk': default_pdk,
                'magic': shutil.which('magic') or '', 'netgen': shutil.which('netgen') or ''}
    for key, default in defaults.items():
        value = getattr(args, key)
        if value is None:
            value = default if args.non_interactive else input(f'{key} path [{default}]: ').strip() or default
        path = Path(value).expanduser().resolve() if value else None
        required = {'repo':'Routing_v2/MagicCleanup.py', 'pdk':'libs.tech/magic/sky130A.magicrc'}
        if not path or not (path/required[key] if key in required else path).is_file():
            parser.error(f'Invalid {key} path: {value!r}. Supply the required local file/directory.')
        if key == 'pdk' and not (path/'libs.tech/netgen/sky130A_setup.tcl').is_file():
            parser.error('SKY130A Netgen setup file is missing from this PDK.')
        config[key] = str(path)
    # Bundled source follows the clone when moved; external paths remain explicit.
    if Path(config['repo']) == ROOT/'ralf': config['repo'] = 'ralf'
    (ROOT/'paths.json').write_text(json.dumps(config, indent=2)+'\n')
    print('Saved local paths.json. Re-run configure.py whenever local paths change.')

if __name__ == '__main__': main()
