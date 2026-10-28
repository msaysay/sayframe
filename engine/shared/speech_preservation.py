"""Verify explicit speech preservation without editing or authorizing output.

The caller supplies authority only after bound planning confirmation. This
checker never reads a model flag. Ordinary acoustic and output gates still run.
"""

VERSION=1
EDITORIAL={'label','contentValue','emphasis','deleted','discardReason'}


def unchanged(before,after,source_id,original_source_id,settings):
    refs={r['id']:r for r in before['segments']}
    if source_id!=original_source_id or len(after)!=len(refs) or {r['id'] for r in after}!=set(refs):
        raise ValueError('本轮要求保留声音，但原始音轨或文稿集合发生变化，未生成')
    for row in after:
        old=refs[row['id']]
        if {k:v for k,v in row.items() if k not in EDITORIAL}!={k:v for k,v in old.items() if k not in EDITORIAL}:
            raise ValueError('本轮要求保留声音，但原字、删字或声音边界发生变化，未生成')
    for key,default in [('pacing',{}),('speed',1)]:
        if settings.get(key,default)!=before['settings'].get(key,default):
            raise ValueError('本轮要求保留声音，但气口或倍速设置发生变化，未生成')
    return {'version':VERSION,'authority':'confirmed-latest-creator-message',
            'sourceId':source_id,'passed':True,'newWordCuts':0,
            'restoredWords':0,'timingChanged':False,'pacingChanged':False,
            'skipped':['word-edits','question-cuts','filler-alignment','speech-detection','proposal-alignment','pause-detection'],
            'cleanupVerified':False,'originalAcousticGatesRequired':True}
