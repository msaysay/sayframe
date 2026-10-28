"""Independent voice and music gain, applied once to the final mix."""
import math
import re
from source_subtitles import validate_source_subtitle_status
DEFAULT_MUSIC_VOLUME=0.1

def validate_voice_gain(value=1):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=4:
        raise ValueError('人声音量须为0到400%')
    return float(value)

def validate_peak_protection(value=False):
    if type(value) is not bool:raise ValueError('输出峰值保护须为开或关')
    return value

def peak_filter(enabled=False):
    # No auto make-up gain. Compensate lookahead and retain encoding headroom.
    return 'alimiter=limit=0.707946:attack=5:release=50:level=false:latency=true' if validate_peak_protection(enabled) else None

TIMESTAMP_ALIGNMENT='aresample=async=1:min_hard_comp=0.001:first_pts=0'

def music_envelope(duration):
    """Fade only the background bed, using the encoded output timeline."""
    if duration is None:return None
    if type(duration) not in (int,float) or not math.isfinite(duration) or duration<=0:
        raise ValueError('配乐时长无效')
    return {'duration':float(duration),'fadeIn':min(.35,duration/4),'fadeOut':min(1.0,duration/4)}

def output_audio_filter(settings,align_timestamps=False,duration=None,redactions=None):
    import voice_denoise
    voice=([TIMESTAMP_ALIGNMENT] if align_timestamps else [])
    denoise=voice_denoise.audio_filter(settings.get('noiseReduction','off'),duration)
    if denoise:voice.append(denoise)
    gain=validate_voice_gain(settings.get('voiceGain',1))
    if gain!=1:voice.append(f'volume={gain:.6f}')
    from content_safety import audio_filter
    censor=audio_filter(redactions)
    if censor:voice.append(censor)
    protection=peak_filter(settings.get('peakProtection',False))
    if settings['musicId']:
        graph=music_filter(settings['musicVolume'],settings['musicDucking'],duration)
        if voice:graph='[0:a]'+','.join(voice)+'[alignedvoice];'+graph.replace('[0:a]','[alignedvoice]')
        if protection:graph=graph[:-3]+'[mixed];[mixed]'+protection+'[a]'
        return ['-filter_complex',graph,'-map','[a]']
    filters=voice+([protection] if protection else [])
    return ['-af',','.join(filters)] if filters else []

def audio_processing(settings,align_timestamps=False,duration=None):
    from voice_denoise import receipt
    enabled=validate_peak_protection(settings.get('peakProtection',False))
    return {'intermediateCodec':'pcm_f32le','sampleRate':48000,'channels':2,'voiceGain':validate_voice_gain(settings.get('voiceGain',1)),'peakProtection':enabled,'limiter':peak_filter(enabled),'sampleCeilingDbFS':-3 if enabled else None,'encodedPeakGuaranteed':False,'timestampAlignment':TIMESTAMP_ALIGNMENT if align_timestamps else None,'musicEnvelope':music_envelope(duration) if settings['musicId'] else None,'voiceDenoise':receipt(settings.get('noiseReduction','off'))}

def validate_music_ducking(value=False):
    if type(value) is not bool:raise ValueError('口播时降低配乐须为开或关')
    return value
def validate_music_volume(value=DEFAULT_MUSIC_VOLUME):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
        raise ValueError('音乐音量须为0到100%')
    return float(value)
def music_settings(payload,uploads):
    settings=payload.get('settings',{})
    if not isinstance(settings,dict):raise ValueError('工程设置无效')
    from voice_denoise import validate
    if 'noiseReduction' in settings:validate(settings['noiseReduction'])
    validate_source_subtitle_status(settings.get('sourceSubtitleStatus','unknown'))
    volume=validate_music_volume(settings.get('musicVolume',DEFAULT_MUSIC_VOLUME))
    ducking=validate_music_ducking(settings.get('musicDucking',False))
    protection=validate_peak_protection(settings.get('peakProtection',False))
    if 'voiceGain' in settings:settings={**settings,'voiceGain':validate_voice_gain(settings['voiceGain'])}
    music=payload.get('musicId')
    if music is not None and (not isinstance(music,str) or not re.fullmatch('[a-f0-9]{32}',music) or not (uploads/('music-'+music+'.mp3')).is_file()):
        raise ValueError('音乐素材不存在')
    return {**settings,'musicId':music,'musicVolume':volume,'musicDucking':ducking,'peakProtection':protection}
def music_filter(volume,ducking=False,duration=None):
    gain=validate_music_volume(volume)
    ducking=validate_music_ducking(ducking)
    envelope=music_envelope(duration)
    bed=f'volume={gain:.6f}'
    if envelope:
        bed+=f",atrim=duration={duration:.6f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d={envelope['fadeIn']:.6f},afade=t=out:st={duration-envelope['fadeOut']:.6f}:d={envelope['fadeOut']:.6f}"
    if ducking:
        return f'[0:a]asplit=2[voice][sc];[1:a]{bed}[bg];[bg][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=350:makeup=1:detection=rms[ducked];[voice][ducked]amix=inputs=2:duration=first:normalize=0[a]'
    return f'[1:a]{bed}[bg];[0:a][bg]amix=inputs=2:duration=first:normalize=0[a]'
