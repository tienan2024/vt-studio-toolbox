import sys
import unittest
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from toolbox import ToolboxWindow
from camera_ui import ConditionForm
from camera_model import config_dict


class CameraConditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.w=ToolboxWindow();self.w.resize(1180,760);self.w.show();self.w.select_page(3);self.p=self.w.camera
        for _ in range(8):self.app.processEvents()

    def tearDown(self):self.w.close();self.app.processEvents()

    def test_typed_inputs_recalculate_and_reverse_known_conditions(self):
        p=self.p;controls=p.controls
        self.assertIsInstance(p.field_forms['target_width_mm'],ConditionForm)
        self.assertEqual(p.plan['metrics']['height'],3800)
        self.assertEqual(p.target_fov_fields['target_fov_width_mm'].text(),'220.000')
        self.assertEqual(p.target_fov_fields['target_fov_height_mm'].text(),'408.000')
        self.assertTrue(p.target_fov_fields['target_fov_height_mm'].isReadOnly())
        self.assertFalse(controls['working_distance_mm'].isEnabled())
        field=controls['target_width_mm'];field.setFocus();field.selectAll()
        QTest.keyClicks(field,'300');QTest.keyClick(field,Qt.Key.Key_Tab);QTest.qWait(220)
        self.assertAlmostEqual(p.plan['metrics']['fov_width_mm'],330)
        self.assertAlmostEqual(p.plan['metrics']['working_distance_mm'],330*12/14.336,places=3)
        direction=controls['framing_source'];direction.setCurrentIndex(direction.findData('distance'))
        QTest.qWait(220)
        self.assertTrue(controls['working_distance_mm'].isEnabled())
        self.assertFalse(controls['horizontal_margin_percent'].isEnabled())
        controls['target_width_mm'].setValue(200);controls['working_distance_mm'].setValue(200)
        QTest.qWait(220)
        self.assertAlmostEqual(p.plan['metrics']['fov_width_mm'],200*14.336/12,places=3)
        self.assertAlmostEqual(controls['horizontal_margin_percent'].value(),19.47,places=2)
        self.assertFalse(p.write_button.isEnabled())
        controls['vertical_margin_percent'].setValue(10);QTest.qWait(220)
        self.assertEqual(p.target_fov_fields['target_fov_height_mm'].text(),'440.000')
        self.assertGreaterEqual(p.plan['metrics']['coverage_height_mm'],440)

    def test_compact_panel_model_switch_and_language_keep_configuration(self):
        p=self.p
        self.assertLess(p.form_tabs.height(),500)
        self.assertLessEqual(p.advanced_button.y()-p.form_tabs.geometry().bottom(),14)
        self.assertLess(p.advanced_button.geometry().bottom(),p.form_panel.height())
        for widget,cell,_ in p.parameter_form.entries:
            if widget.isVisible():self.assertLessEqual(widget.geometry().bottom(),cell.height())
        p.camera_type.setCurrentIndex(p.camera_type.findData('area5mp'));p.recalculate()
        self.assertFalse(p.form_tabs.isTabVisible(1));self.assertTrue(p.line_trigger_group.isHidden())
        before=config_dict(p.settings())
        p.language_box.setCurrentIndex(p.language_box.findData('en'))
        for _ in range(6):self.app.processEvents()
        self.assertEqual(before,config_dict(p.settings()))
        self.assertEqual(p.labels['target_width_mm'].text(),'Product width / mm')
        p.advanced_button.click()
        self.assertEqual(p.form_tabs.currentIndex(),4)
        self.assertTrue(p.form_tabs.isTabVisible(3))
        p.advanced_button.click()
        self.assertEqual(p.form_tabs.currentIndex(),0)


if __name__=='__main__':unittest.main()
