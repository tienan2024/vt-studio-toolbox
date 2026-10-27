# VT 原生缺陷矩形 XML 导出

最后更新：2026-10-27

勾选批量区“VT XML”后，每张BMP旁写入同名XML。默认勾选；PNG精细掩膜和JSON仍保留。XML框取量化后实际变化像素的外接框，不是整块素材的放置框，也不是精细多边形分割。

## 格式依据与适用范围

依据本机 D:/VisionTrain2.2.0/Applications/Hik.VM.DeepLearningTool.exe 的公开数据类及原生保存结果核对；该文件内部FileVersion为1.4.1.30553。原生写入样本见verification/vt_native_probe.xml，导出样本使用官方loadXml读回的位置、宽高和中文类别验证见verification/vt_native_validation.json。验证仅构造/读取数据对象，不启动训练、不执行检测方案，不修改安装目录。

用户指定参考的“尺寸与原点”模块继续使用原VT Studio转换核心；同名XML原样复制，坐标原点不移动。新增测试确认本格式可通过该核心复制且字节不变。新导出器为纯Python，不携带官方程序集，也不要求目标电脑安装VT。

此profile针对本机VisionTrain缺陷检测的矩形标注结构；不把它标为Pascal VOC，也不宣称兼容OCR、其他检测任务或所有网页版AI平台格式。

## 字段

根节点：VisionMaster.ModuleMainWindow.ModuleDialogNew.DeepLearning.FlawTrainData。

_ItemsData包含VisionMaster.ModuleMainWindow.ModuleDialogNew.DeepLearning.FlawCoverRoiParameter。矩形中：

| 字段 | 含义 |
|---|---|
| _OriginPoint | 左上角x,y，图像原始像素坐标 |
| _width / _height | bbox右减左、下减上 |
| _Angle | 0，轴对齐外接框 |
| flags | 界面填写的缺陷类别，XML字符正确转义 |
| _LevelNum | 2，缺陷区域 |
| _ColorValue | 1，本批单一缺陷类的默认像素值 |
| _Sign / _TIsVisible | True，区域有效且可见 |

根还保存_IsOKCalibrated=False和_ImagePath（对应输出BMP绝对路径）。图像和XML应一起导入；移动整个批次后通过VT图片导入流程重新建立当前图像路径。对既有数据集，应核对类别名称及其像素值映射；工具不修改训练项目的类别表。

PNG掩膜保留实际改动的像素范围，XML矩形会包含框内正常像素，这是矩形标注本身的含义。若任务要求精细分割，应继续使用PNG掩膜，不能把矩形XML声称为逐像素分割。

CLI使用--xml vt-flaw（默认）或--xml none。record中的vt_xml为批次相对路径，vt_xml_profile为visiontrain-2.2-flaw-rectangle。配方export_vt_xml默认true，可显式false关闭。
