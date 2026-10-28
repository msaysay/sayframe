# Attribution and third-party components

SAYFRAME's code is distributed under MIT. Third-party components keep their
own licenses; MIT does not relicense the models, fonts, FFmpeg, or media you use.

## Bundled fonts

- Noto Sans SC: SIL Open Font License 1.1. Full notice: `assets/fonts/OFL-NotoSansSC.txt`.
- Ma Shan Zheng: SIL Open Font License 1.1. Full notice: `assets/fonts/OFL-MaShanZheng.txt`.

## Runtime dependencies (downloaded separately)

The release does not bundle Python packages, executable media tools, or models.
Setup installs pinned packages and obtains media components from their publishers:

| Component | Upstream | License / notice |
| --- | --- | --- |
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | MIT |
| PyAV | https://github.com/PyAV-Org/PyAV | BSD-3-Clause; linked FFmpeg has separate terms |
| NumPy | https://github.com/numpy/numpy | BSD-3-Clause and bundled notices |
| ONNX Runtime | https://github.com/microsoft/onnxruntime | MIT |
| kaldi-native-fbank | https://github.com/csukuangfj/kaldi-native-fbank | Apache-2.0 |
| Pillow | https://github.com/python-pillow/Pillow | HPND and bundled notices |
| jieba | https://github.com/fxsjy/jieba | MIT |
| FFmpeg | https://ffmpeg.org/legal.html | LGPL/GPL depending on build; Windows essentials build downloaded from https://www.gyan.dev/ffmpeg/builds/ |
| SenseVoice | https://github.com/FunAudioLLM/SenseVoice | See model publisher's model card and license |
| ONNX SenseVoice model distribution | https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models | See upstream release and model license |

FFmpeg and models are downloaded at setup time, not relicensed or hosted here.
WorkBuddy, its models and native audio/image tools are separate services subject
to their provider's terms, limits and charges. This is a community skill, not an
official Tencent product, and it includes no WorkBuddy account credentials.

## Methodology and inspiration

The Danjie editing adaptations were developed for SAYFRAME from methodologies
co-developed by the project authors and Dandan. The catalog retains version and
source-hash provenance. Original course archives, original skill ZIPs and private
recordings are not distributed. Method examples are never facts about your video.

OpenFilm inspired the project-local editing and reversible-command approach.
SAYFRAME's portable editor is a Python/FFmpeg implementation. For any retained
OpenFilm-derived material, the upstream MIT notice is reproduced below:

MIT License

Copyright (c) 2026 OpenFilm contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
