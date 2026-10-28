"""Detect repeated source sound before encoding, independently of ASR wording.

This validates physical source ranges; it never trims, merges or rewrites them.
Small silence/rounding overlaps are reported too, but only a repeated spoken
word centre or a substantial shared range blocks export.
"""
VERSION=1


def check(clips):
    overlaps=[];blocking=[]
    for i,left in enumerate(clips):
        for j in range(i+1,len(clips)):
            right=clips[j];start=max(left['start'],right['start']);end=min(left['end'],right['end'])
            if end-start<=.001:continue
            duplicate=[]
            for owner in (left,right):
                for word in owner.get('words',[]):
                    if not any(c.isalnum() for c in word['word']):continue
                    center=word.get('acousticCenter',(word['start']+word['end'])/2)
                    if start+.02<center<end-.02:duplicate.append(word['word'])
            item={'indices':[i,j],'ids':[left['id'],right['id']],'start':start,'end':end,'seconds':round(end-start,4),'wordCentres':duplicate}
            overlaps.append(item)
            if duplicate or end-start>.08:
                blocking.append({**item,'reason':'两处保留片段重复取用同一段原音，不能直接拼接；需重新校准完整声音边界'})
    return {'version':VERSION,'passed':not blocking,'overlaps':overlaps,'blocking':blocking,'method':'source-range-reuse-before-encoding'}
