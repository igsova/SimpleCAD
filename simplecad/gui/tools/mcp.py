"""User-controlled AI connection, with copyable local MCP client setup."""
import json
import shlex
import shutil
from ... import ROOT
from ..qt import QtCore, QtWidgets
from ...mcp.bridge import instance
import FreeCADGui as Gui

_dialog=None


class ConnectionDialog(QtWidgets.QDialog):
    def __init__(self,parent):
        super().__init__(parent)
        self.setWindowTitle('AI connection (MCP)')
        self.setModal(False); self.resize(620,430)
        check_icon = (ROOT/'Resources/icons/checked.svg').as_posix()
        self.setStyleSheet('QCheckBox::indicator { width: 16px; height: 16px; } '
                           'QCheckBox::indicator:checked { image: url("'+check_icon+'"); }')
        layout=QtWidgets.QVBoxLayout(self)
        intro=QtWidgets.QLabel('Connect Codex to inspect your open models and use SimpleCAD tools.\nStart the server here whenever you want to use the connection.')
        intro.setWordWrap(True); layout.addWidget(intro)
        self.state=QtWidgets.QLabel(); layout.addWidget(self.state)
        self.edits=QtWidgets.QCheckBox('Allow model changes')
        self.edits.setChecked(instance().api.allow_changes)
        self.edits.setToolTip('Turn off to allow inspection only. Model edits support Undo; settings changes are application preferences.')
        self.edits.toggled.connect(self.set_editing); layout.addWidget(self.edits)
        self.toggle=QtWidgets.QPushButton(); self.toggle.clicked.connect(self.toggle_server); layout.addWidget(self.toggle)
        setup=QtWidgets.QLabel('Codex setup: run the copied command once in Terminal, then start a new Codex task.')
        setup.setWordWrap(True); layout.addWidget(setup)
        codex=QtWidgets.QPushButton('Copy Codex setup command'); codex.clicked.connect(self.copy_codex); layout.addWidget(codex)
        details=QtWidgets.QPushButton('Connection details / other MCP clients')
        details.setCheckable(True); layout.addWidget(details)
        self.configuration=QtWidgets.QPlainTextEdit(); self.configuration.setReadOnly(True)
        self.configuration.setMaximumHeight(150); self.configuration.hide(); layout.addWidget(self.configuration)
        row=QtWidgets.QHBoxLayout(); layout.addLayout(row)
        self.copy=QtWidgets.QPushButton('Copy MCP configuration'); self.copy.clicked.connect(self.copy_config); row.addWidget(self.copy)
        self.copy.hide()
        details.toggled.connect(self.configuration.setVisible); details.toggled.connect(self.copy.setVisible)
        close=QtWidgets.QPushButton('Close'); close.clicked.connect(self.close); row.addWidget(close)
        note=QtWidgets.QLabel('The connection runs on this computer only. Your AI client receives the model details it requests. Closing this panel leaves the server running; Stop server disconnects it.')
        note.setWordWrap(True); layout.addWidget(note)
        self.timer=QtCore.QTimer(self); self.timer.setInterval(500); self.timer.timeout.connect(self.refresh); self.timer.start()
        self.refresh()

    def config(self):
        command=shutil.which('python3') or 'python3'
        return {'mcpServers':{'simplecad':{'command':command,'args':[str(ROOT/'scripts/simplecad_mcp.py')]}}}

    def set_editing(self,value): instance().api.allow_changes=value

    def toggle_server(self):
        try:
            server=instance()
            if server.running: server.stop()
            else: server.start(self.edits.isChecked())
            self.refresh()
        except Exception as error:
            self.state.setText(str(error))

    def refresh(self):
        server=instance()
        status=('Running · '+('Model changes allowed' if server.api.allow_changes else 'Read-only')+'\nLast request: '+server.api.last_action
                if server.running else 'Stopped')
        self.state.setText(status)
        self.toggle.setText('Stop server' if server.running else 'Start server')
        # The token is never shown or copied. Clients read the private file.
        text=json.dumps(self.config(),indent=2)
        if server.running: text+='\n\nConnection file (for multiple FreeCAD windows):\n'+str(server.path)
        if self.configuration.toPlainText()!=text: self.configuration.setPlainText(text)

    def copy_config(self): QtWidgets.QApplication.clipboard().setText(json.dumps(self.config(),indent=2))

    def copy_codex(self):
        config=self.config()['mcpServers']['simplecad']
        QtWidgets.QApplication.clipboard().setText(shlex.join(['codex','mcp','add','simplecad','--',config['command'],*config['args']]))


def show():
    global _dialog
    if _dialog is None: _dialog=ConnectionDialog(Gui.getMainWindow())
    _dialog.show(); _dialog.raise_(); _dialog.activateWindow()
