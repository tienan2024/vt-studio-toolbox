from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import (Asset,Settings,SynthesisError,generation_counts,generate_batch,
                    load_recipe,save_recipe)
from pool import PoolEntry,generate_pool_batch,load_pool_recipe


class QuantityTests(unittest.TestCase):
    def setUp(self):
        self.asset=Asset(Image.new('L',(12,12),40),Image.new('L',(12,12),255),190,{'source_ng':'TEST_ONLY.bmp'})
        self.settings=Settings(scale_min=1,scale_max=1,rotation=0,feather=0,samples_per_ok=7,total_samples=5)

    def test_balanced_counts_and_small_total(self):
        self.assertEqual(generation_counts(3,self.settings),[2,2,1])
        self.assertEqual(generation_counts(3,replace(self.settings,total_samples=2)),[1,1,0])
        self.assertEqual(generation_counts(3,replace(self.settings,total_samples=0)),[7,7,7])

    def test_invalid_totals_and_empty_ok_rejected(self):
        for value in (-1,True,1.5,100001):
            with self.subTest(value=value),self.assertRaises(SynthesisError):
                generation_counts(3,replace(self.settings,total_samples=value))
        with self.assertRaises(SynthesisError):
            generation_counts(0,self.settings)

    def test_single_asset_exact_total_distribution_and_recipe(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=[]
            for i in range(3):
                p=root/f'OK-{i}.bmp';Image.new('L',(80,70),180+i).save(p);paths.append(str(p))
            result=generate_batch(paths,self.asset,self.settings,str(root/'out'))
            run=Path(result['run_dir'])
            records=[json.loads(s) for s in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(result['completed'],5)
            self.assertEqual(result['total'],5)
            self.assertEqual(result['quantity_mode'],'total')
            self.assertEqual([Counter(r['source_ok'] for r in records)[p] for p in paths],[2,2,1])
            self.assertEqual(len(list((run/'images').glob('*.bmp'))),5)
            _,settings,_=load_recipe(run/'recipe.json')
            self.assertEqual(settings.total_samples,5)
            old_compatible=root/'per-ok.json'
            save_recipe(old_compatible,self.asset,replace(self.settings,total_samples=0),paths)
            self.assertNotIn('total_samples',json.loads(old_compatible.read_text(encoding='utf-8'))['settings'])

    def test_pool_exact_small_total_skips_zero_allocation_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=[]
            for i in range(2):
                p=root/f'OK-{i}.bmp';Image.new('L',(80,70),180).save(p);paths.append(str(p))
            paths.append(str(root/'unused-missing.bmp'))
            result=generate_pool_batch(paths,[PoolEntry('test','TEST_ONLY.bmp',self.asset)],
                                       replace(self.settings,total_samples=2),str(root/'out'))
            self.assertEqual(result['completed'],2)
            self.assertEqual([p['count'] for p in result['planned_ok_counts']],[1,1,0])
            entries,settings,restored,_=load_pool_recipe(Path(result['run_dir'])/'recipe.json')
            self.assertEqual(settings.total_samples,2)
            self.assertEqual(restored,paths)

    def test_cancel_retains_requested_total_and_completed_count(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'ok.bmp';Image.new('L',(80,70),180).save(p)
            stop=False
            def progress(*args):
                nonlocal stop
                stop=True
            result=generate_pool_batch([str(p)],[PoolEntry('test','TEST_ONLY.bmp',self.asset)],
                                       replace(self.settings,total_samples=9),str(root/'out'),progress,lambda:stop)
            self.assertEqual(result['status'],'cancelled')
            self.assertEqual(result['total'],9)
            self.assertEqual(result['completed'],1)


if __name__=='__main__':
    unittest.main(verbosity=2)
