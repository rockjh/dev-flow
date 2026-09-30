#鐩存帴鏁版嵁搴撹闂?
浠呭湪浠ヤ笅涓ょ鎯呭喌涓嬩娇鐢ㄧ洿鎺ySQL銆丒lasticsearch銆丮ongoDB鎴栧叾浠栨暟鎹瓨鍌ㄨ鍙ワ細
1. `missing_prerequisite_api` 锛氭ā鍧椾笉鍏紑API鎴栨壒鍑嗙殑娴嬭瘯鎺т欢锛屽彲浠ュ垱寤哄叾API妗堜緥鎵€闇€鐨勬暟鎹€?
2. `missing_response_state` 锛?API鍝嶅簲涓嶆毚闇茶瘉鏄庢搷浣滄垚鍔熸墍闇€鐨勭姸鎬併€?
棣栭€夊叕鍏辨垨宸叉壒鍑嗙殑娴嬭瘯API 锛堝彧瑕佸瓨鍦級銆?鏁版嵁搴撹缃槸娴嬭瘯鍑嗗锛岃€屼笉鏄祴璇曚腑鐨勪笟鍔℃搷浣溿€?鏁版嵁搴撴柇瑷€鏄HTTP鐘舵€佸拰鍙敤涓氬姟鍝嶅簲鏂█鐨勮ˉ鍏咃紱瀹冧滑涓嶄細鍙栦唬鏈嶅姟鎻愪緵鐨勫彲瑙傚療鍝嶅簲妫€鏌ャ€?
# #妗堜緥鏍煎紡
鍦╜cases.yaml`涓０鏄庝釜妗堟墍鏈夌殑姝ラ銆?Runner灏嗘瘡涓€夊畾鐨刞setup`姝ラ鏀堕泦鍒颁竴涓繍琛岀骇鍒鍒掍腑锛屽苟鍦ㄦ渚嬩腑浠呭疄鐜板厛鍐虫潯浠堕槻鎶ゃ€?Bruno鍦╜script:post-response`涓繚鐣檂assertion`姝ラ锛屽苟涓斾粎褰撴墍閫夎寖鍥村寘鍚暟鎹簱姝ラ鏃讹紝杩愯鍣ㄦ墠鍚敤鍏跺紑鍙戜汉鍛樻矙鐩掋€?
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

QUERY LENGTH LIMIT EXCEEDED. MAX ALLOWED QUERY : 500 CHARS
# #鍏朵粬寮曟搸
QUERY LENGTH LIMIT EXCEEDED. MAX ALLOWED QUERY : 500 CHARS
鍦╜qa/bruno/package.json`涓０鏄庢墍闇€鐨勮妭鐐瑰鎴风骞跺浐瀹氬叾鐗堟湰銆?涓嶈涓轰竴娆℃€ф楠ゆ坊鍔犻€氱敤鏁版嵁搴撴娊璞°€?
# #杩愯鏃跺拰瀹夊叏鎬?
杩炴帴鍦板潃銆佹暟鎹簱/绱㈠紩鍚嶇О銆佺敤鎴枫€佸瘑鐮併€乀LS璁剧疆鍜屽す鍏锋爣璇嗙浠呮潵鑷椿鍔ㄧ殑BRUNO鐜鎴栧叾杩囩▼鐜銆?鍒囧嬁鎻愪氦宸茶В鏋愮殑鍑嵁鎴栧叿鏈夊嚟鎹殑URL銆?
MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY. NEXT AVAILABLE IN  10 HOURS 20 MINUTES 15 SECONDS VISIT HTTPS://MYMEMORY.TRANSLATED.NET/DOC/USAGELIMITS.PHP TO TRANSLATE MORE
MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY. NEXT AVAILABLE IN  10 HOURS 20 MINUTES 14 SECONDS VISIT HTTPS://MYMEMORY.TRANSLATED.NET/DOC/USAGELIMITS.PHP TO TRANSLATE MORE