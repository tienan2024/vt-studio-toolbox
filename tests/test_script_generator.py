import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from script_generator import (default_config,validate_config,generate_sources,user_regions,
    save_script,run_cases,run_regression,compiler_path,parse_ngtype,ScriptError,OUTPUTS)


class ScriptGeneratorTests(unittest.TestCase):
    def test_product_regression_and_real_example(self):
        c=default_config();report=run_regression(c)
        self.assertEqual(report['total'],18);self.assertEqual(report['passed'],18)
        result=run_cases(c,[{'aiResult':0,'Label_name':['污点','胶滴','胶滴','胶滴','污点','胶滴','接头']}])['results'][0]
        self.assertTrue(result['process_return']);self.assertEqual(result['outputs']['outResult_index'],'0|0|1|1|1')
        self.assertEqual(result['outputs']['NG_name'],'污点')
        self.assertEqual(set(result['outputs']),set(n for n,t in OUTPUTS))
        self.assertRegex(result['outputs']['NG_imgName'],r'^\(100\)污点_\d{14}_\d{3}$')

    def test_no_ai_preserves_ports_but_does_not_read_labels(self):
        c=default_config();c['use_ai']=False
        results=run_cases(c,[{'aiResult':0,'Label_name':None,'label_read_status':1},
                             {'aiResult':0,'Label_name':['未知'],'全局小污点Result':0}])['results']
        self.assertEqual([r['label_read_calls'] for r in results],[0,0]);self.assertTrue(all(r['process_return'] for r in results))
        self.assertEqual(results[1]['outputs']['outResult_index'],'0|1|1|1|1')
        source=generate_sources(c)['UserProperty.cs']
        self.assertIn('int aiResult',source);self.assertIn('string[] Label_name',source)
        self.assertNotIn('ModuRunTime',source)
        c['signals']=[];c['aliases']=[]
        self.assertTrue(run_cases(c,[{'aiResult':0}])['results'][0]['process_return'])

    def test_unknown_labels_do_not_become_other_types_and_trim_order(self):
        c=default_config()
        rows=run_cases(c,[{'aiResult':0,'Label_name':['接头污点','未知',' 未知 ']},
                          {'NGtype':' 接头 - 污点 ','aiResult':0,'Label_name':[' 污点 ','接头']},
                          {'NGtype':'-污点','全局小污点Result':0},
                          {'NGtype':'OK-污点','aiResult':0,'Label_name':['OK','污点']}])['results']
        self.assertFalse(rows[0]['process_return']);self.assertEqual(rows[0]['outputs']['outResult_index'],'1|0|1|1|1')
        self.assertEqual(rows[0]['outputs']['NG_name'],'分类或配置异常；接头；AI异常，标签未匹配NGtype：未知')
        self.assertEqual(rows[1]['outputs']['NG_name'],'接头');self.assertEqual(rows[1]['outputs']['outResult_index'],'0|0')
        self.assertFalse(rows[2]['process_return']);self.assertEqual(rows[2]['outputs']['outResult_index'],'0|0')
        self.assertEqual(rows[3]['outputs']['NG_name'],'OK')  # first NG named OK must not be replaced

    def test_buffer_validations_and_capacity_boundary(self):
        c=default_config()
        rows=run_cases(c,[{'aiResult':0,'Label_name':['污点']*4096},
                          {'aiResult':0,'Label_name':['污点']*4097},
                          {'aiResult':0,'Label_name':['污点'],'label_count':-1},
                          {'aiResult':1,'Label_name':None,'label_read_status':1}])['results']
        self.assertTrue(rows[0]['process_return']);self.assertFalse(rows[1]['process_return']);self.assertFalse(rows[2]['process_return'])
        self.assertEqual(rows[3]['label_read_calls'],0)

    def test_independent_or_and_safe_literal_generation(self):
        c=default_config();c['signals'].append({'name':'另一污点Result','type':'污点'})
        c['aliases']=[{'match':'exact','value':'标签"\\测试','type':'接头'}]
        rows=run_cases(c,[{'aiResult':0,'Label_name':['标签"\\测试']},
                          {'另一污点Result':0,'全局小污点Result':1}])['results']
        self.assertEqual(rows[0]['outputs']['outResult_index'],'1|0|1|1|1');self.assertTrue(rows[1]['process_return'])
        self.assertEqual(rows[1]['outputs']['outResult_index'],'0|1|1|1|1')

    def test_invalid_configuration_and_input_rejected(self):
        self.assertEqual(parse_ngtype(' 污点 - 接头 - 导流层缺失 '),['污点','接头','导流层缺失'])
        for text in ('','污点--接头','污点-','污点-污点'):
            with self.assertRaises(ScriptError):parse_ngtype(text)
        original=default_config()
        variants=[]
        for signals in ([{'name':'aiResult','type':'污点'}],[{'name':'不合法-Result','type':'污点'}],
                        [{'name':'FooResult','type':'不存在'}],[{'name':'FooResult','type':'污点'}]*2):
            c=copy.deepcopy(original);c['signals']=signals;variants.append(c)
        for types in (['污点','污点'],['污点-接头'],[],['']):
            c=copy.deepcopy(original);c['types']=types;variants.append(c)
        for c in variants:
            with self.assertRaises(ScriptError):validate_config(c)
        with self.assertRaises(ScriptError):run_cases(original,[{'speed':2**40}])

    def test_single_cs_and_preserve_only_user_regions(self):
        c=default_config();source=generate_sources(c)['UserScript.cs']
        source=source.replace('isNG |= 全局小污点Result == 0;','isNG |= false; // preserved')
        regions=user_regions(source);regenerated=generate_sources(c,source)['UserScript.cs']
        self.assertEqual(user_regions(regenerated),regions)
        legacy=source.replace('// USER CODE BEGIN IndependentJudge','/* 用户NG判断代码开始 */').replace('// USER CODE END IndependentJudge','/* 用户NG判断代码结束 */').replace('// USER CODE BEGIN LabelNormalize','/* 用户AI标签归一化开始 */').replace('// USER CODE END LabelNormalize','/* 用户AI标签归一化结束 */')
        self.assertEqual(user_regions(legacy),regions)
        self.assertEqual(run_cases(c,[{'全局小污点Result':0}],source)['results'][0]['outputs']['outResult_index'],'1|1|1|1|1')
        with self.assertRaises(ScriptError):user_regions('no markers')
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'UserScript.cs';save_script(c,out,source)
            self.assertIn('preserved',out.read_text(encoding='utf-8-sig'))
            self.assertEqual([p.name for p in Path(folder).iterdir()],['UserScript.cs'])
            sources=generate_sources(c,source);sources['UserScript.cs']=out.read_text(encoding='utf-8-sig')
            self.assertTrue(run_cases(c,[{}],sources=sources)['results'][0]['process_return'])
            with self.assertRaises(ScriptError):save_script(c,out)

    def test_generated_source_compiles_against_installed_vm_sdk(self):
        sdk=Path('D:/VM/VisionMaster4.4.0/Applications/Module(sp)/x64/Logic/ShellModule')
        if not (sdk/'Script.Methods.dll').is_file():self.skipTest('本机VM 4.4 SDK不可用')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sources=generate_sources(default_config())
            for n,s in sources.items():(root/n).write_text(s,encoding='utf-8-sig')
            result=subprocess.run([str(compiler_path()),'/nologo','/utf8output','/target:library','/out:'+str(root/'Script.dll'),
                '/r:'+str(sdk/'Script.Methods.dll'),'/r:'+str(sdk/'Script.Support.dll')]+[str(root/n) for n in sources],
                capture_output=True,encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


class ScriptCLITests(unittest.TestCase):
    def cli(self,*args,code=0):
        binary=os.environ.get('VT_TOOLBOX_CLI_BINARY');prefix=[binary] if binary else [sys.executable,'-X','utf8',str(ROOT/'cli.py')]
        r=subprocess.run(prefix+list(map(str,args)),capture_output=True,encoding='utf-8',timeout=40,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.assertEqual(r.returncode,code,r.stdout+r.stderr);return json.loads(r.stdout)

    def test_generate_test_and_reject_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);template=self.cli('script-template')['data']
            self.assertEqual(template['schema'],'vt-script-product/1')
            config=root/'product.json';self.cli('script-template','--output',config)
            self.assertEqual(json.loads(config.read_text(encoding='utf-8')),template)
            generated=self.cli('script-code','--config',config,'--output',root/'UserScript.cs')
            self.assertTrue(generated['ok']);self.assertTrue((root/'UserScript.cs').is_file())
            self.cli('script-code','--output',root/'UserScript.cs',code=1)
            result=self.cli('script-test','--config',config,'--regression')['data']
            self.assertEqual(result['passed'],result['total'])
            cases=root/'cases.json';cases.write_text('[{"aiResult":0,"Label_name":["接头"]}]',encoding='utf-8')
            result=self.cli('script-test','--config',config,'--cases',cases)['data']
            self.assertEqual(result['results'][0]['outputs']['outResult_index'],'1|0|1|1|1')
