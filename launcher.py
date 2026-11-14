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
        from PySide6 import QtCore,QtGui
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
            from vt_xml import ROOT_TYPE,POLYGON_TYPE,POINT_TYPE,PROFILE
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
                nodes=doc.find('_ItemsData').findall(POLYGON_TYPE)
                if doc.tag!=ROOT_TYPE or not nodes or record.get('vt_xml_profile')!=PROFILE:
                    raise RuntimeError('VT polygon XML missing')
                points=[(float(p.findtext('x')),float(p.findtext('y'))) for node in nodes for p in node.find('_PolygonPoints').findall(POINT_TYPE)]
                x0,y0,x1,y1=record['bbox_xyxy']
                if [min(x for x,y in points)+1,min(y for x,y in points)+1,max(x for x,y in points)+1,max(y for x,y in points)+1]!=[x0,y0,x1,y1]:
                    raise RuntimeError('VT polygon extent differs from changed-pixel bbox')
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
                          multi_roi_regions=2,vt_xml_export_count=5,vt_xml_polygon_export=True,multi_roi_recipe_restored=True)
            # The frozen GUI compiles the generated source and executes real C#.
            toolbox.select_page(2);script_page=toolbox.script
            from code_preview import CSharpPreview
            preview=script_page.code_views[0];preview.highlighter.rehighlight()
            if not isinstance(preview,CSharpPreview) or not preview.document().firstBlock().layout().formats():
                raise RuntimeError('Frozen C# syntax highlighting missing')
            script_page.ngtype_text.setText(' 污点 - 接头 - 内装折角 - 导流层缺失 - 导流层折角 ')
            script_page.refresh()
            if script_page.config['types']!=['污点','接头','内装折角','导流层缺失','导流层折角']:
                raise RuntimeError('NGtype automatic parsing failed')
            script_page.tabs.setCurrentIndex(1);script_page.ai_result.setCurrentIndex(1)
            script_page.labels.setPlainText('污点，胶滴，接头')
            script_page.start_test('frame');wait_worker(script_page)
            if script_page.output_values.item(0,2).text()!='0|0|1|1|1' or script_page.output_values.item(1,2).text()!='污点':
                raise RuntimeError('Frozen script generation or compiled C# result differs: '+script_page.message.text())
            script_page.start_test('regression');wait_worker(script_page)
            if '18 / 18' not in script_page.test_status.text():raise RuntimeError('Frozen script regression failed')
            from script_generator import default_config,save_script
            save_script(default_config(),root/'UserScript.cs')
            no_ai=default_config();no_ai['use_ai']=False;script_page.load_config(no_ai)
            script_page.ai_result.setCurrentIndex(1);script_page.array_state.setCurrentIndex(2)
            script_page.start_test('frame');wait_worker(script_page)
            if '0 次' not in script_page.test_status.text() or script_page.output_values.item(0,2).text()!='1|1|1|1|1':
                raise RuntimeError('Frozen no-AI compatibility failed')
            report.update(script_gui_compiled=True,script_regression_passed=18,script_no_ai_compatible=True,script_single_cs_saved=True,script_ngtype_auto_parse=True,script_csharp_highlight=True)
            # New port editor must affect the compiled source, including array API keys.
            script_page.load_config(default_config());panel=script_page.variables
            panel.tables['输入'].item(2,1).setText('检测标签')
            panel.tables['输出'].item(0,1).setText('检测位串')
            script_page.ai_result.setCurrentIndex(1);script_page.labels.setPlainText('污点，接头')
            script_page.array_state.setCurrentIndex(0);script_page.start_test('frame');wait_worker(script_page)
            if script_page.output_values.item(0,0).text()!='检测位串' or script_page.output_values.item(0,2).text()!='0|0|1|1|1':
                raise RuntimeError('Frozen editable port C# execution failed')
            if panel.tables['输入'].rowCount()!=8 or panel.tables['输出'].rowCount()!=4:
                raise RuntimeError('Frozen input/output groups differ')
            import zipfile,struct
            server=b'<Root><ModuleBase><Module Index="9" Name="ShellModule" DisplayName="Script"/></ModuleBase><ProceduresInfo><ProcedureBase><Procedure Index="10001" DisplayName="Inspection"/></ProcedureBase><ProcedureInsideModules><Procedure Index="10001"><Inside Index="9"/></Procedure></ProcedureInsideModules></ProceduresInfo></Root>'
            payload=b''
            for field,direction,name,kind in ((b'DynamicInData','Input','aiResult','int'),(b'DynamicOutData','Output','NG_name','string')):
                payload+=field+b'\0'*12+('<ParamRoot><Categorys><Category Name="'+direction+'"><Items><Filter Name="%'+name+'%" ValueType="'+kind+'"/></Items></Category></Categorys></ParamRoot>').encode()
            frame=struct.pack('>II',7,1)+b'9-ShellModule.mdata'.ljust(512,b'\0')+struct.pack('>I',len(payload))+payload
            sol_path=root/'TEST_ONLY.sol'
            with zipfile.ZipFile(sol_path,'w') as archive:
                archive.writestr('SolutionFile/VmServer.xml',server);archive.writestr('SolutionFile/MoudleFrame',frame)
            before=sol_path.read_bytes();panel.start_read(str(sol_path));wait_worker(script_page)
            if panel.flow.currentText()!='Inspection' or panel.tables['输入'].rowCount()!=1 or panel.tables['输出'].rowCount()!=1 or before!=sol_path.read_bytes():
                raise RuntimeError('Frozen SOL metadata extraction failed: '+panel.status.text())
            report.update(script_editable_ports=True,script_variable_groups=True,sol_readonly_ports=True)
            bridge=Path(__file__).resolve().parent/'vm_bridge/SolScriptHost.cs'
            if not bridge.is_file() or not hasattr(panel,'write_button'):raise RuntimeError('SOL SDK adapter or apply control missing')
            report['sol_apply_adapter_available']=True
            toolbox.select_page(3);camera_page=toolbox.camera
            camera_page.recalculate();metrics=camera_page.plan['metrics']
            if not metrics['frequency_pending'] or metrics['line_triggers_per_cycle'] is not None or not camera_page.plan['blocking']:
                raise RuntimeError('Missing cycle measurement must leave automatic factors pending')
            if any(n['key'] in ('PreDivider','Multiplier','PostDivider') for n in camera_page.plan['nodes']):
                raise RuntimeError('Uncalibrated automatic factors leaked into camera nodes')
            camera_page.controls['cycle_travel_mm'].setValue(429.6875);camera_page.recalculate();metrics=camera_page.plan['metrics']
            if (metrics['width'],metrics['height'],metrics['product_height_lines'],metrics['cycle_idle_available'])!=(2048,3800,3724,200) or metrics['lines_per_product']!=4000 or camera_page.write_button.isEnabled():
                raise RuntimeError('Frozen camera calculation or write guard failed')
            if camera_page.plan['settings']['multiplier']!=4:raise RuntimeError('Cycle capacity multiplier failed')
            from camera_model import CameraSettings,calculate
            fraction=calculate(CameraSettings(precision_source='precision',line_y_source='square',sensor_width=2048,
                target_width_mm=40,target_length_mm=60,x_mm_per_px=.02,y_mm_per_px=.02,products_per_minute=300,
                frequency_strategy='cycle',auto_frequency=True,cycle_travel_mm=90,frequency_tolerance_percent=15))
            if fraction['blocking'] or fraction['metrics']['frequency_solution']['ratio']!=5 or fraction['metrics']['material_height_px']!=3334:
                raise RuntimeError('Measured cycle must use small factors and report actual sampling')
            report['camera_small_factors']=True
            camera_page.connection_button.setChecked(True)
            for _ in range(8):app.processEvents()
            if camera_page.optics_summary.y()<=camera_page.metrics.geometry().bottom():
                raise RuntimeError('Camera connection view overlaps summary and result table')
            if len({c.size().toTuple() for c in (camera_page.language_box,camera_page.connection_button,camera_page.files_button)})!=1:
                raise RuntimeError('Camera toolbar control sizes differ')
            if camera_page.line_trigger_source.currentData()!='FrequencyConverter':
                raise RuntimeError('Line trigger UI must show frequency converter output')
            camera_page.connection_button.setChecked(False)
            report.update(camera_connection_layout=True,camera_line_source=True)
            from camera_presets import CameraPresetStore
            original_store=camera_page.preset_store;camera_page.preset_store=CameraPresetStore(root/'TEST_ONLY_presets.json')
            if len(camera_page.page_preset_controls)!=6 or any(choice.count()!=2 for choice,_,_ in camera_page.page_preset_controls.values()):
                raise RuntimeError('Camera pages must have two explicit presets each')
            camera_page.line_trigger_source.setCurrentIndex(camera_page.line_trigger_source.findData('Software'));camera_page.recalculate()
            if not camera_page.line_trigger_source.isEnabled() or camera_page.plan['metrics']['line_triggers_per_cycle'] is not None:
                raise RuntimeError('Editable line source must not reuse converter timing')
            camera_page.apply_page_preset('trigger');camera_page.preset_store=original_store
            if camera_page.settings().line_source!='FrequencyConverter':raise RuntimeError('Camera page preset did not restore reference trigger source')
            report.update(camera_page_presets=True,camera_editable_line_source=True)
            report['camera_cycle_capacity']=True;report['camera_measured_cycle']=True
            if camera_page.controls['working_distance_mm'].isHidden() or not camera_page.controls['working_distance_mm'].isEnabled() or not camera_page.controls['framing_source'].isHidden():
                raise RuntimeError('Frozen automatic camera input layout failed')
            if (metrics['material_width_px'],metrics['material_height_px'])!=(1862,3724):
                raise RuntimeError('Frozen material pixel calculation failed')
            camera_page.controls['working_distance_mm'].setValue(200);camera_page.recalculate()
            if camera_page.settings().framing_source!='distance' or abs(camera_page.controls['horizontal_margin_percent'].value()-19.47)>.001:
                raise RuntimeError('Frozen distance edit did not calculate FOV and margin')
            camera_page.controls['horizontal_margin_percent'].setValue(10);camera_page.recalculate()
            if camera_page.settings().framing_source!='material' or abs(camera_page.controls['working_distance_mm'].value()-184.152)>.001:
                raise RuntimeError('Frozen margin edit did not calculate distance')
            report.update(camera_auto_reciprocal=True,camera_material_pixels=True)
            wd=camera_page.controls['working_distance_mm'];fixed_distance=wd.value()
            camera_page.lock_buttons['working_distance_mm'].click()
            camera_page.controls['target_width_mm'].setValue(210);camera_page.recalculate()
            if (not wd.isReadOnly() or wd.value()!=fixed_distance or wd.buttonSymbols().name!='NoButtons' or
                    abs(camera_page.controls['horizontal_margin_percent'].value()-4.76)>.001 or
                    camera_page.controls['ppr'].buttonSymbols().name=='NoButtons'):
                raise RuntimeError('Frozen fixed value or scoped lock control failed')
            camera_page.controls['target_width_mm'].setValue(200);camera_page.recalculate()
            camera_page.lock_buttons['working_distance_mm'].click()
            report['camera_fixed_values']=True
            from camera_model import CameraSettings
            camera_page.load_settings(CameraSettings(kind='area',target_length_mm=120,frame_selector='FrameStart'))
            if any(n['key']=='PreDivider' for n in camera_page.plan['nodes']) or camera_page.controls['ppr'].isEnabled():
                raise RuntimeError('Frozen area camera plan included line-scan encoder controls')
            report.update(camera_page=True,camera_calculation=True,camera_area_plan=True,camera_write_guard=True)
            if camera_page.form_tabs.isTabVisible(camera_page.basic_tab_count) or not camera_page.tabs.isHidden() or not camera_page.devices_bar.isHidden():
                raise RuntimeError('Frozen camera default view did not hide advanced details')
            camera_page.load_settings(CameraSettings(target_length_mm=280,image_vertical_margin_mm=12))
            metrics=camera_page.plan['metrics']
            if (metrics['height'],metrics['product_height_lines'],metrics['background_height_lines'])!=(2920,2800,120):
                raise RuntimeError('Frozen camera background-margin calculation failed')
            camera_page.load_settings(CameraSettings(precision_source='optics',focal_length_mm=25,pixel_pitch_um=7))
            if abs(camera_page.plan['metrics']['x_mm_per_px']-.112)>1e-9:
                raise RuntimeError('Frozen camera optical estimate failed')
            report.update(camera_simple_default=True,camera_background_margins=True,camera_optical_estimate=True)
            for asset in ('chevron-down.svg','plus.svg','minus.svg'):
                if QtGui.QIcon(str(Path(__file__).resolve().parent/'assets'/asset)).pixmap(16,16).isNull():
                    raise RuntimeError('Frozen camera control icon missing: '+asset)
            combo=camera_page.camera_type;combo.showPopup();app.processEvents()
            if not combo.view().isVisible():raise RuntimeError('Frozen styled camera dropdown did not open')
            combo.hidePopup();report['camera_styled_controls']=True
            camera_page.camera_type.setCurrentIndex(camera_page.camera_type.findData('area5mp'));camera_page.recalculate()
            if not camera_page.line_trigger_group.isHidden() or 'horizontal_margin_percent' not in camera_page.controls:
                raise RuntimeError('MVS camera tabs or area trigger visibility failed')
            camera_page.optical_mode.setCurrentIndex(camera_page.optical_mode.findData('precision_to_wd'))
            camera_page.controls['x_mm_per_px'].setValue(.15);camera_page.recalculate()
            if abs(camera_page.plan['metrics']['working_distance_mm']-.15*6/.00345)>.001:
                raise RuntimeError('Inverse optical calculation failed')
            camera_page.camera_type.setCurrentIndex(camera_page.camera_type.findData('line4k'));camera_page.recalculate()
            source=camera_page.controls['output0_source'];raw=source.currentData()
            if source.isEditable():raise RuntimeError('Output source must use device enum selection')
            camera_page.language_box.setCurrentIndex(camera_page.language_box.findData('en'))
            if source.currentData()!=raw or source.currentText()!=raw:raise RuntimeError('Translated options changed SDK values')
            report.update(camera_mvs_tabs=True,camera_inverse_optics=True,camera_enum_language=True)
            from PySide6.QtWidgets import QComboBox
            for page_index in range(4):
                toolbox.select_page(page_index);app.processEvents()
                choices=toolbox.pages.widget(page_index).findChildren(QComboBox)
                choice=next(c for c in choices if c.isVisible() and c.isEnabled())
                choice.showPopup();app.processEvents()
                if not choice.view().isVisible() or not choice.property('vtSharedReady'):
                    raise RuntimeError('Shared controls missing on page '+str(page_index))
                choice.hidePopup()
            camera_page.load_settings(CameraSettings(height_override=3200,ppr=2000,products_per_minute=400))
            keys={n['key']:n['value'] for n in camera_page.plan['nodes']}
            if camera_page.plan['blocking'] or keys.get('AcquisitionBurstFrameCount')!=1 or keys.get('AcquisitionMode')!='Continuous':
                raise RuntimeError('Single-product trigger configuration invalid')
            if 'product_pitch_mm' in camera_page.controls or 'AcquisitionLineRate' in keys:
                raise RuntimeError('Obsolete pitch input or inactive frequency write retained')
            report.update(shared_controls_four_pages=True,camera_independent_height=True,camera_single_frame=True)
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
