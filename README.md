# SimpleCAD (Chinese + Shapr3D-style Push/Pull & Fillet/Chamfer Mod)
This is a modified version of SimpleCAD for FreeCAD.

## Modification content
1. Chinese UI localization 中文界面汉化
2. New Shapr3D-style Push/Pull: select face, auto pop extrusion arrow, easier direct modeling
3. New Shapr3D-style Fillet & Chamfer: select edge, auto pop 3D handle (pull out for fillet, push in for chamfer, support 30°/45°/60° and custom angles)
4. Keep all original functions compatible, no breaking changes

## Original project
Original repo: https://github.com/igsova/SimpleCAD
SimpleCAD is a direct modeling workbench for FreeCAD, inspired by SketchUp.

## How to install
1. Download this branch source code
2. Put the `simplecad` folder into your FreeCAD Mod directory
3. Restart FreeCAD, find SimpleCAD workbench

---

## 演示截图 (Screenshots)

### 1. 智能推拉 (Push / Pull)
![推拉演示截图](https://github.com/snakeqiuwei/SimpleCAD/raw/zh-and-shapr-pushpull/cffCy6zYdv.png)

### 2. 双向倒圆角 / 倒斜角 (Round & Chamfer)
![倒角演示截图](https://github.com/snakeqiuwei/SimpleCAD/raw/zh-and-shapr-pushpull/rJ1XlMQ8u5.png)

---

## 中文介绍
本分支为 SimpleCAD 修改增强版：
- ✅ **全部界面汉化**：菜单、面板与提示全面中文本地化
- ✅ **Shapr3D 风格推拉交互**：选中面自动弹出法线拉伸箭头，支持贯通吸附
- ✅ **Shapr3D 风格圆角/倒角一体化**：选中棱边自动弹出双向手柄，向外拉倒圆角、向内推倒斜角；倒斜角支持 30°、45°、60° 预设及自定义度数
- ✅ **丝滑交互**：点击空白处自动保存退出、点击其他线/面瞬切、Esc 键单次退出
- ✅ **完全保留原版全部功能**：无破坏性改动，完全兼容原版模型文件

## 💡 推荐再编辑工作流 (Workflow Tips)
- **刚倒完圆角想微调**：直接按一次键盘的 `Ctrl + Z`（撤销），模型立刻瞬回尖角状态，并且边线手柄依然就绪，随时可以重新拖动；
- **以后想彻底消除圆角**：直接使用 SimpleCAD 顶部【曲面】工具栏自带的 **消除圆角… (RemoveRounds)** 或 **删除并缝合面 (HealFaces)**，安全可靠，绝不误触。
