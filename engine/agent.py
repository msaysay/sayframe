"""Local, source-bound editing commands for a host agent such as WorkBuddy.

The host supplies semantic decisions through typed JSON. It never supplies
invented time ranges or shell fragments. Calibration uses SAYFRAME's public
worker; final PCM is compared to the compiled physical spans before release.
"""
import argparse,contextlib,copy,hashlib,html,json,math,os,re,shutil,subprocess,sys,time,uuid
from pathlib import Path

SKILL=Path(__file__).resolve().parents[1]
SHARED=Path(__file__).parent/'shared'
sys.path.insert(0,str(SHARED))
VERSION='0.4.0'
RENDER_VERSION=5
DIAGNOSTIC=None
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')

class UserError(Exception):pass

def emit(value):print(json.dumps(value,ensure_ascii=False,allow_nan=False))
def digest(file):
    with Path(file).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(file):return json.loads(Path(file).read_text('utf-8-sig'))
def atomic(file,value):
    file=Path(file);file.parent.mkdir(parents=True,exist_ok=True)
    temp=file.with_name(file.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');os.replace(temp,file)
def run(args,**kwargs):
    r=subprocess.run([str(x) for x in args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}),**kwargs)
    if r.returncode:
        if DIAGNOSTIC:Path(DIAGNOSTIC).write_bytes(r.stderr[-16000:])
        raise UserError('本地媒体组件执行失败；原稿保留。请查看任务目录的失败记录。')
    return r.stdout
def runtime():
    file=SKILL/'runtime/config.json'
    return read(file) if file.is_file() else {}
def tool(name):
    config=runtime();candidate=config.get(name) or shutil.which(name)
    if not candidate or not Path(candidate).is_file():raise UserError('首次使用请先执行 scripts/setup.py，准备本地识别及媒体组件。')
    return str(Path(candidate).resolve())
def model_dir():
    p=Path(runtime().get('acousticModel') or Path.home()/'.cache/sayframe-asr/sensevoice-2024')
    if not (p/'model.int8.onnx').is_file() or not (p/'tokens.txt').is_file():raise UserError('声音校准模型尚未准备好，请执行 setup.py。')
    return p
def project_dir(value):
    p=Path(value).expanduser().resolve()
    if not (p/'sayframe-project.json').is_file():raise UserError('不是SAYFRAME学员版工程目录。')
    return p
def load_project(value):
    p=project_dir(value);doc=read(p/'sayframe-project.json');source=read(p/'source.json')
    if digest(p/'source.json')!=doc['sourceSignature']:raise UserError('原文稿已被外部修改，请重新导入；不能猜时间继续剪。')
    if not Path(source['file']).is_file() or digest(source['file'])!=source['mediaSha256']:raise UserError('原视频已变化或缺失，未输出错源成片。')
    return p,doc,source
@contextlib.contextmanager
def lock(p):
    file=p/'.sayframe.lock'
    try:fd=os.open(file,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise UserError('此工程仍有操作进行中，勿重复提交；先查询status。异常退出时先核实PID，再清理本工程锁。')
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:yield
    finally:file.unlink(missing_ok=True)
def source_rows(source):return {r['id']:r for r in source['segments']}
def current(doc):return doc['history'][doc['cursor']]
def revision(doc):return hashlib.sha256(json.dumps(current(doc),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def commit(p,doc,state):
    if not state['order']:raise UserError('不能删空所有内容。')
    # Preserve redo branches as well as the append-only operation log.
    if doc['cursor']<len(doc['history'])-1:atomic(p/'history'/('redo-'+uuid.uuid4().hex+'.json'),doc['history'][doc['cursor']+1:])
    doc['history']=doc['history'][:doc['cursor']+1]+[state];doc['cursor']+=1;doc['updatedAt']=time.time()
    atomic(p/'sayframe-project.json',doc)

def cached_render(p,doc,source):
    """Recover a sealed movie for this exact draft, including undo/redo.

    A similarly titled movie, an older renderer or a different source cannot
    satisfy the lookup. Failed attempts and newer exports remain untouched.
    Callers hold the project lock; polling never hashes videos repeatedly.
    """
    try:validate_caption_corrections(source,current(doc))
    except UserError:return None
    rev=revision(doc);exports=p/'exports'
    if not exports.is_dir():return None
    for folder in sorted(exports.iterdir(),key=lambda f:f.stat().st_mtime,reverse=True):
        if not folder.is_dir():continue
        try:
            seal=read(folder/'seal.json');compiled=read(folder/'compiled.json')
            if seal.get('revision')!=rev or seal.get('renderVersion')!=RENDER_VERSION:continue
            if compiled.get('revision')!=rev or compiled.get('sourceSha256')!=source['mediaSha256']:continue
            movie=folder/'final.mp4';preview=folder/'preview.html'
            if not movie.is_file() or not preview.is_file() or movie.stat().st_size!=seal.get('movieBytes') or digest(movie)!=seal.get('movieSha256'):continue
            return {'status':'done','stage':'export','export':str(folder),'movie':str(movie),'preview':str(preview),'seal':seal,'reusedVerifiedRender':True,'notice':'已恢复此稿核验过的成片，预览与下载使用同一文件；未重新编码，也未补充人工听审。'}
        except (OSError,ValueError,TypeError,AttributeError,KeyError):continue
    return None
def probe(file):
    value=json.loads(run([tool('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',file]))
    video=next((s for s in value['streams'] if s['codec_type']=='video'),None)
    if not video or not any(s['codec_type']=='audio' for s in value['streams']):raise UserError('需要含声音的视频。')
    rotation=next((float(s['rotation']) for s in video.get('side_data_list',[]) if 'rotation' in s),float(video.get('tags',{}).get('rotate',0)))
    width,height=video['width'],video['height']
    if round(rotation)%180:width,height=height,width
    return {'duration':float(value['format']['duration']),'width':width,'height':height,'rotation':rotation,'codedWidth':video['width'],'codedHeight':video['height']}
def literal_transcription(original,duration,progress):
    """Keep local CTC's literal restarts instead of polished ASR omissions.

    Context overlaps aid recognition, but each acoustic event belongs to one
    source-time window. These token emissions remain estimates, not cut points.
    """
    import numpy as np
    from precise_speech import CharacterAcoustics
    recognizer=CharacterAcoustics(model_dir());events=[]
    for start in range(0,math.ceil(duration),20):
        lo=max(0,start-2);hi=min(duration,start+22)
        audio=np.frombuffer(run([tool('ffmpeg'),'-v','error','-ss',lo,'-i',original,'-t',hi-lo,'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1']),dtype=np.float32)
        for token in recognizer.trace(audio,lo):
            if start<=token['time']<min(duration,start+20):events.append(token)
        progress(min(duration,start+20))
    events.sort(key=lambda t:t['time']);rows=[];group=[]
    # Layout groups must not mechanically bisect a Chinese word, and weak
    # standalone interjections travel with following words for edge auditing.
    import jieba
    jieba.setLogLevel(40)
    word_boundaries={end for _,_,end in jieba.tokenize(''.join(t['text'] for t in events))}
    char_offset=0
    def finish():
        if not group:return
        words=[]
        for i,t in enumerate(group):
            previous=t['previousTime']
            following=group[i+1]['time'] if i+1<len(group) else min(duration,t['time']+.22)
            begin=max(0,t['time']-.14,(previous+t['time'])/2 if previous<t['time'] else 0)
            end=min(duration,max(begin+.01,(t['time']+following)/2))
            words.append({'word':t['text'],'start':begin,'end':end,'probability':t['probability'],'timingEstimated':True,'timingMethod':'CTC-emission-estimate-not-cut-authority'})
        rows.append({'id':'s'+str(len(rows)+1),'start':words[0]['start'],'end':words[-1]['end'],'text':''.join(w['word'] for w in words),'words':words})
    for index,token in enumerate(events):
        event={**token,'previousTime':events[index-1]['time'] if index else 0}
        length=sum(len(t['text']) for t in group)
        if group and length>=6 and char_offset in word_boundaries and (event['time']-group[-1]['time']>.4 or length>=50):finish();group=[]
        group.append(event)
        char_offset+=len(event['text'])
    finish();return rows

def init_project(file,dest,model='small',language='zh',asr='sensevoice',native=None):
    original=Path(file).expanduser().resolve();dest=Path(dest).expanduser().resolve()
    if not original.is_file():raise UserError('原视频不存在。')
    dest.mkdir(parents=True,exist_ok=True)
    if (dest/'sayframe-project.json').exists():raise UserError('该目录已有工程，请新建一个目录，避免覆盖。')
    with lock(dest):
        sha=digest(original);info=probe(original)
        # No source copy is required; source ownership is checked on every edit/export.
        atomic(dest/'status.json',{'status':'running','stage':'local-transcription','pid':os.getpid()})
        def progress(at):atomic(dest/'status.json',{'status':'running','stage':'local-transcription','throughSeconds':at,'totalSeconds':info['duration'],'pid':os.getpid()})
        if asr=='sensevoice':
            rows=literal_transcription(original,info['duration'],progress);provider='local-sensevoice-literal';used_model='SenseVoiceSmall-int8';used_language='zh'
        else:
            from faster_whisper import WhisperModel
            recognizer=WhisperModel(runtime().get('whisperModel') or model,device='cpu',compute_type='int8',cpu_threads=max(1,min(8,os.cpu_count() or 4)),download_root=str(SKILL/'runtime/models'))
            parts,meta=recognizer.transcribe(str(original),language=language,word_timestamps=True,vad_filter=True,condition_on_previous_text=False);rows=[]
            for segment in parts:
                words=[{'word':w.word,'start':float(w.start),'end':float(w.end),'probability':float(w.probability),'timingEstimated':True} for w in segment.words or [] if w.word.strip() and w.end>w.start]
                if words:rows.append({'id':'s'+str(len(rows)+1),'start':words[0]['start'],'end':words[-1]['end'],'text':''.join(w['word'] for w in words),'words':words})
                progress(float(segment.end))
            provider='local-faster-whisper';used_model=model;used_language=meta.language
        if not rows:raise UserError('没有识别到可用原声，不能编造文稿。')
        if digest(original)!=sha:raise UserError('识别期间原视频改变，未发布工程。')
        source={'version':1,'file':str(original),'mediaSha256':sha,**info,'segments':rows,'asr':{'provider':provider,'model':used_model,'language':used_language,'wordTimes':'estimated-not-cut-authority','completeAudioRequested':True,'coverageCertified':False}}
        if native:
            if native['sourceSha256']!=sha:raise UserError('原生稿与原视频不匹配。')
            source['nativeTranscript']=native
            source['asr'].update(provider='WorkBuddy.AudioTranscribe+local-acoustic-literal',nativeSpeechRecognition=True,localTimingModel=used_model)
        atomic(dest/'source.json',source)
        settings={'title':original.stem[:28],'name':'','intro':'','framework':'观点破题','voice':1.,'musicVolume':.07,'musicFile':None,'speed':1.,'font':'NotoSansSC-Regular.ttf','titleFont':'MaShanZheng-Regular.ttf','identityRanges':[],'captionsEnabled':None,'titleEnabled':None}
        state={'title':original.stem[:80],'order':[r['id'] for r in rows],'removed':{},'corrections':{},'settings':settings,'workflow':{'directionConfirmed':False},'summary':'原始完整文稿；先给框架与方向建议，等待确认，尚未剪辑'}
        doc={'format':'sayframe-agent','version':VERSION,'sourceSignature':digest(dest/'source.json'),'history':[state],'cursor':0,'createdAt':time.time()}
        atomic(dest/'sayframe-project.json',doc);atomic(dest/'status.json',{'status':'done','stage':'import','segments':len(rows)})
        return {'project':str(dest),'segments':len(rows),'duration':info['duration'],'revision':revision(doc),'asr':source['asr'],'next':'read；由WorkBuddy读取全文并根据真实原话规划。'}

def inspect(value,full=False):
    p,doc,source=load_project(value);state=current(doc);refs=source_rows(source)
    value={'project':str(p),'revision':revision(doc),'sourceDuration':source['duration'],'sourceSha256':source['mediaSha256'],'asr':source['asr'],'settings':state['settings'],'workflow':state.get('workflow',{'directionConfirmed':True,'legacy':True}),'order':state['order'],'summary':state['summary'],'wordIndices':'零起始，与原识别词单元对应；时间不可由模型修改。'}
    if source.get('nativeTranscript'):value['nativeTranscript']=source['nativeTranscript']
    value['cover']=state.get('cover')
    import planning
    value['planning']=planning.active(sys.modules[__name__],p,doc)
    value['methodology']=state.get('methodology')
    value['subtitleSpans']=state.get('subtitleSpans',[])
    value['segments']=[{**{k:r[k] for k in ('id','start','end','text')},'captionText':''.join(caption_map(r,state).values()),'kept':r['id'] in state['order'],'removed':state['removed'].get(r['id'],[]),'words':[{'index':i,'original':w['word'],'subtitle':caption_map(r,state)[i]} for i,w in enumerate(r['words'])]} for r in source['segments']]
    if not full:value['segments']=[{k:v for k,v in r.items() if k!='words'} for r in value['segments']]
    return value

def check_caption_text(original,text):
    # Punctuation is stripped in the requested clean subtitle style. Replacing
    # spoken letters with an ellipsis would silently hide them in the movie.
    if any(ch.isalnum() for ch in original) and not any(ch.isalnum() for ch in text):
        raise UserError('不能把原话字幕改成省略号或纯标点来隐藏听不清的词；请保留待确认，或改选完整内容组。字幕校正不删除声音。')

def caption_span(operation,refs):
    if not isinstance(operation,dict) or set(operation)!={'id','indices','quote','text'} or operation['id'] not in refs:raise UserError('整词字幕校正引用无效。')
    words=refs[operation['id']]['words'];indices=operation['indices'];replacement=operation['text']
    if not isinstance(indices,list) or not indices or any(type(i)!=int for i in indices) or not 0<=indices[0]<=indices[-1]<len(words) or indices!=list(range(indices[0],indices[-1]+1)):raise UserError('整词字幕校正须引用同一句内连续的原字。')
    if ''.join(words[i]['word'] for i in indices)!=operation['quote']:raise UserError('整词字幕校正的完整原字引用不一致。')
    if not isinstance(replacement,str) or not replacement.strip() or len(replacement)>500:raise UserError('整词字幕校正需有完整、简短的显示文字。')
    check_caption_text(operation['quote'],replacement)
    return indices

def caption_map(row,state):
    result={i:state['corrections'].get(row['id'],{}).get(str(i),w['word']) for i,w in enumerate(row['words'])}
    for operation in state.get('subtitleSpans',[]):
        if operation['id']!=row['id']:continue
        indices=caption_span(operation,{row['id']:row})
        for i in indices:result[i]=operation['text'] if i==indices[0] else ''
    return result

def validate_caption_corrections(source,state):
    refs=source_rows(source)
    for sid in state['order']:
        covered=set()
        for operation in state.get('subtitleSpans',[]):
            if operation['id']==sid:covered.update(caption_span(operation,refs))
        for index,text in state['corrections'].get(sid,{}).items():
            if int(index) not in covered:check_caption_text(refs[sid]['words'][int(index)]['word'],text)

def apply(value,file,expect):
    p,doc,source=load_project(value)
    with lock(p):
        # Re-read under the cross-process lock before accepting an edit.
        doc=read(p/'sayframe-project.json')
        if revision(doc)!=expect:raise UserError('当前稿已改变；请重新read，不能覆盖较新的修改。')
        txn=read(file);allowed={'summary','order','removeWords','restoreWords','subtitles','subtitleSpans','settings'}
        if not isinstance(txn,dict) or set(txn)-allowed:raise UserError('修改包含未开放字段；不接受任意切点或FFmpeg命令。')
        state=copy.deepcopy(current(doc));refs=source_rows(source)
        if not isinstance(txn.get('summary'),str) or not txn['summary'].strip() or len(txn['summary'])>1200:raise UserError('需要说明本次剪辑逻辑。')
        if 'order' in txn:
            order=txn['order']
            if not isinstance(order,list) or not order or len(order)>500 or len(order)!=len(set(order)) or any(x not in refs for x in order):raise UserError('顺序中存在缺失、重复或未知的原话。')
            state['order']=order
        for key,remove in [('removeWords',True),('restoreWords',False)]:
            for operation in txn.get(key,[]):
                if set(operation)!={'id','indices','quote'} or operation['id'] not in refs:raise UserError('删词原话引用无效。')
                sid=operation['id'];indices=operation['indices'];words=refs[sid]['words']
                if not isinstance(indices,list) or not indices or len(set(indices))!=len(indices) or any(type(i)!=int or i<0 or i>=len(words) for i in indices):raise UserError('词索引无效。')
                if ''.join(words[i]['word'] for i in indices)!=operation['quote']:raise UserError('删词逐字引用不一致。')
                if remove and any(re.search(r'\d|[不没无非未]|[零〇一二三四五六七八九十百千万亿]',words[i]['word']) for i in indices):raise UserError('数字和否定不进入自动删词；需改选完整原话组或保留回听。')
                previous=set(state['removed'].get(sid,[]));state['removed'][sid]=sorted(previous|set(indices) if remove else previous-set(indices))
        for correction in txn.get('subtitles',[]):
            if set(correction)!={'id','index','original','text'} or correction['id'] not in refs:raise UserError('字幕引用无效。')
            r=refs[correction['id']];index=correction['index'];text=correction['text']
            if type(index)!=int or not 0<=index<len(r['words']) or r['words'][index]['word']!=correction['original'] or not isinstance(text,str) or not text.strip() or len(text)>50:raise UserError('字幕原字核验失败。')
            check_caption_text(correction['original'],text)
            if any(op['id']==r['id'] and index in op['indices'] for op in state.get('subtitleSpans',[])):raise UserError('该处已有整词校正，请通过subtitleSpans重新校正完整范围，避免拆坏词语。')
            state['corrections'].setdefault(r['id'],{})[str(index)]=text
        incoming=txn.get('subtitleSpans',[])
        if not isinstance(incoming,list):raise UserError('整词字幕校正必须为列表。')
        touched=set()
        for operation in incoming:
            indices=caption_span(operation,refs);sid=operation['id'];keys={(sid,i) for i in indices}
            if keys&touched:raise UserError('一次修改内的整词校正范围不能重叠。')
            touched.update(keys)
            previous=state.get('subtitleSpans',[]);overlap=[op for op in previous if op['id']==sid and set(op['indices'])&set(indices)]
            clear=set(indices)|{i for op in overlap for i in op['indices']}
            for i in clear:state['corrections'].get(sid,{}).pop(str(i),None)
            state['subtitleSpans']=[op for op in previous if op not in overlap]+[copy.deepcopy(operation)]
        settings=txn.get('settings',{})
        if not isinstance(settings,dict) or set(settings)-(set(state['settings'])|{'captionsEnabled','titleEnabled'}):raise UserError('不支持该设置。')
        for key,value in settings.items():
            if key in ('captionsEnabled','titleEnabled'):
                if type(value)!=bool:raise UserError('请明确选择是否添加字幕和标题，不能用空值或文字代替。')
            elif key in ('voice','musicVolume','speed'):
                low,high={'voice':(0,4),'musicVolume':(0,1),'speed':(.5,2)}[key]
                if type(value) not in (float,int) or not math.isfinite(value) or not low<=value<=high:raise UserError('音量/速度超出范围。')
            elif key in ('font','titleFont'):
                if value not in ('NotoSansSC-Regular.ttf','MaShanZheng-Regular.ttf'):raise UserError('首版仅内置两款授权字体。')
            elif key=='musicFile':
                if value is not None:
                    path=Path(value).expanduser().resolve()
                    if not path.is_file():raise UserError('本次配乐文件不存在。')
                    value=str(path)
            elif key=='identityRanges':
                if not isinstance(value,list) or len(value)>3 or any(set(r)!={'start','end'} or type(r['start']) not in (int,float) or type(r['end']) not in (int,float) or not 0<=r['start']<r['end'] for r in value):raise UserError('人物介绍最多三段，按成片秒数填写。')
            elif not isinstance(value,str) or len(value)>120:raise UserError('文字设置过长。')
            state['settings'][key]=value
        if not any(len(refs[sid]['words'])>len(state['removed'].get(sid,[])) for sid in state['order']):raise UserError('没有可保留的原话。')
        state['summary']=txn['summary']
        if state.get('methodology'):state['methodology']['status']='edited-after-plan'
        commit(p,doc,state)
        return {'status':'draft-updated','revision':revision(doc),'retainedSegments':len(state['order']),'notice':'只更新草稿；声音删词必须通过export的公共声学检查，未称已删音。'}

def undo_redo(value,redo=False):
    p,doc,source=load_project(value)
    with lock(p):
        doc=read(p/'sayframe-project.json');cursor=doc['cursor']+(1 if redo else -1)
        if not 0<=cursor<len(doc['history']):raise UserError('没有可重做的修改。' if redo else '没有可撤销的修改。')
        doc['cursor']=cursor;atomic(p/'sayframe-project.json',doc)
        cached=cached_render(p,doc,source)
        if cached:atomic(p/'status.json',cached)
        return {'revision':revision(doc),'cursor':cursor,'summary':current(doc)['summary'],'movieRestored':bool(cached)}

def compile_clips(source,state):
    clips=[];refs=source_rows(source)
    for sid in state['order']:
        row=refs[sid];removed=set(state['removed'].get(sid,[]));groups=[]
        for i in range(len(row['words'])):
            if i not in removed:
                if groups and groups[-1][-1]==i-1:groups[-1].append(i)
                else:groups.append([i])
        for group in groups:
            a,b=group[0],group[-1];captions=caption_map(row,state);words=[{'index':i,**row['words'][i],'captionWord':captions[i]} for i in group]
            clips.append({'id':sid,'firstIndex':a,'lastIndex':b,'start':words[0]['start'],'end':words[-1]['end'],'text':''.join(w['word'] for w in words),'words':words})
    if not clips:raise UserError('没有可输出的片段。')
    return clips

def ff_filter_path(p):return str(Path(p).resolve()).replace('\\','/').replace(':',r'\:').replace("'",r"'\''")
def ass_time(t):
    c=round(t*100);return f'{c//360000}:{c//6000%60:02}:{c//100%60:02}.{c%100:02}'
def draw_ass(folder,source,state,clips):
    from short_captions import chunks,ass_literal
    width,height=source['width'],source['height'];portrait=height>width;size=round(width*(.067 if portrait else .031));margin=round(width*.09);title_size=round(width*(.085 if portrait else .038))
    from PIL import ImageFont
    font_name={'NotoSansSC-Regular.ttf':'Noto Sans SC','MaShanZheng-Regular.ttf':'Ma Shan Zheng'}
    title_typeface=state['settings']['titleFont'];caption_family=font_name[state['settings']['font']]
    title_text=state['settings']['title'];title_lines=re.split('[，,：:；;]',title_text)
    if len(title_lines)!=2 or not all(line.strip() for line in title_lines):title_lines=[title_text]
    title_face=ImageFont.truetype(str(SKILL/'assets/fonts'/title_typeface),title_size)
    while state['settings'].get('titleEnabled',True) and title_size>round(width*.018) and max(title_face.getlength(line) for line in title_lines)>width*.82:
        title_size-=1;title_face=ImageFont.truetype(str(SKILL/'assets/fonts'/title_typeface),title_size)
    if state['settings'].get('titleEnabled',True) and max(title_face.getlength(line) for line in title_lines)>width*.82:raise UserError('标题太长，请在WorkBuddy中缩短标题后再导出。')
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{caption_family},{size},&H00FFFFFF,&H00FFFFFF,&H00151515,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,2,{margin},{margin},{round(height*.14)},1
Style: Title,{font_name[title_typeface]},{title_size},&H00E0FFFF,&H00FFFFFF,&H005B6354,&H00000000,0,0,0,0,100,100,0,0,1,2,0,8,{margin},{margin},{round(height*.08)},1
Style: Identity,Noto Sans SC,{round(size*.75)},&H00FFFFFF,&H00FFFFFF,&H00151515,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,4,{margin},{margin},{round(height*.28)},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events=[];offset=0.;speed=state['settings']['speed'];subtitle_log=[]
    for clip in clips:
        duration=(clip['end']-clip['start'])/speed;text=''.join(w.get('captionWord',w['word']) for w in clip['words']);cues=chunks(text,10 if portrait else 16) if state['settings'].get('captionsEnabled',True) else []
        total=sum(map(len,cues));at=offset
        for cue in cues:
            end=at+duration*len(cue)/max(total,1)
            events.append(f'Dialogue: 0,{ass_time(at)},{ass_time(end)},Caption,,0,0,0,,{ass_literal(cue)}')
            subtitle_log.append({'start':at,'end':end,'text':cue,'displayTiming':'proportional-visual-only'});at=end
        offset+=duration
    if state['settings'].get('titleEnabled',True):
        title=r'\N'.join(ass_literal(line) for line in title_lines);events.append(f'Dialogue: 1,0:00:00.00,{ass_time(offset)},Title,,0,0,0,,{title}')
    identity=state['settings']['name']+(' · '+state['settings']['intro'] if state['settings']['intro'] else '')
    for r in state['settings']['identityRanges'] if identity else []:
        if r['end']>offset:raise UserError('人物介绍时段超出成片。')
        events.append(f"Dialogue: 1,{ass_time(r['start'])},{ass_time(r['end'])},Identity,,0,0,0,,{ass_literal(identity)}")
    (folder/'captions.ass').write_text(header+'\n'.join(events)+'\n',encoding='utf8');atomic(folder/'captions.json',subtitle_log)
    return offset

def export(value):
    global DIAGNOSTIC
    p,doc,source=load_project(value)
    with lock(p):
        old=read(p/'status.json')
        state=current(doc)
        if not state.get('workflow',{'directionConfirmed':True}).get('directionConfirmed'):
            result={'status':'blocked','stage':'confirmation','notice':'请先查看剪辑框架和方案，确认一个方向，再分别选择是否添加字幕与标题。尚未生成成片。'};atomic(p/'status.json',result);return result
        if any(state['settings'].get(key,True) is None for key in ('captionsEnabled','titleEnabled')):
            result={'status':'blocked','stage':'appearance-choice','notice':'请分别选择是否添加自动字幕、是否添加画面标题；两项都可以关闭。尚未生成成片。'};atomic(p/'status.json',result);return result
        validate_caption_corrections(source,current(doc))
        if old.get('status')=='done' and old.get('seal',{}).get('renderVersion')==RENDER_VERSION and old.get('seal',{}).get('revision')==revision(doc) and Path(old.get('movie','')).is_file() and digest(old['movie'])==old['seal']['movieSha256']:
            return old
        cached=cached_render(p,doc,source)
        if cached:atomic(p/'status.json',cached);return cached
        state=current(doc);rev=revision(doc)
        import covers
        poster=covers.selected(sys.modules[__name__],p,state,doc)
        folder=p/'exports'/uuid.uuid4().hex;folder.mkdir(parents=True);DIAGNOSTIC=folder/'process-failure.txt'
        if any(state['removed'].get(sid) for sid in state['order']):
            status={'status':'blocked','stage':'word-deletion','notice':'首版无Key技能尚未迁入逐词删除的独立声音事务；原话保留。可restoreWords恢复后按完整句组导出，不能只删字幕称删音。'}
            atomic(p/'status.json',status);return status
        status={'status':'running','stage':'calibration','export':str(folder),'pid':os.getpid()};atomic(p/'status.json',status)
        import clip_calibration_worker as worker
        request={'source':{'segments':source['segments'],'duration':source['duration']},'clips':compile_clips(source,state),'edges':{},'video':source['file'],'ffmpeg':tool('ffmpeg'),'model':str(model_dir()),'verifiedExclusions':[]}
        report=worker.calibrate(request);atomic(folder/'clip-calibration.json',report)
        if report['blocking']:
            # Give the host actionable source references rather than opaque
            # worker-array indices. This is evidence, never a deletion recipe.
            context=[]
            for issue in report['blocking']:
                ids=[issue['id']] if issue.get('id') else [request['clips'][i]['id'] for i in issue.get('indices',[]) if 0<=i<len(request['clips'])]
                context.append({**issue,'sourceIds':list(dict.fromkeys(ids)),'sourceQuotes':[source_rows(source)[sid]['text'] for sid in dict.fromkeys(ids)]})
            status.update(status='blocked',stage='calibration',blocking=context,report=str(folder/'clip-calibration.json'),notice='未输出可能截字的成片。保留不确定原话或另选完整组，不按听写差异猜删字。');atomic(p/'status.json',status);return status
        clips=report['clips']
        status.update(stage='rendering');atomic(p/'status.json',status)
        from render_spans import render_spans
        spans=render_spans(clips);atomic(folder/'compiled.json',{'revision':rev,'sourceSha256':source['mediaSha256'],'clips':clips,'physicalSpans':spans,'settings':state['settings'],'policyVersion':__import__('editorial_policy').VERSION})
        # Continuous retained source is encoded once; subtitle row boundaries
        # cannot duplicate audio. No audio crossfade eats neighboring consonants.
        files=[];ff=tool('ffmpeg');speed=state['settings']['speed']
        for n,span in enumerate(spans):
            status.update(completedSpans=n,totalSpans=len(spans));atomic(p/'status.json',status)
            file=folder/f'part-{n:04}.mkv';filters=['aresample=48000:async=1:first_pts=0','aformat=sample_fmts=s16:channel_layouts=stereo',f'atempo={speed}']
            run([ff,'-y','-v','error','-ss',span['start'],'-i',source['file'],'-t',span['end']-span['start'],'-map','0:v:0','-map','0:a:0','-vf',f'setpts=(PTS-STARTPTS)/{speed},fps=30,format=yuv420p','-af',','.join(filters),'-c:v','libx264','-preset','veryfast','-crf','19','-c:a','pcm_s16le',file]);files.append(file)
        (folder/'concat.txt').write_text(''.join("file '"+f.name+"'\n" for f in files),encoding='utf8')
        edited=folder/'edited.mkv';run([ff,'-y','-v','error','-f','concat','-safe','0','-i',folder/'concat.txt','-c','copy',edited])
        # Bit-exact decoded PCM of canonical spans and concatenated media.
        def pcm(file):return run([ff,'-v','error','-i',file,'-vn','-ac','2','-ar','48000','-f','s16le','pipe:1'])
        expected=hashlib.sha256();expected_bytes=0
        for file in files:
            part=pcm(file);expected.update(part);expected_bytes+=len(part)
        actual=pcm(edited);audio_ok=expected.hexdigest()==hashlib.sha256(actual).hexdigest() and expected_bytes==len(actual)
        atomic(folder/'audio-integrity.json',{'passed':audio_ok,'method':'decoded-PCM-canonical-spans-vs-concat','expectedSha256':expected.hexdigest(),'actualSha256':hashlib.sha256(actual).hexdigest()})
        if not audio_ok:raise UserError('实际拼接声音与编译计划不一致，停止输出。')
        # Old projects keep immutable source metadata. Trust the ACTUAL encoded
        # frame dimensions for ASS layout after FFmpeg's automatic rotation.
        geometry=probe(edited);duration=draw_ass(folder,{**source,'width':geometry['width'],'height':geometry['height']},state,clips);fonts=SKILL/'assets/fonts'
        status.update(stage='finishing',completedSpans=len(spans));atomic(p/'status.json',status)
        vf="ass=filename='"+ff_filter_path(folder/'captions.ass')+"':fontsdir='"+ff_filter_path(fonts)+"'"
        args=[ff,'-y','-v','error','-i',edited];music=state['settings']['musicFile']
        if music:args+=['-stream_loop','-1','-i',music]
        from music_mix import output_audio_filter
        mix={'musicId':'own' if music else None,'musicVolume':state['settings']['musicVolume'],'musicDucking':True,'voiceGain':state['settings']['voice'],'noiseReduction':'off','peakProtection':True}
        audio_options=output_audio_filter(mix,duration=duration)
        if poster:
            if digest(poster['file'])!=poster['sha256']:raise UserError('所选封面在生成期间变化，停止输出。')
            shutil.copyfile(poster['file'],folder/'cover.jpg');cover_index=2 if music else 1
            args+=['-loop','1','-i',folder/'cover.jpg']
            graph=f'[0:v]{vf},setsar=1,setpts=PTS-STARTPTS[body];[{cover_index}:v]scale={geometry["width"]}:{geometry["height"]},setsar=1,fps=30,format=yuv420p,trim=end_frame=1,setpts=PTS-STARTPTS[poster];[poster][body]concat=n=2:v=1:a=0[v];'
            if music:graph+=audio_options[1][:-3]+'[contentaudio];[contentaudio]adelay=1600S:all=1[a]'
            else:graph+='[0:a]'+(audio_options[1]+',' if audio_options else '')+'adelay=1600S:all=1[a]'
            args+=['-filter_complex',graph,'-map','[v]','-map','[a]'];duration+=1/30
        else:args+=['-vf',vf]+audio_options+['-map','0:v:0']+([] if music else ['-map','0:a:0'])
        args+=['-c:v','libx264','-preset','veryfast','-crf','19','-c:a','aac','-b:a','192k','-t',duration,'-movflags','+faststart',folder/'final.mp4']
        run(args)
        # The pre-mix acoustic audit is exact; lossy AAC after mixing is not
        # presented as an independent ASR/human listening certificate.
        meta=probe(folder/'final.mp4');seal={'movieSha256':digest(folder/'final.mp4'),'movieBytes':(folder/'final.mp4').stat().st_size,'duration':meta['duration'],'revision':rev,'renderVersion':RENDER_VERSION,'width':meta['width'],'height':meta['height'],'localOnly':True,'acousticCalibrationVersion':worker.calibrate.__module__,'finalIndependentListening':'not-performed','extraRestarts':report.get('extraRestarts',[])}
        seal['storyRevision']=covers.story_revision(sys.modules[__name__],doc)
        if poster:seal['cover']={'id':poster['id'],'sha256':poster['sha256'],'title':poster['title'],'subtitle':poster['subtitle'],'frame':0,'leadFrames':1,'silentLeadSeconds':1/30,'file':str(folder/'cover.jpg')}
        atomic(folder/'seal.json',seal)
        (folder/'preview.html').write_text('<!doctype html><meta charset="utf-8"><title>SAYFRAME</title><style>body{margin:24px;background:#101c20;color:white;font:16px sans-serif}video{max-width:100%;max-height:80vh}</style><h1>'+html.escape(state['settings']['title'])+'</h1><video controls src="final.mp4"></video><p>预览与导出使用同一个视频文件；原声重说可能仍保留，请播放审阅。</p>',encoding='utf8')
        status.update(status='done',stage='export',movie=str(folder/'final.mp4'),preview=str(folder/'preview.html'),seal=seal,notice='实际成片已生成；本地转写/声学复核不等于全部口吃已清除或人工听审。');atomic(p/'status.json',status);return status

def main():
    parser=argparse.ArgumentParser(description='SAYFRAME WorkBuddy本地剪辑，无外部API Key。')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor');sub.add_parser('rules')
    a=sub.add_parser('propose');a.add_argument('--project',required=True);a.add_argument('--file',required=True);a.add_argument('--revision',required=True)
    a=sub.add_parser('choose-plan');a.add_argument('--project',required=True);a.add_argument('--plan',required=True);a.add_argument('--direction',required=True);a.add_argument('--revision',required=True);a.add_argument('--confirm-direction',action='store_true');a.add_argument('--captions',choices=['on','off'],required=True);a.add_argument('--title-overlay',choices=['on','off'],required=True)
    a=sub.add_parser('fork');a.add_argument('--project',required=True);a.add_argument('--out',required=True)
    a=sub.add_parser('cover-prepare');a.add_argument('--project',required=True);a.add_argument('--title',required=True);a.add_argument('--subtitle',default='');a.add_argument('--confirmed',action='store_true')
    a=sub.add_parser('cover-generate');a.add_argument('--project',required=True);a.add_argument('--request',required=True);a.add_argument('--backgrounds')
    a=sub.add_parser('cover-select');a.add_argument('--project',required=True);a.add_argument('--candidate',choices=['teal','ivory','ink'],required=True);a.add_argument('--revision',required=True)
    a=sub.add_parser('prepare-audio');a.add_argument('--video',required=True);a.add_argument('--out-dir',required=True)
    a=sub.add_parser('import-native');a.add_argument('--manifest',required=True);a.add_argument('--receipt',required=True);a.add_argument('--project',required=True)
    a=sub.add_parser('import');a.add_argument('--video',required=True);a.add_argument('--project',required=True);a.add_argument('--model',default='small');a.add_argument('--language',default='zh');a.add_argument('--asr',choices=['sensevoice','whisper'],default='sensevoice')
    a=sub.add_parser('read');a.add_argument('--project',required=True);a.add_argument('--words',action='store_true');a.add_argument('--out')
    a=sub.add_parser('apply');a.add_argument('--project',required=True);a.add_argument('--changes',required=True);a.add_argument('--revision',required=True)
    for command in ('undo','redo','export','status','open'):
        a=sub.add_parser(command);a.add_argument('--project',required=True)
        if command=='open':
            a.add_argument('--refresh',action='store_true',help='用当前安装版本新开工作台，不终止已有服务或任务。')
            a.add_argument('--stay-open',action='store_true',help='在宿主后台任务中持续运行工作台；地址写入工程workbench.json。')
    a=sub.add_parser('frame');a.add_argument('--project',required=True);a.add_argument('--time',type=float,required=True);a.add_argument('--out',required=True)
    args=parser.parse_args()
    try:
        if args.command=='doctor':
            import importlib.util
            config=runtime();modules={m:bool(importlib.util.find_spec(m)) for m in ('faster_whisper','av','numpy','onnxruntime','kaldi_native_fbank','PIL','jieba')}
            binaries={name:config.get(name) or shutil.which(name) for name in ('ffmpeg','ffprobe')}
            model=Path(config.get('acousticModel') or SKILL/'runtime/models/sensevoice')
            model_ready=all((model/name).is_file() for name in ('model.int8.onnx','tokens.txt'))
            ready=all(modules.values()) and all(path and Path(path).is_file() for path in binaries.values()) and model_ready
            emit({'version':VERSION,'python':sys.version.split()[0],**binaries,'modules':modules,'modelReady':model_ready,'ready':ready,'apiKeysRequired':False,'setup':'scripts/setup.py'})
            if not ready:sys.exit(2)
            return
        if args.command=='rules':
            import editorial_policy
            import danjie_methodology
            emit({'version':editorial_policy.VERSION,'rules':editorial_policy.RULE,'methodology':danjie_methodology.catalog(),'methodReview':danjie_methodology.REVIEW,'planningContract':read(SKILL/'references/planning-contract.json'),'frameworks':read(SKILL/'references/frameworks.json'),'editContract':read(SKILL/'references/edit-contract.json')});return
        if args.command in ('propose','choose-plan','fork'):
            import planning
            if args.command=='propose':emit(planning.propose(sys.modules[__name__],args.project,args.file,args.revision))
            elif args.command=='choose-plan':emit(planning.choose(sys.modules[__name__],args.project,args.plan,args.direction,args.revision,{'confirmed':args.confirm_direction,'captionsEnabled':args.captions=='on','titleEnabled':args.title_overlay=='on'}))
            else:emit(planning.fork(sys.modules[__name__],args.project,args.out))
            return
        if args.command.startswith('cover-'):
            import covers
            if args.command=='cover-prepare':emit(covers.prepare(sys.modules[__name__],args.project,args.title,args.subtitle,args.confirmed))
            elif args.command=='cover-generate':emit(covers.generate(sys.modules[__name__],args.project,args.request,args.backgrounds))
            else:emit(covers.choose(sys.modules[__name__],args.project,args.candidate,args.revision))
        elif args.command=='prepare-audio':
            import native_audio
            emit(native_audio.prepare(sys.modules[__name__],args.video,args.out_dir))
        elif args.command=='import-native':
            import native_audio
            manifest,native=native_audio.validate(sys.modules[__name__],args.manifest,args.receipt)
            result=init_project(manifest['video'],args.project,native=native)
            p=project_dir(args.project);atomic(p/'native-tool-receipt.json',read(args.receipt));atomic(p/'prepared-audio.json',manifest);emit(result)
        elif args.command=='import':emit(init_project(args.video,args.project,args.model,args.language,args.asr))
        elif args.command=='read':
            data=inspect(args.project,args.words)
            if args.out:atomic(Path(args.out).expanduser().resolve(),data);emit({'file':str(Path(args.out).resolve()),'revision':data['revision'],'segments':len(data['segments'])})
            else:emit(data)
        elif args.command=='apply':emit(apply(args.project,args.changes,args.revision))
        elif args.command in ('undo','redo'):emit(undo_redo(args.project,args.command=='redo'))
        elif args.command=='export':emit(export(args.project))
        elif args.command=='status':emit(read(project_dir(args.project)/'status.json'))
        elif args.command=='open':
            p=project_dir(args.project);ready=p/'workbench.json';log=p/'workbench.log'
            # Agent hosts may recycle a completed command's child process tree.
            # Keep the supported entry point as the tracked background task
            # instead of escaping that host's process lifecycle or job controls.
            if args.stay_open:
                from workbench import serve
                serve(str(p),str(ready),uuid.uuid4().hex);return
            if ready.is_file() and not args.refresh:
                from urllib.parse import urlsplit
                from urllib.request import urlopen
                existing=read(ready);url=urlsplit(existing.get('url',''))
                if existing.get('engineVersion')==VERSION and existing.get('project')==str(p) and url.scheme=='http' and url.hostname=='127.0.0.1' and url.port and not url.query and not url.fragment:
                    try:
                        with urlopen(existing['url']+'api/state',timeout=1) as response:live=json.load(response)
                        if isinstance(live.get('revision'),str):emit(existing);return
                    except (OSError,ValueError):pass
            launch_id=uuid.uuid4().hex
            with log.open('ab') as stream:
                child=subprocess.Popen([sys.executable,str(Path(__file__).with_name('workbench.py')),str(p),str(ready),launch_id],stdout=stream,stderr=stream,stdin=subprocess.DEVNULL,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}))
            for _ in range(100):
                if ready.is_file():
                    value=read(ready)
                    # Windows venv launchers may create a child with a different
                    # PID. Match this launch's nonce rather than the wrapper PID.
                    if value.get('launchId')==launch_id:emit(value);return
                if child.poll() is not None:raise UserError('本地工作台未启动，请查看工程内workbench.log。')
                time.sleep(.1)
            raise UserError('工作台仍在启动，请查看工程内workbench.json，不重复打开。')
        elif args.command=='frame':
            p,doc,source=load_project(args.project)
            if not 0<=args.time<source['duration']:raise UserError('抽帧位置超出原视频。')
            target=Path(args.out).expanduser().resolve()
            if target.exists():raise UserError('抽帧目标已存在，请换一个文件名。')
            if target.suffix.lower() not in ('.png','.jpg'):raise UserError('抽帧输出须为PNG或JPG。')
            target.parent.mkdir(parents=True,exist_ok=True);run([tool('ffmpeg'),'-v','error','-ss',args.time,'-i',source['file'],'-frames:v','1','-vf','scale=960:-2',target]);emit({'frame':str(target),'sourceTime':args.time,'scope':'单帧画面证据，不是完整音视频听审。'})
    except (UserError,ValueError,OSError,ImportError,KeyError,TypeError) as error:
        # Never include arbitrary provider/log content, environment or credentials.
        message=str(error) if isinstance(error,UserError) else '环境或工程数据未通过检查，原素材和已完成文件保留。'
        if hasattr(args,'project'):
            path=Path(args.project).expanduser().resolve()/'status.json'
            if path.is_file():
                status=read(path)
                if status.get('status')=='running' and status.get('pid')==os.getpid():
                    import traceback
                    diagnostic=Path(status['export'])/'component-error.json' if status.get('export') else path.with_name('component-error.json')
                    atomic(diagnostic,{'kind':type(error).__name__,'missingFile':Path(error.filename).name if isinstance(error,FileNotFoundError) and error.filename else None,'frames':[{'module':Path(frame.filename).name,'line':frame.lineno,'function':frame.name} for frame in traceback.extract_tb(error.__traceback__)]})
                    atomic(path,{**status,'status':'error','message':message,'errorKind':type(error).__name__,'diagnostic':str(diagnostic)})
        emit({'status':'error','message':message,'errorKind':type(error).__name__});sys.exit(2)

if __name__=='__main__':main()
