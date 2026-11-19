# 数据取证和脚本

## 运行

需要 Python 3.10+，没有第三方依赖。初次验证从本目录运行：

```sh
python -m unittest discover -s tests -v
python scripts/market_digest.py --fixture tests/fixtures/current.json --prior tests/fixtures/prior.json --out demo
```

抓取公开 API 时，才使用明确的实时开关：

```sh
python scripts/market_digest.py --live --max-pages 20 --out run-current
python scripts/market_digest.py --live --max-pages 100 --prior run-current/snapshot.json --out run-next
```

输出 `snapshot.json`（时间、过滤口径、抓取覆盖及去重观测）和 `ranked.json`（相对上次采样的变化、24h 成交量、流动性、数据缺口）。退出码 0 是游标耗尽，2 是带偏差风险的部分结果，其他非零错误先排查。先核对 `terminal_cursor_reached`；预算或错误提前结束都会输出可用的部分数据，不能视为完整。磁盘或格式错误应直接失败，不假装有数据。脚本不生成主观预测，不依赖账户、令牌或本机路径。所有样本事件和时间都是合成的。

## API 约定

- [Gamma 市场 keyset](https://docs.polymarket.com/api-reference/markets/list-markets-keyset-pagination)：每页最多 100，使用 `next_cursor → after_cursor`；游标不解码、不自造、不混用 offset，不跨过滤条件重用。脚本以 ID 排序，固定 `closed=false` 并本地只接受明确 active 且未关闭、未归档的市场；末端游标耗尽只说明此过滤查询遍历到尾。要比较规模，保持过滤和排序一致；遇到 schema 变化先标部分，不自动改口径。
- [CLOB 订单簿](https://docs.polymarket.com/api-reference/market-data/get-order-book) 与 [价格历史](https://docs.polymarket.com/api-reference/markets/get-prices-history)：重要条目另核对应 outcome token、买卖报价／价差与交易或历史时点，保留来源和采集时刻。不要用 Gamma 更新时点冒充 CLOB 成交时点，也不要以系统时钟代替源内数据时间。
- [速率限制](https://docs.polymarket.com/api-reference/rate-limits)：小批开始，适当降速。请求超时、临时服务异常等有限重试；禁止绕限制。脚本仅 GET，限制页数、响应字节数和请求时长，不跟随服务器跳转。

## 关键口径

- 按市场 ID 去重，事件归组不替代市场去重。重复 ID 保留后观测；相同 ID 若结果名或 token 不一致，不算变动。
- 二元只取明确的 Yes/No 对应位置，顺序可能颠倒。多结果按该结果名称逐项呈现，不能把排列首项映射为“是”；本脚本只排名可核的 Yes/No。
- 概率差按百分点：0.39→0.44 是 +5 个百分点。脚本只使用两份同口径采样，明确称“较上次采样”，且记录各市场自己的实际采集时点。只有时间跨度确实匹配，才表述为过去 24 小时变化；日成交量不是日价格变化。API 的 `oneDayPriceChange` 只有确认结果方向及单位后才可另用，不与采样差拼接。
- 排除无效数值、缺价、空盘且未验证数据、过期或已决盘口。来源分类及可接单状态只是旁证，和结算状态分别核对；流动性、成交量不是质量保证；大幅价差、近期无成交或事件临期应突出披露。
- 对每个事件同时检查合约条件、规则页面和首要事实来源；不同窗口、重叠结果、不相容结算条件不可加总。所有观察都有范围、更新时间、样本限制。

## 容易反读的个案

[官方界面价格说明](https://help.polymarket.com/en/articles/13364488-how-are-prices-calculated)：显示值通常是买卖价中点；价差超过 0.10 美元走最近成交。最近成交可能已经过时；这条界面规则不能用来假设 Gamma 字段采用相同口径。没有有效双边报价时，不补中点。对网页、API 和订单簿的差异分别记录时点和字段。

同事件多结果：只有核实各档互斥、穷尽且按同一规则结算（含同一截止时刻、定义、公开结算证据）且有合理同步价格时才能求和。合成例：约 40%/30% 两个不重叠的 IPO 区间、30% 不 IPO，则上市 70%；最大档本身无条件 40%，条件于上市约 57.14%，两者不是同一数。嵌套门槛（例如“大于甲”和“大于乙”）或不同期限一律不能直接相加。辅助函数 `event_split` 要求显式确认互斥穷尽和同一结算；若原始观测总和偏离 1 超过 0.02（实现中的保守容差，不是校准标准），只报原始异常，拒绝默默归一化。
