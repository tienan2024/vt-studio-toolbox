import sys
from pathlib import Path
import time
import unittest
from dataclasses import fields
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from PySide6.QtWidgets import QApplication,QStyle,QStyleOptionSpinBox
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from camera_model import CameraSettings
from camera_transaction import compare,apply_comparison
from test_camera import FakeCamera
from toolbox import ToolboxWindow


class CameraDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def wait(self,page):
        end=time.monotonic()+10
        while page.is_busy() and time.monotonic()<end:self.app.processEvents();time.sleep(.01)
        self.app.processEvents();self.assertFalse(page.is_busy(),page.message.text())

    def test_fourth_page_offline_calculation_and_area_fields(self):
        w=ToolboxWindow();p=w.camera
        try:
            w.select_page(3);self.assertTrue(w.camera_nav.isChecked());self.assertEqual(w.pages.count(),4)
            self.assertEqual(set(p.controls),{f.name for f in fields(CameraSettings)});self.assertEqual(p.plan['metrics']['lines_per_product'],3000)
            self.assertFalse(p.write_button.isEnabled())
            s=CameraSettings(kind='area',target_length_mm=120,frame_selector='FrameStart');p.load_settings(s)
            self.assertFalse(p.controls['ppr'].isEnabled());self.assertTrue(p.controls['sensor_height'].isEnabled())
            self.assertIsNone(p.plan['metrics']['lines_per_product']);self.assertFalse(p.plan['blocking'])
        finally:w.close();self.app.processEvents()

    def test_simple_default_and_reveal_settings_details_and_camera_actions(self):
        w=ToolboxWindow();w.show();w.select_page(3);p=w.camera;self.app.processEvents()
        try:
            self.assertEqual(p.metrics.rowCount(),5);self.assertFalse(p.form_tabs.isTabVisible(1))
            self.assertGreaterEqual(p.metrics.viewport().height(),sum(p.metrics.rowHeight(i) for i in range(5)))
            self.assertTrue(p.devices_bar.isHidden());self.assertTrue(p.device_actions.isHidden());self.assertTrue(p.tabs.isHidden())
            self.assertFalse(p.controls['target_width_mm'].isHidden());self.assertTrue(p.controls['focal_length_mm'].isHidden())
            p.advanced_button.click();self.assertTrue(p.form_tabs.isTabVisible(1));self.assertEqual(p.form_tabs.currentIndex(),1)
            p.advanced_button.click();self.assertEqual(p.form_tabs.currentIndex(),0)
            p.details_button.click();self.assertFalse(p.tabs.isHidden());self.assertTrue(p.frame_preview.isHidden())
            p.connection_button.click();self.assertFalse(p.devices_bar.isHidden());self.assertFalse(p.device_actions.isHidden())
            self.assertNotIn('product_pitch_mm',p.controls);self.assertNotIn('allow_overheight',p.controls)
            s=CameraSettings(target_length_mm=280,image_vertical_margin_mm=10)
            p.load_settings(s);self.assertEqual(p.plan['metrics']['height'],2900)
            self.assertEqual(p.metrics.item(2,1).text(),'100')
            p.controls['precision_source'].setCurrentIndex(p.controls['precision_source'].findData('optics'));p.recalculate()
            self.assertIsNone(p.plan);self.assertEqual(p.metrics.rowCount(),0)
            self.assertFalse(p.controls['focal_length_mm'].isHidden());self.assertTrue(p.controls['fov_width_mm'].isHidden())
            p.controls['focal_length_mm'].setValue(25);p.controls['pixel_pitch_um'].setValue(7);p.recalculate()
            self.assertIsNotNone(p.plan);self.assertAlmostEqual(p.plan['metrics']['x_mm_per_px'],.112)
        finally:w.close();self.app.processEvents()

    def test_styled_controls_keep_popup_selection_and_distinct_plus_minus_hit_targets(self):
        w=ToolboxWindow();w.show();w.select_page(3);p=w.camera;self.app.processEvents()
        try:
            p.advanced_button.click();self.app.processEvents()
            combo=p.controls['precision_source'];combo.showPopup();self.app.processEvents()
            self.assertTrue(combo.view().isVisible());self.assertGreaterEqual(combo.view().sizeHintForRow(0),32)
            QTest.keyClick(combo,Qt.Key.Key_Down);QTest.keyClick(combo,Qt.Key.Key_Return);self.app.processEvents()
            self.assertEqual(combo.currentData(),'precision');p.recalculate()
            spin=p.controls['target_width_mm'];option=QStyleOptionSpinBox();spin.initStyleOption(option)
            up=spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,option,QStyle.SubControl.SC_SpinBoxUp,spin)
            down=spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,option,QStyle.SubControl.SC_SpinBoxDown,spin)
            self.assertFalse(up.intersects(down));self.assertTrue(spin.rect().contains(up));self.assertTrue(spin.rect().contains(down))
            before=spin.value();QTest.mouseClick(spin,Qt.MouseButton.LeftButton,pos=up.center())
            self.assertEqual(spin.value(),before+spin.singleStep())
            QTest.mouseClick(spin,Qt.MouseButton.LeftButton,pos=down.center());self.assertEqual(spin.value(),before)
            self.assertEqual({p.controls[key].height() for key in ('kind','target_width_mm','precision_source')},{36})
        finally:w.close();self.app.processEvents()

    def test_product_calibration_height_and_old_config_confirmation(self):
        from camera_model import settings_from_dict
        w=ToolboxWindow();w.show();w.select_page(3);p=w.camera
        try:
            s=CameraSettings(line_y_source='calibration',calibration_length_mm=280,calibration_rows=2800,
                target_length_mm=280,image_vertical_margin_mm=10,ppr=2000,products_per_minute=400)
            p.load_settings(s);m=p.plan['metrics']
            self.assertAlmostEqual(m['y_mm_per_px'],.1);self.assertEqual(m['product_height_lines'],2800)
            self.assertEqual(m['height'],2900);self.assertEqual(m['line_triggers_per_cycle'],6000)
            self.assertFalse(p.plan['blocking'])
            p.controls['height_override'].setValue(3200);p.recalculate()
            self.assertEqual(p.plan['metrics']['product_height_lines'],2800)
            self.assertEqual(p.metrics.item(2,1).text(),'400')
            old=settings_from_dict({'schema':'vt-camera-config/1','product_pitch_mm':300,'image_top_margin_mm':5,'image_bottom_margin_mm':7})
            p.load_settings(old);self.assertEqual(p.settings().line_y_source,'legacy');self.assertTrue(p.plan['blocking'])
            p.controls['line_y_source'].setCurrentIndex(p.controls['line_y_source'].findData('precision'));p.recalculate()
            self.assertEqual(p.settings().line_y_source,'precision')
            self.assertFalse(any('旧配置' in b for b in p.plan['blocking']))
        finally:w.close();self.app.processEvents()

    def test_compare_invalidation_background_write_and_close_protection(self):
        w=ToolboxWindow();w.show();w.select_page(3);p=w.camera;camera=FakeCamera()
        try:
            p.device.addItem('SIMULATED CAMERA',camera.device['uid']);p.device.setCurrentIndex(1)
            with patch('camera_ui.preview_camera',side_effect=lambda uid,s,sdk:compare(camera,s)):
                p.start_job('compare');self.wait(p)
            self.assertTrue(p.write_button.isEnabled());self.assertEqual(p.compare_table.rowCount(),len(p.plan['nodes']))
            p.controls['gain'].setValue(1.2);self.assertFalse(p.write_button.isEnabled());p.recalculate()
            with patch('camera_ui.preview_camera',side_effect=lambda uid,s,sdk:compare(camera,s)):
                p.start_job('compare');self.wait(p)
            with patch('camera_ui.write_camera',side_effect=lambda report,sdk,progress:apply_comparison(camera,report,progress)):
                p.start_write();self.assertTrue(p.is_busy());self.assertFalse(p.files_button.isEnabled());self.assertFalse(p.connection_button.isEnabled())
                w.close();self.assertTrue(w.isVisible());self.wait(p)
            self.assertEqual(p.last_report['status'],'passed');self.assertFalse(p.write_button.isEnabled())
            self.assertIn('UserSet1',p.message.text());self.assertTrue(p.form_panel.isEnabled())
            self.assertTrue(p.files_button.isEnabled());self.assertTrue(p.connection_button.isEnabled())
        finally:w.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
