"""Editable text effects; no generated letters or facial changes."""
from movie_typography import layout,font_id,FONTS,ass_scale,ass_title
from short_captions import ass_literal,ass_stamp
EFFECTS=('outline','soft','teal','reference-card')
VERSION=3
def overlays(title,accent,p,width,height,start,end):
    if p['titleEffect']=='reference-card':return reference_card(title,accent,p,width,height,start,end)
    title_font=font_id(p);title_scale=ass_scale(title_font)
    # Pillow measures glyphs before libass applies the font's OS/2 scale.
    # Reserve that expansion before choosing a line break.
    landscape=p.get('layoutProfile')=='desktop-landscape-v1'
    desktop=p.get('layoutProfile') in ('desktop-v1','desktop-landscape-v1')
    block=layout(title,width,p['titleScale'],title_font,readable_latin=True,prefer_large=True,font_fraction=.035 if landscape else .10,safe_fraction=.76,min_fraction=.025 if landscape else .075) if desktop else layout(title,width/title_scale,p['titleScale'],title_font,readable_latin=True)
    if block['overflow']:raise ValueError('标题太长，请缩短至两行以内')
    out=[];size=block['size'];family=FONTS[block['font']][0];scaled=size*ass_scale(block['font']);y=height*(.025 if landscape else .12 if desktop else .08)
    def emit(layer,tags,text):out.append(f'Dialogue: {layer},{ass_stamp(start)},{ass_stamp(end)},Default,,0,0,0,,{{{tags}}}{text}')
    if desktop and p['titleEffect']=='teal' and block['lines']:
        x=width*.12;w=width*.76;h=size*1.15*len(block['lines'])+width*.02
        emit(1,rf'\an7\pos({x:.1f},{y:.1f})\bord0\shad0\c&H818B07&\1a&H77&\p1',f'm 0 0 l {w:.1f} 0 l {w:.1f} {h:.1f} l 0 {h:.1f}')
    for i,line in enumerate(block['lines']):
        top=y+i*size*1.15;center=width*.5;span=block['widths'][i]
        if p['titleEffect']=='teal' and not desktop:
            visible_span=span*title_scale
            x=center-visible_span/2-size*.1;bar_y=top+size*.6;w=visible_span+size*.2;h=size*.54;r=size*.07
            # Rounded underlay lies behind the lower half of the title.
            path=f'm {r:.1f} 0 l {w-r:.1f} 0 b {w:.1f} 0 {w:.1f} 0 {w:.1f} {r:.1f} l {w:.1f} {h-r:.1f} b {w:.1f} {h:.1f} {w:.1f} {h:.1f} {w-r:.1f} {h:.1f} l {r:.1f} {h:.1f} b 0 {h:.1f} 0 {h:.1f} 0 {h-r:.1f} l 0 {r:.1f} b 0 0 0 0 {r:.1f} 0'
            emit(1,rf'\an7\pos({x:.1f},{bar_y:.1f})\bord0\shad0\c&H98A94A&\1a&H18&\p1',path)
        for shadow in (True,False):
            dx=size*.035 if shadow else 0;dy=size*.055 if shadow else 0
            tags=rf'\an8\pos({center+dx:.1f},{top+dy:.1f})\fn{family}\fs{scaled:.1f}\b0\shad0\bord{size*(.015 if shadow else .008):.1f}\blur{size*.055 if shadow else 0:.1f}\c&H'+(r'000000&\1a&H85&\3c&H000000&\3a&H85&' if shadow else r'FFFFFF&\3c&HFFFFFF&')
            emit(2 if shadow else 3,tags,ass_title(line,block['font'],size))
    if accent:
        small=layout(accent,width/ass_scale('noto'),.43*p['titleScale'],'noto');top=y+len(block['lines'])*size*1.15+height*.003
        if small['overflow']:raise ValueError('副标题太长，请缩短')
        for i,line in enumerate(small['lines']):
            emit(3,rf'\an8\pos({width*.5:.1f},{top+i*small["size"]*1.2:.1f})\fnKoubo Sans Light\fs{small["size"]*1.448:.1f}\b0\bord0\shad1\blur0\c&HFFFFFF&',ass_literal(line))
    return '\n'.join(out)+'\n'

def reference_card(title,accent,p,width,height,start,end):
    blocks=[(layout(text,width/ass_scale(font_id(p)),.8*p['titleScale'],font_id(p),readable_latin=True),color) for text,color in [(title,'FFFFFF'),(accent,'66EFFF')] if text]
    if any(b['overflow'] for b,c in blocks):raise ValueError('标题太长，请缩短至两行以内')
    if not blocks:return ''
    out=[];y=height*.025;gap=width*.012;total=sum(len(b['lines'])*b['size']*ass_scale(b['font'])*1.15 for b,c in blocks)+gap*(len(blocks)-1)
    def emit(layer,tags,text):out.append(f'Dialogue: {layer},{ass_stamp(start)},{ass_stamp(end)},Default,,0,0,0,,{{{tags}}}{text}')
    # The text stays inside 78% of the picture; the panel supplies quiet contrast.
    w=width*.84;h=total+width*.032
    emit(1,rf'\an7\pos({width*.08:.1f},{y-width*.012:.1f})\bord0\shad0\c&H343634&\1a&H75&\p1',f'm 0 0 l {w:.1f} 0 l {w:.1f} {h:.1f} l 0 {h:.1f}')
    for block,color in blocks:
        for line in block['lines']:
            tags=rf'\an8\pos({width*.5:.1f},{y:.1f})\fn{FONTS[block["font"]][0]}\fs{block["size"]*ass_scale(block["font"]):.1f}\b0\bord{width*.004:.1f}\shad{width*.0015:.1f}\c&H{color}&\3c&H101410&\4c&H101410&'
            emit(3,tags,ass_title(line,block['font'],block['size']));y+=block['size']*ass_scale(block['font'])*1.15
        y+=gap
    return '\n'.join(out)+'\n'
