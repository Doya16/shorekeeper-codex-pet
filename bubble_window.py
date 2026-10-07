"""A non-interactive bubble that follows the character's horizontal bounds."""
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QPainter,QPainterPath,QPen,QColor,QFontMetrics
from PySide6.QtWidgets import QWidget
from appearance import font

class SpeechBubble(QWidget):
    def __init__(self,pet):
        flags=Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowDoesNotAcceptFocus|Qt.WindowType.WindowTransparentForInput
        if pet.on_top: flags|=Qt.WindowType.WindowStaysOnTopHint
        super().__init__(pet,flags); self.pet=pet; self.arrow_x=0; self.above=True
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('守岸人 · 气泡')

    def paintEvent(self,event):
        pet=self.pet; opts=pet.options; width=pet.bubble_width; r=pet.bubble_rect
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.scale(pet.bubble_scale,pet.bubble_scale)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(29,52,89,35)); p.drawRoundedRect(r.translated(1,4),16,16)
        path=QPainterPath(); path.addRoundedRect(r,16,16)
        arrow=max(r.left()+22,min(self.arrow_x,r.right()-22))
        y=r.bottom() if self.above else r.top(); tip=y+11 if self.above else y-11
        path.moveTo(arrow-12,y); path.lineTo(arrow,tip); path.lineTo(arrow+12,y); path.closeSubpath()
        p.setPen(QPen(QColor('#adc6e7'),1.4)); p.setBrush(QColor(249,252,255,253)); p.drawPath(path)
        state=pet.bubble_state(); color='#d99436' if state in ('error','waiting') else '#588ccd'
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(color)); p.drawEllipse(QRectF(24,27,8,8))
        p.setPen(QColor('#315a88')); p.setFont(pet.bubble_title_font)
        baseline=22+QFontMetrics(p.font()).ascent()
        for line in pet.bubble_title_lines: p.drawText(42,round(baseline),line); baseline+=pet.bubble_title_height
        p.setFont(pet.bubble_font); p.setPen(QColor('#314963')); baseline=pet.bubble_body_top+QFontMetrics(pet.bubble_font).ascent()
        for line in pet.bubble_lines: p.drawText(26,round(baseline),line); baseline+=pet.bubble_line_height
        p.setPen(QColor('#ccdcee')); p.drawLine(25,round(pet.bubble_divider_y),round(width-25),round(pet.bubble_divider_y))
        p.setPen(QColor('#6482a3')); p.setFont(pet.bubble_footer_font)
        baseline=pet.bubble_divider_y+6+QFontMetrics(p.font()).ascent()
        for line in pet.bubble_footer_lines: p.drawText(26,round(baseline),line); baseline+=pet.bubble_footer_height
        p.end()
