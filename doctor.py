import importlib
import os
from pathlib import Path
import subprocess
import sys
from runtime import ROOT, environment

config = environment()
for module in ('numpy','matplotlib','networkx','pandas','prettytable','pygame','rtree','sklearn','simanneal','torch','torch_geometric','tqdm','PySide6'):
    importlib.import_module(module)
sys.path.insert(0, str(ROOT/'gui'))
from flow import magic
import tempfile
with tempfile.TemporaryDirectory(prefix='ralf-doctor-') as folder:
    output = magic('puts "RALF_MAGIC_OK"\nquit -noprompt\n', folder, config['pdk'], 'probe')
    assert 'RALF_MAGIC_OK' in output
result = subprocess.run([config['netgen'], '-batch'], input='quit\n', text=True, capture_output=True)
if result.returncode: raise RuntimeError(result.stdout+result.stderr)
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from app import Workbench
app = QApplication([])
window = Workbench()
window.close()
print('PASS: Python dependencies, Magic + SKY130A, Netgen and GUI construction')
