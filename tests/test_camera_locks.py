import sys,unittest
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QAbstractSpinBox
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from toolbox import ToolboxWindow
from camera_model import workflow_settings


class CameraFixedValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.w=ToolboxWindow();self.w.show();self.w.select_page(3);self.p=self.w.camera
        for _ in range(8):self.app.processEvents()

    def tearDown(self):self.w.close();self.app.processEvents()

    def pin(self,key):
        QTest.mouseClick(self.p.lock_buttons[key],Qt.MouseButton.LeftButton)
        for _ in range(6):self.app.processEvents()

    def test_fixed_distance_blocks_edit_and_changes_only_free_margin(self):
        p=self.p;wd=p.controls['working_distance_mm'];fixed=wd.value()
        self.assertEqual(wd.buttonSymbols(),QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.assertNotEqual(p.controls['ppr'].buttonSymbols(),QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.pin('working_distance_mm');self.assertTrue(wd.isReadOnly())
        wd.setFocus();wd.selectAll();QTest.keyClicks(wd,'250');QTest.keyClick(wd,Qt.Key.Key_Return)
        self.assertEqual(wd.value(),fixed)
        wd.stepUp();self.assertEqual(wd.value(),fixed)
        wd.setValue(250);self.assertEqual(wd.value(),fixed)
        p.controls['target_width_mm'].setValue(210);p.recalculate()
        self.assertIsNotNone(p.plan,p.message.text());self.assertEqual(wd.value(),fixed)
        self.assertAlmostEqual(p.controls['horizontal_margin_percent'].value(),4.76,places=2)
        self.assertEqual(p.settings().framing_source,'distance')
        self.pin('working_distance_mm');self.assertFalse(wd.isReadOnly())
        wd.setValue(200);p.recalculate();self.assertEqual(wd.value(),200)

    def test_fixed_distance_and_margin_solve_free_material_width(self):
        p=self.p;self.pin('working_distance_mm');self.pin('horizontal_margin_percent')
        fixed=dict(p.fixed_values)
        p.controls['target_width_mm'].setValue(250);p.recalculate()
        self.assertIsNotNone(p.plan,p.message.text())
        self.assertAlmostEqual(p.controls['target_width_mm'].value(),200,places=3)
        for key,value in fixed.items():self.assertEqual(p.controls[key].value(),value)
        self.pin('working_distance_mm');p.controls['working_distance_mm'].setValue(200);p.recalculate()
        self.assertAlmostEqual(p.controls['target_width_mm'].value(),217.212,places=3)
        self.assertEqual(p.controls['horizontal_margin_percent'].value(),fixed['horizontal_margin_percent'])

    def test_conflicting_fixed_values_never_change_and_unlock_recovers(self):
        p=self.p
        for key in ('working_distance_mm','horizontal_margin_percent','target_width_mm'):self.pin(key)
        fixed=dict(p.fixed_values)
        p.controls['optics_method'].setCurrentIndex(p.controls['optics_method'].findData('thin_lens'));p.recalculate()
        self.assertIsNone(p.plan);self.assertIn('固定值冲突',p.message.text())
        self.assertFalse(p.write_button.isEnabled())
        for key,value in fixed.items():self.assertEqual(p.controls[key].value(),value)
        self.pin('horizontal_margin_percent');self.assertIsNotNone(p.plan,p.message.text())
        for key in ('working_distance_mm','target_width_mm'):self.assertEqual(p.controls[key].value(),fixed[key])
        p.geometry={'limits':{key:{'min':1,'max':1,'inc':1} for key in ('PreDivider','Multiplier','PostDivider')}}
        p.recalculate();self.assertIsNone(p.plan)
        self.assertNotIn('固定值冲突',p.message.text())

    def test_camera_change_preserves_fixed_distance_and_explicit_load_resets_locks(self):
        p=self.p;self.pin('working_distance_mm');fixed=p.controls['working_distance_mm'].value()
        p.camera_type.setCurrentIndex(p.camera_type.findData('line4k'));p.recalculate()
        self.assertEqual(p.controls['working_distance_mm'].value(),fixed)
        self.assertTrue(p.controls['working_distance_mm'].isReadOnly())
        self.assertIsNotNone(p.plan,p.message.text())
        p.language_box.setCurrentIndex(p.language_box.findData('en'))
        self.assertTrue(p.lock_buttons['working_distance_mm'].isChecked())
        self.assertIn('Unlock',p.lock_buttons['working_distance_mm'].accessibleName())
        settings=workflow_settings();settings.target_width_mm=300;p.load_settings(settings)
        self.assertEqual(p.fixed_values,{})
        self.assertFalse(p.controls['working_distance_mm'].isReadOnly())
        self.assertFalse(p.lock_buttons['working_distance_mm'].isChecked())


if __name__=='__main__':unittest.main()
