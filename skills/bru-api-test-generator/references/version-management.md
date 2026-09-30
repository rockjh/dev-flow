# 娑撴艾濮熸稉?QA 閻楀牊婀扮粻锛勬倞

閸?`qa/contracts` 娑撳娣幎銈勮⒈娑擃亞娴夋禍鎺斿缁斿娈戦柨浣规瀮娴犺翰鈧?
`version-lock.yaml` 鐠佹澘缍嶉悽鐔稿灇閻?QA 閸滃本鐎铏规窗瑜版洑绠ｆ径鏍х秼閸撳秳绗熼崝鈩冩瀮娴犲墎娈戦幗妯款洣閿涘奔浜掗崣濠勫缁斿娈?OpenAPI 閸滃矂鈧鐣剧拋鎹愵吀閺傚洦銆傞幗妯款洣閵嗗倹顥呴弻銉ユ珤閸欘亣顕伴崣鏍х秼閸撳秴浼愭担婊冨隘閿涘奔绗夊Λ鈧弻銉у閺堫剚甯堕崚璺哄坊閸欏眰鈧倻鏁辨禍搴㈡瀮娴犲墎閮寸紒鐔锋彥閻撗勬￥濞夋洝鐦夐弰搴″徔娴ｆ挻鏁奸崣妯圭啊閸濐亪銆嶇悰灞艰礋閿涘本鎲崇憰浣稿綁閸栨牔绱扮悮顐＄箽鐎瑰牆婀磋ぐ鎺旇娑撳搫濂栭崫?API閵?
`qa-lock.yaml` 鐠佹澘缍嶈ぐ鎾冲 OpenAPI閵嗕焦膩閸фぜ鈧胶鏁ゆ笟瀣嫲閻㈢喐鍨氶悩鑸碘偓浣瑰瘹缁惧箍鈧倻鏁撻幋鎰嫲閻椻晛瀵叉导姘煕閺傛澘鐣犻敍娑欘梾閺屻儱鎷伴幍褑顢戞导姘珕缂佹繆绻冮張鐔稿瘹缁惧箍鈧?
Initialize and gate the business lock through the shared CLI workflow:

```bash
devflow bru-api init --qa-root qa
devflow bru-api generate --qa-root qa --openapi qa/contracts/openapi.json --source-root APP
devflow bru-api preflight --qa-root qa
devflow bru-api run --qa-root qa
```

閸忓彉闊╂潻鎰攽閺冩湹绱伴崷銊ф晸閹存劑鈧線顣╁Λ鈧崪灞惧⒔鐞涘本婀￠梻瀛橆梾閺屻儲绨?閻楀牊婀伴柨浣碘偓鍌氬灥婵瀵叉导姘灡瀵ら缚宕忕粙鍨唨缁捐￥鈧倿顩诲▎锛勭椽閹烘帞娈戞０鍕梾/鏉╂劘顢戞禒鍛讲閸︺劍绨幗妯款洣閺堫亝鏁奸崣妯绘娴ｈ法鏁ょ拠銉ㄥ磸缁嬪尅绱遍弲顕€鈧氨瀚粩瀣畱 `before-execute` 濡偓閺屻儰绮涚憰浣圭湴閻樿埖鈧椒璐?`current`閵嗗倸鐣幋鎰箑妞ょ粯褰佹笟娑欏灇閸旂喓娈?v2 `full-matrix-strict` 閸忋劌鐪幎銉ユ啞閿涘苯鎯庨悽銊﹀閺堝寮楅弽鍏碱梾閺屻儯鈧焦妫ら柨娆掝嚖閵嗕梗status: verified` 娑?`completion_ok: true`閵嗗倸濂栭崫?API 閻ㄥ嫭鎲崇憰浣稿綁閸栨牞顩﹀Ч鍌氬帥鐠嬪啯鏆ｉ獮鍫曞櫢閺傛媽绻嶇悰灞藉綀瑜板崬鎼峰Ο鈥虫健閻ㄥ嫭绁寸拠鏇礉娑斿鎮楅幍宥堝厴閹恒劏绻橀柨浣哄Ц閹降鈧?
鏉╂劘顢戦崳銊ょ窗閼奉亜濮╅幒銊ㄧ箻閹存劕濮涢惃鍕弿鐏炩偓閹笛嗩攽閵嗗倸鎮撻弽椋庢畱閻楀牊婀伴幙宥勭稊娑旂喎褰查弰鎯х础閹笛嗩攽閿涘本妫ら棁鈧い鍦窗閺堫剙婀撮懘姘拱閿?
```bash
devflow bru-api scripts version-check --qa-root qa --phase before-generate
devflow bru-api scripts version-check --qa-root qa --phase before-execute
devflow bru-api scripts version-complete --qa-root qa --completion-report <temporary-strict-report.json> --tests-adapted
```

鐎甸€涚艾鏉╂粎鈻?`baseUrl`閿涘苯缍嬮柈銊ц閹绘劒绶甸悧鍫熸拱閹恒儱褰涢弮璁圭礉閸︺劍妞块崝?Bruno 閻滎垰顣ㄦ稉顓㈠帳缂?`versionPath`閵嗗倸褰叉担璺ㄦ暏 `versionJsonPath`閵嗕梗versionHeader` 閹?`expectedVersion` 闁瀚ㄩ棃鐐寸垼閸戝棗鈧鈧倽顕氶幒銉ュ經韫囧懘銆忔稉?`baseUrl` 閸忓彉闊╁┃鎰剁幢閻楀牊婀伴梻銊ь洣婢惰精瑙﹂幋鏍︾瑝閸栧綊鍘ら弮璁圭礉韫囧懘銆忛崗鍫Ｐ掗崘鎶芥６妫版ê鍟€閹笛嗩攽閵?
`impact-rules.yaml` 娴犲秴褰查悽銊ょ艾鐎电懓鍙炬禒鏍т紣閸忛攱褰佹笟娑氭畱瑜版挸澧犲銉ょ稊閸栧搫鎳￠崥宥堢熅瀵板嫯绻樼悰灞藉瀻缁眹鈧倹婀惌銉ょ瑹閸斅ょ熅瀵板嫭瀵滄穱婵嗙暓閺傜懓绱℃径鍕倞閵?