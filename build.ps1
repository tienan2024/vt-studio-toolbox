param([string]$Python = "python", [string]$DistPath = "release", [string]$WorkPath = "build")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$vtDistFolder = if ([IO.Path]::IsPathRooted($DistPath)) { [IO.Path]::GetFullPath($DistPath) } else { [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $DistPath)) }
$vtPortableFolder = Join-Path $vtDistFolder 'VTStudioToolbox'
& $Python -X utf8 -m PyInstaller --noconfirm --clean --distpath $vtDistFolder --workpath $WorkPath (Join-Path $PSScriptRoot 'packaging/VTStudioToolbox.spec')
if ($LASTEXITCODE -ne 0) { throw "打包失败，请查看上面的错误信息。" }
# Qt 6.11 wheels ship newer VC runtimes than this machine's Python 3.10.
# Keep the portable executable's runtime consistent; do not modify Windows/System32.
$vtQtFolder = & $Python -X utf8 -c "import pathlib, PySide6; print(pathlib.Path(PySide6.__file__).parent)"
if ($LASTEXITCODE -ne 0) { throw "无法定位 Qt 运行库。" }
$vtRuntimeTarget = Join-Path $vtPortableFolder '_internal'
foreach ($vtRuntimeName in @('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'msvcp140_codecvt_ids.dll')) {
    $vtRuntimeSource = Join-Path $vtQtFolder $vtRuntimeName
    if (Test-Path -LiteralPath $vtRuntimeSource) { Copy-Item -LiteralPath $vtRuntimeSource -Destination $vtRuntimeTarget -Force }
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination (Join-Path $vtPortableFolder '使用说明.md')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination (Join-Path $vtPortableFolder 'README.md') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'docs') -Destination $vtPortableFolder -Recurse -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'examples') -Destination $vtPortableFolder -Recurse -Force
$vtLegacyDocFolder = Join-Path $vtPortableFolder 'legacy'
New-Item -ItemType Directory -Path $vtLegacyDocFolder -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'legacy/README.md') -Destination $vtLegacyDocFolder -Force
$vtVerificationFolder = Join-Path $PSScriptRoot 'verification'
New-Item -ItemType Directory -Path $vtVerificationFolder -Force | Out-Null
$vtReportPath = Join-Path $vtVerificationFolder 'portable_smoke.json'
'{"status":"pending"}' | Set-Content -LiteralPath $vtReportPath -Encoding UTF8
$vtPortableExe = Join-Path $vtPortableFolder 'VTStudioToolbox.exe'
$vtCheck = Start-Process -FilePath $vtPortableExe -ArgumentList @('--verify-package', ('"{0}"' -f $vtReportPath)) -WindowStyle Hidden -PassThru -Wait
$vtReport = Get-Content -LiteralPath $vtReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $vtReport.script_editable_ports -or -not $vtReport.script_variable_groups -or -not $vtReport.sol_readonly_ports) {
    throw "变量编辑、输入输出分组或 SOL 只读提取验证失败。"
}
if (-not $vtReport.sol_apply_adapter_available -or -not $vtReport.camera_page -or -not $vtReport.camera_calculation -or
    -not $vtReport.camera_area_plan -or -not $vtReport.camera_write_guard -or -not $vtReport.camera_simple_default -or
    -not $vtReport.camera_background_margins -or -not $vtReport.camera_optical_estimate -or
    -not $vtReport.camera_styled_controls -or -not $vtReport.shared_controls_four_pages -or
    -not $vtReport.camera_independent_height -or -not $vtReport.camera_single_frame -or
    -not $vtReport.camera_mvs_tabs -or -not $vtReport.camera_inverse_optics -or -not $vtReport.camera_enum_language -or
    -not $vtReport.camera_cycle_capacity -or -not $vtReport.camera_auto_reciprocal -or
    -not $vtReport.camera_material_pixels) { throw "SOL自动应用资源或相机页诊断失败。" }
if ($vtCheck.ExitCode -ne 0 -or $vtReport.status -ne 'passed' -or -not $vtReport.frozen -or
    $vtReport.rgb_preview_mode -ne 'RGB' -or $vtReport.rgb_bmp_bits -ne 24 -or
    -not $vtReport.rgb_mask_matches_changed_pixels -or -not $vtReport.rgb_recipe_restored -or
    -not $vtReport.ng_roi_mapped -or -not $vtReport.ng_roi_recipe_restored -or
    $vtReport.multi_ng_entries -ne 3 -or -not $vtReport.multi_ng_color_roi_matched -or
    -not $vtReport.multi_ng_recipe_restored -or -not $vtReport.right_button_pan -or
    $vtReport.exact_total_export -ne 5 -or -not $vtReport.exact_total_recipe_restored -or
    $vtReport.multi_roi_regions -ne 2 -or $vtReport.vt_xml_export_count -ne 5 -or -not $vtReport.vt_xml_polygon_export -or
    -not $vtReport.auto_reference_disabled -or -not $vtReport.flat_canvas_tools -or
    -not $vtReport.script_gui_compiled -or $vtReport.script_regression_passed -ne 18 -or
    -not $vtReport.script_no_ai_compatible -or -not $vtReport.script_single_cs_saved -or -not $vtReport.script_ngtype_auto_parse -or
    -not $vtReport.script_csharp_highlight) {
    throw "便携版启动/预览/导出验证失败，详情：$vtReportPath"
}
$vtCliExe = Join-Path $vtPortableFolder 'VTStudioCLI.exe'
$vtCliInfoText = & $vtCliExe info
if ($LASTEXITCODE -ne 0) { throw "CLI 启动失败。" }
$vtCliInfo = $vtCliInfoText | ConvertFrom-Json
if (-not $vtCliInfo.ok -or -not $vtCliInfo.data.headless -or 'RGB' -notin $vtCliInfo.data.defect_input_modes -or -not $vtCliInfo.data.multi_ng_pool) { throw "CLI 返回格式不符合契约。" }
$vtCliInfoText | Set-Content -LiteralPath (Join-Path $vtVerificationFolder 'portable_cli_info.json') -Encoding UTF8
Write-Output "工具箱实际运行验证通过：Qt 导入、灰度/RGB 合成与掩膜、24 位 BMP、RGB 配方、VT Studio 原核心转换、模块间底图传递。"
Write-Output "AI 命令行入口实际运行验证通过：VTStudioCLI.exe info。"
Write-Output "便携程序：$vtPortableExe"
