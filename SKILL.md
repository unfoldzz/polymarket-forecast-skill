---
name: polymarket-forecast
description: Collect and audit public Polymarket market observations, rank qualifying changes, and produce evidence-linked data reports and a separate platform-neutral event forecast. Use for event watchlists and monitoring digests, not for trading or portfolio execution.
---

# Polymarket 预测观察

使用公开只读数据。不需要账号、签名、密钥或交易权限。默认生成本地文件；不把一次报告请求当成发信、发布或定时授权。

1. **先定口径。** 明确观察窗口、主题、展示时区（未指定可用 UTC）、是否需要数据版、纯预测版或两者。没有历史时不要编造变化；只有少量样本时先出样本报告。
2. **采集并记账。** 阅读 [数据取证与验证](references/method.md) 后按其用法运行 `scripts/market_digest.py`。按原样传递游标、固定过滤条件、记采集首末时间与停因；不把分页遍历称为同一时刻快照。分开保存公开报价、事件事实和独立判断。
3. **筛选而非照抄。** 根据绝对百分点变化、流动性、最近成交和现实影响选题；用事件归组，同组只保留最能说明问题的主盘口，二级结果另列。按明确方向解释条件、截止时间和规则，不把首次出现、陈旧报价或薄盘波动称为实质变化。重要事件即使不在涨跌榜也可另列，但标明选择理由。
4. **验方向与因果。** 详情页原文优先于短标题。核验显著冲突时保留两种观察口径及时间，不以中间价代替最后成交。对可能解释异动的新闻找一手声明和时间；没有证据只说时间相邻，不写因果。跨市场不随意相加，市场隐含值也不是测量出来的客观概率。
5. **分别成稿。** 按 [报告契约](references/reports.md) 制作。数据版有覆盖、观察时点、数值口径、局限和直接来源；纯预测版只写事件与证据的文字摘要、情景判断、反证和验证时间，不写平台名、链接或任何货币金额。不要从数据稿复制原题或来源段落后简单遮掉几个字。
6. **交付前复核。** 核对事件、方向、时间、美元门槛改写后是否仍忠实；检查纯预测版没有平台名、链接、金额。PDF 仅按需导出，逐页检查中文、分页和链接。缺乏足够证据时保留分歧或缺项，不凑数量。
