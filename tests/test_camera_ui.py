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
            self.assertEqual(set(p.controls),{f.name for f in fields(CameraSettings)});self.assertEqual(p.plan['metrics']['lines_per_product'],4000)
            self.assertFalse(p.write_button.isEnabled())
            s=CameraSettings(kind='area',target_length_mm=120,frame_selector='FrameStart');p.load_settings(s)
            self.assertFalse(p.controls['ppr'].isEnabled());self.assertTrue(p.controls['sensor_height'].isEnabled())
            self.assertIsNone(p.plan['metrics']['lines_per_product']);self.assertFalse(p.plan['blocking'])
        finally:w.close();self.app.processEvents()

    def test_simple_default_and_reveal_settings_details_and_camera_actions(self):
        w=ToolboxWindow();w.show();w.select_page(3);p=w.camera;self.app.processEvents()
        try:
            self.assertEqual(p.metrics.rowCount(),7);self.assertFalse(p.form_tabs.isTabVisible(p.basic_tab_count))
            self.assertGreaterEqual(p.metrics.viewport().height(),sum(p.metrics.rowHeight(i) for i in range(7)))
            # Qt frame borders may share up to two logical pixels at fractional DPI.
            self.assertLessEqual(p.metrics.geometry().bottom(),p.optics_summary.geometry().top()+2)
            self.assertTrue(p.devices_bar.isHidden());self.assertTrue(p.device_actions.isHidden());self.assertTrue(p.tabs.isHidden())
            self.assertFalse(p.controls['target_width_mm'].isHidden());self.assertTrue(p.controls['focal_length_mm'].isHidden())
            p.advanced_button.click();self.assertTrue(p.form_tabs.isTabVisible(p.basic_tab_count));self.assertEqual(p.form_tabs.currentIndex(),4)
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
            combo=p.controls['framing_source'];combo.showPopup();self.app.processEvents()
            self.assertTrue(combo.view().isVisible());self.assertGreaterEqual(combo.view().sizeHintForRow(0),32)
            QTest.keyClick(combo,Qt.Key.Key_Down);QTest.keyClick(combo,Qt.Key.Key_Return);self.app.processEvents()
            self.assertEqual(combo.currentData(),'distance');p.recalculate()
            spin=p.controls['target_width_mm'];option=QStyleOptionSpinBox();spin.initStyleOption(option)
            up=spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,option,QStyle.SubControl.SC_SpinBoxUp,spin)
            down=spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,option,QStyle.SubControl.SC_SpinBoxDown,spin)
            self.assertFalse(up.intersects(down));self.assertTrue(spin.rect().contains(up));self.assertTrue(spin.rect().contains(down))
            before=spin.value();QTest.mouseClick(spin,Qt.MouseButton.LeftButton,pos=up.center())
            self.assertEqual(spin.value(),before+spin.singleStep())
            QTest.mouseClick(spin,Qt.MouseButton.LeftButton,pos=down.center());self.assertEqual(spin.value(),before)
            self.assertGreaterEqual(spin.height(),28);self.assertEqual(p.camera_type.height(),36)
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

    def test_mvs_tabs_presets_inverse_optics_and_bilingual_device_options(self):
        w=ToolboxWindow();w.select_page(3);p=w.camera
        try:
            self.assertEqual([p.form_tabs.tabText(i) for i in range(3)],['材料与视野','编码器与图高','采集触发'])
            self.assertIn('horizontal_margin_percent',p.controls)
            p.camera_type.setCurrentIndex(p.camera_type.findData('line2k'));p.recalculate()
            self.assertEqual(p.settings().sensor_width,2048);self.assertEqual(p.settings().pixel_pitch_um,7)
            self.assertEqual(p.settings().focal_length_mm,12);self.assertFalse(p.controls['focal_length_mm'].isEnabled())
            self.assertEqual((p.settings().frame_line,p.settings().encoder_line),('Line3','Line1'))
            p.camera_type.setCurrentIndex(p.camera_type.findData('area5mp'));p.recalculate()
            p.controls['target_length_mm'].setValue(300);p.recalculate()
            self.assertTrue(p.line_trigger_group.isHidden());self.assertEqual(p.settings().frame_selector,'FrameStart')
            self.assertFalse(any(n['key']=='EncoderSourceA' for n in p.plan['nodes']))
            p.optical_mode.setCurrentIndex(p.optical_mode.findData('precision_to_wd'));p.controls['x_mm_per_px'].setValue(.15);p.recalculate()
            self.assertTrue(p.controls['x_mm_per_px'].isEnabled());self.assertFalse(p.controls['working_distance_mm'].isEnabled())
            self.assertAlmostEqual(p.controls['working_distance_mm'].value(),.15*6/.00345,places=3)
            self.assertFalse(p.plan['blocking'])
            p.advanced_button.click();self.assertFalse(p.form_tabs.isTabVisible(1))
            p.camera_type.setCurrentIndex(p.camera_type.findData('line4k'));p.recalculate()
            self.assertFalse(p.line_trigger_group.isHidden());self.assertTrue(p.form_tabs.isTabVisible(1))
            p.output_caps={'Line0':{'status':'readable','choices':['ExposureStartActive','CounterActive']}}
            p.refresh_output_choices();source=p.controls['output0_source']
            self.assertFalse(source.isEditable());source.setCurrentIndex(source.findData('CounterActive'));p.recalculate()
            raw=p.settings().output0_source;self.assertEqual(source.currentText(),'计数器有效')
            p.language_box.setCurrentIndex(p.language_box.findData('en'))
            self.assertEqual(source.currentText(),'CounterActive');self.assertEqual(p.settings().output0_source,raw)
            self.assertEqual(p.form_tabs.tabText(3),'Digital IO')
            p.optical_mode.setCurrentIndex(p.optical_mode.findData('fov'));p.recalculate()
            self.assertAlmostEqual(p.controls['x_mm_per_px'].value(),p.plan['metrics']['x_mm_per_px'],places=6)
            form=p.field_forms['working_distance_mm']
            self.assertTrue(form.table.isRowHidden(form.rows[p.controls['working_distance_mm']]))
        finally:w.close();self.app.processEvents()

    def test_compare_invalidation_background_write_and_close_protection(self):
        w=ToolboxWindow();w.show();w.select_page(3);p=w.camera;camera=FakeCamera()
        p.load_settings(CameraSettings())
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
