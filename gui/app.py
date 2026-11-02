"""Qt 6 desktop workbench for the container's RALF / Magic / Netgen tools."""
from pathlib import Path
import json
import hashlib
import os
import signal
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime

from PySide6.QtCore import Qt, QProcess, QSettings, QTimer
from PySide6.QtGui import QFont, QTextCursor, QTextCharFormat, QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QFileDialog, QPlainTextEdit,
    QSplitter, QTreeWidget, QTreeWidgetItem, QHeaderView, QDialog, QFormLayout,
    QSpinBox, QProgressBar, QMessageBox, QDialogButtonBox, QFileSystemModel, QTreeView, QScrollArea, QMenu, QCheckBox)
from flow import normalize_netlist, load_script, tcl

HERE = Path(__file__).resolve().parent
CONFIG = json.loads(Path(os.environ['RALF_CONFIG']).read_text()) if os.environ.get('RALF_CONFIG') else {}


class TextWindow(QDialog):
    def __init__(self, path, parent):
        super().__init__(parent)
        self.setWindowTitle('CAT — '+Path(path).name)
        self.resize(920,650)
        layout=QVBoxLayout(self)
        label=QLabel(str(path)); label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(label)
        self.editor=QPlainTextEdit()
        self.editor.setFont(QFont('DejaVu Sans Mono',10))
        self.editor.setPlainText(Path(path).read_text(errors='replace'))
        layout.addWidget(self.editor)
        row=QHBoxLayout()
        row.addWidget(QLabel('Edit a copy; the original stays unchanged.'))
        save=QPushButton('Save As…'); save.clicked.connect(self.save)
        row.addWidget(save); layout.addLayout(row)
    def save(self):
        path,_=QFileDialog.getSaveFileName(self,'Save edited text as')
        if path:
            try:
                Path(path).write_text(self.editor.toPlainText())
                self.parent().log('Saved text: '+path)
            except OSError as e:
                self.parent().error(str(e))


class PathField(QWidget):
    def __init__(self, parent, kind='file', filters='All files (*)', cat=True):
        super().__init__()
        self.owner=parent; self.kind=kind; self.filters=filters
        row=QHBoxLayout(self); row.setContentsMargins(0,0,0,0)
        self.edit=QLineEdit(); self.edit.setMinimumWidth(100)
        self.edit.setPlaceholderText('Browse or paste a container path')
        row.addWidget(self.edit,1)
        self.browse=QPushButton('Browse…'); self.browse.clicked.connect(self.choose)
        row.addWidget(self.browse)
        if cat:
            self.cat=QPushButton('CAT'); self.cat.setFixedWidth(48)
            self.cat.setToolTip('Open in the CAT text editor; save edits as a copy')
            self.cat.clicked.connect(lambda:self.owner.cat(self.text()))
            row.addWidget(self.cat)
    def text(self): return self.edit.text().strip()
    def setText(self,value): self.edit.setText(str(value))
    def choose(self):
        if self.kind=='directory':
            path=QFileDialog.getExistingDirectory(self,'Select folder',self.text())
        else:
            path,_=QFileDialog.getOpenFileName(self,'Select file',self.text(),self.filters)
        if path:
            self.setText(path)
            self.edit.editingFinished.emit()


class LVSDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.setWindowTitle('Run LVS — select the schematic and layout')
        self.resize(840,320)
        form=QFormLayout(self)
        self.net=PathField(owner,filters='SPICE netlists (*.spice *.sp *.cir);;All files (*)')
        self.net.setText(owner.lvs_net.text() or owner.net.text())
        self.layout_file=PathField(owner,filters='Magic layout (*.mag)')
        self.layout_file.setText(owner.lvs_layout.text() or owner.layout_file.text())
        self.top=QLineEdit(owner.top.text()); self.ports=QLineEdit(owner.ports.text())
        self.reports=PathField(owner,kind='directory',cat=False)
        self.reports.setText(owner.report_root())
        form.addRow('Reference netlist',self.net); form.addRow('Layout',self.layout_file)
        form.addRow('Top cell',self.top); form.addRow('External ports',self.ports)
        form.addRow('Reports folder',self.reports)
        hint=QLabel('Full DRC is checked again before extraction. Inputs are not modified.'); hint.setWordWrap(True)
        form.addRow(hint)
        self.allow_dirty=QCheckBox('Run diagnostic LVS even if DRC violations remain')
        form.addRow(self.allow_dirty)
        self.run=QPushButton('Run LVS'); self.run.setObjectName('primary')
        self.run.clicked.connect(self.submit); form.addRow(self.run)
        self.owner=owner
        self.net.edit.editingFinished.connect(self.infer)
        if self.net.text()!=owner.net.text(): self.infer()
    def infer(self):
        try:
            top,ports,_,_=normalize_netlist(self.net.text())
            self.top.setText(top); self.ports.setText(' '.join(ports))
        except Exception as e: self.owner.log('Netlist details: '+str(e))
    def submit(self):
        cfg={'action':'lvs','netlist':self.net.text(),'layout':self.layout_file.text(),
             'allow_dirty_lvs':self.allow_dirty.isChecked(),
             'top':self.top.text().strip(),'ports':self.ports.text().strip(),
             'report_dir':str(Path(self.reports.text())/('lvs_'+stamp()))}
        if self.owner.start(cfg):
            self.owner.lvs_net.setText(cfg['netlist']); self.owner.lvs_layout.setText(cfg['layout'])
            self.owner.lvs_files.populate([cfg['netlist'],cfg['layout']])
            self.accept()


def stamp(): return datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:4]


class FileList(QTreeWidget):
    def __init__(self,owner):
        super().__init__(); self.owner=owner
        self.setHeaderLabels(['Files / reports • right-click to add','View']); self.setRootIsDecorated(False)
        self.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.addAction('Add text / Tcl files…',self.add_text)
        self.header().setSectionResizeMode(0,QHeaderView.Stretch)
        self.header().setSectionResizeMode(1,QHeaderView.ResizeToContents)
        self.setMinimumHeight(85)
    def populate(self,paths):
        self.paths=list(dict.fromkeys(str(p) for p in paths if p))
        self.clear()
        for path in self.paths:
            item=QTreeWidgetItem([Path(path).name,'']); item.setToolTip(0,path)
            self.addTopLevelItem(item)
            if Path(path).suffix.lower() not in ('.gds','.png','.pkl'):
                btn=QPushButton('CAT'); btn.setFixedWidth(46)
                btn.clicked.connect(lambda checked=False,p=path:self.owner.cat(p))
                self.setItemWidget(item,1,btn)
    def add_text(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Add text files to this section','',
                    'Text / Tcl / netlists (*.tcl *.spice *.sp *.cir *.txt *.log *.json *.mag *.py);;All files (*)')
        if paths: self.populate(getattr(self,'paths',[])+paths)


class Workbench(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('RALF Layout Workbench — SKY130A')
        available=QApplication.primaryScreen().availableGeometry()
        self.resize(min(1660,available.width()-20),min(980,available.height()-40))
        self.settings=QSettings('RALF','LayoutWorkbench')
        self.proc=None; self.current=None; self.last_result=None; self.output_buffer=''
        self.dialogs=[]; self.magic_processes=[]; self.cancelled=False; self.live_logs=[]
        shell=QWidget(); self.setCentralWidget(shell); main_layout=QVBoxLayout(shell)
        root=QSplitter(Qt.Horizontal); self.main_columns=root; main_layout.addWidget(root,1)
        sidebar=QWidget(); side=QVBoxLayout(sidebar); sidebar.setMinimumWidth(145)
        side.addWidget(QLabel('FILES'))
        self.tree_root=QLineEdit(str(Path.home())); side.addWidget(self.tree_root)
        browse_root=QPushButton('Browse folder…'); side.addWidget(browse_root)
        self.file_model=QFileSystemModel(self); self.file_model.setReadOnly(True)
        self.file_model.setRootPath(str(Path.home()))
        self.file_tree=QTreeView(); self.file_tree.setModel(self.file_model)
        self.file_tree.setRootIndex(self.file_model.index(str(Path.home())))
        for col in (1,2,3): self.file_tree.hideColumn(col)
        self.file_tree.setHeaderHidden(True); self.file_tree.setMinimumWidth(130)
        self.file_tree.doubleClicked.connect(self.tree_open)
        self.file_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self.tree_menu)
        side.addWidget(self.file_tree,1)
        hint=QLabel('Expand folders with arrows.\nDouble-click files to open.'); hint.setWordWrap(True); side.addWidget(hint)
        browse_root.clicked.connect(self.browse_tree)
        self.tree_root.editingFinished.connect(self.set_tree_root)
        root.addWidget(sidebar)
        center=QWidget(); scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(center)
        root.addWidget(scroll); outer=QVBoxLayout(center); outer.setSpacing(14)
        banner=QHBoxLayout()
        title=QLabel('RALF  /  Layout Workbench'); title.setObjectName('title')
        banner.addWidget(title); banner.addStretch()
        self.reset_button=QPushButton('↻  Reset session'); self.reset_button.setObjectName('resetButton')
        self.reset_button.setToolTip('Restart the GUI and clear session fields. Generated files and tool settings are kept.')
        self.reset_button.clicked.connect(self.reset_session); banner.addWidget(self.reset_button)
        self.settings_button=QPushButton('Tool settings'); self.settings_button.clicked.connect(self.tool_settings)
        banner.addWidget(self.settings_button); main_layout.insertLayout(0,banner)
        intro=QLabel('Netlist → placement → routing → GDS   •   Verify with Magic DRC and Netgen LVS')
        intro.setObjectName('muted'); outer.addWidget(intro)
        design=QGroupBox('VIEW DESIGN'); design_row=QHBoxLayout(design)
        self.design_file=PathField(self,filters='Magic / GDS designs (*.mag *.gds *.gdsii);;All files (*)',cat=False)
        design_row.addWidget(self.design_file,1)
        self.view_design_button=QPushButton('Open design in Magic')
        self.view_design_button.clicked.connect(self.view_design); design_row.addWidget(self.view_design_button)
        outer.addWidget(design)
        area_row=QHBoxLayout()
        self.area_button=QPushButton('Measure total area (.mag)')
        self.area_button.clicked.connect(self.start_area)
        self.area_status=QLabel('Total area: —')
        self.area_status.setWordWrap(True)
        self.area_status.setToolTip('Width × height of the top-cell bounding rectangle, including subcells. Not summed transistor area or die area.')
        self.design_file.edit.textChanged.connect(lambda:self.area_status.setText('Total area: — (measure selected layout)'))
        area_row.addWidget(self.area_button); area_row.addWidget(self.area_status,1)
        outer.addLayout(area_row)
        self.workflow_panels=[]
        left=QGroupBox('01   NETLIST → GDS LAYOUT'); left.setObjectName('layoutPanel'); outer.addWidget(left)
        self.workflow_panels.append(left)
        lay=QVBoxLayout(left)
        self.net=PathField(self,filters='SPICE netlists (*.spice *.sp *.cir);;All files (*)')
        lay.addWidget(QLabel('Netlist file')); lay.addWidget(self.net)
        self.net.edit.editingFinished.connect(self.infer_net)
        self.net.edit.textChanged.connect(self.invalidate_net)
        row=QHBoxLayout(); self.top=QLineEdit(); self.top.setPlaceholderText('Inferred from .subckt / filename')
        row.addWidget(QLabel('Top cell')); row.addWidget(self.top); lay.addLayout(row)
        lay.addWidget(QLabel('External ports, in order'))
        self.ports=QLineEdit(); self.ports.setPlaceholderText('Inferred from .subckt; editable for flat netlists')
        lay.addWidget(self.ports)
        lay.addWidget(QLabel('Save in folder'))
        self.parent_dir=PathField(self,kind='directory',cat=False)
        self.parent_dir.setText(self.settings.value('output_parent',str(HERE.parent)))
        lay.addWidget(self.parent_dir)
        row=QHBoxLayout(); row.addWidget(QLabel('New run name'))
        self.run_name=QLineEdit(); self.run_name.setPlaceholderText('02_example_name'); row.addWidget(self.run_name)
        lay.addLayout(row)
        row=QHBoxLayout(); row.addWidget(QLabel('Placement trials'))
        self.trials=QSpinBox(); self.trials.setRange(100,10000); self.trials.setValue(300); row.addWidget(self.trials)
        row.addWidget(QLabel('Seed')); self.seed=QSpinBox(); self.seed.setRange(0,999999); self.seed.setValue(42); row.addWidget(self.seed)
        lay.addLayout(row)
        self.generate=QPushButton('Generate layout + GDS'); self.generate.setObjectName('primary')
        self.generate.clicked.connect(self.generate_layout); lay.addWidget(self.generate)
        self.layout_status=QLabel('Choose a netlist and a new output folder to begin.'); self.layout_status.setWordWrap(True)
        self.layout_status.setMinimumHeight(44)
        lay.addWidget(self.layout_status)
        buttons=QHBoxLayout()
        self.open_magic=QPushButton('Open in Magic'); self.open_magic.clicked.connect(lambda:self.show_magic())
        self.open_folder=QPushButton('Open output folder'); self.open_folder.clicked.connect(self.show_folder)
        self.load_run=QPushButton('Load run…'); self.load_run.clicked.connect(self.load_manifest)
        for b in (self.open_magic,self.open_folder,self.load_run): buttons.addWidget(b)
        lay.addLayout(buttons)
        self.layout_files=FileList(self); self.layout_files.setFixedHeight(110); lay.addWidget(self.layout_files,1)

        drcbox=QGroupBox('02   DRC CHECK'); drcbox.setObjectName('drcPanel'); outer.addWidget(drcbox); d=QVBoxLayout(drcbox)
        self.workflow_panels.append(drcbox)
        self.layout_file=PathField(self,filters='Magic layout (*.mag)')
        d.addWidget(QLabel('Layout to check')); d.addWidget(self.layout_file)
        self.layout_file.edit.textChanged.connect(self.invalidate_drc)
        row=QHBoxLayout(); self.run_drc=QPushButton('Run DRC'); self.run_drc.clicked.connect(self.start_drc)
        self.zoom=QPushButton('Locate selected error in Magic'); self.zoom.clicked.connect(self.zoom_error)
        row.addWidget(self.run_drc); row.addWidget(self.zoom); d.addLayout(row)
        self.drc_status=QLabel('Not checked'); d.addWidget(self.drc_status)
        self.errors=QTreeWidget(); self.errors.setHeaderLabels(['Rule / error','Box (Magic internal units)'])
        self.errors.setFixedHeight(150)
        self.errors.setRootIsDecorated(False); self.errors.header().setSectionResizeMode(0,QHeaderView.Stretch)
        self.errors.itemDoubleClicked.connect(lambda *_:self.zoom_error()); d.addWidget(self.errors,1)
        self.drc_files=FileList(self); self.drc_files.setMaximumHeight(95); d.addWidget(self.drc_files)
        lvsbox=QGroupBox('03   LVS CHECK'); lvsbox.setObjectName('lvsPanel'); outer.addWidget(lvsbox); l=QVBoxLayout(lvsbox)
        self.workflow_panels.append(lvsbox)
        label=QLabel('Select existing files or use the latest generated layout.'); label.setWordWrap(True); l.addWidget(label)
        self.lvs_net=PathField(self,filters='SPICE netlists (*.spice *.sp *.cir);;All files (*)')
        self.lvs_layout=PathField(self,filters='Magic layout (*.mag)')
        l.addWidget(QLabel('Reference netlist')); l.addWidget(self.lvs_net)
        l.addWidget(QLabel('Layout for LVS')); l.addWidget(self.lvs_layout)
        self.lvs_net.edit.textChanged.connect(self.lvs_selection_changed)
        self.lvs_layout.edit.textChanged.connect(self.lvs_selection_changed)
        self.run_lvs=QPushButton('Run LVS…'); self.run_lvs.clicked.connect(self.open_lvs); l.addWidget(self.run_lvs)
        self.lvs_status=QLabel('Not checked'); self.lvs_status.setWordWrap(True); l.addWidget(self.lvs_status)
        self.lvs_files=FileList(self); self.lvs_files.setFixedHeight(110); l.addWidget(self.lvs_files,1)
        outer.addStretch()

        logbox=QGroupBox('LIVE MESSAGES'); logbox.setMinimumWidth(330); root.addWidget(logbox); loglay=QVBoxLayout(logbox)
        self.activity=QLabel('Ready'); self.activity.setWordWrap(True); loglay.addWidget(self.activity)
        row=QHBoxLayout()
        self.progress=QProgressBar(); self.progress.setRange(0,1); self.progress.setValue(0); self.progress.setMaximumWidth(200)
        self.progress.setMaximumWidth(10000); loglay.addWidget(self.progress)
        self.stop=QPushButton('Cancel run'); self.stop.setEnabled(False); self.stop.clicked.connect(self.cancel)
        row.addWidget(self.stop)
        export=QPushButton('Save log…'); export.clicked.connect(self.save_log); row.addWidget(export)
        self.expand_log=QPushButton('Expand ↗'); self.expand_log.clicked.connect(self.show_log_window); row.addWidget(self.expand_log)
        loglay.addLayout(row)
        self.console=QPlainTextEdit(); self.console.setReadOnly(True); self.console.setFont(QFont('DejaVu Sans Mono',9))
        self.console.setMaximumBlockCount(12000); loglay.addWidget(self.console,1)
        self.console.setObjectName('terminal')
        self.error_box=QGroupBox('ERRORS'); error_layout=QVBoxLayout(self.error_box)
        self.error_list=QPlainTextEdit(); self.error_list.setReadOnly(True)
        self.error_list.setPlaceholderText('No errors reported.'); self.error_list.setMinimumHeight(130); self.error_list.setMaximumHeight(210)
        self.error_list.setObjectName('errorTerminal'); error_layout.addWidget(self.error_list)
        loglay.addWidget(self.error_box)
        self.error_messages=[]; self.log_pending=''; self.decision_prompt=None
        self.console.setMinimumHeight(70)
        root.setSizes([180,950,470]); root.setStretchFactor(0,0); root.setStretchFactor(1,3); root.setStretchFactor(2,2)
        root.setCollapsible(1,False); root.setCollapsible(2,False)
        # Navigation jumps to each stage without moving the live log.
        nav=QHBoxLayout()
        for label,panel in zip(('01  Layout','02  DRC','03  LVS'),self.workflow_panels):
            button=QPushButton(label); button.clicked.connect(lambda checked=False,p=panel:scroll.ensureWidgetVisible(p,0,20))
            nav.addWidget(button)
        outer.insertLayout(1,nav)
        self.setStyleSheet('''
            QMainWindow, QDialog {background:#f2f5f8;color:#182d40;}
            QWidget {font-family:"DejaVu Sans";font-size:12px;}
            QLabel#title {font-size:25px;font-weight:700;color:#143448;}
            QLabel#muted {color:#557084;padding-bottom:8px;}
            QGroupBox {background:white;border:1px solid #d6e0e7;border-radius:8px;margin-top:15px;padding:12px;}
            QGroupBox::title {subcontrol-origin:margin;left:12px;color:#28546d;font-weight:bold;}
            QGroupBox#layoutPanel {background:#effbf7;border:1px solid #8ccbb5;border-left:5px solid #198566;}
            QGroupBox#layoutPanel::title {color:#12664e;}
            QGroupBox#drcPanel {background:#fff8e9;border:1px solid #dec384;border-left:5px solid #c68b17;}
            QGroupBox#drcPanel::title {color:#91630b;}
            QGroupBox#lvsPanel {background:#f3f0ff;border:1px solid #b6a7e1;border-left:5px solid #7860b9;}
            QGroupBox#lvsPanel::title {color:#654b9a;}
            QLineEdit,QSpinBox,QPlainTextEdit,QTreeWidget {background:#fbfcfe;border:1px solid #cbd7df;border-radius:4px;padding:5px;selection-background-color:#c2e6ed;selection-color:#182d40;}
            QPushButton {background:#e8eff4;border:1px solid #c7d5df;border-radius:5px;padding:7px 10px;color:#18384e;}
            QPushButton:hover {background:#d5e6ee;}
            QPushButton:disabled {color:#8796a1;background:#eef1f3;}
            QPushButton#primary {background:#126d79;color:white;font-weight:bold;padding:10px;}
            QPushButton#resetButton {background:#fff0ec;border:1px solid #dcaa9d;color:#943f2a;font-weight:bold;}
            QHeaderView::section {background:#edf3f7;border:0;padding:5px;color:#3d596b;}
            QProgressBar {border:0;background:#dce8ee;border-radius:4px;text-align:center;}
            QProgressBar::chunk {background:#148293;}
            QPlainTextEdit#terminal {background:#080c10;color:#f1f5f9;border:1px solid #243542;selection-background-color:#36566d;}
            QPlainTextEdit#errorTerminal {background:#140c0e;color:#ff9292;border:1px solid #663c44;}
        ''')
        self.log('Ready. Paths refer to files inside the running IIC-OSIC-TOOLS container.')
        self.log('Existing output folders are preserved. DRC/LVS results are never assumed from process exit alone.')

    def reset_session(self):
        if self.proc and self.proc.state()!=QProcess.NotRunning:
            answer=QMessageBox.question(self,'Reset this session?',
                'Cancel the active run and restart the GUI? Generated and partial files will be kept.',
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if answer!=QMessageBox.Yes: return
            self.reset_pending=True
            self.cancel()
            return
        self.restart_application()

    def restart_application(self):
        # Replace this process, releasing its Qt windows, models and log buffers.
        # Do not terminate independent Magic windows: they may contain unsaved edits.
        self.settings.sync()
        sys.stdout.flush();sys.stderr.flush()
        os.execv(sys.executable,[sys.executable,str(HERE/'app.py'),'--reset-session',
                                '--tree-root='+self.tree_root.text()])

    def clear_session_fields(self):
        for field in (self.net,self.parent_dir,self.layout_file,self.lvs_net,self.lvs_layout,self.design_file):
            field.setText('')
        for field in (self.top,self.ports,self.run_name): field.clear()
        self.trials.setValue(300);self.seed.setValue(42)
        for files in (self.layout_files,self.drc_files,self.lvs_files): files.populate([])
        self.errors.clear();self.error_list.clear();self.error_messages=[];self.console.clear()
        self.current=None;self.last_result=None;self.output_buffer='';self.log_pending=''
        self.layout_status.setText('New session — select a netlist and output folder.')
        self.drc_status.setText('Not checked');self.lvs_status.setText('Not checked')
        self.activity.setText('Ready — session reset; generated files kept')
        self.progress.setRange(0,1);self.progress.setValue(0)

    def log(self,text):
        self.append_terminal(text.rstrip()+'\n')
        if getattr(self,'session_log',None):
            with open(self.session_log,'a') as f: f.write(text+'\n')
    def error(self,text):
        self.activity.setText('Action needs attention'); self.log('ERROR — '+text)
        self.add_error(text)
    def add_error(self,text):
        text=text.strip()
        if text and text not in self.error_messages:
            self.error_messages.append(text)
            self.error_list.appendPlainText(f'{len(self.error_messages)}. {text}')
    def append_terminal(self,text):
        bar=self.console.verticalScrollBar(); at_end=bar.value()>=bar.maximum()-2
        followers=[v for v in self.live_logs if v.isVisible() and v.verticalScrollBar().value()>=v.verticalScrollBar().maximum()-2]
        cursor=QTextCursor(self.console.document()); cursor.movePosition(QTextCursor.End)
        for line in text.splitlines(keepends=True):
            low=line.lower(); color='#f1f5f9'
            if any(x in low for x in ('error','traceback','failed','exception','could not','couldn\'t')): color='#ff7777'
            elif 'warning' in low: color='#f5c56b'
            elif 'pass' in low or 'match uniquely' in low: color='#7cdda6'
            elif 'stage ' in low or 'running:' in low: color='#75ceef'
            fmt=QTextCharFormat(); fmt.setForeground(QColor(color)); cursor.insertText(line,fmt)
        if at_end: self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())
        for view in followers: view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    def show_log_window(self):
        dialog=QDialog(self); dialog.setWindowTitle('RALF — Live command output'); dialog.resize(1100,760)
        lay=QVBoxLayout(dialog); view=QPlainTextEdit(); view.setReadOnly(True)
        view.setObjectName('terminal'); view.setFont(QFont('DejaVu Sans Mono',10))
        view.setDocument(self.console.document()); view.moveCursor(QTextCursor.End); lay.addWidget(view)
        self.live_logs.append(view)
        lay.addWidget(QLabel('Live output • scroll to inspect previous messages. Closing this window does not stop the run.'))
        self.dialogs.append(dialog); dialog.show()
    def browse_tree(self):
        path=QFileDialog.getExistingDirectory(self,'Browse files',self.tree_root.text())
        if path: self.tree_root.setText(path); self.set_tree_root()
    def set_tree_root(self):
        path=self.tree_root.text().strip()
        if Path(path).is_dir():
            self.file_tree.setRootIndex(self.file_model.index(path))
        else: self.error('Directory does not exist: '+path)
    def tree_open(self,index):
        path=Path(self.file_model.filePath(index))
        if path.is_file():
            if path.suffix.lower() in ('.mag','.gds','.gdsii'):
                self.design_file.setText(path); self.view_design()
            else: self.cat(str(path))
    def tree_menu(self,position):
        index=self.file_tree.indexAt(position)
        if not index.isValid(): return
        self.file_tree.setCurrentIndex(index)
        path=self.file_model.filePath(index)
        menu=QMenu(self.file_tree)
        action=menu.addAction('Copy path')
        action.triggered.connect(lambda:self.copy_tree_path(path))
        menu.exec(self.file_tree.viewport().mapToGlobal(position))
    def copy_tree_path(self,path):
        QApplication.clipboard().setText(str(Path(path).absolute()))
        self.log('Copied path: '+str(Path(path).absolute()))
    def view_design(self):
        self.show_magic(design_path=self.design_file.text())
    def start_area(self):
        self.start({'action':'area','layout':self.design_file.text(),
                    'report_dir':str(HERE/'jobs'/('area_'+stamp()))})
    def show_area(self,result):
        area=result.get('area')
        if area:
            self.area_status.setText(f"Total area: {area['area_um2']:.3f} µm²\n"
                f"{area['width_um']:.3f} × {area['height_um']:.3f} µm — {Path(result['layout']).name}")
            self.area_status.setToolTip(area['definition']+'\n'+result['layout'])
    def cat(self,path):
        try:
            if not Path(path).is_file(): raise ValueError('Select an existing text file first.')
            if Path(path).stat().st_size>10_000_000: raise ValueError('File exceeds the 10 MB text-view limit.')
            dialog=TextWindow(path,self); self.dialogs.append(dialog); dialog.show()
        except Exception as e: self.error(str(e))
    def invalidate_net(self):
        self.lvs_status.setText('Not checked — netlist selection changed')
        self.layout_files.populate([self.net.text()])
    def infer_net(self):
        try:
            top,ports,_,_=normalize_netlist(self.net.text())
            self.top.setText(top); self.ports.setText(' '.join(ports))
            if not self.run_name.text(): self.run_name.setText('02_'+top)
            self.log('Netlist selected: '+self.net.text())
        except Exception as e: self.log('Netlist details: '+str(e))
    def invalidate_drc(self):
        self.errors.clear(); self.drc_status.setText('Not checked — layout selection changed')
        self.lvs_status.setText('Not checked — layout selection changed')
        if hasattr(self,'drc_files'): self.drc_files.populate([self.layout_file.text()])
    def lvs_selection_changed(self):
        self.lvs_status.setText('Not checked — selection changed')
        self.lvs_files.populate([self.lvs_net.text(),self.lvs_layout.text()])
    def tool_settings(self):
        dialog=QDialog(self); dialog.setWindowTitle('Tool locations'); dialog.resize(780,220)
        form=QFormLayout(dialog)
        repo=PathField(self,kind='directory',cat=False); repo.setText(self.repo())
        pdk=PathField(self,kind='directory',cat=False); pdk.setText(self.pdk())
        form.addRow('RALF source folder',repo); form.addRow('SKY130A PDK folder',pdk)
        form.addRow(QLabel('Each layout run snapshots the RALF source into its own 00_Work folder.'))
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec():
            self.settings.setValue('repo',repo.text()); self.settings.setValue('pdk',pdk.text())
            CONFIG.update(repo=repo.text(),pdk=pdk.text())
            if os.environ.get('RALF_CONFIG'): Path(os.environ['RALF_CONFIG']).write_text(json.dumps(CONFIG,indent=2))
    def repo(self): return CONFIG.get('repo') or self.settings.value('repo',str(HERE.parent/'ralf'))
    def pdk(self): return CONFIG.get('pdk') or self.settings.value('pdk',os.environ.get('PDKPATH',''))
    def report_root(self):
        if self.layout_file.text() and Path(self.layout_file.text()).parent.name in ('02_Placement','04_Routing'):
            return str(Path(self.layout_file.text()).parent.parent/'05_Verification')
        if self.last_result and self.last_result.get('output'): return str(Path(self.last_result['output'])/'05_Verification')
        if self.layout_file.text(): return str(Path(self.layout_file.text()).parent/'05_Verification')
        return str(Path(self.parent_dir.text())/'05_Verification')
    def generate_layout(self):
        name=self.run_name.text().strip()
        if not name or name in ('.','..') or '/' in name or '\\' in name:
            return self.error('Enter a new run folder name, not a path.')
        if not self.parent_dir.text() or not Path(self.parent_dir.text()).is_absolute():
            return self.error('Choose an absolute output folder using Browse before generating a layout.')
        self.start({'action':'layout','netlist':self.net.text(),'top':self.top.text().strip(),
                    'ports':self.ports.text().strip(),'output':str(Path(self.parent_dir.text())/name),
                    'placements':self.trials.value(),'seed':self.seed.value(),'repo':self.repo()})
    def start_drc(self):
        self.start({'action':'drc','layout':self.layout_file.text(),
                    'report_dir':str(Path(self.report_root())/('drc_'+stamp()))})
    def open_lvs(self):
        self.lvs_dialog=LVSDialog(self); self.dialogs.append(self.lvs_dialog); self.lvs_dialog.show()
    def start(self,cfg):
        if self.proc and self.proc.state()!=QProcess.NotRunning:
            self.error('Wait for the current job or cancel it first.'); return False
        try:
            for key in ('netlist','layout'):
                if key in cfg and not Path(cfg[key]).is_file(): raise ValueError(f'Select an existing {key} file.')
            if cfg['action']=='layout':
                top,ports,_,_=normalize_netlist(cfg['netlist'],cfg['top'],cfg['ports'])
                cfg['top']=top;cfg['ports']=' '.join(ports)
                if Path(cfg['output']).exists(): raise ValueError('That output folder already exists. Enter a new run name.')
            elif cfg['action']=='lvs': normalize_netlist(cfg['netlist'],cfg['top'],cfg['ports'])
            cfg['pdk']=self.pdk()
            jobs=HERE/'jobs'; jobs.mkdir(exist_ok=True)
            job=jobs/(stamp()+'.json'); cfg['result_file']=str(job.with_suffix('.result.json'))
            job.write_text(json.dumps(cfg,indent=2))
            self.session_log=job.with_suffix('.log'); self.current=cfg; self.cancelled=False
            self.output_buffer=''
            self.log_pending=''; self.error_messages=[]; self.error_list.clear()
            self.proc=QProcess(self); self.proc.setProcessChannelMode(QProcess.MergedChannels)
            self.proc.readyReadStandardOutput.connect(self.read_output)
            self.proc.finished.connect(self.finished)
            self.proc.errorOccurred.connect(lambda e:self.error('Worker process: '+self.proc.errorString()))
            self.set_busy(True); self.log('START — '+cfg['action'])
            if cfg['action']=='drc': self.errors.clear(); self.drc_status.setText('Running full DRC…')
            elif cfg['action']=='lvs': self.lvs_status.setText('Running DRC gate, extraction and LVS…')
            elif cfg['action']=='area': self.area_status.setText('Measuring…')
            else: self.layout_status.setText('Generating… progress and tool output appear below.')
            self.proc.start(sys.executable,['-u',str(HERE/'flow.py'),str(job)])
            self.settings.setValue('output_parent',self.parent_dir.text())
            return True
        except Exception as e: self.error(str(e)); return False
    def set_busy(self,busy):
        for widget in (self.generate,self.run_drc,self.run_lvs,self.load_run,self.settings_button,self.area_button,self.design_file,
                       self.net,self.top,self.ports,self.parent_dir,self.run_name,self.trials,self.seed,self.layout_file,self.lvs_net,self.lvs_layout):
            widget.setEnabled(not busy)
        self.stop.setEnabled(busy)
        self.progress.setRange(0,0 if busy else 1); self.progress.setValue(0 if busy else 1)
        self.activity.setText('Working…' if busy else 'Ready')
    def read_output(self):
        text=bytes(self.proc.readAllStandardOutput()).decode(errors='replace').replace('\r','\n')
        self.output_buffer=(self.output_buffer+text)[-1_000_000:]
        self.append_terminal(text)
        self.log_pending+=text
        while '\n' in self.log_pending:
            line,self.log_pending=self.log_pending.split('\n',1)
            if line.startswith('WORKBENCH_DECISION '):
                self.ask_placement_decision(json.loads(line[len('WORKBENCH_DECISION '):]))
            elif line.startswith('WORKBENCH_ARTIFACT '):
                self.show_artifact(json.loads(line[len('WORKBENCH_ARTIFACT '):]))
            elif line.startswith('WORKBENCH_DRC_RESULT '):
                self.show_drc(json.loads(line[len('WORKBENCH_DRC_RESULT '):]))
            elif line.startswith('WORKBENCH_DRC_ERROR\t'):
                fields=line.split('\t'); self.add_error(fields[1]+' — box '+fields[2])
            elif any(x in line.lower() for x in ('error —','failed with error','traceback','error:', 'exception:')):
                self.add_error(line)
        with open(self.session_log,'a') as f: f.write(text)
    def ask_placement_decision(self,result):
        self.show_drc(result)
        self.activity.setText('Placement DRC found — waiting for your choice')
        prompt=QMessageBox(self); prompt.setWindowTitle('DRC found in placement')
        prompt.setIcon(QMessageBox.Warning)
        prompt.setText(f"DRC found: {result['count']} placement error regions.")
        prompt.setInformativeText('Stop to inspect the placement, or continue routing anyway. Continuing does not waive DRC rules; final DRC and LVS are still required.')
        prompt.setDetailedText(result['report'])
        stop=prompt.addButton('Stop',QMessageBox.RejectRole)
        go=prompt.addButton('Continue anyway',QMessageBox.AcceptRole)
        prompt.setDefaultButton(stop)
        self.decision_prompt=prompt
        def decided(button):
            answer='continue' if button==go else 'stop'
            if self.proc and self.proc.state()!=QProcess.NotRunning: self.proc.write((answer+'\n').encode())
            self.log('Placement DRC decision: '+answer)
            self.activity.setText('Working…' if answer=='continue' else 'Stopping…')
            self.decision_prompt=None
        prompt.buttonClicked.connect(decided)
        prompt.rejected.connect(lambda:decided(stop) if self.decision_prompt else None)
        prompt.open()
    def finished(self,code,status):
        self.read_output(); self.set_busy(False)
        if getattr(self,'reset_pending',False):
            self.restart_application(); return
        if self.decision_prompt:
            self.decision_prompt.close(); self.decision_prompt=None
        action=self.current['action']
        if code or self.cancelled or not Path(self.current['result_file']).is_file():
            self.discover_partial_files()
            msg='Cancelled — partial files retained.' if self.cancelled else 'Failed — inspect the messages below.'
            {'layout':self.layout_status,'drc':self.drc_status,'lvs':self.lvs_status,'area':self.area_status}[action].setText(msg)
            self.error(msg+' Full log: '+str(self.session_log)); return
        result=json.loads(Path(self.current['result_file']).read_text())
        if action=='layout':
            self.apply_manifest(result)
            self.log('Layout and GDS saved in '+result['output'])
            # Preserve actual executable output next to the run.
            import shutil
            shutil.copy2(self.session_log,Path(result['output'])/'05_Verification'/'generation.log')
        elif action=='drc': self.show_drc(result)
        elif action=='area':
            self.show_area(result)
            self.log(self.area_status.text())
        else:
            self.lvs_status.setText('PASS — circuits match uniquely' if result['passed'] else 'FAIL — circuits differ; open the report')
            if result.get('drc_count',0): self.lvs_status.setText(self.lvs_status.text()+f" • DRC still has {result['drc_count']} error regions")
            self.lvs_files.populate([self.current['netlist'],self.current['layout'],result['report'],result['reference'],result['extracted']])
            self.log(self.lvs_status.text())
            if (self.last_result and self.current['layout']==self.last_result['layout']
                    and self.current['netlist']==self.last_result['netlist']):
                record=dict(result,layout_hash=digest(self.current['layout']),netlist_hash=digest(self.current['netlist']))
                self.last_result['lvs']=record
                self.last_result['status']=('DRC clean' if not result.get('drc_count',0) else 'DRC violations remain')+'; LVS '+('PASS' if result['passed'] else 'FAIL')
                (Path(self.last_result['output'])/'manifest.json').write_text(json.dumps(self.last_result,indent=2))
                self.layout_status.setText('Saved: '+self.last_result['output']+'\n'+self.last_result['status'])
        self.activity.setText('Finished — '+action)
    def apply_manifest(self,result):
        self.last_result=result
        self.net.setText(result['netlist']); self.top.setText(result['top']); self.ports.setText(result['ports'])
        self.lvs_net.setText(result['netlist']); self.lvs_layout.setText(result['layout'])
        self.layout_file.setText(result['layout'])
        self.layout_status.setText('Saved: '+result['output']+'\n'+result['status'])
        self.layout_files.populate([result['netlist'],result['placement'],result['layout'],result['routing'],result['gds'],Path(result['output'])/'manifest.json'])
        self.show_drc(result)
        previous=result.get('lvs',{})
        if previous:
            if (previous.get('layout_hash')==digest(result['layout'])
                    and previous.get('netlist_hash')==digest(result['netlist'])):
                self.lvs_status.setText('PASS — circuits match uniquely' if previous['passed'] else 'FAIL — circuits differ')
                if previous.get('drc_count',0): self.lvs_status.setText(self.lvs_status.text()+f" • DRC still has {previous['drc_count']} error regions")
                self.lvs_files.populate([previous['report'],previous['reference'],previous['extracted']])
            else:
                self.lvs_status.setText('Inputs changed — run LVS again')
                self.layout_status.setText('Saved: '+result['output']+'\nInputs changed — recheck DRC and LVS')
    def show_drc(self,result):
        self.layout_file.setText(result['layout'])
        if self.current and self.current.get('action')=='layout' and 'output' not in result:
            self.show_artifact({'layout':result['layout'],'output':self.current.get('output'),'stage':'Available'})
        self.errors.clear(); self.drc_result=result
        count=result['count']
        self.drc_status.setText('PASS — 0 DRC violations' if count==0 else f'{count} error regions • {len(result["errors"])} rule boxes listed')
        for err in result['errors']:
            self.add_error(err['rule']+' — box '+' '.join(f'{x:g}' for x in err['box']))
            item=QTreeWidgetItem([err['rule'],' '.join(f'{x:g}' for x in err['box'])])
            item.setData(0,Qt.UserRole,err['box']); self.errors.addTopLevelItem(item)
        self.drc_files.populate([result['layout'],result['report'],str(Path(result['report']).with_suffix('.json'))])
        self.show_area(result)
        self.log(self.drc_status.text())
    def show_artifact(self,result):
        path=result['layout']
        if not Path(path).is_file(): return
        self.layout_file.setText(path); self.lvs_layout.setText(path); self.design_file.setText(path)
        if self.current and self.current.get('netlist'): self.lvs_net.setText(self.current['netlist'])
        output=result.get('output')
        files=[self.net.text(),path]
        if output:
            for name in ('01_Netlist','02_Placement','03_Devices','04_Routing','05_Verification','06_GDS'):
                folder=Path(output)/name
                files.extend(str(p) for p in sorted(folder.glob('*')) if p.is_file() and p.suffix in ('.mag','.tcl','.spice','.log','.json','.gds'))
        self.layout_files.populate(files)
        self.drc_files.populate([path])
        self.layout_status.setText(result.get('stage','Partial')+' layout available: '+path+'\nVerification may still be pending or have errors.')
    def discover_partial_files(self):
        if self.current.get('action')!='layout' or not self.current.get('output'): return
        root=Path(self.current['output']); top=self.current.get('top','')
        candidates=[root/'04_Routing'/(top+'_Routed.mag'),root/'02_Placement'/(top+'.mag')]
        selected=next((p for p in candidates if p.is_file()),None)
        if selected:
            self.show_artifact({'layout':str(selected),'output':str(root),'stage':'Partial / stopped'})
            reports=sorted((root/'05_Verification').rglob('drc.json'))
            for report in reports:
                data=json.loads(report.read_text())
                if data.get('layout')==str(selected): self.show_drc(data)
    def cancel(self):
        if self.proc and self.proc.state()!=QProcess.NotRunning:
            self.cancelled=True
            try: os.killpg(self.proc.processId(),signal.SIGTERM)
            except ProcessLookupError: self.proc.terminate()
            self.log('Cancellation requested; stopping this job and its child tools.')
    def show_magic(self,box=None,design_path=None):
        try:
            layout=design_path or self.layout_file.text()
            if not Path(layout).is_file(): raise ValueError('Choose or generate a Magic layout first.')
            if Path(layout).suffix.lower() in ('.gds','.gdsii'):
                script='gds read '+tcl(Path(layout).resolve())+'\nset tops [cellname list top]\nif {[llength $tops] > 0} {load [lindex $tops 0]}\nselect top cell\nexpand\n'
            elif Path(layout).suffix.lower()=='.mag': script=load_script(layout)
            else: raise ValueError('Select a .mag, .gds or .gdsii design.')
            script+='set wbwin [lindex [magic::windownames layout] 0]\n$wbwin view\n'
            focus=''
            if box:
                # DRC listall coordinates are internal units, not lambda.
                x0,y0,x1,y1=box; margin=max(x1-x0,y1-y0,40)*0.7
                focus+='box values '+' '.join(f'{v:g}i' for v in (x0-margin,y0-margin,x1+margin,y1+margin))+'\n$wbwin findbox zoom\n'
                focus+='box values '+' '.join(f'{v:g}i' for v in box)+'\ndrc check\n'
            jobs=HERE/'jobs'; jobs.mkdir(exist_ok=True)
            path=jobs/('view_'+stamp()+'.tcl')
            if focus:
                # Initial Tk mapping performs its own fit; zoom after the window maps.
                script+='after 900 {\n'+focus+'}\n'
            path.write_text(script)
            log=open(path.with_suffix('.log'),'w')
            proc=subprocess.Popen([os.environ.get('RALF_MAGIC','magic'),'-rcfile',str(Path(self.pdk())/'libs.tech/magic/sky130A.magicrc'),str(path)],
                                  stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            log.close(); self.magic_processes.append(proc)
            self.log('Opened in Magic'+(' at selected error' if box else '')+': '+layout)
            QTimer.singleShot(1500,lambda:self.check_magic(proc,path))
        except Exception as e: self.error(str(e))
    def check_magic(self,proc,path):
        if proc.poll() is not None:
            self.error('Magic closed or could not open. '+path.with_suffix('.log').read_text(errors='replace'))
    def zoom_error(self):
        item=self.errors.currentItem()
        if not item: return self.error('Select an error row first (or double-click a row).')
        self.show_magic(item.data(0,Qt.UserRole))
    def show_folder(self):
        if self.last_result:
            subprocess.Popen(['xdg-open',self.last_result['output']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else: self.error('Generate or load a run first.')
    def load_manifest(self):
        path,_=QFileDialog.getOpenFileName(self,'Open saved run manifest',self.parent_dir.text(),'Manifest (manifest.json)')
        if path:
            try: self.apply_manifest(json.loads(Path(path).read_text()))
            except Exception as e: self.error('Cannot load run: '+str(e))
    def save_log(self):
        path,_=QFileDialog.getSaveFileName(self,'Save message log','ralf_messages.log')
        if path:
            try: Path(path).write_text(self.console.toPlainText())
            except Exception as e: self.error(str(e))
    def closeEvent(self,event):
        if self.proc and self.proc.state()!=QProcess.NotRunning:
            self.error('Cancel the running job before closing the workbench.'); event.ignore()
        else: event.accept()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else ''


if __name__=='__main__':
    app=QApplication(sys.argv)
    window=Workbench(); window.show()
    if '--reset-session' in sys.argv:
        window.clear_session_fields()
        tree=next((a.split('=',1)[1] for a in sys.argv if a.startswith('--tree-root=')),None)
        if tree: window.tree_root.setText(tree);window.set_tree_root()
    elif len(sys.argv)>1:
        try: window.apply_manifest(json.loads(Path(sys.argv[1]).read_text()))
        except Exception as e: window.error(str(e))
    sys.exit(app.exec())
