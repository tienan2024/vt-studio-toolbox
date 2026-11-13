import unittest
from dataclasses import replace
from camera_model import CameraSettings,CameraError,workflow_settings,calculate,config_dict,settings_from_dict
from camera_frequency import solve_cycle_capacity


class CycleWorkflowTests(unittest.TestCase):
    def test_user_example_and_3900_height_have_idle_and_exact_square_planning(self):
        s=workflow_settings();p=calculate(s);m=p['metrics']
        self.assertAlmostEqual(m['fov_width_mm'],220);self.assertAlmostEqual(m['working_distance_mm'],184.151785714)
        self.assertAlmostEqual(m['x_mm_per_px'],.107421875,places=12)
        self.assertEqual((m['width'],m['product_height_lines'],m['height'],m['cycle_idle_available']),(2048,3724,3800,200))
        self.assertEqual((p['settings']['pre_divider'],p['settings']['multiplier'],p['settings']['post_divider']),(1,4,1))
        self.assertFalse(p['blocking']);self.assertIsNone(m['actual_y_mm_per_px'])
        other=calculate(replace(s,height_override=3900));self.assertEqual(other['metrics']['cycle_idle_available'],100)
        self.assertEqual(other['settings']['multiplier'],4)
        tight=calculate(replace(s,height_override=4000));self.assertEqual(tight['settings']['multiplier'],5)
        self.assertEqual(settings_from_dict(config_dict(s)),s)

    def test_real_cycle_travel_exposes_stretching_and_product_clipping(self):
        s=workflow_settings();bad=calculate(replace(s,cycle_travel_mm=400))
        self.assertEqual(bad['metrics']['actual_product_height_lines'],4000)
        self.assertTrue(any('裁掉' in reason for reason in bad['blocking']))
        self.assertTrue(any('拉伸' in reason for reason in bad['blocking']))
        good=calculate(replace(s,cycle_travel_mm=429.6875));self.assertFalse(good['blocking'])

    def test_counting_modes_change_multiplication_without_changing_frame_plan(self):
        for count,mult in ((1,4),(2,2),(4,1)):
            p=calculate(replace(workflow_settings(),edge_factor=count))
            self.assertEqual(p['settings']['multiplier'],mult)
            self.assertEqual(p['metrics']['line_triggers_per_cycle'],4000)
            self.assertEqual(p['metrics']['height'],3800)

    def test_distance_reverse_framing_and_thin_lens(self):
        s=workflow_settings();distance=calculate(s)['metrics']['working_distance_mm']
        p=calculate(replace(s,framing_source='distance',working_distance_mm=distance))
        self.assertAlmostEqual(p['metrics']['fov_width_mm'],220)
        professional=calculate(replace(s,optics_method='thin_lens'))
        self.assertAlmostEqual(professional['metrics']['working_distance_mm'],distance+12)
        self.assertTrue(calculate(replace(s,framing_source='distance',working_distance_mm=50))['blocking'])

    def test_device_limits_and_safety_guard_are_respected(self):
        limits={k:{'min':1,'max':8,'inc':1} for k in ('PreDivider','Multiplier','PostDivider')}
        self.assertTrue(solve_cycle_capacity(3900,1000,limits)['limits_verified'])
        limits['Multiplier']['max']=3
        with self.assertRaises(CameraError):calculate(workflow_settings(),limits)
        with self.assertRaises(CameraError):calculate(replace(workflow_settings(),cycle_idle_lines=0))
        manual=calculate(replace(workflow_settings(),auto_frequency=False,height_override=4000,multiplier=4))
        self.assertTrue(any('空档' in r for r in manual['blocking']))

    def test_old_schema2_remains_legacy_and_keeps_its_original_result(self):
        old=config_dict(CameraSettings())
        for k in ('framing_source','horizontal_margin_percent','frequency_strategy','height_rounding','cycle_idle_lines','cycle_travel_mm'):old.pop(k)
        s=settings_from_dict(old);self.assertEqual(s.framing_source,'legacy')
        self.assertEqual(calculate(s)['metrics']['height'],3000)
