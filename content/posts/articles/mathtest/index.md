---
title: 测试Markdown 中写数学公式（KaTeX）
date: 2026-10-28
tags: [test]
summary: 用 $...$ 写行内公式，$$...$$ 写块级公式。构建脚本自动引入 KaTeX，无需额外步骤。
slug: math-demo
---

> 本站的数学公式由 **KaTeX** 自动渲染。在 Markdown 里写 LaTeX 语法即可，构建时不用额外处理。

## 行内公式：`$...$`

单个 `$` 包裹，嵌入正文里。

勾股定理：$a^2 + b^2 = c^2$

质能方程：$E = mc^2$

二次方程求根公式：$x = \dfrac{-b \pm \sqrt{b^2 - 4ac}}{2a}$，其中 $\Delta = b^2 - 4ac$。

## 块级公式：`$$...$$`

双 `$$` 独占一行，居中显示，字号更大。

**高斯积分**：

$$
\int_{-\infty}^{+\infty} e^{-x^2}\,dx = \sqrt{\pi}
$$

**欧拉恒等式**——被誉为"最美的数学公式"：

$$
e^{i\pi} + 1 = 0
$$

**泰勒展开**：

$$
f(x) = f(a) + \frac{f'(a)}{1!}(x - a) + \frac{f''(a)}{2!}(x - a)^2 + \cdots
$$

## 常用 LaTeX 语法速查

| 效果 | 写法 | 示例 |
|------|------|------|
| 上下标 | `x^2`, `x_1` | $x^2$, $x_1$ |
| 组合上下标 | `x_{ij}`, `e^{i\pi}` | $x_{ij}$, $e^{i\pi}$ |
| 分数 | `\frac{a}{b}`, `\dfrac{a}{b}` | $\frac{a}{b}$, $\dfrac{a}{b}$ |
| 根号 | `\sqrt{x}`, `\sqrt[n]{x}` | $\sqrt{x}$, $\sqrt[n]{x}$ |
| 求和 | `\sum_{i=1}^{n} i` | $\sum_{i=1}^{n} i$ |
| 积分 | `\int_{a}^{b} f(x)\,dx` | $\int_{a}^{b} f(x)\,dx$ |
| 乘积 | `\prod_{i=1}^{n} i` | $\prod_{i=1}^{n} i$ |
| 极限 | `\lim_{x \to \infty}` | $\lim_{x \to \infty}$ |
| 希腊字母 | `\alpha`, `\beta`, `\pi`, `\infty` | $\alpha, \beta, \pi, \infty$ |
| 运算符 | `\pm`, `\times`, `\div`, `\leq`, `\geq` | $\pm, \times, \div, \leq, \geq$ |
| 箭头 | `\to`, `\Rightarrow`, `\leftarrow` | $\to, \Rightarrow, \leftarrow$ |
| 向量/帽子 | `\vec{v}`, `\hat{x}`, `\bar{x}` | $\vec{v}, \hat{x}, \bar{x}$ |
| 省略号 | `\cdots`, `\ldots`, `\vdots` | $\cdots, \ldots, \vdots$ |

## 矩阵

```
$$
\begin{pmatrix} a & b \\ c & d \end{pmatrix}
\begin{pmatrix} e \\ f \end{pmatrix}
=
\begin{pmatrix} ae + bf \\ ce + df \end{pmatrix}
$$
```

渲染为：

$$
\begin{pmatrix} a & b \\ c & d \end{pmatrix}
\begin{pmatrix} e \\ f \end{pmatrix}
=
\begin{pmatrix} ae + bf \\ ce + df \end{pmatrix}
$$

## 分段函数

```
$$
f(x) = \begin{cases}
  x^2 & x \geq 0 \\
  -x & x < 0
\end{cases}
$$
```

渲染为：

$$
f(x) = \begin{cases}
  x^2 & x \geq 0 \\
  -x & x < 0
\end{cases}
$$

## 对齐的多行公式

用 `aligned` 环境让等号对齐：

```
$$
\begin{aligned}
  (a + b)^2 &= a^2 + 2ab + b^2 \\
  (a - b)^2 &= a^2 - 2ab + b^2
\end{aligned}
$$
```

渲染为：

$$
\begin{aligned}
  (a + b)^2 &= a^2 + 2ab + b^2 \\
  (a - b)^2 &= a^2 - 2ab + b^2
\end{aligned}
$$

## 注意事项

1. **转义美元符号**：如果文章里要写货币 `$`，用 `\$` 转义。例如 `价格是 \$99` 渲染为 价格是 $99。
2. **块级公式独占一行**：`$$` 前后要空行，不要跟在文字后面。
3. **LaTeX 写错了怎么办**：不会报错崩溃，KaTeX 会把错误的源码原样显示，方便你排查。
4. **不支持 AMSTeX 环境**：KaTeX 不支持 `\begin{equation}`、`\begin{align}` 等，可以用 `aligned` 或直接用 `$$` 包裹多行。
