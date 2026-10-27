from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import Asset,Settings,SynthesisError,synthesize
from pool import PoolEntry,save_pool_recipe,load_pool_recipe,choose_sample


class MultiRegionTests(unittest.TestCase):
    def setUp(self):
        self.base=Image.new('L',(240,200),180)
        self.asset=Asset(Image.new('L',(12,12),40),Image.new('L',(12,12),255),190,{})
        self.regions=((.05,.1,.3,.4),(.7,.6,.95,.9))
        self.settings=Settings(scale_min=1,scale_max=1,rotation=0,feather=0,rois=self.regions)

    def test_no_placement_in_gap_and_both_boxes_used(self):
        used=set()
        for seed in range(20):
            output,mask,record=synthesize(self.base,self.asset,self.settings,seed)
            box=record['allowed_roi_xyxy'];l,t,r,b=record['placement_xyxy']
            self.assertTrue(box[0]<=l<r<=box[2] and box[1]<=t<b<=box[3])
            used.add(record['selected_roi_index'])
            changed=np.asarray(output)!=np.asarray(self.base)
            np.testing.assert_array_equal(changed,np.asarray(mask)>0)
            self.assertEqual(output.tobytes(),synthesize(self.base,self.asset,self.settings,seed)[0].tobytes())
        self.assertEqual(used,{0,1})

    def test_too_small_box_skipped_and_all_small_rejected(self):
        settings=replace(self.settings,rois=((0,0,.01,.01),self.regions[1]))
        self.assertEqual(synthesize(self.base,self.asset,settings,2)[2]['selected_roi_index'],1)
        with self.assertRaisesRegex(SynthesisError,'所有允许范围'):
            synthesize(self.base,self.asset,replace(settings,rois=((0,0,.01,.01),)),2)

    def test_pool_recipe_keeps_per_donor_boxes(self):
        entry=PoolEntry('test','TEST_ONLY',self.asset,self.regions[0],self.regions)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'recipe.json'
            save_pool_recipe(path,[entry],self.settings,[])
            loaded,settings,_,_=load_pool_recipe(path)
            self.assertEqual(loaded[0].rois,self.regions)
            _,_,record=choose_sample(self.base,loaded,settings,3)
            self.assertEqual(record['source_rois_normalized'],[list(r) for r in self.regions])
        for regions in ([(0,0,1,1)]*65,[(0,0,2,1)],[(0,0,float('nan'),1)]):
            with self.assertRaises(SynthesisError):
                replace(self.settings,rois=regions).validate()
