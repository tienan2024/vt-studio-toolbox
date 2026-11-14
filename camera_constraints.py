"""Resolve interactive optical inputs while preserving explicitly fixed values."""
from dataclasses import replace
import math
from camera_model import CameraError, calculate


def within_precision(key, first, second, decimals):
    return math.isclose(first,second,rel_tol=0,abs_tol=.5*10**(-decimals[key])+1e-9)


def resolve_fixed_values(settings,fixed,decimals,limits=None):
    """Try the two existing optical directions; only free variables may move."""
    if not fixed or settings.framing_source=='legacy':return settings
    initial=replace(settings,**fixed)
    preferred='distance' if 'working_distance_mm' in fixed else initial.framing_source
    directions=[preferred,'distance' if preferred=='material' else 'material']
    evaluated=False;first_error=None
    for source in directions:
        candidate=replace(initial,framing_source=source)
        try:
            plan=calculate(candidate,limits);metrics=plan['metrics']
            evaluated=True
            if source=='material':
                value=metrics['working_distance_mm']
                if 'working_distance_mm' in fixed:
                    if not within_precision('working_distance_mm',value,fixed['working_distance_mm'],decimals):continue
                else:candidate=replace(candidate,working_distance_mm=round(value,decimals['working_distance_mm']))
            else:
                value=metrics['horizontal_margin_percent_actual']
                if 'horizontal_margin_percent' in fixed:
                    if not within_precision('horizontal_margin_percent',value,fixed['horizontal_margin_percent'],decimals):
                        if 'target_width_mm' in fixed or fixed['horizontal_margin_percent']<=-100:continue
                        width=metrics['fov_width_mm']/(1+fixed['horizontal_margin_percent']/100)
                        candidate=replace(candidate,target_width_mm=round(width,decimals['target_width_mm']))
                        value=calculate(candidate,limits)['metrics']['horizontal_margin_percent_actual']
                        if not within_precision('horizontal_margin_percent',value,fixed['horizontal_margin_percent'],decimals):continue
                else:candidate=replace(candidate,horizontal_margin_percent=round(value,decimals['horizontal_margin_percent']))
            # Re-evaluate after quantization before anything is written to the UI.
            calculate(candidate,limits)
            return candidate
        except (CameraError,ZeroDivisionError,OverflowError) as error:
            if first_error is None:first_error=error
            continue
    if not evaluated and isinstance(first_error,CameraError):raise first_error
    raise CameraError('固定值冲突：工作距离、材料宽度与横向余量无法同时满足，请解除其中一项锁定或调整光学条件。')
