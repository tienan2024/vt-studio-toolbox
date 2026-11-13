"""Bounded search for integer pre/multiply/post factors and achieved line pitch."""
import bisect,math
from camera_model import CameraError

KEYS=('PreDivider','Multiplier','PostDivider')


def solve_cycle_capacity(required_lines,counts_per_cycle,limits=None):
    """Recommend whole-number multiplication and leave capture idle time."""
    if required_lines<=0 or counts_per_cycle<=0:raise CameraError('周期所需行数和输入计数必须大于0。')
    limits=limits or {}
    for key in ('PreDivider','PostDivider'):
        cap=limits.get(key,{'min':1,'max':256,'inc':1})
        if not cap.get('min',1)<=1<=cap.get('max',256) or (1-cap.get('min',1))%max(1,cap.get('inc',1)):
            raise CameraError('设备不支持预/后分频为1的整数倍频方案，请使用专业标定方式。')
    cap=limits.get('Multiplier',{'min':1,'max':256,'inc':1});minimum=int(cap.get('min',1));step=max(1,int(cap.get('inc',1)))
    low=minimum+max(0,math.ceil((1-minimum)/step))*step
    needed=max(low,math.ceil(required_lines/counts_per_cycle-1e-12))
    mult=low+math.ceil((needed-low)/step)*step
    if mult>cap.get('max',256):raise CameraError('设备倍频上限不足，无法同时满足图高和周期空档。')
    return {'pre_divider':1,'multiplier':mult,'post_divider':1,'ratio':mult,'ratio_error_percent':None,
            'limits_verified':all(k in limits for k in KEYS),'strategy':'cycle','required_lines':required_lines}


def solve_frequency(target_ratio,limits=None):
    if not math.isfinite(target_ratio) or target_ratio<=0:raise CameraError('目标倍分频比必须为正数。')
    limits=limits or {};ranges=[]
    for key in KEYS:
        cap=limits.get(key,{'min':1,'max':256,'inc':1})
        minimum=int(cap.get('min',1));high=int(cap.get('max',256));step=max(1,int(cap.get('inc',1)))
        low=minimum+max(0,math.ceil((1-minimum)/step))*step
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
