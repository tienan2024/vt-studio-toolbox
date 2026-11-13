"""Bounded search for integer pre/multiply/post factors and achieved line pitch."""
import bisect,math
from camera_model import CameraError

KEYS=('PreDivider','Multiplier','PostDivider')


def solve_frequency(target_ratio,limits=None):
    if not math.isfinite(target_ratio) or target_ratio<=0:raise CameraError('目标倍分频比必须为正数。')
    limits=limits or {};ranges=[]
    for key in KEYS:
        cap=limits.get(key,{'min':1,'max':256,'inc':1})
        low=max(1,int(cap.get('min',1)));high=int(cap.get('max',256));step=max(1,int(cap.get('inc',1)))
        if high<low:raise CameraError(key+'设备范围无效。')
        if (high-low)//step+1>1024:raise CameraError(key+'搜索范围过大，请核对设备限制。')
        ranges.append(range(low,high+1,step))
    pres,mults,posts=ranges;best=None
    for pre in pres:
        for post in posts:
            desired=target_ratio*pre*post;index=bisect.bisect_left(mults,desired)
            for j in {max(0,index-1),min(len(mults)-1,index)}:
                mult=mults[j];ratio=mult/(pre*post)
                score=(abs(target_ratio/ratio-1),pre*post,pre,post,mult)
                if best is None or score<best[0]:best=(score,pre,mult,post,ratio)
    _,pre,mult,post,ratio=best
    return {'pre_divider':pre,'multiplier':mult,'post_divider':post,'ratio':ratio,
            'ratio_error_percent':100*(ratio/target_ratio-1),'limits_verified':all(k in limits for k in KEYS)}
