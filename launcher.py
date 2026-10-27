"""Entry point with a packaged-app diagnostic that survives native import errors."""
from pathlib import Path
import sys


def verify_package(report_path):
    import ctypes
    import json
    import os
    import tempfile
    import time
    import traceback
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    report = {'status': 'running', 'frozen': bool(getattr(sys, 'frozen', False))}
    path = Path(report_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import numpy as np
        from PIL import Image
        from PySide6 import QtCore
        from PySide6.QtWidgets import QApplication
        from toolbox import ToolboxWindow
        from engine import load_gray, load_image, VERSION
        report['qt_version'] = QtCore.qVersion()
        report['tool_version'] = VERSION
        if sys.platform == 'win32':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            kernel.GetModuleHandleW.restype = ctypes.c_void_p
            kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
            kernel.GetModuleFileNameW.restype = ctypes.c_uint
            modules = {}
            for name in ['Qt6Core.dll', 'icuuc.dll', 'VCRUNTIME140.dll']:
                handle = kernel.GetModuleHandleW(name)
                buffer = ctypes.create_unicode_buffer(32768)
                if handle:
                    kernel.GetModuleFileNameW(handle, buffer, len(buffer))
                modules[name] = buffer.value
            report['loaded_modules'] = modules
        app = QApplication.instance() or QApplication([])
        app.setStyle('Fusion')
        toolbox = ToolboxWindow()
        toolbox.show()
        toolbox.select_page(1)
        window = toolbox.defect

        def wait_worker(target):
            deadline = time.monotonic() + 30
            while target.is_busy() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            app.processEvents()
            if target.is_busy():
                raise RuntimeError('Diagnostic worker timeout')

        with tempfile.TemporaryDirectory(prefix='vt_package_test_') as folder:
            root = Path(folder)
            yy, xx = np.indices((320, 400))
            image = Image.fromarray((180 + xx%11 + yy%7).astype(np.uint8))
            ok = root/'TEST_ONLY_ok.bmp'
            image.save(ok)
            donor = np.full((100,100), 185, dtype=np.uint8)
            donor[28:72,30:70] = 45
            ng = root/'TEST_ONLY_ng.bmp'
            Image.fromarray(donor).save(ng)
            window.add_ok([str(ok)])
            window.load_ng(str(ng))
            window.set_asset([(25,25),(75,25),(75,75),(25,75)])
            window.samples.setValue(2)
            window.output_path.setText(str(root/'out'))
            window.preview()
            wait_worker(window)
            if window.preview_result is None:
                raise RuntimeError(window.message.text())
            report['preview_size'] = list(window.preview_result[0].size)
            window.export()
            wait_worker(window)
            if not window.last_run:
                raise RuntimeError(window.message.text())
            run = Path(window.last_run)
            summary = json.loads((run/'summary.json').read_text(encoding='utf-8'))
            if summary['status'] != 'complete' or summary['completed'] != 2:
                raise RuntimeError(f'Export incomplete: {summary}')
            report['export_count'] = summary['completed']
            for item in (run/'images').glob('*.bmp'):
                output = load_gray(item)
                if output.size != (400,320) or output.mode != 'L':
                    raise RuntimeError('Wrong output format')
                mask = Image.open(run/'masks'/f'{item.stem}.png')
                np.testing.assert_array_equal(np.asarray(mask)>0, np.asarray(output)!=np.asarray(image))
            report['mask_matches_changed_pixels'] = True
            inputs = root/'converter_input'
            inputs.mkdir()
            image.save(inputs/'TEST_ONLY_original_name.bmp')
            xml = b'<points test="unchanged"/>'
            (inputs/'TEST_ONLY_original_name.xml').write_bytes(xml)
            converter = toolbox.converter
            toolbox.select_page(0)
            converter.set_input(str(inputs))
            wait_worker(converter)
            converter.width.setValue(420)
            converter.height.setValue(340)
            converter.output_root.setText(str(root/'converter_output'))
            converter.start()
            wait_worker(converter)
            if not converter.results:
                raise RuntimeError(converter.message.text())
            converted = load_gray(converter.results[0])
            if converted.size != (420,340):
                raise RuntimeError('Wrong legacy conversion dimensions')
            np.testing.assert_array_equal(np.asarray(converted)[:320,:400],np.asarray(image))
            if not np.all(np.asarray(converted)[320:,:]==0):
                raise RuntimeError('Legacy origin/fill differs')
            converted_xml = Path(converter.results[0]).with_suffix('.xml')
            if converted_xml.read_bytes() != xml:
                raise RuntimeError('XML was altered')
            converter.send()
            if str(Path(converter.results[0]).resolve()) not in window.ok_paths or toolbox.pages.currentIndex()!=1:
                raise RuntimeError('Module handoff failed')
            report.update(legacy_conversion_size=list(converted.size), legacy_xml_unchanged=True,
                          legacy_origin='top_left', module_handoff=True)
            # Exercise color in the actual frozen GUI process as well as source tests.
            rgb_base = Image.new('RGB', (400,320), (180,150,115))
            rgb_ok, rgb_ng = root/'TEST_ONLY_rgb_ok.bmp', root/'TEST_ONLY_rgb_ng.bmp'
            rgb_base.save(rgb_ok)
            rgb_donor = np.full((100,100,3), (220,190,160), dtype=np.uint8)
            rgb_donor[28:72,30:70] = (45,65,100)
            Image.fromarray(rgb_donor).save(rgb_ng)
            window.ok_paths.clear()
            window.ok_list.clear()
            window.ng_list.selectAll()
            window.remove_ng()
            window.add_ok([str(rgb_ok)])
            window.load_ng(str(rgb_ng))
            window.set_asset([(25,25),(75,25),(75,75),(25,75)])
            window.output_path.setText(str(root/'rgb_out'))
            original_asset = window.asset
            window.begin_ng_roi()
            window.ng_canvas.selection_changed.emit([(10,10),(90,10),(90,90),(10,90)])
            if window.asset is not original_asset or tuple(window.roi) != (.1,.1,.9,.9):
                raise RuntimeError('NG ROI overwrote donor or failed to normalize')
            if tuple(window.ok_canvas.points[0]) != (40.,32.):
                raise RuntimeError('NG ROI failed to map to OK')
            window.preview()
            wait_worker(window)
            if window.preview_result is None or window.preview_result[0].mode != 'RGB':
                raise RuntimeError('RGB preview failed: '+window.message.text())
            window.export()
            wait_worker(window)
            if not window.last_run:
                raise RuntimeError('RGB export failed: '+window.message.text())
            rgb_run = Path(window.last_run)
            rgb_summary = json.loads((rgb_run/'summary.json').read_text(encoding='utf-8'))
            if rgb_summary['status'] != 'complete' or rgb_summary['completed'] != 2:
                raise RuntimeError('RGB export incomplete')
            for item in (rgb_run/'images').glob('*.bmp'):
                output = load_image(item)
                if output.mode != 'RGB' or output.size != rgb_base.size or int.from_bytes(item.read_bytes()[28:30], 'little') != 24:
                    raise RuntimeError('Wrong RGB output format')
                with Image.open(rgb_run/'masks'/f'{item.stem}.png') as mask:
                    np.testing.assert_array_equal(np.asarray(mask)>0,
                        np.any(np.asarray(output)!=np.asarray(rgb_base),axis=2))
                    ys,xs = np.nonzero(np.asarray(mask))
                    if not np.all((xs>=40)&(xs<360)&(ys>=32)&(ys<288)):
                        raise RuntimeError('Output escaped NG material ROI')
            window.apply_recipe(str(rgb_run/'recipe.json'))
            if window.asset.pixels.mode != 'RGB' or window.asset.reference_rgb is None:
                raise RuntimeError('RGB recipe restore failed')
            if tuple(window.roi) != (.1,.1,.9,.9):
                raise RuntimeError('NG ROI recipe restore failed')
            report.update(rgb_preview_mode='RGB', rgb_export_count=2, rgb_bmp_bits=24,
                          rgb_mask_matches_changed_pixels=True, rgb_recipe_restored=True,
                          ng_roi_mapped=True, ng_roi_pixels=[40,32,360,288], ng_roi_recipe_restored=True)
            # Real frozen multi-NG workflow: two color donors + one grayscale donor.
            rgb_ng_second=root/'TEST_ONLY_rgb_ng_second.bmp'
            second_donor=rgb_donor.copy()
            second_donor[28:72,30:70]=(70,45,85)
            Image.fromarray(second_donor).save(rgb_ng_second)
            window.load_ng(str(rgb_ng_second))
            window.set_asset([(25,25),(75,25),(75,75),(25,75)])
            window.begin_ng_roi()
            window.ng_canvas.selection_changed.emit([(20,20),(80,20),(80,80),(20,80)])
            window.load_ng(str(ng))
            window.set_asset([(25,25),(75,25),(75,75),(25,75)])
            window.begin_ng_roi()
            window.ng_canvas.selection_changed.emit([(20,20),(80,20),(80,80),(20,80)])
            window.add_ok([str(ok)])
            window.output_path.setText(str(root/'pool_out'))
            window.export()
            wait_worker(window)
            pool_run=Path(window.last_run)
            pool_summary=json.loads((pool_run/'summary.json').read_text(encoding='utf-8'))
            if pool_summary['status']!='complete' or pool_summary['completed']!=4 or pool_summary['pool_entries']!=3:
                raise RuntimeError('Multi-NG export failed: '+window.message.text())
            entries={entry.entry_id:entry for entry in window.ready_entries()}
            for line in (pool_run/'manifest.jsonl').read_text(encoding='utf-8').splitlines():
                record=json.loads(line)
                chosen=entries[record['pool_entry_id']]
                if record['image_mode']!=chosen.asset.pixels.mode or record['source_roi_normalized']!=list(chosen.roi):
                    raise RuntimeError('Pool color or per-NG ROI mismatch')
                l,t,r,b=record['placement_xyxy'];rl,rt,rr,rb=record['allowed_roi_xyxy']
                if not (rl<=l<r<=rr and rt<=t<b<=rb):
                    raise RuntimeError('Pool placement escaped selected NG region')
            window.apply_recipe(str(pool_run/'recipe.json'))
            if len(window.ready_entries())!=3 or len(window.ng_documents)!=3:
                raise RuntimeError('Multi-NG recipe restore failed')
            report.update(multi_ng_entries=3,multi_ng_generated=4,multi_ng_color_roi_matched=True,multi_ng_recipe_restored=True)
            window.quantity_mode.setCurrentIndex(window.quantity_mode.findData('total'))
            window.batch_total.setValue(5)
            window.output_path.setText(str(root/'exact_total_out'))
            window.export();wait_worker(window)
            total_run=Path(window.last_run)
            total_summary=json.loads((total_run/'summary.json').read_text(encoding='utf-8'))
            if total_summary['status']!='complete' or total_summary['total']!=5 or total_summary['completed']!=5:
                raise RuntimeError('Frozen exact total failed: '+window.message.text())
            if [p['count'] for p in total_summary['planned_ok_counts']]!=[3,2] or len(list((total_run/'images').glob('*.bmp')))!=5:
                raise RuntimeError('Frozen total allocation or file count differs')
            window.apply_recipe(str(total_run/'recipe.json'))
            if window.quantity_mode.currentData()!='total' or window.batch_total.value()!=5:
                raise RuntimeError('Frozen total quantity recipe restore failed')
            report.update(exact_total_export=5,exact_total_allocation=[3,2],exact_total_recipe_restored=True)
            # New UI contracts and native VT XML are checked in the frozen process.
            window.auto_reference.setChecked(False);window.reference.setValue(173)
            if not window.reference.isEnabled() or window.settings().reference_gray!=173:
                raise RuntimeError('Manual background reference failed')
            window.auto_reference.setChecked(True)
            if window.reference.isEnabled() or window.settings().reference_gray!=0:
                raise RuntimeError('Auto background reference must disable manual input')
            window.ng_list.clearSelection()
            window.ng_list.item(1).setSelected(True);window.ng_list.item(2).setSelected(True)
            window.remove_ng()
            window.ok_list.clearSelection()
            window.ok_list.item(1).setSelected(True);window.remove_ok()
            window.reset_roi();window.begin_ng_roi()
            window.ng_canvas.selection_changed.emit([(5,5),(35,5),(35,35),(5,35)])
            window.ng_canvas.selection_changed.emit([(65,65),(95,65),(95,95),(65,95)])
            if len(window.rois)!=2:
                raise RuntimeError('Multiple allowed regions were not retained')
            window.vt_xml_check.setChecked(True)
            window.output_path.setText(str(root/'refined_out'))
            window.export();wait_worker(window)
            refined_run=Path(window.last_run)
            import xml.etree.ElementTree as ET
            from vt_xml import ROOT_TYPE,RECT_TYPE
            refined_records=[json.loads(s) for s in (refined_run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
            if len(refined_records)!=5:
                raise RuntimeError('Refined batch incomplete: '+window.message.text())
            for record in refined_records:
                if len(record.get('allowed_rois_xyxy',[]))!=2:
                    raise RuntimeError('Multiple region metadata missing')
                l,t,r,b=record['placement_xyxy'];rl,rt,rr,rb=record['allowed_roi_xyxy']
                if not (rl<=l<r<=rr and rt<=t<b<=rb):
                    raise RuntimeError('Patch crossed permitted region boundary')
                doc=ET.parse(refined_run/record['vt_xml']).getroot()
                node=doc.find('_ItemsData').find(RECT_TYPE)
                x0,y0,x1,y1=record['bbox_xyxy']
                if doc.tag!=ROOT_TYPE or node.findtext('_OriginPoint')!=f'{x0},{y0}' or float(node.findtext('_width'))!=x1-x0:
                    raise RuntimeError('VT XML coordinates differ from changed-pixel bbox')
            window.apply_recipe(str(refined_run/'recipe.json'))
            if len(window.rois)!=2 or not window.auto_reference.isChecked():
                raise RuntimeError('Refined recipe restore failed')
            from app import AdaptiveImageList
            adaptive=AdaptiveImageList();adaptive.update_height()
            if adaptive.height()!=80:raise RuntimeError('Empty list height differs')
            adaptive.addItems([str(i) for i in range(20)]);adaptive.update_height()
            if adaptive.height()!=180:raise RuntimeError('Long list height differs')
            adaptive.deleteLater()
            from ui_controls import ModeStrip
            if not isinstance(window.ng_mode_picker,ModeStrip):
                raise RuntimeError('Canvas modes are not flat tool buttons')
            report.update(auto_reference_disabled=True,adaptive_list_bounds=[80,180],flat_canvas_tools=True,
                          multi_roi_regions=2,vt_xml_export_count=5,multi_roi_recipe_restored=True)
            from app import Canvas
            from PySide6.QtGui import QMouseEvent
            pan_canvas=Canvas('TEST_ONLY right-button pan')
            pan_canvas.resize(450,300)
            pan_canvas.set_image(Image.new('L',(1200,1000),180))
            pan_canvas.show();app.processEvents()
            pan_canvas.auto_fit=False
            pan_canvas.resetTransform();pan_canvas.scale(1.5,1.5);pan_canvas.centerOn(600,500)
            before=(pan_canvas.horizontalScrollBar().value(),pan_canvas.verticalScrollBar().value())
            for kind,xy,button,buttons in (
                (QtCore.QEvent.Type.MouseButtonPress,(160,120),QtCore.Qt.MouseButton.RightButton,QtCore.Qt.MouseButton.RightButton),
                (QtCore.QEvent.Type.MouseMove,(210,150),QtCore.Qt.MouseButton.NoButton,QtCore.Qt.MouseButton.RightButton),
                (QtCore.QEvent.Type.MouseButtonRelease,(210,150),QtCore.Qt.MouseButton.RightButton,QtCore.Qt.MouseButton.NoButton)):
                pos=QtCore.QPointF(*xy)
                glob=QtCore.QPointF(pan_canvas.viewport().mapToGlobal(pos.toPoint()))
                event=QMouseEvent(kind,pos,glob,button,buttons,QtCore.Qt.KeyboardModifier.NoModifier)
                app.sendEvent(pan_canvas.viewport(),event)
            after=(pan_canvas.horizontalScrollBar().value(),pan_canvas.verticalScrollBar().value())
            pan_canvas.close()
            if after!=(before[0]-50,before[1]-30):
                raise RuntimeError('Frozen right-button canvas pan failed')
            report['right_button_pan']=True
        toolbox.close()
        report['status'] = 'passed'
    except Exception:
        report['status'] = 'failed'
        report['traceback'] = traceback.format_exc()
    finally:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    if '--verify-package' in sys.argv:
        index = sys.argv.index('--verify-package')
        if index+1 >= len(sys.argv):
            sys.exit(2)
        sys.exit(verify_package(sys.argv[index+1]))
    cli_args = sys.argv[1:]
    is_cli = Path(sys.executable).stem.casefold() == 'vtstudiocli'
    if '--cli' in cli_args:
        cli_args.remove('--cli')
        is_cli = True
    if is_cli:
        from cli import main as cli_main
        sys.exit(cli_main(cli_args))
    from app import main
    sys.exit(main())
