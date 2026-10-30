"""用户受控的 AI 助手连接，提供可复制的本地 MCP 客户端配置。"""
import json
import shlex
import shutil
from ... import ROOT
from ..qt import QtCore, QtWidgets
from ...mcp.bridge import instance
import FreeCADGui as Gui

_dialog = None


class ConnectionDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('AI 助手连接 (MCP)')
        self.setModal(False); self.resize(620, 430)
        check_icon = (ROOT / 'Resources/icons/checked.svg').as_posix()
        self.setStyleSheet('QCheckBox::indicator { width: 16px; height: 16px; } '
                           'QCheckBox::indicator:checked { image: url("' + check_icon + '"); }')
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel('连接 Codex 等 AI 助手以检查当前打开的模型并调用 SimpleCAD 工具。\n'
                                '需要使用该连接时，可随时在此启动服务。')
        intro.setWordWrap(True); layout.addWidget(intro)
        self.state = QtWidgets.QLabel(); layout.addWidget(self.state)
        self.edits = QtWidgets.QCheckBox('允许 AI 修改模型')
        self.edits.setChecked(instance().api.allow_changes)
        self.edits.setToolTip('关闭后仅允许 AI 检查与读取模型（只读模式）。模型修改支持撤销；设置更改属于应用程序偏好项。')
        self.edits.toggled.connect(self.set_editing); layout.addWidget(self.edits)
        self.toggle = QtWidgets.QPushButton(); self.toggle.clicked.connect(self.toggle_server); layout.addWidget(self.toggle)
        setup = QtWidgets.QLabel('Codex 配置：在终端 (Terminal) 中运行一次复制的命令，然后即可开始新的 Codex 任务。')
        setup.setWordWrap(True); layout.addWidget(setup)
        codex = QtWidgets.QPushButton('复制 Codex 配置命令'); codex.clicked.connect(self.copy_codex); layout.addWidget(codex)
        details = QtWidgets.QPushButton('连接详情 / 其他 MCP 客户端配置')
        details.setCheckable(True); layout.addWidget(details)
        self.configuration = QtWidgets.QPlainTextEdit(); self.configuration.setReadOnly(True)
        self.configuration.setMaximumHeight(150); self.configuration.hide(); layout.addWidget(self.configuration)
        row = QtWidgets.QHBoxLayout(); layout.addLayout(row)
        self.copy = QtWidgets.QPushButton('复制 MCP 配置 (JSON)'); self.copy.clicked.connect(self.copy_config); row.addWidget(self.copy)
        self.copy.hide()
        details.toggled.connect(self.configuration.setVisible); details.toggled.connect(self.copy.setVisible)
        close = QtWidgets.QPushButton('关闭'); close.clicked.connect(self.close); row.addWidget(close)
        note = QtWidgets.QLabel('该连接仅在此本机运行。您的 AI 客户端仅接收其请求的模型信息。关闭此窗口不会中断后台服务；点击“停止服务”可断开连接。')
        note.setWordWrap(True); layout.addWidget(note)
        self.timer = QtCore.QTimer(self); self.timer.setInterval(500); self.timer.timeout.connect(self.refresh); self.timer.start()
        self.refresh()

    def config(self):
        command = shutil.which('python3') or 'python3'
        return {'mcpServers': {'simplecad': {'command': command, 'args': [str(ROOT / 'scripts/simplecad_mcp.py')]}}}

    def set_editing(self, value): instance().api.allow_changes = value

    def toggle_server(self):
        try:
            server = instance()
            if server.running: server.stop()
            else: server.start(self.edits.isChecked())
            self.refresh()
        except Exception as error:
            self.state.setText(str(error))

    def refresh(self):
        server = instance()
        status = ('运行中 · ' + ('允许修改模型' if server.api.allow_changes else '只读模式') + '\n最近请求: ' + server.api.last_action
                  if server.running else '已停止')
        self.state.setText(status)
        self.toggle.setText('停止服务' if server.running else '启动服务')
        # 认证令牌绝不显示或复制；客户端通过私有连接文件读取
        text = json.dumps(self.config(), indent=2)
        if server.running: text += '\n\n连接信息文件 (用于多 FreeCAD 窗口通信):\n' + str(server.path)
        if self.configuration.toPlainText() != text: self.configuration.setPlainText(text)

    def copy_config(self): QtWidgets.QApplication.clipboard().setText(json.dumps(self.config(), indent=2))

    def copy_codex(self):
        config = self.config()['mcpServers']['simplecad']
        QtWidgets.QApplication.clipboard().setText(shlex.join(['codex', 'mcp', 'add', 'simplecad', '--', config['command'], *config['args']]))


def show():
    global _dialog
    if _dialog is None: _dialog = ConnectionDialog(Gui.getMainWindow())
    _dialog.show(); _dialog.raise_(); _dialog.activateWindow()