# プロジェクト状態

更新日: 2026-10-22

本書は「いまの実装」「確認待ち」「次の作業」を共有する状況メモです。確定仕様の詳細は product_spec.md と ui_spec.md、過去の経緯は devlog.md を参照してください。コードを変更する作業では、実ファイルを状態確認の基準とします。

## 現在の状態

- アプリ名: どっちに池袋
- 試作UI: Ver.0.4.2
- 実装: フレームワークなしのHTML/CSS/JavaScript。GitHub Pagesで試作公開中: https://bwm2bwm.github.io/dotchi-ikebukuro/
- 現在の画面: 池袋→氷川台、有楽町線・副都心線の列車候補を比較。路線別／発車順、直通のみフィルター、毎秒カウントダウン、最早着マークを実装。
- データ: data.js の架空ダイヤ6本のみ。ODPT API接続なし。実際の乗車判断には使用できない旨を表示。
- 現UIの基準: iPhone 12 / Safariでユーザーが確認したVer.0.4.2画面。詳細は ui_spec.md。
- Git管理: .gitignore に .DS_Store を設定し、追跡解除済み。履歴に反映済み。

## 確認済みの前提

- 現在のコードは発車をアプリ起動時刻とモックの相対秒から計算し、到着を仮所要時間から計算する。接続待ち値は表示のみで、実際の接続判定はない。
- 路線別表示は有楽町線→副都心線。グループ内は発車時刻順で、本数は各グループの先頭カードに表示する。
- 広告はレイアウト検証用の固定320×50pxプレースホルダー。実広告・広告SDKはない。
- ソースと公開画面の細かな同期状態は、公開前にGitHub Pagesで確認する。

## ODPTの状況

- ODPT開発者登録はユーザーより承認済みとの報告あり（2026-10-22）。ユーザーのMac環境に `.env.local`、`.venv`、certifiが準備され、通常ターミナルからのAPI接続成功が報告された。
- Phase 3 GTFS実データ解析済み。ローカルZIPはversion 20261008、有効期間2026-09-19〜2027-03-12。池袋→氷川台の順に停車行が並ぶtripは有楽町線279件・副都心線295件。氷川台到着時刻は有楽町線279/279、副都心線248/295に記録され、残る47件は `pickup_type=1` / `drop_off_type=1`、時刻空欄のため停車／通過を判別できない。明確な乗降可能レコードでは到着時刻248/248。
- GTFS `trip_id` の中央部（先頭・末尾2文字を除く）とODPT `odpt:trainNumber`、路線、曜日区分で照合し、一意一致は有楽町線199/279、副都心線168/295。すべての一意一致で池袋発時刻も一致。未一致便は同じ規則では対応不明。GTFS trip_short_nameは対象便すべて空。
- GTFS `calendar` と `calendar_dates` から平日・土日・祝日の実日付を評価。24時超のサービス時刻も確認済み。小竹向原は路線別のstop_id 606/906で座標・駅名は一致し、別trip_id同士の時刻候補を生成できるが、最低乗換時間・ホーム経路がなく接続可否は未判定。
- Phase 3旅程検証: `stops.txt` の `platform_code` は全件空で、番線・同一ホームは個別列車単位に確認できない。ユーザー指定の暫定ルール（同一運行日、反対路線の別trip、記録時刻の差60秒以上）で解析した結果、平日66組・土曜80組・祝日80組の1分候補。全て後続出発を組み合わせた全ペアでは平日32,105組、土曜24,696組で冗長なため、Ver.0.5では池袋発列車ごとにまとめ、最早到着を先に表示する案。詳細は [odpt_research.md](odpt_research.md)。
- 再現スクリプト `scripts/odpt_phase3_itinerary_analyze.py` を追加。取得済みZIPのみを読み、日別の直通・乗換候補、0/1/2分、日付跨ぎ、運行例外、期間外を集計する。アプリ本体は未変更。
- 詳細な検証結果、47便ID、接続例、実運行表示の評価は [odpt_research.md](odpt_research.md)。解析器は `scripts/odpt_phase3_gtfs_analyze.py`。
- ODPT JSON単独では、対象駅の途中到着時刻がなく、小竹向原の到着と乗換待ち時間も算出できない。一方、今回のGTFSでは氷川台と小竹向原の到着時刻を確認できた。JSON単独の制約とGTFS補完結果は [odpt_research.md](odpt_research.md)。
- ODPTの列車時刻表と池袋駅時刻表は `odpt:train` + `odpt:calendar` で対象方向の全件照合済み。GTFSの実日付例外は今回別途確認済み。ホーム・最低乗換時間、GTFS更新頻度、数値API制限は未確認。詳細は [odpt_research.md](odpt_research.md)。
- 接続可能・不可・不明を区別する方針。ホームや最低乗換時間を確認できない場合は、接続可能と断定しない。

## 実装上の確認メモ

- 架空データでは transfer の有無を直通／乗換の判定に使い、destination は列車の行き先として表示する。到着時刻は別の固定所要分から計算するため、目的地への到達可否を表す実データ仕様として流用しない。
- index.html のスタイルシートURLは styles.css?v=0.4.1。UIはVer.0.4.2なので、クエリ値は画面版数を示すものではないが、次回スタイル変更時にキャッシュ更新値を揃えるか確認する。

## 未解決事項

1. 実列車の番線・構内経路・事業者の最低乗換時間は未確認。アプリ独自の暫定60秒ルールを使う場合も、接続保証とは表示しない。
2. GTFSのフィード更新・改正適用日を継続確認し、期間外は実ダイヤを表示しない。
3. 遅延情報の提供有無、鮮度、欠損・通信エラーの表示方法を確認する。
4. 同一池袋発便に複数接続候補がある場合の画面上の扱いを検討する。
5. 目的地候補の最終範囲と選択・保存方法、正式ホスティング、広告・支援方式を検討する。

## 次のタスク

1. Step 2B-2でadapterをlocal preview用のコピーUIに接続し、カード・時計・カウントダウンを確認する。
2. 到着時刻なし便の表示、最早着同着、行先不明表示、現在から24時間の時間窓をpreview上で確認する。
3. 接続結果をレビューしてから、アプリ本体に取り込む範囲を決める。公開・配信変更は別途扱う。

## Phase 3旅程最適化の更新（2026-10-22）

- `scripts/odpt_phase3_itinerary_optimize.py` を追加。保存済みGTFS ZIPとODPT JSONから、平日・土曜・祝日の直通比較、待ち上限5/10/15分・上限なしでの乗換候補、GTFS表示項目、ODPT列車種別の一意照合を再現できる。
- 有効な直通と乗換の双方を比較できた代表日3日では、全待ち上限で直通が最早、同着0、乗換による短縮0。乗換のみの親便は平日152、土曜・祝日162（待ち上限なし）だが、うち直通行に時刻欠損／降車不可の便が13／34。乗換のみを直通より早いと数えない。
- 元接続組→親便集約数は平日10分上限622→417、土曜・祝日490→366。上限なしは32,082／24,682組となり、初期表示に全接続を並べない設計が必要。
- GTFSから路線名・headsign・時刻・運行日は取得可能だが、列車種別列はない。保存済みODPTは一意照合分のみ種別／行先補完に使い、未照合便は不明のままにする。
- Ver.0.5案: 池袋発便ごとに最早旅程を主表示し、直通を代替候補として保持。直通優先の同着規則、60秒暫定乗換基準、番線不明・接続保証なしをモデル化する。待ち上限5/10/15分、乗換案の初期表示、欠損便の扱いは未決定。詳細・件数表は [odpt_research.md](odpt_research.md)。
- アプリ本体と取得済みデータは未変更。コミットなし。

## Ver.0.5 Step 1 — 実ダイヤ旅程生成（2026-10-22）

- 再利用モジュール [odpt_itinerary.py](../scripts/odpt_itinerary.py) を追加。service date適用、論理駅alias、GTFS時刻（24時超を含む）、乗降・欠損状態、直通・反対路線乗換を内部モデルへ正規化する。既定接続条件は60〜600秒。
- 1つの池袋発tripにつきprimary itineraryは最大1件。到着時刻最早を選び、同着なら直通優先。比較用のdirect alternative、最早transfer alternativeと接続数を保持し、全接続候補配列を画面形式では返さない。番線unknown、接続保証false。
- 保存済みODPT JSONは便番号・路線・calendar区分と池袋発時刻の一意一致時だけ、両区間tripに種別／行先を補完。未一致・曖昧・不一致は状態のみ保持し、生JSONを返さない。
- [validate_odpt_itineraries.py](../scripts/validate_odpt_itineraries.py) で検証: 平日池袋発439便（直通287、乗換候補417、primary:直通287／乗換148／到着不可4）、土曜・祝日各405便（直通240、乗換候補366、primary:直通240／乗換156／到着不可9）。10分以内の接続は平日645組（うち60〜600秒622）、土休日504組（うち490）。0/1/2分は平日23/66/60組、土休日14/80/29組。期間外はFeedDateErrorで候補生成を止める。
- `tests/test_odpt_itinerary.py` の8テスト通過。現UI・HTML/CSS/JavaScript、GTFS ZIP、ODPT JSON、公開用データは変更していない。Step 2はこのPython出力から画面データadapterを設計し、欠損表示と便ごとのprimary/direct alternativeをUIへ接続する。

## Ver.0.5 Step 2A — Web UI接続設計（2026-10-22）

- [Web UI接続仕様案](ver_0_5_step_2a_ui_integration.md) を作成。現行UIの相対 `departSec` / 仮 `travelMin` と、Step 1のサービス日・24時超秒・primary/direct alternativeを対応づけ、カード表示、路線別／発車順、フィルター、最早着、深夜運行日を設計した。
- [export_local_timetable_payload.py](../scripts/export_local_timetable_payload.py) を追加。最小限のカード用JSONにschema version、生成時刻、GTFS版・有効期間、運行日、暫定接続条件を付け、リポジトリ内の出力先を拒否する。書き出しコマンドは用意したが、本番UI・公開用データへは接続していない。
- Step 2Bはリポジトリ外の一時staging copyをローカルHTTP配信し、そこだけにpreview用loader/adapterを置く案。現行HTML/CSS/JavaScriptの表示と動作は未変更。詳細な未決事項は設計書参照。
- `python3 -B -m unittest discover -s tests -v` は11テスト通過。payload exporterの期間外日skip、repository内出力拒否、必須metadata、最小項目と生データ非出力を検証。payloadファイル自体は出力していない。

## Ver.0.5 Step 2B-1 — JavaScript adapter（2026-10-22）

- [timetable_adapter.mjs](../scripts/timetable_adapter.mjs) を追加。DOMに依存せずStep 2A payloadを検証し、路線色・種別ラベル・行先不明・東京時間の絶対発着時刻をカードview modelへ変換する。
- 東京時間の前日／当日／翌日service dayを対象にし、nowより後かつ24時間以内・feed有効期間内の便を抽出。24時超時刻、service day違いの同一route/trip/絶対発車の重複、到着時刻欠損、directOnly、路線別／発車順、最早着1件・同着時の早発優先を扱う。
- 不確実性は `platformStatus=unknown`, `connectionGuaranteed=false` をview modelに保持。未対応train typeは「種別不明」、destination欠損は「行き先不明」。到着を推測せず除外理由・dataQualityを返す。
- [timetable_adapter.test.mjs](../tests/timetable_adapter.test.mjs) の12件をNode標準test runnerで実行し全件通過。通常TZと `TZ=UTC` の双方で実行。UIファイル・payload・生データは変更／生成していない。
- Step 2B-2はローカル一時previewへadapterを接続し、カードDOMへのマッピング、時計、カウントダウン、filter・mode動作を確認する。

## 計画中・未決定の企画

- 目的地候補として10駅案があるが、最終リストではない。
- 目的地選択・最近使った駅の保存は予定で、方式は未決定。
- Cloudflare Pages + Workers等は正式ホスティング候補に留まる。
- Google AdSense等の広告、任意支援サービス、公共交通オープンデータチャレンジ応募は検討段階。採用・応募は未決定。
- 版数／アプリ更新日時を表示する案がある。時刻表データ更新日時とは分けて検討する。

## 作業上の注意

実ダイヤ導入までは架空データの警告を残す。ODPT仕様、データ提供状況、利用条件や外部サービスの仕様は確認前に断定しない。詳細な判断経緯・作業・検証結果は devlog.md に追記する。
