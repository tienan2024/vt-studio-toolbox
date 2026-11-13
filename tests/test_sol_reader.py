import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sol_reader import read_sol,frame_records,xml_root,_ports,SolError


def fixture(path,version=7):
    server=b'''<Root><ModuleBase><Module Index="9" Name="ShellModule" DisplayName="Script"/></ModuleBase>
    <ProceduresInfo><ProcedureBase><Procedure Index="10001" DisplayName="Inspection"/></ProcedureBase>
    <ProcedureInsideModules><Procedure Index="10001"><Inside Index="9"/></Procedure></ProcedureInsideModules></ProceduresInfo></Root>'''
    def ports(category,values):
        filters=''.join('<Filter Name="%'+name+'%" ValueType="'+kind+'"/>' for name,kind in values)
        return ('<ParamRoot><Categorys><Category Name="'+category+'"><Items>'+filters+
                '<Filter Name="TimeStamp" ValueType="float"/></Items></Category></Categorys></ParamRoot>').encode()
    payload=b'DynamicInData\0'+b'\0'*12+ports('Input',[('检测Result','int'),('Label_name','string')])
    payload+=b'DynamicOutData\0'+b'\0'*12+ports('Output',[('NG_name','string')])
    width,encoding=(256,'utf-16-le') if version==5 else (512,'utf-8')
    frame=struct.pack('>II',version,2)
    for name,data in [('9-ShellModule.mdata',payload),('GlobalVarBinding',b'no executable content')]:
        frame+=name.encode(encoding).ljust(width,b'\0')+struct.pack('>I',len(data))+data
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('SolutionFile/VmServer.xml',server);archive.writestr('SolutionFile/MoudleFrame',frame)
    return frame


class SolReaderTests(unittest.TestCase):
    def test_verified_frame_versions_flow_and_directions_readonly(self):
        with tempfile.TemporaryDirectory() as folder:
            for version in (5,7):
                path=Path(folder)/'example.sol';fixture(path,version);before=path.read_bytes()
                result=read_sol(path);script=result['scripts'][0]
                self.assertEqual(result['frame_version'],version);self.assertTrue(result['read_only'])
                self.assertEqual(script['flow'],'Inspection');self.assertEqual(script['id'],'9')
                self.assertEqual([p['name'] for p in script['inputs']],['检测Result','Label_name'])
                self.assertEqual([p['name'] for p in script['outputs']],['NG_name'])
                self.assertEqual(path.read_bytes(),before)

    def test_frame_bounds_and_versions_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            frame=fixture(Path(folder)/'test.sol')
            for invalid in (frame[:-1],frame+b'junk',struct.pack('>II',8,0),struct.pack('>II',7,10001)):
                with self.assertRaises(SolError):frame_records(invalid)

    def test_invalid_container_and_xml_do_not_execute_or_extract(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.sol';path.write_bytes(b'not a SOL')
            with self.assertRaises(SolError):read_sol(path)
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('SolutionFile/VmServer.xml',b'<!DOCTYPE root><root/>')
                archive.writestr('SolutionFile/MoudleFrame',b'')
            with self.assertRaisesRegex(SolError,'DTD'):read_sol(path)

    def test_missing_port_categories_and_utf16_dtd_fail_closed(self):
        with self.assertRaisesRegex(SolError,'DTD'):xml_root('<!DOCTYPE root><root/>'.encode('utf-16'))
        with self.assertRaisesRegex(SolError,'分类'):
            _ports(b'DynamicInData\0<ParamRoot><Categorys/></ParamRoot>DynamicOutData\0<ParamRoot/>')


if __name__=='__main__':unittest.main()
