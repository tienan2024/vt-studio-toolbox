"""RGB regression tests use artificial images, never production training data."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import (Asset, Settings, SynthesisError, asset_dict, asset_from_dict,
                    extract_asset, generate_batch, load_image, load_recipe,
                    save_recipe, synthesize)


class RGBTests(unittest.TestCase):
    def setUp(self):
        self.base = Image.new('RGB', (180, 160), (175, 145, 115))
        ng = np.full((80, 80, 3), (220, 190, 160), dtype=np.uint8)
        ng[30:50, 30:50] = (55, 95, 120)
        self.ng = Image.fromarray(ng)
        self.asset = extract_asset(self.ng, [(25,25),(55,25),(55,55),(25,55)], 'TEST_ONLY_rgb.bmp')
        self.settings = Settings(scale_min=1, scale_max=1, rotation=0, feather=0,
                                 strength_min=1, strength_max=1, samples_per_ok=2)

    def test_color_loader_preserves_rgb_and_expands_palette(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'彩色.bmp'
            self.base.save(path)
            loaded = load_image(path)
            self.assertEqual(loaded.mode, 'RGB')
            np.testing.assert_array_equal(loaded, self.base)
            indexed = self.ng.quantize(colors=8)
            expected = indexed.convert('RGB')
            indexed.save(path)
            loaded = load_image(path)
            self.assertEqual(loaded.mode, 'RGB')
            np.testing.assert_array_equal(loaded, expected)
            Image.new('RGBA', (10,10), (20,40,60,128)).save(path.with_suffix('.png'))
            with self.assertRaises(SynthesisError):
                load_image(path.with_suffix('.png'))
            pal = self.ng.quantize(colors=8)
            pal.save(path.with_suffix('.png'), transparency=0)
            with self.assertRaises(SynthesisError):
                load_image(path.with_suffix('.png'))

    def test_channel_background_avoids_color_cast_outside_defect(self):
        self.assertEqual(self.asset.reference_rgb, (220.,190.,160.))
        output, mask, info = synthesize(self.base, self.asset, self.settings, 4)
        l,t,r,b = info['placement_xyxy']
        # Donor's clean ring equals its channel backgrounds; it must leave the base intact.
        np.testing.assert_array_equal(np.asarray(output)[t,l], (175,145,115))
        np.testing.assert_array_equal(np.asarray(output)[t+10,l+10], np.rint(np.array((175,145,115))*np.array((55,95,120))/np.array((220,190,160))).astype('uint8'))
        self.assertEqual(info['reference_rgb'], [220.,190.,160.])
        self.assertTrue(np.all(np.asarray(output) <= np.asarray(self.base)))
        self.assertEqual(mask.mode, 'L')

    def test_both_modes_deterministic_exact_mask_and_roi(self):
        original, donor = self.base.tobytes(), self.asset.pixels.tobytes()
        for mode in ('darken','texture'):
            with self.subTest(mode=mode):
                settings = replace(self.settings, mode=mode, rotation=25, feather=2,
                                   strength_min=.8, strength_max=.8, roi=(.2,.2,.8,.8))
                output, mask, info = synthesize(self.base, self.asset, settings, 47)
                second, second_mask, second_info = synthesize(self.base, self.asset, settings, 47)
                self.assertEqual(output.mode, 'RGB')
                self.assertEqual(output.size, self.base.size)
                self.assertEqual(output.tobytes(), second.tobytes())
                self.assertEqual(mask.tobytes(), second_mask.tobytes())
                self.assertEqual(info, second_info)
                changed = np.any(np.asarray(output) != np.asarray(self.base), axis=2)
                np.testing.assert_array_equal(changed, np.asarray(mask)>0)
                self.assertEqual(info['changed_pixel_count'], int(changed.sum()))
                y,x = np.nonzero(changed)
                self.assertEqual(info['bbox_xyxy'], [int(x.min()),int(y.min()),int(x.max())+1,int(y.max())+1])
                self.assertTrue(np.all((x>=36)&(x<144)&(y>=32)&(y<128)))
        self.assertEqual(self.base.tobytes(), original)
        self.assertEqual(self.asset.pixels.tobytes(), donor)

    def test_mask_includes_changes_in_only_one_channel(self):
        asset = Asset(Image.new('RGB',(8,8),(175,55,115)), Image.new('L',(8,8),255), 190, {})
        output, mask, info = synthesize(self.base, asset, replace(self.settings, mode='texture'), 2)
        changes = np.asarray(output) != np.asarray(self.base)
        self.assertFalse(changes[...,0].any())
        self.assertTrue(changes[...,1].any())
        self.assertFalse(changes[...,2].any())
        self.assertEqual(info['changed_pixel_count'],64)
        self.assertEqual(np.count_nonzero(np.asarray(mask)),64)

    def test_manual_reference_is_shared_across_rgb_channels(self):
        _,_,info = synthesize(self.base,self.asset,replace(self.settings,reference_gray=200),9)
        self.assertEqual(info['reference_rgb'],[200,200,200])

    def test_embedded_rgb_recipe_and_invalid_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'配方.json'
            save_recipe(path,self.asset,self.settings,[])
            restored,settings,paths=load_recipe(path)
            self.assertEqual(restored.pixels.mode,'RGB')
            self.assertEqual(restored.pixels.tobytes(),self.asset.pixels.tobytes())
            self.assertEqual(restored.reference_rgb,self.asset.reference_rgb)
            one=synthesize(self.base,self.asset,self.settings,1)
            two=synthesize(self.base,restored,settings,1)
            self.assertEqual(one[0].tobytes(),two[0].tobytes())
        data=asset_dict(self.asset)
        for bad in ([1,2], [0,190,160], [220,float('nan'),160], '220,190,160'):
            with self.subTest(bad=bad), self.assertRaises(SynthesisError):
                asset_from_dict({**data,'reference_rgb':bad})
        wrong_mask=replace(self.asset,mask=self.asset.mask.convert('RGB'))
        with self.assertRaises(SynthesisError):
            asset_from_dict(asset_dict(wrong_mask))

    def test_rgb_batch_bmp_header_and_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            path=root/'OK彩色.bmp'; self.base.save(path)
            before=path.read_bytes()
            result=generate_batch([str(path)],self.asset,self.settings,str(root/'output'))
            run=Path(result['run_dir'])
            self.assertEqual(result['completed'],2)
            records=[json.loads(line) for line in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
            for record in records:
                p=run/record['image']
                self.assertEqual(int.from_bytes(p.read_bytes()[28:30],'little'),24)
                with Image.open(p) as im, Image.open(run/record['mask']) as mask:
                    self.assertEqual(im.mode,'RGB')
                    self.assertEqual(im.size,self.base.size)
                    np.testing.assert_array_equal(np.any(np.asarray(im)!=np.asarray(self.base),axis=2), np.asarray(mask)>0)
                self.assertEqual(record['image_mode'],'RGB')
            self.assertEqual(path.read_bytes(),before)

    def test_mode_mismatch_rejected_before_creating_batch(self):
        with self.assertRaisesRegex(SynthesisError,'模式.*不一致'):
            synthesize(self.base.convert('L'),self.asset,self.settings,1)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); path=root/'gray.bmp'; self.base.convert('L').save(path)
            with self.assertRaisesRegex(SynthesisError,'模式.*不一致'):
                generate_batch([str(path)],self.asset,self.settings,str(root/'output'))
            self.assertFalse((root/'output').exists())


if __name__=='__main__':
    unittest.main(verbosity=2)
