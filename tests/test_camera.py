import copy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from camera_model import CameraSettings,calculate,settings_from_dict,config_dict,node_id,import_mfs_text,CameraError
from camera_sdk import NodeUnavailable,discover_mvs,enumerate_cameras
from camera_transaction import compare,apply_comparison,CameraWriteError,selectors,read_output_sources,read_trigger_ios


class FakeCamera:
    """Simulated node constraints, selector banks and nonvolatile user-set storage."""
    def __init__(self,settings=None):
        self.device={'uid':'GigE:TEST-001','serial':'TEST-001','model':'SIMULATED CAMERA'}
        self.values={};self.specs={};self.writes=[];self.commands=[];self.fail_key=None;self.fail_load=False
        self.selectors={'TriggerSelector':'FrameBurstStart','LineSelector':'Line1','UserSetSelector':'Default'}
        self.contextual=set()
        for e in calculate(settings or CameraSettings())['nodes']:
            if e.get('optional'):continue
            if 'TriggerSelector' in e['selectors']:self.contextual.add(e['key'])
            ident=node_id(e);self.values[ident]=e['value'];self.specs[ident]=copy.deepcopy(e)
        for e in self.specs.values():
            if e['key']=='LineMode' and e['selectors'].get('LineSelector')=='Line0':self.values[node_id(e)]='Input'
        self._set_plain('Width',1024);self._set_plain('OffsetX',7);self._set_plain('Gain',0.0)
        self._set_plain('UserSetDefault','Default');self.saved=None
    def _set_plain(self,key,value):self.values[node_id({'key':key,'selectors':{}})]=value
    def ident(self,key):
        if key in ('TriggerMode','TriggerSource','TriggerActivation','TriggerDelay','TriggerCacheEnable') or key in self.contextual:context={'TriggerSelector':self.selectors['TriggerSelector']}
        elif key in ('LineMode','LineFormat','LineSource','LineDebouncerTimeNs','StrobeEnable','StrobeLineDuration'):context={'LineSelector':self.selectors['LineSelector']}
        else:context={}
        return node_id({'key':key,'selectors':context})
    def read(self,key,kind):
        if key in self.selectors:return {'kind':'enum','value':self.selectors[key],'writable':True,'choices':['Default','UserSet1','FrameBurstStart','FrameStart','LineStart']+['Line'+str(i) for i in range(16)]}
        ident=self.ident(key)
        if ident not in self.values:raise NodeUnavailable(key,0)
        if key in ('LineSource','StrobeEnable'):
            mode=self.values[self.ident('LineMode')]
            if mode=='Input':raise NodeUnavailable(key,1)
        value=self.values[ident];result={'kind':kind,'value':value,'writable':True}
        if kind in ('int','float'):result.update(min=0,max=100000000,inc=1)
        if key=='Width':result.update(min=1,max=4096-self.values[self.ident('OffsetX')])
        if kind=='enum':result['choices']=list({value,'Continuous','Timed','TriggerWidth','Off','On','Input','Output','Strobe','UserSet1','ExposureStartActive','FrequencyConverter','EncoderModuleOut','NA','AnyDirection','IgnoreDirection','Mono8','RGB8Packed','Differential','RisingEdge','FallingEdge'}|{'Line'+str(i) for i in range(16)})
        if kind=='string':result['max_length']=32
        return result
    def write(self,key,kind,value):
        if key==self.fail_key:self.fail_key=None;raise CameraError('SIMULATED failure '+key)
        if key=='Width' and value>4096-self.values[self.ident('OffsetX')]:raise CameraError('SIMULATED offset-dependent Width limit')
        self.writes.append((key,value,dict(self.selectors)))
        if key in self.selectors:self.selectors[key]=value
        else:self.values[self.ident(key)]=value
    def command_ready(self,key):pass
    def command(self,key):
        self.commands.append(key)
        if key=='UserSetSave':self.saved=(copy.deepcopy(self.values),copy.deepcopy(self.selectors))
        if key=='UserSetLoad':
            if self.fail_load:raise CameraError('SIMULATED load failure')
            self.values,self.selectors=copy.deepcopy(self.saved)
    def geometry(self):
        return {'sensor_width':4096,'sensor_height':2048,'limits':{key:self.read(key,'int') for key in ('Width','Height','OffsetX')}}


class CameraCalculationTests(unittest.TestCase):
    def test_product_geometry_is_independent_of_encoder_cycle_and_inactive_rate(self):
        first=calculate(CameraSettings(target_length_mm=280,image_vertical_margin_mm=10,line_rate_override=30000))
        second=calculate(CameraSettings(target_length_mm=280,image_vertical_margin_mm=10,ppr=2000,products_per_minute=400))
        self.assertEqual(first['metrics']['height'],second['metrics']['height'])
        self.assertEqual(second['metrics']['line_triggers_per_cycle'],6000)
        self.assertFalse(first['blocking']);self.assertNotIn('AcquisitionLineRate',{n['key'] for n in first['nodes']})
        self.assertEqual({n['key']:n['value'] for n in first['nodes']}['AcquisitionBurstFrameCount'],1)
        self.assertEqual({n['key']:n['value'] for n in first['nodes']}['AcquisitionMode'],'Continuous')
        old=settings_from_dict({'schema':'vt-camera-config/1','product_pitch_mm':300,'image_top_margin_mm':5,'image_bottom_margin_mm':7})
        self.assertEqual(old.line_y_source,'legacy');self.assertEqual(old.image_vertical_margin_mm,12)
        self.assertTrue(calculate(old)['blocking']);old.line_y_source='precision'
        self.assertFalse(any('旧配置' in x for x in calculate(old)['blocking']))
        calibrated=calculate(CameraSettings(line_y_source='calibration',calibration_length_mm=300,calibration_rows=3000))
        self.assertEqual(calibrated['metrics']['y_mm_per_px'],.1)
        square=calculate(CameraSettings(target_length_mm=100,line_y_source='square'))
        self.assertEqual(square['metrics']['y_mm_per_px'],square['metrics']['x_mm_per_px']);self.assertTrue(square['warnings'])

    def test_background_margins_add_capture_lines_without_changing_encoder_or_line_rate(self):
        s=CameraSettings(target_length_mm=280,image_vertical_margin_mm=12)
        m=calculate(s)['metrics'];self.assertEqual(m['product_height_lines'],2800)
        self.assertEqual((m['vertical_margin_lines'],m['background_height_lines'],m['height']),(120,120,2920))
        self.assertEqual(m['lines_per_product'],3000);self.assertEqual(m['required_line_rate_hz'],40000)
        self.assertFalse(calculate(s)['blocking'])
        self.assertTrue(calculate(CameraSettings(image_vertical_margin_mm=1))['blocking'])
        with self.assertRaises(CameraError):calculate(CameraSettings(image_vertical_margin_mm=-1))
        area=calculate(CameraSettings(kind='area',target_length_mm=195,image_vertical_margin_mm=6))
        self.assertTrue(area['blocking'])
        rounded=calculate(CameraSettings(target_length_mm=.15,image_vertical_margin_mm=.02),{'Height':{'min':4,'inc':4}})
        self.assertEqual(rounded['metrics']['height'],4)

    def test_optical_estimate_requires_physical_data_and_preserves_line_scan_y_sampling(self):
        with self.assertRaises(CameraError):calculate(CameraSettings(precision_source='optics'))
        with self.assertRaises(CameraError):calculate(CameraSettings(precision_source='optics',focal_length_mm=500,pixel_pitch_um=7))
        s=CameraSettings(precision_source='optics',focal_length_mm=25,pixel_pitch_um=7)
        plan=calculate(s);m=plan['metrics'];self.assertAlmostEqual(m['x_mm_per_px'],.112)
        self.assertAlmostEqual(m['y_mm_per_px'],.1);self.assertEqual(m['product_height_lines'],3000)
        self.assertEqual(m['square_pixel_product_lines'],2679);self.assertTrue(plan['warnings'])
        inverse=CameraSettings(precision_source='optics',optics_direction='precision_to_wd',focal_length_mm=25,pixel_pitch_um=7,x_mm_per_px=.112)
        self.assertAlmostEqual(calculate(inverse)['metrics']['working_distance_mm'],400)
        self.assertEqual(settings_from_dict(config_dict(inverse)),inverse)
        old=config_dict(s);old.pop('optics_direction')
        self.assertEqual(settings_from_dict(old).optics_direction,'wd_to_precision')
        s.kind='area';s.target_length_mm=120
        self.assertAlmostEqual(calculate(s)['metrics']['y_mm_per_px'],.112)
        old=config_dict(CameraSettings())
        for name in ('focal_length_mm','pixel_pitch_um','image_vertical_margin_mm'):old.pop(name)
        self.assertEqual(calculate(settings_from_dict(old))['metrics']['height'],3000)

    def test_enum_inspection_restores_selectors_without_changing_io_modes(self):
        camera=FakeCamera();camera.values[camera.ident('LineMode')]='Input'
        camera.values[node_id({'key':'LineMode','selectors':{'LineSelector':'Line0'}})]='Strobe'
        before=copy.deepcopy(camera.values);original=copy.deepcopy(camera.selectors)
        sources=read_output_sources(camera);triggers=read_trigger_ios(camera,True)
        self.assertIn('ExposureStartActive',sources['Line0']['choices'])
        self.assertEqual(sources['Line1']['status'],'unavailable')
        self.assertIn('Line3',triggers['frame_line']);self.assertIn('Line1',triggers['encoder_line'])
        self.assertEqual(camera.selectors,original);self.assertEqual(camera.values,before)
        self.assertTrue(all(key in original for key,_,_ in camera.writes))

    def test_line_physics_fixed_encoder_chain_and_real_roi_steps(self):
        s=CameraSettings();r=calculate(s,{'Width':{'min':16,'inc':16},'OffsetX':{'min':0,'inc':4}})
        m=r['metrics'];self.assertEqual(m['lines_per_product'],3000);self.assertEqual(m['required_line_rate_hz'],40000)
        self.assertEqual(m['recommended_line_rate_hz'],45000);self.assertEqual(m['width'],3280);self.assertEqual(m['offset_x'],408)
        self.assertAlmostEqual(m['y_mm_per_px'],.1);self.assertEqual(r['settings']['multiplier'],3)
        s.working_distance_mm=1000;self.assertEqual(calculate(s)['metrics']['x_mm_per_px'],400/4096)
    def test_noninteger_overheight_exposure_and_square_constraints(self):
        for kwargs,reason in (({'height_override':3200},'Height'),
                             ({'exposure_us':50},'曝光'),({'require_square':True},'差异')):
            r=calculate(CameraSettings(**kwargs));self.assertTrue(any(reason in v for v in r['blocking']),r)
        r=calculate(CameraSettings(height_override=3200,ppr=2000,products_per_minute=400));self.assertFalse(r['blocking'])
        self.assertEqual(r['metrics']['product_height_lines'],3000);self.assertEqual(r['metrics']['background_height_lines'],200)
        r=calculate(CameraSettings(target_length_mm=10,multiplier=1,post_divider=3));self.assertFalse(r['blocking']);self.assertTrue(r['warnings'])
    def test_area_excludes_encoder_nodes_and_separates_xy_precision(self):
        s=CameraSettings(kind='area',target_length_mm=120,frame_selector='FrameStart');r=calculate(s)
        keys={e['key'] for e in r['nodes']}
        self.assertNotIn('PreDivider',keys);self.assertNotIn('AcquisitionLineRate',keys);self.assertIsNone(r['metrics']['lines_per_product'])
        self.assertFalse(any(e['selectors'].get('TriggerSelector')=='LineStart' for e in r['nodes']))
        self.assertFalse(r['blocking'])
    def test_config_and_mfs_are_bounded_typed_data(self):
        s,count=import_mfs_text('#GenApi persistence file version 3.0.1\nWidth\t3296\nOffsetX\t500\nHeight\t3200\nTriggerSelector\tFrameBurstStart\nTriggerSource\tLine3\nPreDivider\t1\nMultiplier\t3\nPostDivider\t1\n')
        self.assertEqual(s.width_override,3296);self.assertEqual(s.offset_x,500);self.assertFalse(s.centered_x);self.assertEqual(count,7)
        self.assertEqual(settings_from_dict(config_dict(s)),s)
        for value in (float('nan'),float('inf')):
            with self.assertRaises(CameraError):CameraSettings(gain=value).validate()
        with self.assertRaises(CameraError):CameraSettings(frame_line='Line1').validate()
        with self.assertRaises(CameraError):settings_from_dict({'schema':'unknown'})


class CameraTransactionTests(unittest.TestCase):
    def test_line_trigger_precedes_timed_exposure_and_frame_trigger_is_last(self):
        camera=FakeCamera();line=node_id({'key':'TriggerMode','selectors':{'TriggerSelector':'LineStart'}})
        mode=node_id({'key':'ExposureMode','selectors':{'TriggerSelector':'LineStart'}})
        camera.values[line]='Off';camera.values[mode]='TriggerWidth';original_read=camera.read
        def constrained_read(key,kind):
            cap=original_read(key,kind)
            if key in ('ExposureMode','ExposureTime'):
                cap['writable']=camera.values[line]=='On' and (key=='ExposureMode' or camera.values[mode]=='Timed')
            return cap
        camera.read=constrained_read
        report=compare(camera,CameraSettings());self.assertTrue(report['ready'],report['errors'])
        result=apply_comparison(camera,report);self.assertEqual(result['status'],'passed')
        writes=camera.writes
        i_line=next(i for i,(k,v,c) in enumerate(writes) if k=='TriggerMode' and v=='On' and c['TriggerSelector']=='LineStart')
        i_mode=next(i for i,(k,v,c) in enumerate(writes) if k=='ExposureMode' and v=='Timed')
        i_frame=next(i for i,(k,v,c) in enumerate(writes) if k=='TriggerMode' and v=='On' and c['TriggerSelector']=='FrameBurstStart')
        self.assertLess(i_line,i_mode);self.assertLess(i_mode,i_frame)

    def test_extra_trigger_state_changes_reject_and_capacity_failure_prevents_flash(self):
        camera=FakeCamera();camera._set_plain('FrameTimeoutEnable',False)
        report=compare(camera,CameraSettings());camera._set_plain('FrameTimeoutEnable',True)
        with self.assertRaisesRegex(CameraError,'超时状态已变化'):apply_comparison(camera,report)
        self.assertFalse(camera.commands)
        camera=FakeCamera();camera._set_plain('ResultingLineRate',20000.0)
        report=compare(camera,CameraSettings())
        with self.assertRaises(CameraWriteError) as exc:apply_comparison(camera,report)
        self.assertIn('允许的行频',str(exc.exception));self.assertFalse(camera.commands)
        self.assertFalse(exc.exception.report['persistent_may_have_changed'])

    def test_selectors_restore_and_write_order_persist_reload_readback(self):
        camera=FakeCamera();before_select=copy.deepcopy(camera.selectors);report=compare(camera,CameraSettings())
        self.assertTrue(report['ready'],report['errors']);self.assertEqual(camera.selectors,before_select)
        self.assertTrue(any(r['status']=='依赖模式切换后校验' for r in report['rows']))
        camera.writes.clear();result=apply_comparison(camera,report)
        self.assertEqual(result['status'],'passed');self.assertEqual(camera.commands,['UserSetSave','UserSetLoad'])
        self.assertEqual(camera.read('UserSetDefault','enum')['value'],'UserSet1')
        names=[key for key,value,context in camera.writes]
        self.assertLess(names.index('OffsetX'),names.index('Width'));self.assertLess(names.index('TriggerMode'),names.index('Width'))
        self.assertTrue(result['readback_verified'])
    def test_other_client_changes_are_rejected_before_parameter_writes(self):
        camera=FakeCamera();report=compare(camera,CameraSettings());camera._set_plain('Gain',1.5);camera.writes.clear()
        with self.assertRaisesRegex(CameraError,'已被修改'):apply_comparison(camera,report)
        self.assertFalse(camera.commands);self.assertFalse(any(k=='Gain' for k,v,c in camera.writes))
    def test_write_failure_restores_runtime_without_flash_commands(self):
        camera=FakeCamera();camera.values[node_id({'key':'LineMode','selectors':{'LineSelector':'Line0'}})]='Strobe'
        report=compare(camera,CameraSettings());original=copy.deepcopy(camera.values)
        camera.fail_key='Gain'
        with self.assertRaises(CameraWriteError) as raised:apply_comparison(camera,report)
        self.assertTrue(raised.exception.report['runtime_restored'],raised.exception.report)
        self.assertFalse(raised.exception.report['persistent_may_have_changed']);self.assertFalse(camera.commands)
        self.assertEqual(camera.values,original)
    def test_post_save_failure_does_not_claim_flash_rollback(self):
        camera=FakeCamera();report=compare(camera,CameraSettings());camera.fail_load=True
        with self.assertRaises(CameraWriteError) as raised:apply_comparison(camera,report)
        self.assertTrue(raised.exception.report['persistent_may_have_changed']);self.assertFalse(raised.exception.report['runtime_restored'])
        self.assertIn('用户集可能',str(raised.exception))

    def test_selector_restore_failure_preserves_primary_failure_report(self):
        camera=FakeCamera();report={'persistent_may_have_changed':True,'runtime_restored':True}
        with self.assertRaises(CameraWriteError) as raised:
            with selectors(camera) as select:
                select.select({'LineSelector':'Line0'});camera.fail_key='LineSelector'
                raise CameraWriteError('SIMULATED primary error',report)
        self.assertTrue(raised.exception.report['persistent_may_have_changed']);self.assertFalse(raised.exception.report['runtime_restored'])
        self.assertIn('SIMULATED primary',str(raised.exception));self.assertTrue(raised.exception.report['rollback_errors'])

    def test_auto_gain_can_change_until_the_planned_auto_off_transition(self):
        camera=FakeCamera();camera._set_plain('GainAuto','Continuous');read=camera.read
        def auto_read(key,kind):
            cap=read(key,kind)
            if key=='Gain' and camera.values[camera.ident('GainAuto')]=='Continuous':cap['writable']=False
            return cap
        camera.read=auto_read;preview=compare(camera,CameraSettings())
        self.assertTrue(preview['ready'],preview['errors']);camera._set_plain('Gain',.7)
        result=apply_comparison(camera,preview)
        self.assertEqual(result['status'],'passed');self.assertEqual(camera.read('GainAuto','enum')['value'],'Off')
        self.assertAlmostEqual(camera.read('Gain','float')['value'],2.9079)

    def test_mode_hidden_original_values_are_reported_as_unverified_after_failure(self):
        camera=FakeCamera();report=compare(camera,CameraSettings());camera.fail_key='Gain'
        with self.assertRaises(CameraWriteError) as raised:apply_comparison(camera,report)
        self.assertFalse(raised.exception.report['runtime_restored']);self.assertFalse(camera.commands)
        self.assertTrue(any('切换模式前不可读' in e for e in raised.exception.report['rollback_errors']))

    def test_format_setter_side_effects_are_restored_even_when_setter_fails(self):
        settings=CameraSettings(pixel_format='RGB8Packed');camera=FakeCamera(settings)
        camera._set_plain('PixelFormat','Mono8');camera.values[node_id({'key':'LineMode','selectors':{'LineSelector':'Line0'}})]='Strobe'
        original=copy.deepcopy(camera.values);preview=compare(camera,settings);write=camera.write;failed=[False]
        def format_write(key,kind,value):
            write(key,kind,value)
            if key=='PixelFormat':
                camera._set_plain('Width',512)
                if not failed[0]:failed[0]=True;raise CameraError('SIMULATED partial format update')
        camera.write=format_write
        with self.assertRaises(CameraWriteError) as raised:apply_comparison(camera,preview)
        self.assertTrue(raised.exception.report['runtime_restored'],raised.exception.report['rollback_errors'])
        self.assertEqual(camera.values,original);self.assertFalse(camera.commands)


if __name__=='__main__':unittest.main()
