"""Authoritative cloud text, independent of local acoustic timing generation."""
import hashlib,json,math,uuid,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import cloud_asr

def recognize_file(key,path,duration,api,digest=None,purpose='source'):
    path=Path(path)
    if purpose not in ('source','final-audio-check'):raise ValueError('声音识别用途无效')
    if duration<=0:raise ValueError('视频时长无效')
    if digest is None:
        with path.open('rb') as media:digest=hashlib.file_digest(media,'sha256').hexdigest()
    cache=api.ROOT/'recognition-cache';cache.mkdir(exist_ok=True)
    receipt=cache/(digest+'.json')
    if receipt.is_file():
        recognized=json.loads(receipt.read_text('utf-8'))
        if recognized.get('mediaSha256')!=digest or recognized.get('model') not in (None,cloud_asr.MODEL):raise ValueError('语音识别记录与视频不匹配')
        return cloud_asr.normalize_receipt(recognized)
    # Task context follows audio extraction into the import's worker thread.
    local=getattr(api.TASKS,'local',None);old=getattr(local,'key',None)
    if local is not None:local.key=key
    try:
        windows=[];waves=[];count=math.ceil(duration/120)
        for index in range(count):
            api.TASKS.check(key);start=index*120;end=min(start+120,duration)
            prefix='recognition' if purpose=='source' else 'final-audio-check'
            wave=api.ROOT/'uploads'/f'{prefix}-{key}-{index}.wav'
            api.command(['-ss',str(start),'-i',str(path),'-t',str(end-start),'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(wave)])
            windows.append({'start':start,'end':end});waves.append(wave)
        def one(index):
            api.TASKS.check(key);audio=waves[index].read_bytes();audio_sha=hashlib.sha256(audio).hexdigest()
            part=cache/(digest+'-window-'+str(index)+'-'+str(count)+'.json')
            try:
                saved=json.loads(part.read_text('utf8'))
                if saved['model']==cloud_asr.MODEL and saved['audioSha256']==audio_sha and saved['start']==windows[index]['start'] and saved['end']==windows[index]['end'] and isinstance(saved['answer']['text'],str) and saved['answer']['text'].strip():return index,saved['answer']
            except (OSError,ValueError,KeyError,TypeError):pass
            def request_audio(data,start,end):
                sha=hashlib.sha256(data).hexdigest();span_file=cache/(digest+f'-span-{start:.3f}-{end:.3f}.json')
                try:
                    prior=json.loads(span_file.read_text('utf8'))
                    if prior['audioSha256']==sha and prior['model']==cloud_asr.MODEL and isinstance(prior['answer']['text'],str) and prior['answer']['text'].strip():return prior['answer']
                except (OSError,ValueError,KeyError,TypeError):pass
                def publish(value):
                    tmp=span_file.with_suffix('.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps({'audioSha256':sha,'model':cloud_asr.MODEL,'answer':value},ensure_ascii=False),'utf8');tmp.replace(span_file);return value
                for attempt in range(2):
                    try:return publish(cloud_asr.recognize(data))
                    except Exception as error:
                        api.TASKS.check(key)
                        incomplete=isinstance(error,ValueError) and '未返回完整文稿' in str(error)
                        if incomplete and end-start>20.01:
                            # A model's incomplete response is not silence and
                            # never permission to replace words with local ASR.
                            # Retry smaller real waveform windows instead.
                            step=40 if end-start>40.01 else 20;sub=[];usage=[];at=start
                            while at<end-.001:
                                until=min(end,at+step);wave=api.ROOT/'uploads'/f'recognition-split-{key}-{at:.3f}-{until:.3f}.wav'
                                api.command(['-ss',str(at),'-i',str(path),'-t',str(until-at),'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(wave)])
                                child=request_audio(wave.read_bytes(),at,until)
                                usage.append(child.get('usage',{}))
                                sub.extend(child.get('windows',[{'start':at,'end':until,'text':child['text']}]))
                                at=until
                            return publish({'text':'\n'.join(w['text'] for w in sub),'model':cloud_asr.MODEL,'usage':{'requests':usage},'windows':sub,'adaptiveSplit':True})
                        if attempt or any(code in str(error) for code in ('401','403','402')):
                            raise ValueError(f'云端第{index+1}/{count}段（{start:.0f}–{end:.0f}秒）未识别完成；原件与已完成缓存保留，请稍后重试') from None
                        time.sleep(1)
            thread_local=getattr(api.TASKS,'local',None);previous=getattr(thread_local,'key',None)
            if thread_local is not None:thread_local.key=key
            try:answer=request_audio(audio,windows[index]['start'],windows[index]['end'])
            finally:
                if thread_local is not None:thread_local.key=previous
            api.TASKS.check(key)
            checkpoint={'model':cloud_asr.MODEL,'audioSha256':audio_sha,**windows[index],'answer':answer}
            tmp=part.with_suffix('.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(checkpoint,ensure_ascii=False),'utf8');tmp.replace(part)
            return index,answer
        answers={}
        with ThreadPoolExecutor(max_workers=2,thread_name_prefix='cloud-asr') as pool:
            futures=[pool.submit(one,i) for i in range(count)]
            try:
                for future in as_completed(futures):
                    index,answer=future.result();answers[index]=answer
                    message=f'云端文稿识别 {len(answers)}/{count} · 声音定位同时准备' if purpose=='source' else f'正在复核成片声音 {len(answers)}/{count}'
                    api.TASKS.progress(key,message,{'stage':'cloud-asr' if purpose=='source' else purpose,'completedWindows':len(answers),'windows':count})
            except Exception:
                for future in futures:future.cancel()
                raise
        recognized={'model':cloud_asr.MODEL,'mediaSha256':digest,'text':'\n'.join(answers[i]['text'] for i in range(count)),'usage':[answers[i]['usage'] for i in range(count)],'windows':[part for i,w in enumerate(windows) for part in answers[i].get('windows',[{**w,'text':answers[i]['text']}])]}
        api.TASKS.check(key)
        temp=receipt.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(recognized,ensure_ascii=False),'utf-8');temp.replace(receipt)
        return cloud_asr.normalize_receipt(recognized)
    finally:
        if local is not None:local.key=old
