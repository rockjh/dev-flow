"""Behavior assertions against committed source, including rejection boundaries."""
import subprocess

from toolkit.biz_flow_doc_generator.discovery import scan
from toolkit.biz_flow_doc_generator.evidence import collect_evidence


def project(tmp_path, files):
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    for args in (("init", "-q"), ("add", "."),
                 ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    return tmp_path


def test_selected_deep_behavior_retains_caught_calls_and_void_completion(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
class Controller {
  Service service;
  @PostMapping("/orders") void receive() {
    try { service.process(); } catch (RuntimeException e) { service.recover(); }
  }
  @GetMapping("/other") String other() { return "other"; }
}
class Service {
  void process() { calculate(); }
  void calculate() { }
  void recover() { }
}
'''})
    shallow = scan(root, entry_only=True)
    entry_id = next(e.entry_id for e in shallow.entries if "/orders" in e.identifier)
    assert not shallow.unresolved
    facts = collect_evidence(scan(root, entry_ids={entry_id}))[entry_id]
    assert {"process", "calculate", "recover"} <= {c["details"]["method"] for c in facts["calls"]}
    assert all("other" != c["details"]["method"] for c in facts["calls"])
    assert any(o["type"] == "normal_completion" and o["phase"] == "entry" for o in facts["outcomes"])
    assert facts["persistence_actions"] == []


def test_execute_is_bound_and_callback_runs_at_actual_invocation(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
class Controller {
  Wrapper wrapper;
  Service service;
  @PostMapping("/orders") void receive() { wrapper.execute(() -> service.process()); }
}
class Wrapper { void execute(Runnable task) { before(); task.run(); after(); }
  void before() { } void after() { }
}
class Service { void process() { } }
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    methods = [c["details"]["method"] for c in facts["calls"]]
    assert methods.index("before") < methods.index("process") < methods.index("after")
    assert facts["persistence_actions"] == []
    assert not facts["gaps"]


def test_memory_names_and_sql_comments_are_not_storage(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
import java.util.Map;
class Controller {
  Map<String,String> values;
  @GetMapping("/orders") String receive() {
    // UPDATE secret_table SET state = 1
    values.put("key", "value");
    return values.get("key");
  }
}
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert facts["persistence_actions"] == []
    assert not any(g["code"].startswith("PERSISTENCE") for g in facts["gaps"])


def test_ambiguous_binding_is_a_gap_not_a_random_implementation(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
interface Service { void process(); }
class One implements Service { public void process() { } }
class Two implements Service { public void process() { } }
class Controller { Service service;
  @PostMapping("/orders") void receive() { service.process(); }
}
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert any(g["code"] == "CALL_BINDING_AMBIGUOUS" for g in facts["gaps"])
    assert all(c["details"]["target"] not in {"One.process()", "Two.process()"} for c in facts["calls"])


def test_jpa_generic_repository_maps_entity_table_and_save_without_commit_claim(tmp_path):
    root = project(tmp_path, {"pom.xml": '''<project><dependencies><dependency>
<groupId>org.springframework.data</groupId><artifactId>spring-data-jpa</artifactId><version>3.3.0</version>
</dependency></dependencies></project>''', "Controller.java": '''
import org.springframework.data.jpa.repository.JpaRepository;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.Column;
class Controller { OrderRepository repository;
  // 保存订单
  @PostMapping("/orders") void receive(Order order) { repository.save(order); }
}
interface OrderRepository extends JpaRepository<Order, Long> {}
/** 订单记录 */
@Entity @Table(name="biz_order")
class Order { @Column(name="order_state") String state; }
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert not facts["gaps"]
    action = facts["persistence_actions"][0]
    assert action["details"]["resource_name"] == "biz_order"
    assert action["details"]["operation"] == "save"
    assert action["details"]["fields"] == ["order_state"]
    assert action["details"]["display_name"] == "订单记录"
    assert any(o["type"] == "write_attempt" and action["fact_id"] in o["evidence_refs"] for o in facts["outcomes"])
    assert all(o["type"] != "transaction_commit" for o in facts["outcomes"])


def test_querydsl_update_keeps_physical_fields_predicates_and_row_check(tmp_path):
    root = project(tmp_path, {"pom.xml": '''<project><dependencies><dependency>
<groupId>com.querydsl</groupId><artifactId>querydsl-jpa</artifactId><version>5.1.0</version>
</dependency></dependencies></project>''', "Controller.java": '''
import com.querydsl.jpa.impl.JPAUpdateClause;
import com.querydsl.core.types.dsl.EntityPathBase;
import com.querydsl.core.types.dsl.StringPath;
import com.querydsl.core.types.dsl.NumberPath;
import javax.persistence.Entity;
import javax.persistence.Table;
import javax.persistence.Column;
import javax.persistence.EntityManager;
class Controller { QOrder order; EntityManager entityManager;
  // 领取订单
  @PostMapping("/claim") boolean claim(long id) {
    long rows = new JPAUpdateClause(entityManager, order)
      .set(order.state, "CLAIMED").where(order.id.eq(id).and(order.state.eq("READY"))).execute();
    return rows == 1;
  }
}
@Entity @Table(name="biz_order")
class Order { @Column(name="order_id") long id; @Column(name="order_state") String state; }
class QOrder extends EntityPathBase<Order> {
  StringPath state = createString("state");
  NumberPath<Long> id = createNumber("id", Long.class);
}
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert not facts["gaps"]
    action = facts["persistence_actions"][0]["details"]
    assert action["resource_name"] == "biz_order" and action["fields"] == ["order_state"]
    assert 'order.id.eq(id).and(order.state.eq("READY"))' in action["predicate"]
    assert "rows" in action["affected_rows"]
    assert any("rows == 1" in o["details"]["expression"] for o in facts["outcomes"])


def test_method_reference_iteration_is_sync_and_executor_background_follows_entry_return(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
import java.util.List;
import java.util.concurrent.ExecutorService;
class Controller { Service service; ExecutorService executor;
  // 处理订单
  @PostMapping("/orders") void receive(List<String> orders) {
    orders.forEach(service::process);
    executor.submit(() -> service.process("background"));
  }
}
class Service { void process(String order) {} }
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert not facts["gaps"]
    assert any(b["type"] == "synchronous_iteration" for b in facts["branches"])
    assert any(e["type"] == "task_submission" for e in facts["effects"])
    entry_returns = [i for i,s in enumerate(facts["flow"]) if s["phase"] == "entry" and s["kind"] == "outcome"]
    backgrounds = [i for i,s in enumerate(facts["flow"]) if s["phase"] == "background"]
    assert max(entry_returns) < min(backgrounds)
    assert any(o["type"] == "background_result" and not o["details"]["observed_by_entry"] for o in facts["outcomes"])


def test_stored_callback_is_not_executed_and_conditional_callback_keeps_control(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
class Controller { Wrapper wrapper; Service service;
  // 接收订单
  @PostMapping("/orders") void receive(boolean enabled) {
    wrapper.store(() -> service.never());
    wrapper.execute(enabled, () -> service.process());
  }
}
class Wrapper { Runnable task;
  void store(Runnable value) { task = value; }
  void execute(boolean enabled, Runnable value) { if (enabled) { value.run(); } }
}
class Service { void never() {} void process() {} }
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert not any(c["details"]["method"] == "never" for c in facts["calls"])
    call = next(c for c in facts["calls"] if c["details"]["method"] == "process")
    assert any(b["fact_id"] in call["conditions"] for b in facts["branches"])


def test_constructor_qualifier_inheritance_overload_and_chain_bind_declarations(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
interface Port { void process(String value); }
@Service("one") class One implements Port {
  public void process(String value) {} public void process(long value) {}
  One next() { return this; }
}
@Service("two") class Two implements Port { public void process(String value) {} }
class Base { String invoke() { return "order"; } }
class Controller extends Base {
  Port port;
  Controller(@Qualifier("one") Port port) { this.port = port; }
  // 处理订单
  @PostMapping("/orders") void receive() { port.process(invoke()); One local = new One(); local.next().process("order"); }
}
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert not facts["gaps"]
    bound = [c["details"]["target"] for c in facts["calls"] if c["details"]["method"] == "process"]
    assert bound == ["One.process(java.lang.String)", "One.process(java.lang.String)"]
    assert any(s["declaration_id"].startswith("Controller.Controller(") for s in facts["sources"])


def test_finally_is_after_catch_and_memory_state_is_a_separate_result(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
class Controller { boolean recorded;
  // 接收订单
  @PostMapping("/orders") void receive() {
    try { work(); } catch (RuntimeException error) { recover(); } finally { recorded = true; }
  }
  void work() { throw new RuntimeException("failed"); }
  void recover() {}
}
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    cleanup = next(b for b in facts["branches"] if b["type"] == "finally")
    original = next(b for b in facts["branches"] if b["type"] == "try_statement")
    end = next(i for i,s in enumerate(facts["flow"]) if s["fact_id"] == original["fact_id"] and s["kind"] == "control_end")
    start = next(i for i,s in enumerate(facts["flow"]) if s["fact_id"] == cleanup["fact_id"] and s["kind"] == "control_start")
    assert start > end
    assert any(e["type"] == "memory_state_change" for e in facts["effects"])
    thrown = next(o for o in facts["outcomes"] if o["type"] == "throw")
    assert thrown["details"]["possible_handlers"] and not thrown["details"]["observed_by_entry"]


def test_unknown_contract_and_budget_never_prove_no_persistence(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
class Controller { Unknown storage;
  // 查询订单
  @GetMapping("/orders") void receive() { storage.lookup(); }
}
'''})
    result = scan(root)
    facts = next(iter(collect_evidence(result).values()))
    assert facts["coverage"]["persistence"] == "unknown" and facts["gaps"]
    bounded = next(iter(collect_evidence(result, budget=1).values()))
    assert any(g["code"] == "ANALYSIS_BUDGET_EXCEEDED" for g in bounded["gaps"])


def test_loop_condition_and_update_keep_execution_order(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
class Controller {
  // 处理订单
  @PostMapping("/orders") void receive() {
    for (start(); ready(); advance()) { process(); }
    do { process(); } while (ready());
  }
  void start() {} boolean ready() { return true; } void advance() {} void process() {}
}
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert [c["details"]["method"] for c in facts["calls"]] == ["start", "ready", "process", "advance", "process", "ready"]


def test_transaction_annotation_is_not_proof_of_activation_or_commit(tmp_path):
    root = project(tmp_path, {"Controller.java": '''
import org.springframework.transaction.annotation.Transactional;
class Controller {
  // 保存订单
  @PostMapping("/orders") @Transactional void receive() {}
}
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert any(g["code"] == "TRANSACTION_ACTIVATION_UNRESOLVED" for g in facts["gaps"])
    assert all(o["type"] != "transaction_commit" for o in facts["outcomes"])
