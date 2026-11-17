import copy,sys,tempfile,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from camera_model import CameraSettings,calculate,config_dict,settings_from_dict,import_mfs_text,node_id
from camera_presets import CameraPresetStore,PAGE_KEYS
from camera_snapshot import read_snapshot,compare_presets
from camera_transaction import compare,apply_comparison,read_trigger_ios
from test_camera import FakeCamera

FIELDS=('encoder_source_b','encoder_output_mode','encoder_counter_mode','converter_input_source','converter_alignment')
NODE_FIELDS=dict(zip(('EncoderSourceB','EncoderOutputMode','EncoderCounterMode','InputSource','SignalAlignment'),FIELDS))


class ChainCamera(FakeCamera):
    def read(self,key,kind):
        cap=super().read(key,kind)
        if key=='EncoderOutputMode':cap['choices']=['AnyDirection','ForwardOnly','BackwardOnly']
        if key=='EncoderCounterMode':cap['choices']=['IgnoreDirection','FollowDirection','BackwardDirection']
        return cap


class TriggerChainTests(unittest.TestCase):
    def test_old_schema_keeps_previous_nodes_and_alignment_follows_old_line_edge(self):
        raw=config_dict(CameraSettings(line_edge='RisingEdge'))
        for key in FIELDS:raw.pop(key)
        nodes={n['key']:n['value'] for n in calculate(settings_from_dict(raw))['nodes']}
        self.assertEqual({key:nodes[key] for key in NODE_FIELDS},dict(EncoderSourceB='NA',EncoderOutputMode='AnyDirection',
            EncoderCounterMode='IgnoreDirection',InputSource='EncoderModuleOut',SignalAlignment='RisingEdge'))
        self.assertNotIn('EncoderTriggerMode',nodes)

    def test_explicit_chain_roundtrips_mfs_preset_comparison_and_verified_writes(self):
        settings=replace(CameraSettings(),camera_model_id='SIMULATED CAMERA',encoder_source_b='Line2',encoder_output_mode='ForwardOnly',
            encoder_counter_mode='FollowDirection',converter_alignment='RisingEdge')
        text='EncoderSourceB\tLine2\nEncoderOutputMode\tForwardOnly\nEncoderCounterMode\tFollowDirection\nInputSource\tEncoderModuleOut\nSignalAlignment\tRisingEdge\n'
        imported,_=import_mfs_text(text)
        self.assertEqual([getattr(imported,k) for k in FIELDS],[getattr(settings,k) for k in FIELDS])
        self.assertEqual(settings_from_dict(config_dict(settings)),settings)
        with tempfile.TemporaryDirectory() as folder:
            store=CameraPresetStore(Path(folder)/'presets.json');store.save('trigger',0,settings,'SIMULATED CAMERA')
            saved=CameraPresetStore(store.path).values('trigger',0,'SIMULATED CAMERA')
            self.assertEqual([saved[k] for k in FIELDS],[getattr(settings,k) for k in FIELDS])
        camera=ChainCamera(settings)
        for key,value in (('EncoderSourceB','NA'),('EncoderOutputMode','AnyDirection'),('EncoderCounterMode','IgnoreDirection'),('SignalAlignment','FallingEdge')):camera._set_plain(key,value)
        snapshot=read_snapshot(camera,camera.geometry())
        data=config_dict(settings);pages={page:{'slot':0,'values':{key:data[key] for key in keys}} for page,keys in PAGE_KEYS.items()}
        rows=compare_presets(snapshot,pages)
        for field in ('encoder_source_b','encoder_output_mode','encoder_counter_mode','converter_alignment'):
            self.assertEqual(next(r for r in rows if r['field']==field)['status'],'不同')
        alignment=[r for r in rows if r['entry'] and r['entry']['key']=='SignalAlignment']
        self.assertEqual(len(alignment),1);self.assertEqual(alignment[0]['field'],'converter_alignment')
        preview=compare(camera,settings);self.assertTrue(preview['ready'],preview['errors'])
        with patch('camera_transaction.time.sleep'):report=apply_comparison(camera,preview)
        self.assertEqual(report['status'],'passed')
        for key,field in NODE_FIELDS.items():self.assertEqual(camera.read(key,'enum')['value'],getattr(settings,field))
        self.assertEqual(camera.read('TriggerActivation','enum')['value'],'RisingEdge')
        self.assertEqual(next(n['value'] for n in preview['plan']['nodes'] if n['key']=='TriggerActivation' and n['selectors'].get('TriggerSelector')=='LineStart'),'FallingEdge')
        choices=read_trigger_ios(camera,True)
        self.assertTrue(set(FIELDS)<=set(choices));self.assertIn('ForwardOnly',choices['encoder_output_mode'])

    def test_direct_converter_input_uses_that_io_and_area_excludes_the_entire_chain(self):
        settings=replace(CameraSettings(),converter_input_source='Line2',converter_alignment='RisingEdge')
        nodes=calculate(settings)['nodes'];keys={n['key'] for n in nodes}
        self.assertNotIn('EncoderSourceA',keys);self.assertNotIn('EncoderSourceB',keys)
        self.assertEqual({n['selectors']['LineSelector'] for n in nodes if n['key']=='LineMode' and n['value']=='Input'},{'Line3','Line2'})
        self.assertEqual(next(n['value'] for n in nodes if n['key']=='InputSource'),'Line2')
        blocked=calculate(replace(settings,converter_input_source='NA'))
        self.assertTrue(any('输入源为NA' in text for text in blocked['blocking']))
        area=replace(CameraSettings(),kind='area',frame_selector='FrameStart')
        keys={n['key'] for n in calculate(area)['nodes']}
        self.assertTrue(keys.isdisjoint(NODE_FIELDS));self.assertNotIn('EncoderSourceA',keys)


class TriggerChainDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_visible_controls_use_device_enumeration_and_hide_for_area(self):
        from camera_ui import CameraPage
        with tempfile.TemporaryDirectory() as folder:
            store=CameraPresetStore(Path(folder)/'presets.json')
            with patch('camera_ui.CameraPresetStore',return_value=store):page=CameraPage()
            try:
                page.form_tabs.setCurrentIndex(2);page.show();self.app.processEvents()
                self.assertTrue(all(page.controls[k].isVisible() for k in FIELDS))
                page.apply_enum_choices('encoder_counter_mode',['IgnoreDirection','FollowDirection'])
                self.assertEqual(page.controls['encoder_counter_mode'].count(),2)
                page.apply_enum_choices('converter_alignment',['RisingEdge','FallingEdge'])
                self.assertEqual(page.controls['converter_alignment'].itemText(page.controls['converter_alignment'].findData('')),'跟随行触发边沿')
                self.assertIn('Line1',page.trigger_help.text())
                page.controls['converter_input_source'].setCurrentIndex(page.controls['converter_input_source'].findData('Line2'));page.recalculate()
                self.assertTrue(page.encoder_trigger_group.isHidden());self.assertFalse(page.controls['encoder_source_b'].isVisible())
                self.assertEqual(page.trigger_help.text(),'Line2 → 频率转换器 → 行触发。')
                page.language_box.setCurrentIndex(page.language_box.findData('en'));page.recalculate()
                self.assertEqual(page.trigger_help.text(),'Line2 → FrequencyConverter → LineStart.')
                page.camera_type.setCurrentIndex(page.camera_type.findData('area5mp'));page.recalculate();self.app.processEvents()
                self.assertTrue(all(not page.controls[k].isVisible() for k in FIELDS))
                self.assertEqual(page.trigger_help.text(),'Frame trigger only.')
            finally:page.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
