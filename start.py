import json
import os
import subprocess
import sys
import tempfile
from runtime import ROOT, environment

config = environment()
# Resolve relative paths without rewriting the portable saved configuration.
with tempfile.TemporaryDirectory(prefix='ralf-settings-') as folder:
    path = os.path.join(folder, 'paths.json')
    with open(path, 'w') as stream: json.dump(config, stream)
    os.environ['RALF_CONFIG'] = path
    result = subprocess.run([sys.executable, str(ROOT/'gui/app.py'), *sys.argv[1:]])
    # Preserve changes made through Tool settings.
    with open(path) as stream: updated = json.load(stream)
    if updated != config:
        if updated['repo'] == str(ROOT/'ralf'): updated['repo'] = 'ralf'
        (ROOT/'paths.json').write_text(json.dumps(updated, indent=2)+'\n')
    sys.exit(result.returncode)
