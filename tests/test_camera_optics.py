import unittest
from dataclasses import replace
from camera_model import CameraSettings,CameraError,calculate,config_dict,settings_from_dict
from camera_options import PRESETS


class OpticalModelsTests(unittest.TestCase):
    def test_quick_and_thin_lens_round_trip_and_principal_plane(self):
        s=CameraSettings(precision_source='optics',focal_length_mm=25,pixel_pitch_um=7)
        self.assertAlmostEqual(calculate(s)['metrics']['x_mm_per_px'],.112)
        s=replace(s,optics_method='thin_lens',principal_plane_offset_mm=10)
        m=calculate(s)['metrics'];self.assertAlmostEqual(m['x_mm_per_px'],.1078)
        inverse=replace(s,optics_direction='precision_to_wd',x_mm_per_px=m['x_mm_per_px'])
        self.assertAlmostEqual(calculate(inverse)['metrics']['working_distance_mm'],400)
        self.assertEqual(settings_from_dict(config_dict(inverse)),inverse)
        with self.assertRaises(CameraError):calculate(replace(s,principal_plane_offset_mm=-380))
        with self.assertRaises(CameraError):calculate(replace(inverse,principal_plane_offset_mm=1000))

    def test_measured_fov_and_legacy_defaults_do_not_use_lens_formula(self):
        s=CameraSettings(precision_source='fov',optics_method='thin_lens',fov_width_mm=409.6)
        self.assertAlmostEqual(calculate(s)['metrics']['x_mm_per_px'],.1)
        config=config_dict(s)
        for key in ('camera_model_id','optics_method','principal_plane_offset_mm'):config.pop(key)
        self.assertEqual(settings_from_dict(config).optics_method,'quick')

    def test_six_native_sensor_profiles_and_color_identity(self):
        self.assertEqual(len(PRESETS),6)
        self.assertEqual(len({p['model'] for p in PRESETS.values()}),6)
        self.assertEqual([p['sensor_width'] for p in PRESETS.values()],[2048,2048,4096,4096,2448,2448])
        self.assertEqual(PRESETS['line2k']['pixel_pitch_um'],7)
        self.assertEqual(PRESETS['line2k_color']['sensor_height'],3)
        self.assertEqual(PRESETS['area5mp_color']['pixel_pitch_um'],3.45)
        self.assertEqual([p['focal_length_mm'] for p in PRESETS.values()],[12,12,25,25,6,6])

    def test_auto_frequency_exact_solution_and_actual_sampling_error(self):
        caps={key:{'min':1,'max':8,'inc':1} for key in ('PreDivider','Multiplier','PostDivider')}
        s=CameraSettings(auto_frequency=True,encoder_travel_mm_per_rev=300)
        plan=calculate(s,caps);solution=plan['metrics']['frequency_solution']
        self.assertEqual([solution[k] for k in ('pre_divider','multiplier','post_divider')],[1,3,1])
        self.assertTrue(solution['limits_verified']);self.assertAlmostEqual(plan['metrics']['y_mm_per_px'],.1)
        limited={k:{'min':1,'max':1,'inc':1} for k in caps}
        plan=calculate(s,limited)
        self.assertAlmostEqual(plan['metrics']['y_mm_per_px'],.3)
        self.assertTrue(any('容差' in reason for reason in plan['blocking']))
        with self.assertRaises(CameraError):calculate(replace(s,encoder_travel_mm_per_rev=0))

    def test_solver_obeys_steps_and_minimizes_pitch_error(self):
        from camera_frequency import solve_frequency
        import itertools
        caps={'PreDivider':{'min':1,'max':5,'inc':2},'Multiplier':{'min':2,'max':8,'inc':2},'PostDivider':{'min':1,'max':4,'inc':1}}
        result=solve_frequency(1.23,caps)
        possible=[abs(1.23/(m/(p*q))-1) for p,m,q in itertools.product(range(1,6,2),range(2,9,2),range(1,5))]
        self.assertAlmostEqual(abs(1.23/result['ratio']-1),min(possible))

    def test_auto_comparison_needs_device_ranges_and_round_trips_selected_factors(self):
        from test_camera import FakeCamera
        from camera_transaction import compare,apply_comparison
        s=CameraSettings(auto_frequency=True,encoder_travel_mm_per_rev=300)
        camera=FakeCamera(s);self.assertFalse(compare(camera,s)['ready'])
        original=camera.geometry
        def geometry():
            result=original()
            result['limits'].update({k:{'min':1,'max':8,'inc':1} for k in ('PreDivider','Multiplier','PostDivider')})
            return result
        camera.geometry=geometry;report=compare(camera,s);self.assertTrue(report['ready'],report['errors'])
        result=apply_comparison(camera,report);self.assertEqual(result['status'],'passed')
