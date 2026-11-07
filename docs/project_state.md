# プロジェクト状態

最終整理: 2026-11-07。仕様の正本は [product_spec.md](product_spec.md) と [ui_spec.md](ui_spec.md)、ODPT/GTFSの根拠と未解決事項は [odpt_research.md](odpt_research.md)、配信方式は [hosting_research.md](hosting_research.md)。詳細な作業履歴は [devlog.md](devlog.md)。

ODPT-2Fの更新・鮮度管理方式は設計提案として文書化済み（未実装）。ODPT News確認を一次情報とし、7 sourceの取得履歴・hash・差分検証・非公開candidate・人間承認・期限切れfail-closedを段階導入する案。実データ公開、自動公開、取得workflowはいずれも未承認・未実施。詳細は [odpt_research.md](odpt_research.md) のODPT-2F節。

ODPT-2G Phase 0〜1D、Phase 2A基本差分、Phase 2B-2a/2b意味比較を実装済み。意味比較対象はODPT JSON 6 source（TrainTimetable、Railway、Station、StationTimetable）で、両storeと両側7原本のhash/byte数を検証する。StationTimetableの動的boolean keyはopaque extensionとしてcoverage partial。GTFSの補助関係やStationTimetableのopaque keyは部分評価のため、実自己比較の全体semanticStatusはindeterminate。取得履歴は不明で、鮮度・同一ダイヤ性・旅程品質・公開資格は判定しない。詳細はODPT-2G節とdevlogを参照。

Phase 2B-2c-1では独立read-only GTFS loaderを追加。11テーブルのZIP/CSV安全検証・key/参照検証・日付/時刻/sequence正規化をメモリ内で行う。Phase 2B-2c-3でGTFS全11テーブルの意味比較と固定7 sourceの統合を追加。新しいodpt_semantic_compare.pyからcoverage・確定差分・曖昧性・checksを一括確認できる。既存ODPT比較・6テーブルCLIの対象/終了コードは維持する。実自己比較の既知差分は7 sourceとも0、GTFSのshape/block補助関係・StationTimetable opaque keyは未解明のまま。

Phase 2C-2aの品質比較入力基盤を追加。Phase 2C-1採用契約をresearchへ記録し、strict evaluationContext、15依存ファイル・実行環境のengine fingerprint、両storeと14原本のread-only検証を行う。同一Snapshot自己比較でreadyを確認。readyは条件・入力の一致のみで、旅程生成/metrics/品質差分/表示モデルは未評価。

Phase 2C-2b-1で単一Snapshotのgenerator/v2基本metrics収集を追加。初期3日×8駅×2出発路線の48セルで生成行G・表示候補C・実測除外E、primary直通/乗換、除外理由、generatorが保持するalternative/接続組数をメモリ内に返す。既存入力検証と原本7件/store8件の開始・終了照合を利用し、collector自身もengine依存へ追加（現在16ファイル）。collectionStatusはpartialで、品質PASS・公開資格を表さない。matcher・UNKNOWN/WARNING・routeCoverage詳細、品質差分・表示モデルは後続。既存v2 gateと実データ公開未承認は維持。

Phase 2C-2b-2で単一Snapshotの詳細metricsを追加。collector専用の観測派生クラスでraw matcher状態を取得し、generator集約状態、primary/最良乗換alternativeの第1・第2区間、延べ参照/セル内一意対象、照合率の分子/分母を分離する。診断code・v2除外・validator error・routeCoverage・種別/行先の根拠を収集する。既存generator/matcher/v2 gateと表示ラベルは未変更。品質engine依存は17ファイル。全体collectionStatusはpartialを維持し、旧新品質差分・画面モデル・公開資格は未評価。

Phase 2C-2c-1で独立read-only `scripts/odpt_quality_diff.py` を追加。同じ凍結engine/contextで既存collectorをbaseline→candidateの順に実行し、基本9指標（除外理由は理由別）の差分を48セルで比較する。欠損・取得不能は0補完せず、両側の算術検査を独立に実行する。結果は非公開・メモリ内のみで、詳細保持上限・集計保持・決定的digestを持つ。比較自体もengine依存に加え現在18ファイル。全体comparisonStatusはpartial、確定変化ありならqualityDiffStatus=changed、基本差分0でも詳細/表示モデル未比較のためindeterminate。実自己比較は48セル・672比較で基本差分0、原本/store前後不変を確認。候補減少を品質悪化・公開資格へ変換しない。詳細metrics差分・画面表示モデル比較は後続。

Phase 2C-2c-2で詳細98指標の比較を追加。基本metrics/summaryの意味を維持し、詳細差分・詳細集計・詳細状態を追加fieldに分離する。同一engine/context/runtimeでraw・native・集約matcher、区間/primary・alternative/延べ・セル内一意、診断体系別、coverage、種別・行先を比較する。率は分子/分母を併記し、分母件数の変化は許容して明示、定義差と率未定義は数値差にしない。時刻・待ち時間の検査対象/違反件数はcollector未実装のため未評価。詳細上限1,000件を維持し、changed/not-evaluable/inconsistency明細を優先、unchanged件数は集計へ保持する。実自己比較は比較可能な基本/詳細差分と確定findingが0、分母0の率はnull、CLI終了0、全体partial/indeterminate。確定差分があればchangedを保持する。画面表示モデルと公開資格は未評価。品質engine依存は19ファイル。

Phase 2C-3b-1で独立表示context（schemaVersion 1）と非公開Node runnerを追加。固定UTC観測時刻・4シナリオ・JSTの必要3日を検証し、既存buildV2QaBoardの出力を正規化する。候補全体bestとgroups内カードを区別し、UNKNOWN・欠日・既知0件を混同しない。engine依存にrunner/context・selection・DOM JS/HTMLを追加。実source表示collector・旧新表示比較・DOM/視覚品質は未実装。原本/storeは使用せず合成QAのみ。

Phase 2C-3b-2で非公開単一Snapshot表示collector `odpt_display_metrics.py` を追加。Source/Snapshot入力・engine/runtime・原本/store前後不変を検証し、メモリ内v2生成・厳密な除外監査・既存QA state・Node runnerを接続する。固定観測時刻×8駅×4シナリオでitems/cards/best/routeStates/UNKNOWNを収集し、候補0件と評価不能を区別する。CLI既定は2026-10-29 12:00 JSTの32表示セル。表示差分・DOM/視覚品質・公開資格は未評価。engine依存はcollectorを加え26ファイル。

Phase 2C-3c-1で独立した非公開表示モデル基本差分CLI `odpt_display_diff.py` を追加。同じ凍結engine/旅程・表示contextで既存collectorをbaseline→candidateの順に実行する。IDを除いた選択journey内容の多重集合・順序、groupsとbest/表示マークを比較し、重複の曖昧性と評価不能を保持する。unchangedは集計し、actionable明細だけ上限保持。routeStates/始発終電UNKNOWN詳細分類とDOM/視覚品質は未評価なので全体partial/indeterminate、確定差分があればchanged。engine依存は比較自身を加え27ファイル。

Phase 2C-3c-2で同CLIへboard観測範囲の詳細状態差分を追加。日×路線のrouteStates/terminalKnown、board serviceState、始発/終電案内・終電候補のgroups内/上限外表示・UNKNOWN抑止・JST暦日とserviceDate/発車epochの対応を比較する。基本summary/items/groups/bestの意味は維持し、stateSummary/stateDiffs/stateTransitions/stateChecksと統合displaySummaryを追加。欠損・未知状態値・不整合と確定差分を独立に保持し、品質悪化や公開資格に変換しない。全件集計、明細リスト別既定1,000件上限、unchanged集約、決定的digestと終了コード0/2/3/4を維持。既定32セルの実source自己比較は基本・全状態差分0、整合2,304 checks PASS・終了0。終電/日付境界4時刻の追加128セルも全差分0・9,216 checks PASS・終了0。DOM/視覚品質、board外の最終候補、生coverage dataState/WARNING件数、鮮度・公開資格は未評価、全体partial/indeterminateを維持。helperの自動依存追跡でengineは28ファイル。実データ公開未承認・既存generator/matcher/adapter/公開gateは維持。

Phase 2C-3d-2で合成専用の固定時計DOM harness・表示整合テストを追加。既存Fake DOM、メモリ内fetch、実candidate bytes/hash・公開ID検証、Web Crypto、手動intervalを利用し、同じepochのreference board.groupsとDOMカードの構造・順序・文言・classを検証する。4シナリオ、直通alternative、上限内外best/終電、countdownのミリ秒境界、8 routeState、UNKNOWN/INFO/補助日coverage、24/25時、空表示・検証失敗、後始末・反復決定性を確認。実HTMLの接続は標準HTMLParserによる別検査。最終の関連Node57件（v2 DOM20件含む）・Python20件（HTML3件含む）がPASS。途中失敗はテストがIntlのcomma区切り日時をdatetime-localへ渡したことが原因で、境界観測を固定Date.now＋手動intervalへ修正した。既存adapter/DOM/UI・品質比較・公開gate・engine 28依存は未変更。Node意味表示の合成QAを追加した範囲であり、既存比較のpartial/indeterminateは維持。実source接続は3d-3、ブラウザー実描画・CSS/フォント/safe-area・focus/アクセシビリティ・HTTP/CSP/cache・鮮度/公開資格は未評価。

Phase 2C-3d-3aで独立read-only `scripts/odpt_dom_metrics.py`（`dotchi.odpt.dom-qa`/schemaVersion 1）を追加。既存collectorの駅日生成・厳密除外監査・envelope・bounded Node transportと3d-2 DOM harnessを共有し、全8駅×必要3日をメモリ内で一度ずつ生成・監査して全駅QA stateを構成する。DOM対象は固定2026-10-29 12:00 JSTの千川・氷川台×4scenario＝8セルに限定。候補object/canonical bytes/hash/IDを同一入力として既存Node adapterとDOM entryへ渡し、groups/内容/状態/countdownを照合する。generator/matcher/v2射影/QA state/adapter/DOM/UI・公開gateの規則は維持。completeは宣言したNode DOM意味評価範囲のみを表し、既存比較のpartial/indeterminateは変更しない。runtime/engine条件差はincomparable、欠損・利用不能・既知0・不整合をreason/availabilityとnullで区別する。engineは新collector/runner/harnessを加え31依存となり、旧engineの結果は同一条件比較不可。実source smoke、合成/回帰結果と実測値はresearch/devlogに記録。全駅・全境界へのDOM評価拡大、旧新DOM比較、実ブラウザー/CSS等の視覚品質、鮮度・公開資格は未評価。

Phase 2C-3d-3bでは既存DOM QA API/CLIに明示的な全8駅選択を追加し、引数なしの既定2駅×4scenario＝8セルを維持した。2026-10-29 12:00 JSTの32セルを同一engine/contextで2回実行し、両方complete・352 checks PASS・同一digest。各runで8駅×3日=24駅日を一度ずつ生成し、Node runnerは32回起動。10/31は必要日10/30・31・11/1を原本から生成でき、氷川台4scenarioの実source DOM QAで副都心線insufficient、data_insufficient、terminalKnown=false、warningを確認。既知状態の合成fixtureも既存テストで確認。現engineは32駅DOM対象の追加により3d-3a時からfingerprintが変化しているため旧engine間比較は不可。3d-3a節の未評価範囲は引き続き未評価であり、実ブラウザー描画や公開資格をcompleteに含めない。詳細と計測は [odpt_research.md](odpt_research.md) と [devlog.md](devlog.md)。

Phase 2C-3d-4では固定実source観測時刻4点（JST 10/29 23:59:59、10/30 00:00:00/00:12:59/00:13:00）で、氷川台・千川×4scenarioの計32 DOMセルを確認。全run complete・88 checks PASS/run、境界前後のcards/terminal/serviceStateと日付envelopeを記録し、原本/store不変。10/31 generator診断を単日集計で再確認し、6 unmatchedのうち3件がWARNING除外、残る3件は候補に含まれることを特定。adapterのroute9 candidateEligible=false、terminalKnown=false、DOMデータ不足表示まで証拠を区別した。品質比較は同じSnapshot/入力条件・完全一致engine fingerprint/runtime/contextを必要とする。基盤はNode DOM意味整合までで、異世代実データ比較の実績、鮮度/正確性/公開資格、実ブラウザー・視覚・アクセシビリティ・HTTP評価は未成立。公開前未解決事項と品質レイヤーの到達点はresearchに記録する。

## 現在の配信・QA経路

- **公開synthetic版:** 公開builder・validator・runtimeと手動起動CIはsynthetic fixture専用。公開データは実ダイヤではない。
- **Cloudflare Pages staging:** synthetic release-managed配信の初回・第2世代更新を確認済み。rollback、旧タブ継続利用など一部QAは未完了。
- **非公開ODPT v2 QA:** 保存済みローカルODPT/GTFSからcandidateを作り、localhost専用画面で検証する独立経路。公開artifactやv1 synthetic builderに接続していない。
- **実ODPT公開:** 未承認。自動公開も未承認。公開可能との判断は行っていない。

## 完了した主要機能

- v1 synthetic公開payload、独立artifact validator、synthetic-only builder/runtime、手動CI。
- release-managed manifest、世代別asset、独立validator、staging更新検証。
- 保存済みODPT/GTFSによるsnapshot QA、public-display-v2 candidate generator/validator、非公開QA画面。
- ODPT-1Dでは同一service date内の乗換待ち最大60分をv2候補に適用。共有v1条件は維持。
- 詳細・数値・検証履歴は [devlog.md](devlog.md) と [archive/t12_phase4_7_release_design.md](archive/t12_phase4_7_release_design.md) を参照。

## 現在の未解決事項

- 保存sourceの取得成功日時、最新性、ODPTとGTFSの同一ダイヤ版性。
- 実データの承認済み `applicationPeriod` と、GTFS feed期間との整合規則。
- JSON 6件の公式endpoint/filterと全件性。東京メトロGTFSのdate省略時の版とJSONとの整合は取得後に要審査。`date=current/next/latest`の解明・将来の通知運用は初回取得の必須条件にしない。
- 2D-3Cで明示ライブ許可・環境provider・受信範囲検査まで実装。実通信/実キーでの検証は未実施。未知selector・補助参照の意味解明、candidate gateは未完。保存済みsourceの取得成功日時・最新性・適用期間は不明のまま。
- 公開payloadの再構成リスク、表示・クレジット条件の実データ公開適用確認。
- release-managedのrollback実地確認、旧タブ・cache境界QA。
- 運行日境界を跨ぐ乗換探索は未実装。

ODPT事務局の2026-10-26回答で確認済みの範囲（説明した構成での加工済み時刻表配信、サーバー側保存/cache、広告・任意支援付き無料公開）は未解決に戻さない。回答の適用範囲を超える許可とは扱わない。詳細は [odpt_research.md](odpt_research.md)。

## 次の作業

1. 初回正式公開を優先し、[Phase 2D-3B](odpt_research.md#phase-2d-3b)の未確認事項（JSON endpoint/filter・全件性、date省略版、初回取得の許可範囲/非公開保存先）を確定する。指定PDF/画像の一般API根拠は2026-11-07に直接確認し、該当ページをresearchへ記録した。
2. 2D-3Cの最小実装・オフライン検証結果をレビューする。コードの完成と実通信の許可は別で、実取得はまだ実施しない。
3. 明示許可後の非公開7 source取得、版/全件性確認、既存2A〜2C評価へ進む。未解決QA・適用期間・公開条件を審査し、公開承認は別に行う。自動更新・監視設計は追加しない。

この文書は状態の要約であり、履歴の数値や手順を重複管理しない。

Phase 2D-2A: 既存manual fetchに、TLS検証・接続/読取timeout・制限付きredirect・サイズ/status/contentType検査、注入可能transport、attempt別開始/結果/非秘密証拠、手動retry、Snapshot確定前の全raw二巡照合を追加。実通信はCLI/real adapterとも無効。取得完了は公開資格を意味せず、publicationApproved=false/applicationPeriod=null/crossSourceConsistency=not-evaluatedを維持する。合成テストのみで検証。2D-2Bの評価接続は下記の専用adapterを使う。既存store readerへ直接渡す形式ではなく、retry親記録も含めて検証する。公式取得仕様・実TLS/転送・現行データでの動作は未検証。

Phase 2D-2B: 読取専用`odpt_evaluation_input.py`で確定済みfetch batchの全attempt/retry・成功選択・strict Snapshot参照/fingerprint・raw hash/bytes/形式を検証し、選択7件を既存2A/2B/2Cへ渡す。旧store reader/schemaと取得処理は維持。品質collectorの物理inventoryはattempt/証拠を含む可変数metadataへ対応。`odpt_fetch_evaluate.py`で評価stageと、2Cのservice dates/UTC観測1点/DOM対象駅を明示する。生成/QA stateは全8駅、scenario4種、同一凍結engine/context/runtimeを要求。原本コピー・レポート保存なし。公開承認/期間/版整合を変更しない。異世代実Snapshot・鮮度・公開資格・実ブラウザー描画は未評価。2D-3で実取得へ進むには公式経路/selector・期間/版整合根拠と明示的取得許可が必要。

Phase 2D-3A: manual fetchの固定7 source driverをCLIへ接続。新規先必須、最初の失敗/中断で停止、対象明示retry＋未試行sourceの続行、7成功後だけraw再照合/Snapshot確定を実装。通常CLI/real adapterはコード上のpolicy停止で通信禁止（定数や通常flagだけでは解除不可）。mock注入はPythonテスト入口のみ。補助batch/evidence v2はmock/liveを区別し、旧v1 offlineを維持。評価adapterは共通のprovenance検証を使用し、Source/Snapshot strict schema・承認状態は維持する。live形式の検証は合成fixtureのみで、実取得した証明にはしない。公式取得経路/認証/filter/date省略/全件取得条件と、ライブ設定・保存先・通信範囲の明示許可は未成立。

Phase 2D-3B: 2026-11-07に公式API仕様PDF pp. 7–10、API補足pp. 1/6、東京メトロGTFS公式catalog画像を直接確認。一般HTTPS/query認証/encode/filter/search upper-limit/dump endpoint根拠をresearchへ反映。JSON個別endpoint/filterと全件性は6件ともC。GTFS初期URL/認証/形式は画像に一致しA、省略版・転送先等は未確認。200/coverage/matcher/Snapshot completeは検索切捨てや共通欠落を証明しない。date省略案は会員ポータル補足の対象限定と東京メトロURLへの適用未確認を明記し、取得後にfeed/calendar・公式改正情報・JSON整合を審査。最小変更案と安全な実行計画をresearchへ集約。文書以外は変更なし。

Phase 2D-3C: 既存manual fetchへ通信なしplanと保存先/固定source/retry履歴の確認値、fetch/retry両方の明示許可経路を実装。許可後だけ環境providerを接続し、不正credentialは通信前に拒否。JSONの非空/@type/識別子/operator/指定railway検査を成功記録前・raw確定前に追加し、既存ZIP/TLS/HTTP/保存/retry/評価を再利用。承認状態・strict schemaは維持。テストはdummy/mockのみで、ライブ許可contextは発動せず、許可後のdispatch/native adapterをmock化して検証。実通信・実キーの使用なし。

2026-11-07 route9 coverage修正: 旅客利用可否とODPT照合品質を限定的に分離。利用者確認済みの土休日西武方面S-TRAIN池袋降車専用ルールを、rawの路線/日種/方向/種別/行先/一意番号/到着時刻/小竹向原乗降不可で絞って適用。対象行・未照合・WARNINGを保持しつつ乗車不可として候補から除く。独立行先crosswalk欠落だけの未照合は、有効旅程または明示通過がある場合に旅客coverageを阻害しない。未知/衝突/独立WARNINGとvalidatorのfail-closedを維持。根拠と限定条件はresearch、QA結果はdevlogを参照。公開承認・適用期間・外部通信・原本/storeは変更しない。

2026-11-07 ODPT-0ゲート修正: route9の証拠判定をQAと共有し、A/B解決区分とC/D阻害区分を追加。QA status=WARNING、原診断・未照合数を維持し、scope/fingerprint/全route complete/構造FAIL=0/未解決=0/駅日別と原数の算術一致で非公開候補生成を判定する。manifestに原集計・駅日別解決根拠を保存し再検証する。公開承認・適用期間は未設定。検証結果と保存先はdevlog参照。
非公開候補生成とbundle validator PASS（11/6〜8、8駅、9,576候補、48路線日complete）。QA status=WARNING、原未照合/原WARNINGは各96のままA48/B48/未解決0。回帰149件とDOM 176セル/1,936 checks PASS。候補/元QAレポートのprivate保存先はdevlogに記録。鮮度・版/適用期間・公開資格と公開承認は未確定。
