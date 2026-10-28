# 学员安装与使用

这是Windows优先的首版测试技能，不要求安装SAYFRAME桌面应用。WorkBuddy负责内容理解和自然语言交流；本会话有AudioTranscribe时优先原生转写，再由本机完成声音定位和FFmpeg编码。没有原生入口时自动衔接本地SenseVoice，Whisper为可选方式。不额外调用作者的任何API或服务器。

在WorkBuddy的“专家·技能·连接器 → 技能 → 添加技能 → 上传技能”选择 `SAYFRAME-WorkBuddy-0.4.0.zip`。新开会话启用“SAYFRAME框架剪辑”，告诉它视频的本地路径和工程要保存的文件夹。首次按技能说明准备依赖，模型下载需要联网与磁盘空间；之后已有模型的转写/剪辑可本地进行，WorkBuddy对话模型仍按账户自身规则计费。不能承诺账户套餐不限量或零积分。

学员不用自己先转文字。大视频先由技能提取压缩音轨，交给WorkBuddy的原生AudioTranscribe，再导入同一工程；本地声音定位用于避免只改字幕而没改声音。原生转写不能宣称音频全程离线或不限额度，具体以WorkBuddy当前账户和工具提示为准。即使原生可读稿略去语气词，实际删音仍要通过声音保护。

可用指令：“先分析这段访谈，给我三个不同方向”；“按观点破题剪一条，保留必要提问”；“把案例放到后面，音乐调到5%”；“恢复上一步”；“导出视频”。

本版内置蛋解十二方法的剪辑适配：六维目标客户卡、三圈选题卡、当头一棒、以理服人、亮出绝活、指条明路、开场八式、六维人设卡、四行简介、乾坤大挪移、六脉神剑、一题多讲。不要求先做十二张卡。先交流内容和目标，工具推荐框架及几个方向；你确认方向后，再分别选择是否加字幕、是否加画面标题（都可以关闭），然后生成。工作台在当前页面内确认，不弹新窗口。缺少证据或入口会说明，不补假经历、数字或台词。

需要看画面时说“打开工作台”：内置三栏界面可播放当前成片、拖动整句调序、恢复原话、改标题与音量、撤销重做和下载。同一工程共用同一个最终视频；修改还没生成时明确显示原片，不能把原片当成剪后预览。对话继续在WorkBuddy中进行。

首次需要Windows、Python3.11或3.12、联网和足够磁盘空间。依赖和模型可能需要数百MB至1GB以上，长视频CPU转写及编码需要等待。此测试版尚未在全新学员电脑完成首次下载验证。

封面流程：视频剪好后先确定封面文字，再自动生成青绿笔触、浅底大字、黑金重点三个版本，选用后写入视频首帧。包内有匿名风格示意图；真人画面始终来自学员自己的当前视频，图像生成仅用于装饰背景，避免换脸和错字。可以在WorkBuddy里使用原生ImageGen，按其实际提示消耗积分；也可使用本地三版排版，不冒称AI生图。工程封面和视频不会回传作者。详见[封面流程](cover-workflow.md)。

语音转写准确率受录音质量影响。此测试版尚不支持完整自动逐字删音、多原片拼接、桌面可视化画中画编辑、完整315首配乐库。字幕位置固定为安全区的单行短句，显示时间为估计，不用它证明切口精确。

每个工程保留原稿、历史、修改摘要、声学校准报告和每次输出；原视频只读。导出失败不会把可能切掉正常字的文件当成功成片。不需把原视频发给作者。

官方参考：
- WorkBuddy技能包格式：https://open.workbuddy.cn/docs/skill
- 技能上传安装：https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market
- 本地转写说明：https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/WorkBuddy-Zero-Cost-Skill-Top-10/Local-Whisper
- FFmpeg Windows发行：https://www.gyan.dev/ffmpeg/builds/
- SenseVoice模型：https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models
- Whisper模型：https://huggingface.co/Systran/faster-whisper-small

内置Noto Sans SC、Ma Shan Zheng字体的OFL许可在assets/fonts。识别与编码依赖按各自许可由setup下载。本技能包不含私人视频、工程、密钥或作者的WorkBuddy登录。
