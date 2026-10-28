"""Acoustic quiet detection, with reversible source-time removals across text edits."""
import array,hashlib,json,math,re,subprocess,unicodedata
from pathlib import Path

def validate_pauses(value,duration):
    if not isinstance(value,list) or len(value)>200:raise ValueError('停顿清单无效')
    result=[];previous=-1;ids=set()
    for row in value:
        if (not isinstance(row,dict) or not re.fullmatch('[a-f0-9]{32}',str(row.get('id','')))
            or row['id'] in ids or type(row.get('keep')) is not bool
            or any(type(row.get(k)) not in (int,float) or not math.isfinite(row[k]) for k in ('start','end'))
            or not 0<=row['start']<row['end']<=duration or row['end']-row['start']<.3
            or row['start']<previous):raise ValueError('停顿时间、选择或引用无效')
        result.append({k:row[k] for k in ('id','start','end','keep')});previous=row['end'];ids.add(row['id'])
    return result

def protected_word_ranges(record,duration,padding=.15):
    ranges=[]
    for segment in record.get('segments',[]):
        for word in segment.get('words',[]):
            start,end=word.get('start'),word.get('end')
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,end)) or not 0<=start<=end<=duration:
                raise ValueError('原词时间无效，未自动建议删除低音量区间')
            if start==end:
                text=word.get('word','')
                if not text or all(c.isspace() or unicodedata.category(c).startswith('P') for c in text):continue
                # A spoken character with no acoustic span is not a cut point.
                # Protect its containing sentence rather than removing nearby
                # quiet based on an interpolated zero-length timestamp.
                start=min(start,segment.get('start',start));end=max(end,segment.get('end',end))
            ranges.append((max(0,start-padding),min(duration,end+padding)))
    merged=[]
    for start,end in sorted(ranges):
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    return merged

def exclude_recognized_speech(ranges,protected):
    result=[]
    for start,end in ranges:
        cursor=start
        for a,b in protected:
            if b<=cursor:continue
            if a>=end:break
            if a>cursor:result.append((cursor,min(a,end)))
            cursor=max(cursor,b)
            if cursor>=end:break
        if cursor<end:result.append((cursor,end))
    return result

def detect(record,api,key=None):
    path=Path(record.get('video_path') or record['audio_path']);duration=record['duration_seconds']
    with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    protected=protected_word_ranges(record,duration)
    protected_digest=hashlib.sha256(json.dumps(protected,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    cache_digest=hashlib.sha256(('v4:'+digest+':'+protected_digest).encode()).hexdigest()
    cache=api.ROOT/'recognition-cache';cache.mkdir(exist_ok=True);receipt=cache/('pauses-v4-'+cache_digest+'.json')
    if receipt.exists():return json.loads(receipt.read_text('utf-8'))|{'sourceId':record['video_id']}
    args=[str(api.FFMPEG),'-v','error','-nostdin','-i',str(path),'-vn','-ac','1','-ar','16000','-f','s16le','-']
    if key:api.TASKS.progress(key,'正在找长停顿和空白');api.TASKS.check(key)
    log=subprocess.run(args,capture_output=True,timeout=120)
    if log.returncode:raise ValueError('暂时无法读取音轨停顿')
    if key:api.TASKS.check(key)
    samples=array.array('h',log.stdout);levels=[]
    for i in range(0,len(samples),800):
        block=samples[i:i+800];levels.append(20*math.log10(max(1,math.sqrt(sum(x*x for x in block)/len(block)))/32768))
    threshold=max(-50,min(-35,sorted(levels)[int(len(levels)*.2)]+9)) if levels else -40
    ranges=exclude_recognized_speech(quiet_ranges(levels,threshold,duration),protected)
    candidates=[];start=None
    for start,end in ranges:
        left=round(max(0,start+.1),3);right=round(max(0,end-.1),3)
        if right-left>=.3:candidates.append({'id':hashlib.sha256(f'{digest}:{left}:{right}'.encode()).hexdigest()[:32],'start':left,'end':right,'keep':False})
    result={'version':4,'method':'adaptive-rms-50ms-transcript-guard','protectedWordsSha256':protected_digest,'protectedWordPaddingSeconds':.15,'wordAlignmentVerified':False,'thresholdDb':round(threshold,2),'sourceId':record['video_id'],'mediaSha256':digest,'pauses':validate_pauses(candidates,duration)}
    temp=receipt.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');temp.replace(receipt)
    return result

def quiet_ranges(levels,threshold,duration):
    # Bridge brief handling clicks so a quiet thinking pause is not fragmented.
    quiet=[x<threshold for x in levels];i=0
    while i<len(quiet):
        if quiet[i]:i+=1;continue
        a=i
        while i<len(quiet) and not quiet[i]:i+=1
        if a>0 and i<len(quiet) and i-a<=2:quiet[a:i]=[True]*(i-a)
    ranges=[];start=None
    for i,flag in enumerate(quiet+[False]):
        if flag and start is None:start=i*.05
        if not flag and start is not None:
            end=min(duration,i*.05)
            if end-start>=.55-1e-8:ranges.append((start,end))
            start=None
    return ranges

def apply_pauses(clips,source,pauses,max_clips=400):
    if not pauses:return clips
    from audio_cuts import apply_audio_cuts,audio_run_key
    out=[]
    for clip in clips:
        parts=[dict(clip)]
        for quiet in pauses:
            if quiet['keep']:continue
            next_parts=[]
            for c in parts:
                start=max(c['start'],quiet['start']);end=min(c['end'],quiet['end'])
                if end-start<.001:next_parts.append(c);continue
                # Never remove a complete utterance or leave an unplayable sliver.
                if start<=c['start']+.04 or end>=c['end']-.04:
                    if start<=c['start']+.04 and end>=c['end']-.04:next_parts.append(c);continue
                    if start<=c['start']+.04:next_parts.append({**c,'start':end});continue
                    if end>=c['end']-.04:next_parts.append({**c,'end':start});continue
                key=audio_run_key(c)
                next_parts.extend(apply_audio_cuts([c],source,{key:[{'id':quiet['id'],'start':start,'end':end,'wordCut':True}]}))
            parts=next_parts
        estimated_words=clip.get('words') and any(w.get('timingEstimated') for w in clip['words'])
        actually_cut=abs(sum(p['end']-p['start'] for p in parts)-(clip['end']-clip['start']))>.001
        if estimated_words and actually_cut and parts:
            # Quiet detection cuts sound, not words. Estimated ASR timestamps
            # may put real speech inside a quiet interval. Keep the retained
            # transcript once, captioned over the concatenated audible run.
            group=audio_run_key(clip)
            for p in parts:p.update(pauseCaptionGroup=group,pauseCaptionText=clip['text'],words=[],captionTiming='estimated')
        elif clip.get('captionTiming')=='estimated' and parts:
            chars=list(clip['text']);total=sum(p['end']-p['start'] for p in parts);elapsed=0;at=0
            for index,p in enumerate(parts):
                elapsed+=p['end']-p['start'];until=len(chars) if index==len(parts)-1 else round(len(chars)*elapsed/total)
                p.update(text=''.join(chars[at:until]),words=[],captionTiming='estimated');p.pop('captionCorrectionInactive',None);at=until
        out.extend(parts)
    if len(out)>max_clips:raise ValueError('停顿过多，请分段处理')
    return out
