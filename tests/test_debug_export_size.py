import json,tempfile,unittest,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diagnostic_log import DiagnosticStore

class ExportSizeTests(unittest.TestCase):
    def test_large_files_keep_tail_and_valid_json_with_redaction(self):
        with tempfile.TemporaryDirectory() as folder:
            store=DiagnosticStore(Path(folder)/'logs')
            try:
                data={'rows':[{'node':i,'value':'test-value'} for i in range(2200)],'end_marker':'COMPLETE','password':'EXAMPLE_PRIVATE_VALUE'}
                source=store.directory/'snapshot-test.json';source.write_text(json.dumps(data,indent=2),encoding='utf-8')
                log=store.directory/'session-large.log';log.write_text(('test line\n'*8000)+'END_OF_LOG\npassword=EXAMPLE_PRIVATE_VALUE',encoding='utf-8')
                archive=store.export(Path(folder)/'debug.zip')
                with zipfile.ZipFile(archive) as z:
                    exported=json.loads(z.read(source.name));text=z.read(log.name).decode()
                    self.assertEqual(exported['end_marker'],'COMPLETE');self.assertEqual(len(exported['rows']),2200)
                    self.assertIn('END_OF_LOG',text);self.assertNotIn('EXAMPLE_PRIVATE_VALUE',text)
                    self.assertEqual(exported['password'],'<redacted>')
            finally:store.handler.close()
