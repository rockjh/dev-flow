# 涓氬姟涓?QA 鐗堟湰绠＄悊

鍦?`qa/contracts` 涓嬬淮鎶や袱涓浉浜掔嫭绔嬬殑閿併€?
`version-lock.yaml` 璁板綍鐢熸垚鐨?QA 鍜屾瀯寤虹洰褰曚箣澶栧綋鍓嶄笟鍔℃枃浠剁殑鎽樿锛屼互鍙婄嫭绔嬬殑 OpenAPI 鍜岄€夊畾璁捐鏂囨。鎽樿銆傛鏌ュ櫒鍙鍙栧綋鍓嶅伐浣滃尯锛屼笉妫€鏌ョ増鏈帶鍒跺巻鍙层€傛憳瑕佸彂鐢熷彉鍖栨椂鎸夊奖鍝?API 淇濆畧鍒嗙被锛屽洜涓烘枃浠剁郴缁熷揩鐓ф棤娉曡瘉鏄庡叿浣撳摢椤硅涓哄彂鐢熷彉鍖栥€?
`qa-lock.yaml` 璁板綍褰撳墠 OpenAPI銆佹ā鍧椼€佺敤渚嬪拰鐢熸垚鐘舵€?fingerprint銆傜敓鎴愬拰鐗╁寲浼氬埛鏂板畠锛涙鏌ヤ笌鎵ц浼氭嫆缁濊繃鏈?fingerprint銆?
閫氳繃鍏变韩 CLI 娴佺▼鍒濆鍖栧苟闂ㄧ涓氬姟閿侊細

```bash
devflow bru-api init --qa-root qa
devflow bru-api generate --qa-root qa --openapi qa/contracts/openapi.json --source-root APP
devflow bru-api preflight --qa-root qa
devflow bru-api run --qa-root qa
```

鍏变韩杩愯鏃朵細鍦ㄧ敓鎴愩€侀妫€鍜屾墽琛屾湡闂存鏌ユ簮浠ｇ爜/鐗堟湰閿併€傚垵濮嬪寲浼氬垱寤鸿崏绋垮熀绾裤€傞娆＄紪鎺掔殑棰勬/杩愯浠呭湪婧愭憳瑕佹湭鍙樺寲鏃跺彲浣跨敤璇ヨ崏绋匡紱鏅€氱嫭绔嬬殑 `before-execute` 妫€鏌ヤ粛瑕佹眰鐘舵€佷负 `current`銆傚畬鎴愭潯浠舵槸鎴愬姛鐢熸垚 v2 `full-matrix-strict` 鍏ㄥ眬鎶ュ憡锛屽惎鐢ㄦ墍鏈変弗鏍兼鏌ャ€佹棤閿欒銆乣status: verified` 涓?`completion_ok: true`銆傚奖鍝?API 鐨勬憳瑕佸彉鍖栧繀椤诲厛璋冩暣骞堕噸鏂拌繍琛屽彈褰卞搷妯″潡娴嬭瘯锛屼箣鍚庢墠鑳芥帹杩涢攣銆?
杩愯鍣ㄤ細鑷姩鎺ㄨ繘鎴愬姛鐨勫叏灞€鎵ц銆傛棤闇€椤圭洰鏈湴鑴氭湰锛屼篃鍙互鏄惧紡鎵ц鐩稿悓鐨勭増鏈搷浣滐細

```bash
devflow bru-api scripts version-check --qa-root qa --phase before-generate
devflow bru-api scripts version-check --qa-root qa --phase before-execute
devflow bru-api scripts version-complete --qa-root qa --completion-report qa/results/<strict-report>.json --tests-adapted
```

瀵逛簬杩滅▼ `baseUrl`锛屽綋閮ㄧ讲鎻愪緵鐗堟湰绔偣鏃讹紝鍦ㄥ綋鍓?Bruno 鐜涓厤缃?`versionPath`銆傚彲鐢?`versionJsonPath`銆乣versionHeader` 鎴?`expectedVersion` 閫夋嫨闈炴爣鍑嗗€笺€傜鐐瑰繀椤讳笌 `baseUrl` 浣跨敤鍚屼竴 origin锛涚増鏈棬绂佸け璐ユ垨涓嶅尮閰嶆椂蹇呴』鍏堣В鍐筹紝鍐嶆墽琛屻€?
`impact-rules.yaml` 浠嶅彲鐢ㄤ簬瀵瑰叾浠栧伐鍏锋彁渚涚殑褰撳墠宸ヤ綔鍖哄懡鍚嶈矾寰勫垎绫汇€傛湭鐭ヤ笟鍔¤矾寰勬寜淇濆畧绛栫暐澶勭悊銆?