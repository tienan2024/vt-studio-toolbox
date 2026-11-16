import copy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from sol_apply import discover_vm,remember_vm,config_for_module,plan_application,SolApplyError
from script_generator import default_config,generate_sources
from test_sol_apply import module

class SolContinuationTests(unittest.TestCase):
    def test_c_and_d_search_finds_nonstandard_vendor_folder(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);(base/'C').mkdir();(base/'D').mkdir()
            target=base/'C'/'Program Files'/'Vendor'/'VisionMaster4.4.0'/'Applications';target.mkdir(parents=True)
            real_path=Path
            def map_path(value):return base/value[0] if value in ('C:/','D:/') else real_path(value)
            def sdk(value):
                if real_path(value)==target:return target
                raise SolApplyError('Not an installation')
            registry=SimpleNamespace(HKEY_LOCAL_MACHINE=0,OpenKey=lambda *a:(_ for _ in ()).throw(OSError()))
            with patch('sol_apply.Path',side_effect=map_path),patch('sol_apply.vm_preference_path',return_value=base/'absent'),patch('sol_apply.sdk_apps',side_effect=sdk),patch.dict('sys.modules',{'winreg':registry}),patch.dict('os.environ',{'VT_VM_APPLICATIONS':''}):
                self.assertEqual(discover_vm(),str(target))

    def test_two_successive_record_updates_retain_first_script(self):
        import xml.etree.ElementTree as ET
        from sol_apply import replace_native_record,verify_saved
        from sol_reader import frame_records
        server=ET.fromstring('<Root/>');original=(server,7,{'9-ShellModule.mdata':b'original A','23-ShellModule.mdata':b'original B'})
        native=(server,7,{'9-ShellModule.mdata':b'generated A','23-ShellModule.mdata':b'normalization'})
        version,records=frame_records(replace_native_record(original,native,'9'));first=(server,version,records)
        second_native=(server,7,{'9-ShellModule.mdata':b'normalization','23-ShellModule.mdata':b'generated B'})
        version,records=frame_records(replace_native_record(first,second_native,'23'))
        self.assertEqual(records['9-ShellModule.mdata'],b'generated A')
        self.assertTrue(verify_saved(first,(server,version,records),'23','generated B')['other_records_unchanged'])

    def test_remembered_vm_is_validated_and_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'settings.json';apps=Path(folder)/'Applications'
            with patch('sol_apply.vm_preference_path',return_value=p),patch('sol_apply.sdk_apps',return_value=apps):
                remember_vm(apps)
                with patch.dict('os.environ',{'VT_VM_APPLICATIONS':''}):self.assertEqual(discover_vm(),str(apps))
            self.assertEqual(set(__import__('json').loads(p.read_text())),{'applications'})

    def test_missing_both_ai_inputs_adds_ports_and_generates_no_ai_logic(self):
        target=module();target['inputs']=[r for r in target['inputs'] if r['name'] not in ('aiResult','Label_name')]
        c=default_config();adapted=config_for_module(c,target);plan=plan_application(c,target)
        self.assertTrue(c['use_ai']);self.assertFalse(adapted['use_ai'])
        self.assertEqual({r['name'] for r in plan['added']},{'aiResult','Label_name'})
        self.assertFalse(plan['ai_enabled']);self.assertIn('false',generate_sources(adapted)['UserScript.cs'])
        from script_ui import ScriptPage
        # The variable-import path accepts the same absent compatibility pair.
        self.assertEqual(len(ScriptPage.sol_signals(None,target)),3)

    def test_success_advances_sol_and_keeps_all_flows_available(self):
        from PySide6.QtWidgets import QApplication
        from script_ui import ScriptPage
        app=QApplication.instance() or QApplication([]);p=ScriptPage()
        try:
            a=module();a.update(flow_id='1');b=copy.deepcopy(a);b.update(id='23',flow_id='2',flow='Other')
            p.variables.set_metadata({'path':'original.sol','scripts':[a,b]})
            p.test_finished('apply',{'output':'first.sol','module_id':'9','metadata':{'path':'first.sol','scripts':[a,b]}})
            self.assertEqual(p.variables.metadata['path'],'first.sol');self.assertEqual(p.variables.path,'first.sol')
            p.variables.flow.setCurrentIndex(p.variables.flow.findData('2'))
            self.assertEqual(p.variables.selected_module()['id'],'23')
            p.test_finished('apply',{'output':'second.sol','module_id':'23','metadata':{'path':'second.sol','scripts':[a,b]}})
            self.assertEqual(p.variables.metadata['path'],'second.sol');self.assertEqual(p.variables.selected_module()['id'],'23')
        finally:p.deleteLater();app.processEvents()

if __name__=='__main__':unittest.main()
