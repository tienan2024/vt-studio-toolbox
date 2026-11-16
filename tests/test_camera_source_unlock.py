import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from camera_model import CameraSettings,CameraError,node_id
from camera_transaction import compare,apply_comparison,CameraWriteError,IO_SOURCE_KEYS
from test_camera import FakeCamera


class SourceLockedCamera(FakeCamera):
    """Source selection owns IO even when both TriggerMode banks are Off."""
    def __init__(self):
        super().__init__();self.timeline=[];self.mode_cache={}
        for selector in ('FrameBurstStart','LineStart'):
            self.values[node_id({'key':'TriggerMode','selectors':{'TriggerSelector':selector}})]='Off'
            self.values[node_id({'key':'TriggerSource','selectors':{'TriggerSelector':selector}})]='AnyLine'
        self._set_plain('EncoderSourceA','Line0');self._set_plain('EncoderSourceB','Line0');self._set_plain('InputSource','Line0')

    def occupied(self,line):
        return any(value in (line,'AnyLine') for ident,value in self.values.items()
                   if any(ident==node_id({'key':key,'selectors':context})
                          for key in IO_SOURCE_KEYS for context in ({},{'TriggerSelector':'FrameBurstStart'},{'TriggerSelector':'LineStart'})))

    def read(self,key,kind):
        cap=super().read(key,kind)
        if key in IO_SOURCE_KEYS:
            cap['choices']=[v for v in cap['choices'] if v==cap['value'] or not v.startswith('Line') or not v[4:].isdigit()
                            or self.values.get(node_id({'key':'LineMode','selectors':{'LineSelector':v}}))=='Input']
        if key=='LineMode':
            line=self.selectors['LineSelector']
            locked=self.mode_cache.setdefault(line,self.occupied(line) and cap['value']=='Input')
            if locked:cap.update(writable=False,choices=[cap['value']])
            self.timeline.append(('mode_read',line,cap['writable']))
        return cap

    def write(self,key,kind,value):
        if key=='LineMode' and value!='Input' and self.occupied(self.selectors['LineSelector']):
            raise CameraError('TEST source still owns '+self.selectors['LineSelector'])
        if key in IO_SOURCE_KEYS and value.startswith('Line') and value[4:].isdigit():
            mode=self.values.get(node_id({'key':'LineMode','selectors':{'LineSelector':value}}))
            if mode!='Input':raise CameraError('TEST source needs input '+value)
        result=super().write(key,kind,value)
        self.timeline.append(('write',key,value,dict(self.selectors)))
        return result

    def invalidate_nodes(self):
        self.mode_cache.clear();self.timeline.append(('refresh',));return True


class SourceUnlockTests(unittest.TestCase):
    def apply(self,camera,preview=None):
        with patch('camera_transaction.time.sleep'):
            return apply_comparison(camera,preview or compare(camera,CameraSettings()))

    def test_sources_release_io_even_when_triggers_already_off_and_cache_is_stale(self):
        camera=SourceLockedCamera();before=copy.deepcopy(camera.values)
        preview=compare(camera,CameraSettings())
        self.assertTrue(preview['ready'],preview['errors']);self.assertEqual(camera.values,before)
        result=self.apply(camera,preview);self.assertEqual(result['status'],'passed')
        line0=next(r for r in result['io_preparation']['lines'] if r['node']['selectors']['LineSelector']=='Line0')
        self.assertTrue(line0['capability']['writable']);self.assertIn('Strobe',line0['capability']['choices'])
        output=next(i for i,e in enumerate(camera.timeline) if e[:3]==('write','LineMode','Strobe'))
        sources=[i for i,e in enumerate(camera.timeline) if e[0]=='write' and e[1] in IO_SOURCE_KEYS]
        self.assertEqual(len(sources),5);self.assertLess(max(sources),output)
        self.assertEqual(camera.timeline[max(sources)+1],('refresh',))
        self.assertEqual(camera.commands,['UserSetSave','UserSetLoad'])

    def test_target_input_mode_precedes_selecting_that_line_as_source(self):
        camera=SourceLockedCamera();camera.values[node_id({'key':'LineMode','selectors':{'LineSelector':'Line3'}})]='Strobe'
        self.assertEqual(self.apply(camera)['status'],'passed')
        writes=[e for e in camera.timeline if e[0]=='write']
        input_index=next(i for i,e in enumerate(writes) if e[1:3]==('LineMode','Input') and e[3]['LineSelector']=='Line3')
        source_index=next(i for i,e in enumerate(writes) if e[1:3]==('TriggerSource','Line3'))
        self.assertLess(input_index,source_index)

    def test_failure_restores_original_source_ownership_after_io_is_input(self):
        camera=SourceLockedCamera();before=copy.deepcopy(camera.values);camera.fail_key='Gain'
        with self.assertRaises(CameraWriteError) as caught:self.apply(camera)
        self.assertEqual(camera.values,before);self.assertFalse(camera.commands)
        # Source-only recovery must not turn on an originally Off trigger bank.
        self.assertEqual(camera.read('TriggerMode','enum')['value'],'Off')
        self.assertTrue(any('切换模式前不可读' in e for e in caught.exception.report['rollback_errors']))

    def test_readonly_after_source_update_stops_before_output_write_or_save(self):
        camera=SourceLockedCamera();read=camera.read
        def fixed(key,kind):
            cap=read(key,kind)
            if key=='LineMode':cap['writable']=False
            return cap
        camera.read=fixed
        with self.assertRaises(CameraWriteError) as caught:self.apply(camera)
        self.assertIn('LineSelector=Line0',str(caught.exception));self.assertFalse(camera.commands)
        self.assertFalse(any(k=='LineMode' and value=='Strobe' for k,value,_ in camera.writes))

    def test_source_write_failure_prevents_output_and_restores_previous_sources(self):
        camera=SourceLockedCamera();before=copy.deepcopy(camera.values);camera.fail_key='InputSource'
        with self.assertRaises(CameraWriteError):self.apply(camera)
        self.assertEqual(camera.values,before);self.assertFalse(camera.commands)
        self.assertFalse(any(k=='LineMode' and value=='Strobe' for k,value,_ in camera.writes))

    def test_readonly_source_is_deferred_and_revalidated_after_triggers_off(self):
        camera=SourceLockedCamera();read=camera.read
        def dependent(key,kind):
            cap=read(key,kind)
            if key=='InputSource' and any(camera.values[node_id({'key':'TriggerMode','selectors':{'TriggerSelector':s}})]=='On'
                                          for s in ('FrameBurstStart','LineStart')):cap['writable']=False
            return cap
        camera.read=dependent
        camera.values[node_id({'key':'TriggerMode','selectors':{'TriggerSelector':'LineStart'}})]='On'
        preview=compare(camera,CameraSettings())
        row=next(r for r in preview['rows'] if r['entry']['key']=='InputSource')
        self.assertEqual(row['status'],'依赖模式切换后校验');self.assertTrue(preview['ready'],preview['errors'])
        self.assertEqual(self.apply(camera,preview)['status'],'passed')

    def test_external_readonly_source_change_invalidates_preview(self):
        camera=SourceLockedCamera();read=camera.read
        def fixed(key,kind):
            cap=read(key,kind)
            if key=='InputSource':cap['writable']=False
            return cap
        camera.read=fixed;preview=compare(camera,CameraSettings())
        camera._set_plain('InputSource','Line3')
        with self.assertRaisesRegex(CameraError,'对比后已被修改'):self.apply(camera,preview)
        self.assertFalse(camera.commands)


if __name__=='__main__':unittest.main()
