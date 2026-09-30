# 涓氬姟涓?QA 鐗堟湰绠＄悊

鍦?`qa/contracts` 涓嬬淮鎶や袱涓浉浜掔嫭绔嬬殑閿併€?

`version-lock.yaml` 璁板綍鐢熸垚鐨?QA 鍜屾瀯寤虹洰褰曚箣澶栧綋鍓嶄笟鍔℃枃浠剁殑鎽樿锛屼互鍙婄嫭绔嬬殑 OpenAPI 鍜岄€夊畾璁捐鏂囨。鎽樿銆傛鏌ュ櫒鍙鍙栧綋鍓嶅伐浣滃尯锛屼笉妫€鏌ョ増鏈帶鍒跺巻鍙层€傛憳瑕佸彉鍖栦細琚繚瀹堝湴褰掔被涓哄奖鍝?API锛屽洜涓烘枃浠剁郴缁熷揩鐓ф棤娉曡瘉鏄庡叿浣撴敼鍙樹簡鍝」琛屼负銆?

`qa-lock.yaml` 璁板綍褰撳墠 OpenAPI銆佹ā鍧椼€佺敤渚嬪拰鐢熸垚鐘舵€佹寚绾广€傜敓鎴愪笌瀹炰綋鍖栦細鍒锋柊瀹冿紱妫€鏌ュ拰鎵ц浼氭嫆缁濊繃鏈熸寚绾广€?

閫氳繃鍏变韩 CLI 宸ヤ綔娴佸垵濮嬪寲骞堕棬绂佷笟鍔￠攣锛?

```bash
devflow bru-api init --qa-root qa
devflow bru-api generate --qa-root qa --openapi qa/contracts/openapi.json --source-root APP
devflow bru-api preflight --qa-root qa
devflow bru-api run --qa-root qa
```

鍏变韩杩愯鏃朵細鍦ㄧ敓鎴愩€侀妫€
鍜屾墽琛屾湡闂存鏌ユ簮浠ｇ爜/鐗堟湰閿併€傚垵濮嬪寲浼氬垱寤鸿崏绋垮熀绾裤€傚彧瑕佹簮鎽樿鏈彉鍖栵紝绗竴娆＄紪鎺掔殑棰勬/杩愯鍙互浣跨敤璇ヨ崏绋匡紱鏅€氱嫭绔嬬殑 `before-execute` 妫€鏌ヤ粛瑕佹眰鐘舵€佷负 `current`銆傚畬鎴愰渶瑕佹垚鍔熺殑 v2 `full-matrix-strict` 鍏ㄥ眬鎶ュ憡锛屽惎鐢ㄥ叏閮ㄤ弗鏍兼鏌ャ€佹棤閿欒銆乣status: verified` 涓?`completion_ok: true`銆傚奖鍝?API 鐨勬憳瑕佸彉鍖栧繀椤诲厛璋冩暣骞堕噸鏂拌繍琛屽彈褰卞搷妯″潡娴嬭瘯锛屾墠鑳芥帹杩涢攣銆?

杩愯鍣ㄤ細鑷姩鎺ㄨ繘鎴愬姛鐨勫叏灞€鎵ц銆傛棤闇€椤圭洰鏈湴鑴氭湰锛屼篃鍙互鏄惧紡鎵ц鐩稿悓鐨勭増鏈搷浣滐細

```bash
devflow bru-api scripts version-check --qa-root qa --phase before-generate
devflow bru-api scripts version-check --qa-root qa --phase before-execute
devflow bru-api scripts version-complete --qa-root qa --completion-report qa/results/<strict-report>.json --tests-adapted
```

瀵逛簬杩滅▼ `baseUrl`锛屽綋閮ㄧ讲鎻愪緵鐗堟湰绔偣鏃讹紝鍦ㄦ椿鍔?Bruno 鐜涓厤缃?`versionPath`銆俙versionJsonPath`銆乣versionHeader` 鎴?`expectedVersion` 鍙€夋嫨闈炴爣鍑嗗€笺€傜鐐瑰繀椤讳笌 `baseUrl` 鍏变韩婧愶紱鐗堟湰闂ㄧ澶辫触鎴栦笉鍖归厤鏃讹紝蹇呴』瑙ｅ喅鍚庢墠鑳芥墽琛屻€?

`impact-rules.yaml` 浠嶅彲鐢ㄤ簬鍒嗙被鍏朵粬宸ュ叿鎻愪緵鐨勫綋鍓嶅伐浣滃尯鍛藉悕璺緞銆傛湭鐭ヤ笟鍔¤矾寰勬寜淇濆畧鏂瑰紡澶勭悊銆?
