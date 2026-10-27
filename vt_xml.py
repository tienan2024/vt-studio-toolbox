"""VisionTrain 2.2.x native FlawTrainData rectangle annotations (not Pascal VOC)."""
from pathlib import Path
import math
import xml.etree.ElementTree as ET

ROOT_TYPE='VisionMaster.ModuleMainWindow.ModuleDialogNew.DeepLearning.FlawTrainData'
RECT_TYPE='VisionMaster.ModuleMainWindow.ModuleDialogNew.DeepLearning.FlawCoverRoiParameter'


def write_vt_xml(path,image_path,record):
    width,height=record['image_size']
    l,t,r,b=record['bbox_xyxy']
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (width,height,l,t,r,b)) or not (0<=l<r<=width and 0<=t<b<=height):
        raise ValueError('VT XML标注框必须在输出图像像素范围内。')
    label=record['class_name']
    if not isinstance(label,str) or not label.strip() or any(ord(c)<32 for c in label):
        raise ValueError('VT XML缺陷名称无效。')
    root=ET.Element(ROOT_TYPE)
    items=ET.SubElement(root,'_ItemsData');rect=ET.SubElement(items,RECT_TYPE)
    fields={'_LevelNum':'2','flags':label,'_ColorValue':'1','_Opacity':'0.25',
            '_OriginPoint':f'{l},{t}','_width':str(r-l),'_height':str(b-t),
            '_Sign':'True','_TIsSignVisible':'True','_Angle':'0','_TIsVisible':'True','_TOpacity':'1'}
    for key,value in fields.items():
        ET.SubElement(rect,key).text=value
    ET.SubElement(root,'_IsOKCalibrated').text='False'
    ET.SubElement(root,'_ImagePath').text=str(Path(image_path).resolve())
    ET.indent(root,space='  ')
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
