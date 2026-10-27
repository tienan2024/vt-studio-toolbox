import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine import extract_asset,Settings,save_recipe


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.inputs=self.root/'input';self.inputs.mkdir()
        self.ok=self.inputs/'真实原名.bmp'
        Image.new('L',(240,220),180).save(self.ok)
        self.ng=self.root/'ng.bmp'
        ng=Image.new('L',(150,150),190)
        ImageDraw.Draw(ng).ellipse((55,50,95,95),fill=35)
        ng.save(self.ng)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self,*args,code=0):
        portable=os.environ.get('VT_TOOLBOX_CLI_BINARY')
        prefix=[portable] if portable else [sys.executable,'-X','utf8',str(ROOT/'cli.py')]
        result=subprocess.run([*prefix,*map(str,args)],
            capture_output=True,text=True,encoding='utf-8',timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.assertEqual(result.returncode,code,result.stdout+result.stderr)
        value=json.loads(result.stdout)
        self.assertEqual(value['schema'],'vt-toolbox-cli/1')
        self.assertEqual(value['exit_code'],code)
        return value,result

    def test_info_schema_and_inspect(self):
        data,_=self.run_cli('info')
        self.assertTrue(data['data']['headless'])
        schema,_=self.run_cli('schema')
        self.assertIn('synthesize',schema['data']['commands'])
        info,_=self.run_cli('inspect',self.ok)
        self.assertEqual(info['data']['width'],240)
        self.assertTrue(info['data']['defect_input_compatible'])

    def test_convert_json_and_original_pixels(self):
        data,result=self.run_cli('convert','--input',self.inputs,'--output',self.root/'converted',
            '--width',260,'--height',240,'--fill','white')
        self.assertEqual(result.stderr,'')
        output=Path(data['data']['images'][0])
        self.assertEqual(output.name,self.ok.name)
        with Image.open(output) as im:
            self.assertEqual(im.size,(260,240))
            values=np.asarray(im)
            self.assertTrue(np.all(values[:220,:240]==180))
            self.assertTrue(np.all(values[220:,:]==255))

    def test_asset_to_batch_and_progress_stderr_only(self):
        asset=self.root/'asset.json'
        self.run_cli('extract-asset','--ng',self.ng,'--rect','40,35,110,110','--output',asset)
        result,process=self.run_cli('--progress','synthesize','--asset',asset,'--ok',self.ok,
            '--output',self.root/'defects','--count',2,'--seed',17,'--roi-normalized','0.1,0.1,0.9,0.9')
        self.assertEqual(result['data']['completed'],2)
        self.assertIn('progress',process.stderr)
        run=Path(result['data']['run_dir'])
        records=[json.loads(line) for line in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(records),2)
        for item in records:
            with Image.open(run/item['image']) as im,Image.open(run/item['mask']) as mask:
                self.assertEqual(im.size,(240,220))
                np.testing.assert_array_equal(np.asarray(mask)>0,np.asarray(im)!=180)

    def test_saved_gui_recipe_and_override(self):
        with Image.open(self.ng) as im:
            asset=extract_asset(im,[(40,35),(110,35),(110,110),(40,110)],str(self.ng))
        recipe=self.root/'recipe.json'
        save_recipe(recipe,asset,Settings(samples_per_ok=5,roi=(.2,.2,.8,.8)),[str(self.ok)])
        check,_=self.run_cli('validate-recipe',recipe)
        self.assertTrue(check['data']['valid'])
        output,_=self.run_cli('synthesize','--recipe',recipe,'--output',self.root/'generated','--count',1)
        self.assertEqual(output['data']['completed'],1)
        run=Path(output['data']['run_dir'])
        record=json.loads((run/'manifest.jsonl').read_text(encoding='utf-8').strip())
        self.assertEqual(record['allowed_roi_xyxy'],[48,44,192,176])

    def test_errors_are_json_and_reports_never_overwrite(self):
        value,_=self.run_cli('convert','--input',self.inputs,code=2)
        self.assertFalse(value['ok'])
        self.run_cli('extract-asset','--ng',self.ng,'--rect=-1,0,50,50',
                     '--output',self.root/'bad.json',code=1)
        self.assertFalse((self.root/'bad.json').exists())
        report=self.root/'报告.json'
        result,_=self.run_cli('--json-out',report,'inspect',self.ok)
        self.assertEqual(json.loads(report.read_text(encoding='utf-8')),result)
        before=report.read_bytes()
        self.run_cli('--json-out',report,'info',code=1)
        self.assertEqual(report.read_bytes(),before)

    def test_partial_conversion_has_nonzero_machine_status(self):
        (self.inputs/'invalid.bmp').write_bytes(b'not a bitmap')
        value,_=self.run_cli('convert','--input',self.inputs,'--output',self.root/'partial',
            '--width',260,'--height',240,code=3)
        self.assertFalse(value['ok'])
        self.assertEqual(value['data']['status'],'partial')

    def test_rgb_asset_recipe_batch_and_mode_mismatch(self):
        Image.new('RGB',(240,220),(180,155,120)).save(self.ok)
        ng=Image.new('RGB',(150,150),(210,190,170))
        ImageDraw.Draw(ng).ellipse((55,50,95,95),fill=(40,70,95))
        ng.save(self.ng)
        inspected,_=self.run_cli('inspect',self.ok)
        self.assertTrue(inspected['data']['defect_input_compatible'])
        self.assertEqual(inspected['data']['effective_mode'],'RGB')
        asset=self.root/'rgb-asset.json'
        extracted,_=self.run_cli('extract-asset','--ng',self.ng,'--rect','40,35,110,110','--output',asset)
        self.assertEqual(extracted['data']['image_mode'],'RGB')
        batch,_=self.run_cli('synthesize','--asset',asset,'--ok',self.ok,
                             '--output',self.root/'rgb-output','--count',2)
        run=Path(batch['data']['run_dir'])
        checked,_=self.run_cli('validate-recipe',run/'recipe.json')
        self.assertEqual(checked['data']['asset_mode'],'RGB')
        with Image.open(self.ok) as original:
            pixels=np.asarray(original)
        records=[json.loads(line) for line in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(records),2)
        for record in records:
            self.assertEqual(record['image_mode'],'RGB')
            output=run/record['image']
            self.assertEqual(int.from_bytes(output.read_bytes()[28:30],'little'),24)
            with Image.open(output) as im,Image.open(run/record['mask']) as mask:
                np.testing.assert_array_equal(np.any(np.asarray(im)!=pixels,axis=2), np.asarray(mask)>0)
        Image.new('L',(240,220),180).save(self.ok)
        rejected,_=self.run_cli('synthesize','--asset',asset,'--ok',self.ok,
                              '--output',self.root/'mismatch-output','--count',1,code=1)
        self.assertIn('不一致',rejected['error'])
        self.assertFalse((self.root/'mismatch-output').exists())

    def test_multiple_assets_with_individual_regions_and_pool_recipe(self):
        gray_asset=self.root/'gray-asset.json'
        self.run_cli('extract-asset','--ng',self.ng,'--rect','40,35,110,110',
                     '--roi-normalized','.1,.1,.7,.7','--output',gray_asset)
        rgb_ok=self.root/'RGB_OK.bmp';Image.new('RGB',(240,220),(180,155,120)).save(rgb_ok)
        rgb_ng=self.root/'RGB_NG.bmp'
        ng=Image.new('RGB',(150,150),(210,190,170))
        ImageDraw.Draw(ng).ellipse((55,50,95,95),fill=(40,70,95));ng.save(rgb_ng)
        rgb_asset=self.root/'rgb-asset.json'
        self.run_cli('extract-asset','--ng',rgb_ng,'--rect','40,35,110,110',
                     '--roi-normalized','.3,.2,.9,.8','--output',rgb_asset)
        result,_=self.run_cli('synthesize','--assets',gray_asset,rgb_asset,'--ok',self.ok,rgb_ok,
                             '--count',2,'--output',self.root/'pool-output')
        self.assertEqual(result['data']['pool_entries'],2)
        self.assertEqual(result['data']['completed'],4)
        run=Path(result['data']['run_dir'])
        records=[json.loads(line) for line in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
        for record in records:
            expected=[.1,.1,.7,.7] if record['image_mode']=='L' else [.3,.2,.9,.8]
            self.assertEqual(record['source_roi_normalized'],expected)
            self.assertEqual(record['pool_entry_id'],'asset-001' if record['image_mode']=='L' else 'asset-002')
        checked,_=self.run_cli('validate-recipe',run/'recipe.json')
        self.assertEqual(checked['data']['pool_entries'],2)
        reused,_=self.run_cli('synthesize','--recipe',run/'recipe.json','--count',1,
                             '--output',self.root/'pool-reused')
        self.assertEqual(reused['data']['completed'],2)
        single,_=self.run_cli('synthesize','--asset',gray_asset,'--ok',self.ok,'--count',1,
                             '--output',self.root/'single-with-region')
        line=(Path(single['data']['run_dir'])/'manifest.jsonl').read_text(encoding='utf-8').strip()
        self.assertEqual(json.loads(line)['allowed_roi_xyxy'],[24,22,168,154])

    def test_unmatched_pool_and_invalid_asset_region_fail_without_output(self):
        asset=self.root/'asset.json'
        self.run_cli('extract-asset','--ng',self.ng,'--rect','40,35,110,110','--output',asset)
        Image.new('RGB',(240,220),(180,150,120)).save(self.ok)
        result,_=self.run_cli('synthesize','--assets',asset,'--ok',self.ok,'--output',self.root/'unmatched',code=1)
        self.assertIn('匹配失败',result['error'])
        self.assertFalse((self.root/'unmatched').exists())
        self.run_cli('extract-asset','--ng',self.ng,'--rect','40,35,110,110',
                     '--roi-normalized','0,0,1.5,1','--output',self.root/'invalid-asset.json',code=1)
        self.assertFalse((self.root/'invalid-asset.json').exists())

    def test_exact_total_pool_recipe_reuse_and_per_ok_override(self):
        asset=self.root/'asset.json'
        self.run_cli('extract-asset','--ng',self.ng,'--rect','40,35,110,110','--output',asset)
        second=self.root/'second-ok.bmp';Image.new('L',(240,220),180).save(second)
        result,_=self.run_cli('synthesize','--assets',asset,'--ok',self.ok,second,'--total',5,
                             '--output',self.root/'total-output')
        self.assertEqual(result['data']['completed'],5)
        self.assertEqual(result['data']['total'],5)
        self.assertEqual([p['count'] for p in result['data']['planned_ok_counts']],[3,2])
        run=Path(result['data']['run_dir'])
        self.assertEqual(len(list((run/'images').glob('*.bmp'))),5)
        checked,_=self.run_cli('validate-recipe',run/'recipe.json')
        self.assertEqual(checked['data']['settings']['total_samples'],5)
        reused,_=self.run_cli('synthesize','--recipe',run/'recipe.json','--output',self.root/'reuse')
        self.assertEqual(reused['data']['completed'],5)
        override,_=self.run_cli('synthesize','--recipe',run/'recipe.json','--count',1,
                               '--output',self.root/'per-ok-override')
        self.assertEqual(override['data']['completed'],2)
        single,_=self.run_cli('synthesize','--asset',asset,'--ok',self.ok,second,'--total',3,
                             '--output',self.root/'single-total')
        self.assertEqual(single['data']['completed'],3)

    def test_quantity_arguments_are_exclusive_and_validate_total(self):
        asset=self.root/'asset.json'
        self.run_cli('extract-asset','--ng',self.ng,'--rect','40,35,110,110','--output',asset)
        self.run_cli('synthesize','--asset',asset,'--ok',self.ok,'--total',5,'--count',2,
                     '--output',self.root/'ambiguous',code=2)
        for total in ('0','-1','100001'):
            self.run_cli('synthesize','--asset',asset,'--ok',self.ok,'--total',total,
                         '--output',self.root/'invalid-total',code=1)
        self.assertFalse((self.root/'invalid-total').exists())

    def test_multiple_roi_boxes_and_xml_export_controls(self):
        asset=self.root/'regions.json'
        regions='0.05,0.05,0.45,0.45;0.55,0.55,0.95,0.95'
        self.run_cli('extract-asset','--ng',self.ng,'--rect','45,40,105,105',
                     '--roi-regions',regions,'--output',asset)
        result,_=self.run_cli('synthesize','--assets',asset,'--ok',self.ok,'--total',6,
                             '--output',self.root/'multi-boxes')
        run=Path(result['data']['run_dir'])
        records=[json.loads(s) for s in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(records),6)
        self.assertEqual(len(list((run/'images').glob('*.xml'))),6)
        for record in records:
            self.assertEqual(len(record['allowed_rois_xyxy']),2)
            l,t,r,b=record['placement_xyxy'];rl,rt,rr,rb=record['allowed_roi_xyxy']
            self.assertTrue(rl<=l<r<=rr and rt<=t<b<=rb)
        checked,_=self.run_cli('validate-recipe',run/'recipe.json')
        self.assertEqual(len(checked['data']['entries'][0]['roi_regions_normalized']),2)
        disabled,_=self.run_cli('synthesize','--recipe',run/'recipe.json','--total',1,'--xml','none',
                               '--output',self.root/'no-xml')
        self.assertFalse(list((Path(disabled['data']['run_dir'])/'images').glob('*.xml')))
        self.run_cli('synthesize','--asset',asset,'--ok',self.ok,'--roi-regions',regions,
                     '--roi-normalized','0,0,1,1','--output',self.root/'ambiguous-roi',code=2)


if __name__=='__main__':
    unittest.main(verbosity=2)
