import math,time
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QPainter,QPainterPath,QPen,QColor,QFontMetrics
from appearance import font
from bindings import MANUAL
from voice_pool import clip_bubble_text
from bubble_window import SpeechBubble
from PySide6.QtWidgets import QApplication
from sizing import fitted_scale

def wrap_text(text,metrics,width):
    lines=[]; line=''
    for char in text:
        if char=='\n' or (line and metrics.horizontalAdvance(line+char)>width):
            lines.append(line); line='' if char=='\n' else char
        else: line+=char
    lines.append(line)
    return lines

class PetRenderer:
    def image_rect(self,image):
        r=self.pet_rect; ratio=min(r.width()/image.width(),r.height()/image.height())
        width=image.width()*ratio; height=image.height()*ratio
        return QRectF(r.center().x()-width/2,r.center().y()-height/2,width,height)
    def update_layout(self):
        area=self.screen_area(); self.layout_area=area
        b=self.bubble_binding(); opts=self.options
        self.bubble_font=font(b['font_family'] or opts['bubble_font_family'],b['font_size'] or opts['bubble_font_size'])
        self.quota_font=font(opts['font_family'],opts['quota_font_size'])
        size=opts['pet_size']; width=size+8; self.scene_width=width
        self.pet_rect=QRectF(4,4,size,size)
        metrics=QFontMetrics(self.quota_font)
        bar_height=max(39,metrics.height()+18)
        bar_width=min(size,max(146,metrics.horizontalAdvance(self.quota_label(compact=True))+28))
        self.quota_rect=QRectF((width-bar_width)/2,size+8,bar_width,bar_height)
        height=self.quota_rect.bottom()+6; self.scene_height=height
        self.scale_factor=fitted_scale(self.requested_scale,width,height,area.width(),area.height())
        # Round inward so fractional zoom cannot cross the character bounds.
        self.bubble_left=math.ceil(self.pet_rect.left()*self.scale_factor)
        bubble_pixels=math.floor(self.pet_rect.right()*self.scale_factor)-self.bubble_left
        self.bubble_scale=self.scale_factor
        self.bubble_width=bubble_pixels/self.bubble_scale
        self.bubble_title_font=font(opts['font_family'],max(15,opts['ui_font_size']-1),True)
        title_metrics=QFontMetrics(self.bubble_title_font)
        self.bubble_title_lines=wrap_text('守岸人 · '+self.state_title(self.bubble_state()),title_metrics,self.bubble_width-68)
        self.bubble_title_height=title_metrics.height()+2
        self.bubble_body_top=22+self.bubble_title_height*len(self.bubble_title_lines)+9
        self.bubble_lines=wrap_text(self.bubble_text(),QFontMetrics(self.bubble_font),self.bubble_width-52)
        self.bubble_line_height=QFontMetrics(self.bubble_font).height()+3
        self.bubble_footer_font=font(opts['font_family'],max(13,opts['ui_font_size']-3))
        footer_metrics=QFontMetrics(self.bubble_footer_font)
        self.bubble_footer_lines=wrap_text('双击互动 · 右键自定义',footer_metrics,self.bubble_width-52)
        self.bubble_footer_height=footer_metrics.height()+2
        self.bubble_divider_y=self.bubble_body_top+self.bubble_line_height*len(self.bubble_lines)+7
        bubble_height=self.bubble_divider_y+8+self.bubble_footer_height*len(self.bubble_footer_lines)
        self.bubble_rect=QRectF(10,12,self.bubble_width-20,bubble_height)
        # Dialogue grows vertically without truncating or shrinking the font.
        self.bubble_window.resize(bubble_pixels,math.ceil((bubble_height+38)*self.bubble_scale))
        neww,newh=round(width*self.scale_factor),round(height*self.scale_factor)
        if self.width()!=neww or self.height()!=newh:
            bottom=self.y()+self.height(); center=self.x()+self.width()/2; self.resize(neww,newh)
            if getattr(self,'position_ready',False): self.move(round(center-neww/2),bottom-newh); self.clamp_position()
        self.setToolTip(self.quota_details()); self.update_bubble(); self.size_changed.emit()

    def update_bubble(self):
        if not hasattr(self,'bubble_rect'): return
        bubble=self.bubble_window
        if not self.isVisible() or not self.bubble_visible(): bubble.hide(); return
        center=self.mapToGlobal((self.pet_rect.center()*self.scale_factor).toPoint())
        area=self.screen_area()
        x=self.x()+self.bubble_left
        y=self.y()-bubble.height()-4; above=y>=area.top()
        if not above: y=min(area.bottom()-bubble.height()+1,self.y()+self.height()+4)
        y=max(area.top(),y)
        bubble.above=above; bubble.arrow_x=(center.x()-x)/self.bubble_scale
        bubble.move(x,y); bubble.show(); bubble.update()

    def bubble_visible(self):
        b=self.bubble_binding(); elapsed=time.monotonic()-self.controller.started
        if b['bubble_mode']=='off': return False
        if self.voice_bubble(): return True
        if b['bubble_mode']=='audio': return False
        if b['bubble_seconds'] and elapsed>=b['bubble_seconds']: return False
        return not self.quiet or self.controller.owner=='preview' or self.state in MANUAL|{'done','error','waiting'} or b['bubble_mode']=='custom'

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform); p.scale(self.scale_factor,self.scale_factor)
        opts=self.options; width=self.scene_width; b=self.binding(self.state)
        elapsed=(time.monotonic()-self.controller.started)*1000
        frame=self.animation.frame(elapsed*b['speed'],playback='once' if self.preview_id else b['playback'])
        fraction=(time.monotonic()-self.transition_start)/.20
        if self.transition_old is not None and fraction<1:
            p.setOpacity(1-fraction*2 if fraction<.5 else (fraction-.5)*2); shown=self.transition_old if fraction<.5 else frame; p.drawImage(self.image_rect(shown),shown)
        else: self.transition_old=None; p.drawImage(self.image_rect(frame),frame)
        p.setOpacity(1); self.last_image=frame
        bar=self.quota_rect
        windows=self.quota_data.get('windows') or []; remaining=min((w['remaining'] for w in windows),default=0)
        low=windows and remaining<20; border='#a67125' if low else '#4276ad'; fill='#d99032' if low else '#397cc3'
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(20,43,77,50)); p.drawRoundedRect(bar.translated(0,2),11,11)
        p.setPen(QPen(QColor(border),1.6)); p.setBrush(QColor('#fff4de' if low else '#edf5ff')); p.drawRoundedRect(bar,11,11)
        track=QRectF(bar.left()+11,bar.bottom()-9,bar.width()-22,4)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#c1d3e7')); p.drawRoundedRect(track,2,2)
        if windows:
            p.setBrush(QColor(fill)); p.drawRoundedRect(QRectF(track.left(),track.top(),track.width()*max(0,min(100,remaining))/100,track.height()),2,2)
        p.setFont(self.quota_font); p.setPen(QColor('#744d13' if low else '#204e7d'))
        label=QFontMetrics(self.quota_font).elidedText(self.quota_label(compact=True),Qt.TextElideMode.ElideRight,round(bar.width()-18))
        p.drawText(QRectF(bar.left()+9,bar.top()+3,bar.width()-18,bar.height()-14),Qt.AlignmentFlag.AlignCenter,label); p.end()
