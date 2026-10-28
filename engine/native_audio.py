"""WorkBuddy's native AudioTranscribe receipts, bound to prepared source audio.

The host records the exact tool return. Native readable timestamps inform
content, never authorize a physical cut or certify speaker attribution.
"""
import re
from pathlib import Path

def prepare(agent,video,directory):
    source=Path(video).expanduser().resolve();out=Path(directory).expanduser().resolve()
    if not source.is_file():raise agent.UserError('原视频不存在。')
    out.mkdir(parents=True,exist_ok=True)
    if list(out.iterdir()):raise agent.UserError('音轨准备目录须为空，避免覆盖旧证据。')
    info=agent.probe(source);sha=agent.digest(source);parts=[]
    for index,start in enumerate(range(0,__import__('math').ceil(info['duration']),1800)):
        end=min(info['duration'],start+1800);file=out/f'audio-{index+1:03}.m4a'
        agent.run([agent.tool('ffmpeg'),'-n','-v','error','-ss',start,'-i',source,'-t',end-start,'-vn','-ac','1','-ar','16000','-c:a','aac','-b:a','64k',file])
        if file.stat().st_size>=1_000_000_000:raise agent.UserError('音轨仍超出原生工具限制，未提交转写。')
        parts.append({'id':f'a{index+1}','file':str(file),'sha256':agent.digest(file),'sourceStart':start,'sourceEnd':end})
    if agent.digest(source)!=sha:raise agent.UserError('音轨准备期间原视频变化，停止。')
    manifest={'version':1,'video':str(source),'sourceSha256':sha,'duration':info['duration'],'parts':parts,'next':'由当前WorkBuddy对每个part调用真实AudioTranscribe，逐一保存原样返回；不能用摘要替代。'}
    agent.atomic(out/'prepared-audio.json',manifest)
    return {'manifest':str(out/'prepared-audio.json'),**manifest}

def seconds(clock):
    parts=[float(x) for x in clock.split(':')]
    if len(parts) not in (2,3) or any(x<0 for x in parts) or any(x>=60 for x in parts[1:]):raise ValueError('invalid native timestamp')
    return sum(value*60**i for i,value in enumerate(reversed(parts)))

def validate(agent,manifest_file,receipt_file):
    manifest=agent.read(manifest_file);receipt=agent.read(receipt_file)
    if receipt.get('tool')!='AudioTranscribe' or receipt.get('sourceSha256')!=manifest['sourceSha256']:raise agent.UserError('原生转写来源不匹配。')
    if agent.digest(manifest['video'])!=manifest['sourceSha256']:raise agent.UserError('原视频变化，拒绝错源转写。')
    expected={p['id']:p for p in manifest['parts']};seen=set();rows=[]
    for result in receipt.get('parts',[]):
        part=expected.get(result.get('id'))
        if not part or part['id'] in seen or result.get('audioSha256')!=part['sha256'] or agent.digest(part['file'])!=part['sha256']:raise agent.UserError('音轨回执缺失、重复或来源不符。')
        raw=result.get('rawResult')
        if not isinstance(raw,str) or not raw.strip():raise agent.UserError('必须保存AudioTranscribe的原始返回，不能只交摘要。')
        matched=0
        for line in raw.splitlines():
            match=re.fullmatch(r'\s*\[([\d:.]+)\s*,\s*([\d:.]+)\s*,\s*([^\]]+)\]\s*(\S.*?)\s*',line)
            if not match:continue
            start,end=seconds(match[1]),seconds(match[2]);limit=part['sourceEnd']-part['sourceStart']
            if not 0<=start<end<=limit+.3:raise agent.UserError('原生转写时间超出对应音轨。')
            rows.append({'start':part['sourceStart']+start,'end':min(part['sourceEnd'],part['sourceStart']+end),'speakerLabel':match[3],'text':match[4],'part':part['id']});matched+=1
        if not matched:raise agent.UserError('未识别出原生时间格式；保留原回执，不能猜时间导入。')
        seen.add(part['id'])
    if seen!=set(expected):raise agent.UserError('还有音轨未转写，不能把抽样冒充全文。')
    rows.sort(key=lambda r:r['start'])
    return manifest,{'provider':'WorkBuddy.AudioTranscribe','receiptSha256':agent.digest(receipt_file),'sourceSha256':manifest['sourceSha256'],'segments':rows,'provenance':'host-recorded-tool-return-not-cryptographically-attested','coverageCertified':False,'speakerAttributionCertified':False,'notice':'原生可读稿用于内容理解；切口以原片的本地声学复核为准。'}
