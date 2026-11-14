import sys,unittest
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from camera_model import CameraSettings,CameraError,workflow_settings,calculate
from camera_transaction import compare
from test_camera import FakeCamera


class MeasuredCycleTests(unittest.TestCase):
    def example(self,**changes):
        s=CameraSettings(precision_source='precision',line_y_source='square',sensor_width=2048,
            target_width_mm=40,target_length_mm=60,x_mm_per_px=.02,y_mm_per_px=.02,
            frequency_strategy='cycle',auto_frequency=True,cycle_travel_mm=90,products_per_minute=300,frequency_tolerance_percent=15)
        return replace(s,**changes)

    def test_unknown_distance_keeps_optics_but_never_recommends_factors_or_allows_write(self):
        s=workflow_settings();p=calculate(s);m=p['metrics']
        self.assertTrue(m['frequency_pending']);self.assertIsNone(m['frequency_solution'])
        for key in ('line_triggers_per_cycle','required_line_rate_hz','cycle_idle_available','encoder_counts_per_mm'):
            self.assertIsNone(m[key])
        self.assertEqual(m['height'],3800);self.assertAlmostEqual(m['working_distance_mm'],184.151785714)
        self.assertFalse({'PreDivider','Multiplier','PostDivider'} & {n['key'] for n in p['nodes']})
        c=FakeCamera();report=compare(c,s)
        self.assertFalse(report['ready']);self.assertTrue(any('每周期实际走料' in e for e in report['errors']))
        self.assertFalse(c.commands)

    def test_picture_example_uses_small_factors_and_reports_approximation(self):
        p=calculate(self.example());m=p['metrics'];self.assertFalse(p['blocking'])
        self.assertAlmostEqual(m['encoder_counts_per_mm'],1000/90)
        self.assertAlmostEqual(m['material_cycle_fraction'],2/3)
        self.assertAlmostEqual(m['material_encoder_counts'],1000*2/3)
        self.assertEqual(m['square_pixel_product_lines'],3000);self.assertEqual(m['target_cycle_line_count'],4500)
        self.assertEqual(m['material_height_px'],3334);self.assertEqual(m['line_triggers_per_cycle'],5000)
        self.assertEqual(m['frequency_solution']['ratio'],5)
        self.assertEqual((p['settings']['pre_divider'],p['settings']['multiplier'],p['settings']['post_divider']),(1,5,1))
        self.assertAlmostEqual(m['actual_y_mm_per_px'],.018);self.assertAlmostEqual(m['y_sampling_error_percent'],-10)
        strict=calculate(self.example(frequency_tolerance_percent=1))
        self.assertTrue(any('纵向精度' in e for e in strict['blocking']))

    def test_capacity_never_inflates_ratio_and_manual_factors_are_checked(self):
        tight=calculate(self.example(height_override=5000))
        self.assertEqual(tight['metrics']['frequency_solution']['ratio'],5)
        self.assertTrue(any('空档' in e for e in tight['blocking']))
        manual=calculate(self.example(auto_frequency=False,multiplier=4,frequency_tolerance_percent=1))
        self.assertAlmostEqual(manual['metrics']['actual_y_mm_per_px'],90/4000)
        self.assertTrue(any('纵向精度' in e for e in manual['blocking']))

    def test_effective_counts_and_period_revolutions_are_used_once(self):
        for changes,ratio in (({'edge_factor':2},2.5),({'encoder_revs':2},2.5),({'ppr':2000},2.5)):
            m=calculate(self.example(**changes))['metrics']
            self.assertEqual(m['input_counts_per_cycle'],2000)
            self.assertEqual(m['frequency_solution']['ratio'],ratio)
            self.assertEqual(m['line_triggers_per_cycle'],5000)
            self.assertEqual(m['material_height_px'],3334)

    def test_all_factors_are_bounded_even_with_large_device_limits(self):
        from camera_frequency import solve_frequency
        caps={k:{'min':1,'max':256,'inc':1} for k in ('PreDivider','Multiplier','PostDivider')}
        for ratio in (.12,.45,1.23,4.5,12):
            result=solve_frequency(ratio,caps)
            self.assertTrue(all(1<=result[k]<=5 for k in ('pre_divider','multiplier','post_divider')))
        caps['Multiplier']['min']=6
        with self.assertRaises(CameraError):solve_frequency(3,caps)
        with self.assertRaises(CameraError):calculate(self.example(auto_frequency=False,multiplier=6))


if __name__=='__main__':unittest.main()
