import json
from pathlib import Path
import sys
import tempfile
import unittest
from dataclasses import replace

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import (Asset, Settings, SynthesisError, extract_asset, generate_batch,
                    load_gray, load_recipe, save_recipe, synthesize)


class EngineTests(unittest.TestCase):
    def setUp(self):
        yy, xx = np.indices((200, 280))
        self.base = Image.fromarray((170+(xx%13)+(yy%9)).astype(np.uint8))
        donor = Image.new("L", (100, 100), 180)
        a = np.array(donor)
        a[35:65, 30:70] = 45
        self.ng = Image.fromarray(a)
        self.asset = extract_asset(self.ng, [(28, 32), (72, 32), (72, 68), (28, 68)], "test_only_ng.bmp")
        self.settings = Settings(scale_min=0.8, scale_max=1.0, feather=2, roi=(0.2, 0.2, 0.8, 0.8))

    def test_repeatable_mask_exact_and_roi(self):
        out, mask, info = synthesize(self.base, self.asset, self.settings, 42)
        out2, mask2, info2 = synthesize(self.base, self.asset, self.settings, 42)
        self.assertEqual(out.tobytes(), out2.tobytes())
        self.assertEqual(mask.tobytes(), mask2.tobytes())
        self.assertEqual(info, info2)
        changed = np.asarray(out) != np.asarray(self.base)
        np.testing.assert_array_equal(np.asarray(mask) == 255, changed)
        self.assertTrue(changed.any())
        ys, xs = np.nonzero(changed)
        self.assertEqual(info['bbox_xyxy'], [xs.min(), ys.min(), xs.max()+1, ys.max()+1])
        self.assertGreaterEqual(xs.min(), 56)
        self.assertLess(xs.max(), 224)
        self.assertGreaterEqual(ys.min(), 40)
        self.assertLess(ys.max(), 160)
        self.assertEqual(out.size, self.base.size)
        self.assertEqual(out.mode, "L")

    def test_darken_never_brightens_and_source_not_mutated(self):
        source_bytes = self.base.tobytes()
        donor_bytes = self.asset.pixels.tobytes()
        result, _, _ = synthesize(self.base, self.asset, self.settings, 2)
        self.assertTrue(np.all(np.asarray(result) <= np.asarray(self.base)))
        self.assertEqual(source_bytes, self.base.tobytes())
        self.assertEqual(donor_bytes, self.asset.pixels.tobytes())

    def test_polygon_and_feather_stay_in_support(self):
        asset = extract_asset(self.ng, [(30, 30), (70, 30), (50, 70)])
        settings = replace(self.settings, rotation=0, scale_min=1, scale_max=1)
        _, mask, record = synthesize(self.base, asset, settings, 10)
        x, y, r, b = record['placement_xyxy']
        support = np.asarray(asset.mask) > 0
        self.assertFalse(np.any((np.asarray(mask)[y:b, x:r] > 0) & ~support))

    def test_texture_can_transfer_bright_defect(self):
        asset = Asset(Image.new('L', (20, 20), 240), Image.new('L', (20, 20), 255), 180, {})
        settings = replace(self.settings, mode='texture', feather=0, rotation=0)
        out, _, _ = synthesize(self.base, asset, settings, 1)
        self.assertGreater(np.asarray(out).max(), np.asarray(self.base).max())

    def test_rejects_invalid_ranges(self):
        for settings in [replace(self.settings, scale_min=2, scale_max=1),
                         replace(self.settings, strength_min=0),
                         replace(self.settings, roi=(0.8, 0, 0.2, 1)),
                         replace(self.settings, rotation=float('nan')),
                         replace(self.settings, samples_per_ok=1.5)]:
            with self.assertRaises(SynthesisError):
                settings.validate()

    def test_oversized_and_no_change_are_explicit_errors(self):
        with self.assertRaisesRegex(SynthesisError, '放不进'):
            synthesize(self.base, self.asset, replace(self.settings, scale_min=5, scale_max=5), 1)
        asset = Asset(Image.new('L', (20, 20), 255), Image.new('L', (20, 20), 255), 180, {})
        with self.assertRaisesRegex(SynthesisError, '有效像素变化'):
            synthesize(self.base, asset, self.settings, 1)

    def test_grayscale_bmp_header_and_rgb_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'中文.bmp'
            self.base.save(p)
            raw = p.read_bytes()
            self.assertEqual(raw[:2], b'BM')
            self.assertEqual(int.from_bytes(raw[28:30], 'little'), 8)
            self.assertEqual(load_gray(p).mode, 'L')
            Image.new('RGB', (10, 10)).save(p)
            with self.assertRaises(SynthesisError):
                load_gray(p)

    def test_recipe_embeds_donor_and_restores_parameters(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'配方.json'
            save_recipe(p, self.asset, self.settings, ['不存在的底图.bmp'])
            asset, settings, paths = load_recipe(p)
            self.assertEqual(asset.pixels.tobytes(), self.asset.pixels.tobytes())
            self.assertEqual(asset.mask.tobytes(), self.asset.mask.tobytes())
            self.assertEqual(settings.mode, self.settings.mode)
            self.assertEqual(tuple(settings.roi), self.settings.roi)
            self.assertEqual(paths, ['不存在的底图.bmp'])

    def test_unique_batches_manifest_and_source_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'测试底图.bmp'
            self.base.save(p)
            original_bytes = p.read_bytes()
            settings = replace(self.settings, samples_per_ok=2)
            s = generate_batch([str(p)], self.asset, settings, str(Path(folder)/'out'))
            s2 = generate_batch([str(p)], self.asset, settings, str(Path(folder)/'out'))
            self.assertNotEqual(s['run_dir'], s2['run_dir'])
            self.assertEqual(s['completed'], 2)
            run = Path(s['run_dir'])
            records = [json.loads(line) for line in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(records), 2)
            for record in records:
                out = load_gray(run/record['image'])
                mask = Image.open(run/record['mask'])
                self.assertEqual(out.size, self.base.size)
                np.testing.assert_array_equal(np.asarray(mask)>0, np.asarray(out)!=np.asarray(self.base))
                self.assertEqual(record['split_group'], str(p.resolve()))
                self.assertTrue(record['synthetic'])
                self.assertTrue((run/record['annotation']).is_file())
            self.assertEqual(p.read_bytes(), original_bytes)
            self.assertEqual(json.loads((run/'summary.json').read_text(encoding='utf-8'))['status'], 'complete')

    def test_cancel_preserves_only_completed_records(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'ok.bmp'
            self.base.save(p)
            count = [0]
            def progress(done, *_):
                count[0] = done
            summary = generate_batch([str(p)], self.asset, replace(self.settings, samples_per_ok=5),
                      str(Path(folder)/'out'), progress=progress, cancelled=lambda: count[0]>=1)
            self.assertEqual(summary['status'], 'cancelled')
            self.assertEqual(summary['completed'], 1)
            manifest = Path(summary['run_dir'])/'manifest.jsonl'
            self.assertEqual(len(manifest.read_text(encoding='utf-8').splitlines()), 1)
            self.assertEqual(len(list((Path(summary['run_dir'])/'images').glob('*.bmp'))), 1)

    def test_failed_preflight_leaves_no_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'outputs'
            with self.assertRaises(FileNotFoundError):
                generate_batch([str(Path(folder)/'missing.bmp')], self.asset, self.settings, str(root))
            self.assertFalse(root.exists())

    def test_16bit_and_empty_polygon_rejected(self):
        with self.assertRaises(SynthesisError):
            extract_asset(self.ng, [(1, 1), (1, 1), (1, 1)])
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'16bit.png'
            Image.fromarray(np.zeros((10,10), dtype=np.uint16)).save(p)
            with self.assertRaises(SynthesisError):
                load_gray(p)


if __name__ == '__main__':
    unittest.main(verbosity=2)
