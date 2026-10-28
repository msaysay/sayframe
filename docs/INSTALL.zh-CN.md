# 安装与更新

[English](INSTALL.md) · [简体中文](INSTALL.zh-CN.md)

在 WorkBuddy 中发送仓库地址，并让它安装 SAYFRAME 技能。宿主需先读 `SKILL.md`，
校验 `manifest.json` 后只安装其中列出的文件；安装后新开会话启用技能。
具体能否直接按地址导入取决于当前 WorkBuddy 版本，不能把自然语言安装请求当作每个版本都有网址输入框。

无法按地址安装时，到 Releases 下载对应版本 ZIP，在“添加技能 → 上传技能”导入。
源码仓库与 ZIP 使用同一技能入口。

## 本机源码安装

```powershell
git clone https://github.com/msaysay/sayframe.git
cd sayframe-workbuddy
python scripts/install.py
```

默认安装到 `~/.workbuddy/skills/sayframe-workbuddy`。安装器校验文件哈希，保留已有私密
runtime，备份能识别的旧技能代码，不复制 Git 历史、原片或任意额外文件。
更新前先完成当前剪辑任务；程序不会替你杀掉 WorkBuddy 进程。

## 第一次使用

先让工具交流内容、推荐框架和方向，需要 Python 3.11/3.12。
宿主先执行 doctor，缺组件时说明联网下载与空间要求，再准备 setup。
依赖、FFmpeg、模型的来源与许可见 `references/student-guide.md`、`THIRD_PARTY_NOTICES.md`。

当前会话有 AudioTranscribe 时优先使用；缺少时有本地回退。
云端模型和转写按宿主账户规则计费、处理数据，不承诺全部离线或零积分。

导入视频只建立原稿。确认方向后，再分别选择字幕和标题是否添加，两项都可以关闭。
程序会阻止新工程在没有确认与选择时直接出片。

## 恢复

原视频保持可读取；后续在同一工程修改，不手改 JSON、声源时间或哈希。
撤销重做有可信旧成片时直接恢复；失败记录和原片保留。
原片移动后应重新导入新工程，不改源指纹冒充同一素材。

新电脑首次准备、网址安装、市场导入仍需在目标版本实测，既有本机测试不能替代这些分发验证。
