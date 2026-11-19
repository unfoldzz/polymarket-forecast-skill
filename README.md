# Polymarket 预测观察 Skill

从公开市场报价观察未来事件。先核规则和证据，再给情景判断；不下单、不发邮件、不采集凭据。

让支持 Agent Skills 的工具读取 [SKILL.md](SKILL.md)。典型请求：

> 对比最近两批采样，对各板块先给总结，再列上涨最快与当前概率较高的事件，单列首次观察的新市场。输出详细数据版和不带平台名、链接或金额的纯预测版。明说历史缺失和扫描限制。

### 快速验证

Python 3.10+，无需第三方包。在本目录运行：

```sh
python -m unittest discover -s tests -v
python scripts/market_digest.py --fixture tests/fixtures/current.json --prior tests/fixtures/prior.json --out demo
```

示例是虚构数据。实时访问需主动加 `--live`；页预算耗尽属于部分采集，不能冒称完整全站快照。命令行只负责取数、核验和排序，不会替你解释事件或代发报告。查看 [取证方法](references/method.md) 和 [两份报告结构](references/reports.md)。
