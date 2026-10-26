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
# 2026-10-23 — 実ダイヤpreview再構築・T02/T03

- preview専用のHTML/CSS/ES moduleと再生成scriptを `_local_preview/` に追加。Pagesはroot/Jekyll方式で、underscore directoryはJekyll出力対象外。公開rootの `index.html`, `app.js`, `data.js`, `styles.css` に変更なし。
- 出力先を `~/Library/Application Support/dotchi-ikebukuro-preview/site/` に固定。payload・実行コピーは非公開・Git外に配置し、出力directory mode 0700、payload mode 0600。GTFS/ODPTの保存済みローカルデータのみ使用。
- exporter payloadに適用期間、GTFS/ODPT source update time、web app build timeを区別して保持。元ファイルから更新時刻・build時刻を確認できないため3値はnull。JST適用期間は `[validFrom 00:00, validThrough翌日00:00)`。
- adapterの24時間payload TTLを削除。期間判定に加えて前日・当日・翌日のfeed期間内service dayがpayloadに揃うか毎秒検証し、不足／期間外は列車を返さない。現在から先24時間のcandidate horizonは維持。
- previewへstatus banner、payload fetch/JSON/schema失敗表示、通常候補なし状態、路線別3+3／発車順6件、直通filter、表示候補内最早着、JST時計、カウントダウンを接続。毎秒はadapter候補計算と既存カードのcountdown更新を行い、selection signatureが変わる場合のみDOM再描画。preview perf history 50回を `window.__dotchiPreviewPerf` に保持。
- 実payload: serviceDate 2026-10-22〜24、GTFS version 20261008、池袋発1,283便。adapter valid、路線別3+3／発車順6／直通のみ、best一件、countdownを実payloadで確認。100反復（1回あたりline/departure/direct board）合算時間中央値2.17ms、p95 6.90ms（Node測定、Safari性能値ではない）。
- 検証: JS 25件（通常TZ・`TZ=UTC`双方）、Python unittest 28件、preview JS/Python syntax check、`git diff --check`成功。localhost HTTPでindex/payload/moduleを200確認。Safari操作環境がSafariアプリへ接続できず、Safari目視は未実施。
- Mac Safari手順はREADMEの「ローカル実ダイヤpreview」を参照。歴史上のpreviewソースは失われたため、画面細部は完全一致を保証しない。外部API、`.env.local` / API key、生データの再取得、GitHub Pages変更、commit/push/mergeなし。
# 2026-10-23 — T01 ローカルpreview更新の安全化

- `prepare_preview.py` を入力確認→同じ出力filesystem上の一時stage生成→Node adapter検証→成功後置換へ変更。payloadの形式・必須metadataに加え、現在時点で必要なservice dayをadapterで検証する。24時間TTLは設けない。
- stage検証前の例外では既存previewに触れない。置換中にstage配置が失敗した場合は退避した既存siteを戻す。
- payload validatorとstage/失敗保護/必須入力/日付跨ぎのPythonテストを追加。READMEとproject_stateに更新手順・鮮度上の制約を記録。
- 保存済み元データの更新日時・Web build日時は不明のためnullのまま。payloadを再生成しても元データの鮮度は保証しない。
- 外部API・資格情報・公開デモ・実payloadのGit管理には触れない。commitなし。
# 2026-10-23 — 公開モック準拠のローカルpreview UI統合

- root公開モックの `styles.css` をpreview生成stageから永続previewへコピーし、preview HTMLはそのCSSとpreview固有上書きを読み込む。公開側index/styles/appには変更なし。
- HTMLのヘッダー／時計、注意文、独立ルート枠、操作行、コンパクト3列カード、フッター、320×50広告placeholder dockをモック構造へ合わせた。路線別見出しを外し、先頭カード内に件数を置く。
- 実ダイヤの状態バナーは通常時1行、異常時は折返し表示。payload期間、生成日時、GTFS feed期間、GTFS/ODPT更新日時、Web build日時を折りたたみ詳細に区別して表示し、未取得は未取得と表記。
- adapter、selection、列車判定・選択、T01の生成・検証・差し替え手順には変更なし。スタイルコピーのみprepare_previewへ追加。実payloadを再生成し自動テストを実施。iPhone Safariの実機目視は未実施。

## iPhone Safari縦レイアウト調整

- 上部のmain/demo/route/status/details/controls間の余白を合計20px圧縮。カードの文字サイズ・最小高・4px間隔、広告dockの寸法とsafe-area下余白予約は維持。
- 常時表示していた安全上の注意文を折りたたみmetadata詳細内へ移動。期限切れ・運行日不足・読込失敗の動的status bannerは変更せず、エラー時は引き続き表示。
- iOS Safariの狭幅時だけヘッダーをsafe-area上端内側でstickyにし、システムstatus textとの重なりを避ける。自動レイアウト契約テスト追加。物理iPhone上のscroll/safe-area/広告dock確認は未実施。

## 2026-10-23 — 有楽町線種別補完・種別表示改善（T08/T09）

- 公式の有楽町線運行ルールを使う表示fallbackを追加。route 6、ODPT unique match、原typeとunscoped through-service typeの一致、池袋乗車可、要町/千川/小竹向原の一意かつ有効な停車、順序・時刻整合、S-TRAIN等の例外なしを条件とする。raw ODPT code・照合結果は保持し、sourceを `official_route_rule`、表示を `各駅停車` とする。
- 旅程のない便には補完を適用しない。対象日payloadには池袋乗車と途中停車が揃っていても有効な氷川台旅程が成立しない便があり、そのレコードは「種別不明」を維持した。route rule適用の可否はtrip IDのハードコードではなく検証条件による。
- タイプ名と行先を独立したDOM要素にした。各駅停車は通常色、急行/通勤急行は太字＋実線下線、Fライナーは愛称として別色＋破線下線、停車パターン補助表示は控えめな色＋点線下線、種別不明は控えめな色。カード寸法・広告dock・safe areaは変更していない。公開rootの `index.html` / `styles.css` / `app.js` は変更なし。
- 保存済みGTFS/ODPTのみで代表日集計。preview表示候補の種別不明は平日9/435→0/435、土曜6/396→0/396、祝日6/396→0/396。source `official_route_rule` は9/6/6。旅程不能で非表示のunknownレコードは各日1/3/3件残す。別日も含む更新済みpreview（2026-10-22〜24）は `~/Library/Application Support/dotchi-ikebukuro-preview/site`。
- 自動検証: `python3 -B -m unittest discover -s tests -v` 38件成功。`node --test tests/*.test.mjs` 30件成功。スタティックUI契約でカード寸法、広告dock/safe-area、表示スタイル、別要素化を確認。Safari実機目視・物理iPhoneの横幅/縦寸法確認は未実施。手順は作業報告に記載。
- 公式根拠のURL、適用範囲、例外、改正時の再検証条件は [`odpt_research.md`](odpt_research.md)。外部通信・APIキー読取・元データ編集・公開デモ変更・Git追加・commit/push/mergeなし。

## 2026-10-23 — T14 目的地対応範囲 Phase 1

- Phase 1として、要町・千川・小竹向原・氷川台・平和台・地下鉄赤塚・地下鉄成増・和光市の8駅を内部カタログ化。有楽町線／副都心線の別々のGTFS stop IDと池袋からの順序を管理する。
- `ItineraryGenerator` に `destination_station_id` を追加。既定は氷川台で、氷川台だけを旅程検証済みとして許可。他7駅は明示的な未検証エラーで止めるため、未検証の通過・欠損記録を到着と見なさない。
- exporterは旅程の到着駅IDを参照するようにし、既定氷川台のpayload内容を維持。氷川台の候補便数・旅程選択・表示、adapter/preview/UI、T01更新処理には変更なし。追加駅の旅程生成や目的地選択UIは次Phase。
- 外部通信・APIキー・ODPT/GTFS原データ・公開モックには触れず、実payloadを生成せず、commit/push/mergeなし。

## 2026-10-23 — T14 Phase 2 要町・千川・小竹向原

- `ItineraryGenerator` で要町・千川・小竹向原を有効化し、同一GTFS tripの池袋乗車から目的地まで、stop ID・進行順・時刻単調性・目的地到着時刻・降車可を検証して直通候補を生成。明示的通過 (`drop_off_type=1`) は候補から外し、対象駅行欠損・時刻欠損・乗降制限・時刻/順序矛盾を日次不足診断へ分類。小竹向原を含め別trip乗換は生成しない。
- 目的地別payloadは既存schemaVersion 1へ任意 `destinationStatus` を追加。normal / no_candidates / data_insufficient とY/F別件数を保持する。adapterは目的地ID整合、状態・件数を検証し、必要service dayにdata_insufficient / unsupported / invalidがあれば候補を出さない。既存payloadと氷川台payloadは状態フィールドなしで従来互換。
- 保存済みfeedの旅程数（Y/F）: 要町・千川は平日219/152、土曜・祝日190/154。小竹向原は平日219/220、土曜・祝日190/212。明示通過除外は要町・千川が68/61/61、小竹向原が0/3/3。実データの不足レコードは全対象日0。各対象・日で状態normal。
- 全対象候補は直通のみ。同一trip内のarrival/drop-offと24時超を含むservice secondsを確認。目的地別3日payloadを一時領域で生成し、既存Node validatorを通過。氷川台の保存済みpreview payloadは `generatedAt` を除く全payloadが一致。
- ODPT match結果とraw reported typeは全共通tripで一致。平日Y線1件は氷川台の既存旅程なしで表示をunknownに保留していた公式route-rule種別が、Phase 2目的地では有効な直通旅程のため `各駅停車` 表示へ解決された。raw ODPT値 (`SemiExpress`) とunique matchは維持。土曜・祝日は種別表示差なし。
- 検証: Python unittest 43件成功。Node全体33件成功、adapter UTC 23件成功。代表3日の候補・passカウント、データ不足の合成停止、残り4駅と未知ID拒否、headsign/選択目的地分離、T02適用期間・必要運行日停止、既存最早着/直通filter回帰を確認。
- 公開mock、preview UI/生成物、ODPT/GTFS元データは変更せず、目的地別payloadは一時領域の検証後削除。外部API・秘密情報なし、commit/push/mergeなし。

## 2026-10-23 — T14 Phase 3 平和台・地下鉄赤塚・地下鉄成増・和光市

- 検証済み目的地allowlistへ残り4駅を追加。Phase 2と同じ共通判定を使い、池袋から目的地まで同一GTFS trip内のstop ID、進行順、到着時刻、降車可、イベント時刻単調性を確認する。別tripの連結・小竹向原乗換候補は生成しない。既定の氷川台分岐やexporter/adapter/UIは変更なし。
- 代表日（平日2026-10-22、土曜2026-10-24、祝日2026-11-03）のY/F件数は平和台・地下鉄赤塚が150/137、129/111、129/111。地下鉄成増も同数。和光市は150/150、129/145、129/145。土曜と祝日は同じGTFS service種別で便数・通過数が一致。
- 明示通過除外は平和台・地下鉄赤塚・地下鉄成増で副都心線13/34/34、和光市と有楽町線各駅は0。必要停車・時刻・降車・順序不足は全4駅・全代表日で0。24時超の到着は目的地順に平日7/7/8/8、土曜・祝日8/8/9/9件を含み、service secondsを保持。
- 生成状態は既存名の `normal`。`no_candidates`、`data_insufficient`、`unsupported`、`invalid` の意味・adapter fail-closed方針は維持。目的地別payloadはリポジトリ外へ出力でき、通常preview既定は氷川台のまま。READMEに8駅payload生成用CLI optionを追記。
- 4駅の日別route/pass/24時超件数と同一trip・降車・stop ID、Wakoshi payloadの目的地/status/headsign分離をテストへ追加。既存Phase 2件数テストも従来期待値を維持。
- GTFS/ODPT原データ、永続preview出力、公開モックは変更しない。実payload検証は一時領域に限定。

## 2026-10-23 — T14 Phase 3.5 小竹向原乗換生成の共通化

- 目的地カタログに経路方針を持たせ、要町・千川・小竹向原は `direct_only`、氷川台・平和台・地下鉄赤塚・地下鉄成増・和光市は `direct_and_kotake_transfer` とした。後者5駅で、池袋発tripから小竹向原で降車し、反対路線の別tripへ乗車して同じservice day内に目的地へ到着する候補を共通生成する。別tripを直通として結合しない。
- 新4駅の乗換元は小竹向原までの停車順・時刻単調性・到着・降車可を確認し、乗換先は小竹向原発車・乗車可、目的地の下流停車順・到着時刻・降車可を確認する。60〜600秒を維持。既存の最早着選定、直通優先、乗換候補の主候補選定を変更していない。小竹向原乗換は `connectionGuaranteed=false`、platform `unknown` のまま。
- 公式の[小竹向原駅案内](https://www.tokyometro.jp/station/kotake-mukaihara/index.html)、[バリアフリー設備案内](https://www.tokyometro.jp/station/kotake-mukaihara/accessibility/index.html)、[駅構内図](https://www.tokyometro.jp/station/kotake-mukaihara/yardmap/index_print.html)を2026-10-23に確認。駅案内は有楽町線・副都心線と和光市方面を示し、バリアフリー案内は1・2番線と3・4番線のホーム群を示す。駅構造上の移動条件は接続可能性の参考にとどめる。GTFSには列車別番線、minimum transfer time、connection guarantee、block_idが確認できず、時刻表上の候補を実際の接続保証とは扱わない。ユーザー提示の3・4番線同一島式ホーム情報も、60秒を保証時間と解釈する根拠にはしない。
- 新4駅の `destinationStatus` は直通候補親trip数、乗換候補を持つ親trip数、全乗換候補組数、乗換のみ親trip数、乗換側の明示通過・データ不足を分けて記録する。直通不足と乗換側不足も分け、直通旅程の検証結果は乗換側の不足で変えない。候補がある日は、Phase 2と同じく有効候補を表示しつつ不足件数も報告する。氷川台の既存status/payload形状は互換のため変更しない。
- 代表日（平日2026-10-22、土曜2026-10-24、祝日2026-11-03）の新4駅の件数は平和台・地下鉄赤塚・地下鉄成増で同じ。平日: 直通親287、乗換候補親417、乗換組622、乗換のみ148、primary 435。土曜・祝日: 直通親240、乗換候補親366、乗換組490、乗換のみ156、primary 396。和光市は平日300/419/635/135/435、土曜・祝日274/378/525/123/397（同順）。新3駅では乗換先の明示通過13/34/34件、和光市は0。土曜・祝日は各駅で小竹向原の必要な乗換記録が使えないtripが3件あり、乗換不足として計上。直通判定は独立して維持し、有効旅程は従来の部分候補方針どおり利用可能。
- 新4駅を合わせると、primaryの1分乗換は平日247件、土曜・祝日各294件。2分乗換は平日124件、土曜・祝日各66件。全4駅・3日とも乗換の方が直通より早い／同着のprimaryは0件で、該当旅程は乗換のみの池袋発便。1〜2分は候補を一律除外しないが、接続保証がないため、Phase 4では「時刻表上の乗換候補」、待ち時間、番線未確認、接続保証なしを短く伝える方法を評価する。
- 回帰確認: 氷川台・要町・千川・小竹向原の旧生成結果は全3日でgeneratedAt以外一致。氷川台の保存済みpreview payloadも同条件で一致。追加4駅はPhase 3直通候補射影（発着、headsign、ODPT raw種別・source・照合、駅ID等）が旧結果と一致。自動検証はPython unittest 47件、Node全体34件、adapter UTC 24件が成功。追加4駅の実payloadを各1件、一時領域で生成してadapter validatorで検証し、生成ファイルは削除した。
- 外部API、認証情報、GTFS/ODPT原データ、preview UI/公開mock、永続preview payloadは変更していない。目的地別検証payloadは一時領域のみで生成し、Git管理・commit/push/mergeなし。

## 2026-10-23 — T14 Phase 4A 目的地選択・8駅payload切替

- `_local_preview` のルート枠をボタン化し、8駅を停車順に選択するモーダルを追加。選択中の駅名と状態を表示し、閉じる/Escape、矢印・Home・Endキー、フォーカス復帰、背景scroll抑止、safe-areaを実装。画面本体の高さと既存カード寸法・6件制限・広告dockは変更していない。
- loaderに固定station ID→payload pathを定義。初期・reloadは氷川台 (`timetable.json`)、残る7駅は `timetable-{stationId}.json`。requested ID以外のpayloadや未知IDを拒否し、fallbackしない。切替時は現カードとmetadataを消し、読み込み状態を表示する。latest-request controllerが連続切替で遅れて返った古いresponseを無効化する。フィルターと表示modeは状態を保持。
- prepare_previewは一時stage内で8目的地のpayloadを生成し、個別に現行adapter検証してから全ファイルとUIを原子的に差し替える。いずれかの生成・検証失敗時は旧siteを維持。payload bytes、生成秒、検証秒を完了ログに出す。
- 選択駅名は画面上部とカード到着ラベルに反映。直通のみ／路線別・発車順／最早着／countdown、各駅の既存旅程、24時超・T01〜T03安全判定を維持。T17で指定されたモード左右入替、初期発車順、文字サイズ、到着caption統一は変更していない。
- Python unittest 49件、Node全体38件、adapter UTC 24件成功。実データ8駅payloadを現行運行日（2026-10-22〜24）で生成し、全てadapter validatorを通過。最後の反映実測は生成40.0秒、検証1.7秒、容量22,109,229 bytes。氷川台payloadは独立した同条件のexporter出力と `generatedAt` 以外一致。配信コピーのHTML/JS/CSS/adapter/loaderも作業ソースと一致。Safari実機操作は未確認。公開mock・root `index.html` / `styles.css` / `app.js`・ODPT/GTFS元データは変更しない。外部通信・認証情報・commit/push/mergeなし。
- 配置payloadの3運行日合計: 要町・千川はprimary直通1,086件ずつ、小竹向原は1,280件。氷川台・平和台・地下鉄赤塚・地下鉄成増はprimary 1,266件、直通候補814件、乗換候補親trip1,200件、候補組1,734組ずつ。和光市はprimary1,267、直通874、乗換候補親trip1,216、組1,795。各service dayはadapter上validで、非氷川台payloadの日次destinationStatusはnormal。氷川台statusを追加せず旧payload形状を維持。

## 2026-10-23 — T14 Phase 4A.1 目的地記憶・読込計測

- `dotchi-ikebukuro.destination-id.v1` に許可済みstation IDだけを保存。初期値は氷川台、保存値が未知・storage getter/read/writeが失敗する場合も画面操作を続ける。storageにはpayloadや列車情報を保存しない。選択駅のpayload取得失敗時はその駅のエラー状態を維持し、別駅データへfallbackしない。
- ページ内に直近2駅分の検証済みprepared payloadをLRUで保持。同じ駅を選び直す操作はfetchしない。切替で過去の駅へ戻った場合はメモリcacheを使う。HTTP `cache: no-store` は維持し、ページreload時には保存stationのファイルを取得する。cache hit後も毎秒 `buildBoard` を呼び、有効期間・required service days・現在時刻の24時間horizonを再評価する。8駅全てを初期取得しない。
- 開発計測は画面に出さず `window.__dotchiPreviewPerf.loadHistory` にfetch応答待ち、本文読込、JSON parse、adapter validation/preparation、payload byte、cache hitを、`history` に毎秒のadapter/candidate processing、selection、DOM描画を最大50標本記録する。これによりSafari Web Inspectorから端末側の長時間段階を確認できる。
- 実payloadをMac Nodeで12周（warm-up 2周を除く80標本/段階）計測。氷川台payloadは3,306,543 bytes。Macローカルread median 1.360ms / p95 13.573ms、JSON parse 14.240 / 18.196ms、adapter validation/preparation 38.443 / 47.628ms、buildBoard＋selection 0.791 / 1.264ms。これはMac Nodeとwarm filesystem cacheの参考値でiPhone Safariの転送・DOM値ではない。reported 1〜3秒の端末側原因をこれだけで特定できない。`no-store` のHTTP取得時間とDOM更新時間をSafariで読む必要がある。
- 自動テストはPython 49件、Node全体43件、adapter UTC 24件が成功。8駅payloadを再生成し、生成39.9秒・検証1.7秒、合計22,109,229 bytes。配置先は `~/Library/Application Support/dotchi-ikebukuro-preview/site`。iPhone確認用の配信コピーは再生成後のソースと一致し、全8駅payloadがstage内検証後に原子的に反映された。
- iPhone Safariの実機計測値は未取得。Safari Web Inspectorで `window.__dotchiPreviewPerf.loadHistory.slice(-10)` と `window.__dotchiPreviewPerf.history.slice(-10)` を確認し、端末側のfetch/本文/parse/adapter/selection/DOM時間を測る。公開mock/root公開ファイル、GTFS/ODPT元データ、外部API、秘密情報、commit/push/mergeには触れない。

## 2026-10-23 — T14 Phase 4B / T17 UIレイアウト改善

- preview操作行を左「路線別｜発車順」、右「直通のみ表示」に並べ替え、初期modeを発車順に設定。目的地切替ではmodeとfilter stateを変更せず、保存済み目的地IDにも影響しない。
- 発車時刻は到着時刻と同じ15px/800、直通・乗換説明は「発車まで」と同じ12px相当へ。カウントダウンと到着時刻のラベルを値の上に中央配置し、全駅の到着ラベルを「到着」に統一。ルート枠は「▼ 目的地を選択」とし、既存モーダル・フォーカス・キーボード操作は維持。
- 変更は `_local_preview/index.html` / `preview.css` / `preview.js` とUI契約テストに限定。カード最小高68px、カード間隔4px、6件表示、広告dock、safe area、種別色・最早着色は維持。公開root mockに差分なし。
- 自動テスト: Python 49件、Node全体44件成功。8駅payloadを生成46.3秒・検証1.8秒で再生成（合計22,109,229 bytes）。配信ファイルの一致と `git diff --check` を確認。Safari実機での最終視覚確認は利用者による確認待ち。iPhone用ローカルserverは `192.168.11.7:8765` のみで稼働。

## 2026-10-23 — T17 実機フィードバック追加修正

- 発車・到着時刻に共通の `.time-value` スタイルを適用（15px、800、継承font family、line-height 1.1、letter-spacing normal、tabular numerals）。発車の「発」は独立要素。
- カード列を上端揃えにし、路線名／発車まで／到着のラベル行と、発車時刻／countdown／到着時刻の数値位置を揃える。最早着表示は路線名と同じ行に維持し、路線横の件数表示だけを削除。
- 表示モードは `dotchi-ikebukuro.display-mode.v1` にline/departureのみを保存・復元。初期値・不正値・storage利用不可はdeparture。目的地IDの既存キーとは独立し、直通filterは保存しない。
- Python unittest 49件、Node全体47件成功。8駅のローカルpreviewを生成89.8秒・検証3.4秒で再生成（22,109,229 bytes）。配信ファイルを確認後、iPhone確認のため `192.168.11.7:8765` のみで起動。公開モック、旅程生成、payload内容は変更なし。

## 2026-10-23 — T17 カード内最終レイアウト調整

- 路線名／発車まで／到着のラベル行はカード上端で維持。発車時刻・countdown・到着時刻は各ラベルから同じ4px空けて配置し、既存の左説明行は `margin-top: 6px` で下げてカード下部の余白へ再配分。カードmin-height 68px、外側vertical padding 5px、margin-bottom 4pxは不変更。
- 左列を確保するため、内部gapを4→3px、水平paddingを15/7→13/6px、右列を78/61→72/56pxへ調整。390px viewportで左列は215px。320pxまでの狭幅や拡大時は、種別・行先のflex itemを縮小・折返し可能にし、文字を省略しない。
- 保存済み8駅payload（平日2026-10-22/23、土曜2026-10-24）のprimary旅程は表示ペア24種類。GTFS有効期間の祝日2026-11-03も、8駅payloadを`/private/tmp`の一時領域で作成して確認（23種類、3,071 primary records）。最大表示幅は「各駅停車 石神井公園行」193.98px（Mac CoreText system-font reference、15px/800時刻、14px/600種別・行先、現在のCSS gap込）。次点「Fライナー 森林公園行」191.21px。全幅390pxで左列215px、約21pxの余裕。iOS Safari実機は利用者側で再確認が必要で、別OSのCJK fallbackや文字拡大時はwrapを安全策とする。
- Python unittest 49件、Node全体47件成功。ローカルpreviewを生成42.2秒・検証1.6秒で再生成（22,109,229 bytes）。配信コピーのHTML/CSS/JS/loader一致、公開root mock差分なし、`git diff --check` を確認。`192.168.11.7:8765` の既存serverが再生成後のCSSを配信することもhash一致で確認。保存済み元データ・旅程生成・type resolutionには変更なし。iOS実機での最終表示確認は利用者側で残る。

## 2026-10-26 — 終電・翌運行日の候補表示 Phase 1

- adapterで目的地に到達可能な候補をserviceDate・池袋発routeId別に集計し、全件から最終発車候補を判定。primary候補に乗換を含み、直通filter時はdirectAlternativeだけで再判定。到着時刻・最早着主候補の選定とは分離し、結果のカードに`isLastDeparture`、`terminalBasis`を付与。
- 各serviceDate・路線で最初の到達可能発車60分前から候補を解放。前日24:xx/25:xxは前日serviceDateのまま残り、翌serviceDateの早朝候補と混ぜない。終電終了はserviceState=`ended`（両route stateがended）に限定し、routeStates内でrunning/ended/not_started/no_service/no_candidates/data_insufficient/unknown/unavailableを返す。
- 全8目的地payloadのdestinationStatusへroute別scheduledTripCount・originTripCount・candidateCount・不足数を出力。従来destinationStatusがなかった氷川台にも付与し、routeのserviceDate終端を根拠付きで判定可能にした。旧payloadは形式上読めるが、終電根拠のないserviceDateはunknown、未来serviceDate候補を表示しないfail-safe。
- 表示selectionは路線別の直近3件／発車順の直近6件を維持し、表示範囲外の終電候補を優先挿入しない。終電判定は件数制限前の全到達候補で行い、終電候補が通常範囲内にある場合のみ選択結果に`isLastDeparture`が残る。カードDOM・ラベル・終了文面は未変更（Phase 2）。root mockファイルにも変更なし。
- テスト: Python unittest 50件成功。`node --test tests/*.test.mjs` 60件成功、`TZ=UTC node --test tests/*.test.mjs` 60件成功。追加分は路線別終電、乗換末便、filter切替、24/25時、代表深夜時刻、60分境界、発車境界、運休日・不足、全8駅payload形状、表示件数上限。実payload生成・外部APIアクセスは実施していない。
- ローカルpreviewは保存済み入力から8駅分を再生成済み（最終実行: 生成72.3秒、検証3.3秒、22,114,119 bytes）。出力先はユーザー領域のApplication Support内で、公開先ではない。終電ラベル・両路線終了文はPhase 2。

## 2026-10-26 — Phase 1 表示候補選択ルール調整

- selectionは路線別で各路線の直近3件、発車順で全候補の直近6件を返す。表示範囲外の終電候補が通常候補を押し出さないことをテストで固定。
- テストは両表示モードで表示範囲内候補が保たれ、終電フラグはselection結果に現れないことを確認する。直通のみ相当の入力でも同じ件数・順序を確認。
- 終電全候補判定、`terminalBasis`、`routeStates`、`serviceState`、始発60分前ゲート、安全停止処理は変更しない。
- 確認: Python unittest 50件、Node全体60件、`TZ=UTC`のNode全体60件が成功。`git diff --check`成功。ODPTアクセスなし、root mock変更なし。

## 2026-10-26 — 終電表示 Phase 2 UI

- previewカードに`isLastDeparture`と`terminalBasis`に基づく「終電」／「直通終電」badgeを追加。表示対象の通常上限・発車時刻・countdown・到着時刻の配置は維持。
- `serviceState === 'ended'`のときのみ「本日の終電は終了しました」を表示。データ不足・unavailable・運行前・候補なしは従来の空状態／警告に留める。
- 毎秒の既存tickと目的地／表示モード／直通filter変更で表示状態を再計算。目的地読込開始時は既存処理でカードを消去し、旧目的地の終電表示を残さない。
- badge用スタイル・UI契約と状態表示helperを追加。変更対象はローカルpreviewに限定し、root mock、カード寸法、6件、広告dock、safe-area、Phase 1 adapter判定は変更しない。
- テスト: Node全体64件および`TZ=UTC`でも64件成功。Python全体50件成功、preview builderのコピー検証を含む9件も変更後に再実行して成功。`git diff --check`成功。
- 保存済みローカル入力からprivate previewを更新（8駅、22,114,119 bytes、生成52.5秒、検証2.2秒）。出力先はApplication Support内。ODPT API通信・公開root mock変更なし。

## 2026-10-26 — ローカルpreview仮想日時QA

- preview限定の`debugNow` URL queryを追加。厳密なJST壁時計パースを行い、preview tickへ固定`nowMs`を渡す。未指定・不正値は実時刻へfallbackし、有効時だけ上部にテスト日時を表示。
- preview builderが`virtual_now.mjs`を配布bundleへcopyするよう更新。payload/GTFS/ODPT保存データ、Phase 1判定、公開root mockは変更していない。
- adapter統合テストは23:50/00:10/00:40/01:30/04:00/05:00を仮想時計経由で実行。QA中に00:40/01:30は候補カードなしでもserviceState=`running`になるPhase 1状態集約を確認。次serviceDateの将来候補を表示60分前より先にrunningと扱う既存仕様のため。今回の制約に従い判定コードは変更せず、project_stateへ記録。
- テスト: `node --test tests/*.test.mjs` 70件成功、`TZ=UTC node --test tests/*.test.mjs` 70件成功。Python unittest 50件成功。preview builderのコピー検証を含むPython suiteで`virtual_now.mjs`の同梱を確認。
- 保存済みローカル入力からprivate previewを再生成（2026-10-25〜27、8駅、22,114,119 bytes、生成45.3秒、検証2.1秒）。公開先・外部APIアクセスなし。

## 2026-10-26 — 終電後のserviceState集約修正

- `summarizeRouteStates`がserviceDateを問わず`lastDepartureAtMs > nowMs`を調べていたため、始発60分ゲート前の翌serviceDate候補でもroute stateがrunningになっていた。これを廃止し、今日・前日のservice day状態と各routeの60分ゲートで集約する。
- 前日状態がendedで当日状態がnot_startedならrouteはended。前日の24/25時便が残っている時は前日状態runningを保持。当日運行が一方の路線だけ始まった場合はserviceState=partial、両路線が始まればrunning。
- unknown/data_insufficient・no_service・no_candidates・unavailableはendedの根拠に使わない。候補生成、最早着、直通／乗換選定、`isLastDeparture`・`terminalBasis`、表示上限は変更しない。
- adapterテストに00:40/01:30のended、始発60分前の路線別遷移、直通のみ、24/25時継続、データ不足、目的地変更を追加。
- テスト: Python unittest 50件成功。`node --test tests/*.test.mjs` 70件、`TZ=UTC node --test tests/*.test.mjs` 70件成功。前日未終電・両路線終了・一路線だけの始発ゲート通過・不完全service dayを検証。
- 修正adapterをprivate previewへ反映。保存済みデータから8駅・2026-10-25〜27分を再生成（22,114,119 bytes、生成41.1秒、検証1.8秒）。公開host・外部API通信なし。

## 2026-10-27 — 仮想日時QA専用payload生成

- 原因: payloadは生成時刻のJST前日・当日・翌日だけを収録する。通常previewは10/26生成で10/25〜27を含んでいたが、10/27の仮想日時評価ではadapterが10/26〜28をrequired service daysとして要求するため、10/28不足で安全停止していた。ローカルGTFS適用期間は10/28を含む（10/28は期間内）。
- 追加した `_local_preview/prepare_qa_preview.py` は対象日を固定アンカーとして既存のpreview builderを呼び、`~/Library/Application Support/dotchi-ikebukuro-preview/qa/<対象日>/site` に別出力する。通常previewの出力先・判定ロジック・UI・仮想時刻処理は変更しない。
- 初回生成ではpayload validatorが実時刻（10/26）基準で10/25〜27を要求し、QA対象payloadの10/26〜28を拒否した。validatorに任意のISO `--now` を追加し、通常実行では従来どおり実時刻を使い、QA生成時のみ対象日のJST正午を基準にrequired serviceDate・適用期間を検証する。終電・候補判定ロジックは不変。
- builderの既存transactionにより、8駅すべての生成とpayload検証が成功してから出力を入れ替える。失敗時は既存preview/QA出力を保持。対象日形式・JST validator時刻・3 serviceDate範囲の単体テストを追加。
- 使い方: `python3 _local_preview/prepare_qa_preview.py --target-date 2026-10-27`。Macと同じLAN上のiPhoneからも確認する場合は `python3 -m http.server 8765 --bind 0.0.0.0 --directory "$HOME/Library/Application Support/dotchi-ikebukuro-preview/qa/2026-10-27/site"` で配信する。Mac Safariは `http://127.0.0.1:8765/index.html?debugNow=2026-10-27T00:40:00`、iPhone Safariは `http://<MacのLAN IP>:8765/index.html?debugNow=2026-10-27T00:40:00` を開く。`01:30:00`へ変えると早朝状態も確認できる。Mac/iPhoneを同じLANに接続し、LAN IPは `ipconfig getifaddr en0` で確認する。確認後はサーバをCtrl-Cで停止する。通常previewへ戻す場合は通常previewのserverを起動する。
- 生成結果: 8駅、22,770,114 bytes、運行日2026-10-26〜28、生成48.3秒・validator検証2.0秒。feed適用期間は2026-09-19〜2027-03-12で全日範囲内。excluded serviceDateなし。通常previewは10/25〜27のまま別ディレクトリに保持。
- QA対象日時00:40/01:30ではvalidity=valid、missingServiceDatesなし、カード0件。有楽町線route6はended、副都心線route9はdata_insufficientによりunknown、全体serviceState=unknown。route9は各対象日で13件のdataInsufficientCountがあるため、実payloadで「本日の終電は終了しました」となることは確認できない。安全停止の結果であり、合成fixtureでのendedロジックとpayload日付充足を分けて扱う。Safari実機確認は未実施。
- テスト: Python unittest 53件成功、Node tests通常TZ 70件成功、`TZ=UTC`でも70件成功。

## 2026-10-27 — GTFS降車不可とデータ不足の分類修正

- 原因: 既定の氷川台経路は到着時刻欠落を常に`destination_arrival_missing`として不足扱いしていた。副都心線の13件はGTFS `drop_off_type=1`で降車不可が明示されており、時刻欠落だけでは到達判定不能ではない。
- 明示通過を`destination_explicit_pass`で記録し、route/top-level `passThroughCount`へ加算。`destination_arrival_missing`診断は保持するが、同じイベントが明示passならこの理由だけでは`dataInsufficientCount`に含めない。他の独立issue codeや乗換側不足は従来どおり不足にする。`drop_off_type=2/3`はrestricted、未知値はunknownとして不足扱い。
- 既定Hikawadai経路でも後続駅が記録されているのに目的駅行が欠落する状態を`destination_stop_record_missing`として検出し、曖昧・駅順不整合も不足にする。明示pass以外を通過と推測しない。
- 直通候補作成条件（降車可能かつ到着時刻あり）と小竹向原乗換生成、ODPT照合、payload schema、終電adapter判定は維持。`dataInsufficientCount`の既存フィールドを正確化しただけで、8駅とも同じschema。
- 実データ: 2026-10-26〜28の氷川台・副都心線で既知13件をすべて明示passと分類。ODPT unique match 13件、直通候補0、乗換候補13件を維持。dataInsufficientCount 0、passThroughCount 13、transferDataInsufficientCount 0。全8駅・3日でschema検証成功し、他7駅のデータ不足は0。
- QA専用previewを保存済みGTFS/ODPT入力から再生成（8駅、22,771,206 bytes、10/26〜28、生成65.1秒・検証2.7秒）。通常private previewは出力先にせず、既存データを維持。実payloadで2026-10-27 00:40/01:30は全8駅ともvalid、氷川台も通常・直通のみ両モードで`serviceState=ended`。ODPT API通信なし。
- テスト: Python unittest 59件成功。`node --test tests/*.test.mjs` 71件成功、`TZ=UTC node --test tests/*.test.mjs` 71件成功。追加テストはdrop_off type分類、独立issue維持、後続停車記録欠落、既知実データ13件、transfer保持、direct-only terminalを対象。`git diff --check`成功。

## 2026-10-26 — 通常private preview最終確認準備

- 保存済みローカルGTFS/ODPT入力のみを使い、現在時刻（JST 2026-10-26）を基準に通常private previewを再生成。出力は `~/Library/Application Support/dotchi-ikebukuro-preview/site`、serviceDateは2026-10-25〜27、8駅、payload合計22,115,799 bytes。生成45.6秒、validator検証2.1秒。
- GTFS適用期間2026-09-19〜2027-03-12内に必要な3 service dayがあり、全8駅のpayloadでschema・metadataと現在時刻の必要運行日を検証。通常／直通のみのadapter評価も全駅valid。
- 配信bundleのindex、CSS、preview JS、adapter、loader、validator、`terminal_ui.mjs`、`virtual_now.mjs`が各作業tree sourceとbyte一致。氷川台10/26副都心線は明示pass-through 13件、`dataInsufficientCount` 0、直通候補137・乗換候補213。終電・始発判定およびGTFS降車不可分類を通常preview payload／bundleへ反映。
- 利用者報告の実機QA: Mac ChromeとiPhone Safariで、終電直前badge、片路線のみ終了、両路線終了メッセージ、始発60分前の路線別再開、路線別・発車順、目的地切替、iPhone 6件表示／カード配置／広告dockを目視確認し問題なし。
- QA専用previewは別の `qa/2026-10-27/site` に維持し、今回の処理前後で18ファイルのaggregate hash一致を確認。公開root mock・公開配信先は変更していない。
- テスト: `python3 -B -m unittest discover -s tests` 59件成功（163.4秒）、`node --test tests/*.test.mjs` 71件成功、`TZ=UTC node --test tests/*.test.mjs` 71件成功。外部APIアクセス・秘密情報読取・commitなし。
- 通常preview起動例: `python3 -m http.server 8765 --bind 127.0.0.1 --directory "$HOME/Library/Application Support/dotchi-ikebukuro-preview/site"`。実ダイヤはprivate local preview内のみ。

## 2026-10-26 — iPhone Safari切替性能計測（private previewのみ）

- `_local_preview/performance_metrics.mjs` とpreview UIにopt-in計測を追加。`?perf=1` 時だけ、目的地切替の最新値・直近10件履歴・コピー操作を表示。通常アクセスは欄をhiddenにし、switch計測を作成しない。結果はページメモリに限定し外部送信・永続保存なし。`debugNow` queryは併用可能。
- 既存loader計測を再利用し、未実行のloader段階は `null`、LRU cache HITはnetwork/body/JSON/prepareを0として区別。Networkはfetch応答待ち＋`response.text()`本文完了（転送・文字列化を含む）。JSON parseとschema検証・カード事前生成は別段階。payload byteはContent-Length取得時に記録。
- 切替clickからの総時間は最終描画更新後の2回目 `requestAnimationFrame` まで。`renderMs`は最終DOM同期開始から同時点までの画面反映近似。board、selection、renderの区間計測はstage間で重複しない。`totalMs`はそれらを含むwall timeのためstage値と合計しない。staleな応答は独立した駅名とロード段階だけを記録し、total/renderは未実行として扱う。
- 履歴は選択開始時刻順に最大10件。連続切替の最新要求IDと駅ごとのclosureにより古いresponseは画面結果に混ぜず、画面反映前に後続選択が始まった場合もsupersededとする。診断欄はカードDOMの後、広告dockの前の通常document flowに置き、診断中も6件上限・dock・safe areaのroot CSSは変更しない。
- 通常private previewの `PREVIEW_FILES` にmoduleを追加し、Application Support内の通常siteを保存済み入力から更新。2026-10-25〜27、8駅、22,115,799 bytes、最終同期は生成42.3秒、検証1.7秒。配信bundleの新UI・module・loader・adapterはsourceとbyte一致。QA previewの18ファイルaggregate hashは前後一致。
- テスト: Python unittest 59件成功（189.2秒）、Node 78件成功、`TZ=UTC`のNode 78件成功。JavaScript syntax checkと`git diff --check`成功。`preview_layout`で通常時hidden・page flow・広告dock周り、perf flag/`debugNow`併用、loaderのcache/miss/error、stale結果、10件上限を確認。iPhone Safari実機の新計測値は未採取で、利用方法は `?perf=1` を付けてiPhoneで切替後、ページ下部の診断欄を確認する。
- iPhone起動例: `python3 -m http.server 8765 --bind 0.0.0.0 --directory "$HOME/Library/Application Support/dotchi-ikebukuro-preview/site"`。同一Wi‑FiのiPhoneで `http://<MacのLAN IP>:8765/index.html?perf=1` を開く。終了後server停止。ODPT API・API key・公開root mock・公開配信先・commit/push/mergeなし。

## 2026-10-26 — preview計測のNetwork内訳

- `?perf=1` の最新結果と履歴／コピー出力に既存loader値の `fetchMs`（fetch開始〜応答header受信）と`bodyReadMs`（`response.text()`本文読込完了）を追加。`networkMs`は両者の合計で、失敗時は到達済み区間のみを合計し未実行値は未実行表示。cache HITは各値0。
- 変更は診断表示・計測record・対応テスト・説明に限定。通常表示、列車カード、終電判定、cache機構、payload生成処理は変更なし。

## 2026-10-26 — T11利用条件回答・T12配信設計調査

- ODPT事務局から共有された利用条件回答を `docs/odpt_research.md` に記録し、T11を完了扱いにした。想定利用の範囲を超えた包括許可とは解釈せず、既存の基本ライセンス・ガイドラインとデータ更新表示義務を引き続き記載。
- GitHub Pages + Actions、Cloudflare Pages + Workers、GitHub Pages + 外部更新処理を14観点で比較。Cloudflare Pages静的配信 + GitHub Actions build/updateを推奨し、Workersなしの静的構成で足りると整理。実装はT12未着手、T13/T15も未着手。
- 現行root mock、private preview、payload loader、offline exporter、atomic preview generator、validator、`.gitignore`を読み取り専用で確認。workspaceに`.github/workflows`と`package.json`はなく、remote GitHub settings・secretの有無は未確認。APIキー・ODPT API・公開root mockには触れていない。
- 2026-10-26時点の公式料金・制限・圧縮/cache、Direct Upload/rollback、GitHub Pages用途制限、i-mobile ads.txt仕様を公式URLと確認日付きで `docs/hosting_research.md` に記載。payload容量値はローカル生成物のfile sizeとzlib圧縮概算のみを参照し、実ダイヤ本文は文書へ転載していない。
- 公開mockとprivate previewを維持。コード変更、CI設定、deployment、ODPT API通信、secret参照、commit/push/mergeなし。

## 2026-10-26 — T12 Phase 1 公開用payload profile

- `scripts/public_payload_profile.py` を追加。schema v1の `local-preview-only` 入力だけを受け付け、新しい `public-display-v1` scopeへallowlist射影する。未知項目は出力せず、元入力は変更しない。不正schema/scope、欠落必須値、不正日付・時刻・ID、重複serviceDate、目的地不一致、空service dataを明示エラーにする。
- adapter必須項目と候補判定に必要な `id` / `originTripId`、serviceDate、発車・到着秒数、primary/direct/transfer、transfer wait、destination statusを維持。時刻表示値と25時台service secondsも保持する。raw ODPT train type URI、照合診断、stop-pattern診断、内部ログ、API key風値、絶対パス、未知項目は除外。adapter必須のODPT destination ID配列は保持する。
- `tests/fixtures/public_payload_profile_input.json` と `tests/test_public_payload_profile.py` はsynthetic値のみで追加。allowlist・未知field除外、scope分離、ID/旅程構造、serviceDate/時刻、空・不正入力、決定性、入力不変を確認。
- テスト結果: synthetic-only Python subset 35件成功。保存済み実ダイヤを扱う既存Python test classesは実ダイヤ変換禁止のため未実行。Node全体78件成功、`TZ=UTC`でも78件成功。
- Phase 1単独では公開profileは現行adapterに未接続。Phase 2でadapter/loaderへpublic scope対応を加え、ローカルprofileの拒否維持と候補・終電/始発判定をsynthetic payloadで回帰確認する。private preview、adapter、loader、UI、公開root mock、Cloudflare設定は変更せず、実ダイヤ変換・ODPT API・秘密情報参照・deployment・Git操作なし。
