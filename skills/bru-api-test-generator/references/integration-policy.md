# 璺ㄦ湇鍔￠泦鎴愮瓥鐣?

褰撳満鏅法瓒婃湇鍔¤竟鐣岋紝鎴栦娇鐢ㄦ秷鎭€佹暟鎹瓨鍌ㄣ€佺紦瀛樸€佽皟搴﹀櫒銆侀厤缃腑蹇冦€佽澶囩綉鍏虫垨鍏朵粬瑙傚療/鎺у埗缁勪欢鏃讹紝闃呰鏈弬鑰冦€?
## Boundaries

璇峰垎绂讳互涓嬭亴璐ｏ細

1. `common/clients/` 璋冪敤鍏紑鎴栬幏鎵瑰噯鐨勬祴璇?绠＄悊鎺ュ彛銆?2. `common/builders/` 鏄惧紡鏄犲皠鍙鐢ㄧ殑姝ｅ紡鍗忚杞借嵎銆?3. `common/repositories/` 璐熻矗鍙傛暟鍖栧彧璇绘煡璇㈠拰绋冲畾璁板綍鏄犲皠銆?4. `common/controls/` 璐熻矗榛樿鍏抽棴銆佺粡鎺堟潈涓斿彲閫嗙殑鎺у埗鎿嶄綔銆?5. `common/integrations/` 涓哄彂鐜板埌鐨勭粍浠剁被鍨嬫彁渚涢€氱敤閫傞厤鍣ㄣ€?6. `common/fixtures/` 璐熻矗閫傞厤鍣ㄧ敓鍛藉懆鏈熴€佹巿鏉冦€佸揩鐓у拰闅旂銆?7. `common/assertions/` 姣旇緝鍗忚銆佹秷鎭€佹寔涔呭寲鍜屽彲瑙傚療璇佹嵁銆?8. 鍦烘櫙妯″潡浠呰〃杈惧満鏅姩浣溿€佹槧灏勩€佹柇瑷€鍜屾竻鐞嗐€?
閫氱敤妯″潡鎺ユ敹鍙戠幇鍒扮殑閰嶇疆鍜屽満鏅槧灏勩€備笉寰楀祵鍏ラ」鐩悕绉般€佷笟鍔℃帴鍙ｃ€佽〃銆佷富棰樸€侀厤缃敭銆佸嚟鎹€佹灇涓俱€佺姸鎬佹垨鐜鍦板潃銆傚鐢ㄥ凡鎵瑰噯涓斿浐瀹氱増鏈殑渚濊禆锛涗笉寰楁倓鎮勬柊澧炲鎴风搴撱€?
鍙疄渚嬪寲骞堕妫€鍦烘櫙澹版槑鐨勬湇鍔″拰缁勪欢銆傚鍏ユ垨鏀堕泦鏈熼棿涓嶅緱鏋勯€犻€傞厤鍣ㄣ€佸缓绔嬭繛鎺ャ€佽闃呫€佹鏌ヨ繘绋嬫垨鎵ц鍋ュ悍妫€鏌ャ€?
## HTTP 涓?RPC

- 浠庡彂鐜扮粨鏋滃拰娲诲姩鐜涓彇寰楀熀纭€鍦板潃銆佷笂涓嬫枃璺緞銆佸崗璁€佽璇併€佹爣澶淬€佸簭鍒楀寲銆佽秴鏃跺拰 TLS銆?- 鍙鍐掔儫浣跨敤鍋ュ悍妫€鏌ャ€丱penAPI銆佹煡璇㈡垨淇濊瘉鏈懡涓殑璇锋眰銆?- Direct `requests`, `httpx`, and `urllib` calls use an explicit positive timeout. `urlopen` with request data is a write and is forbidden in smoke. An arbitrary fixture method such as `client.get()` is not transport proof.
- A read-only RPC smoke call goes through a common `read_only_rpc` adapter that declares `READ`/`RPC`, a source anchor from discovery, one bounded non-write operation, and a returned real result.
- 鍒嗗埆楠岃瘉姝ｅ紡浼犺緭鐘舵€佸拰璁捐瀹氫箟鐨勪笟鍔＄粨鏋溿€?- Record `verified=True` only from a validation expression that consumes that call's result. HTTP smoke status is an integer and 5xx always fails.
- 浼犺緭鎴愬姛浣嗕笟鍔＄粨鏋滃け璐ヤ粛瑙嗕负澶辫触銆?- Do not retry a non-idempotent call unless design declares the idempotency semantics and the formal protocol declares the key shape.
- Redact credentials and sensitive payload fields in diagnostics while retaining method, non-secret target identity, correlation key name, status, and bounded response summary.

## 娑堟伅

瀵逛簬鍙戠幇鍒扮殑浠讳綍浠ｇ悊鎴栫綉鍏筹細

1. create a unique run/scenario consumer identity;
2. subscribe or capture starting position before the business action and wait for readiness;
3. observe only a bounded offset/time window;
4. match with design-defined correlation fields whose transport shape comes from the formal protocol;
5. assert channel identity, key/headers, schema/version, and relevant business fields;
6. close deterministically after success or failure.

鍙戝竷榛樿鍏抽棴銆傚惎鐢ㄩ渶瑕佹潵婧愮‘璁ょ殑妯℃嫙濂戠害銆佹瘡娆¤繍琛屾巿鏉冿紝浠ュ強閰嶇疆鐨勪粎娴嬭瘯鐩爣鍓嶇紑鎴栫簿纭厑璁稿垪琛ㄣ€傞櫎闈炴湁鏉ユ簮鏀寔鐨勬祴璇曞绾︽槑纭姹備笖鐢ㄦ埛鎺堟潈浜嗙‘鍒囨祴璇曠幆澧冿紝鍚﹀垯鎷掔粷淇濈暀娑堟伅銆佹棤闄愬埗閫氶厤绗︽垨涓氬姟鐩爣銆?
For Kafka-like logs, wait for assignment and capture starting offsets. For MQTT-like brokers, use a unique client ID, protocol-defined QoS/TLS/session behavior, and deterministic disconnect. For other systems, preserve the same readiness, bounded observation, exact correlation, and cleanup invariants without forcing Kafka or MQTT terminology into generated code.

## 鏁版嵁搴撹瀵?
瑙傚療浠撳簱鍙毚闇插弬鏁板寲璇诲彇鏂规硶銆備娇鐢ㄧ浉鍚屽満鏅叧鑱旈敭骞朵緷鎹崟璋冩埅姝㈡椂闂磋疆璇紝鎶ュ憡鏈€鍚庤瀵熷埌鐨勮褰曘€傛柇瑷€鎵€鏈夋潈銆佽姹傜殑涓氬姟鐘舵€?瀛楁鍙婄浉鍏冲叧绯汇€?
A message proves publication; a database record proves persistence or consumption. When both are evidence sources, assert them independently, then compare every shared design/protocol-defined field. Define explicit mappings for different field names or representations. A time-range-only row, broad message match, or equal correlation ID alone is insufficient.

Database control follows [discovery-and-control-policy.md](discovery-and-control-policy.md). Keep control operations out of read repositories and test entrypoints. Multi-table setup is an ordered list of individually snapshotted, parameter-bound, exact single-row operations; restore attempted operations in reverse order and verify every restored state. Never use control SQL as the business action under test or to manufacture the final asserted result.

## 缂撳瓨瑙傚療

Expose the smallest source-required read surface, such as exact-key value, existence, TTL, or exact hash fields. Cache evidence is secondary when a public API, event, operation record, or database provides stronger business evidence.

Load endpoint, credentials, logical database/index, TLS, serialization, and test prefix from the active environment. Bounded waits use monotonic deadlines and last-state diagnostics.

If cleanup is necessary, a fixture may delete only an exact scenario-owned key under the configured test prefix. Reject wildcard deletion, namespace-wide clearing, database flushing, and deletion of pre-existing business keys.

## 璋冨害鍣ㄥ拰浣滀笟

Prefer an approved trigger or admin interface discovered in source. Correlate trigger arguments, execution record, and downstream state. A scheduler acknowledgement does not prove the job's business result.

If time advancement or expiry simulation is needed, use a source-confirmed clock/configuration control or the controlled SQL policy. Snapshot the original state, isolate the target from other scenarios, trigger or await the job with a bounded deadline, verify its result, and restore the state.

Do not invoke an uncontrolled production schedule, alter global time, or call an undocumented scheduler endpoint.

## 鍔ㄦ€侀厤缃€佹ā鎷熷拰鏁呴殰娉ㄥ叆

- Use only controls found in application source/configuration and present in the scenario matrix.
- Record the control scope, affected component, correlation/isolation method, prior value, intended value, and restoration evidence.
- Default controls off. Enabling requires the exact target test environment and per-run authorization.
- Apply controls as narrowly as the platform permits; reject global changes when unrelated traffic can be affected.
- Snapshot before mutation, verify that the application consumed the change, and restore in guaranteed cleanup.
- A mock response or injected failure must still be verified through the public business result and downstream evidence relevant to the scenario.

## 杩愯鏃惰瘖鏂?
Every adapter reports only non-secret endpoint identity, component type, correlation-key name, bounded deadline, and last observed state. Never include credential values, complete connection strings, authorization headers, raw sensitive messages, or full database rows.

Control and endpoint evidence is adapter-owned. Record it immediately after the real external call in the same straight-line block, derive endpoint status, summary, and verification from the returned object, and pass the same scenario-owned correlation value in a resource/key/selector or request-payload argument to both a write operation and its control event. Logging, headers, or tracing metadata do not establish isolation. Scenario steps and test entrypoints cannot emit these events.

Connection or runtime failures after preflight are failed smoke/business checks. They cannot be converted to `pending_environment`, `contract_blocked`, `skip`, or `xfail`.

Likewise, a callable business entry that returns the wrong state, omits a downstream event, leaves a scheduler/consumer result absent, or reports transport success with an incorrect business envelope is a product/runtime failure with evidence. It is not `environment_missing`. Continue recording the remaining independently safe observations and cleanup before failing the scenario.
