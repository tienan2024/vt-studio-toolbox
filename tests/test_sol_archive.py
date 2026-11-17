import struct,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sol_apply import preserve_archive_container,verify_archive_payloads,SolApplyError


class SolArchiveTests(unittest.TestCase):
    def archive(self,path,frame,changed_metadata=False):
        with zipfile.ZipFile(path,'w') as z:
            z.comment=b'original archive comment'
            for name,data in [('SolutionFile/UiParamData/layout.bin',b'opaque UI bytes'),
                              ('SolutionFile/MoudleFrame',frame),('SolutionFile/VmServer.xml',b'<Root/>')]:
                entry=zipfile.ZipInfo(name,(2026,11,17,10,0,0) if changed_metadata else (1980,1,0,0,0,0))
                entry.comment=b'original entry comment' if not changed_metadata else b'normalized'
                entry.extra=b'\xfe\xca\x02\x00xy' if not changed_metadata else b''
                entry.external_attr=32 if not changed_metadata else 0
                entry.compress_type=zipfile.ZIP_DEFLATED if changed_metadata else zipfile.ZIP_STORED
                z.writestr(entry,data)

    def test_restore_opaque_original_entries_with_target_in_middle(self):
        with tempfile.TemporaryDirectory() as folder:
            a,b,c=[Path(folder)/name for name in ('original.zip','native.zip','preserved.zip')]
            self.archive(a,b'old frame');self.archive(b,b'a longer native frame',True)
            original=a.read_bytes()
            with self.assertRaisesRegex(SolApplyError,'非目标ZIP'):verify_archive_payloads(a,b)
            preserve_archive_container(a,b,c)
            result=verify_archive_payloads(a,c)
            self.assertTrue(result['non_target_archive_raw_preserved']);self.assertEqual(result['preserved_zip_entries'],2)
            with zipfile.ZipFile(c) as z:
                self.assertEqual(z.read('SolutionFile/MoudleFrame'),b'a longer native frame')
                self.assertEqual(z.getinfo('SolutionFile/UiParamData/layout.bin').date_time,(1980,1,0,0,0,0))
                self.assertEqual(z.comment,b'original archive comment')
            self.assertEqual(a.read_bytes(),original)

    def test_equal_crc_does_not_hide_rewritten_zip_headers(self):
        with tempfile.TemporaryDirectory() as folder:
            a,b=[Path(folder)/name for name in ('a.zip','b.zip')]
            self.archive(a,b'frame');self.archive(b,b'frame',True)
            with self.assertRaisesRegex(SolApplyError,'非目标ZIP'):verify_archive_payloads(a,b)

    def test_existing_output_and_unknown_prefix_or_tail_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            a,b,c=[Path(folder)/name for name in ('a.zip','b.zip','c.zip')]
            self.archive(a,b'old');self.archive(b,b'new');c.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):preserve_archive_container(a,b,c)
            self.assertEqual(c.read_bytes(),b'keep')
            c.unlink();a.write_bytes(a.read_bytes()+b'unknown trailing data')
            with self.assertRaisesRegex(SolApplyError,'结束记录'):preserve_archive_container(a,b,c)
            self.assertFalse(c.exists())
            self.archive(a,b'old');a.write_bytes(b'unknown prefix'+a.read_bytes())
            with self.assertRaisesRegex(SolApplyError,'ZIP头边界'):preserve_archive_container(a,b,c)

    def test_multivolume_end_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            a,b,c=[Path(folder)/name for name in ('a.zip','b.zip','c.zip')]
            self.archive(a,b'old');self.archive(b,b'new')
            raw=bytearray(a.read_bytes());end=raw.rfind(b'PK\x05\x06');struct.pack_into('<H',raw,end+4,1);a.write_bytes(raw)
            with self.assertRaisesRegex(SolApplyError,'结束记录'):preserve_archive_container(a,b,c)
            self.assertFalse(c.exists())


if __name__=='__main__':unittest.main()
