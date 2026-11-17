import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from script_ui import ScriptPage
from script_generator import ScriptError,variable_rows

class MissingPortTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_module_with_no_fixed_ports_can_generate_complete_template(self):
        page=ScriptPage()
        try:
            module={'flow':'Test','name':'Script','inputs':[{'name':'检测Result','type':'int'}],'outputs':[]}
            page.apply_sol_module(module,{'检测Result':'污点'})
            rows=variable_rows(page.config)
            self.assertEqual(len([r for r in rows if r['direction']=='输入']),6)
            self.assertEqual(len([r for r in rows if r['direction']=='输出']),4)
            self.assertFalse(page.config['use_ai']);self.assertEqual(page.config['signals'][0]['name'],'检测Result')
        finally:page.deleteLater();self.app.processEvents()

    def test_conflicting_types_and_unknown_existing_outputs_still_rejected(self):
        page=ScriptPage()
        try:
            with self.assertRaises(ScriptError):page.sol_signals({'inputs':[{'name':'aiResult','type':'float'}],'outputs':[]})
            with self.assertRaises(ScriptError):page.sol_signals({'inputs':[],'outputs':[{'name':'旧输出','type':'string'}]})
        finally:page.deleteLater();self.app.processEvents()

if __name__=='__main__':unittest.main()
