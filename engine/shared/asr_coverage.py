"""Detect gross cloud ASR omissions against local timing; never substitute local text."""
import copy,re

def letters(text):
    return ''.join(c for c in text if c.isalnum())

def local_size(segments,start,end):
    return sum(len(letters(w['word'])) for s in segments for w in s.get('words',[])
               if w['end']>start and w['start']<end)

def missing(text,segments,start,end):
    if re.match(r'\s*(?:think>|<think>|<chinese>)',text):return True
    size=local_size(segments,start,end)
    # Short answers and silence cannot establish an omission. This conservative
    # guard detects a long spoken passage reduced to a few words, not accuracy.
    return size>=100 and len(letters(text))<size*.2

def recover(receipt,segments,duration,recognize_span):
    windows=receipt.get('windows')
    if not isinstance(windows,list):return receipt,[]
    bad=[i for i,w in enumerate(windows) if missing(w['text'],segments,w['start'],w['end'])]
    if not bad:return receipt,[]
    fixed=[];usage=list(receipt.get('usage',[]));repairs=[]
    def complete(start,end,step=40):
        out=[];at=start
        while at<end-.001:
            until=min(at+step,end);answer=None
            try:answer=recognize_span(at,until)
            except ValueError as error:
                if '未返回完整文稿' not in str(error):raise
            if answer is not None:usage.append(answer.get('usage',{}))
            if answer is None or missing(answer['text'],segments,at,until):
                if until-at<=10.001:raise ValueError(f'{at:.0f}–{until:.0f}秒仍有较多漏识别，完整文稿尚未准备好；未用本地文字替代')
                out.extend(complete(at,until,max(10,step/2)))
            else:out.append({'start':at,'end':until,'text':answer['text']})
            at=until
        # Short windows alone may be below the gross-omission threshold. The
        # original long interval must still have enough heard content jointly.
        if missing(''.join(w['text'] for w in out),segments,start,end):
            if step<=10:raise ValueError(f'{start:.0f}–{end:.0f}秒仍有较多漏识别，完整文稿尚未准备好；未用本地文字替代')
            return complete(start,end,max(10,step/2))
        return out
    for i,w in enumerate(windows):
        if i not in bad:fixed.append(copy.deepcopy(w));continue
        start=w['start'];end=w['end']
        if not 0<=start<end<=duration:raise ValueError('语音识别分段时间无效')
        restored=complete(start,end);fixed.extend(restored);repairs.extend({'start':w['start'],'end':w['end']} for w in restored)
    return {**receipt,'windows':fixed,'text':'\n'.join(w['text'] for w in fixed),
            'usage':usage,'coverageVersion':1,'coverageRepairs':repairs},repairs
