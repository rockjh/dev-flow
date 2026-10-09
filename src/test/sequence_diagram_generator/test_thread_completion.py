"""Fixed standard-library thread contracts; no target code is executed."""
import pytest
from toolkit.sequence_diagram_generator.models import FlowModel
from toolkit.sequence_diagram_generator.validation import FlowValidator
from test_boundaries import analyze


@pytest.mark.parametrize("spawn", ["std::thread::spawn", "start"])
def test_rust_direct_join_tracks_real_dispatch_parallel_region_and_wait(spawn):
    source = "use std::thread::spawn as start; fn worker()->i32 { if true {return 1;} 2 } fn flow()->i32 { let h = " + spawn + "(worker); let n = 3; let result = h.join(); n }"
    scope = analyze("rust", source)
    assert not scope.gaps, scope.gaps
    parallel = next(c for c in scope.controls if c.kind == "par")
    dispatch = next(s for s in scope.steps if s.kind == "dispatch")
    waiting = next(s for s in scope.steps if s.kind == "wait")
    assert waiting.dependencies == (dispatch.step_id,)
    assert waiting.completion == "observed" and "may be Err" in waiting.label
    assert parallel.evidence_ids == dispatch.evidence_ids
    assert any(e.kind == "fork" and e.source_id == parallel.control_id for e in scope.control_flow)
    assert any(o.resolution == "summary" and o.receiver == "std::thread::JoinHandle.join" for o in scope.external)
    report = FlowValidator().validate_model(FlowModel((scope,), "", ""))
    assert report.passed, [r for r in report.rules if not r.passed]


@pytest.mark.parametrize("source", [
    "fn worker(){} fn flow(){let h=std::thread::spawn(worker); if true {h.join();}}",
    "fn worker(){} fn flow(){let h=std::thread::spawn(worker); consume(h);}",
    "fn worker(){} fn flow(){let h=std::thread::spawn(worker); let h=other(); h.join();}",
    "fn worker(){} fn flow(){let h=std::thread::spawn(||worker()); h.join();}",
    "async fn worker(){} fn flow(){let h=std::thread::spawn(worker); h.join();}",
])
def test_rust_unbound_thread_handle_does_not_claim_completion(source):
    scope = analyze("rust", source)
    assert any(g.critical for g in scope.gaps)
    assert not any(s.kind == "wait" and s.receiver == "std::thread::JoinHandle.join" for s in scope.steps)


def test_go_direct_channel_receive_observes_value_without_claiming_goroutine_exit():
    source = "package main\nfunc producer(out chan bool){println(1);out<-true}\nfunc flow() bool {done:=make(chan bool);go producer(done);println(2);value:=<-done;return value}"
    scope = analyze("go", source)
    assert not scope.gaps, scope.gaps
    assert any(c.kind == "par" for c in scope.controls)
    waiting = next(s for s in scope.steps if s.kind == "wait")
    dispatch = next(s for s in scope.steps if s.kind == "dispatch")
    assert waiting.dependencies == (dispatch.step_id,) and waiting.completion == "observed"
    assert "goroutine exit not claimed" in waiting.label and len(waiting.evidence_ids) == 2
    assert any(s.kind == "dispatch" and "send initiated" in s.label and s.completion == "dispatched" for s in scope.steps)
    report = FlowValidator().validate_model(FlowModel((scope,), "", ""))
    assert report.passed, [r for r in report.rules if not r.passed]


@pytest.mark.parametrize("middle", ["close(done);", "consume(done);", "if true {value:=<-done;println(value)};"])
def test_go_unknown_channel_lifecycle_does_not_prove_completion(middle):
    scope = analyze("go", "package main\nfunc producer(out chan bool){out<-true}\nfunc flow(){done:=make(chan bool);go producer(done);" + middle + "}")
    assert any(g.critical for g in scope.gaps)
    assert not any(s.kind == "wait" and "goroutine exit not claimed" in s.label for s in scope.steps)
