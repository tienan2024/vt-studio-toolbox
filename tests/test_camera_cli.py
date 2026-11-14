import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class CameraCLITests(unittest.TestCase):
    def cli(self,*args,code=0):
        binary=os.environ.get('VT_TOOLBOX_CLI_BINARY');prefix=[binary] if binary else [sys.executable,'-X','utf8',str(ROOT/'cli.py')]
        result=subprocess.run(prefix+list(map(str,args)),capture_output=True,encoding='utf-8',timeout=35,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.assertEqual(result.returncode,code,result.stdout+result.stderr);return json.loads(result.stdout)

    def test_template_plan_typed_input_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'camera.json';plan=Path(folder)/'plan.json'
            self.cli('camera-template','--output',config)
            pending=self.cli('camera-plan','--config',config,code=1)['data']
            self.assertTrue(pending['metrics']['frequency_pending'])
            self.assertIsNone(pending['metrics']['line_triggers_per_cycle'])
            data=json.loads(config.read_text(encoding='utf-8'));data['cycle_travel_mm']=429.6875
            config.write_text(json.dumps(data),encoding='utf-8')
            result=self.cli('camera-plan','--config',config,'--output',plan)['data']
            self.assertEqual(result['metrics']['lines_per_product'],4000);self.assertEqual(result['metrics']['recommended_line_rate_hz'],23000)
            self.assertEqual(json.loads(plan.read_text(encoding='utf-8')),result)
            self.cli('camera-template','--output',config,code=1)
            data=json.loads(config.read_text(encoding='utf-8'));data['height_override']=3200;config.write_text(json.dumps(data),encoding='utf-8')
            result=self.cli('camera-plan','--config',config,code=1)['data'];self.assertTrue(result['blocking'])
            self.cli('camera-write','--comparison',config,code=1)


if __name__=='__main__':unittest.main()
