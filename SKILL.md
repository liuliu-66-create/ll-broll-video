---
name: ll-broll-video
description: 把口播文案做成黑白蜡笔女孩逐帧 B-roll。先拆镜并等用户选择 3:4、4:3 或 16:9，再用 Codex 内置生图生成静态帧表，本地导出 GIF 和无声 MP4，逐帧检查人物与动作连续性。
---

# 黑白蜡笔女孩 B-roll

1. 读取口播原话和已有时间码。按意思拆镜，每镜一个动作或概念，一句话也可以独立成镜。给用户看镜号、对应原话、画面动作和预计时长。有时间码就沿用，没有时先给估计时长。
2. 拆镜之后单独询问：「这次用哪个画幅？3:4 竖版、4:3 横版，还是 16:9 横版？」等用户在此步骤明确选定画幅后再开始生图或渲染。没有默认值。原片、附件、历史对话、拆镜前提到的尺寸以及界面预选项均不能替代这次答复。答复含糊时只澄清画幅。
3. 用 Codex 内置生图工具，把 [黑白蜡笔女孩参考图](assets/crayon-girl.png)、已确认的画幅和四段动作一起传入，每镜生成一张 4×4 静态 PNG。依照 [帧表提示词和验收清单](references/sprite-sheet.md) 查看全部画格。可直接使用生图工具返回的本地文件路径。
4. 帧表初检通过后运行本地脚本。每镜单独存到当前项目。脚本按行切出 16 帧，从同一组帧分别导出循环 GIF 和无声 MP4，并检查文件尺寸、帧数和时间。
5. 用同一份验收清单复看成品的每一帧与播放节奏，重点查多手、变脸、裁切和动作突然跳变。画面有问题时定位镜号和帧段，针对问题重做该镜并重验。只交付通过验收的镜头。需要连看时，将通过验收且画幅相同的镜头按顺序拼接，检查镜头交界和总时长。

脚本使用 Python 3、Pillow、FFmpeg（含 libx264）和 FFprobe。

```text
python scripts/render_broll.py render --sheet <frame-sheet.png> --ratio <confirmed-ratio> --duration-ms <milliseconds> --output-dir <new-scene-folder>
python scripts/render_broll.py join --ratio <confirmed-ratio> --output <new-combined.mp4> <scene-01/clip.mp4> <scene-02/clip.mp4>
```

每镜输出 `sheet.png`、`frames/01.png` 至 `16.png`、`preview.gif` 和 `clip.mp4`。已有明确口播时长则按该时长，时间单位是毫秒。
