"""Bound A/B listening excerpts; never an authority to edit speech.

Clients select an existing audit cue, never paths, words or cutting times.
Excerpts are context for review, not new movie clips or a phoneme verdict.
"""
import hashlib,json,math,uuid
from pathlib import Path
import final_audio_check,final_seams,expected_audio_words
VERSION=3
CONTEXT_VERSION=1
NOTE='原音包含未剪内容；成片包含实际混音。定位来自工程字音记录，可能不精确。对照只用于回听，不代表已确认丢字，也不会改动文稿或声音。'


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def context(mode):
    if mode is not None and mode not in ('standard','extended'):raise ValueError('请选择有效的声音对照范围')
    return 'extended' if mode=='extended' else None


def request_fields(payload):
    value={k:payload.get(k) for k in ['video','auditBinding','cueIndex']}
    if context(payload.get('contextMode')):value['contextMode']='extended'
    return value


def window(point,duration,mode=None):
    mode=context(mode)
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in [point,duration]) or duration<=0 or not 0<=point<=duration:raise ValueError('声音对照位置无效')
    before,after=(6,8) if mode=='extended' else (2.5,3.5)
    return [round(max(0,point-before),6),round(min(duration,point+after),6)]


def locate(project,issue,duration,mode=None):
    mode=context(mode)
    ref=issue.get('source') or {};index=ref.get('wordIndex')
    if type(index) is not int:raise ValueError('这处差异没有可靠原词定位，请先重新检查声音')
    rows=[r for r in project['segments'] if r['id']==ref.get('id')]
    if len(rows)!=1 or not 0<=index<len(rows[0]['words']):raise ValueError('原词定位不匹配')
    word=rows[0]['words'][index]
    # Use the same strictly bound raw-word coverage as the encoded audit.
    # This shallow view cannot change the stored project or bless a cut; it
    # only lets an existing review cue find its intended listening context.
    tables,_=expected_audio_words.resolve(project)
    view={**project,'clips':[{**clip,'words':words} for clip,words in zip(project['clips'],tables)]}
    candidates=[w for w in final_seams.timeline(view) if w['id']==ref['id'] and w['wordIndex']==index and w['word']==ref.get('word') and abs(w['nearSeconds']-ref.get('nearSeconds',-99))<=.002]
    if len(candidates)!=1 or word['word']!=ref.get('word'):raise ValueError('这处差异无法唯一对应实际成片，未猜测位置')
    point=word.get('acousticCenter',(word['start']+word['end'])/2)
    if type(point) not in (int,float) or not math.isfinite(point) or not word['start']<=point<=word['end']:point=(word['start']+word['end'])/2
    return {'id':ref['id'],'wordIndex':index,'word':word['word'],
            'originalWindow':window(point,duration,mode),'movieWindow':window(candidates[0]['nearSeconds'],sum(c.get('outputDuration',(c['end']-c['start'])/c.get('speed',1)) for c in project['clips'])+project.get('coverDuration',0),mode),**({'contextMode':'extended'} if mode else {})}


def prepare(payload,api):
    owner,movie=final_audio_check.completed(payload.get('video'),api)
    audit=final_audio_check.cached(owner,movie,api);index=payload.get('cueIndex')
    if not audit or audit.get('binding')!=payload.get('auditBinding'):raise ValueError('声音检查已变化，请重新打开当前成片')
    return prepare_audit(owner,movie,audit,index,api,context(payload.get('contextMode')))


def prepare_audit(owner,movie,audit,index,api,mode=None):
    """Internal encoded-render audit entry; not exposed as a client payload.

    A render has finished writing media before its enclosing job is done.
    Keep completed() mandatory for public routes, and independently bind the
    in-process audit to those exact media/project bytes here.
    """
    _,_,sha,binding=final_audio_check.inputs(owner,movie,api)
    if (not audit or audit.get('actualEncodedMovie') is not True or audit.get('ownerJobId')!=owner
        or audit.get('binding')!=binding or audit.get('mediaSha256')!=sha
        or type(index) is not int or not 0<=index<len(audit.get('differences',[]))):raise ValueError('声音检查已变化，请重新打开当前成片')
    media,path=final_audio_check.paths(owner,movie,api);project=json.loads(path.read_text('utf8'))
    record=api.get_case(project['sourceId']);source=api.public_case(record,True)
    api.PROJECT_LIBRARY.clean_project(project,source)
    original=Path(record.get('video_path') or record.get('audio_path') or '')
    if not original.is_file():raise ValueError('原始声音文件暂不可用，成片保持不变')
    target=locate(project,audit['differences'][index],source['duration'],context(mode));stat=original.stat()
    conflict=__import__('source_text_conflicts').inspect(project,source,audit['differences'][index].get('source'))
    if conflict is not None:target['sourceTextContext']=conflict
    stamp={'bytes':stat.st_size,'mtimeNs':stat.st_mtime_ns}
    binding=hashlib.sha256(json.dumps({'version':VERSION,'auditBinding':audit['binding'],'projectSha256':digest(path),'sourceId':project['sourceId'],'sourceFile':str(original.resolve()),'sourceStat':stamp,'target':target},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'owner':owner,'media':media,'original':original,'binding':binding,'auditBinding':audit['binding'],'target':target,'sourceStat':stamp,'projectSha256':digest(path)}


def cached_pair(bound,api):
    owner=bound['owner'];folder=api.ROOT/'outputs'/owner
    receipt=folder/('audio-comparison-'+bound['binding']+'.json')
    if receipt.is_file():
        try:
            old=json.loads(receipt.read_text('utf8'));items=old.get('excerpts',[])
            if old.get('binding')!=bound['binding'] or old.get('projectSha256')!=bound['projectSha256'] or old.get('sourceStat')!=bound['sourceStat'] or old.get('target')!=bound['target'] or len(items)!=2 or {a.get('kind') for a in items}!={'original','movie'}:return None
            for a in items:
                kind=a['kind'];url=f'/outputs/{owner}/audio-comparison-{bound["binding"]}-{kind}.wav';path=api.ROOT/url.lstrip('/')
                if a.get('url')!=url or a.get('window')!=bound['target']['originalWindow' if kind=='original' else 'movieWindow'] or not path.is_file() or digest(path)!=a.get('sha256'):return None
            return {**old,'reused':True}
        except (ValueError,OSError,TypeError,KeyError):return None
    return None


def render_pair(key,bound,refresh,api):
    owner=bound['owner'];folder=api.ROOT/'outputs'/owner
    receipt=folder/('audio-comparison-'+bound['binding']+'.json')
    old=cached_pair(bound,api)
    if old is not None:return old
    api.TASKS.progress(key,'正在准备原音与成片对照')
    excerpts=[];temps=[]
    try:
        for kind,path,interval in [('original',bound['original'],bound['target']['originalWindow']),('movie',bound['media'],bound['target']['movieWindow'])]:
            api.TASKS.check(key);dest=folder/f'audio-comparison-{bound["binding"]}-{kind}.wav';temp=dest.with_name(dest.stem+'-'+uuid.uuid4().hex+'.wav');temps.append(temp)
            # Decode first, trim in decoded time; never use these windows to
            # alter the movie or issue a new cutting plan.
            api.TASKS.process([str(api.FFMPEG),'-v','error','-i',str(path),'-ss',str(interval[0]),'-t',str(interval[1]-interval[0]),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le','-y',str(temp)],timeout=60)
            if temp.stat().st_size<=44:raise ValueError('声音对照片段为空')
            excerpts.append({'kind':kind,'url':f'/outputs/{owner}/{dest.name}','window':interval,'sha256':digest(temp),'destination':dest})
        if refresh()['binding']!=bound['binding']:raise ValueError('准备期间声音或工程已变化，未使用过期对照')
        for temp,a in zip(temps,excerpts):temp.replace(a.pop('destination'))
        value={'version':VERSION,'binding':bound['binding'],'auditBinding':bound['auditBinding'],'ownerJobId':owner,'target':bound['target'],'sourceStat':bound['sourceStat'],'projectSha256':bound['projectSha256'],'excerpts':excerpts,'note':NOTE,'changedSpeech':False,'reused':False}
        api.save(receipt,value);return value
    finally:
        for temp in temps:temp.unlink(missing_ok=True)


def run(key,payload,api):
    return render_pair(key,prepare(payload,api),lambda:prepare(payload,api),api)


def from_audit(key,owner,movie,audit,index,api):
    return render_pair(key,prepare_audit(owner,movie,audit,index,api),lambda:prepare_audit(owner,movie,audit,index,api),api)


def submit(payload,api):
    bound=prepare(payload,api)
    request=request_fields(payload)
    with api.TASKS.lock:
        active=next((j for j in api.JOBS.values() if j.get('kind')=='audio-comparison' and j.get('status') in ('queued','running','cancelling') and j.get('request')==request),None)
        if active:return active['id']
        return api.TASKS.submit('audio-comparison','原音与成片对照',request,lambda key:run(key,request,api),request_token=payload.get('requestToken'))
