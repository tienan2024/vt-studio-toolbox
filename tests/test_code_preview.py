from pathlib import Path
import sys
import unittest
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from code_preview import CSharpPreview,COLORS


class CSharpPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def color(self,view,line,word):
        block=view.document().findBlockByNumber(line);text=block.text()
        pos=len(text[:text.index(word)].encode('utf-16-le'))//2
        for run in block.layout().formats():
            if run.start<=pos<run.start+run.length:return run.format.foreground().color().name()
        return None

    def test_csharp_lexical_colors_and_multiline_states(self):
        text='''public class Sample {
  public bool Process() { var text = "😀 // literal"; return true; }
  // return false;
  /* comment
     public int fake = 7;
  */ var path = @"first
     // verbatim ""quote""
  last"; return false;
  var raw = """first
  // raw literal
  last"""; int number = 0xFF + 2.5f;
#region product
}'''
        view=CSharpPreview();view.set_source(text);view.highlighter.rehighlight()
        for line,word,role in ((0,'public','keyword'),(0,'Sample','type'),(1,'Process','method'),
            (1,'return','control'),(1,'true','keyword'),(1,'😀','string'),(2,'return','comment'),
            (4,'public','comment'),(6,'verbatim','string'),(7,'return','control'),
            (9,'raw literal','string'),(10,'0xFF','number'),(10,'2.5f','number'),(11,'#region','directive')):
            self.assertEqual(self.color(view,line,word),COLORS[role],(line,word))
        self.assertEqual(view.toPlainText(),text);view.close()

    def test_readonly_gutter_scroll_and_plain_text_copy(self):
        view=CSharpPreview();view.resize(700,400);view.show()
        text='\n'.join('int value'+str(i)+' = '+str(i)+'; // 测试' for i in range(240))
        view.set_source(text);self.app.processEvents()
        self.assertTrue(view.isReadOnly());self.assertGreater(view.line_numbers.width(),20)
        self.assertEqual(view.blockCount(),240)
        view.verticalScrollBar().setValue(100);position=view.verticalScrollBar().value()
        view.set_source(text);self.assertEqual(view.verticalScrollBar().value(),position)
        view.selectAll();view.copy();self.assertEqual(self.app.clipboard().text(),text)
        self.assertEqual(len(view.extraSelections()),1);view.close()
