# bru-api 示例：任务管理

本示例只保留 API 测试资产。实际项目必须先运行 `devflow/biz-flow-doc-generator`，再从
项目 `docs/biz-flow/` 读取业务 Markdown、模块归属、流程覆盖和源码证据。
不要在 `qa/` 中复制业务设计；`constraints/design-rules.yaml` 只是可重建缓存。

保留内容如下：

- `qa/contracts/`：OpenAPI、接口契约、用例和锁。
- `qa/bruno/任务管理/`：中文模块名和中文 Bruno 请求文件。
- `qa/execution/`：执行配置和环境变量占位符。
- `qa/reports/`：权威报告路径占位符。

运行前，将示例项目放入已经完成 biz-flow 的项目中，并执行：

```text
devflow bru-api check --qa-root example/qa --all
devflow bru-api preflight --qa-root example/qa
devflow bru-api run --qa-root example/qa
```
