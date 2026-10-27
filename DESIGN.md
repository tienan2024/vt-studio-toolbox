---
name: VT STUDIO 图像工具箱
description: 面向现场视觉工程师的 Windows 原生图像处理工作台
colors:
  primary: "#b5531c"
  primary-hover: "#984215"
  workspace: "#f5f6f8"
  surface: "#ffffff"
  text: "#263548"
  text-subtle: "#58687b"
  border: "#c8d1dd"
  navigation: "#172332"
  navigation-hover: "#25374c"
  navigation-selected: "#354257"
  canvas: "#202b30"
  selection: "#39dbc4"
  source-outline: "#72b8ed"
  target-outline: "#f2ac68"
  message: "#e8eef4"
  message-text: "#30465e"
  warning: "#fff0e7"
  warning-text: "#8e3e19"
typography:
  headline:
    fontFamily: "Microsoft YaHei UI"
    fontSize: "23px"
    fontWeight: 650
  title:
    fontFamily: "Microsoft YaHei UI"
    fontSize: "21px"
    fontWeight: 600
  body:
    fontFamily: "Microsoft YaHei UI"
    fontSize: "13px"
  label:
    fontFamily: "Microsoft YaHei UI"
    fontSize: "12px"
rounded:
  indicator: "3px"
  field: "5px"
  control: "6px"
  panel: "8px"
spacing:
  compact: "5px"
  small: "8px"
  regular: "10px"
  group: "12px"
  section: "16px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.surface}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.field}"
    padding: "5px"
  navigation-selected:
    backgroundColor: "{colors.navigation-selected}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "12px"
  canvas:
    backgroundColor: "{colors.canvas}"
---

# Design System: VT STUDIO 图像工具箱

## Overview

当前设计以“现场图像工作台”为描述：深蓝导航组织工具，浅色工作区承载参数，深色画布显示图像。它是 Windows PySide6 原生桌面界面；本文件记录已经实现的视觉约定，样式以 `theme.py` 为准，画布以 `app.py` 为准。最后更新：2026-10-27。

**Key Characteristics:**

- 一个窗口切换“尺寸与原点”和“缺陷合成”，保留工作区状态。
- 烧橙色突出执行操作；画布上的几何辅助线有独立语义。
- 使用系统中文字体、原生文件选择器和标准表单控件。

## Colors

### Primary

烧橙色用于主按钮、焦点边框、进度和选中的复选框；悬停使用更深的同色。它不代替图像内容的灰度值。

### Neutral

深蓝导航与浅色工作区形成固定结构，白色表单和深色画布区分参数与图像。次要说明使用柔和灰蓝色；普通消息用浅蓝底，错误消息使用暖色底和深色文字。

### Image annotations

缺陷页蓝色选区标识提取素材，绿色实框标识独立的允许生成范围，蓝色虚框参考原 NG 缺陷位置；范围不会改写素材。转换页蓝框标识原图边界，浅橙框标识输出范围。范围含义同时出现在文字提示中，不能只靠颜色传达。

允许范围支持多个框，侧栏逐项编号且可删除/撤销；预览以实线强调本次选用框，其他允许框用虚线参考。不得用所有框的外接大框代替独立区域。

## Typography

应用默认使用 Microsoft YaHei UI（10 pt），共享 QSS 将普通控件设为 body 大小；页面标题、工具标题、辅助标签使用 frontmatter 中的层级。导航品牌为 20 px、650 字重，页脚为 11 px。空画布提示由 QGraphicsScene 使用同一字体的 11 pt 绘制。

字体尺寸和 Qt 的点大小属于不同设置层级；新增页面沿用现有样式，不将所有数值机械替换为同一个单位。

## Layout

工具箱最小窗口为 1180 × 720；初始目标为 1440 × 900，受当前屏幕可用区域约束。左侧固定 176 px 导航，右侧是共享页头和 QStackedWidget 工作区。内容外边距为左右 18 px、底部 12 px；页头下方间距为 10 px。

转换页采用可拖动分栏：左侧素材列表、中间画布、右侧可滚动参数。素材栏宽度范围 180–275 px，参数栏 250–305 px；中间画布优先伸展。底部批量输出和消息单独排布。缺陷页使用可滚动左参数栏、右侧三个画布页签及底部操作区；嵌入画布最小高度为 160 px，画布与页签提示分开分配空间。

缩小窗口依赖 Qt 布局、分栏和参数滚动，不采用网页断点或移动端重排。已执行的工具箱截图尺寸为 1440 × 900 和 1180 × 760；1180 × 720 是代码约束，不能混称为已截图验证的尺寸。

图像按比例适应窗口，也支持滚轮缩放和拖动平移。显示缩放不修改输出尺寸或选区保存坐标。

## Elevation & Depth

共享样式不使用阴影。导航、工作区、白色控件和深色画布通过色调分层；组标题使用细分隔线，面板使用细边框。保留原生窗口与对话框的系统行为。

## Shapes

表单、按钮和容器使用小圆角，具体数值见 frontmatter。普通按钮为细边框，焦点边框增至 2 px；选区描边为 2 px，缺陷选区使用 cosmetic pen，缩放时保持线条可辨识。不要给图像像素增加装饰性圆角遮挡。

## Components

### Buttons and forms

主按钮用于“开始转换”等执行操作；次按钮用于文件选择、预览和查看结果。按钮有悬停、按下、焦点和禁用状态。输入框、下拉框及数值框共享边框和焦点色。数值控件隐藏上下步进按钮，保留输入和键盘调节能力。

复选框显式绘制 15 × 15 px 指示框，选中后使用烧橙底和 `assets/check.svg` 白色勾选图；不能依赖被 QSS 覆盖后的原生勾选外观。

### Navigation

侧栏文字配合自绘 20 × 20 px 线性图标；图标由 QPainter 绘制，不依赖在线图标字体。当前页使用更亮的深蓝选中底和加粗白字，悬停与焦点单独标识。切换页面保留已选素材和参数。

### Canvas and tabs

转换页区分“裁切 / 填充范围”和“输出预览”；缺陷页区分 OK 底图、NG 圈选与合成预览。工具条包含适应窗口和必要圈选操作，说明放在画布外。选入空目录、损坏或无法读取的新素材时，清空旧画布并显示当前状态。

NG列表沿用OK的多文件选择、当前项预览和多项移除，文字状态区分“待圈选/已圈选”，不只依赖颜色。每项保留素材和范围；左侧标记当前NG范围，合成预览提示实际选用NG来源。共用画布以右键按住拖动平移，右键单击收尾多边形，保留Enter操作。

数量方式、数值输入及预计合计固定放在右侧批量导出区，避免藏在长参数栏中。下拉明确区分“每张 OK 生成”和“本批生成总数”，只显示当前方式的输入框；处理时禁用，调整数量不使单张预览失效。

背景参考行左右等宽，左侧手动数值、右侧“自动”勾选；自动时输入为浅灰禁用态。OK/NG列表最小80、最大180逻辑像素，随行数增长后滚动。空画布为浅色视口中的320×180白色小卡片，加载图像后恢复深色画布。

标注工具使用平铺按钮，选中状态为浅橙背景、深橙文字与下方细标记；标记在切换时以150ms OutCubic移动，布局变化不应中断动画。紧凑工具条保持在一行，避免压缩小窗口画布。移除“本地离线”“本地处理·无需GPU”徽标及页脚文案，只保留版本。

### Feedback

消息条、进度条和可展开的处理记录承担不同任务。处理期间禁用冲突操作；错误保留可操作的说明。使用完成数量和简短状态文本，避免长消息挤占小窗口的画布。

## Do's and Don'ts

### Do:

- **Do** 复用共享 QSS 和 Canvas，在同一个窗口扩展工具。
- **Do** 使用文字解释原图边界、目标范围和缺陷选区。
- **Do** 保持图像显示缩放与实际像素输出分离。
- **Do** 在人工测试图与截图上明确标注测试用途。

### Don't:

- **Don't** 把旧版青绿色主操作规则继续用于工具箱按钮。
- **Don't** 用全屏装饰、阴影层叠或动画挤占图像与参数空间。
- **Don't** 在读取新素材失败后继续显示上一张素材的预览。
- **Don't** 将人工截图、源码测试或旧版便携包结果表述为当前现场检测效果或新版交付验收。
