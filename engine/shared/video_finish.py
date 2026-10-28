"""Shared movie typography and tempo. Source word timestamps remain immutable."""
import math
SPEEDS=(.75,1,1.1,1.25,1.5,2)
DEFAULT={'enabled':True,'title':'','accent':'','name':'','intro':'','captionSize':.07,'captionBottom':.24,'style':'reference','titleFont':'ma','titleScale':1,'coverFont':'noto','coverTop':.60,'titleEffect':'teal','identityMode':'auto','identityCount':2,'identityDuration':7,'identityStarts':[],'insets':[]}
def speed(value=1):
    if type(value) not in (int,float) or value not in SPEEDS:raise ValueError('倍速须选0.75、1、1.1、1.25、1.5或2倍')
    return float(value)
def presentation(value=None):
    if value is None:return dict(DEFAULT)
    if not isinstance(value,dict) or set(value)-(set(DEFAULT)|{'identityRanges','captionFont','layoutProfile'}):raise ValueError('画面排版设置无效')
    out=DEFAULT|value
    if out.get('layoutProfile','reference') not in ('reference','desktop-v1','desktop-landscape-v1'):raise ValueError('排版配置无效')
    if type(out['enabled']) is not bool:raise ValueError('标题显示设置无效')
    if out['style'] not in ('classic','reference'):raise ValueError('画面字体方案无效')
    if out['titleEffect'] not in ('outline','soft','teal','reference-card'):raise ValueError('标题质感无效')
    from movie_typography import FONTS
    if out['titleFont'] not in ('auto',*FONTS):raise ValueError('标题字体无效')
    if out['coverFont'] not in FONTS:raise ValueError('封面字体无效')
    if 'captionFont' in out and out['captionFont'] not in FONTS:raise ValueError('字幕字体无效')
    if type(out['coverTop']) not in (int,float) or not .44<=out['coverTop']<=.68:raise ValueError('封面文字位置无效')
    if type(out['titleScale']) not in (int,float) or out['titleScale'] not in (1,1.15):raise ValueError('标题大小无效')
    for k,limit in [('title',28),('accent',28),('name',12),('intro',160)]:
        if not isinstance(out[k],str) or len(out[k])>limit:raise ValueError('画面文字过长')
    for k,lo,hi in [('captionSize',.05,.085),('captionBottom',.12,.32)]:
        if type(out[k]) not in (int,float) or not math.isfinite(out[k]) or not lo<=out[k]<=hi:raise ValueError('字幕大小或位置无效')
    import movie_insets
    out['insets']=movie_insets.validate(out['insets'])
    if out['identityMode'] not in ('auto','manual','off') or type(out['identityCount']) is not int or out['identityCount'] not in (1,2,3) or type(out['identityDuration']) is not int or out['identityDuration'] not in (5,7,10):raise ValueError('人物介绍出场安排无效')
    starts=out['identityStarts']
    if not isinstance(starts,list) or len(starts)>3 or any(type(t) not in (int,float) or not math.isfinite(t) or not 5<=t<=7200 or i>0 and t-starts[i-1]<out['identityDuration']+12 for i,t in enumerate(starts)):raise ValueError('人物介绍出场安排无效')
    out['identityStarts']=starts[:]
    if 'identityRanges' in out:out['identityRanges']=__import__('identity_edit').validate_ranges(out['identityRanges'])
    return out
def text_lines(text,limit=12):
    from short_captions import chunks
    return chunks(text,limit)[:2]

def intro_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()][:4]
def overlays(rows,width,height,duration,settings,cover_duration=0,identity_windows=None):
    """ASS dialogue coordinates also drive the unbaked editor preview."""
    from short_captions import ass_literal,ass_stamp
    p=presentation(settings.get('presentation'));out=[]
    def add(text,size,x,y,start,end,color='FFFFFF',align=7,family=None,literal=True):
        if not text or end<=start:return
        from movie_typography import FONTS,ass_scale
        ratio=next((ass_scale(k) for k,v in FONTS.items() if v[0]==family),1.5)
        tags=r'{\an'+str(align)+r'\pos('+f'{round(x)},{round(y)}'+r')\fs'+str(round(size*ratio))+(r'\fn'+family+r'\b'+('1' if family=='Noto Sans SC' else '0') if family else r'\b1')+r'\c&H'+color+r'&}'
        out.append(f'Dialogue: 1,{ass_stamp(start)},{ass_stamp(end)},Default,,0,0,0,,{tags}{ass_literal(text) if literal else text}')
    for window in identity_windows or []:
        x=width*(.08 if p['style']=='reference' else .10);y=height*(.51 if p['style']=='reference' else .52)
        add(p['name'],width*.072,x,y,window['start'],window['end'])
        for i,text in enumerate(intro_lines(p['intro'])):add(text,width*.037,x,y+width*(.10+i*.046),window['start'],window['end'])
    if p['enabled']:
        title=p['title'] or settings.get('coverTitle','');accent=p['accent'] or settings.get('coverSubtitle','')
        if p['titleEffect']!='outline' or p.get('layoutProfile')=='desktop-v1':
            import title_effects
            out.append(title_effects.overlays(title,p['accent'],p,width,height,cover_duration,duration))
            return '\n'.join(out)+'\n'
        if p['style']=='reference':
            from movie_typography import layout,font_id,FONTS,ass_title
            block=layout(title,width,p['titleScale'],font_id(p),readable_latin=True)
            if block['overflow']:raise ValueError('标题太长，请缩短至两行以内')
            for i,line in enumerate(block['lines']):add(ass_title(line,block['font'],block['size']),block['size'],width*.5,height*.08+i*block['size']*1.15,cover_duration,duration,align=8,family=FONTS[block['font']][0],literal=False)
            return '\n'.join(out)+'\n'
        y=height*.08
        add(title,min(width*.066,width*.80/max(1,len(title))),width*.10,y,cover_duration,duration)
        add(accent,min(width*.059,width*.80/max(1,len(accent))),width*.10,y+width*.083,cover_duration,duration,'8BF1FF')
    return '\n'.join(out)+'\n'

def cover(im,settings,font_path):
    from PIL import Image,ImageDraw,ImageFont
    p=presentation(settings.get('presentation'));im=im.convert('RGBA');layer=Image.new('RGBA',im.size);d=ImageDraw.Draw(layer);w,h=im.size
    for y in range(round(h*.27)):d.line([(0,y),(w,y)],fill=(8,12,17,round(125*(1-y/(h*.27)))))
    def draw(text,size,x,y,color='white',center=False):
        if not text:return
        font=ImageFont.truetype(str(font_path),max(8,round(size)));font.set_variation_by_axes([700])
        while d.textlength(text,font=font)>w*(.88 if center else .8) and font.size>8:
            font=ImageFont.truetype(str(font_path),font.size-1);font.set_variation_by_axes([700])
        if center:x=(w-d.textlength(text,font=font))/2
        d.text((x,y),text,font=font,fill=color,stroke_width=max(1,round(w*.004 if center else w*.002)),stroke_fill='#202020',anchor='lt')
    if p['style']=='reference':
        for y in range(round(h*.43),h):d.line([(0,y),(w,y)],fill=(0,0,0,round(220*(y-h*.43)/(h*.57))))
        from movie_typography import layout,load,font_id
        primary=settings.get('coverTitle') or p['title'];secondary=settings.get('coverSubtitle') or p['accent']
        # Reference: white proposition then a larger yellow emphasis, both local
        # fonts with dark outline and lower gradient; preserve the real subject.
        y=h*p['coverTop']
        for text,color,scale in [(primary,'white',1),(secondary,'#E8C860',1.15)]:
            block=layout(text,w,scale*p['titleScale'],p['coverFont'])
            if block['overflow']:raise ValueError('封面文字太长，请缩短至两行以内')
            f=load(block['font'],block['size'])
            for line in block['lines']:
                d.text(((w-f.getlength(line))/2,y),line,font=f,fill=color,stroke_width=max(1,round(w*.005)),stroke_fill='#101010',anchor='lt');y+=block['size']*1.2
            y+=h*.025
        if y>h*.88:raise ValueError('封面文字过多，请缩短标题')
        return Image.alpha_composite(im,layer).convert('RGB')
    draw(settings.get('coverTitle') or p['title'],w*.066,w*.1,h*.08)
    draw(settings.get('coverSubtitle') or p['accent'],w*.059,w*.1,h*.08+w*.083,'#FFF18B')
    draw(p['name'],w*.072,w*.1,h*.52)
    if p['name']:
        for i,line in enumerate(text_lines(p['intro'],18)):draw(line,w*.034,w*.1,h*.52+w*(.10+i*.045))
    return Image.alpha_composite(im,layer).convert('RGB')
