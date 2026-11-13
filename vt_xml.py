"""VisionTrain 2.2.x native polygons from the final changed-pixel mask."""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np

ROOT_TYPE='VisionMaster.ModuleMainWindow.ModuleDialogNew.DeepLearning.FlawTrainData'
RECT_TYPE='VisionMaster.ModuleMainWindow.ModuleDialogNew.DeepLearning.FlawCoverRoiParameter'
POLYGON_TYPE='VisionMaster.ModuleMainWindow.ModuleDialogNew.DeepLearning.FlawPolygonRoiParameter'
POINT_TYPE='HikPcUI.ImageView.PolygonPoint'
PROFILE='visiontrain-2.2-flaw-polygon'
MAX_BOUNDARY_EDGES=1_000_000


def _area(points):
    return sum(x*b-a*y for (x,y),(a,b) in zip(points,points[1:]+points[:1]))/2


def mask_polygons(mask):
    """Trace pixel-cell edges, retaining islands and holes without smoothing.

    Returns cell-corner coordinates. Doubled zero-width bridges join holes
    to their parent outline: VT uses even/odd fill and ignores the Sign flag.
    """
    if mask.mode!='L':raise ValueError('VT多边形需要L模式的最终像素掩膜。')
    box=mask.getbbox()
    if box is None:raise ValueError('VT多边形不能使用空掩膜。')
    left,top,_,_=box
    a=np.asarray(mask.crop(box))!=0;padded=np.pad(a,1)
    sides=(a & ~padded[:-2,1:-1],a & ~padded[1:-1,2:],
           a & ~padded[2:,1:-1],a & ~padded[1:-1,:-2])
    if sum(np.count_nonzero(s) for s in sides)>MAX_BOUNDARY_EDGES:
        raise ValueError('缺陷轮廓过于复杂（超过100万边），请检查素材和掩膜。')
    edges={};directions=((1,0),(0,1),(-1,0),(0,-1))
    for direction,side in enumerate(sides):
        ys,xs=np.nonzero(side)
        for y,x in zip(ys.tolist(),xs.tolist()):
            start=((x,y),(x+1,y),(x+1,y+1),(x,y+1))[direction]
            edges.setdefault(start,{})[direction]=(start[0]+directions[direction][0],start[1]+directions[direction][1])
    loops=[]
    while edges:
        start=next(iter(edges));point=start;direction=next(iter(edges[start]));points=[]
        while True:
            points.append(point);following=edges[point].pop(direction)
            if not edges[point]:del edges[point]
            point=following
            if point==start:break
            # Right turns keep diagonally touching foreground cells separate.
            direction=next(d for d in ((direction+1)%4,direction,(direction-1)%4,(direction+2)%4) if d in edges[point])
        corners=[]
        for i,p in enumerate(points):
            prev=points[i-1];nxt=points[(i+1)%len(points)]
            if (p[0]-prev[0])*(nxt[1]-p[1]) != (p[1]-prev[1])*(nxt[0]-p[0]):
                corners.append((p[0]+left,p[1]+top))
        loops.append(corners)
    outers=[p for p in loops if _area(p)>0]
    vertices=[np.asarray(p,dtype=np.float64) for p in outers]
    following=[np.roll(p,-1,axis=0) for p in vertices]
    bounds=np.asarray([(v[:,0].min(),v[:,1].min(),v[:,0].max(),v[:,1].max()) for v in vertices])
    areas=[abs(_area(p)) for p in outers]
    attachments=[{} for p in outers]
    for hole in (p for p in loops if _area(p)<0):
        (x,y),(u,v)=hole[:2];dx=u-x;dy=v-y;length=abs(dx)+abs(dy)
        hx=(x+u)/2+dy/length*.25;hy=(y+v)/2-dx/length*.25
        candidates=np.flatnonzero((bounds[:,0]<=hx)&(hx<bounds[:,2])&(bounds[:,1]<=hy)&(hy<bounds[:,3]))
        parents=[]
        for i in candidates:
            v=vertices[i];n=following[i];cross=(v[:,1]>hy)!=(n[:,1]>hy)
            v=v[cross];n=n[cross]
            if np.count_nonzero(hx < v[:,0]+(hy-v[:,1])*(n[:,0]-v[:,0])/(n[:,1]-v[:,1]))%2:parents.append(i)
        if not parents:raise ValueError('缺陷内部孔洞无法归属到外轮廓。')
        index=min(parents,key=lambda i:areas[i]);outer=outers[index]
        hi=min(range(len(hole)),key=lambda j:hole[j])
        oi=int(np.argmin(np.sum((vertices[index]-hole[hi])**2,axis=1)))
        ring=hole[hi:]+hole[:hi]
        attachments[index].setdefault(oi,[]).extend(ring+[ring[0],outer[oi]])
    return [[p for i,point in enumerate(outer) for p in [point]+bridges.get(i,[])]
            for outer,bridges in zip(outers,attachments)]


def write_vt_xml(path,image_path,record,mask):
    if list(mask.size)!=list(record['image_size']):
        raise ValueError('VT多边形掩膜与输出图片尺寸不一致。')
    label=record['class_name']
    if not isinstance(label,str) or not label.strip() or any(ord(c)<32 for c in label):
        raise ValueError('VT XML缺陷名称无效。')
    polygons=mask_polygons(mask)
    root=ET.Element(ROOT_TYPE);items=ET.SubElement(root,'_ItemsData')
    for polygon in polygons:
        node=ET.SubElement(items,POLYGON_TYPE)
        for key,value in {'_LevelNum':'2','flags':label,'_ColorValue':'1','_Opacity':'0.25',
                          '_IsVisibleLabel':'True','_Sign':'True','_TIsVisible':'True','_TOpacity':'1'}.items():
            ET.SubElement(node,key).text=value
        points=ET.SubElement(node,'_PolygonPoints')
        for x,y in polygon:
            point=ET.SubElement(points,POINT_TYPE)
            # Native VT fills y in (min,max] and adds 1 to the x buffer index.
            # Compensate so its training raster equals the PNG at image edges too.
            ET.SubElement(point,'x').text=str(x-1);ET.SubElement(point,'y').text=str(y-1)
    ET.SubElement(root,'_IsOKCalibrated').text='False'
    ET.SubElement(root,'_ImagePath').text=str(Path(image_path).resolve())
    ET.indent(root,space='  ')
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
    record.update(vt_xml_profile=PROFILE,vt_xml_polygon_count=len(polygons),
                  vt_xml_point_count=sum(map(len,polygons)),
                  vt_xml_coordinates='vt-2.2-native-scan-offset-minus-one')
