# 妯″潡骞惰鐢熸垚涓庢墽琛?

浠呭湪鍗忚皟鑰呭喕缁?OpenAPI 娓呭崟銆佹ā鍧楁槧灏勩€佸叡浜墽琛岄厤缃拰 `qa/constraints/rules.yaml` 鍚庝娇鐢ㄥ伐浣滃櫒銆?
Before dispatching each assignment, record its current-workspace boundary:

```bash
devflow bru-api worker-start --module <module>
```

## 褰掑睘

| 璐熻矗浜?| 鍙啓鑼冨洿 |
| --- | --- |
| 鍗忚皟鑰?| 鍏ㄥ眬濂戠害銆侀攣銆佺害鏉熷悎骞躲€佹墽琛岄厤缃€侀泦鍚堟枃浠躲€佽法妯″潡娴佺▼鍜屾渶缁堟姤鍛?|
| 妯″潡宸ヤ綔鍣?| 浠呴檺鍏?`contracts/modules/<directory>/` 鍜?`bruno/<directory>/`锛涙墽琛岃瘉鎹拰鏃ュ織淇濈暀鍦ㄨ繘绋嬫湰鍦?|

宸ヤ綔鍣ㄥ彲浠ヨ鍙栧叡浜绾︺€侀厤缃€佹棦鏈夎瘉鎹拰鎵ц鏀寔婧愪唬鐮併€傛簮浠ｇ爜妫€鏌ヤ粎闄愯繍琛屾椂閰嶇疆銆佽璇?鏍囧ご璁剧疆銆佸す鍏枫€佹祴璇曟暟鎹噯澶囧拰妯℃嫙寮€鍏筹紱涓嶅緱鎻愪緵涓氬姟瑙勫垯鎴栭鏈熺粨鏋溿€備笉寰楀啓鍏ヤ笟鍔′唬鐮併€佸叾浠栨ā鍧椼€乣index.yaml`銆乣generation-state.yaml`銆乣qa-lock.yaml`銆乣bru-api-test-generator-version.json`銆乣collection.bru`銆佸叡浜幆澧冩垨璺ㄦā鍧楁祦绋嬨€?
鍗忚皟鑰?records each assignment and gives the constraint validator the worker role, assigned module, and changed paths. `module-worker-boundary` and `business-code-immutable` fail any path outside the table above.

## 宸ヤ綔鍣ㄦ祦绋?

1. 闃呰鍒嗛厤鐨勬ā鍧楀绾﹀拰鍏变韩鏈哄櫒瑙勫垯銆?2. 妫€鏌ユ墽琛屽垎閰嶇敤渚嬫墍闇€鐨勮繍琛屾椂閰嶇疆銆佽璇?绛惧悕/鏍囧ご璁剧疆銆佸す鍏枫€佹暟鎹簱娴嬭瘯鏁版嵁鍑嗗銆佷笂浼犳ā鏉垮拰澶栭儴鏈嶅姟妯℃嫙寮€鍏炽€?3. 闃呰宸插闃呯殑璁捐瑙勫垯鍜?OpenAPI 濂戠害锛岄殢鍚庣紪鍐欐ā鍧楄璁″紩鐢ㄣ€乣logic.yaml`銆乣cases.yaml`锛屽苟鍦ㄩ€傜敤鏃剁紪鍐欐槑纭祦绋?鎺掗櫎椤广€傛簮鍙戠幇浠呬綔涓烘墽琛屾敮鎸侊紝涓嶈兘鍒涘缓涓氬姟鐢ㄤ緥鎴栭鏈熷€笺€?4. 杩愯妯″潡鐗╁寲銆傚畠鍙啓鍏ユā鍧?Bruno 鐩綍銆乣materialization-state.yaml`銆乣module-lock.yaml` 鍜屾ā鍧楁枃妗ｃ€?5. 杩愯 `devflow bru-api run --module <module>`銆傚畠楠岃瘉妯″潡閿侊紝骞跺皢璇佹嵁鍜屾棩蹇椾繚瀛樺湪杩涚▼鏈湴涓存椂鐩綍銆?6. 杩愯 `devflow bru-api worker-check --module <module> --stage post-execution`銆傚彉鏇磋矾寰勬牴鎹褰曠殑蹇収璁＄畻銆?7. 杩斿洖瑙勫垯/鐢ㄤ緥/閫昏緫/娴佺▼ ID銆佹寜绫诲埆褰掔撼鐨勫け璐ヤ互鍙婇樆濉炴€х殑浜哄伐纭椤广€俙qa/reports/latest.md` 鐢卞崗璋冭€呰礋璐ｃ€?
宸ヤ綔鍣ㄥけ璐ュ彧褰卞搷瀵瑰簲妯″潡锛屽叾浠栧伐浣滃櫒缁х画銆?

## 鐙珛鎬т笌娴佺▼

妯″潡杩愯涓嶈兘渚濊禆鍏朵粬妯″潡閫氳繃銆傚叡浜缃垨鎹曡幏鐨勬爣璇嗙闇€瑕佺敱鍗忚皟鑰呰礋璐ｇ殑鏄庣‘娴佺▼銆備笉寰楅€氳繃鏂囦欢鍚嶃€佹ā鍧楅『搴忔垨鍏变韩鍙彉澶瑰叿缂栫爜渚濊禆銆?
骞惰鎵ц杩樿姹傞殧绂昏处鍙枫€佺鎴枫€佽褰曞拰澶瑰叿璺緞銆傛湭璇佹槑闅旂鏃讹紝宸ヤ綔鍣ㄥ彲浠ュ苟鍙戠敓鎴愶紝浣嗗崗璋冭€呭繀椤婚『搴忔墽琛屾ā鍧椼€?
## 鍗忚皟鑰呭悎骞?

After workers finish, the coordinator:

1. 楠岃瘉姣忎釜宸ヤ綔鍣ㄧ殑蹇収杈圭晫鍜屾ā鍧楅攣锛?2. 楠岃瘉鍏变韩璁捐瑙勫垯锛屽苟灏嗚瀵熻瘉鎹繚鐣欏湪杩涚▼鏈湴锛?3. 閲嶆柊鐢熸垚 `index.yaml` 鍜?`generation-state.yaml`锛屼笉閲嶇疆鏈敼鍙樼殑鎴愬姛鐢ㄤ緥锛?4. 鍏ㄥ眬鐗╁寲骞跺埛鏂?`qa-lock.yaml`锛?5. 楠岃瘉璺ㄦā鍧楁祦绋嬶紱
6. 鍦ㄥ叏妯″潡杩愯鍚庡啓鍏ュ敮涓€鐨?`qa/reports/latest.md` 鎽樿锛涗互鍙?7. 浠呭綋鍗忚皟鑰呰礋璐ｇ殑璺ㄦā鍧楁祦绋嬮渶瑕佹椂杩愯鍏ㄦā鍧楅泦鍚堛€?
宸ヤ綔鍣ㄦ姤鍛婃槸杈撳叆锛屼笉鏄瘉鏄庛€傚叡浜害鏉熴€佸叏灞€鏍稿鍜屾墽琛岃瘉鎹叿鏈夋潈濞佹€с€?