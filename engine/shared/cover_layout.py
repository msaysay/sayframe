"""Optional cover placement; legacy template geometry remains the default."""
import math,copy
def validate_cover_layout(v):
 if not isinstance(v,dict) or set(v)!={'position','marginPercent','bandPercent'} or v['position'] not in ('top','middle','bottom'):raise ValueError('封面排版无效')
 for key,lo,hi in [('marginPercent',0,35),('bandPercent',12,35)]:
  if type(v[key]) not in (int,float) or not math.isfinite(v[key]) or not lo<=v[key]<=hi:raise ValueError('封面排版数值无效')
 return copy.deepcopy(v)
def geometry(c,width,height):
 pix=lambda v:math.floor(v+.5)
 if 'layout' in c:
  v=validate_cover_layout(c['layout']);band=height*v['bandPercent']/100;margin=height*v['marginPercent']/100
  y=margin if v['position']=='top' else height-band-margin if v['position']=='bottom' else (height-band)/2
  return [0,pix(y),width,pix(y+band)]
 if c['template']=='classic':return [0,0,width,pix(height*.2)]
 if c['template']=='question':return [24,pix(height*.06),width-24,pix(height*.26)]
 return [0,pix(height*.70),width,pix(height*.91)]

"""Wrap cover copy at phrases and words before falling back to characters."""
import re
def title_lines(text,measure,width):
    if measure(text)<=width:return [text]
    phrases=re.findall(r'[^，,。！？!?；;]+[，,。！？!?；;]?',text)
    output=[]
    for phrase in phrases:
        try:
            import jieba
            jieba.setLogLevel(40);tokens=jieba.cut(phrase)
        except ImportError:tokens=list(phrase)
        line=''
        for token in tokens:
            if line and measure(line+token)>width:output.append(line);line=''
            for char in token:
                if line and measure(line+char)>width:output.append(line);line=''
                line+=char
        if line:output.append(line)
    return output
