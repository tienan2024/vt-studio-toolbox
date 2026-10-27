from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine import Asset,Settings,generate_batch
from pool import PoolEntry,generate_pool_batch
from vt_xml import ROOT_TYPE,RECT_TYPE,write_vt_xml
from legacy_bridge import ConversionSettings,convert_batch


class VTXmlTests(unittest.TestCase):
    def test_single_and_pool_export_sidecar_bbox_and_disable(self):
        asset=Asset(Image.new('L',(12,12),40),Image.new('L',(12,12),255),190,{})
        settings=Settings(samples_per_ok=1,scale_min=1,scale_max=1,rotation=0,feather=0,class_name='污渍 & 测试')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);ok=root/'ok.bmp';Image.new('L',(100,80),180).save(ok)
            for pool in (False,True):
                result=(generate_pool_batch([str(ok)],[PoolEntry('a','TEST_ONLY',asset)],settings,str(root/'pool')) if pool else
                        generate_batch([str(ok)],asset,settings,str(root/'single')))
                run=Path(result['run_dir'])
                record=json.loads((run/'manifest.jsonl').read_text(encoding='utf-8').strip())
                xml=run/record['vt_xml'];self.assertEqual(xml.with_suffix('.bmp'),run/record['image'])
                doc=ET.parse(xml).getroot();self.assertEqual(doc.tag,ROOT_TYPE)
                rect=doc.find('_ItemsData').find(RECT_TYPE)
                l,t,r,b=record['bbox_xyxy']
                self.assertEqual(rect.findtext('_OriginPoint'),f'{l},{t}')
                self.assertEqual(float(rect.findtext('_width')),r-l)
                self.assertEqual(float(rect.findtext('_height')),b-t)
                self.assertEqual(rect.findtext('flags'),settings.class_name)
            result=generate_batch([str(ok)],asset,replace(settings,export_vt_xml=False),str(root/'no-xml'))
            self.assertEqual(list((Path(result['run_dir'])/'images').glob('*.xml')),[])

    def test_official_native_reader_restores_our_xml(self):
        helper=ROOT/'verification/vt_xml_runtime/NativeXmlProbe.exe'
        if not helper.is_file() or not Path('D:/VisionTrain2.2.0/Applications').is_dir():
            self.skipTest('本机官方VT读取器验证环境不可用')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'test.bmp';Image.new('RGB',(100,80),(180,150,120)).save(image)
            xml=root/'test.xml'
            write_vt_xml(xml,image,{'image_size':[100,80],'bbox_xyxy':[12,15,43,41],'class_name':'污渍 & 测试'})
            result=subprocess.run([str(helper),'D:/VisionTrain2.2.0/Applications',str(xml)],capture_output=True,encoding='utf-8',timeout=30,
                                  creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            payload=json.loads(result.stdout.split('VT_XML_RESULT:')[-1])
            self.assertEqual([payload[k] for k in ('x','y','width','height')],[12,15,31,26])
            self.assertEqual(payload['label'],'污渍 & 测试')
            (ROOT/'verification/vt_native_validation.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')

    def test_xml_passes_original_size_and_origin_tool_without_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);inputs=root/'input';inputs.mkdir()
            image=inputs/'test.bmp';Image.new('L',(100,80),180).save(image)
            xml=image.with_suffix('.xml')
            write_vt_xml(xml,image,{'image_size':[100,80],'bbox_xyxy':[12,15,43,41],'class_name':'污渍'})
            before=xml.read_bytes()
            result=convert_batch(ConversionSettings(str(inputs),str(root/'converted'),100,80))
            self.assertEqual(result['status'],'complete')
            copied=Path(result['images'][0]).with_suffix('.xml')
            self.assertEqual(copied.read_bytes(),before)
