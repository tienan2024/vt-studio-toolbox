from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from PIL import Image,ImageDraw
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine import Asset,Settings,generate_batch
from pool import PoolEntry,generate_pool_batch
from vt_xml import ROOT_TYPE,RECT_TYPE,POLYGON_TYPE,POINT_TYPE,PROFILE,write_vt_xml,mask_polygons
from legacy_bridge import ConversionSettings,convert_batch


def complex_mask():
    mask=Image.new('L',(128,96));d=ImageDraw.Draw(mask)
    d.polygon([(10,10),(54,10),(54,25),(38,25),(38,55),(10,55)],fill=255)
    d.rectangle((17,17,26,30),fill=0)  # hole, with an island inside
    d.rectangle((20,20,22,22),fill=255)
    d.ellipse((70,12,110,65),fill=255);d.ellipse((80,22,100,55),fill=0)
    d.line((0,80,80,80),fill=255,width=1)
    for xy in ((0,0),(1,1),(127,0),(0,95),(127,95)):d.point(xy,fill=255)
    noise=(np.random.default_rng(24).random((20,28))>.25).astype(np.uint8)*255
    mask.paste(Image.fromarray(noise),(90,70))
    return mask


def scan_xml(xml,size):
    # Independent scan conversion matching the installed VT's native raster.
    width,height=size;buffer=np.zeros(width*height,dtype=bool)
    for node in ET.parse(xml).getroot().find('_ItemsData'):
        pts=[(float(p.findtext('x')),float(p.findtext('y'))) for p in node.find('_PolygonPoints')]
        for y in range(int(min(p[1] for p in pts)),int(max(p[1] for p in pts)+1)):
            xs=[]
            for (x0,y0),(x1,y1) in zip(pts,pts[1:]+pts[:1]):
                if (y0<y<=y1) or (y1<y<=y0):xs.append(int(x0+(y-y0)/(y1-y0)*(x1-x0)))
            xs.sort()
            for i in range(0,len(xs),2):
                for x in range(xs[i],xs[i+1]):
                    index=y*width+x+1
                    if 0<=index<len(buffer):buffer[index]=True
    return buffer.reshape(height,width)


class VTXmlTests(unittest.TestCase):
    def test_single_and_pool_export_sidecar_bbox_and_disable(self):
        shape=Image.new('L',(12,12));ImageDraw.Draw(shape).polygon([(0,0),(11,0),(0,11)],fill=255)
        asset=Asset(Image.new('L',(12,12),40),shape,190,{})
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
                self.assertIsNone(doc.find('_ItemsData').find(RECT_TYPE))
                nodes=doc.find('_ItemsData').findall(POLYGON_TYPE)
                self.assertTrue(nodes)
                self.assertGreater(record['vt_xml_point_count'],4)
                self.assertEqual(nodes[0].findtext('flags'),settings.class_name)
                self.assertEqual(record['vt_xml_profile'],PROFILE)
                self.assertTrue(np.array_equal(scan_xml(xml,(100,80)),np.asarray(Image.open(run/record['mask']))!=0))
            result=generate_batch([str(ok)],asset,replace(settings,export_vt_xml=False),str(root/'no-xml'))
            self.assertEqual(list((Path(result['run_dir'])/'images').glob('*.xml')),[])

    def test_official_native_reader_and_training_raster(self):
        helper=ROOT/'verification/vt_xml_runtime/PolygonXmlProbe.exe'
        if not helper.is_file() or not Path('D:/VisionTrain2.2.0/Applications').is_dir():
            self.skipTest('本机官方VT读取器验证环境不可用')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'test.bmp';Image.new('RGB',(128,96),(180,150,120)).save(image)
            mask=complex_mask();xml=root/'test.xml'
            record={'image_size':[128,96],'class_name':'污渍 & 测试'}
            write_vt_xml(xml,image,record,mask)
            result=subprocess.run([str(helper),'D:/VisionTrain2.2.0/Applications',str(xml)],capture_output=True,encoding='utf-8',timeout=30,
                                  creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            payload=json.loads(result.stdout.split('VT_POLYGON_RESULT:')[-1])
            self.assertEqual(payload['count'],record['vt_xml_polygon_count'])
            doc=ET.parse(xml).getroot()
            xml_points=[[[float(p.findtext('x')),float(p.findtext('y'))] for p in n.find('_PolygonPoints')] for n in doc.find('_ItemsData')]
            self.assertEqual([p['points'] for p in payload['polygons']],xml_points)
            native=np.frombuffer(Path(str(xml)+'.native-mask').read_bytes(),dtype=np.uint8).reshape(96,128)
            self.assertTrue(np.array_equal(native==1,np.asarray(mask)!=0))
            (ROOT/'verification/vt_polygon_native_validation.json').write_text(json.dumps({'status':'passed','polygon_count':payload['count'],'native_mask_matches_png':True,'changed_pixel_count':int((native==1).sum())},ensure_ascii=False,indent=2),encoding='utf-8')

    def test_holes_islands_diagonal_thin_and_image_edges(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);xml=root/'test.xml';mask=complex_mask()
            record={'image_size':list(mask.size),'class_name':'污渍'}
            write_vt_xml(xml,root/'image.bmp',record,mask)
            self.assertTrue(np.array_equal(scan_xml(xml,mask.size),np.asarray(mask)!=0))
            self.assertGreater(record['vt_xml_polygon_count'],1)
            # 511 nonempty 3x3 masks cover diagonal saddles and a one-cell hole.
            for bits in range(1,512):
                a=np.array([(bits>>i)&1 for i in range(9)],dtype=np.uint8).reshape(3,3)*255
                m=Image.fromarray(a)
                write_vt_xml(xml,root/'image.bmp',{'image_size':[3,3],'class_name':'x'},m)
                self.assertTrue(np.array_equal(scan_xml(xml,(3,3)),a!=0),bits)

    def test_invalid_mask_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for mask in (Image.new('L',(3,3)),Image.new('RGB',(3,3)),Image.new('L',(4,4),255)):
                with self.assertRaises(ValueError):
                    write_vt_xml(Path(folder)/'bad.xml','image.bmp',{'image_size':[3,3],'class_name':'x'},mask)

    def test_xml_passes_original_size_and_origin_tool_without_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);inputs=root/'input';inputs.mkdir()
            image=inputs/'test.bmp';Image.new('L',(100,80),180).save(image)
            xml=image.with_suffix('.xml')
            mask=Image.new('L',(100,80));ImageDraw.Draw(mask).polygon([(12,15),(43,15),(30,41)],fill=255)
            write_vt_xml(xml,image,{'image_size':[100,80],'class_name':'污渍'},mask)
            before=xml.read_bytes()
            result=convert_batch(ConversionSettings(str(inputs),str(root/'converted'),100,80))
            self.assertEqual(result['status'],'complete')
            copied=Path(result['images'][0]).with_suffix('.xml')
            self.assertEqual(copied.read_bytes(),before)
