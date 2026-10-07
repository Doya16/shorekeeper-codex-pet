"""Keep inactive fields visibly locked, with an explanation beside the field."""
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel

class GuardedField(QWidget):
    def __init__(self,control):
        super().__init__(); self.control=control; self.original_tooltip=control.toolTip()
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(5)
        layout.addWidget(control)
        self.hint=QLabel(); self.hint.setWordWrap(True); self.hint.setObjectName('lockedHint')
        layout.addWidget(self.hint); self.hint.hide()

    def lock(self,reason=''):
        self.control.setEnabled(not reason)
        self.control.setToolTip(reason or self.original_tooltip)
        self.setToolTip(reason); self.hint.setText(reason); self.hint.setVisible(bool(reason))
        self.control.setAccessibleDescription(reason)
