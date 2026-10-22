# 開発ログ

## 2026-10-22 — Phase 3 小竹向原乗換・旅程生成の詳細検証

- 取得済みGTFS ZIPの停留所・停車時刻・カレンダー関連ファイルを調査。`platform_code` は185件すべて空で、ZIPに `transfers.txt` / `pathways.txt` 等もなく、3・4番線や個別列車のホームは判定不能と記録。
- 新しいローカル解析器 `scripts/odpt_phase3_itinerary_analyze.py` を追加。指定日をservice dayとしてcalendar例外を適用し、同一tripの直通と別trip・反対路線の乗換を分離。乗車・降車禁止、欠損時刻を候補から除外し、時刻差60秒以上をユーザー指定の暫定ルールとして集計。
- 平日2026-10-22、土曜2026-10-24、例外祝日2026-11-03を解析。1分ちょうどの接続候補は順に66組・80組・80組。0分・2分境界、日付跨ぎ、フィード期間外2026-09-18の結果と具体例を `docs/odpt_research.md` に記載。
- 全ての後続列車を組み合わせた全候補数は平日32,105組、土曜24,696組。同一池袋発便に候補が多数重なるため、Ver.0.5向け内部データモデルと、出発便ごとに旅程をまとめる表示案も調査文書へ追記。
- スクリプトを代表日と期間外日で実行して出力を確認し、`git diff --check` を実施。アプリHTML/CSS/JavaScript、取得データ、APIキー類は変更・読み取りせず、外部アクセスとコミットは行っていない。

## 2026-10-22 — ODPT Phase 3 GTFS詳細検証

- 取得済み `local_data/odpt/` のGTFS ZIPとODPT JSONだけを使用。外部API通信、`.env.local` / APIキー読み取り、アプリHTML/CSS/JavaScript変更、コミットは行っていない。
- 副都心線の池袋→氷川台295便中、到着時刻あり248件、空欄47件を個別確認。欠損47件は全てstop_id 905 / stop_sequence 12 / pickup_type 1 / drop_off_type 1 / timepoint 0。通過か停車かはフィードから判定不能と記録。乗降可の停車便では両路線とも到着記録率100%。
- GTFS trip_idの先頭2・末尾2文字を除いた列車番号部分、路線、service_idとODPT calendarを比較。有楽町線199/279、副都心線168/295が同曜日区分で一意一致し、池袋発も一致。IDのみで一致しない便は未対応確定とせず、この規則では未照合と整理。
- 小竹向原のstop_id 606/906が駅名・座標を共有する別stopであることを確認。到着・発車時刻から別trip_idの候補例を作成し、同一trip_idの継続乗車と区別。最低乗換時間が不明のため接続可能とはしていない。
- calendar / calendar_dates / feed_infoの対象日、平日・土日・祝日、期間外、24時超のサービス時刻を記録。GTFS単独で予定ダイヤを表示できる範囲と、欠損・期間・遅延・乗換判定の制約を `docs/odpt_research.md` に追記し、`docs/project_state.md` を更新。
- 解析器 `scripts/odpt_phase3_gtfs_analyze.py` をローカルZIPに対して実行し、出力値を記録と照合した。自動テストは追加していない。

## 2026-10-22 — ODPT実データ調査 Phase 2準備

- 前提資料と既存 `odpt_smoke.py` を確認。現行UI Ver.0.4.2の仕様を維持し、HTML/CSS/JavaScriptは変更していない。
- `scripts/odpt_phase2_fetch.py` を作成。`.env.local` からキーを読み、certifi TLS検証、対象6リクエスト、分類済みエラー、リトライなしでJSONをローカル保存する。
- `scripts/odpt_phase2_analyze.py` を作成。実在するJSONフィールドと駅レコードを列挙し、配置済みGTFS ZIPを調査する。必要列がある場合の旅程は時刻候補としてのみ表示し、運行日・乗換可否を断定しない。
- `.gitignore` で `local_data/odpt/` を除外し、READMEと調査・状態文書に実行手順・未確認事項を反映。
- CodexからODPT/CKANへの通信およびデータ取得は行っていない。実データ取得・解析は未実施。CKAN実配布URL・認証条件を未確認のためGTFS自動取得は未対応。

## 2026-10-22 — ODPT実データ調査 Phase 1

- 東京メトロのCKANカタログで列車／駅時刻表、駅・路線情報、GTFS、GTFS-RT、運行情報の掲載を確認。
- APIキー候補の環境変数は未設定。認証付き取得は行わず、実レコード・実便・小竹向原の接続条件は未確認として `docs/odpt_research.md` に記録。
- 基本ライセンスの商用利用・再配布制限と、API頻度制限の公開条項を確認。更新頻度、数値上限、キャッシュ条件、定型クレジットは未確認。
- 現状と次作業を `docs/project_state.md` に反映。動作コード・UIは変更していない。

## 2026-10-18 — Ver.0.2 構成整理

- 既存の単一HTMLを調査し、画面骨組み、スタイル、表示ロジック、架空列車データを確認。
- CSSを `styles.css`、表示ロジックを `app.js`、架空データを `data.js` に分離。フレームワークや依存ライブラリは追加していない。
- Ver.0.1の企画仕様とVer.0.2のUI改修記録を `docs/product_spec.md` と `docs/ui_spec.md` に統合し、旧ファイルを削除。`README.md` と本ログを追加。
- 副都心線の色を茶系から紫系にして、有楽町線の黄系と識別しやすくした。
- ODPT移行課題としてデータ粒度、運行日・列車識別、接続判定、利用条件、認証、鮮度・障害時対応を記録。

## 確認

静的ファイル構成を確認。実ブラウザー操作・自動テストは未実施。ODPT APIへの接続は行っていない。

## 2026-10-18 — 副都心線カラー修正

- 架空ダイヤの副都心線カラーを `#9C5E31`（ブラウン）に変更。
- UI仕様書の副都心線カラー表記を更新。有楽町線カラーと画面・機能・レイアウトは変更なし。

## 2026-10-18 — UI改善 Ver.0.3

- iPhone標準システムフォントを優先し、列車種別・行先、直通／乗換情報を約14px、補助ラベルを12pxに拡大。
- カウントダウンのタブラー数字、路線色、カードの既存情報構成を維持。情報の折返しと小画面用の列幅を調整し、横はみ出しを抑制。
- 画面上部とカード周辺の余白を圧縮し、6本表示を保ちやすくした。
- JavaScriptの構文確認を実施。Codex環境では375px、390px、430px幅の実ブラウザー表示確認はできなかった。

## 2026-10-18 — UI改善 Ver.0.4

- 320×50px相当の仮広告プレースホルダーを画面下部に固定追加。
- iPhoneの下部セーフエリアを考慮し、メイン領域の下余白を広告枠分確保して本文との重なりを防止。
- 広告SDK・外部ライブラリは追加せず、既存機能・文字設定・路線カラーは維持。
- JavaScript構文と機能コードの非変更を確認。後続のiPhone 12 / Safariスクリーンショットでは広告枠の境界・配置に改善余地が見つかり、Ver.0.4.1の課題へつながった。

## 2026-10-18 — UI改善 Ver.0.4.1

- 広告表示を固定ドックと320×50 CSS pxの本体に分離し、薄い青背景 `#D8E9F8` と青枠 `#3785C9`、控えめな角丸を設定。
- safe-areaはドックの下部paddingで一度だけ加算し、メイン下余白は広告本体・safe-area・20pxの間隔に合わせた。
- `viewport-fit=cover` を確認し、スタイルシートURLにバージョンを付けて古いCSSキャッシュを避ける。
- 後続のiPhone 12 / Safari確認で、初期表示時に広告が最後のカードへ重なる問題が報告された。Ver.0.4.2で上部領域を圧縮して対応。

## 2026-10-18 — UI改善 Ver.0.4.2

- ヘッダーの「MY TRAIN BOARD」と「直近の乗車候補」を削除し、アプリ名・現在時刻を維持。
- 固定目的地を「池袋 → 氷川台」の一行表示にし、表示切替と直通フィルターを44px高の同一操作行へ配置。
- 路線外見出しを削除し、有楽町線→副都心線のグループ順に変更。グループ内は発車順を保ち、本数を先頭カードに表示。発車順モードは全路線を混在させて時刻順表示。
- 広告枠の寸法・色・safe-area処理、架空列車データ、列車カードの文字設定を維持。
- `node --check` と `git diff --check` は通過。簡易DOM確認で路線別順、本数、路線内発車順、発車順表示、直通フィルター、カウントダウン、最早着表示を確認。
- Codexのローカルブラウザー操作環境は起動せず、375px／390px／430pxの個別表示は未確認。プロジェクト状態メモでは、ユーザーによるiPhone 12 / SafariのVer.0.4.2画面確認済みとしている。

## 2026-10-18 — ODPT接続の事前調査

- 現行モックでは停車駅列・運行日・接続列車を保持せず、到着時刻は固定所要分から算出し、乗換待ちは表示だけであることを整理。
- ODPT用データ変換とアプリ内の便・停車・旅程モデルを分離する方針、最低乗換時間・ホーム情報が不明なら接続可と断定しない方針を提案。
- 東京メトロの駅時刻表・列車時刻表をカタログ上の候補として確認。個別レコード、対応付け、接続条件、利用条件はAPI登録後の確認事項として残した。
- APIキー未取得の前提で、API接続やコード変更は行っていない。

## 2026-10-19 — ドキュメント運用の整理

- product_spec.md を確定済み製品仕様、ui_spec.md を確定済みUI詳細仕様、project_state.md を最新状況・未解決課題・次タスク、devlog.md を過去履歴として整理。
- 企画上の候補や将来案は予定／未決定と明記し、現在のコード・UI仕様と区別。
- READMEに4文書の役割と、Codex作業後に関連文書だけを更新するルールを追加。
- 既存の動作コード・画面・データは変更していない。

## 2026-10-22 — ODPT実データ調査 Phase 2

- `local_data/odpt/` の指定6 JSONをローカル解析。外部APIへ再アクセスせず、APIキーや `.env.local` は読み取っていない。
- 列車時刻表は有楽町線843件・副都心線993件。`odpt:trainTimetableObject` は停車順だが、途中駅は主に発車時刻のみ。池袋→氷川台の直通停車列を平日・土休日の両路線で確認した一方、氷川台到着時刻は得られなかった。
- 池袋駅時刻表と列車時刻表は列車IDとcalendarの組で対象方向全件照合。小竹向原到着時刻がなく、待ち時間や乗換候補はこの6 JSONだけでは構成不能と記録。
- 時刻表の実例、欠損・重複、calendar値、駅IDの路線間差、ODPT JSON単独での実現可能性と残課題を `docs/odpt_research.md` に追記。状態メモも更新。
- HTML/CSS/JavaScript、取得済みデータ、アプリ動作は変更していない。コミットなし。

## 2026-10-22 — ODPT Phase 3 GTFS調査・解析準備

- CKANの東京メトロ鉄道関連情報リソースでGTFS/GTFS-JPと基本ライセンスを確認。CKANの表示だけでは実ダウンロードURL・認証・更新日時を確定できず、独立したTransitlandフィード目録で静的GTFS URL、`acl:consumerKey` クエリ認証、version 20261008と有効期間を照合。出典の違いを `docs/odpt_research.md` に明記。
- GTFS調査器を既存Phase 2 JSON解析器から分離して `scripts/odpt_phase3_gtfs_analyze.py` として追加。GTFS主要テーブル、対象駅・路線便・停車時刻、timepoint、運行日例外、ODPT列車番号・池袋発時刻との候補照合を解析する。
- `local_data/odpt/` にZIPがないことを確認。未配置時のスクリプト実行は未解析を案内し、架空データや推測値を生成しない。構文コンパイルと未配置分岐を確認。
- CKANからの安全なブラウザー取得手順とZIP配置後の実行コマンドを調査メモ・状態メモへ追記。ネットワークでGTFS本体を取得せず、`.env.local` / APIキーを読まず、アプリHTML/CSS/JavaScriptは変更していない。コミットなし。

## 2026-10-22 — Phase 3 旅程候補最適化・表示項目検証

- `scripts/odpt_phase3_itinerary_optimize.py` を追加し、平日・土曜・祝日のGTFS日別サービスで、池袋発便ごとに直通と最早到着の小竹向原乗換を比較。待ち上限5/10/15分・上限なし、直通優先の同着規則、60秒以上、乗降可能・時刻ありを適用。
- 代表日では有効な直通がある全便で直通が乗換より早く、同着・乗換短縮は0件。元接続ペアから池袋発便単位に集約した件数、待ち時間上限による削減、1/2/3/5分短縮条件、ODPT種別・行先との一意照合を記録。
- GTFSの路線名・方面・時刻・途中停車順・運行日と、列車種別がGTFSにない点を整理。種別・ODPT行先は一意一致した便だけ補完し、それ以外は推測しない仕様案をまとめた。
- `docs/odpt_research.md` に結果、例、内部データモデル、Ver.0.5実装順序・未決事項を追記し、`docs/project_state.md` と本記録を更新。
- 取得済みローカルデータだけを使用。外部API・`.env.local`・APIキーへのアクセスなし。HTML/CSS/JavaScriptと取得済み生データは変更せず、コミットなし。

## 2026-10-22 — Ver.0.5 Step 1 実ダイヤ旅程生成

- `scripts/odpt_itinerary.py` にオフライン再利用モジュールを実装。GTFS ZIPからcalendar/calendar_dates、feed期間、路線別駅ID、stop_timesを正規化し、同一trip直通・別trip小竹向原乗換、欠損・乗降不可、24時超時刻、番線unknownを扱う。
- 既定接続条件60〜600秒。池袋発tripごとに最早着を1件だけprimaryとして選択し、同着なら直通優先。直通代替と最早乗換候補／候補数は保持する。ODPT JSONはGTFS列車番号・路線・calendarの一意一致と池袋発時刻一致時だけ種別・行先を両区間に補い、生JSONは返さない。
- `scripts/validate_odpt_itineraries.py` と `tests/test_odpt_itinerary.py` を追加。代表日と期間外日を検証し、0/1/2分、60〜600秒条件、複数接続集約、日付跨ぎ、祝日例外、欠損・降車不可、ODPT照合を確認。自動テスト8件すべて成功。
- 実績: 平日439発便、直通287、乗換候補を持つ便417、primaryは直通287・乗換148・有効到着なし4。土曜／祝日各405発便、直通240、乗換候補366、primaryは直通240・乗換156・有効到着なし9。既存Phase 3の60秒以上ペア622／490と整合。0分候補は集計に残るが生成旅程には採用しない。
- `docs/project_state.md` を更新。GTFS/ODPTの生データ、`.env.local`、APIキーに触れず、外部通信なし。アプリHTML/CSS/JavaScriptと公開用データは変更せず、コミットなし。

## 2026-10-22 — Ver.0.5 Step 2A Web UI接続設計

- `app.js` / `data.js` / `index.html` / `styles.css` と製品・UI仕様を読み、現行の相対秒・仮所要分モデルとStep 1のservice-date付き旅程モデルの差を整理。
- `docs/ver_0_5_step_2a_ui_integration.md` にUI項目対応、最小payload、日付・24時超・現在時刻処理、候補選択、欠損表示、local preview分離、Step 2Bの作業順を記録。
- `scripts/export_local_timetable_payload.py` を追加。必要なカードデータと内部metadataだけをJSON化し、repository内への書き出しを拒否する。外部APIやキーを参照しない。
- payload exporterのインメモリ出力検証を追加。HTML/CSS/JavaScriptは変更せず、実payloadをrepositoryやpublicへ配置せず、コミットなし。
- `python3 -B -m unittest discover -s tests -v` は計11件成功。exporterのrepository内出力拒否、repository外出力制約のCLI helpと `git diff --check` も確認。GTFS/ODPTのpayloadファイルは生成していない。

## 2026-10-22 — Ver.0.5 Step 2B-1 JavaScript adapter

- 独立ES module `scripts/timetable_adapter.mjs` を追加。payload schema検証、Asia/Tokyo service-second→epoch変換、未来24時間候補、前日／当日／翌日service day、重複排除、直通filter、路線別・発車順、最早着単一選択を実装。
- カード項目にroute color、既知train typeの日本語表記、destination unknown、直通／乗換・待ち時間、arrival/departure epoch、番線unknown・接続非保証を変換。primary到着なしは推測せず除外理由を保持。
- Node標準 `node:test` で12件実行。日付跨ぎ、feed境界、now前後、24時間窓、service day duplicate、direct/transfer、mode/filter、同着、欠損、不正payloadを確認。通常timezoneと `TZ=UTC` の両方で成功。
- `docs/ver_0_5_step_2a_ui_integration.md` にadapter動作と返却形式を補足し、project stateを更新。`index.html` / `app.js` / `data.js` / `styles.css`、実payload、取得データを変更・生成せず、外部API・秘密情報に触れず、コミットなし。

## 2026-10-22 — Ver.0.5 Step 2B-2 ローカル実ダイヤUI接続

- `/private/tmp/dotchi-ikebukuro-preview/site` にVer.0.4.2の画面スタイルを引き継いだ隔離previewを作成。preview専用 `index.html` / `app.js` は一時領域にのみ置き、adapterをES moduleとして読み込み、既存カードの路線色・表示順・フィルターを維持した。
- payload exporterで当日と前後日のサービスデータを生成し、JST基準の時計、絶対発着時刻、1秒更新カウントダウン、直通／乗換待ち、最早着一件を接続。ロード失敗・古いpayloadはメッセージ表示し、架空データへfallbackしない。種別不明・番線未確認・接続非保証も画面に反映。
- Safariをlocalhost `127.0.0.1:8765` で開き、HTTP 200とカード表示を確認。画面ではGTFS由来の発着時刻・行先、色、カウントダウン、未照合種別、1分乗換注記を確認した。404 faviconは表示データに影響しない。
- adapterで代表日を固定して集計: 平日2026-10-22は435件（直通287・乗換148・1分接続65）、土曜2026-10-24は396件（240・156・80）、祝日2026-11-03は418件（263・155・79）。各ケースで最早着マークは1件、発車順は昇順。通常・土曜・祝日で日別便数が異なることを確認。
- preview実データpayloadは一時Web root内の約1.7MBの最小旅程JSONのみ。比較用土曜・祝日payloadとSafari画面captureはWeb root外の同じ一時ディレクトリに保存。GTFS ZIP、ODPT生JSON、認証情報は一切コピーせず、アプリ本体のHTML/CSS/JavaScript、公開配信物、Git管理対象を変更していない。
- iPhone Safariは未確認。サーバーをloopbackに限定したため別端末から到達できない。実機で確認する場合は制約を維持するUSB等の別経路が必要で、現時点ではMac Safariのレスポンシブ表示確認を案内する。外部通信なし、コミットなし。

## 2026-10-22 — Ver.0.5 Step 2B-2 改善

- preview専用 `preview_selection.mjs` を `/private/tmp/dotchi-ikebukuro-preview/site/` に追加し、路線別は各3件、発車順は全路線6件へ制限。adapterによる未来便・直通filterの後に制限し、見える候補の中で最早着を付け直す。毎秒再評価するため発車後の次候補補充も継続。
- preview専用Nodeテスト6件を追加し、路線別3+3、全体6、少数候補、表示内best、同着の早発優先、発車後の補充を検証。実payloadを14:00 JSTで再生し、line/departure/directOnlyの各6件・best一件・発車後6件補充を確認。Safariでもroute mode 3+3、mixed departure mode 6件、directOnly ON 6件（全て直通）を視認。14:26発車後に次候補へ補充される挙動も実画面で確認。
- previewの再確認用URLに `?directOnly=1` と `?mode=departure` を追加。どちらも一時previewのみの初期状態指定で、通常の画面操作も利用できる。画面captureは `/private/tmp/dotchi-ikebukuro-preview/` に保存。
- 種別の取りこぼし原因は既存ODPT indexが池袋と氷川台を通るODPT停車列に限定していた点。ODPT全便へ広げ、路線・calendar・GTFS trip number・池袋発時刻を照合。valid primaryのID確認率は平日307/435（70.6%）、土休日286/396（72.2%）。増分はすべて乗換旅程の先行便。
- さらにroute/calendar/発車分/別日ID一致から検証したdestination crosswalkで追加候補を比較。既知ID便のholdout 307/307・286/286で候補が同一train IDを選択。ID未確認の一意候補は平日128、土休日107、土休日3便は候補なし。未知便の直接ID証拠はないため、種別を実装補完せず「候補」として記録。
- ODPT副都心線 TrainTimetable内に `odpt:trainType=F-Liner` が107件。GTFSには種別・愛称属性がなく、取得済みODPTにも別サービスブランド属性は確認できない。`reportedTrainType` と `serviceBrand` を分離する内部モデル案を `docs/odpt_research.md` に追記。
- ローカル種別解析器 `scripts/odpt_phase3_train_type_match.py` を追加。GTFS/ODPTのローカルファイルのみ使用。公開HTML/CSS/JavaScript、実データpayload、GitHub Pagesを変更せず、API/秘密情報へアクセスせず、commitなし。

## 2026-10-22 — Ver.0.5 列車種別の確定照合改善

- `scripts/odpt_itinerary.py` のODPT候補索引から氷川台停車条件を外し、列車番号・路線・calendar・池袋発時刻の全一致後に一意性を判定するよう変更。これにより乗換旅程の先行列車も照合対象となる。
- payloadにODPT原コード `reportedTrainType`、独立した `serviceBrand`、GTFS由来行先の `destinationSource` を追加。F-Linerは原値を保持し、adapterが「Fライナー」と表示する。未照合便の種別補完はしない。
- 照合結果は平日307/435、土曜286/396、祝日286/396。平日F-Liner 23件、土休日各20件。未照合は各代表日128/110/110件のまま不明表示。
- Pythonテスト11件、JavaScript adapterテスト13件を通常TZと `TZ=UTC` で実行し成功。preview専用表示件数テスト6件も成功。2026-10-21〜23のpayloadをリポジトリ外で再生成し、路線別3+3・発車順6・直通のみ・各表示内最早着1件・Fライナーラベルをadapter経由で確認。localhostのHTTP応答は200。
- この実行環境ではSafariアプリを `open -a Safari` で解決できず、Safariの画面確認だけ未実施。ローカルpreviewサーバーは127.0.0.1:8765で起動中。
- 外部API・秘密情報・公開用UI・リポジトリ内実payloadに触れず、commitなし。

## 2026-10-22 — GTFS停車パターンによる列車種別識別検証

- 東京メトロ公式の副都心線停車駅表と有楽町線駅案内を確認。副都心線は各停／通勤急行／急行の駅パターンを比較できるが、急行とF-Linerは停車パターンで区別できない。有楽町線公式表には種別ごとの通過区分がなく、全駅停車パターンのみ調べた。
- `scripts/odpt_phase3_stop_pattern_classifier.py` を追加。時刻あり＋少なくとも一方の乗降可を停車根拠、時刻なし＋乗降両方不可の駅行をGTFS上の非旅客停車証拠、駅行なし・その他を判定不能とした。物理的な通過は断定しない。
- 確定ODPTと比較可能な副都心線パターンは平日104、土休日102件で不一致0。未照合便のうち平日46（各停30、通勤急行16）、土休日34（各停34）を分類可能。急行/F-Liner同型9件（土休日）、有楽町線全駅パターン44/36件は列車種別名へ変換しない。
- 確定照合だけの不明率29.4%/27.8%から、各停・通勤急行だけを補助分類しても18.9%/19.2%まで下がる見込み。検証を記録し、表示ロジック・preview・payloadには反映していない。
- 調査記録とproject stateを更新。ローカルGTFS/ODPT以外のデータは解析に使わず、外部API・キー・`.env.local`・公開UIには触れず、commitなし。

## 2026-10-22 — Ver.0.5 停車パターン種別表示をローカルpreviewへ反映

- 停車イベント判定・路線別分類・表示名解決を `scripts/odpt_stop_patterns.py` に共通化し、`odpt_phase3_stop_pattern_classifier.py` と `odpt_itinerary.py` から利用。ODPT一意照合値を優先し、Fukutoshinで検証可能な不一致は `種別不明` と診断属性に保持。停車イベント欠損は分類に使わない。ODPT照合が ambiguous / unavailable の場合はパターンfallbackを行わず、明示的な unmatched のみ分類する。
- payload exporter とJS adapterを更新し、`typeSource`, `typeValidation`, `typeDiagnostic`, `stopPattern`, raw ODPT typeを保持。F-Linerは確定ODPTのみ「Fライナー」、急行同型は「急行型」、有楽町線全駅停車は正式種別でない「全駅停車」として表示。previewの表示件数制御とカウントダウン実装は変更せずadapterだけ差し替え。
- 代表日集計: 平日2026-10-22は435 primary便中、ODPT確定307・パターン表示90・種別不明38。土曜2026-10-24と祝日2026-11-03は各396便中、ODPT確定286・パターン表示79・種別不明31。ODPTのみの不明表示128/435 (29.4%)・110/396 (27.8%) から、汎用「種別不明」表示は38/435 (8.7%)・31/396 (7.8%) へ減少。正式種別の不明率は補助表示を除いて82/435 (18.9%)・76/396 (19.2%)。平日パターン表示90件は各停30・通勤急行16・有楽町全停44、土休日79件は各停34・急行型9・有楽町全停36。
- 分類可能なODPT確定副都心線便との矛盾は平日0/104、土休日0/102。必要イベント不足による分類不能は補完せず。F-Linerを停車駅から断定するケースはなし。
- Python unittest 15件、Node adapter 14件（通常TZ・`TZ=UTC`）、preview-selection 6件が成功。payloadを `/private/tmp/dotchi-ikebukuro-preview/site/timetable.json` へ再生成し、平日/土曜/祝日代表payloadも一時ディレクトリに生成。adapter結果は路線別3+3、発車順6、直通のみ6、各モード最早着1件。既存カウントダウンおよび日付跨ぎはadapterのテストで検証。
- Safariの再確認は `http://127.0.0.1:8765/index.html` を開いて強制再読み込み。画面で路線別3+3件、発車順6件、`?directOnly=1` の直通のみ、各カードの種別ラベルと最早着印を確認。Safariの画面自体は今回の更新後に再撮影していないため、手動再確認が必要。
- 公開HTML/CSS/JS、外部API、資格情報は未変更・未使用。payloadと生GTFS/ODPTはGit管理対象外、commitなし。

## 2026-10-22 — 残存種別不明の全件原因診断

- `scripts/odpt_phase3_unknown_diagnostics.py` を追加し、平日・土曜・祝日の表示可能primary旅程から `typeSource=unknown` を抽出。対象38/31/31便、全件をtrip ID・路線・発時刻・headsign・ODPT状態/候補番号・stop event/時刻/pickup/drop_offと一緒にderived JSONへ出力。ファイルは `/private/tmp` に限定。
- 原因は100/100件で別trip乗換journeyの第一GTFS tripが小竹向原終端、氷川台がtrip区間外。イベント記録なしを通過とは判断しない。要町・千川は85便で時刻あり・乗降可、15便で時刻なし・pickup/drop_off両方不可の明示通過記録。小竹向原は全件時刻あり・乗降可。平和台も第一trip外でイベントなし。
- 現行ID切り出しとODPT trainNumberは全件不一致。一方、秒単位発時刻候補、先頭ゼロ/可変末尾を考慮した番号候補、held-out destination-headsign照合は100件すべて一意。タイプ候補内訳は平日Local29/Express3/SemiExpress4/RapidExpress2、土休日各Local23/Express3/F-Liner3/SemiExpress2。候補は独立したID原票ではないので自動補完へは反映せず、採用条件を調査文書に記録。
- 番号変形の対照879/879が既知ODPT `odpt:train` に一意一致。停車パターンでは、副都心線39便が要町・千川停車から各駅停車候補、15便は通過駅ペアでも氷川台欠落で通勤急行/急行系を分離できない。有楽町線46便は代表駅のみ停車記録で全区間各駅停車とは確定しない。
- 要求どおり名称変更・表示ロジック・アプリ・previewには手を入れず、research/state/devlogと診断スクリプトのみ更新。外部API/資格情報なし、commitなし。

## 2026-10-22 — GTFS列車番号正規化・ODPT照合器

- `scripts/odpt_train_matcher.py` に限定的なtrip_id parserと照合器を追加。観測した `00` padding、唯一の `20` 末尾例外、数字先頭ゼロを候補化。route、calendar、ODPT train number、池袋発秒、独立destination/headsign対応、GTFS有効停車イベント列とODPT駅順がすべて整合する場合だけ `confirmed` を返す。候補一意と確定を別statusにし、複数候補、番号衝突、行先対応不足、順序矛盾は保留する。
- 代表日primary 1,227便を実データで照合。旧確定879/1,227（71.6%）から1,221/1,227（99.5%）へ増加。既知879件は全件同じODPT trainを回帰確認。残存unknown100件はweekday38、SaturdayHoliday31（土曜）、SaturdayHoliday31（祝日）で全件確定。ほかの未照合248件中242確定、6件（小川町行の3 tripを土曜/祝日で重複）はdestination crosswalk不在により保留。
- 種別raw値の対象100件内訳: 有楽町線 Local36 / SemiExpress8 / RapidExpress2、副都心線 Local39 / Express9 / F-Liner6。副都心線の線内種別、他社線種別、F-Liner愛称を独立属性にし、F-Liner raw値をExpressへ機械置換しない。有楽町線のthrough-service raw typeは線内種別とも他社種別とも断定せず未スコープ値で保持。
- `tests/test_odpt_train_matcher.py` を追加して13件。number形、曜日/路線、衝突、同時刻複数候補、行先/駅順不一致、保留、type scope、879既知対照、100 residual、全primary便の残り6件を確認。`python3 -B -m unittest discover -s tests -v`: 28件成功。
- 派生検証レポートは `/private/tmp/dotchi-ikebukuro-train-match-report.json` に保存。照合器を`ItineraryGenerator`/exporter/adapter/UIへ接続しておらず、プレビュー・payload・画面表示は変更なし。ローカルデータのみ、外部API・資格情報なし、commitなし。

## 2026-10-22 — 照合器統合とpreview切替応答最適化

- `scripts/odpt_itinerary.py` で運行日別ODPT索引と確認済destination/headsign crosswalkを構築し、`odpt_train_matcher.py` を旅程生成へ統合。raw type URI・報告された種別・メトロ種別・他社/未適用種別・Fライナー愛称・照合方法/理由を内部DTOとexport payloadへ追加。矛盾や根拠不足の候補は未確定を維持。`scripts/timetable_adapter.mjs` にもこれらの属性を保持する変換を追加。
- 回帰validatorはknown control 879件を維持、residual unknown 100件を確定、その他の未照合248件中242件確定、6件候補未確定。代表日primaryの種別表示は平日各停359・通勤急行30・急行14・Fライナー23・不明9。土曜/祝日は各停335・急行28・Fライナー24・不明6・急行型補助3。FライナーをExpressへ変換せず、急行型補助も正式急行へ昇格しない。through-serviceの有楽町線種別はメトロ線内名へ流用しない。
- 既存UIの約2秒切替原因は、1,317便すべてのpayload検証・日時formatter/card再生成・候補sortを毎秒繰り返し、全カードDOMを差し替える処理。切替時の再fetchはなかった。adapterに `prepareTimetablePayload` を追加しIntl formatterを共有。全候補の二度sortを一度sort＋reduceへ変更。preview appは操作時にだけ候補生成し、毎秒は時計/カウントダウン文字列のみ更新。発車到達・JST日付変更・payload古さ変更時には再描画する。路線別3+3、発車順6件、filter後に件数制限、最早着マークはpreview_selectionで維持。
- 実測: Nodeで同一1,317便payloadの15回計測（preview同様onTiming有効）。raw payloadはadapter中央値36.47ms/最大50.10ms、候補走査26.89/39.52ms、sort 0.05/0.34ms。準備済みpayloadはadapter中央値0.88ms/最大4.47ms、候補走査0.57/1.71ms、sort 0.03/0.22ms。過去に採取した旧adapter中央値352–618ms/p95 513–729msと比べ改善。Mac Safariの実ブラウザーevent-to-DOM計測は未実施であり、Node数値をSafari数値として扱わない。ローカルpreviewに `window.__dotchiPreviewPerf` を追加し、fetch回数・候補走査/sort/adapter/selection/DOM/event→DOM/次frameを直近50操作分表示可能。
- ローカルpreview payloadを `/private/tmp/dotchi-ikebukuro-preview/site/timetable.json` に2026-10-21〜23の1,317便で再生成し、更新adapterを作業コピーへ配置。サーバは起動せず停止状態を維持。
- 再生成した実payloadをJST 2026-10-22 06:00でadapter+preview selectionへ通し、line mode 3+3、departure mode 6件、直通filter off/on、最早着印各1件を確認。direct-only時は表示6件全て直通。
- 検証: Python unittest 28件、Node adapter 16件（通常TZ・`TZ=UTC`の両方）、preview selection 6件、Node syntax check、matcher report（879 control + 100 residual + 242 confirmed + 6 held）成功。
- Safari再確認: `cd /private/tmp/dotchi-ikebukuro-preview/site && python3 -m http.server 8765 --bind 127.0.0.1` でlocalhost限定起動後、Safariで `http://127.0.0.1:8765/index.html` を開く。Consoleで `window.__dotchiPreviewPerf` を確認し、路線別/発車順と直通filterを各10回ほど切替えて、`history` の `eventToDomMs`, `adapterMs`, `candidateMs`, `sortMs`, `selectionMs`, `domMs` を読む。`fetchCount` が1のままかも確認する。発車後の補充、3+3/6件、最早着1件も確認する。終了時にサーバーを停止。preview・payloadは作業コピー/`/private/tmp`のみ、公開UI変更・外部通信・秘密情報参照・commitなし。
