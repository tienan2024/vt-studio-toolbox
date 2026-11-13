import copy
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from script_generator import default_config,generate_sources,validate_config,run_cases,run_regression,ScriptError,variable_rows
from script_ui import ScriptPage
from test_sol_reader import fixture


class EditablePortTests(unittest.TestCase):
    def test_renamed_inputs_array_and_outputs_execute_the_actual_csharp(self):
        c=default_config();c['ports']={'aiResult':'AI总结果','Label_name':'类别数组','NGtype':'类型列表','speed':'线速','outResult_index':'结果位串','NG_saveImg':'存图开关'}
        c['variable_notes']={'aiResult':'来自上游的AI总判断'}
        result=run_cases(c,[{'AI总结果':0,'类别数组':['污点','接头']}])['results'][0]
        self.assertEqual(result['outputs']['结果位串'],'0|0|1|1|1');self.assertEqual(result['outputs']['存图开关'],1)
        self.assertEqual(result['label_read_calls'],1)
        report=run_regression(c);self.assertEqual(report['passed'],report['total'])
        self.assertEqual(variable_rows(c)[0]['note'],'来自上游的AI总判断')
        c['use_ai']=False;self.assertEqual(run_cases(c,[{'AI总结果':0}])['results'][0]['label_read_calls'],0)

    def test_names_are_validated_and_data_literals_are_not_renamed(self):
        for ports in ({'aiResult':'class'},{'aiResult':'speed'},{'aiResult':'types'},{'aiResult':'重复','speed':'重复'}, {'aiResult':'全局小污点Result'}):
            c=default_config();c['ports']=ports
            with self.assertRaises(ScriptError):validate_config(c)
        c=default_config();c['ports']={'NG_name':'名称输出'};c['aliases']=[{'match':'exact','value':'NG_name','type':'污点'}]
        source=generate_sources(c)['UserScript.cs']
        self.assertIn('label == "NG_name"',source);self.assertIn('名称输出 = finalName',source)


class VariablePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_edit_sync_preserves_regions_and_groups_and_rejects_duplicate(self):
        p=ScriptPage();panel=p.variables
        try:
            self.assertEqual(panel.tables['输入'].rowCount(),8);self.assertEqual(panel.tables['输出'].rowCount(),4)
            p.previous=p.sources['UserScript.cs'];panel.tables['输入'].item(0,1).setText('AI总结果')
            self.assertEqual(p.config['ports']['aiResult'],'AI总结果');self.assertIsNotNone(p.previous)
            self.assertIn('AI总结果 == 0',p.sources['UserScript.cs'])
            panel.tables['输出'].item(0,1).setText('位串');self.assertIn('位串 = string.Join',p.sources['UserScript.cs'])
            panel.tables['输入'].item(1,1).setText('AI总结果')
            self.assertEqual(panel.tables['输入'].item(1,1).text(),'NGtype')
            panel.tables['输入'].item(5,1).setText('新污点Result')
            self.assertEqual(p.config['signals'][0]['name'],'新污点Result');self.assertIn('新污点Result == 0',p.sources['UserScript.cs'])
            self.assertEqual(p.current_case()['AI总结果'],1)
            self.assertFalse(panel.tables['输入'].item(0,2).flags() & Qt.ItemFlag.ItemIsEditable)
            c=copy.deepcopy(p.config);p.load_config(default_config());p.load_config(c)
            self.assertEqual(panel.tables['输出'].item(0,1).text(),'位串')
        finally:p.deleteLater();self.app.processEvents()

    def test_background_sol_read_flow_selection_and_reference_is_readonly(self):
        p=ScriptPage();panel=p.variables
        try:
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'example.sol';fixture(path);before=path.read_bytes();panel.start_read(str(path))
                deadline=time.monotonic()+5
                while panel.is_busy() and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
                self.assertFalse(panel.is_busy());self.assertEqual(panel.flow.currentText(),'Inspection')
                self.assertEqual(panel.tables['输入'].rowCount(),2);self.assertEqual(panel.tables['输出'].rowCount(),1)
                self.assertFalse(panel.tables['输入'].item(0,1).flags() & Qt.ItemFlag.ItemIsEditable)
                self.assertEqual(path.read_bytes(),before)
                panel.source.setCurrentIndex(0);self.assertEqual(panel.tables['输入'].rowCount(),8)
        finally:p.deleteLater();self.app.processEvents()

    def test_sol_password_cancel_and_product_signal_application(self):
        p=ScriptPage();panel=p.variables
        try:
            with patch('script_variables.QInputDialog.getText',return_value=('',False)):
                class Job:
                    def deleteLater(self):pass
                panel.job=Job();panel.pending_password=True;panel.read_stopped();self.assertIn('取消',panel.status.text())
            rows=variable_rows(default_config());module={'flow':'Test','name':'Script','inputs':[r for r in rows if r['direction']=='输入' and r['name']!='aiResult'],
                'outputs':[r for r in rows if r['direction']=='输出']}
            p.apply_sol_module(module,{r['name']:r['type'] for r in default_config()['signals']})
            self.assertFalse(p.config['use_ai']);self.assertEqual(len(p.config['signals']),3)
            self.assertEqual(len([r for r in variable_rows(p.config) if r['direction']=='输入']),8)
        finally:p.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()
