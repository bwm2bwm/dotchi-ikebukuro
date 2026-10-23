# プロジェクト状態

## 公開モック準拠のローカルpreview UI

- `_local_preview/index.html` は公開モックと同じヘッダー／時計、注意表示、ルート枠、44px操作行、カードDOM、下部広告dockの構成。`prepare_preview.py` はroot `styles.css` をローカル出力へコピーし、preview.cssで状態表示・折りたたみmetadataを補う。
- 実ダイヤ側はローカルデータ注記、適用期間バナー、安全停止、payload適用期間／生成日時／GTFS・ODPT更新日時／Web build日時の個別表示を維持。未取得日時は「未取得」。
- adapter、selection、列車数制限、T01のpayload生成・検証・安全差し替えロジックは変更していない。prepare_previewにはroot CSSのコピーだけを追加。再生成によりpayload生成日時は更新される。iPhone Safari目視確認が残る。

## iPhone Safari縦レイアウト調整

- 6列車カード、公開モック由来カード寸法、320×50広告dock、本文の広告高＋20px＋safe-area予約を維持。通常時の最下部注意文は通常画面から除き、payload詳細内へ移動。例外発生時の状態バナーは引き続き表示。
- 上部のCSS余白を合計20px圧縮。iOS Safariではヘッダーをsafe area内側のsticky位置に置き、ステータス表示との重なりを抑制する。実機での最終目視確認が残る。

## ローカルpreview更新（T01）

- `python3 _local_preview/prepare_preview.py` は保存済みGTFS/ODPT必須ファイルを確認し、JST前日・当日・翌日のpayloadをリポジトリ外の一時stageで生成します。
- stageのpayloadを既存adapterでJSON/schema/必須metadata、適用期間、現在必要なservice dayについて検証し、合格後にのみ永続previewを置換します。生成・検証エラーでは既存siteを維持します。外部通信・データ再取得はありません。
- 元データ更新時刻・Web build時刻は未確認のままnull。payload生成時刻は更新時に変わりますが、元データが古い可能性は残るため鮮度保証ではありません。24時間TTLなし。
- 自動テスト: `python3 -B -m unittest discover -s tests` とNodeテスト。実payload再生成には保存済みローカルデータが必要です。

更新日: 2026-10-23

## T14 目的地拡張 Phase 1

- `scripts/odpt_itinerary.py` に対象8駅の駅カタログを追加し、有楽町線／副都心線それぞれのGTFS stop IDと池袋からの進行順を内部管理する。対象は要町・千川・小竹向原・氷川台・平和台・地下鉄赤塚・地下鉄成増・和光市。
- 旅程生成器は `destination_station_id` を受け取れる。旅程検証済みの既定値は氷川台のみで、他7駅は「カタログ済み・旅程未検証」として生成を拒否する。これにより未検証駅の通過列車を到着候補に誤認しない。
- exporterは旅程の到着駅IDを使うが、既定氷川台のpayload値は維持。preview UI・adapter・selection・T01更新手順・公開モックは変更しない。
- 追加駅の経路成立／データ不足の詳細分類はPhase 2/3でGTFSの停車・乗降・運行日カバレッジ検証と併せて実装する。GTFSの別tripを直通扱いする拡張は行っていない。

## T14 目的地拡張 Phase 2

- 要町・千川・小竹向原を旅程生成可能にした。池袋で乗車可能な同一GTFS tripに対象駅の停車記録があり、停車順・時刻・降車可が整合する場合だけ直通候補を生成する。別trip接続は行わない。
- 目的地別payloadの日次 `destinationStatus` は `normal` / `no_candidates` / `data_insufficient` と路線別件数を保持する。adapterは必要運行日のデータ不足をfail-closedし、検証済み候補なしとは区別する。未対応・不正状態も列車を出さない。
- 保存済みGTFS/ODPTで平日・土曜・祝日の候補数、通過・不足を検証。既定氷川台payloadは保存済みpreviewを基準に `generatedAt` 以外すべて一致。UIとT01更新フローは未変更。
- Phase 3対象は平和台・地下鉄赤塚・地下鉄成増・和光市。Phase 4で目的地選択UIとiPhone Safari検証を行う。

## ローカル実ダイヤpreview・T02/T03（2026-10-23）

- 永続previewソースを [`_local_preview/`](../_local_preview/) に置く。GitHub PagesはリポジトリrootをJekyllで配信する構成（Pages workflow、`.nojekyll`、Jekyll設定ファイルなし）で、underscore始まりのpreviewディレクトリはJekyll出力対象外。公開デモのroot `index.html` / `app.js` / `data.js` / `styles.css` は変更しない。
- 実行用サイトとpayloadは `~/Library/Application Support/dotchi-ikebukuro-preview/site/` に生成し、GTFS/ODPT生データ・実payload・実行コピーはGit管理外。再生成は `python3 _local_preview/prepare_preview.py`、起動はlocalhostにbindしたPython HTTP server。
- adapterはJST適用期間 `[startsAt, endsAt)` と、現在日を中心とした前日・当日・翌日のうちfeed期間内にある必須service dayを検証する。24時間payload TTLは撤廃。24時間は表示候補horizonとして維持。必要service day不足・期間外は空表示と状態メッセージ。
- T02/T03のstatus messageは専用preview bannerへ接続。payload取得失敗・JSON/必須metadataエラーも列車カードを出さずエラー表示。正常だが候補がない場合は別の空状態を表示。表示は路線別各3件／発車順6件、直通filter、表示対象内最早着、東京時計・発車countdown。
- 現在の永続preview生成物: 2026-10-22〜24の3日、1,283便、GTFS version 20261008。adapterの実payload判定はvalid、HTTP index/payload/moduleは200。100回のNode loop（line/departure/direct boardを各回生成）の合算は中央値2.17ms / p95 6.90ms（Safari値ではない）。
- Nodeテスト25件は通常TZ・`TZ=UTC`双方成功、Python unittest 28件成功、JS/Python syntax check・`git diff --check`成功。Safariアプリは自動操作環境から利用できず、目視は未実施。Mac Safariでの再確認手順はREADME。
- 元preview専用ソースは一時領域と共に失われたため、UI細部の完全一致は保証しない。再構成した画面でSafari目視確認が残る。

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

1. Step 2B-2のローカル検証結果をレビューし、実装仕様への採用範囲を決める。
2. Step 2B-3で承認済みの範囲をアプリ本体へ接続する前に、payload更新手順・鮮度・欠損便表示を確定する。
3. iPhone実機確認が必要な場合は、localhost限定条件を維持できる別のアクセス方法を決める。

## Phase 3旅程最適化の更新（2026-10-22）

- `scripts/odpt_phase3_itinerary_optimize.py` を追加。保存済みGTFS ZIPとODPT JSONから、平日・土曜・祝日の直通比較、待ち上限5/10/15分・上限なしでの乗換候補、GTFS表示項目、ODPT列車種別の一意照合を再現できる。
- 有効な直通と乗換の双方を比較できた代表日3日では、全待ち上限で直通が最早、同着0、乗換による短縮0。乗換のみの親便は平日152、土曜・祝日162（待ち上限なし）だが、うち直通行に時刻欠損／降車不可の便が13／34。乗換のみを直通より早いと数えない。
- 元接続組→親便集約数は平日10分上限622→417、土曜・祝日490→366。上限なしは32,082／24,682組となり、初期表示に全接続を並べない設計が必要。
- GTFSから路線名・headsign・時刻・運行日は取得可能だが、列車種別列はない。保存済みODPTは一意照合分のみ種別／行先補完に使い、未照合便は不明のままにする。
- Ver.0.5案: 池袋発便ごとに最早旅程を主表示し、直通を代替候補として保持。直通優先の同着規則、60秒暫定乗換基準、番線不明・接続保証なしをモデル化する。待ち上限5/10/15分、乗換案の初期表示、欠損便の扱いは未決定。詳細・件数表は [odpt_research.md](odpt_research.md)。
- アプリ本体と取得済みデータは未変更。コミットなし。

## Ver.0.5 列車種別の確定照合改善（2026-10-22）

- `scripts/odpt_itinerary.py` のODPT索引を全TrainTimetableレコード対象に変更。GTFS列車番号・路線・運行日区分・池袋発時刻の全条件が一致し、一意なレコードだけ種別とODPT行先IDを補う。乗換先行列車に不要な「氷川台停車」条件を撤去。
- `reportedTrainType` にODPT原コードを保持し、`serviceBrand` は独立項目として `null`。F-Linerは「Fライナー」、Expressは「急行」と表示し、両者を同一視しない。未照合は種別不明。日本語行先はGTFS `trip_headsign` 由来として出所をpayloadへ記録。
- 主旅程の確定照合は平日307/435（70.6%）、土曜286/396（72.2%）、祝日286/396（72.2%）。旧197/435・170/396から改善。F-Linerは平日23便、土曜・祝日各20便を原コードから表示。
- Pythonテスト11件成功。adapterテスト13件が通常TZ・`TZ=UTC` の双方で成功。preview selectionテスト6件成功。更新payloadをadapterへ読み込み、路線別3+3、発車順6、直通のみ6、各表示内の最早着1件、Fライナー表示を確認。preview HTTPは127.0.0.1で200応答。
- 今回の実行環境ではSafariアプリを `open -a Safari` で特定できず、画面の自動再確認はできなかった。Safariでの手動確認は [ローカルpreview](</private/tmp/dotchi-ikebukuro-preview/README.txt>) の手順を使う。
- ローカルpreviewは `/private/tmp/dotchi-ikebukuro-preview/site` のみ更新。公開HTML/CSS/JavaScript、GTFS/ODPT生データ、Git管理下のpayloadは変更・追加しない。詳細照合条件と種別内訳は [odpt_research.md](odpt_research.md)。

## GTFS停車パターンによる種別識別検証（2026-10-22）

- [odpt_phase3_stop_pattern_classifier.py](../scripts/odpt_phase3_stop_pattern_classifier.py) を追加。GTFS stop_timesの時刻・pickup/drop-off・駅レコード有無を検証し、保存済みODPT確定種別と平日・土曜・祝日で比較した。表示ロジック・preview payloadには反映していない。
- 副都心線は要町・千川・小竹向原・氷川台の記録が分類できる場合、各停／通勤急行／急行停車パターンを識別。急行停車パターンからF-Linerは特定しない。有楽町線は公式停車駅表に種別別通過区分がなく、全駅停車パターンまでを独立情報として記録し、列車種別名には変換しない。
- ODPT確定便との比較可能な副都心線サンプルで矛盾は0件（平日104、土休日102）。未照合便では平日46、土休日34を各停／通勤急行パターンに分類できる見込み。これを別source付きで採用した場合、正確な種別不明率は29.4%→18.9%、27.8%→19.2%となる見込み。急行/F-Liner同型、有楽町線全駅パターンは別属性であり、正確な種別判明率には含めない。
- 詳細件数、未照合trip例、条件不足・誤判定リスク、公式停車駅表のURLは [odpt_research.md](odpt_research.md)。外部APIなし。生データやpreviewは変更せず、commitなし。

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

## Ver.0.5 Step 2B-2 — 実ダイヤのローカルUI接続（2026-10-22）

- リポジトリ外の [`/private/tmp/dotchi-ikebukuro-preview`](</private/tmp/dotchi-ikebukuro-preview>) にpreview作業コピーを作成。元の `index.html` / `app.js` / `data.js` / `styles.css` は変更せず、preview専用HTML・JSだけを一時領域内で作成。`data.js` の架空便はpreviewへ含めていない。
- [export_local_timetable_payload.py](../scripts/export_local_timetable_payload.py) で2026-10-21〜23の最小表示payloadを生成し、`site/timetable.json` に配置。3運行日・各439発便、GTFS版20261008、有効期間2026-09-19〜2027-03-12。GTFS ZIP、ODPT生JSON、秘密情報はsiteへコピーしていない。
- `timetable_adapter.mjs` 経由で路線別・発車順、直通filter、現在から24時間内候補、JST時計／カウントダウン、直通／小竹向原乗換・待ち時間を表示。路線別は各路線3件、発車順は合計6件に制限し、filter後に件数を切る。最早着は表示6件内で一件選び、発車後の毎秒再描画で後続便を補充する。行先・種別不明は不明表示、時刻データ読込失敗・payload鮮度超過で架空便へfallbackしない。
- Mac Safariで `http://127.0.0.1:8765/index.html` を開いて画面表示を確認。カードの実発時刻・到着時刻・残り時間、路線色、未確定列車種別、乗換注記を視認。ローカルHTTPのHTML/CSS/JS/adapter/payloadはすべて200応答。サーバーは検証後停止。
- 日付を固定したadapter集計: 平日2026-10-22は表示候補435（直通287、乗換148、うち待ち60秒65）、土曜2026-10-24は396（直通240、乗換156、60秒80）、祝日2026-11-03は418（直通263、乗換155、60秒79）。各ケースで発車順整列と最早着マーク1件を確認。実時刻における画面候補数は時間経過で変動する。
- 過去previewの一時保存先と起動例。現在の永続保存先と起動手順は本書先頭のローカルpreview状態を参照。過去版は生成24時間TTLだったが、現在は必要運行日カバレッジ判定へ置き換えた。
- iPhone実機は未確認。`127.0.0.1` はMac自身に限定されるため、別端末のSafariから直接アクセスできない。Mac Safariのレスポンシブデザインモードでは画面幅の確認ができるが、実機接続にはlocalhost限定制約を維持する別方式の検討が必要。
- 外部APIアクセス、`.env.local` / APIキー読取、GitHub Pages反映、公開データ生成、commitはなし。実ダイヤHTML/JS/payloadはすべてリポジトリ外。

## Ver.0.5 Step 2B-2 改善 — 表示件数・種別照合（2026-10-22）

- ローカルpreviewの [`app.js`](</private/tmp/dotchi-ikebukuro-preview/site/app.js>) に表示選択module [`preview_selection.mjs`](</private/tmp/dotchi-ikebukuro-preview/site/preview_selection.mjs>) を追加。路線別3+3件、発車順合計6件、直通filter後の枠詰め、表示候補内の最早着一件、発車後の後続補充を実装。リポジトリ内アプリコードは未変更。
- 一時領域の `preview_selection.test.mjs` 6件が通過。実payloadでも路線別6件・発車順6件・直通のみ6件（代表時刻14:00）、最早着1件、最初の便発車後も6件へ補充されることを検証。Safariでも路線別3+3、発車順混在6件、`?directOnly=1` の直通6件を視認し、14:26の発車後に次の候補へ入れ替わることを確認。
- [odpt_phase3_train_type_match.py](../scripts/odpt_phase3_train_type_match.py) を追加。既存ID照合がODPT停車列に氷川台を要求し、乗換列車の種別を落とす条件を確認した。全ODPT時刻表で route/calendar/trainNumber/池袋発秒を照合すると、平日valid primary 435便中307（70.6%）、土休日396便中286（72.2%）の種別をIDで確認。既存の氷川台経由indexでは197/435・170/396だった。
- 行先ID・GTFS headsign・池袋発分を使うholdout照合では、ID既知便の同一train ID選択が307/307・286/286。ID未確認の追加一意候補は平日128、土休日107（3件は候補なし）。候補規則は既知便に対して100%だったが、未確認便自体の独立ID裏付けではないため、実装上の種別補完はしていない。
- 保存済み副都心線ODPT TrainTimetable 993レコード中107件の `odpt:trainType` が `F-Liner`。別個のサービス愛称属性は取得済みJSON/GTFSには見当たらない。モデルでは原 `reportedTrainType` と独立 `serviceBrand` を分け、後者は公式識別値が得られるまで不明とする。詳細は [odpt_research.md](odpt_research.md)。
- adapter既存テストは通常／`TZ=UTC` 各12件通過。`git diff --check` 成功。実ダイヤpayloadは `/private/tmp` に限定し、外部通信・秘密情報・commitなし。

## Ver.0.5 停車パターン種別表示 — ローカルpreviewのみ（2026-10-22）

- [odpt_stop_patterns.py](../scripts/odpt_stop_patterns.py) を共有判定器として追加。確定ODPT値を優先し、副都心線の矛盾は表示保留＋診断属性として保持。パターン補完はODPT `unmatched` のみ対象。欠損停車イベントは推測しない。
- payloadとadapterに種別ラベル・根拠source・適用検証・診断を追加。ODPT確認済みF-Linerは「Fライナー」、未照合急行同型は「急行型」、有楽町線全駅停車は補助表示「全駅停車」。F-Linerへのパターン推測はしない。
- 実ダイヤをリポジトリ外の preview payload へ更新。平日435便はsource別にODPT 307 / GTFS pattern 90 / unknown 38。土曜・祝日各396便は286 / 79 / 31。汎用「種別不明」表示は29.4%→8.7%（平日）、27.8%→7.8%（土曜・祝日）。補助表示を除いた正式種別不明率は18.9% / 19.2%。
- 分類可能な確定ODPT副都心線便と矛盾0件（平日104、土休日102）。このサンプルとGTFS版に限定した結果であり、有楽町線全停・急行型は正式種別判明件数に数えない。
- Python 15件、adapter 14件（通常TZ / UTC）、preview selection 6件が通過。件数枠3+3／6、直通filter、最早着一件をpreview adapterと選択moduleで確認。Safariは強制再読み込み後に表示ラベルを確認する手順をdevlogへ記載。今回の更新後のSafari画面再撮影は未実施。
- 変更したのは解析・export・adapter・テスト・docsのみ。公開版HTML/CSS/JSや配信payloadは変更なし。payloadは `/private/tmp/dotchi-ikebukuro-preview/` に限定し、外部API・認証情報なし、commitなし。

## Ver.0.5 残存「種別不明」全件原因診断（2026-10-22）

- [odpt_phase3_unknown_diagnostics.py](../scripts/odpt_phase3_unknown_diagnostics.py) を追加。平日38・土曜31・祝日31便すべてについてGTFS停車イベント、pickup/drop-off、池袋発、行先、ODPT候補列車番号と候補種別を再現出力する。診断JSONは `/private/tmp/dotchi-ikebukuro-unknown-diagnostics.json` のみ。
- 100便すべては別trip乗換のprimary旅程で、池袋発の第一tripが小竹向原で終端し、氷川台はそのtrip区間外。氷川台を通過扱いにはしない。区間内の駅時刻欠損・乗降禁止は0便。要町・千川は85便が停車証拠、15便が明示通過証拠。
- 現行ID切り出しでは100便全件ODPT unmatchedだが、実運行日区分の時刻表に秒単位の池袋発候補が全件ある。先頭ゼロ/可変末尾を含む番号表記候補では100/100が一意となり、別日destination-headsign crosswalkも100/100一意。既知照合879件の対照で番号候補一意・ODPT train一致は879/879。未照合自体の独立ID証明ではないため推奨条件として記録し、表示ロジックは未変更。
- 停車パターンのみで副都心線「各駅停車」と推定できる余地は平日17・土休日各11便。通過ペア15便は通勤急行/急行/F-Linerを区別できない。急行型を「急行」と呼ぶ変更はF-Liner誤表示になる。有楽町線「全駅停車」も4代表駅のみのパターンから正式種別「各駅停車」へ一括変更しない。
- 土曜/祝日31件のGTFS trip IDは全件同一。異なる運行日として重複カウントしない。詳細集計・例・名称案は [odpt_research.md](odpt_research.md)。preview、公開アプリ、表示ロジックは変更なし。

## Ver.0.5 列車番号正規化・ODPT照合検証（2026-10-22）

- 再利用照合器 [`odpt_train_matcher.py`](../scripts/odpt_train_matcher.py) と検証スクリプト [`validate_odpt_train_matching.py`](../scripts/validate_odpt_train_matching.py) を追加。GTFS trip_id構造は当該feedで観測した形式に限定し、`00` padding、唯一の `20` 末尾例外、数値先頭ゼロを候補化する。路線、calendar、池袋発秒、ODPT行先/headsign対応、実停車駅順まで一致する場合のみ確定。
- 既知879件を全件回帰確認。3代表日のprimary旅程1,227件中、従来の確定照合879件（71.6%）から、新照合1,221件（99.5%）へ増加。残存「種別不明」100便は平日38、土曜31、祝日31の全件で確定。その他の未照合248件では242件確定、6件は小川町行先crosswalk根拠がなく保留。
- 新規テスト13件を含むPython全28件が成功。詳細な未確定理由・型スコープ評価は [`odpt_research.md`](odpt_research.md)。詳細JSONはリポジトリ外 `/private/tmp/dotchi-ikebukuro-train-match-report.json`。
- 照合器を既存旅程生成器・payload exporter・ローカルpreview・UIには未接続。公開HTML/CSS/JS、表示、payloadは変更していない。表示接続時はODPT原種別、メトロ線内種別、他社線種別、F-Liner愛称を別フィールドに保ち、行先crosswalk未確立の候補は不明のまま扱う。
- ローカルGTFS/ODPTのみ使用。外部通信、`.env.local` / APIキー読取、payload公開、commit/push/mergeなし。

## 計画中・未決定の企画

- 目的地候補として10駅案があるが、最終リストではない。
- 目的地選択・最近使った駅の保存は予定で、方式は未決定。
- Cloudflare Pages + Workers等は正式ホスティング候補に留まる。
- Google AdSense等の広告、任意支援サービス、公共交通オープンデータチャレンジ応募は検討段階。採用・応募は未決定。
- 版数／アプリ更新日時を表示する案がある。時刻表データ更新日時とは分けて検討する。

## 作業上の注意

実ダイヤ導入までは架空データの警告を残す。ODPT仕様、データ提供状況、利用条件や外部サービスの仕様は確認前に断定しない。詳細な判断経緯・作業・検証結果は devlog.md に追記する。

## 有楽町線種別補完・T08/T09表示改善（2026-10-23）

- 有楽町線のroute 6に限り、ODPT `unique_match`・池袋乗車可能・要町/千川/小竹向原の有効かつ順序整合した停車記録・raw through-service type保持・例外/矛盾なしを満たし、氷川台まで有効な旅程がある便を `各駅停車` と表示する。sourceは `official_route_rule`。ODPT raw code、照合結果は維持。15 tripのID置換は行わない。
- 2026-10-22平日、10-24土曜、11-03祝日のpreview表示候補における種別不明は9/435→0/435、6/396→0/396、6/396→0/396。追加の無効旅程レコード1/3/3件は補完せず不明のまま。ODPT原種別はpayload上も維持する。
- 種別名と行先を独立表示。急行/通勤急行は強調、Fライナーは愛称として別の下線表現、停車パターン由来の補助表示は控えめ、種別不明は控えめな明示。各駅停車は通常色。カードサイズ、公開モック、広告dock、safe-areaは変更なし。
- 2010年東京メトロの有楽町線各駅停車化資料、2026年改正資料、S-TRAIN FAQなどの根拠・適用条件・再確認事項は [`odpt_research.md`](odpt_research.md) に記録。ダイヤ改正時に再検証する。
- 外部API・資格情報アクセスなし。実ダイヤ元データとpayloadは変更・Git追加せず、公開モックのrootファイルも変更なし。Safari実機での最終目視は未実施。

## Ver.0.5 照合器統合・preview応答改善（2026-10-22）

- `scripts/odpt_train_matcher.py` を `ItineraryGenerator` とexporterへ接続。known control 879/879維持、100/100 residual unknownを確定、その他248件のうち242確定・6保留。6件は土休日3 tripの重複表示で、独立したdestination/headsign根拠が不足するため未照合を維持。
- ODPT原種別URI、メトロ線内種別、他社線種別候補、適用区間未確認値、Fライナー愛称をpayload・adapterに分離保持。3代表日の「種別不明」表示は平日9/435、土曜・祝日各6/396。土休日各3件の急行同型は補助表示のままで正式な急行にしない。Fライナーは愛称のみ表示。詳細と例外は [`odpt_research.md`](odpt_research.md)。
- ローカルpreviewは `/private/tmp/dotchi-ikebukuro-preview/site`。payloadは2026-10-21〜23の3日分1,317便で再生成済み。SafariでのUI接続確認は可能だが、今回の画面操作とSafari timing実測は未実施。previewサーバは停止中。
- 原因は毎秒全件のpayload検証・カード作成・sortと全カードDOM差し替え。切替時は一度準備したpayloadを使い、表示対象だけをDOM反映。毎秒は時計と6件以下のカウントダウン表示だけを更新し、発車到達・JST日付変更・payload freshness変更で候補を再生成。Safari用計測値は `window.__dotchiPreviewPerf` を参照。
- 1,317便に対するNode adapter測定（15回）は、準備済みpayloadのadapter全体中央値0.88ms / 最大4.47ms、未準備raw payloadは中央値36.47ms / 最大50.10ms。prepared時の候補走査は中央値0.57ms / 最大1.71ms、sortは0.03ms / 最大0.22ms。旧版adapterの測定中央値352–618ms / p95 513–729msと比較できるが、これらはSafariのevent-to-DOM値ではない。Safari実測は未取得。
- 検証: Python unittest 28件成功、JS adapter 16件成功（通常TZ・`TZ=UTC`）、preview selection 6件成功。実データpayloadで路線別3+3 / 発車順6、direct filter on/off、best mark1件、filter後のtransfer除去を確認。matcher validatorはknown879、residual100、other matched242、held6を再現。公開HTML/CSS/JSは未変更。実ダイヤpayloadとrawデータはGit管理対象外、外部通信・資格情報参照・commitなし。
