import json
import re
import subprocess
from pathlib import Path

from toolkit.core.redaction import redact
from toolkit.biz_flow_doc_generator.discovery import _decorated_entries, scan
from toolkit.biz_flow_doc_generator.documents import apply_module_map, write_discovery
from toolkit.biz_flow_doc_generator.cli import _write_overview_report
from toolkit.biz_flow_doc_generator.cli import _split_entry_ids
from toolkit.biz_flow_doc_generator.models import EntryPoint, GitInfo, ScanResult


def test_java_multiline_handler_keeps_body_and_annotated_parameter_types(tmp_path: Path) -> None:
    """多行声明和参数注解不能截断处理器及其业务分支。"""
    from toolkit.biz_flow_doc_generator.discovery import _functions, _enrich_signatures
    source = '''package example;
class DeviceController {
    /** 查询设备详情。 */
    @GetMapping("/devices/{id}")
    @Operation(summary = "查询设备详情")
    public Response<Device> detail(
        @PathVariable("id") @NotNull String id)
        throws Exception {
        if (id.isBlank()) { throw new BusinessException("EMPTY_ID"); }
        return load(id);
    }
    private Device load(String id) { return null; }
}
'''
    (tmp_path / "DeviceController.java").write_text(source, encoding="utf-8")
    _git(tmp_path)
    functions = _functions(source, "Java", "DeviceController.java")
    _enrich_signatures(functions, "Java")
    handler = next(item for item in functions if item.name == "detail")
    assert handler.signature == "detail(String)"
    assert "EMPTY_ID" in handler.body and "return load(id)" in handler.body
    result = scan(tmp_path)
    assert result.entries[0].handler == "detail"
    assert "查询设备详情" in result.entries[0].business_name
    assert "*/" not in result.entries[0].business_name
    assert not any("handler for" in finding for finding in result.unresolved)


def test_feign_outbound_mapping_is_not_an_unrecognized_registration(tmp_path: Path) -> None:
    (tmp_path / "UserClient.java").write_text('''package example;
@FeignClient(name = "users")
public interface UserClient {
    @GetMapping("/users/{id}")
    User get(@PathVariable("id") String id);
}
''', encoding="utf-8")
    _git(tmp_path)
    result = scan(tmp_path)
    assert result.entries == [] and result.unresolved == []


def test_java_field_receiver_uses_declared_type_and_external_boundary(tmp_path: Path) -> None:
    (tmp_path / "Controller.java").write_text('''package example;
import sdk.OperatorApplication;
class Controller {
    private final One service;
    private final OperatorApplication external;
    @GetMapping("/orders")
    public void run() {
        service.submitOrder();
        external.getCapability();
    }
}
class One {
    public void submitOrder() { throw new BusinessException("ONE_ERROR"); }
}
class Two {
    public void submitOrder() { throw new BusinessException("TWO_ERROR"); }
}
''', encoding="utf-8")
    _git(tmp_path)
    result = scan(tmp_path)
    assert "ONE_ERROR" in result.entries[0].error_codes()
    assert "TWO_ERROR" not in result.entries[0].error_codes()
    assert not any("getCapability has an unknown receiver" in finding for finding in result.unresolved)
    assert any(item.kind == "外部调用" and "OperatorApplication.getCapability" in item.statement
               for item in result.entries[0].behaviors)


def test_class_job_registration_and_constructor_merge_into_template_entry(tmp_path: Path) -> None:
    (tmp_path / "DeviceJob.java").write_text('''package example;
@JobHandler("example.device.job")
class DeviceJob extends AbstractJobHandler {
    DeviceJob(Service service) {}
    public String cronExpression() { return "cron"; }
    protected void doExecute(String input) {}
}
''', encoding="utf-8")
    _git(tmp_path)
    result = scan(tmp_path)
    assert [(entry.kind, entry.identifier, entry.handler) for entry in result.entries] == [
        ("scheduled", "example.device.job", "doExecute")]


def test_plain_register_is_not_a_message_trigger_and_receiver_resolves_topic(tmp_path: Path) -> None:
    (tmp_path / "DeviceReceiver.java").write_text('''package example;
class DeviceReceiver extends AbstractReceiver<String> {
    DeviceReceiver(Service service) {}
    public int threadNum() { return 8; }
    protected void doServe(String value) {}
    public String topic() { return Topics.DEVICE_REPORT; }
}
class Tasks {
    void register(String fileId, Long timestamp) { register(fileId, timestamp, null); }
}
''', encoding="utf-8")
    (tmp_path / "Topics.java").write_text('''class Topics {
    public static final String DEVICE_REPORT = "device.report";
}
''', encoding="utf-8")
    _git(tmp_path)
    result = scan(tmp_path)
    assert [(entry.kind, entry.identifier, entry.handler) for entry in result.entries] == [
        ("message", "device.report", "doServe")]


def test_conversation_and_markdown_share_business_counts_and_filenames(tmp_path: Path) -> None:
    """对话和总览展示同一模块映射，排除候选不计入业务数量。"""
    from toolkit.biz_flow_doc_generator.cli import _conversation_overview
    from toolkit.biz_flow_doc_generator.documents import readable_inventory
    business = EntryPoint("one", "url", "GET /devices", "list", "Device.java", 2,
                          "device", "Device.java", business_name="查询设备")
    excluded = EntryPoint("two", "message", "id", "save", "DeviceDao.java", 2,
                          "device", "DeviceDao.java", scope_status="excluded")
    result = ScanResult(tmp_path, GitInfo("main", "a" * 40, "a" * 40, False, False),
                        ["Java"], [], [business], [], ["待复核"], "fp", all_entries=[business, excluded])
    mapping = {"modules": [{"name": "device", "display_name": "设备", "responsibility": "查询设备",
                             "file": "00-设备.md", "entry_ids": ["one"]}],
               "exclusions": [{"candidate": "two", "module": "device", "reason": "DAO 数据访问方法",
                               "evidence": ["DeviceDao.java:2"]}]}
    conversation = _conversation_overview(result, mapping, tmp_path)
    overview = "\n".join(readable_inventory(result, mapping))
    assert "| 00-设备 | 查询设备 | 1 |" in conversation
    assert "| 00-设备 | 查询设备 | 1 |" in overview
    assert "仓储及数据访问 | 1" in conversation and "仓储及数据访问 | 1" in overview
    assert "DeviceDao.java:2" not in conversation and "DeviceDao.java:2" in overview
    assert "待源码复核" in conversation and "阻塞项：" not in conversation
    assert "| 其他源码证据待核对 | 1 |" in conversation
    assert "generate --confirm" in conversation
    assert "不能仅回复文件链接" in conversation


def test_review_requires_entry_confirmation_and_does_not_write_flow_modules(tmp_path, monkeypatch):
    """入口清单确认后才启动审核；执行器失败不得写时序图或推进源码基线。"""
    from toolkit.biz_flow_doc_generator.cli import init_command, discover_command, review_command, generate_command
    (tmp_path / "DeviceController.java").write_text('''class DeviceController {
    /** 查询设备。 */
    @GetMapping("/devices")
    public String query() { return "ok"; }
}
''', encoding="utf-8")
    _git(tmp_path)
    assert init_command(["--project", str(tmp_path)]) == 0
    before = (tmp_path / "docs/biz-flow/biz-flow-doc-generator-version.json").read_bytes()
    calls = []
    def unavailable(run_id):
        calls.append(run_id)
        return None, {"type": "unavailable", "adapter": "", "probed": True, "capabilities": {}}
    monkeypatch.setattr("toolkit.biz_flow_doc_generator.orchestration.discover_agent_executor", unavailable)
    assert review_command(["--project", str(tmp_path)]) == 8
    assert calls == []
    docs = tmp_path / "docs/biz-flow"
    assert discover_command(["--project", str(tmp_path)]) == 0
    overview_path = docs / "业务流程覆盖总览.md"
    overview = overview_path.read_text(encoding="utf-8")
    assert "<!-- devflow:module-confirmed -->" not in overview
    directory_files = {path.name: path.read_bytes() for path in docs.glob("[0-9]*.md")}
    assert directory_files and all(b"sequenceDiagram" not in content for content in directory_files.values())
    overview_path.write_text(overview + "\n<!-- devflow:module-confirmed -->\n", encoding="utf-8")
    assert review_command(["--project", str(tmp_path)]) == 8
    assert len(calls) == 1
    assert {path.name: path.read_bytes() for path in docs.glob("[0-9]*.md")} == directory_files
    assert (docs / "biz-flow-doc-generator-version.json").read_bytes() == before
    assert generate_command(["--project", str(tmp_path)]) == 8
    assert (docs / "biz-flow-doc-generator-version.json").read_bytes() == before


def test_repeated_discovery_preserves_reviewed_filename_without_confirming(tmp_path: Path) -> None:
    (tmp_path / "DeviceController.java").write_text('''class DeviceController {
    /** 查询设备。 */
    @GetMapping("/devices")
    public String query() { return "ok"; }
}
''', encoding="utf-8")
    _git(tmp_path)
    result = scan(tmp_path)
    docs = tmp_path / "docs" / "biz-flow"
    _, map_path = write_discovery(result, docs)
    overview = docs / "业务流程覆盖总览.md"
    text = overview.read_text(encoding="utf-8")
    assert "<!-- devflow:module-confirmed -->" not in text
    map_path.unlink()
    overview.write_text(re.sub(r'file="[^"]+"', 'file="00-旧文件.md"', text), encoding="utf-8")
    _, map_path = write_discovery(result, docs)
    text = overview.read_text(encoding="utf-8")
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    filename = mapping["modules"][0]["file"]
    assert "<!-- devflow:module-confirmed -->" not in text
    assert f'file="{filename}"' in text and f'| {Path(filename).stem} |' in text
    assert filename == "00-旧文件.md"
    source = tmp_path / "DeviceController.java"
    source.write_text(source.read_text(encoding="utf-8") + "\n// 更新设备入口说明。\n", encoding="utf-8")
    changed = scan(tmp_path, entry_only=True)
    assert changed.source_fingerprint != result.source_fingerprint
    write_discovery(changed, docs)
    updated = overview.read_text(encoding="utf-8")
    assert changed.source_fingerprint in updated
    assert "<!-- devflow:module-confirmed -->" not in updated


def _git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)


def test_java_platform_entries_and_excluded_sources(tmp_path: Path) -> None:
    (tmp_path / "Handlers.java").write_text(
        '@XxlJob("inventory")\n'
        "class Job extends XxlJobHandler {\n"
        "  public Response\n"
        "  doExecute(Request request) { return ok(); }\n"
        "}\n"
        "class Receiver extends BaseReceiver {\n"
        '  static final String TOPIC = "orders.created";\n'
        "  public void\n"
        "  doServe(Message message) {}\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / ".idea").mkdir()
    (tmp_path / ".idea" / "ignored.java").write_text('@XxlJob("ignored") void execute() {}', encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "ignored.log").write_text('@XxlJob("ignored")', encoding="utf-8")
    _git(tmp_path)

    result = scan(tmp_path)
    assert result.files == ["Handlers.java"]
    assert [(entry.kind, entry.identifier, entry.handler) for entry in result.entries] == [
        ("message", "orders.created", "doServe"),
        ("scheduled", "inventory", "doExecute"),
    ]
    assert [entry.entry_id for entry in scan(tmp_path).entries] == [entry.entry_id for entry in result.entries]


def test_nested_java_business_entries_use_outer_class_in_full_name(tmp_path: Path) -> None:
    (tmp_path / "Jobs.java").write_text(
        "package com.example.jobs;\n"
        "class Outer {\n"
        "  class First extends XxlJobHandler {\n"
        "    public void doExecute(String value) {}\n"
        "  }\n"
        "  class Second extends XxlJobHandler {\n"
        "    public void doExecute(String value) {}\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    _git(tmp_path)

    result = scan(tmp_path)
    entries = [entry for entry in result.entries if entry.kind == "scheduled"]
    assert len(entries) == 2
    capabilities = {entry.functions[0] for entry in entries}
    assert capabilities == {
        "java:com.example.jobs.Outer.First#doExecute(String)",
        "java:com.example.jobs.Outer.Second#doExecute(String)",
    }
    assert not any("CAPABILITY_ID_CONFLICT" in item for item in result.unresolved)


def test_shared_helper_identity_is_independent_of_entry_registration(tmp_path: Path) -> None:
    (tmp_path / "events.py").write_text(
        "def persist():\n    return 0\n"
        "# 订单创建\n"
        "@EventListener(classes='order.created')\n"
        "def store_order():\n    persist()\n"
        "# 订单更新\n"
        "@EventListener(classes='order.updated')\n"
        "def update_order():\n    persist()\n",
        encoding="utf-8",
    )
    _git(tmp_path)

    result = scan(tmp_path)
    entries = {entry.identifier: entry for entry in result.entries}
    assert entries["order.created"].functions[-1] == entries["order.updated"].functions[-1]
    assert entries["order.created"].functions[-1] == "python:events#persist()"
    assert not any("CAPABILITY_ID_CONFLICT" in item for item in result.unresolved)


def test_annotation_listener_resolves_constant_topics(tmp_path: Path) -> None:
    (tmp_path / "Listener.java").write_text(
        "class Listener {\n"
        "  private static final String TOPIC = \"device.report\";\n"
        "  @KafkaListener(topics = TOPIC)\n"
        "  public void consume(String message) {}\n"
        "}\n",
        encoding="utf-8",
    )
    _git(tmp_path)

    result = scan(tmp_path)
    assert [(entry.kind, entry.identifier) for entry in result.entries] == [("message", "device.report")]


def test_java_method_names_ending_in_command_are_not_cli_entries(tmp_path: Path) -> None:
    (tmp_path / "CommandService.java").write_text(
        "class CommandService {\n"
        "  private void dispatchCommand() { markEventExecuting(); }\n"
        "  private void markEventExecuting() { createDistributionTask(); }\n"
        "  private void createDistributionTask() {}\n"
        "}\n",
        encoding="utf-8",
    )
    _git(tmp_path)

    result = scan(tmp_path)
    assert result.entries == []
    assert not any("CAPABILITY_ID_CONFLICT" in item for item in result.unresolved)


def test_cli_registration_requires_a_decorator_not_an_ordinary_call() -> None:
    for text in ("client.command('run');", "new Command('run');", "buildCommand();", "command();"):
        assert _decorated_entries(text, "Java", "Service.java") == []
    for decorator in ("click.command", "app.command", "typer.command", "Command"):
        entries = _decorated_entries(
            f"@{decorator}(name='run')\ndef run():\n    return 0\n", "Python", "commands.py"
        )
        assert entries == [("cli", "run", 1, "run")]


def test_shared_helper_is_not_a_capability_ownership_conflict(tmp_path: Path) -> None:
    (tmp_path / "events.py").write_text(
        "def persist():\n    return 0\n"
        "# 接收订单事件并保存订单\n"
        "@EventListener(classes='order.created')\n"
        "def store_order():\n    persist()\n"
        "# 接收订单事件并保存记录\n"
        "@EventListener(classes='order.created')\n"
        "def store_history():\n    persist()\n",
        encoding="utf-8",
    )
    _git(tmp_path)
    result = scan(tmp_path)
    assert len(result.entries) == 2
    shared = set(result.entries[0].functions) & set(result.entries[1].functions)
    assert any("#persist(" in capability for capability in shared)
    assert not any("CAPABILITY_ID_CONFLICT" in item for item in result.unresolved)

    docs = tmp_path / "docs" / "biz-flow"
    _, path = write_discovery(result, docs)
    mapping = json.loads(path.read_text(encoding="utf-8"))
    mapping["confirmed"] = True
    for module in mapping["modules"]:
        module.update(rationale="按订单事件源码归组", responsibility="保存订单事件")
    for review in mapping["entry_reviews"]:
        review.update(status="confirmed", confirmed_by="tester", trigger="订单事件", purpose="保存订单",
                      input="订单数据", outcome="保存完成", failure="向调用方传播异常")
        for step in review["steps"]:
            step["text"] = "保存订单事件"
    path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    assert apply_module_map(result, path) == []


def test_structured_markers_survive_redaction() -> None:
    value = '<!-- biz-flow-entry: token=ENTRY -->\n<!-- devflow:module name="token" --> token=secret'
    redacted = redact(value)
    assert "biz-flow-entry: token=ENTRY" in redacted
    assert 'devflow:module name="token"' in redacted
    assert "token=[REDACTED]" in redacted


def test_redaction_preserves_authorization_path_in_structured_entry_id() -> None:
    entry_id = "url:GET /v0/admin/operators/{operatorCode}/authorization:controller.java:queryAuthorization"
    assert redact(entry_id) == entry_id
    assert redact("authorization: bearer-secret") == "authorization: [REDACTED]"


def test_module_entry_ids_preserve_commas_in_method_parameters() -> None:
    first = "worker:java:example.Worker#run(Input,Long)"
    second = "url:GET /health:Controller#health()"
    assert _split_entry_ids(f"{first},{second}") == [first, second]


def test_mermaid_success_uses_cleaned_label() -> None:
    from toolkit.biz_flow_doc_generator.documents import _diagram
    from toolkit.biz_flow_doc_generator.models import EntryPoint, EntryReview

    entry = EntryPoint("url:GET /x:a.py:handler", "url", "GET /x", "handler", "a.py", 1, "a", "a.py")
    entry.review = EntryReview("id", "caller", "purpose", "input", "password: SECRET; outcome", "failure")
    diagram = _diagram(entry)
    assert "SECRET" not in diagram
    assert "password: [REDACTED]" in diagram


def test_error_code_prefers_raised_literal_over_condition_status() -> None:
    from toolkit.biz_flow_doc_generator.discovery import _error

    evidence = _error(
        'payment_id not in PAYMENTS or status != "PAID" -> raise OrderError("PAYMENT_FAILED")',
        "app.py",
        10,
    )
    assert evidence.code == "PAYMENT_FAILED"


def test_overview_keeps_excluded_candidates_in_complete_list(tmp_path: Path) -> None:
    (tmp_path / "AcController.py").write_text("# 查询 AC 信息\n", encoding="utf-8")
    (tmp_path / "AcDao.py").write_text("def load(): pass\n", encoding="utf-8")
    business = EntryPoint(
        "url:GET /ac:AcController.py:get", "url", "GET /ac", "get", "AcController.py", 1,
        "ac", "AcController.py", business_name="查询 AC 信息", trigger_summary="HTTP：GET /ac",
        source_evidence=[{"file": "AcController.py", "line": 1, "reason": "路由注释"}],
    )
    excluded = EntryPoint(
        "message:id:AcDao.py:load", "message", "id:ac", "load", "AcDao.py", 1,
        "ac", "AcDao.py", business_name="技术入口：load", trigger_summary="消息：id:ac",
        source_evidence=[{"file": "AcDao.py", "line": 1, "reason": "DAO 注册"}],
        scope_status="excluded", exclusion_reason="DAO 持久化适配器",
    )
    result = ScanResult(
        tmp_path, GitInfo("main", "a" * 40, "a" * 40, False, False), ["Python"], [],
        [business, excluded], ["AcController.py", "AcDao.py"], [], "fingerprint",
        {"AcController.py": 1, "AcDao.py": 1}, all_entries=[business, excluded],
        discovered_entry_count=2,
    )
    docs_root = tmp_path / "docs" / "biz-flow"
    discovery_path, _ = write_discovery(result, docs_root)
    overview = (docs_root / "业务流程覆盖总览.md").read_text(encoding="utf-8")
    assert overview.index("业务模块划分") < overview.index("建议忽略的入口")
    assert business.entry_id in overview
    assert excluded.entry_id in overview
    assert discovery_path.is_file()

    module_map = docs_root / "biz-flow-modules.json"
    document = json.loads(module_map.read_text(encoding="utf-8"))
    document["confirmed"] = True
    module_map.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    result.entries = [business]
    _write_overview_report(docs_root, result, {})
    rendered = (docs_root / "业务流程覆盖总览.md").read_text(encoding="utf-8")
    assert "| 技术入口：" not in rendered.split("## 完整入口清单", 1)[0]
    assert excluded.entry_id in rendered


def test_business_object_precedes_processing_form_and_framework_names() -> None:
    from toolkit.biz_flow_doc_generator.discovery import _business_module_name
    entries = [
        ("POST /v0/admin/ac/batch-sync", "run", "api/AcController.java", "AC业务"),
        ("POST /v0/admin/mocks", "notify", "api/operator/MockController.java", "运营商"),
        ("job", "doExecute", "jobs/terminal/sync/TimeoutJob.java", "设备"),
    ]
    for identifier, handler, file, expected in entries:
        entry = EntryPoint("id", "url" if identifier.startswith("POST") else "scheduled",
                           identifier, handler, file, 1, "technical", "source")
        assert _business_module_name(entry) == expected


def test_chinese_storage_label_only_clears_label_unknown() -> None:
    from toolkit.biz_flow_doc_generator.validation import pending_entry_inventory
    label = {"code": "PERSISTENCE_DISPLAY_NAME_UNRESOLVED", "evidence": "Store.java:3"}
    resource = {"code": "PERSISTENCE_RESOURCE_UNRESOLVED", "evidence": "Store.java:3"}
    inventory = {"unresolved": [label, resource]}
    value = {"persistence_actions": [{"source_file": "Store.java", "source_line": 3,
                                      "display_name": "订单"}]}
    assert pending_entry_inventory(value, inventory)["unresolved"] == [resource]
    value["persistence_actions"][0]["display_name"] = "数据库"
    assert pending_entry_inventory(value, inventory)["unresolved"] == [label, resource]


def test_module_overview_uses_source_terms_and_covers_every_entry(tmp_path: Path) -> None:
    """在无项目专用词典的业务域验证文件名、全部入口动作及双端一致性。"""
    from toolkit.biz_flow_doc_generator.cli import _conversation_overview
    from toolkit.biz_flow_doc_generator.documents import readable_inventory, _is_chinese_module_filename

    actions = ["查询仓库库存", "新增仓库", "编辑仓库", "删除仓库", "导出库存", "接收库存变更通知"]
    methods = "\n".join(
        f'    /** 通用处理说明。 */\n    @PostMapping("/v0/admin/warehouses/action{i}")\n'
        f'    @Operation(summary = "{action}")\n    public void action{i}() {{}}'
        for i, action in enumerate(actions)
    )
    source = '@Tag(name = "仓库库存、变更通知")\n@RestController\nclass WarehouseController {\n' + methods + '\n}\n'
    (tmp_path / "WarehouseController.java").write_text(source, encoding="utf-8")
    _git(tmp_path)
    result = scan(tmp_path)
    assert {entry.business_name for entry in result.entries} == set(actions)
    assert all(entry.module_label == "仓库库存、变更通知" for entry in result.entries)
    docs = tmp_path / "docs/biz-flow"
    _, mapping_path = write_discovery(result, docs)
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    module = mapping["modules"][0]
    assert module["file"] == "00-仓库库存管理与变更通知.md"
    assert _is_chinese_module_filename(module["file"])
    assert not _is_chinese_module_filename("00-仓库、库存.md")
    assert not _is_chinese_module_filename("00-仓库 库存.md")
    assert not _is_chinese_module_filename("00-仓库-库存.md")
    assert all(feature in module["responsibility"] for feature in ("维护仓库", "查询仓库库存", "变更通知"))
    assert "；" in module["responsibility"]
    assert "等业务" not in module["responsibility"]
    conversation = _conversation_overview(result, mapping, docs)
    overview = (docs / "业务流程覆盖总览.md").read_text(encoding="utf-8")
    table = re.search(r"(?m)^\| 业务模块文件名 \|[^\n]*\n(?:\|[^\n]*\n?)+", conversation).group().rstrip()
    assert table in overview
    assert table.splitlines()[0] == "| 业务模块文件名 | 业务描述 | 入口数量 |"
    assert "| 00-仓库库存管理与变更通知 |" in table and "| 6 |" in table
    assert ".md" not in table
    assert all(entry.entry_id in overview for entry in result.entries)
    assert module["file"] in overview.split("<!-- devflow:machine-map -->")[1]
    write_discovery(result, docs)
    assert "\n".join(readable_inventory(result, mapping)) in overview
    assert json.loads(mapping_path.read_text(encoding="utf-8"))["modules"] == mapping["modules"]


def test_module_description_uses_swagger_business_capabilities_and_keeps_sentences(tmp_path: Path) -> None:
    """Swagger 说明独立于文件名，保留多句能力并清理调用方和 HTML。"""
    from toolkit.biz_flow_doc_generator.documents import write_entry_directory
    source = '''@Tag(name = "仓库设备管理",
    description = "client:portal<br/>查询仓库设备列表，执行设备启用和停用。" + "支持设备状态查询。")
@RestController
class WarehouseDeviceController {
    @GetMapping("/v0/admin/warehouses/devices")
    @Operation(summary = "查询仓库设备列表", description = "client:portal<br/>查询列表。")
    public void list() {}
    @GetMapping("/v0/admin/warehouses/devices/{id}")
    @Operation(summary = "查询仓库设备详情")
    public void detail() {}
    @PostMapping("/v0/admin/warehouses/devices/enable")
    @Operation(summary = "启用仓库设备")
    public void enable() {}
    @PostMapping("/v0/admin/warehouses/devices/disable")
    @Operation(summary = "停用仓库设备")
    public void disable() {}
}
'''
    (tmp_path / "WarehouseDeviceController.java").write_text(source, encoding="utf-8")
    _git(tmp_path)
    result = scan(tmp_path, entry_only=True)
    description = "查询仓库设备列表，执行设备启用和停用。支持设备状态查询。"
    assert len(result.entries) == 4
    assert all(entry.module_description == description for entry in result.entries)
    docs = tmp_path / "docs/biz-flow"
    _, mapping_path = write_discovery(result, docs)
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    module = mapping["modules"][0]
    assert module["responsibility"] == description
    assert "查询仓库设备详情" not in module["responsibility"]
    assert "client:" not in module["responsibility"] and "<br" not in module["responsibility"]
    assert write_entry_directory(result, docs, mapping) == []
    assert description in (docs / module["file"]).read_text(encoding="utf-8")
    assert description in (docs / "业务流程覆盖总览.md").read_text(encoding="utf-8")
    first = (docs / "业务流程覆盖总览.md").read_bytes()
    write_discovery(result, docs)
    assert (docs / "业务流程覆盖总览.md").read_bytes() == first


def test_module_description_limits_shared_swagger_scope_and_merges_queries() -> None:
    """跨域分组不引入其他域的 Swagger 能力，列表详情不逐接口罗列。"""
    from toolkit.biz_flow_doc_generator.documents import _module_business_description

    names = ["分页查询仓库设备列表", "查询仓库设备详情", "查询仓库设备状态", "启用仓库设备", "停用仓库设备", "查询设备费用"]
    entries = [EntryPoint(str(index), "url", "/devices", "run", "Device.java", index + 1,
                          "仓库", "Device.java", business_name=name, module_label="仓库设备",
                          module_description="维护仓库设备，查询设备费用。")
               for index, name in enumerate(names)]
    description = _module_business_description(entries[:-1], entries)
    assert description == "查询仓库设备；启用仓库设备；停用仓库设备。"
    assert "费用" not in description
    assert _module_business_description(entries, entries) == "维护仓库设备，查询设备费用。"
    recovery = EntryPoint("job", "scheduled", "recover", "run", "Recover.java", 1,
                          "仓库", "Recover.java", business_name="仓库设备恢复",
                          module_description="仓库设备恢复任务。")
    receiver = EntryPoint("message", "message", "events", "receive", "Receiver.java", 1,
                          "仓库", "Receiver.java", business_name="仓库设备状态变更",
                          module_description="仓库设备状态变更消费者，只提交已持久化记录主键。")
    assert _module_business_description([recovery, receiver], [recovery, receiver]) == "仓库设备恢复；仓库设备状态变更。"


def test_module_filenames_summarize_objects_without_losing_actions(tmp_path: Path) -> None:
    """业务域加主要职能构成一句文件名，重复查询概括而不逐入口拼接。"""
    labels = ["设备管理", "设备事件", "设备统计", "跨系统设备关系回调", "运营商设备操作记录"]
    entries = [
        EntryPoint(f"entry-{i}", "url", f"GET /devices/{i}", "run", "Device.java", i + 1,
                   "device", "Device.java", business_name=f"查询设备业务{i}", module_label=label)
        for i, label in enumerate(labels)
    ]
    entries.extend([
        EntryPoint("order", "url", "POST /orders", "sync", "Order.java", 1, "order", "Order.java",
                   business_name="智库订单同步", module_label="智库"),
        EntryPoint("batch-1", "url", "GET /batch-tasks", "list", "Batch.java", 1, "batch", "Batch.java",
                   business_name="分页查询批量任务", module_label="批量任务"),
        EntryPoint("batch-2", "url", "GET /batch-tasks/options", "options", "Batch.java", 2, "batch", "Batch.java",
                   business_name="查询任务类型选项", module_label="批量任务"),
    ])
    result = ScanResult(tmp_path, GitInfo("main", "a" * 40, "a" * 40, False, False),
                        ["Java"], [], entries, [], [], "fingerprint")
    _, mapping_path = write_discovery(result, tmp_path / "docs/biz-flow")
    modules = {item["name"]: item for item in json.loads(mapping_path.read_text(encoding="utf-8"))["modules"]}
    assert modules["batch"]["file"] == "00-批量任务查询.md"
    assert modules["order"]["file"] == "02-订单同步.md"
    assert "订单同步" in modules["order"]["responsibility"]
    assert len(Path(modules["device"]["file"]).stem) <= 43
    assert "查询" in modules["device"]["responsibility"]
    assert "业务0" not in modules["device"]["file"]


def test_automatic_short_filename_migrates_completed_content_and_preserves_custom_names(tmp_path: Path) -> None:
    """自动旧短名迁移不丢图和人工正文，自定义文件名及冲突目标不被覆盖。"""
    import pytest

    entry = EntryPoint("one", "url", "GET /stock", "query", "Stock.java", 1,
                       "仓库库存", "Stock.java", business_name="查询仓库库存", module_label="仓库库存")
    create = EntryPoint("create", "url", "POST /stock", "create", "Stock.java", 2,
                        "仓库库存", "Stock.java", business_name="创建仓库", module_label="仓库库存")
    result = ScanResult(tmp_path, GitInfo("main", "a" * 40, "a" * 40, False, False),
                        ["Java"], [], [entry, create], [], [], "fingerprint")
    docs = tmp_path / "docs/biz-flow"
    _, mapping_path = write_discovery(result, docs)
    overview = docs / "业务流程覆盖总览.md"
    generated = json.loads(mapping_path.read_text(encoding="utf-8"))["modules"][0]["file"]
    old_name = "00-仓库库存.md"
    overview.write_text(overview.read_text(encoding="utf-8").replace(generated, old_name), encoding="utf-8")
    preserved = "<!-- biz-flow-module: 仓库库存 -->\n# 仓库库存\n```mermaid\nsequenceDiagram\n```\n人工补充说明\n"
    (docs / old_name).write_text(preserved, encoding="utf-8")
    write_discovery(result, docs)
    assert not (docs / old_name).exists()
    assert (docs / generated).read_text(encoding="utf-8") == preserved
    assert json.loads(mapping_path.read_text(encoding="utf-8"))["modules"][0]["name"] == "仓库库存"

    legacy = "00-仓库库存维护查询处理.md"
    overview.write_text(overview.read_text(encoding="utf-8").replace(generated, legacy), encoding="utf-8")
    (docs / generated).rename(docs / legacy)
    write_discovery(result, docs)
    assert not (docs / legacy).exists()
    assert (docs / generated).read_text(encoding="utf-8") == preserved

    custom = "00-仓库库存盘点说明.md"
    overview.write_text(overview.read_text(encoding="utf-8").replace(generated, custom), encoding="utf-8")
    (docs / generated).rename(docs / custom)
    write_discovery(result, docs)
    assert json.loads(mapping_path.read_text(encoding="utf-8"))["modules"][0]["file"] == custom
    assert (docs / custom).read_text(encoding="utf-8") == preserved

    overview.write_text(overview.read_text(encoding="utf-8").replace(custom, old_name), encoding="utf-8")
    (docs / custom).rename(docs / old_name)
    (docs / generated).write_text("另一个文件的人工内容", encoding="utf-8")
    with pytest.raises(RuntimeError, match="迁移目标已存在"):
        write_discovery(result, docs)
    assert (docs / old_name).read_text(encoding="utf-8") == preserved
    assert (docs / generated).read_text(encoding="utf-8") == "另一个文件的人工内容"


def test_function_summary_retains_source_object_qualifiers_without_project_templates(tmp_path: Path) -> None:
    """同域摘要保留策略、关系和解密对象，不能退化为纯动作词。"""
    from toolkit.biz_flow_doc_generator.documents import _module_function_summary

    entries = [
        EntryPoint("policy", "url", "POST /rules", "configure", "Rules.java", 1, "协作", "Rules.java",
                   business_name="配置配送策略", module_label="仓库配送策略"),
        EntryPoint("relation", "message", "relations", "receive", "Rules.java", 2, "协作", "Rules.java",
                   business_name="接收资产设备关系变更", module_label="资产设备关系变更"),
        EntryPoint("decrypt", "url", "POST /decrypt", "decrypt", "Rules.java", 3, "协作", "Rules.java",
                   business_name="解密完整资产编号", module_label="资产信息"),
    ]
    title = _module_function_summary("协作", entries)
    assert all(value in title for value in ("仓库配送策略", "资产设备关系"))
    assert "策略配置" not in title and "关系变更" not in title
    assert not title.endswith(("处理", "业务", "流程"))
    assert title.startswith("协作")
    # 辅助解密入口仍完整归档，简洁标题不等于缩小扫描范围。
    _, mapping_path = write_discovery(ScanResult(tmp_path, GitInfo("main", "a" * 40, "a" * 40, False, False),
                                                 ["Java"], [], entries, [], [], "fingerprint"), tmp_path / "docs")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert set(mapping["modules"][0]["entry_ids"]) == {entry.entry_id for entry in entries}


def test_entry_only_preserves_registrations_without_behavior_unknowns(tmp_path: Path) -> None:
    """入口阶段不追踪线程池和未知调用，深分析仍保留异步边界。"""
    (tmp_path / "orders.py").write_text(
        "# 查询订单\n@app.get('/orders')\ndef orders():\n    executor.submit(work)\n    missing()\n"
        "def work():\n    raise ValueError('FAILED')\n", encoding="utf-8",
    )
    _git(tmp_path)
    shallow = scan(tmp_path, entry_only=True)
    assert len(shallow.entries) == 1 and shallow.entries[0].kind == "url"
    assert len(shallow.registration_audit) == 1
    assert shallow.registration_audit[0]["status"] == "business"
    assert shallow.registration_audit[0]["entry_ids"] == [shallow.entries[0].entry_id]
    assert shallow.entries[0].behaviors == [] and shallow.entries[0].errors == []
    assert not any("called function" in finding or "receiver type" in finding for finding in shallow.unresolved)
    full = scan(tmp_path)
    assert not any(entry.kind == "worker" for entry in full.entries)
    assert any(error.phase == "worker" for error in full.entries[0].errors)
    selected = scan(tmp_path, entry_ids=set())
    assert selected.entries == [] and len(selected.all_entries) == 1
    assert not any("called function" in finding for finding in selected.unresolved)


def test_java_all_mappings_survive_validation_braces_and_long_class_annotations(tmp_path: Path) -> None:
    """无括号路由、长类注解和校验文案中的花括号不得漏接口或错绑。"""
    source = '''@RequestMapping("/orders")
@ApiResponses({
    @ApiResponse(responseCode = "200"),
    @ApiResponse(responseCode = "500",
        description = "failed")
})
@Tag(name = "订单管理")
class OrderController {
    @PostMapping
    @Operation(summary = "创建订单")
    public void create(@NotBlank(message = "{validation.message}") String id) {}
    @GetMapping
    @Operation(summary = "查询订单")
    public void query() {}
    @PostMapping("/{id}")
    public void update(@NotBlank(message = "{validation.message}") String id) {}
}
'''
    (tmp_path / "OrderController.java").write_text(source, encoding="utf-8")
    _git(tmp_path)
    result = scan(tmp_path, entry_only=True)
    assert {(entry.identifier, entry.handler) for entry in result.entries} == {
        ("POST /orders/", "create"), ("GET /orders/", "query"), ("POST /orders/{id}", "update"),
    }
    assert all(entry.handler_confirmed for entry in result.entries)
    assert not any("registered business entry" in finding or "handler for" in finding for finding in result.unresolved)


def test_business_resource_precedes_search_and_execute() -> None:
    from toolkit.biz_flow_doc_generator.discovery import _business_module_name
    first = EntryPoint("one", "url", "POST /v0/admin/software-sales/callbacks/search", "search",
                       "Callback.java", 1, "fallback", "Callback.java", module_label="软件销售回调")
    second = EntryPoint("two", "url", "POST /v0/admin/dms-server-configs/execute", "execute",
                        "Config.java", 1, "fallback", "Config.java", module_label="DMS服务配置")
    assert _business_module_name(first) == "软件销售"
    assert _business_module_name(second) == "DMS业务"



def test_java_mapping_arrays_only_expand_paths_and_request_methods() -> None:
    source = '''@RequestMapping({"/orders", "/purchases"})
class Orders {
    @RequestMapping(path = {"/create", "/submit"}, method = {RequestMethod.GET, RequestMethod.POST}, produces = "application/json")
    public void submit() {}
}
'''
    entries = _decorated_entries(source, "Java", "Orders.java")
    assert {identifier for _, identifier, _, _ in entries} == {
        f"{method} {base}/{action}"
        for method in ("GET", "POST") for base in ("/orders", "/purchases") for action in ("create", "submit")
    }
    assert all(handler == "submit" for _, _, _, handler in entries)


def test_configuration_file_helper_is_not_a_file_trigger() -> None:
    assert _decorated_entries("class Config { void configurationFile() {} }", "Java", "Config.java") == []


def test_operation_summary_precedes_technical_description() -> None:
    from toolkit.biz_flow_doc_generator.discovery import _comment_label
    source = '@Operation(summary = "创建订单", description = "client:portal 创建订单详细说明")\npublic void create() {}'
    assert _comment_label(source, 2) == "创建订单"


def test_multiline_response_annotations_do_not_hide_business_summary() -> None:
    from toolkit.biz_flow_doc_generator.discovery import _comment_label
    source = '''class Vehicle {
    @Operation(summary = "查询车辆当月套餐用量总量", description = "调用方信息")
    @ApiResponses(
        {@ApiResponse(responseCode = "200", description = "字符串中的括号 ( 和 )")})
    @GetMapping("")
    public void query() {}
    public void helper() {}
}
'''
    assert _comment_label(source, 6) == "查询车辆当月套餐用量总量"
    assert _comment_label(source, 7) == ""


def test_multiline_operation_summary_remains_business_action() -> None:
    from toolkit.biz_flow_doc_generator.discovery import _comment_label
    source = '''@Operation(
    summary = "取消套餐订购履约",
    description = "client:software_sale 说明")
@ApiResponses({
    @ApiResponse(responseCode = "200")
})
@PostMapping("/cancel")
public void cancel() {}
'''
    assert _comment_label(source, 8) == "取消套餐订购履约"


def test_same_business_object_merges_channels_and_query_scopes(tmp_path: Path) -> None:
    sources = {
        "VehicleUsageSummaryController.java": '''@Tag(name = "渠道甲车辆用量查询")
class VehicleUsageSummaryController {
    @GetMapping("/channel-a/vehicle-usages")
    @Operation(summary = "查询车辆用量总量")
    public void query() {}
}
''',
        "VehicleUsageDetailController.java": '''@Tag(name = "渠道乙车辆用量查询")
class VehicleUsageDetailController {
    @GetMapping("/channel-b/vehicle-usages")
    @Operation(summary = "查询车辆用量明细")
    public void query() {}
}
''',
        "SalablePlanController.java": '''@Tag(name = "可售套餐")
class SalablePlanController {
    @PostMapping("/salable-plans")
    @Operation(summary = "创建可售套餐")
    public void create() {}
}
''',
        "SalablePlanQueryController.java": '''@Tag(name = "可售套餐订单内部查询")
class SalablePlanQueryController {
    @GetMapping("/salable-plan-orders")
    @Operation(summary = "查询可售套餐订单")
    public void query() {}
}
''',
        "SalablePlanRecoveryJob.java": '''/** 可售套餐恢复任务。 */
@JobHandler("plans.recover")
class SalablePlanRecoveryJob extends AbstractJobHandler {
    protected void doExecute(String param) {}
}
''',
    }
    sources.update({
        "SoftwareSaleFulfillmentController.java": '''@Tag(name = "软件销售履约接口")
class SoftwareSaleFulfillmentController {
    @PostMapping("/software-sales/fulfillment")
    public void subscribe() {}
}
''',
        "SoftwareSaleFulfillmentJob.java": '''/** 软件销售履约状态更新任务。 */
@JobHandler("software-sale.fulfillment")
class SoftwareSaleFulfillmentJob extends AbstractJobHandler {
    protected void doExecute(String param) {}
}
''',
    })
    for name, source in sources.items():
        (tmp_path / name).write_text(source, encoding="utf-8")
    _git(tmp_path)
    result = scan(tmp_path, entry_only=True)
    vehicle = [entry for entry in result.entries if "VehicleUsage" in entry.file]
    plan = [entry for entry in result.entries if "SalablePlan" in entry.file]
    assert {entry.module for entry in vehicle} == {"用量"}
    assert {entry.module for entry in plan} == {"套餐"}
    assert len(vehicle) == 2 and len(plan) == 3
    software = [entry for entry in result.entries if "SoftwareSale" in entry.file]
    assert len(software) == 2 and {entry.module for entry in software} == {"软件销售"}


def test_calls_ignore_literal_sql_and_comment_calls_without_removing_real_call() -> None:
    from toolkit.biz_flow_doc_generator.discovery import _calls, _qualified_calls
    body = '''def run():
    value = "INSERT INTO accounts(email) VALUES (?) fake.remote() helper()"
    other = """helper() literal.insert()"""
    # other.remote() helper()
    helper()
    connection.execute(value)
    connection.commit()
'''
    assert "accounts" not in _calls(body)
    assert _calls(body).count("helper") == 1
    assert _qualified_calls(body) == [("connection", "execute"), ("connection", "commit")]


def test_module_labels_remove_registration_channels_and_keep_business_actions() -> None:
    from toolkit.biz_flow_doc_generator.discovery import _module_label
    labels = {
        "车辆销售状态公开接口": "车辆销售状态",
        "SIM状态内部查询": "SIM状态查询",
        "运营商配置内部同步": "运营商配置同步",
        "实名结果公开回调": "实名结果回调",
        "设备滞留回收任务": "设备滞留回收",
        "套餐订单状态变更定时任务": "套餐订单状态变更",
    }
    for label, expected in labels.items():
        source = f'@Tag(name = "{label}")\nclass Business {{}}'
        assert _module_label(source, 2)[0] == expected
