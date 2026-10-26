# プロジェクト状態

## T11/T12/T13/T15 状況（2026-10-26）

- **T11 利用条件確認: 完了。** ODPT事務局から、相談した想定利用方法における時刻表データの加工・配信、server-side保存/cache、基本ライセンスとガイドラインを守る広告・任意支援付き無料公開は問題ないとの回答を受領。データ更新状況は開発者サイトのNewsで適宜掲載するとのこと。回答の対象範囲を超えた包括的許可とは解釈しない。記録は [`odpt_research.md`](odpt_research.md) のT11節。
- **T12 正式配信方式・ホスティング: 進行中。** Phase 1（公開payload profileのallowlist射影）、Phase 2（adapter・loader対応、synthetic互換性確認）、Phase 3-1（共有runtimeとlocal/public entrypointの分離）を実装済み。Phase 3-2のproduction HTML/CSS分離、静的builder、Cloudflare接続、CI、実ダイヤの変換・公開は未実施。推奨案はCloudflare Pages静的配信 + GitHub Actions更新処理。Workersは不要。比較・条件・段階計画は [`hosting_research.md`](hosting_research.md)。
- **T13: 未着手。T15: 未着手。**
- 現在のGitHub Pages root mockとApplication Supportのlocal previewは維持。実ダイヤの一般公開はしていない。GitHub remote settings / secretの有無は今回確認していない。`.env.local`、API key、ODPT APIにはアクセスしていない。

## T12 Phase 1 公開用payload profile（2026-10-26）

- `scripts/public_payload_profile.py` にschema v1 `local-preview-only`入力から `public-display-v1` へ射影するオフライン変換関数を追加。許可フィールドだけを新しいオブジェクトへコピーし、入力を変更しない。未知のフィールドは深い階層でも出力しない。
- serviceDate、運行駅、時刻表metadata、候補ID (`id` / `originTripId`)、route、発車秒数、primary/direct/transfer itinerary、transfer wait、データ状態、destinationStatusのroute countsなどadapterが要求する構造を維持。25時台service secondsもそのまま保持する。
- raw ODPT train type URI、照合理由・方式、stop-pattern診断、内部ログ、任意未知項目、API key風フィールド、絶対パスはallowlist対象外。adapterが必須としている `odptDestinationIds` / `outgoingDestinationIds` は識別値として保持する。公開前の再構成可能性・利用条件reviewは引き続き必要。
- synthetic fixtureと `tests/test_public_payload_profile.py` を追加。local/public scope混同、必須値・日付・時刻・ID・直通/乗換、空データ、不正値、未知項目除外、決定性、入力不変を検証する。
- テスト: synthetic-only Python subset 35件成功。実ダイヤを生成する既存Python test classesは今回の制約により実行対象外。Node全体78件成功、`TZ=UTC`でも78件成功。
- Phase 1の時点ではprivate preview、adapter、loader、UI、公開root mock、payload生成処理を変更せず、profile出力のadapter接続は未実施だった。Phase 2でpublic scopeを明示対応し、候補・終電/始発動作をsynthetic payloadで回帰確認済み。Cloudflare・実ダイヤ変換・外部送信・deploymentなし。

## T12 Phase 2 adapter・loader公開profile対応（2026-10-26）

- adapterの`validateTimetablePayload`・`prepareTimetablePayload`・`buildBoard`に期待profile引数を追加。local scopeが既定で、public scopeは呼び出し側が`public-display-v1`を明示した場合だけ受理。prepared payloadにもprofileを結び付け、別profileでの再利用を拒否する。schema・payload内容検証と共通候補判定を維持。
- loaderは`expectedProfile`と`cacheMode`を受け取る。localは`no-store`、publicは明示された`default`（ブラウザーHTTP cache経由、Pages ETag再検証を想定）に限定。公開profileでcacheMode省略、localに異なるcacheMode、未知profileはエラー。駅別取得・2駅LRU・stale判定・既存計測・失敗処理は維持。
- local preview entrypointとpayload検証scriptもlocal profile / `no-store`を明示するよう更新。UI表示・文言・レイアウトは変更せず、private/QA previewを再生成していない。
- Phase 1射影との比較中、直通のみのroute終電判定が必要とする`destinationStatus.routes[*].directCandidateCount`をPhase 1 allowlistが落としていたことを検出。候補判定コードは変更せず、Phase 1 profileでこのfieldを全目的地向けに保持し、25時台・direct-only terminalを含むlocal/public比較を追加。
- synthetic fixtureで発車順・最早着・路線分類・直通/乗換・乗換待ち・direct-only・路線別終電/直通終電・終電後・前serviceDateの25時台・翌朝の各路線60分前gate・HeiwadaiのdestinationStatus/candidate countが一致することを検証。表示判断の比較は一致し、診断フィールドは射影により意図どおり異なる。
- テスト結果: Node全体87件、`TZ=UTC`でも87件成功。実データ非依存Python subset 35件成功。JavaScript/Python syntax確認と`git diff --check`成功。実ダイヤを生成する既存Python test classesは対象外。
- 実ダイヤ変換・API/secret参照・外部送信・Cloudflare設定/デプロイなし。保存済みprivate previewとQA previewは再生成・変更していない。公開root mockとGit操作もなし。

## T12 Phase 3-1 runtime分離（2026-10-26）

- 通常の目的地選択、表示順・直通filter、payload load、stale制御、adapter候補判定、カード／状態描画を`_local_preview/preview_core.mjs`へ移した。DOM要素を初期化時に列挙して不足要素を明示エラーにし、現在時刻provider・診断hookを呼び出し側から渡す。
- `_local_preview/preview.js`はlocal bootstrapとして維持し、`LOCAL_DATA_SCOPE` + `cacheMode: 'no-store'`、`debugNow`、`perf=1`、計測履歴・コピーを担当。診断moduleのimportはこのentrypointに限定した。
- `_local_preview/preview_public.js`は`PUBLIC_DATA_SCOPE` + `cacheMode: 'default'`と実時刻providerを固定する。設定上書き引数を公開せず、local仮想時刻・計測moduleをimportしない。production HTML/builderは本Phaseでは作っていない。
- `prepare_preview.py`のlocal preview file allowlistに共有coreを追加した。既存private preview・QA previewの生成物は再生成していない。候補ロジック、DOM文言、CSS、公開root mockは変更していない。
- `tests/preview_runtime_split.test.mjs`でprofile/cache契約、DOM依存検証、entrypoint間の診断境界・時刻/hook注入を確認。既存のsynthetic profile互換性テストがlocal/publicの候補・終電／始発判断を比較する。
- 確認: Node.js 91件成功（通常・`TZ=UTC`）。実データ非依存のPython subset 35件成功。3 JavaScript module構文確認と`git diff --check`成功。保存済み実データを読むPythonテスト群はsynthetic-only制約により未実行。
- Phase 3-2以降: production HTML/CSS分離、synthetic-only静的builder、成果物allowlist/診断混入検査、実装後のartifact検証。Cloudflare Pages・CI・production payload生成は未実施。

## T12 Phase 3-1 初期表示不具合の修正（2026-10-26）

- 原因: `collectElements()`がDOM ID文字列（例`destination-trigger`）をproperty keyにしたobjectを返していたが、runtime初期化がcamelCaseの`destinationTrigger`等を直接destructureしていた。その結果、listener登録時に同期TypeErrorとなり、loader呼び出し前にentrypointが停止してHTML初期文言「読み込み中…」が残った。
- 修正: DOM IDをcamelCase変数へ明示的にaliasするdestructuringへ変更。初期loader promiseの予期しないrejectは既存のload error表示へ遷移させ、local/public bootstrapの同期初期化失敗も状態欄へエラー表示する。profile/cache契約・候補計算・表示ロジックは変更なし。
- synthetic初期表示テストを追加し、local (`no-store`)・public (`default`)の両runtimeで初回fetchが行われ、loadingを抜けて状態DOMが更新されること、予期しないloader rejectがerror表示になることを検証。
- 通常private previewを再生成。2026-10-25〜27、8駅、22,115,799 bytes。全駅payload validator成功し、生成bundleの`preview_core.mjs`・entrypoint・module source一致を確認。HTTP server経由でSafariに実表示し、列車カードが表示されることを目視。HTML/JS/core/payloadのHTTP応答は200。
- 確認: Node.js 94件成功（通常・`TZ=UTC`）。実データ非依存Python subset 35件成功。source/generated JS構文確認と`git diff --check`成功。Console panelのエラー収集は実施していない。
- QA専用previewと公開root mockはこの処理の出力対象外。ODPT/API key参照、外部送信、deployment、Git操作なし。

## iPhone Safari目的地切替計測（ローカルpreview限定）

- URLに `?perf=1` を付けると、目的地切替後に最新結果と直近10件の履歴を表示する。`debugNow`と併用可能。通常アクセスでは計測欄を隠し、目的地別の計測結果はページメモリ内だけに保持する。
- 記録値は目的地名、総時間、Network、`fetchMs`、`bodyReadMs`、JSON parse、schema検証・カード事前生成、board、表示selection、描画、メモリcache hit/miss、payload byte、結果状態。最新値・履歴の両方にfetch/body内訳を表示し、計測履歴はテキストでコピーできる。外部送信・計測結果のlocalStorage保存なし。
- `fetchMs`はfetch開始からHTTP応答ヘッダー受信まで、`bodyReadMs`は`response.text()`開始から本文文字列読込完了まで。本文読込には転送と文字列化を含む。`networkMs`は両者の合計（失敗時は到達済み区間の合計、未実行区間は未実行）。`prepareMs`は目的地整合確認・schema検証・カード事前生成。`boardMs`はbuildBoard全体、`selectionMs`は3+3件／6件の表示選択。
- `renderMs`は最終DOM更新開始からrequestAnimationFrame 2回目までの画面反映近似。`totalMs`は選択操作開始から同時点までであり、各段階を含むwall time。段階値同士は重複しないが、totalと個別値は加算しない。ロードエラー時は未実行段階を「未実行」とし、画面にエラー状態を反映するまでの時間を記録。古い応答はその駅自身の負荷だけを記録して「別駅へ切替済み」とし、総時間・描画時間は出さない。
- 目的地切替履歴は最新10件で、直近2駅LRUのcache HIT時はNetwork・JSON・prepareを0、payload byteを未取得として表示する。再読込後は履歴・メモリcacheとも消える。簡易HTTP・Wi‑Fi・端末状態・SafariのrequestAnimationFrame間隔は計測結果に影響する。
- `prepare_preview.py`が新しい計測moduleをprivate Application Support previewへコピーする。公開root mockと実ダイヤ配信先には反映しない。
- iPhoneはMacと同じWi‑Fi上で、通常previewを `python3 -m http.server 8765 --bind 0.0.0.0 --directory "$HOME/Library/Application Support/dotchi-ikebukuro-preview/site"` で配信し、`http://<MacのLAN IP>:8765/index.html?perf=1` を開く。仮想日時QAは `&debugNow=...` を続けて指定できる。確認後はserverを停止する。

## 通常private preview最終確認準備（2026-10-26）

- 保存済みローカルGTFS/ODPT入力から通常private previewを再生成。通常出力先はApplication Support内の `dotchi-ikebukuro-preview/site`、運行日は2026-10-25〜27、8駅、payload合計22,115,799 bytes。生成45.6秒、payload検証2.1秒。
- GTFSの適用期間は2026-09-19〜2027-03-12。今回必要なservice day（10/25・10/26・10/27）は全て収録され、現在日時で全8駅の通常／直通のみpayload評価がvalid。8駅すべてのpayloadをschema・metadata validatorで検証。
- 配信bundle内のHTML、CSS、JS、adapter、loader、validator、`terminal_ui.mjs`、`virtual_now.mjs`は各ソースと一致。氷川台の10/26副都心線はGTFS明示通過13件を`passThroughCount`へ計上し、`dataInsufficientCount` 0、乗換候補213件を保持。終電・始発判定も最新adapterとUIを含む通常previewへ反映。
- 利用者からMac Chrome／iPhone Safari実機QA完了の報告あり。終電badge、片路線・両路線終了、始発60分前の路線別再開、路線別／発車順、目的地切替、iPhoneの6件表示・カード配置・広告dockを目視し問題なしとのこと。
- QA専用previewは通常previewと別ディレクトリのまま未変更。公開root mock・公開配信先への変更なし。

## 終電・翌運行日の候補表示 Phase 1（2026-10-26）

- `scripts/timetable_adapter.mjs` は、目的地へ到達可能な候補をserviceDate・池袋発路線ごとに集計し、最終発車を`isLastDeparture`で返す。通常表示はprimary候補（直通／乗換）、直通filter時は直通候補のみから判定する。終電判定は池袋発時刻で行い、最早着選定とは独立。
- 運行日別状態は`routeStates`、全体状態は`serviceState`で返す。`ended`は両路線のroute stateがendedの場合だけ。運休日、到達候補なし、データ不足、旧payload／不完全metadataは別状態にし、候補ゼロを終電終了とはみなさない。
- serviceDate・路線の最初の到達可能候補の発車60分前から当該日の候補を表示する。前日serviceDateの24時超の候補はserviceDateを維持し、翌serviceDateとは別に判定する。既存の24時間horizon、期限・必要service day検証、最早着選定は維持。
- 表示件数の制限前に終電候補を判定する。selectionは従来どおり路線別の直近3件／発車順の直近6件を返し、終電候補が範囲内にある場合だけ`isLastDeparture`が選択結果に残る。表示範囲外の終電候補は通常候補を押し出さない。
- Phase 2 UIは`isLastDeparture`と認識済み`terminalBasis`からカードに「終電」／「直通終電」を表示し、`serviceState === 'ended'`の場合だけ終了文を表示する。エラー／データ不足は既存の警告・安全停止へ流し、目的地切替の読込中は旧カードを消去する。毎秒の既存tickで始発60分前ゲート・終電後状態を反映する。
- 終電badgeは種別・行先と同じ領域にコンパクトに追加。発車・countdown・到着列、カード最小高68px／間隔4px、6件制限、広告dock・safe-areaと公開root mockは未変更。
- ローカルpreviewの配信bundleへ`terminal_ui.mjs`と`virtual_now.mjs`を含め、2026-10-25〜27の保存済み入力からprivate Application Support previewを再生成済み。公開配信は行っていない。
- exporterは全8駅でroute別`scheduledTripCount`、池袋発trip、到達候補、直通／乗換データ不足をpayloadへ出力する。氷川台も日別`destinationStatus`を持つ。古いpayloadもschema validatorでは読めるが、終電根拠がないserviceDateはunknownとして扱い、未来日の候補は安全のため出さない。
- 自動テスト追加: 路線別終電・片路線終了・遅い乗換・直通filter、24/25時、23:50/00:10/00:40/01:30/05:00、発車境界、始発60分前境界、serviceDate分離、データ不足／運休日／到達候補なし、8駅payload形状、表示上限への終電保持。
- 確認: Python unittest 50件成功。Node全体60件成功、`TZ=UTC`でも60件成功。テストはローカルGTFS/ODPT保存データを読み、外部API通信はしていない。preview payloadは別途ローカル保存データから再生成済み。

## ローカルpreviewの仮想日時QA

- `_local_preview/virtual_now.mjs` はURLの`debugNow=YYYY-MM-DDTHH:mm[:ss]`をAsia/Tokyoの壁時計として解釈し、`buildBoard`に渡す`nowMs`だけを固定する。端末TZに依存せず、日付不正・時刻不正・タイムゾーン接尾辞付きなどは無視して実時刻へ戻す。
- 有効な指定時だけ「テスト日時：YYYY/MM/DD HH:mm」を表示。指定時の時計・列車・カウントダウンは進まず、通常利用はパラメータを外すかページを再読込する。
- Mac Safari例: `http://127.0.0.1:8765/index.html?debugNow=2026-10-27T00:10:00`。iPhone SafariはMacと同じLAN上で、preview serverをMacのLAN IPへbindして`http://<MacのLAN IP>:8765/index.html?debugNow=2026-10-27T00:10:00`を開く。確認後は`debugNow`をURLから外して再読込する。公開ホストへ配置しない。
- 仮想日時が現在のpayload適用期間・必要service dayに収まらない場合は、既存の安全停止で列車を表示しない。ロジックは日付を補完しない。
- QA後の修正: 次serviceDateの候補は60分ゲート前に`running`を引き起こさない。前serviceDateが両路線ended、当日路線がnot_startedの間はserviceState=`ended`。路線別の始発ゲート到達でそのrouteだけrunningとなり、全体はpartial、両路線が到達したらrunning。前serviceDateの24/25時便が未発車ならroute stateはrunningを保つ。
- 運休日・到達候補なしはno_service/no_candidatesを維持し、前serviceDateの終電証拠が不足ならunknown。payload不足・期限切れは既存のunavailable安全停止を維持。
- 修正確認: Python unittest 50件成功。Node全体70件成功、`TZ=UTC`でも70件成功。ODPT APIアクセス・root mock変更なし。
- 修正adapterを含むprivate previewを保存済み入力から再生成済み（8駅、2026-10-25〜27）。公開先への実ダイヤ配置なし。

## 公開モック準拠のローカルpreview UI

- `_local_preview/index.html` は公開モックと同じヘッダー／時計、注意表示、ルート枠、44px操作行、カードDOM、下部広告dockの構成。`prepare_preview.py` はroot `styles.css` をローカル出力へコピーし、preview.cssで状態表示・折りたたみmetadataを補う。
- 実ダイヤ側はローカルデータ注記、適用期間バナー、安全停止、payload適用期間／生成日時／GTFS・ODPT更新日時／Web build日時の個別表示を維持。未取得日時は「未取得」。
- 8駅の目的地選択はPhase 4Aでpreview専用に追加。selectionの列車候補・件数制限ロジックは維持し、ルート枠でモーダルを開く。Phase 4A.1で選択IDのみlocalStorageに保存・復元し、payloadは端末保存しない。

## iPhone Safari縦レイアウト調整

- 6列車カード、公開モック由来カード寸法、320×50広告dock、本文の広告高＋20px＋safe-area予約を維持。通常時の最下部注意文は通常画面から除き、payload詳細内へ移動。例外発生時の状態バナーは引き続き表示。
- 上部のCSS余白を合計20px圧縮。iOS Safariではヘッダーをsafe area内側のsticky位置に置き、ステータス表示との重なりを抑制する。実機での最終目視確認が残る。

## ローカルpreview更新（T01）

- `python3 _local_preview/prepare_preview.py` は保存済みGTFS/ODPT必須ファイルを確認し、JST前日・当日・翌日の8駅payloadをリポジトリ外の一時stageで生成します。氷川台の互換ファイル名は `timetable.json`、他7駅は `timetable-{stationId}.json` です。
- 全payloadを既存adapterでJSON/schema/必須metadata、適用期間、現在必要なservice dayについて検証し、すべて合格後にのみpreview一式を置換します。1駅でも生成・検証に失敗した場合は既存siteを維持します。外部通信・データ再取得はありません。
- 元データ更新時刻・Web build時刻は未確認のままnull。payload生成時刻は更新時に変わりますが、元データが古い可能性は残るため鮮度保証ではありません。24時間TTLなし。
- 自動テスト: `python3 -B -m unittest discover -s tests` とNodeテスト。実payload再生成には保存済みローカルデータが必要です。

## T14 Phase 4A 目的地選択・payload切替

- ルート枠を目的地選択ボタンにし、要町・千川・小竹向原・氷川台・平和台・地下鉄赤塚・地下鉄成増・和光市を順番どおりに選ぶモーダルを追加。選択状態、Escape/閉じる、矢印/Home/Endキー、フォーカス復帰、背景スクロール抑止、safe-areaを扱う。UIレイアウト変更はモーダルとルート枠に限定。
- loaderは固定station ID→固定filename対応を使用し、選択されたpayloadだけを取得。payload内の全service dayが選択IDと一致しなければ拒否する。更新時は旧カード・metadataを消して読み込み中を示し、最新要求tokenで高速切替の古いresponseを破棄。失敗時は列車を表示せずエラーを示す。Phase 4A.1でlocalStorageにstation IDのみを保存・復元し、保存値不正やstorage利用不可は氷川台へfallback。
- 目的地別の既存旅程生成と直通filter／路線別・発車順／最早着／countdownは維持。Phase 4Bでは画面上部に選択駅を表示し、カード到着ラベルは共通の「到着」とする。
- Phase 4A自動テストでは8駅の固定mapping、payload不一致・未知ID拒否、非同期切替競合、8ファイル生成・検証、途中失敗時の既存preview保持を確認。実payload 8件も生成・検証し、現在の保存先に反映済み。生成40.0秒・検証1.7秒、総容量22,109,229 bytes。氷川台は独立exporterとの比較でgeneratedAt以外一致。
- Phase 4A.1ではlocalStorage保存障害・不正値のfallback、2件LRUのメモリ内prepared payload cache、fetch/body/JSON/adapter/selection/DOM計測を追加。キャッシュ利用時も`buildBoard`を都度実行し、期限・必要service dayの判定は維持。自動テストはPython 49件、Node 43件、adapter UTC 24件が成功。Safari実機の目的地記憶と計測確認が残る。
- Phase 4B/T17で操作行を左モード・右直通filterの順にし、初期モードを発車順へ変更。発車時刻を到着時刻相当の15px/800、直通・乗換説明を発車までラベル相当の12px、時刻ラベルを数値の上に中央配置し、到着ラベルは「到着」に統一。ルート枠は「▼ 目的地を選択」を表示する。カード最小高68px・間隔4px、6件、広告dock/safe areaを定義する既存スタイルは維持。
- T17回帰: Python unittest 49件、Node全体44件成功。公開mockのroot HTML/CSS/JSに差分なし。8駅payload再生成（22,109,229 bytes、生成46.3秒、検証1.8秒）。配信コピーを確認し、iPhone用serverは `192.168.11.7:8765` のみへbind。
- T17実機追加修正では、数値3列を同じ4px下げ、route/countdown/arrivalの見出し行を上端固定。左3行の空きを減らし、全8駅・平日/土休日payloadと2026-11-03祝日の一時生成分で長い表示組合せを調査。Mac CoreText system-font参考幅は最大193.98px、iPhone 12相当390px幅で左列215px。水平padding/gapと右列幅を小幅調整し、文字拡大・狭幅では種別/行先が折り返せる。

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
- Phase 3対象の4駅追加・Phase 3.5乗換候補共通化を完了。Phase 4Aで8駅選択と目的地別payload切替をローカルpreviewへ実装。Phase 4Bでレイアウト調整を行う。

## T14 目的地拡張 Phase 3.5

- 目的地カタログで経路方針を管理する。要町・千川・小竹向原は直通のみ、氷川台・平和台・地下鉄赤塚・地下鉄成増・和光市は直通＋小竹向原での別trip乗換候補に対応。
- 乗換元・先の路線、service day、乗降可、停車順、時刻の単調性、目的地到着・降車可を検証。60〜600秒の既存範囲、直通優先／最早着主候補選定は維持。別tripを同一列車の継続や直通旅程として扱わない。
- `destinationStatus` は直通候補、乗換候補親trip、乗換候補組、乗換のみ、乗換不足・通過を分ける。既存の部分候補方針を維持し、不完全な乗換データを直通旅程の不足判定に混ぜない。氷川台・既存3駅の出力回帰はgeneratedAt以外のpayload一致で確認。
- 小竹向原の公式駅案内・バリアフリー情報・構内図は [`odpt_research.md`](odpt_research.md) を参照。3・4番線の同一島式ホームという駅構造情報があっても、GTFSから番線や列車別接続保証を確認できない。全transferは `connectionGuaranteed=false`、platform unknownで、「時刻表上の乗換候補」として扱う。60秒を保証時間と解釈しない。
- Phase 4では1〜2分候補が多数あること、接続保証・番線情報がないことを利用者へ伝える表示と、候補の扱いを検討する。今回はUI・最低乗換時間・選定方式は変更しない。

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
- 正式ホスティング設計調査の推奨はCloudflare Pages静的配信 + GitHub Actions build/update（Workersなし）。実装・採用・公開は未着手。詳細は [`hosting_research.md`](hosting_research.md)。
- Google AdSense等の広告、任意支援サービス、公共交通オープンデータチャレンジ応募は検討段階。採用・応募は未決定。
- 版数／アプリ更新日時を表示する案がある。時刻表データ更新日時とは分けて検討する。

## 作業上の注意

実ダイヤ導入までは架空データの警告を残す。ODPT仕様、データ提供状況、利用条件や外部サービスの仕様は確認前に断定しない。詳細な判断経緯・作業・検証結果は devlog.md に追記する。

## 2026-10-27 — 仮想日時QA専用preview

- `_local_preview/prepare_qa_preview.py --target-date YYYY-MM-DD` は保存済みローカルGTFS/ODPT入力から、QA対象日の前日・当日・翌serviceDateを含むpreviewをApplication Support配下の `qa/YYYY-MM-DD/site` に生成する。通常previewの `site` は出力先にしない。
- 生成は既存 `prepare_preview.prepare()` のステージング・payload検証・入替/rollbackを利用する。QA validatorだけは対象日のJST日時を基準にrequired serviceDateを検証する。GTFS適用期間外の日は拒否され、既存QA出力を保持する。外部APIへは接続しない。
- 仮想日時QAには対象日の両隣のserviceDateが必要。通常previewの固定日付幅（生成時のJST前日・当日・翌日）と仮想時計が別日になると `missing_service_days` になることがあった。
- 2026-10-27 QA payloadは10/26〜28の3日分で生成・検証済み。GTFS `drop_off_type=1`の明示通過と到着時刻欠落を区別するよう修正し、氷川台・副都心線の13件はpassThroughCountに分類、dataInsufficientCountは0。00:40/01:30とも通常・直通のみで両路線ended。詳細はdevlogの2026-10-27分類修正記録。

## T14 Phase 3 — 並走区間8駅の目的地payload（2026-10-23）

- 8駅すべてを `VERIFIED_DESTINATION_IDS` に登録。追加4駅（平和台・地下鉄赤塚・地下鉄成増・和光市）はPhase 2と同じ同一GTFS trip限定の直通判定で有効化。小竹向原等で別tripを接続する処理は追加していない。
- 代表3日で全追加駅が `normal`。データ不足0。平和台・地下鉄赤塚・地下鉄成増は副都心線に明示通過便（平日13、土曜/祝日34）があり除外。和光市には明示通過なし。24時超到着は維持。
- CLI `scripts/export_local_timetable_payload.py --destination-station-id <ID>` で各駅の検証payloadを生成可能。`_local_preview/prepare_preview.py` とpreview UIの既定目的地は氷川台のまま。選択UIはPhase 4。
- T01–T03の期間/service day/status安全判定、ODPT照合、raw type・F-Liner分離、有楽町線route ruleに変更なし。T14詳細集計とPhase 3テストは `docs/devlog.md`。

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
