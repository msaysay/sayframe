"""Source-bound acoustic preflight shared by automatic completion and export.

Only timings of the submitted clips can change. Text, selection and order do
not. User cuts and previously audited deleted-word boundaries take priority.
"""
import copy,hashlib,json,uuid
from pathlib import Path
VERSION=17

def source_mismatch(ids,row,first,second):
    """Bound original-audio observations for semantic regrouping, not rewriting.

    A recognition mismatch does not certify that an original word is absent.
    Keep both windows and the exact expected text; no approximate-match bypass.
    """
    return {'ids':list(ids),'reason':'保留原话与两次原音核对未能一致对应',
            'sourceEvidence':{'expected':''.join(w['word'] for w in row['words'])[:1200],
                              'recognizedWindows':[''.join(t['text'] for t in trace)[:1600] for trace in (first,second)],
                              'policy':'原音识别差异不是删字依据；只可比较其他完整语义组，不能改原词、猜切点或放宽否定/数字/正常字保护。'}}

class CalibrationRejected(ValueError):
    def __init__(self,blocking):
        self.blocking=copy.deepcopy(blocking)
        super().__init__('部分声音切口还不能安全定位，未导出截字版本：'+blocking[0]['reason'])

def source_links(clips,source,edges):
    """Pairs of adjacent retained source speech that will be decoded once.

    Deleted spoken words, reorders, user edits and long gaps remain real cuts.
    A caption boundary inside one such run is not a phoneme boundary.
    """
    from pacing import word_index,clip_edge_key
    rows,positions=word_index(source);links=set()
    for index,(left,right) in enumerate(zip(clips,clips[1:])):
        a=positions.get(f"{left['id']}:{left['lastIndex']}");b=positions.get(f"{right['id']}:{right['firstIndex']}")
        if a is None or b is None or b<=a:continue
        if any(any(ch.isalnum() for ch in w['word']) for w in rows[a+1:b]):continue
        if 'end' in edges.get(clip_edge_key(left),{}) or 'start' in edges.get(clip_edge_key(right),{}):continue
        if left.get('audioFragment') or right.get('audioFragment'):continue
        links.add(index)
    return links

def continuity_links(clips,source,edges):
    return {i for i in source_links(clips,source,edges) if abs(clips[i+1]['start']-clips[i]['end'])<=.9}

def normalize_seams(clips,source,edges,frozen=()):
    from speech_seams import normalize
    locked=__import__('frozen_clip_bounds').indices(clips,frozen) if frozen else ()
    return normalize(clips,continuity_links(clips,source,edges),locked)

def calibrate(key,record,clips,payload,api,*,frozen_clips=(),frozen_retractions=()):
    source=api.public_case(record,True);pacing=payload.get('settings',{}).get('pacing',{})
    if frozen_clips:clips=__import__('frozen_clip_bounds').apply(clips,frozen_clips)
    exclusions=__import__('cut_exclusions').collect(source['segments'],payload.get('segments',[]))
    python=api.ROOT.parent/'research/tools/sensevoice-python/Scripts/python.exe'
    model=Path.home()/'.cache/sayframe-asr/sensevoice-2024'
    if not python.is_file() or not (model/'model.int8.onnx').is_file():
        raise ValueError('声音切口校准尚未准备好，未导出可能截字的版本')
    media=Path(record['video_path']);stat=media.stat()
    signature={'version':VERSION,'sourceId':source['id'],'media':[stat.st_size,stat.st_mtime_ns],
               'clips':clips,'edges':pacing.get('edges',{}),'pauses':pacing.get('pauses',[]),'verifiedExclusions':exclusions}
    if frozen_clips:signature['frozenClipBounds']={'version':__import__('frozen_clip_bounds').VERSION,'clips':frozen_clips,'paddingRetractions':frozen_retractions}
    digest=hashlib.sha256(json.dumps(signature,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    cache=api.ROOT/'recognition-cache'/('clip-calibration-v1-'+digest+'.json')
    if cache.is_file():receipt=json.loads(cache.read_text('utf-8'))
    else:
        request=api.ROOT/'recognition-cache'/('clip-calibration-request-'+uuid.uuid4().hex+'.json')
        request_data={'source':source,'clips':clips,'edges':pacing.get('edges',{}),'verifiedExclusions':exclusions,
                          'video':str(media),'ffmpeg':str(api.FFMPEG),'model':str(model),**({'frozenClips':frozen_clips,'frozenPaddingRetractions':frozen_retractions} if frozen_clips else {})}
        api.save(request,request_data)
        try:
            api.TASKS.progress(key,'正在核对开场、句尾和重复切口')
            receipt=json.loads(api.TASKS.process([str(python),'-X','utf8',str(api.ROOT/'clip_calibration_worker.py'),str(request)],cwd=api.ROOT,timeout=180))
            if receipt.get('blocking'):
                from preserved_edge_recovery import prepare
                try:proofs,recovery=prepare(request_data,receipt,api,key)
                except (OSError,ValueError,RuntimeError) as error:
                    api.TASKS.check(key)
                    proofs,recovery=[],{'attempted':True,'reason':'independent audio witness unavailable; original refusal preserved','errorKind':type(error).__name__}
                if proofs:
                    initial=receipt
                    api.save(request,{**request_data,'preservedOuterEdges':proofs})
                    receipt=json.loads(api.TASKS.process([str(python),'-X','utf8',str(api.ROOT/'clip_calibration_worker.py'),str(request)],cwd=api.ROOT,timeout=180))
                    receipt['initialFailure']={'blocking':initial['blocking'],'extraRestarts':initial.get('extraRestarts',[])}
                receipt['preservedEdgeRecovery']=recovery
        finally:request.unlink(missing_ok=True)
        api.save(cache,receipt)
    api.TASKS.check(key)
    report={k:v for k,v in receipt.items() if k!='clips'}|{'receipt':cache.name,'version':VERSION}
    folder=api.ROOT/'outputs'/key;folder.mkdir(parents=True,exist_ok=True)
    api.save(folder/'clip-calibration.json',report)
    revised=receipt.get('clips')
    if not isinstance(revised,list) or len(revised)!=len(clips):raise ValueError('声音切口回执无效，未输出')
    for before,after in zip(clips,revised):
        for field in ('id','firstIndex','lastIndex','text'):
            if before[field]!=after.get(field):raise ValueError('声音校准改变了选词或顺序，未输出')
        if not 0<=after['start']<after['end']<=source['duration']:raise ValueError('声音校准区间无效')
        if [(w['index'],w['word'],w.get('captionWord')) for w in before.get('words',[])]!=[(w['index'],w['word'],w.get('captionWord')) for w in after.get('words',[])]:raise ValueError('声音校准改变了原字，未输出')
    if receipt.get('blocking'):
        # The cached decision is unchanged; expose its actual failed edge.
        raise CalibrationRejected(__import__('audio_failure_context').enrich(receipt['blocking'],revised,receipt.get('audits',[])))
    revised=normalize_seams(revised,source['segments'],pacing.get('edges',{}),frozen_clips)
    if frozen_clips:
        if receipt.get('frozenClipBoundsVersion')!=__import__('frozen_clip_bounds').VERSION:raise ValueError('沿用取音缺少本次原声核验，未输出')
        report['frozenClipBounds']=__import__('frozen_clip_bounds').verify(revised,frozen_clips)
    leaked=__import__('cut_exclusions').leaks(revised,exclusions)
    if leaked:raise CalibrationRejected(leaked)
    return revised,report
