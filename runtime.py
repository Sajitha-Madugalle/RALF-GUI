import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def environment():
    config = json.loads((ROOT/'paths.json').read_text())
    for key, value in config.items():
        path = Path(value)
        config[key] = str((ROOT/path).resolve() if not path.is_absolute() else path)
    os.environ['RALF_MAGIC'] = config['magic']
    os.environ['RALF_NETGEN'] = config['netgen']
    os.environ['PDKPATH'] = config['pdk']
    os.environ['QT_API'] = 'pyside6'
    os.environ['PATH'] = os.pathsep.join([str(Path(config[x]).parent) for x in ('magic','netgen')] + [os.environ['PATH']])
    return config
