"""Product-configured VM C# generation and execution of that exact source offline."""
from collections import OrderedDict
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from script_templates import USER_SCRIPT, HARNESS

SCHEMA='vt-script-product/1'
FIXED_INPUTS=[('aiResult','int'),('NGtype','string'),('Label_name','string'),('speed','int'),('起始存图速度','int')]
OUTPUTS=[('outResult_index','string'),('NG_name','string'),('NG_imgName','string'),('NG_saveImg','int')]
REGIONS=('IndependentJudge','LabelNormalize')
KEYWORDS=set(('abstract as base bool break byte case catch char checked class const continue decimal default delegate do double else enum event explicit extern false finally fixed float for foreach goto if implicit in int interface internal is lock long namespace new null object operator out override params private protected public readonly ref return sbyte sealed short sizeof stackalloc static string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using virtual void volatile while').split())
RESERVED=set(n for n,t in FIXED_INPUTS+OUTPUTS)|{'Process','Init','TryReadAiLabels','UseAi','AiLabelCapacity','nErrorCode','GetIntValue','GetStringValue','GetStringArrayValue','SetIntValue','SetStringValue'}
INTERNAL_NAMES=set('UserScript ScriptMethods IProcessMethods Script System Array DateTime List Inputs Outputs Case LabelReadCalls types i aiNG labels labelsReadOK configError ngName hasFirstNG bits type isNG reason unmatched label finalName raw count result normalized values value label_count label_null label_read_status'.split())


def port_name(config,key):return config.get('ports',{}).get(key,key)


def physical_inputs(config,data):
    return {port_name(config,k) if k in dict(FIXED_INPUTS) else k:v for k,v in data.items()}


def rename_identifiers(source,mapping):
    """Rename identifier tokens, leaving comments and string/character data intact."""
    tokens=re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|@"(?:""|[^"])*"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[^\W\d]\w*',re.UNICODE)
    return tokens.sub(lambda m:mapping.get(m.group(),m.group()),source)


class ScriptError(ValueError):pass


def parse_ngtype(text):
    if not isinstance(text,str):raise ScriptError('NGtype应为用-分隔的字符串。')
    values=[v.strip() for v in text.split('-')]
    if any(not v for v in values):raise ScriptError('NGtype含空类型，请检查首尾或连续的-。')
    if len(values)>128 or len(set(values))!=len(values):raise ScriptError('NGtype最多128类，类型不能重复。')
    return values


def default_config():
    return {'schema':SCHEMA,'product':'示例产品','use_ai':True,
            'types':['污点','接头','内装折角','导流层缺失','导流层折角'],
            'signals':[{'name':'全局小污点Result','type':'污点'},
                       {'name':'接头大污点Result','type':'接头'},
                       {'name':'ai导流层Result','type':'导流层缺失'}],
            'aliases':[{'match':'contains','value':'接头','type':'接头'},
                       {'match':'contains','value':'污点','type':'污点'},
                       {'match':'contains','value':'胶滴','type':'污点'}]}


def _text(value,field,limit=100):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 for c in value):
        raise ScriptError(field+'不能为空、过长或包含控制字符。')
    return value.strip()


def validate_config(config):
    if not isinstance(config,dict) or config.get('schema')!=SCHEMA:raise ScriptError('产品配置格式应为'+SCHEMA)
    c=dict(config);c['product']=_text(c.get('product'),'产品名')
    if not isinstance(c.get('use_ai'),bool):raise ScriptError('use_ai必须为布尔值。')
    types=c.get('types')
    if not isinstance(types,list) or not 1<=len(types)<=128:raise ScriptError('请配置1～128个NG类型。')
    c['types']=[_text(t,'NG类型',80) for t in types]
    if len(set(c['types']))!=len(types) or any('-' in t or '|' in t for t in c['types']):raise ScriptError('NG类型不能重复或含有分隔符 -、|。')
    signals=c.get('signals',[]);aliases=c.get('aliases',[])
    if not isinstance(signals,list) or len(signals)>128 or not isinstance(aliases,list) or len(aliases)>256:raise ScriptError('独立信号最多128项，归一化规则最多256项。')
    c['signals']=[];names=set()
    for row in signals:
        if not isinstance(row,dict):raise ScriptError('独立信号格式错误。')
        name=_text(row.get('name'),'信号变量名',80);target=_text(row.get('type'),'信号目标类型',80)
        if not name.isidentifier() or not name.endswith('Result') or name in KEYWORDS or name in RESERVED or name in INTERNAL_NAMES or name in names:
            raise ScriptError('信号名须为有效且唯一的C#标识符，以Result结尾，不能使用固定变量名：'+name)
        if target not in c['types']:raise ScriptError('独立信号目标不在NG类型中：'+target)
        names.add(name);c['signals'].append({'name':name,'type':target})
    c['aliases']=[]
    for row in aliases:
        if not isinstance(row,dict) or row.get('match') not in ('contains','exact'):raise ScriptError('归一化匹配方式必须为contains或exact。')
        value=_text(row.get('value'),'标签匹配文字',128);target=_text(row.get('type'),'标签目标类型',80)
        if c['use_ai'] and target not in c['types']:raise ScriptError('标签目标不在NG类型中：'+target)
        c['aliases'].append({'match':row['match'],'value':value,'type':target})
    ports=c.get('ports',{});notes=c.get('variable_notes',{})
    if not isinstance(ports,dict) or set(ports)-set(dict(FIXED_INPUTS+OUTPUTS)):raise ScriptError('变量用途键无效。')
    used=set(names);clean={}
    for key,_ in FIXED_INPUTS+OUTPUTS:
        name=_text(ports.get(key,key),'变量名',80)
        if (not name.isidentifier() or name in KEYWORDS or name in INTERNAL_NAMES or
            (name in RESERVED and name!=key) or name in used):raise ScriptError('变量名无效、重复或与框架名称冲突：'+name)
        used.add(name)
        if name!=key:clean[key]=name
    c.pop('ports',None)
    if clean:c['ports']=clean
    allowed=set(dict(FIXED_INPUTS+OUTPUTS))|{'signal:'+r['name'] for r in c['signals']}
    if not isinstance(notes,dict) or set(notes)-allowed:raise ScriptError('变量说明的用途键无效。')
    if any(not isinstance(v,str) or len(v)>300 or any(ord(ch)<32 for ch in v) for v in notes.values()):raise ScriptError('变量说明最多300字，不能包含控制字符。')
    c.pop('variable_notes',None)
    if notes:c['variable_notes']={k:v.strip() for k,v in notes.items()}
    return c


def cs_string(value):
    return json.dumps(value,ensure_ascii=False).replace('\u2028',r'\u2028').replace('\u2029',r'\u2029')


def user_regions(source):
    result={}
    for name,legacy in (('IndependentJudge','用户NG判断代码'),('LabelNormalize','用户AI标签归一化')):
        for marker,word in (('BEGIN','开始'),('END','结束')):
            canonical='// USER CODE '+marker+' '+name
            source=re.sub(r'/\*\s*USER CODE '+marker+r'\s+'+name+r'\s*\*/',lambda m:canonical,source)
            source=re.sub(r'/\*\s*'+legacy+word+r'\s*\*/',lambda m:canonical,source)
    for name in REGIONS:
        start='// USER CODE BEGIN '+name;end='// USER CODE END '+name
        if source.count(start)!=1 or source.count(end)!=1:raise ScriptError('USER CODE区域缺失或重复：'+name)
        a=source.index(start)+len(start);b=source.index(end)
        if a>=b:raise ScriptError('USER CODE区域顺序错误：'+name)
        result[name]=source[a:b].strip('\r\n ')
    return result


def generate_sources(config,previous_script=None):
    c=validate_config(config)
    groups=OrderedDict()
    for row in c['signals']:groups.setdefault(row['type'],[]).append(row['name'])
    independent=['            switch (type)','            {']
    for target,names in groups.items():
        independent+=['                case '+cs_string(target)+':',
                      '                    isNG |= '+' || '.join(n+' == 0' for n in names)+';',
                      '                    break;']
    independent+=['            }']
    normalize=[]
    for i,row in enumerate(c['aliases']):
        condition=('label.Contains('+cs_string(row['value'])+')' if row['match']=='contains' else 'label == '+cs_string(row['value']))
        normalize.append('            '+('if' if i==0 else 'else if')+' ('+condition+') label = '+cs_string(row['type'])+';')
    regions={'IndependentJudge':'\n'.join(independent),'LabelNormalize':'\n'.join(normalize) or '            // No aliases; retain the trimmed original label.'}
    if previous_script is not None:regions=user_regions(previous_script)
    script=USER_SCRIPT.replace('__USE_AI__','true' if c['use_ai'] else 'false').replace('__INDEPENDENT__',regions['IndependentJudge']).replace('__NORMALIZE__',regions['LabelNormalize'])
    # Only the framework API key is string data which must follow the port name.
    script=script.replace('GetStringArrayValue("Label_name",','GetStringArrayValue('+cs_string(port_name(c,'Label_name'))+',')
    script=rename_identifiers(script,c.get('ports',{}))
    props=['using System;','using Script.Methods;','','// VM auto-generates accessors too. Do not add duplicate properties.','public partial class UserScript : ScriptMethods, IProcessMethods','{']
    for name,kind in FIXED_INPUTS[:-1]+[(r['name'],'int') for r in c['signals']]+FIXED_INPUTS[-1:]:
        if name=='Label_name':
            props+=['    // VM variable type: string. Read the whole ClassLabel(All) array, never concatenate.',
                    '    public string[] Label_name',
                    '    { get { string[] raw = new string[AiLabelCapacity]; int count;',
                    '        nErrorCode = GetStringArrayValue("Label_name", ref raw, out count);',
                    '        if (nErrorCode != 0 || raw == null || count < 0 || count > raw.Length) return null;',
                    '        string[] values = new string[count]; Array.Copy(raw, values, count); return values; } }']
        else:
            default='0' if kind=='int' else 'string.Empty';method='GetIntValue' if kind=='int' else 'GetStringValue'
            props+=['    public '+kind+' '+name+' { get { '+kind+' value = '+default+'; nErrorCode = '+method+'('+cs_string(name)+', ref value); return value; } }']
    for name,kind in OUTPUTS:
        method='SetIntValue' if kind=='int' else 'SetStringValue'
        props+=['    public '+kind+' '+name+' { set { nErrorCode = '+method+'('+cs_string(name)+', value); } }']
    props+=['}']
    properties='\n'.join(props)+'\n'
    for old,new in c.get('ports',{}).items():
        properties=properties.replace('('+cs_string(old)+',','('+cs_string(new)+',')
    return {'UserScript.cs':script,'UserProperty.cs':rename_identifiers(properties,c.get('ports',{}))}


def variable_rows(config):
    c=validate_config(config)
    notes=c.get('variable_notes',{})
    roles={'aiResult':'AI总判定','NGtype':'类型列表','Label_name':'AI标签数组','speed':'当前线速','起始存图速度':'存图阈值',
           'outResult_index':'NG位串','NG_name':'首个NG名称','NG_imgName':'图片名称','NG_saveImg':'存图开关'}
    rows=([{'direction':'输入','key':n,'role':roles[n],'name':port_name(c,n),'type':t,'note':'绑定ClassLabel(All)，脚本整组读取' if n=='Label_name' else '固定输入'} for n,t in FIXED_INPUTS]+
          [{'direction':'输入','key':'signal:'+r['name'],'role':'独立信号 · '+r['type'],'name':r['name'],'type':'int','note':r['type']+'：0异常 / 1正常'} for r in c['signals']]+
          [{'direction':'输出','key':n,'role':roles[n],'name':port_name(c,n),'type':t,'note':'固定输出'} for n,t in OUTPUTS])
    for row in rows:row['note']=notes.get(row['key'],row['note'])
    return rows


def save_script(config,output,previous_script=None,overwrite=False):
    c=validate_config(config);source=generate_sources(c,previous_script)['UserScript.cs']
    output=Path(output)
    if output.suffix.lower()!='.cs':raise ScriptError('请保存为.cs文件。')
    try:
        with output.open('w' if overwrite else 'x',encoding='utf-8-sig') as stream:stream.write(source)
    except FileExistsError as exc:raise ScriptError('脚本文件已存在，请使用新文件名。') from exc
    return {'output':str(output.resolve()),'filename':output.name}


def base_case(config):
    c=validate_config(config)
    return physical_inputs(c,{'aiResult':1,'NGtype':'-'.join(c['types']),'Label_name':[],
            'speed':100,'起始存图速度':80,**{r['name']:1 for r in c['signals']}})


def compiler_path():
    root=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET'
    for framework in ('Framework64','Framework'):
        path=root/framework/'v4.0.30319/csc.exe'
        if path.is_file():return path
    raise ScriptError('未找到.NET Framework 4.x C#编译器；可继续生成脚本，离线编译测试需要Windows .NET Framework 4.x。')


def run_cases(config,cases,previous_script=None,sources=None):
    c=validate_config(config)
    if not isinstance(cases,list) or not 1<=len(cases)<=256:raise ScriptError('每次测试需要1～256个用例。')
    merged=[]
    for row in cases:
        if not isinstance(row,dict):raise ScriptError('测试用例必须是JSON对象。')
        data=base_case(c);data.update(row)
        if data[port_name(c,'NGtype')] is not None and not isinstance(data[port_name(c,'NGtype')],str):raise ScriptError('NGtype应为字符串或null。')
        labels=data[port_name(c,'Label_name')]
        if 'label_null' in data and type(data['label_null']) is not bool:raise ScriptError('label_null必须为布尔值。')
        if labels is not None and (not isinstance(labels,list) or len(labels)>10000 or any(v is not None and not isinstance(v,str) for v in labels)):raise ScriptError('Label_name应为字符串数组或null，最多10000项。')
        for name in [port_name(c,n) for n in ['aiResult','speed','起始存图速度']]+[r['name'] for r in c['signals']]+[n for n in ('label_read_status','label_count') if n in data]:
            if type(data[name]) is not int or not -2147483648<=data[name]<=2147483647:raise ScriptError(name+'必须为32位整数。')
        merged.append(data)
    compiler=compiler_path();sources=sources or generate_sources(c,previous_script)
    flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    with tempfile.TemporaryDirectory(prefix='vt_script_') as folder:
        root=Path(folder)
        for name in ('UserScript.cs','UserProperty.cs'):(root/name).write_text(sources[name],encoding='utf-8-sig')
        (root/'Harness.cs').write_text(HARNESS,encoding='utf-8-sig')
        executable=root/'Harness.exe'
        try:
            compiled=subprocess.run([str(compiler),'/nologo','/utf8output','/target:exe','/r:System.Web.Extensions.dll','/out:'+str(executable),str(root/'UserScript.cs'),str(root/'UserProperty.cs'),str(root/'Harness.cs')],capture_output=True,encoding='utf-8',errors='replace',timeout=30,**flags)
            if compiled.returncode:raise ScriptError('C#编译失败：\n'+compiled.stdout+compiled.stderr)
            (root/'cases.json').write_text(json.dumps(merged,ensure_ascii=False),encoding='utf-8')
            ran=subprocess.run([str(executable),str(root/'cases.json')],capture_output=True,encoding='utf-8',errors='replace',timeout=30,**flags)
            if ran.returncode:raise ScriptError('C#执行失败：\n'+ran.stderr)
            results=json.loads(ran.stdout)
        except subprocess.TimeoutExpired as exc:raise ScriptError('C#编译或测试超过30秒，已终止本次子进程。') from exc
    return {'execution':'compiled-csharp-offline-double','compiler':str(compiler),'results':results}


def regression_cases(config):
    c=validate_config(config);rows=[]
    def add(name,updates,ng=(),error=False,save=1):
        data=base_case(c);data.update(physical_inputs(c,updates))
        types=(data[port_name(c,'NGtype')] or '').split('-');types=[t.strip() for t in types]
        rows.append({'name':name,'input':data,'expected_return':not error,
                     'expected_bits':'|'.join('0' if i in ng else '1' for i in range(len(types))),
                     'expected_save':save})
    add('全部正常',{})
    add('速度低于阈值',{'speed':79},save=0)
    add('速度等于阈值',{'speed':80})
    add('NGtype前后空格',{'NGtype':' - '.join(c['types'])+' '})
    add('空类型档位',{'NGtype':'-'.join(c['types'])+'-'},ng=[len(c['types'])],error=True)
    add('NGtype为null',{'NGtype':None},ng=[0],error=True)
    for signal in c['signals']:
        add(signal['name']+'独立NG',{signal['name']:0},ng=[c['types'].index(signal['type'])])
    if c['use_ai']:
        # Pick a canonical type which aliases actually keep unchanged.
        def normalize(label):
            for a in c['aliases']:
                if (a['match']=='contains' and a['value'] in label) or (a['match']=='exact' and a['value']==label):return a['type']
            return label
        target=c['types'][0];normalized=normalize(target);index=c['types'].index(normalized)
        add('AI命中',{'aiResult':0,'Label_name':[target]},ng=[index])
        add('AI重复与空白标签',{'aiResult':0,'Label_name':[' '+target+' ',target,'',None]},ng=[index])
        add('AI空数组',{'aiResult':0},error=True)
        add('AI数组缺失',{'aiResult':0,'Label_name':None},error=True)
        add('AI读取失败',{'aiResult':0,'label_read_status':1},error=True)
        add('AI负数数量',{'aiResult':0,'label_count':-1},error=True)
        add('AI超容量',{'aiResult':0,'label_count':4097},error=True)
        unknown=next(v for v in ['__未配置标签__']+[chr(i) for i in range(0x2600,0x2a00)] if normalize(v) not in c['types'])
        add('未知标签与已知标签并存',{'aiResult':0,'Label_name':[target,unknown]},ng=[index],error=True)
        add('AI正常时不读标签',{'Label_name':None,'label_read_status':1})
    else:
        add('无AI模式忽略异常AI输入',{'aiResult':0,'Label_name':None,'label_read_status':1})
    return rows


def run_regression(config,previous_script=None):
    cases=regression_cases(config);result=run_cases(config,[r['input'] for r in cases],previous_script)
    for case,actual in zip(cases,result['results']):
        case['actual']=actual;case['passed']=(actual['process_return']==case['expected_return'] and actual['outputs'][port_name(config,'outResult_index')]==case['expected_bits'] and actual['outputs'][port_name(config,'NG_saveImg')]==case['expected_save'])
    return {'execution':result['execution'],'cases':cases,'passed':sum(r['passed'] for r in cases),'total':len(cases)}
