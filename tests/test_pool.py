from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine import Asset,Settings,SynthesisError,save_recipe
from pool import (PoolEntry,choose_sample,generate_pool_batch,save_pool_recipe,
                  load_pool_recipe,POOL_SCHEMA)


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.base=Image.new('L',(200,180),180)
        self.a=Asset(Image.new('L',(20,20),40),Image.new('L',(20,20),255),190,{'source_ng':'a.bmp'})
        self.b=Asset(Image.new('L',(20,20),90),Image.new('L',(20,20),255),190,{'source_ng':'b.bmp'})
        self.entries=[PoolEntry('a','a.bmp',self.a,(.1,.1,.4,.7)),PoolEntry('b','b.bmp',self.b,(.6,.2,.9,.8))]
        self.settings=Settings(scale_min=1,scale_max=1,rotation=0,feather=0,samples_per_ok=2)

    def test_filters_mode_fit_and_keeps_selected_roi(self):
        rgb=Asset(Image.new('RGB',(20,20),(30,60,90)),Image.new('L',(20,20),255),190,{})
        huge=replace(self.a,pixels=Image.new('L',(700,700),40),mask=Image.new('L',(700,700),255))
        entries=[PoolEntry('rgb','rgb',rgb),PoolEntry('huge','huge',huge),self.entries[1]]
        out,mask,record=choose_sample(self.base,entries,self.settings,4)
        self.assertEqual(record['pool_entry_id'],'b')
        self.assertEqual(record['allowed_roi_xyxy'],[120,36,180,144])
        changed=np.asarray(out)!=np.asarray(self.base)
        np.testing.assert_array_equal(changed,np.asarray(mask)>0)
        y,x=np.nonzero(changed)
        self.assertTrue(np.all((x>=120)&(x<180)&(y>=36)&(y<144)))

    def test_seeded_selection_uses_both_donors_and_is_repeatable(self):
        seen=set()
        for seed in range(20):
            one=choose_sample(self.base,self.entries,self.settings,seed)
            two=choose_sample(self.base,self.entries,self.settings,seed)
            self.assertEqual(one[0].tobytes(),two[0].tobytes())
            self.assertEqual(one[2],two[2])
            seen.add(one[2]['pool_entry_id'])
        self.assertEqual(seen,{'a','b'})

    def test_unmatched_ok_refuses_before_creating_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'rgb.bmp'
            Image.new('RGB',(200,180),(180,140,100)).save(p)
            with self.assertRaisesRegex(SynthesisError,'rgb.bmp.*匹配失败'):
                generate_pool_batch([str(p)],self.entries,self.settings,str(root/'output'))
            self.assertFalse((root/'output').exists())

    def test_mixed_ok_modes_match_their_own_pool_entries(self):
        rgb=Asset(Image.new('RGB',(20,20),(30,60,90)),Image.new('L',(20,20),255),190,{'source_ng':'rgb-ng.bmp'})
        entries=[self.entries[0],PoolEntry('rgb','rgb-ng.bmp',rgb,(.2,.2,.8,.8))]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);gray=root/'gray.bmp';color=root/'rgb.bmp'
            self.base.save(gray);Image.new('RGB',(200,180),(180,150,120)).save(color)
            before=[p.read_bytes() for p in (gray,color)]
            result=generate_pool_batch([str(gray),str(color)],entries,self.settings,str(root/'output'))
            run=Path(result['run_dir'])
            records=[json.loads(s) for s in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(records),4)
            self.assertEqual(result['donor_usage'],{'a':2,'rgb':2})
            for record in records:
                self.assertEqual(record['pool_entry_id'],'a' if record['image_mode']=='L' else 'rgb')
                with Image.open(run/record['image']) as image:
                    self.assertEqual(image.mode,record['image_mode'])
                self.assertIn('source_roi_normalized',record)
            self.assertEqual([p.read_bytes() for p in (gray,color)],before)

    def test_pool_and_legacy_recipes_restore_embedded_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pool=root/'pool.json'
            save_pool_recipe(pool,self.entries,self.settings,['missing-ok.bmp'],['pending-ng.bmp'])
            entries,settings,paths,pending=load_pool_recipe(pool)
            self.assertEqual(len(entries),2)
            self.assertEqual(entries[1].asset.pixels.tobytes(),self.b.pixels.tobytes())
            self.assertEqual(entries[1].roi,self.entries[1].roi)
            self.assertEqual(pending[0]['path'],'pending-ng.bmp')
            self.assertEqual(paths,['missing-ok.bmp'])
            legacy=root/'legacy.json'
            save_recipe(legacy,self.a,replace(self.settings,roi=(.2,.2,.8,.8)),[])
            loaded,_,_,_=load_pool_recipe(legacy)
            self.assertEqual(loaded[0].roi,(.2,.2,.8,.8))
            data=json.loads(pool.read_text(encoding='utf-8'))
            self.assertEqual(data['schema'],POOL_SCHEMA)
            data['entries'][1]['id']=data['entries'][0]['id']
            pool.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(SynthesisError):
                load_pool_recipe(pool)

    def test_cancel_keeps_only_finished_samples_and_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'ok.bmp';self.base.save(p)
            stop=False
            def progress(done,total,name):
                nonlocal stop
                stop=True
            result=generate_pool_batch([str(p)],self.entries,replace(self.settings,samples_per_ok=5),
                                       str(root/'output'),progress,lambda:stop)
            self.assertEqual(result['status'],'cancelled')
            self.assertEqual(result['completed'],1)
            self.assertEqual(sum(result['donor_usage'].values()),1)
            self.assertEqual(len((Path(result['run_dir'])/'manifest.jsonl').read_text(encoding='utf-8').splitlines()),1)

    def test_processing_failure_preserves_manifest_and_failed_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'ok.bmp';self.base.save(p)
            def broken_progress(*args):
                raise OSError('TEST_ONLY disk or progress failure')
            with self.assertRaises(SynthesisError) as caught:
                generate_pool_batch([str(p)],self.entries,self.settings,str(root/'output'),broken_progress)
            run=Path(caught.exception.run_dir)
            summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['status'],'failed')
            self.assertEqual(summary['completed'],1)
            self.assertEqual(len((run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()),1)


if __name__=='__main__':
    unittest.main(verbosity=2)
