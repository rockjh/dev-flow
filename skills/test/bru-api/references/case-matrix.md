# API 鐢ㄤ緥鐭╅樀

鏍规嵁 OpenAPI 鐢熸垚鍗忚鍐崇瓥锛屾牴鎹凡瀹℃牳鐨勮璁¤鍒欑敓鎴愪笟鍔″喅绛栥€傛簮浠ｇ爜鍜屾帰閽堣瘉鎹彧鑳界敤浜庣‘璁ゆ墽琛屾敮鎸佹垨鎶ュ憡瀹炵幇鍋忓樊銆傛瘡涓鐐归兘蹇呴』瑕嗙洊鍏釜绫诲埆銆傞€傜敤鍐崇瓥闇€鍏宠仈涓撶敤鐢ㄤ緥锛涘凡纭涓嶉€傜敤鐨勫喅绛栧繀椤荤粰鍑哄叿浣撳師鍥犮€?
| Category | Evidence | Required coverage |
| --- | --- | --- |
| `success` | reviewed design rule for every reachable operation | at least one distinct success case |
| `authentication` | reviewed design rule; OpenAPI security only describes request shape | missing and invalid credentials with the design-defined status/envelope |
| `authorization` | reviewed design permissions and conditions; OpenAPI security is protocol context | authenticated but forbidden cases defined by design |
| `validation` | required, enum, pattern, min/max, length, format, media type | each declared invalid or boundary class |
| `query` | reviewed design behavior plus OpenAPI parameter structure | boundaries, filters, sorting, combinations, empty results, invalid page/pageSize |
| `file` | multipart/binary schema and explicit contract constraints | missing/empty file, extension, MIME, and size cases where proven |
| `business_error` | design rules and documented business error semantics | one case per documented business result |
| `safety` | design rules for idempotency, concurrency, repeat submission | declared design behavior |

## 瑕嗙洊閰嶇疆

`contract-draft` 浠呯敓鎴愬彲鐢?OpenAPI 鍜岄」鐩害鏉熷簱鐩存帴璇佹槑璇锋眰褰㈢姸鍙婇鏈熶紶杈撹涓虹殑鐢ㄤ緥銆傚嚭鐜?`manual_confirmation` 鍗抽樆鏂敓鎴愶紱搴斿厛瑙ｅ喅璁捐姝т箟锛屼笉寰楀熀浜庝笉瀹屾暣妯″瀷鎵ц鏃犲叧涓氬姟鐢ㄤ緥銆?
`full-matrix` 鐢熸垚 OpenAPI 鍗忚绾︽潫鎴栧凡瀹℃牳璁捐瑙勫垯鏀寔鐨勫叏閮ㄩ€傜敤鍦烘櫙銆傚畨鍏ㄩ厤缃敤浜庡噯澶囪姹傦紝鎺㈤拡璇佹嵁鐢ㄤ簬鎶ュ憡鍋忓樊銆傜湡瀹炲満鏅嫢缂哄皯瓒冲璁捐璇佹嵁鏉ュ畾涔夌簿纭笟鍔＄敤渚嬶紝浠嶅睘浜庨樆鏂€х己鍙ｃ€?
`verified` 涓嶆槸鐢熸垚閰嶇疆銆傚彧鏈夐粯璁ょ殑鍏ㄦā鍧楄寖鍥撮€氳繃涓ユ牸瀵硅处鍜屾墽琛屽悗鎵嶅彲浣跨敤銆?
## 璁よ瘉涓庡繀闇€璇锋眰澶?

涓嶈鏍规嵁 `/admin` 璺緞鎺ㄦ柇璁よ瘉鎴栨巿鏉冦€傝鍖哄垎浠ヤ笅閰嶇疆锛?
```yaml
required-tenant-context:
  type: required-header
  header: X-Tenant-Id
  probe_result:
    missing_header_status: 400
    reason: The application rejects a missing tenant context Header

auth-token:
  type: authentication
  header: Authorization
  probe_result:
    no_token_status: 401
    invalid_token_status: 401
```

浠呰繍琛屼竴娆′唬琛ㄦ€х殑缂哄皯浠ょ墝鎺㈤拡鍜屼竴娆℃棤鏁堜护鐗屾帰閽堬紝鐢ㄤ簬鎶ュ憡瀹炵幇鍋忓樊銆傚湪璇佹嵁涓繚鐣欏疄闄?HTTP 鐘舵€佸拰鍝嶅簲淇″皝锛涢櫎闈炲凡瀹℃牳璁捐鏄庣‘澹版槑锛屽惁鍒欎笉寰楀皢瑙傛祴鍊煎鍒朵负棰勬湡鍊笺€?
蹇呴渶鐨勫簲鐢ㄨ姹傚ご涓嶈嚜鍔ㄦ瀯鎴愯璇佽瘉鎹€備娇鐢?OpenAPI 鍜屾墽琛岄厤缃噯澶囪姹傦紝骞朵緷鎹凡瀹℃牳璁捐瑙勫垯纭畾璁よ瘉琛屼负锛涘皢宸茬‘璁ょ殑涓嶉€傜敤鎯呭喌鍗曠嫭璁板綍銆?
鎺堟潈琛屼负蹇呴』鏈夊凡瀹℃牳鐨勮璁¤鍒欍€侽penAPI 瀹夊叏鎵╁睍鍜?`security-profile.yaml` 鍙敤浜庡噯澶囧嚟鎹紝婧愪唬鐮佹敞瑙ｅ拰鎺㈤拡鍙敤浜庢姤鍛婂亸宸€傚惁鍒欏簲浣跨敤濡備笅宸茬‘璁ょ殑涓嶉€傜敤鍐崇瓥锛?
```yaml
authorization:
  applicable: false
  status: confirmed
  reason: reviewed design declares no authorization branch for this operation
```

## 楠岃瘉

涓洪€傜敤鐨勭害鏉熷垎鍒敓鎴愮敤渚嬶細

- missing required query, path, Header, and body fields;
- illegal enum values and pattern mismatches;
- values immediately outside minimum/maximum and minLength/maxLength;
- invalid declared formats;
- wrong Content-Type when the endpoint declares a rejection response.

瀵逛簬瀵硅薄绫诲瀷鏌ヨ鍙傛暟锛岄獙璇佹鏋剁粦瀹氾紝骞舵寜鏂囨。搴忓垪鍖栨垨灞曞紑瀛楁銆備笉寰楀皢瀵硅薄浣滀负鏈В閲婄殑鏍囬噺鍙戦€併€?
## 鏌ヨ涓庢枃浠剁敤渚?

鏌ヨ绔偣搴旇鐩?page/pageSize 杈圭晫銆佽繃婊ゅ€笺€佹帓搴忓€笺€佺粍鍚堟潯浠躲€佺┖缁撴灉鍜屾棤鏁堝垎椤佃緭鍏ャ€備娇鐢?OpenAPI 涓殑鐪熷疄鍙傛暟鍚嶏紝涓嶅緱铏氭瀯閫氱敤鍒嗛〉 API銆?
瀵逛簬 multipart 鎴栦簩杩涘埗杈撳叆锛屽缁堣鐩栫己灏戝繀闇€鏂囦欢鐨勬儏鍐点€備粎褰?OpenAPI 鎴栧凡瀹℃牳璁捐澹版槑鐩稿簲绾︽潫鏃讹紝鎵嶈鐩栫┖鏂囦欢銆佹棤鏁堟墿灞曞悕銆佹棤鏁?MIME 鍜岃秴澶ф枃浠躲€傚す鍏峰簲鏀惧湪鎵ц鐜鎴栧す鍏风洰褰曚腑锛屼笉寰楀啓鍏ラ厤缃€?
## 涓氬姟閿欒涓庡畨鍏?

涓氬姟閿欒鍙兘渚濇嵁宸插鏍哥殑璁捐瑙勫垯鐢熸垚銆傛簮浠ｇ爜寮傚父澶勭悊鍣ㄥ拰杩愯鏃惰娴嬪彲鐢ㄤ簬鎶ュ憡瀹炵幇鍋忓樊锛屼絾缁濅笉鑳芥嵁姝ゅ垱寤轰笟鍔￠鏈熴€?
浠呭湪璁捐澹版槑骞傜瓑鎬с€佸苟鍙戞垨閲嶅鎻愪氦琛屼负鏃剁敓鎴愬畨鍏ㄧ敤渚嬨€侶TTP 鏂规硶鏈韩涓嶆槸璇佹嵁銆?
## 璁捐瑙勫垯鏍囪

宸插鏍哥殑 Markdown 璁捐鏂囨。涓紝姣忎釜 `METHOD /path` 灏忚妭鍙寘鍚竴涓垨澶氫釜鏄庣‘瑙勫垯銆傛瘡鏉¤鍒欎娇鐢ㄤ竴涓?`Rule ID`锛涘悓涓€绔偣瀛樺湪澶氫釜缁撴灉鏃堕噸澶嶆爣璁板潡锛?
```markdown
## POST /jobs
Rule ID: JOBS_ACCEPTED
Scenario: success
Condition: request is valid
Request: {body: {jobType: reconcile}}
Async: true
HTTP status: 202
Acceptance status: accepted
Final status: completed
State: completed
Business code: 0
Assert: $.status = completed
```

瀵逛簬鏈夊簭鐨勫璇锋眰瑙勫垯锛屽彧澹版槑涓€娆″畬鏁村彲鎵ц娴佺▼銆傛瘡涓楠ゅ紩鐢ㄥ凡瀹℃牳鐨勮鍒?ID锛沜aptures 灏嗗悕绉版槧灏勫埌鍝嶅簲 JSON 璺緞锛屽苟涓旀瘡涓?`uses` 鍚嶇О閮藉繀椤诲嚭鐜板湪璇ヨ鍒欑殑璇锋眰涓細

```markdown
Test Flow: {id: JOB_FLOW, steps: [{rule_id: JOB_ACCEPTED, operation: submit, capture: {job_id: "$.jobId"}}, {rule_id: JOB_COMPLETED, operation: poll, uses: [job_id]}]}
```

閲嶅鎻愪氦鎴栭噸璇曞簲浣跨敤涓嶅悓鐨勮鍒?ID銆傞噸璇曟楠や娇鐢?`operation: retry`銆傞櫎闈為」鐩彁渚涚粡鎺堟潈鐨勬晠闅滄敞鍏ユ搷浣滃強宸查獙璇佺殑鎭㈠/娓呯悊鎿嶄綔锛屽惁鍒欏閮ㄦ晠闅滆鍒欎細琚樆鏂€傚悕涓?`fault-inject`銆乣inject-failure`銆乣mock-failure` 鎴?`dependency-failure` 鐨勬楠や粎鏄璁℃爣绛撅紝涓嶆槸鎵ц璇佹嵁銆傛墍鏈夊紩鐢ㄧ殑鎿嶄綔浠嶉渶鍏峰 OpenAPI 绔偣鍜岃璁¤鍒欍€?
鏀寔鐨勬爣璁板寘鎷?`Rule ID`銆乣Scenario`銆乣Condition`銆乣Request`銆乣Async`銆乣HTTP status`銆乣Business code`銆乣State`銆乣State transition`銆乣Acceptance status`銆乣Final status`銆乣Side effect`銆乣Idempotency`銆乣Retry`銆乣Concurrency`銆乣External failure` 鍜?`Assert`銆傛爣璁板€间娇鐢?YAML 鏍囬噺鎴栧鍣ㄧ被鍨嬨€傛爣璁板彧鏄姞閫熸牸寮忥紝骞堕潪璁捐瑕佹眰锛氭鏂囥€佽〃鏍笺€佷唬鐮?curl 鍧椼€佹湁搴忔楠ゅ拰楠屾敹娓呭崟浼氬厛琚鍏ヨ璁＄悊瑙ｇ煩闃点€傛瘡鏉℃彁鍙栦簨瀹為兘鏍囪涓?`explicit`銆乣derived` 鎴?`unknown`锛屽苟闄勬潵婧愭憳褰曞拰鎺ㄥ銆傛瘡涓潪鎴愬姛鍒嗘敮鍙婂寘鍚鏉¤鍒欑殑绔偣閮介渶瑕佸彲鎵ц璇锋眰鏄犲皠锛涜嫢姝ｆ枃鏈缓绔嬫槧灏勶紝搴斿皢鍊欓€夐」淇濈暀鍦ㄥ緟纭鐘舵€侊紝涓嶅緱浠庢簮浠ｇ爜鎴栬繍琛屾椂鍊熺敤鍊笺€?
寮傛瑙勫垯蹇呴』鍚屾椂澹版槑鎺ユ敹鐘舵€佸拰鏈€缁堢姸鎬侊紝骞舵彁渚涙湁鐣岃疆璇?瀵硅处鏈哄埗鍙婃槑纭殑缁堟绛栫暐銆傞『搴忔彁浜ゅ姞鍗曟鏌ヨ涓嶆瀯鎴愯疆璇㈣瘉鎹紝浠嶄細琚樆鏂€備粎鎻忚堪鍗曡姹傚厓鏁版嵁鐨勫紓姝ュ拰瀹夊叏瑙勫垯浼氳闃绘柇銆傞『搴忔祦绋嬫棤娉曡瘉鏄庡苟鍙戯紝璺ㄦā鍧楁垨璺ㄦ湇鍔℃祦绋嬪睘浜?E2E 棰嗗煙銆傜敓鎴愬櫒浼氭嫆缁?OpenAPI 涓笉瀛樺湪鐨勮璁?HTTP 鐘舵€侊紝骞跺皢姝т箟瑙勫垯璁板綍鍒?`manual_confirmations`锛屼笉鐢熸垚涓氬姟娴嬭瘯銆?
## 瀹屾垚

姣忎釜鐢ㄤ緥閮戒繚鐣欒姹傘€侀鏈?HTTP/涓氬姟缁撴灉銆佽璁℃垨 OpenAPI 璇佹嵁鍙婄簿纭柇瑷€銆俙review-*` 鍊煎拰鏈В鍐崇殑纭椤逛細闃绘柇鐢熸垚銆傛瘡涓垚鍔熺敤渚嬭嚦灏戦渶瑕佷竴涓簿纭殑涓氬姟缁撴灉鎴栫姸鎬佸彉鏇存柇瑷€锛涘０鏄庝笟鍔＄爜鏃讹紝璇ョ爜蹇呴』鏄垚鍔熷€硷紝骞堕厤鏈夊叿浣撶粨鏋滄柇瑷€銆傛瘡鏉℃湁璁捐渚濇嵁鐨勯€昏緫璁板綍閮藉繀椤诲叧鑱旂湡瀹炵敤渚?ID锛屾瘡涓０鏄庣殑娴佺▼閮藉繀椤绘湁鏈夊簭鎵ц璇佹嵁銆?