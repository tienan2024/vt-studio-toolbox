# VT Studio 5.0 原转换核心

最后更新：2026-10-26

`vt-engine.exe` 是从用户本机 `VT_STUDIO_v5.0.exe` 的单文件 .NET 包内，定位 `VT_STUDIO_v5.0.dll`，再提取其嵌入的 Windows 转换核心资源所得。不是从第三方下载的替代引擎，不代表恢复了原始开发工程。

SHA-256：`94a015245345ea11fe6da2f87a1be28733218d890ad2b8b1bf130006a5a6675e`。

适配层遵循原应用 `VTStudio.Settings`、`VTStudio.EngineEvent`、`VTStudio.Report` 的 JSON 行协议。原应用要求 stdin 在处理期间保持打开，EOF 会触发取消；适配层保留此行为。

已实测原点固定左上角 (0,0)，仅处理右侧与下方；保留原图文件名，支持 BMP/PNG、子目录、XML 原样复制，以及是否允许裁切触及标注的原有设置。

提取与行为核对证据保留在本机被 Git 忽略的 `verification/legacy_recovery` 与 `verification/legacy_probe`。此二进制是工具箱运行依赖，打包时随程序分发；勿单独替换为其他版本。
