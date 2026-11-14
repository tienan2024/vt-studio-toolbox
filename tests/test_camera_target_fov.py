import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from camera_model import workflow_settings,calculate,config_dict,settings_from_dict,CameraError


class TargetFovTests(unittest.TestCase):
    def test_material_pixels_exclude_margins_and_distance_is_reversible(self):
        settings=workflow_settings();m=calculate(settings)['metrics']
        self.assertEqual((m['material_width_px'],m['material_height_px']),(1862,3724))
        self.assertEqual(m['material_pixel_count'],1862*3724)
        for method in ('quick','thin_lens'):
            settings.optics_method=method;settings.framing_source='material';m=calculate(settings)['metrics']
            settings.framing_source='distance';settings.working_distance_mm=m['working_distance_mm']
            inverse=calculate(settings)['metrics']
            self.assertAlmostEqual(inverse['fov_width_mm'],220)
            self.assertAlmostEqual(inverse['horizontal_margin_percent_actual'],10)
            self.assertEqual(inverse['material_pixel_count'],1862*3724)

    def test_two_margins_drive_height_and_cycle_capacity(self):
        settings=workflow_settings();settings.vertical_margin_percent=10;settings.cycle_travel_mm=537.109375
        plan=calculate(settings);m=plan['metrics']
        self.assertAlmostEqual(m['target_fov_width_mm'],220.)
        self.assertAlmostEqual(m['target_fov_height_mm'],440.)
        self.assertEqual(m['required_image_height'],4096)
        self.assertEqual(m['height'],4100)
        self.assertEqual((plan['settings']['multiplier'],m['line_triggers_per_cycle'],m['cycle_idle_available']),(5,5000,900))
        self.assertGreaterEqual(m['coverage_height_mm'],440)
        self.assertEqual(config_dict(settings_from_dict(config_dict(settings))),config_dict(settings))
        settings.height_override=3900
        self.assertTrue(any('ROI不足' in reason for reason in calculate(settings)['blocking']))

    def test_default_and_old_configs_keep_their_documented_semantics(self):
        settings=workflow_settings();m=calculate(settings)['metrics']
        self.assertEqual(m['target_fov_height_mm'],408)
        self.assertEqual(m['height'],3800)
        self.assertTrue(m['frequency_pending'])
        settings.cycle_travel_mm=429.2
        self.assertLess(abs(calculate(settings)['metrics']['y_sampling_error_percent']),settings.frequency_tolerance_percent)
        settings.cycle_travel_mm=429.6875;settings.vertical_margin_percent=10
        measured=calculate(settings)
        self.assertEqual(measured['settings']['multiplier'],4)
        self.assertTrue(any('空档' in reason for reason in measured['blocking']))
        settings.vertical_margin_percent=2
        settings.cycle_travel_mm=0
        old=config_dict(settings);old.pop('vertical_margin_percent');old['image_vertical_margin_mm']=12
        restored=settings_from_dict(old);m=calculate(restored)['metrics']
        self.assertEqual(restored.vertical_margin_percent,-1)
        self.assertEqual(m['target_fov_height_mm'],412)
        self.assertEqual(m['required_image_height'],math.ceil(400/m['y_mm_per_px'])+math.ceil(12/m['y_mm_per_px']))
        settings.vertical_margin_percent=-.5
        with self.assertRaises(CameraError):calculate(settings)

    def test_area_uses_both_target_dimensions_without_distorting_pixels(self):
        settings=workflow_settings();settings.kind='area';settings.sensor_width=2448;settings.sensor_height=2048
        settings.pixel_pitch_um=3.45;settings.focal_length_mm=6;settings.frame_selector='FrameStart'
        plan=calculate(settings);m=plan['metrics']
        self.assertFalse(plan['blocking'])
        self.assertEqual(m['x_mm_per_px'],m['y_mm_per_px'])
        self.assertGreaterEqual(m['coverage_width_mm'],m['target_fov_width_mm'])
        self.assertGreaterEqual(m['coverage_height_mm'],m['target_fov_height_mm'])
        self.assertLessEqual(m['height'],2048)


if __name__=='__main__':unittest.main()
