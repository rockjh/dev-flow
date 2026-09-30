# 直接数据库访问

仅在以下两种情况下使用直接MySQL、 Elasticsearch、 MongoDB或其他数据存储语句 ：

1. `missing_prerequisite_api` ：模块不公开 API或批准的测试控件 ，可以创建其 API案例所需的数据。
2. `missing_response_state` ： API响应不暴露证明操作成功所需的状态。

首选公共或已批准的测试API （ API只要存在 ）。数据库设置是测试准备 ，而不是测试中的业务操作。数据库断言是对 HTTP状态和可用业务响应断言的补充 ；它们不会取代服务提供的可观察响应检查。

## 用例格式

在`cases.yaml`中声明个案所有的步骤。跑步者将每个选定的 `setup`步骤收集到一个跑步级计划中 ，并在情况下仅实现先决条件防护。在 Bruno中保留 `script:post-response`步骤 `assertion`并且仅当所选范围包含数据库步骤时 ，运行器才启用其开发人员沙盒。

```yaml
database_steps:
  - phase: setup
    reason: missing_prerequisite_api
    engine: mysql
    evidence:
      - src/main/java/example/ThingRepository.java:42
    id: thing-ready
    data_source: primary
    estimated_records: 1
    idempotent: true
    ownership:
      namespace_env: DEVFLOW_DATA_NAMESPACE
      resource: thing
      selector: id = DEVFLOW_DATA_NAMESPACE
    precheck: |
      const mysql = require("mysql2/promise");
      const connection = await mysql.createConnection({
        host: bru.getEnvVar("MYSQL_HOST"),
        port: Number(bru.getEnvVar("MYSQL_PORT")),
        user: bru.getEnvVar("MYSQL_USER"),
        password: bru.getEnvVar("MYSQL_PASSWORD"),
        database: bru.getEnvVar("MYSQL_DATABASE")
      });
      const [rows] = await connection.execute(
        "SELECT id FROM thing WHERE id = ?",
        [bru.getEnvVar("DEVFLOW_DATA_NAMESPACE")]
      );
      await connection.end();
      bru.setVar("DEVFLOW_STEP_EXISTS", rows.length ? "true" : "false");
    script: |
      const mysql = require("mysql2/promise");
      const connection = await mysql.createConnection({
        host: bru.getEnvVar("MYSQL_HOST"),
        port: Number(bru.getEnvVar("MYSQL_PORT")),
        user: bru.getEnvVar("MYSQL_USER"),
        password: bru.getEnvVar("MYSQL_PASSWORD"),
        database: bru.getEnvVar("MYSQL_DATABASE")
      });
      const thingId = bru.getEnvVar("DEVFLOW_DATA_NAMESPACE");
      await connection.execute(
        "INSERT IGNORE INTO thing(id, status) VALUES (?, ?)",
        [thingId, "READY"]
      );
      await connection.end();
    setup_verification: |
      const mysql = require("mysql2/promise");
      const connection = await mysql.createConnection({
        host: bru.getEnvVar("MYSQL_HOST"),
        port: Number(bru.getEnvVar("MYSQL_PORT")),
        user: bru.getEnvVar("MYSQL_USER"),
        password: bru.getEnvVar("MYSQL_PASSWORD"),
        database: bru.getEnvVar("MYSQL_DATABASE")
      });
      const [rows] = await connection.execute(
        "SELECT id FROM thing WHERE id = ?",
        [bru.getEnvVar("DEVFLOW_DATA_NAMESPACE")]
      );
      await connection.end();
      if (rows.length !== 1) throw new Error("owned fixture is missing");
    cleanup: |
      const mysql = require("mysql2/promise");
      const connection = await mysql.createConnection({
        host: bru.getEnvVar("MYSQL_HOST"),
        port: Number(bru.getEnvVar("MYSQL_PORT")),
        user: bru.getEnvVar("MYSQL_USER"),
        password: bru.getEnvVar("MYSQL_PASSWORD"),
        database: bru.getEnvVar("MYSQL_DATABASE")
      });
      await connection.execute("DELETE FROM thing WHERE id = ?", [bru.getEnvVar("DEVFLOW_DATA_NAMESPACE")]);
      await connection.end();
    cleanup_verification: |
      const mysql = require("mysql2/promise");
      const connection = await mysql.createConnection({
        host: bru.getEnvVar("MYSQL_HOST"),
        port: Number(bru.getEnvVar("MYSQL_PORT")),
        user: bru.getEnvVar("MYSQL_USER"),
        password: bru.getEnvVar("MYSQL_PASSWORD"),
        database: bru.getEnvVar("MYSQL_DATABASE")
      });
      const [rows] = await connection.execute(
        "SELECT id FROM thing WHERE id = ?",
        [bru.getEnvVar("DEVFLOW_DATA_NAMESPACE")]
      );
      await connection.end();
      if (rows.length) throw new Error("owned fixture still exists after cleanup");

  - phase: assertion
    reason: missing_response_state
    engine: mysql
    evidence:
      - src/main/java/example/ThingRepository.java:68
    expected:
      row_count: 1
      status: DONE
    script: |
      const mysql = require("mysql2/promise");
      const connection = await mysql.createConnection({
        host: bru.getEnvVar("MYSQL_HOST"),
        port: Number(bru.getEnvVar("MYSQL_PORT")),
        user: bru.getEnvVar("MYSQL_USER"),
        password: bru.getEnvVar("MYSQL_PASSWORD"),
        database: bru.getEnvVar("MYSQL_DATABASE")
      });
      const [rows] = await connection.execute(
        "SELECT status FROM thing WHERE id = ?",
        [bru.getEnvVar("THING_ID")]
      );
      test("thing state was persisted", () => {
        expect(rows).to.have.lengthOf(1);
        expect(rows[0].status).to.equal("DONE");
      });
      await connection.end();
```

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 其他引擎

- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

在`qa/bruno/package.json`中声明所需的节点客户端并固定其版本。不要为一次性步骤添加通用数据库抽象。

## 运行时与安全

连接地址、数据库/索引名称、用户、密码、TLS设置和夹具标识符仅来自活动的 BRUNO环境或其过程环境。切勿提交已解析的凭据或具有凭据的 URL。

语句应使用参数绑定或确切的文档ID ，并在可能的情况下具有幂等性。

每个可能的创建在设置开始之前被记录`created`然后仅在设置验证后被提升为。 这允许清除部分失败的写入，而无需声明创建成功。 清理在套件之后或之后通过`devflow bru-api mock-data-clean`以相反的依赖关系顺序运行 ；中断的运行仍可通过运行 ID恢复。 连接、查询、期望、清理或缺勤验证错误是失败，而不是手动传递。
