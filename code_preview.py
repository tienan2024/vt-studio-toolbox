"""Read-only C# preview: lexical highlighting, line numbers and stable scrolling."""
import re

from PySide6.QtCore import Qt,QSize,QRect
from PySide6.QtGui import (QColor,QFont,QPainter,QSyntaxHighlighter,QTextCharFormat,
                          QTextFormat,QTextCursor)
from PySide6.QtWidgets import QPlainTextEdit,QWidget,QTextEdit

COLORS={'keyword':'#569cd6','control':'#c586c0','type':'#4ec9b0',
        'method':'#dcdcaa','string':'#ce9178','number':'#b5cea8',
        'comment':'#82ad6e','directive':'#c586c0','identifier':'#9cdcfe'}
KEYWORDS=set('abstract as base bool byte char checked class const decimal default delegate double enum event explicit extern false fixed float implicit in int interface internal is lock long namespace new null object operator out override params private protected public readonly ref sbyte sealed short sizeof stackalloc static string struct this true typeof uint ulong unchecked unsafe ushort using virtual void volatile async await var dynamic partial get set value record init required file global not and or with unmanaged nameof'.split())
CONTROL=set('break case catch continue do else finally for foreach goto if return switch throw try while yield'.split())
TYPES=set('Array DateTime List Dictionary HashSet Math Convert Exception String Boolean Int32 Int64 Single Double StringBuilder StringComparison UserScript ScriptMethods IProcessMethods'.split())
IDENTIFIER=re.compile(r'(?<![\w@])@?(?:[^\W\d]|_)\w*',re.UNICODE)
NUMBER=re.compile(r'(?<![\w])(?:0[xX][\da-fA-F_]+|0[bB][01_]+|(?:\d[\d_]*(?:\.[\d_]+)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?)[fFdDmMuUlL]*(?!\w)')


class CSharpHighlighter(QSyntaxHighlighter):
    def __init__(self,document):
        super().__init__(document);self.formats={}
        for role,color in COLORS.items():
            fmt=QTextCharFormat();fmt.setForeground(QColor(color));self.formats[role]=fmt

    def highlightBlock(self,text):
        # QTextDocument positions are UTF-16, unlike Python's Unicode indexes.
        offsets=[0]
        for char in text:offsets.append(offsets[-1]+(2 if ord(char)>0xffff else 1))
        def paint(start,end,role):
            self.setFormat(offsets[start],offsets[end]-offsets[start],self.formats[role])
        def plain(start,end):
            part=text[start:end]
            if part.lstrip().startswith('#'):
                paint(start,end,'directive');return
            for match in NUMBER.finditer(part):paint(start+match.start(),start+match.end(),'number')
            for match in IDENTIFIER.finditer(part):
                word=match.group();a=start+match.start();b=start+match.end()
                if word in CONTROL:role='control'
                elif word in KEYWORDS:role='keyword'
                elif word in TYPES or re.search(r'\b(?:class|struct|interface|enum|record|new)\s+$',text[start:a]):role='type'
                elif re.match(r'\s*(?:<[^;{}]*?>\s*)?\(',text[b:end]):role='method'
                else:role='identifier'
                paint(a,b,role)

        state=max(0,self.previousBlockState());self.setCurrentBlockState(0)
        i=0;normal_start=0;length=len(text)
        while i<length:
            if state==1 or text.startswith('/*',i):
                plain(normal_start,i);start=i
                end=text.find('*/',i if state==1 else i+2)
                if end<0:paint(start,length,'comment');self.setCurrentBlockState(1);return
                i=end+2;paint(start,i,'comment');state=0;normal_start=i;continue
            if state==2:
                start=i
                while i<length:
                    if text.startswith('""',i):i+=2
                    elif text[i]=='"':i+=1;state=0;break
                    else:i+=1
                paint(start,i,'string');normal_start=i
                if state:self.setCurrentBlockState(2);return
                continue
            if state>=1000:
                end=text.find('"'*(state-1000),i)
                if end<0:paint(i,length,'string');self.setCurrentBlockState(state);return
                end+=state-1000;paint(i,end,'string');i=end;normal_start=i;state=0;continue
            if text.startswith('//',i):
                plain(normal_start,i);paint(i,length,'comment');return
            raw=re.match(r'\$*("{3,})',text[i:]) if text[i] in '$"' else None
            if raw:
                plain(normal_start,i);start=i;delimiter=len(raw.group(1));i+=len(raw.group())
                end=text.find('"'*delimiter,i)
                if end<0:paint(start,length,'string');self.setCurrentBlockState(1000+delimiter);return
                i=end+delimiter;paint(start,i,'string');normal_start=i;continue
            prefix=next((p for p in ('$@"','@$"','@"','$"','"',"'") if text.startswith(p,i)),None)
            if prefix:
                plain(normal_start,i);start=i;i+=len(prefix)
                verbatim='@' in prefix;quote=prefix[-1];closed=False
                while i<length:
                    if verbatim and text.startswith('""',i):i+=2
                    elif not verbatim and text[i]=='\\':i=min(length,i+2)
                    elif text[i]==quote:i+=1;closed=True;break
                    else:i+=1
                paint(start,i,'string');normal_start=i
                if verbatim and not closed:self.setCurrentBlockState(2);return
                continue
            i+=1
        plain(normal_start,length)
        # Empty lines inside multiline literals/comments must retain their state.
        if state:self.setCurrentBlockState(state)


class LineNumbers(QWidget):
    def __init__(self,editor):super().__init__(editor);self.editor=editor
    def sizeHint(self):return QSize(self.editor.number_width(),0)
    def paintEvent(self,event):self.editor.paint_numbers(event)


class CSharpPreview(QPlainTextEdit):
    def __init__(self,parent=None):
        super().__init__(parent);self.setObjectName('CSharpPreview')
        self.setReadOnly(True);self.setFont(QFont('Consolas',10));self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet('QPlainTextEdit#CSharpPreview { background:#1c2735; color:#d3dce8; border:0; padding:8px; font-family:Consolas,monospace; font-size:13px; selection-background-color:#354f6b; selection-color:#ffffff; }')
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ')*4)
        self.line_numbers=LineNumbers(self);self.highlighter=CSharpHighlighter(self.document())
        self.blockCountChanged.connect(self.update_margin);self.updateRequest.connect(self.update_numbers)
        self.cursorPositionChanged.connect(self.current_line);self.update_margin();self.current_line()

    def number_width(self):return 18+self.fontMetrics().horizontalAdvance(str(max(1,self.blockCount())))

    def update_margin(self,*args):
        if self.viewportMargins().left()!=self.number_width():self.setViewportMargins(self.number_width(),0,0,0)
        self.position_numbers()

    def update_numbers(self,rect,dy):
        if dy:self.line_numbers.scroll(0,dy)
        else:self.line_numbers.update(0,rect.y(),self.number_width(),rect.height())
        if rect.contains(self.viewport().rect()):self.update_margin()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.position_numbers()

    def position_numbers(self):
        viewport=self.viewport().geometry()
        self.line_numbers.setGeometry(QRect(self.contentsRect().left(),viewport.top(),self.number_width(),viewport.height()))

    def current_line(self):
        selection=QTextEdit.ExtraSelection();selection.format.setBackground(QColor('#253447'))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection,True)
        selection.cursor=self.textCursor();selection.cursor.clearSelection();self.setExtraSelections([selection])
        if hasattr(self,'line_numbers'):self.line_numbers.update()

    def paint_numbers(self,event):
        painter=QPainter(self.line_numbers);painter.fillRect(event.rect(),QColor('#172332'));painter.setFont(self.font())
        block=self.firstVisibleBlock();number=block.blockNumber()
        top=int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        current=self.textCursor().blockNumber()
        while block.isValid() and top<=event.rect().bottom():
            height=int(self.blockBoundingRect(block).height())
            if block.isVisible() and top+height>=event.rect().top():
                painter.setPen(QColor('#d3dce8' if number==current else '#899bad'))
                painter.drawText(0,top,self.line_numbers.width()-8,self.fontMetrics().height(),Qt.AlignmentFlag.AlignRight,str(number+1))
            block=block.next();number+=1;top+=height

    def set_source(self,text):
        if self.toPlainText()==text:return
        vertical=self.verticalScrollBar().value();horizontal=self.horizontalScrollBar().value()
        position=self.textCursor().position()
        self.setPlainText(text)
        cursor=QTextCursor(self.document());cursor.setPosition(min(position,self.document().characterCount()-1));self.setTextCursor(cursor)
        self.verticalScrollBar().setValue(vertical);self.horizontalScrollBar().setValue(horizontal)
