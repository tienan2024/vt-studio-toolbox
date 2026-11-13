import copy
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from script_generator import default_config,variable_rows,generate_sources
from sol_apply import plan_application,replace_native_record,verify_saved,verify_archive_payloads,SolApplyError
from sol_reader import frame_records


def module():
    rows=variable_rows(default_config())
    return {'id':'9','flow':'Inspection','name':'Script',
            'inputs':[r for r in rows if r['direction']=='输入'],'outputs':[r for r in rows if r['direction']=='输出']}


class SolApplicationTests(unittest.TestCase):
    def test_existing_bindings_and_no_ai_optional_ports_are_preserved(self):
        c=default_config();target=module();plan=plan_application(c,target)
        self.assertEqual(len(plan['preserved']),12);self.assertEqual(plan['added'],[])
        target['inputs']=[r for r in target['inputs'] if r['name']!='aiResult'];c['use_ai']=False
        self.assertEqual([r['name'] for r in plan_application(c,target)['added']],['aiResult'])
        target['inputs'].append({'name':'未使用Result','type':'int'})
        self.assertEqual(len(plan_application(c,target)['preserved']),11)

    def test_unknown_input_renamed_output_and_type_conflict_cannot_break_bindings(self):
        c=default_config();target=module();target['inputs']=target['inputs'][1:]
        with self.assertRaisesRegex(SolApplyError,'必需输入'):plan_application(c,target)
        c['ports']={'NG_name':'改名输出'}
        with self.assertRaisesRegex(SolApplyError,'下游绑定'):plan_application(c,module())
        c=default_config();target=module();target['inputs'][0]['type']='float'
        with self.assertRaisesRegex(SolApplyError,'类型'):plan_application(c,target)

    def test_native_record_replacement_preserves_all_other_records_and_boundaries(self):
        code=generate_sources(default_config())['UserScript.cs'];server=ET.fromstring('<Root><Bindings source="7"/></Root>')
        original=(server,7,{'9-ShellModule.mdata':b'old','23-ShellModule.mdata':b'untouched','GlobalVarBinding':b'opaque'})
        native=(server,7,{'9-ShellModule.mdata':code.encode(),'23-ShellModule.mdata':b'native-normalization'})
        encoded=replace_native_record(original,native,'9');version,records=frame_records(encoded)
        check=verify_saved(original,(server,version,records),'9',code)
        self.assertTrue(check['other_records_unchanged']);self.assertEqual(records['23-ShellModule.mdata'],b'untouched')
        altered=copy.deepcopy(records);altered['GlobalVarBinding']=b'changed'
        with self.assertRaisesRegex(SolApplyError,'非目标'):verify_saved(original,(server,7,altered),'9',code)
        with self.assertRaisesRegex(SolApplyError,'绑定'):verify_saved(original,(ET.fromstring('<Root/>'),7,records),'9',code)
        with self.assertRaisesRegex(SolApplyError,'完整生成代码'):verify_saved(original,(server,7,records),'9','not saved')
        with self.assertRaisesRegex(SolApplyError,'版本7'):replace_native_record((server,5,original[2]),native,'9')

    def test_packaging_guard_rejects_dropped_resources_or_changed_payloads(self):
        with tempfile.TemporaryDirectory() as folder:
            a,b=Path(folder)/'a.sol',Path(folder)/'b.sol'
            def archive(path,resource):
                with zipfile.ZipFile(path,'w') as z:z.writestr('SolutionFile/MoudleFrame',b'frame');z.writestr('model.bin',resource)
            archive(a,b'unchanged');archive(b,b'unchanged');verify_archive_payloads(a,b)
            archive(b,b'wrong model')
            with self.assertRaises(SolApplyError):verify_archive_payloads(a,b)


if __name__=='__main__':unittest.main()
