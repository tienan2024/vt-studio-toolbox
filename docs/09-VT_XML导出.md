# VT 原生缺陷多边形 XML 导出

最后更新：2026-11-12

6.6起，勾选“VT XML”后，每张BMP旁写入同名多边形XML。多边形来自最终8位量化后的实际变化像素掩膜，PNG掩膜继续保留；JSON的bbox_xyxy仍是定位摘要。6.5旧批次的矩形XML不自动重写。

## 格式与边界

依据本机D:/VisionTrain2.2.0/Applications/Hik.VM.DeepLearningTool.exe（内部版本1.4.1.30553）的原生保存、loadXml读取和GetImageDataByImage训练栅格化验证。导出器仅依赖NumPy和Python标准库，不携带官方程序集。其他VT版本、OCR或网页版平台格式未宣称通用兼容。

根节点为VisionMaster.ModuleMainWindow.ModuleDialogNew.DeepLearning.FlawTrainData；_ItemsData下每个区域为FlawPolygonRoiParameter完整类型名，同一缺陷的分离区域分别输出。

| 字段 | 含义 |
|---|---|
| _PolygonPoints | HikPcUI.ImageView.PolygonPoint列表，每个含x/y |
| flags | 缺陷类别，中文和XML特殊字符正确转义 |
| _LevelNum / _ColorValue | 2 / 1，与原版本类别约定一致 |
| _Sign / _TIsVisible | True |
| _IsVisibleLabel / _Opacity | True / 0.25 |

根保留_IsOKCalibrated=False和_ImagePath绝对图片路径。类别名称应与训练项目类别表一致，工具不修改该表。

## 轮廓与坐标

沿像素单元边缘追踪轮廓，只删除共线点；不平滑、不外扩、不删小连通域。细线、单像素点、斜角相接和图像四边均保留。内部孔洞通过往返的零宽连接线并入所属外轮廓，利用原生奇偶填充保留正常区域；不能简单使用_Sign=False，因为本机VT训练栅格化不根据该字段扣除孔洞。点序列因此可能有重复顶点，这是孔洞连接所需，不能任意去重。

**VT专用坐标补偿**：本机原生扫描器纵向使用(min,max]，横向写入索引额外+1。XML顶点因此等于PNG像素单元边界坐标减(1,1)，图像上/左边缘顶点允许-1。它不是JSON bbox坐标错误，也不能再按普通像素坐标统一加减；已用原生训练掩膜验证无偏移。不要将此profile直接当作通用多边形格式使用。

掩膜须为与图像等大的非空L图；原始轮廓超过100万条像素边时明确拒绝导出，避免无界内存开销，不静默改回矩形。

## 记录、兼容与验证

CLI仍使用--xml vt-flaw或--xml none，旧配方export_vt_xml开关不变。record保存vt_xml相对路径、vt_xml_profile=visiontrain-2.2-flaw-polygon、vt_xml_polygon_count、vt_xml_point_count和vt_xml_coordinates=vt-2.2-native-scan-offset-minus-one。

原“尺寸与原点”模块仍对已有XML原样复制，文件名及坐标均不修改；新多边形XML复制后字节一致。验证包括全部511种非空3×3掩膜、复杂凹形/孔洞/岛/细线/边缘点，以及本机VT原生读取点序列并栅格化为训练掩膜后与PNG逐像素比较。验证记录见verification/vt_polygon_native_validation.json，原生探针和官方DLL仅存在被忽略的本机验证目录。

本轮没有在VT界面中训练模型或验证训练收益。当前“缺陷”仍按像素是否变化定义，未增加可见性阈值或人工边界修正；轮廓精确并不保证语义标注一定正确。
