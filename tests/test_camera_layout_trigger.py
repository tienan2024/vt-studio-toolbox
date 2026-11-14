import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from toolbox import ToolboxWindow


class CameraLayoutTriggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def settle(self):
        for _ in range(12):self.app.processEvents()

    def setUp(self):
        self.w=ToolboxWindow();self.w.resize(1180,720);self.w.show();self.w.select_page(3);self.p=self.w.camera;self.settle()

    def tearDown(self):self.w.close();self.app.processEvents()

    def test_connection_and_details_never_compress_text_into_result_table(self):
        p=self.p
        for height in (720,640):
            self.w.resize(1180,height)
            for connected in (True,False):
                p.connection_button.setChecked(connected)
                for details in (True,False):
                    p.details_button.setChecked(details);self.settle()
                    self.assertGreater(p.optics_summary.y(),p.metrics.geometry().bottom())
                    self.assertGreaterEqual(p.optics_summary.height(),p.optics_summary.heightForWidth(p.optics_summary.width()))
                    self.assertGreater(p.summary.y(),p.optics_summary.geometry().bottom())

    def test_top_controls_have_equal_sizes_and_trigger_sources_are_distinct(self):
        p=self.p
        for language in ('zh','en'):
            p.language_box.setCurrentIndex(p.language_box.findData(language));self.settle()
            self.assertEqual(len({w.size().toTuple() for w in (p.language_box,p.connection_button,p.files_button)}),1)
        p.form_tabs.setCurrentIndex(2);self.settle()
        self.assertEqual(p.line_trigger_source.currentData(),'FrequencyConverter')
        self.assertTrue(p.line_trigger_source.isEnabled());self.assertTrue(p.controls['encoder_line'].isVisible())
        p.controls['encoder_line'].setCurrentIndex(p.controls['encoder_line'].findData('Line2'));p.recalculate()
        entries={(n['key'],n['selectors'].get('TriggerSelector')):n['value'] for n in p.plan['nodes']}
        self.assertEqual(entries['EncoderSourceA',None],'Line2')
        self.assertEqual(entries['TriggerSource','LineStart'],'FrequencyConverter')
        self.assertEqual(entries['TriggerSource','FrameBurstStart'],'Line3')
        p.camera_type.setCurrentIndex(p.camera_type.findData('area5mp'));self.settle()
        self.assertTrue(p.line_trigger_group.isHidden());self.assertTrue(p.encoder_trigger_group.isHidden())


if __name__=='__main__':unittest.main()
