from pathlib import Path
import os
import sys
import tempfile
import unittest
from dataclasses import replace

import numpy as np
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from legacy_bridge import ConversionSettings, convert_batch, scan_images, preview_conversion, engine_path
from engine import SynthesisError


@unittest.skipUnless(os.name=='nt','Original VT Studio engine is Windows native')
class LegacyCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.input=self.root/'input'
        self.input.mkdir()
        self.pixels=np.arange(1,13,dtype=np.uint8).reshape(3,4)
        self.file=self.input/'原名.bmp'
        Image.fromarray(self.pixels).save(self.file)
        self.settings=ConversionSettings(str(self.input),str(self.root/'out'),6,5)

    def tearDown(self):
        self.tmp.cleanup()

    def test_engine_hash_and_padding_origin_xml_preserved(self):
        self.assertTrue(engine_path().is_file())
        before=self.file.read_bytes()
        xml=b'<points X="3" Y="2"/>'
        self.file.with_suffix('.xml').write_bytes(xml)
        result=convert_batch(self.settings)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['completed'],1)
        p=Path(result['images'][0])
        self.assertEqual(p.name,'原名.bmp')
        out=np.asarray(Image.open(p))
        self.assertEqual(out.shape,(5,6))
        np.testing.assert_array_equal(out[:3,:4],self.pixels)
        self.assertTrue(np.all(out[3:,:]==0))
        self.assertTrue(np.all(out[:,4:]==0))
        self.assertEqual(p.with_suffix('.xml').read_bytes(),xml)
        self.assertEqual(self.file.read_bytes(),before)

    def test_white_padding_and_crop_preserve_top_left(self):
        result=convert_batch(replace(self.settings,white=True))
        out=np.asarray(Image.open(result['images'][0]))
        self.assertTrue(np.all(out[3:,:]==255))
        self.assertTrue(np.all(out[:,4:]==255))
        crop=convert_batch(replace(self.settings,width=3,height=2))
        np.testing.assert_array_equal(np.asarray(Image.open(crop['images'][0])),self.pixels[:2,:3])
        self.assertNotEqual(result['run_dir'],crop['run_dir'])

    def test_flat_output_and_duplicate_names_rejected(self):
        sub=self.input/'sub';sub.mkdir()
        Image.fromarray(self.pixels).save(sub/'second.bmp')
        result=convert_batch(self.settings)
        self.assertEqual({Path(p).name for p in result['images']},{'原名.bmp','second.bmp'})
        self.assertTrue(all(Path(p).parent.name=='images' for p in result['images']))
        Image.fromarray(self.pixels).save(sub/'原名.bmp')
        with self.assertRaisesRegex(SynthesisError,'同名'):
            scan_images(str(self.input),True)

    def test_nested_output_and_empty_input_rejected(self):
        with self.assertRaisesRegex(SynthesisError,'子文件夹'):
            replace(self.settings,output_root=str(self.input/'out')).validate()
        empty=self.root/'empty';empty.mkdir()
        with self.assertRaisesRegex(SynthesisError,'未找到'):
            convert_batch(replace(self.settings,input_folder=str(empty)))

    def test_xml_name_collision_rejected_without_writing(self):
        sub=self.input/'sub';sub.mkdir()
        Image.fromarray(self.pixels).save(sub/'原名.png')
        self.file.with_suffix('.xml').write_bytes(b'<a/>')
        (sub/'原名.xml').write_bytes(b'<b/>')
        with self.assertRaisesRegex(SynthesisError,'同名 XML'):
            convert_batch(self.settings)
        self.assertFalse((self.root/'out').exists())

    def test_cancel_before_start_creates_no_batch(self):
        result=convert_batch(self.settings,cancelled=lambda:True)
        self.assertEqual(result['status'],'cancelled')
        self.assertFalse((self.root/'out').exists())

    def test_rgb_png_preserved_and_xml_copy_optional(self):
        self.file.unlink()
        rgb=np.arange(36,dtype=np.uint8).reshape(3,4,3)
        Image.fromarray(rgb).save(self.input/'color.png')
        (self.input/'color.xml').write_bytes(b'<points/>')
        result=convert_batch(replace(self.settings,copy_xml=False))
        p=Path(result['images'][0])
        np.testing.assert_array_equal(np.asarray(Image.open(p).convert('RGB'))[:3,:4],rgb)
        self.assertFalse(p.with_suffix('.xml').exists())

    def test_display_preview_matches_small_geometry(self):
        preview,ratio=preview_conversion(Image.fromarray(self.pixels),6,5,True)
        self.assertEqual(ratio,1)
        np.testing.assert_array_equal(np.asarray(preview)[:3,:4],self.pixels)
        self.assertTrue(np.all(np.asarray(preview)[3:,:]==255))


if __name__=='__main__':
    unittest.main(verbosity=2)
