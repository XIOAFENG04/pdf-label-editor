# PDF 标签编辑器

Windows 桌面端 PDF 标签编辑 / 批量替换工具（Python + Tkinter + PyMuPDF）。

## 功能

- 打开 PDF 后单击文字直接编辑（类似 Adobe 的点击即改），支持整块文字选中与移动
- 图片、文本框、矢量图形可拖动 / 缩放
- 打印（带预览、纸张预设、缩放适配）
- 素材库：剪贴板粘贴、拖放到页面、多选批量替换
- 批量工具：批量替换产品标签、多页条码批量替换、旧标签批量更新
- 设置：默认缩放（320%）、打开方式、深色/跟随系统主题
- 自动检查更新（GitHub Releases）

## 安装

下载 Releases 中的 `PDF标签编辑器-安装程序-x.y.z.exe`，双击安装，可选安装位置并自动创建桌面快捷方式。

也可以直接使用便携版 exe，无需安装。

## 系统要求

Windows 10 / 11 64 位。

## 开发

```
python outputs/PDF小工具/pdf_tool.py
```

依赖：PyMuPDF、Pillow、pywin32（详见 `outputs/PDF小工具/依赖`）。

## 版本与更新

版本号写在 `outputs/PDF小工具/updater.py` 的 `APP_VERSION`。发布新版本：

```powershell
work/publish_release.ps1 -Version 1.0.1 -Notes "本次更新内容"
```

脚本会打包安装程序、打 tag、创建 GitHub Release 并上传安装包；程序里的「检查更新」会读取该 Release。

## 激活说明

首次启动需要输入软件密钥。客户使用同一个密钥；如需获取密钥，请联系：730004921@qq.com。
