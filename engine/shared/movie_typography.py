"""Measured, bounded text layouts shared by cover and baked movie titles."""
from pathlib import Path
from PIL import ImageFont
import re
BRUSH_LATIN_FALLBACK={'ma','zhimang','longcang','maocao'}
FONT_SCALES={}

def title_runs(text,font):
    """Keep Chinese brush strokes, set Latin words in a legible companion.

    Explicit glyph coverage is insufficient: Ma Shan Zheng's AI resembles 川
    in the real 02 export. This is typography only; text is never rewritten.
    """
    if font not in BRUSH_LATIN_FALLBACK or '\\' in text:return [(text,font)] if text else []
    parts=[];at=0
    for match in re.finditer(r'[A-Za-z][A-Za-z0-9.+_-]*',text):
        if match.start()>at:parts.append((text[at:match.start()],font))
        parts.append((match.group(),'noto'));at=match.end()
    if at<len(text):parts.append((text[at:],font))
    return parts

def title_width(text,font,size):
    return title_measure(font,size)(text)

def title_measure(font,size):
    fonts={font:load(font,size)}
    if font in BRUSH_LATIN_FALLBACK:fonts['noto']=load('noto',size)
    return lambda text:sum(fonts[k].getlength(t) for t,k in title_runs(text,font))

def ass_title(text,font,size):
    from short_captions import ass_literal
    return ''.join(r'{\fn'+FONTS[k][0]+r'\fs'+f'{size*ass_scale(k):.1f}'+r'\b'+('1' if k=='noto' else '0')+'}'+ass_literal(t) for t,k in title_runs(text,font))
FONTS={
 'noto':('Noto Sans SC','NotoSansSC.ttf',True),
 'ma':('Ma Shan Zheng','MaShanZheng-Regular.ttf',False),
 'qingke':('ZCOOL QingKe HuangYou','ZCOOLQingKeHuangYou-Regular.ttf',False),
 'kuaile':('ZCOOL KuaiLe','ZCOOLKuaiLe-Regular.ttf',False),
 'zhimang':('Zhi Mang Xing','ZhiMangXing-Regular.ttf',False),
 'xiaowei':('ZCOOL XiaoWei','ZCOOLXiaoWei.ttf',False),
 'smiley':('Smiley Sans','SmileySans-Oblique.ttf',False),
 'zhenkai':('LXGW ZhenKai GB','LXGWZhenKai.ttf',False),
 'marker':('LXGW Marker Gothic','LXGWMarkerGothic.ttf',False),
 'wenkai':('LXGW WenKai GB','LXGWWenKaiGB-Regular.ttf',False),
 'wenkai-light':('LXGW WenKai GB Light','LXGWWenKaiGB-Light.ttf',False),
 'wenkai-medium':('LXGW WenKai GB Medium','LXGWWenKaiGB-Medium.ttf',False),
 'serif':('Koubo Serif Regular','KouboSerif-Regular.ttf',False),
 'serif-black':('Koubo Serif ExtraBold','KouboSerif-ExtraBold.ttf',False),
 'douyin':('DouyinSans', 'DouyinSansBold.ttf', False),
 'round':('寒蝉全圆体', 'ChillRoundF.ttf', False),
 'half-round':('寒蝉半圆体', 'ChillRoundM.ttf', False),
 'bright':('LXGW Bright GB', 'LXGWBrightGB-Regular.ttf', False),
 'bright-medium':('LXGW Bright GB Medium', 'LXGWBrightGB-Medium.ttf', False),
 'bright-light':('LXGW Bright GB Light', 'LXGWBrightGB-Light.ttf', False),
 'longcang':('Long Cang', 'LongCang-Regular.ttf', False),
 'maocao':('Liu Jian Mao Cao', 'LiuJianMaoCao-Regular.ttf', False),
}
def font_id(p):return ('ma' if p['style']=='reference' else 'noto') if p.get('titleFont','auto')=='auto' else p['titleFont']

def ass_scale(font):
    # libass scales OS/2 Windows ascent + descent to Fontsize. This differs
    # from hhea in several Chinese display fonts; match Pillow/CSS em widths.
    return FONT_SCALES.get(font,{'douyin':1.202,'round':1.2695,'half-round':1.448,'bright':1.343,'bright-medium':1.343,'bright-light':1.343,'longcang':1.318,'maocao':1.615,'noto':1.448,'ma':1.373,'qingke':1.071,'kuaile':1.065,'zhimang':1.383,'xiaowei':1.21,'smiley':1.2,'zhenkai':1.317,'marker':1.317,'wenkai':1.317,'wenkai-light':1.317,'wenkai-medium':1.317,'serif':1.437,'serif-black':1.437}.get(font,1.0))
def load(font,size):
    result=ImageFont.truetype(str(Path(__file__).parent/'fonts'/FONTS[font][1]),round(size))
    if font=='noto':result.set_variation_by_axes([800])
    return result
def layout(text,width,scale=1,font='ma',max_lines=2,readable_latin=False,*,prefer_large=False,font_fraction=.13,safe_fraction=.78,min_fraction=.075):
    text=str(text).strip();size=width*font_fraction*scale
    # Prefer one large line when it fits above the readable floor. Only then
    # use two lines; a short subtitle should not become two oversized blocks.
    if '\n' not in text and not prefer_large:
        for pixels in range(round(size),round(width*min_fraction*scale)-1,-1):
            f=load(font,pixels)
            measure=title_measure(font,pixels) if readable_latin else f.getlength
            if measure(text)<=width*safe_fraction:return {'lines':[text] if text else [],'size':pixels,'font':font,'widths':[measure(text)] if text else [],'overflow':False}
    # Keep a readable minimum. Wrap at measured glyph widths instead of dividing
    # font size by all characters in a sentence; never silently clip the ending.
    for pixels in range(round(size),round(width*min_fraction*scale)-1,-1):
        f=load(font,pixels);lines=[];line=''
        measure=title_measure(font,pixels) if readable_latin else f.getlength
        for char in text:
            if char=='\n':lines.append(line);line='';continue
            if line and measure(line+char)>width*safe_fraction:lines.append(line);line=''
            line+=char
        if line:lines.append(line)
        if len(lines)<=max_lines:return {'lines':lines,'size':pixels,'font':font,'widths':[measure(s) for s in lines],'overflow':False}
    return {'lines':lines,'size':pixels,'font':font,'widths':[measure(s) for s in lines],'overflow':True}
