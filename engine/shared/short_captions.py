"""Short single-line captions; a user newline is a timed cue boundary."""
import re,unicodedata
VERSION=1
def spoken(ch):return ch in '%‰' or not unicodedata.category(ch).startswith('P')

NUMBER=re.compile(r'\d+(?:\ue000\d+)?(?:[%‰]|年|月|日|秒|倍|元|个|人|次|对儿?)?|[零〇一二三四五六七八九十百千万亿两]+分之[零〇一二三四五六七八九十百千万亿两]+|[零〇一二三四五六七八九十百千万亿两]{2,}(?:年|月|日|秒|倍|元|个|人|次|对儿?)?')

def word_tokens(line):
    def words(part):
        try:
            import jieba
            jieba.setLogLevel(40);return list(jieba.cut(part))
        except ImportError:return list(part)
    result=[];at=0
    for match in NUMBER.finditer(line):
        result.extend(words(line[at:match.start()]));result.append(match.group());at=match.end()
    result.extend(words(line[at:]));return caption_units(result)

def caption_units(tokens):
    """Bind small grammatical units for display only; never rewrite words."""
    paired=('会不会','能不能','是不是','要不要','有没有','对不对','好不好')
    bound=[];at=0
    while at<len(tokens):
        match=None
        for size in (3,2):
            if at+size<=len(tokens) and ''.join(tokens[at:at+size]) in paired:match=size;break
        if match:bound.append(''.join(tokens[at:at+match]));at+=match
        else:bound.append(tokens[at]);at+=1
    units=[]
    for token in bound:
        if units and token in ('的','了') and not re.search(r'[\s，。！？；,.!?;]$',units[-1]):
            if (token=='的' and units[-1] in ('我','你','他','她','它','我们','你们','他们','她们','它们')) or token=='了':
                units[-1]+=token;continue
        units.append(token)
    result=[];at=0
    while at<len(units):
        token=units[at]
        if token in ('跟','把','被','给','对','与','和','从','往','向','在','到') and at+1<len(units) and not re.search(r'[\s，。！？；,.!?;]',units[at+1]):
            result.append(token+units[at+1]);at+=2
        else:result.append(token);at+=1
    return result

def display_timing(rows,start,end):
    """Resolve overlapping *visual* cues, preserving every cue and source anchor."""
    if not rows:return rows
    rows=[dict(row) for row in rows]
    valid=all(start<=r['start']<r['end']<=end for r in rows)
    if valid:
        for previous,current in zip(rows,rows[1:]):
            if previous['end']>current['start']:
                boundary=(previous['end']+current['start'])/2
                if not previous['start']<boundary<current['end']:valid=False;break
                previous['end']=current['start']=boundary
                previous['displayTiming']=current['displayTiming']='overlap-boundary'
    if not valid:
        # Contradictory acoustic anchors cannot be cutting evidence. Allocate
        # display time only, so a short normal word is never silently dropped.
        total=sum(len(r['text']) for r in rows);at=start
        for row in rows:
            until=at+(end-start)*len(row['text'])/total
            row.update(start=at,end=until,displayTiming='estimated-visual-only');at=until
    return rows
def chunks(text,limit=10):
    text=re.sub(r'(?<=\d)\.(?=\d)','\ue000',text)
    result=[]
    def push(value):
        value=''.join(ch for ch in value if spoken(ch)).replace('\ue000','.').strip()
        if not value:return
        if result and re.fullmatch(r'[，。！？；,.!?;]+',value):
            if len(result[-1]+value)<=limit:result[-1]+=value
            else:
                previous=result[-1];at=max(1,len(previous)-max(2,len(value)))
                result[-1]=previous[:at];result.append(previous[at:]+value)
        else:result.append(value)
    for line in text.splitlines():
        first=len(result)
        tokens=word_tokens(line.strip())
        run=''
        for token in tokens:
            if run and (len(run+token)>limit or (len(run)>=6 and re.match(r'^(不要|不能|但是|而且|如果|所以|而不是)',token))):
                push(run);run=''
            if NUMBER.fullmatch(token) and len(token)<=limit:
                run+=token
                if len(run)>=limit:push(run);run=''
                continue
            for ch in token:
                run+=ch
                if ch in '，。！？；,.!?;' or len(run)>=limit:
                    push(run)
                    run=''
        push(run)
        if len(result)-first>=2 and len(result[-1])<=2 and len(result[-2])>=6:
            previous=result[-2]
            tail_tokens=word_tokens(previous)
            tail=''
            for token in reversed(tail_tokens):
                tail=token+tail
                if len(tail)>=2:break
            if len(previous)-len(tail)>=4 and len(tail)+len(result[-1])<=limit:
                result[-2]=previous[:-len(tail)];result[-1]=tail+result[-1]
    return result
def cues(clips,limit=10):
    groups=[]
    for clip in clips:
        if clip.get('pauseCaptionGroup'):
            length=clip.get('outputDuration',(clip['end']-clip['start'])/clip.get('speed',1))
            if groups and groups[-1].get('pauseCaptionGroup')==clip['pauseCaptionGroup']:
                groups[-1]['outputDuration']+=length;groups[-1]['end']=groups[-1]['outputDuration']
            else:groups.append({**clip,'start':0,'end':length,'outputDuration':length,'text':clip['pauseCaptionText'],'words':[]})
        else:groups.append(dict(clip))
    clips=groups
    result=[];offset=0
    for clip in clips:
        first=len(result)
        length=clip.get('outputDuration',clip['end']-clip['start']);end=offset+length
        if clip.get('captionTiming')=='silent-original':offset=end;continue
        words=[{**w,'word':w.get('captionWord',w['word'])} for w in clip.get('words',[])];visual_words=words
        if any(w['end']<=w['start'] and any(spoken(ch) and not ch.isspace() for ch in w['word']) for w in words):
            # Unknown word timing must not silently remove a subtitle, especially
            # a short negation or condition. Allocate the retained clip text over
            # its audible duration while keeping original word times immutable.
            words=[]
        if words:
            expanded=[]
            for w in words:
                chars=[ch for ch in w['word'] if spoken(ch) or ch=='.'];span=w['end']-w['start']
                expanded.extend({**w,'word':c,'start':w['start']+span*i/len(chars),'end':w['start']+span*(i+1)/len(chars)} for i,c in enumerate(chars))
            lines=chunks(''.join(w['word'] for w in words),limit)
            expanded=[w for i,w in enumerate(expanded) if spoken(w['word']) or (w['word']=='.' and i>0 and i+1<len(expanded) and expanded[i-1]['word'].isdigit() and expanded[i+1]['word'].isdigit())]
            at=0;tempo=clip.get('speed',1)
            for text in lines:
                # Map text boundaries back to audio, retaining punctuation and highlights.
                while at<len(expanded) and expanded[at]['word'].isspace():at+=1
                group=expanded[at:at+len(text)];at+=len(text)
                if group:result.append({'start':max(offset,offset+(group[0]['start']-clip['start'])/tempo),'end':min(end,offset+(group[-1]['end']-clip['start'])/tempo),'text':text,'parts':group})
        else:
            lines=chunks(clip['text'],limit);weights=[len(x) for x in lines];total=sum(weights);at=offset
            # Styling may still refer to original words when their audio times
            # are unknown. These are display-only parts, never cutting anchors.
            visual=[{'word':ch,'emphasis':w.get('emphasis',False),'timing':'display-only'} for w in visual_words for ch in w['word'] if (spoken(ch) or ch=='.') and not ch.isspace()]
            visual=[w for i,w in enumerate(visual) if spoken(w['word']) or (w['word']=='.' and i>0 and i+1<len(visual) and visual[i-1]['word'].isdigit() and visual[i+1]['word'].isdigit())]
            if ''.join(w['word'] for w in visual)!=''.join(lines):visual=[]
            position=0
            for text,weight in zip(lines,weights):
                until=at+length*weight/total;result.append({'start':at,'end':until,'text':text,'parts':visual[position:position+weight]});at=until;position+=weight
        result[first:]=display_timing(result[first:],offset,end)
        offset=end
    return [c for c in result if c['end']>c['start'] and c['text'].strip()]
FONTS={'standard':('Noto Sans SC',True,'&H00FFFFFF'),'clean':('Noto Sans SC',False,'&H00FFFFFF'),'authority':('Noto Sans SC',True,'&H0000D7FF'),'interview':('Noto Sans SC',True,'&H00FFFFFF'),'muscle':('Noto Sans SC',True,'&H00FFFFFF'),'china':('ZCOOL XiaoWei',False,'&H00F0F5FF')}
FONTS.update(qingke=('ZCOOL QingKe HuangYou',False,'&H00FFFFFF'),kuaile=('ZCOOL KuaiLe',False,'&H00FFFFFF'),zhimang=('Zhi Mang Xing',False,'&H00FFFFFF'))
FONTS['mint']=('Koubo Sans Light',False,'&H00FFFFFF')
FONTS.update({'douyin': ('DouyinSans', False, '&H00FFFFFF'), 'round': ('寒蝉全圆体', False, '&H00FFFFFF'), 'half-round': ('寒蝉半圆体', False, '&H00FFFFFF'), 'bright': ('LXGW Bright GB', False, '&H00FFFFFF'), 'bright-medium': ('LXGW Bright GB Medium', False, '&H00FFFFFF'), 'bright-light': ('LXGW Bright GB Light', False, '&H00FFFFFF'), 'longcang': ('Long Cang', False, '&H00FFFFFF'), 'maocao': ('Liu Jian Mao Cao', False, '&H00FFFFFF')})

def ass(rows,width,height,style='standard',presentation=None):
    from video_finish import presentation as check
    p=check(presentation)
    # libass normalizes font height using ascent/descent. This bundled font's
    # visible Chinese glyph is ~2/3 that height; match the CSS/Pillow em width.
    family,bold,color=FONTS.get(style,FONTS['standard']);em_size=min(width*p['captionSize'],height*(.045 if p.get('layoutProfile')=='desktop-landscape-v1' else .07));size=max(8,round(em_size*(1.448 if style=='mint' else 1.5 if family=='Noto Sans SC' else __import__('movie_typography').ass_scale(style))));margin=round(height*p['captionBottom'])
    if p.get('captionFont'):
        from movie_typography import FONTS as TYPES,ass_scale
        family,_,bold=TYPES[p['captionFont']];size=max(8,round(em_size*ass_scale(p['captionFont'])))
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{family},{size},{color},&H00FFFFFF,&H00181818,&H60000000,{-1 if bold else 0},0,0,0,100,100,0,0,{3 if style=='interview' else 1},{round(width*.0012,2) if style=='mint' else 2},{0 if style=='mint' else 1},2,{round(width*.06)},{round(width*.06)},{margin},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines=[]
    for row in rows:
        text=ass_literal(row['text'])
        if style=='muscle' and row.get('parts'):text=''.join((r'{\c&H006DD7FF&\b1}'+ass_literal(w['word'])+r'{\r}' if w.get('emphasis') else ass_literal(w['word'])) for w in row['parts'])
        if style=='mint' and row.get('parts') and ''.join(w['word'] for w in row['parts'])==row['text']:
            tags=rf'{{\fnDouyinSans\fs{em_size*1.1*__import__("movie_typography").ass_scale("douyin"):.1f}\b0\c&HAAFF86&\bord{width*.0018:.2f}}}'
            text=''.join(tags+ass_literal(w['word'])+r'{\r}' if w.get('emphasis') else ass_literal(w['word']) for w in row['parts'])
        lines.append(f"Dialogue: 0,{ass_stamp(row['start'])},{ass_stamp(row['end'])},Default,,0,0,0,,{text}")
    return header+'\n'.join(lines)+'\n'

def ass_stamp(t):
    cs=round(t*100);h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100)
    return f'{h}:{m:02}:{s:02}.{cs:02}'

def ass_literal(text):
    return text.replace('\\','＼').replace('{','｛').replace('}','｝').replace('\r','').replace('\n',r'\N')
