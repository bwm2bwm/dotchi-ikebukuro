# ODPT実データ調査（Phase 1）

> Phase 2の実データ解析結果は文書末尾を参照。
> 利用条件に関する2026-10-26の事務局回答は、過去の未確認事項を更新する情報として文書末尾の「T11 ODPT事務局回答」を参照する。回答の適用範囲を超える包括的許可とは解釈しない。

## 現在の確定事項・未解決事項（2026-11-07）

初回正式公開を優先する直近の取得判断は、末尾の[Phase 2D-3B](#phase-2d-3b)を参照。2026-11-07の公式資料に関するユーザー確認記録と、Codexが直接確認できた範囲を区別している。実通信は無効のまま。

### 確定事項

- 2026-10-26に共有されたODPT事務局正式回答では、相談した構成における時刻表データの加工・配信、サーバー側保存/cache、広告・任意支援を伴う無料公開は、東京メトロの公共交通オープンデータ基本ライセンスとガイドラインを守る条件で問題ないとのこと。これは説明済み構成への回答で、包括的許可ではない。回答内容はユーザー共有記録に基づき、個人情報・メールアドレスは記載しない。
- 更新通知の確認先は開発者サイト内「ニュース」。通知後の更新条件等は公式ガイドラインも適用。
- GTFS `feed_start_date`/`feed_end_date` は対象サービス情報の期間、`feed_version` はfeed版識別子。いずれも取得日時ではない。
- public-display-v2の `applicationPeriod` は未設定（null）、公開承認false。source取得成功日時・ODPT/GTFS版整合・適用期間根拠が揃っていないため。

### 未解決事項

- 6件の保存ODPT JSONについて、取得日時、更新単位・頻度、現行ダイヤへの適用を示す版/適用期間の公式メタデータ。
- 東京メトロGTFS ZIPに `date=current/next/latest` が適用されるか、`next`不在時の応答、切替時刻・timezone。
- API補足仕様の当該東京メトロデータへの適用範囲。ファイル取得の説明から通常ODPT JSON APIへの適用を推定しない。
- 会員ポータルのメタデータAPIが本プロジェクトの対象データ・契約で利用できるか。利用可能性は未確認。
- 公開payloadが元時刻表の大部分を復元できないこと、取得鮮度・差分・版整合を検証する公開ゲート。
- ODPT JSON/GTFSの更新確認・取得履歴・差分判定を用いた運用設計。初期案と段階計画は本書「ODPT-2F 更新・鮮度管理設計」を参照。

### 調査根拠（確認日・範囲）

| 根拠 | 確認日 | 適用範囲・限界 |
|---|---|---|
| [ODPT Developer Guideline](https://developer.odpt.org/terms/data_basic_use_guideline.html) | 2026-11-03 | 静的データの取得日時表示、定期更新、原則として更新通知後1週間以内。通知チャンネルの詳細は下記FAQ/補足仕様と照合 |
| [ODPT FAQ](https://developer.odpt.org/faq) | 2026-11-03 | URLを確認。閲覧環境で本文を取得できず、個別回答の根拠には未使用 |
| [API補足仕様](https://developer.odpt.org/api_addendum) | 2026-11-03 | `date=current/next/latest`の提示記載とファイル取得例を確認。東京メトロGTFSへの対応、JSON API、next不在・境界時刻は未確認 |
| [ODPT開発者フォーラム](https://developer-forum.odpt.org/) | 2026-11-03 | 閲覧を試みたが該当回答を確認できず。投稿・問い合わせは行っていない |
| [開発者サイト News](https://developer.odpt.org/news) | 2026-11-03 | 事務局回答で更新通知の確認先として案内。通知の即時性や個別購読機能は未確認 |
| ODPT事務局正式回答（ユーザー共有記録） | 2026-10-26 | 説明した加工時刻表・保存/cache・広告/任意支援付き無料公開に適用。回答原文・個別条件の再取得なし |

ODPT-2A〜2Fの結果は本書後半の各調査節およびdevlogを参照。過去の章にある「未取得」「未確認」は当時の状態を示す履歴であり、上記の現在の確定事項を取り消すものではない。

## ODPT-2E 会員ポータルメタデータAPI限定実検証（2026-11-03、ユーザー共有記録）

- Chromeで認証なしにmetadata APIを確認した結果として、ユーザーから共有された記録では `organization=tokyometro` は空配列、`format=gtfs` には結果があるものの「東京メトロ」「Tokyo Metro」は見つからなかった。
- この記録はユーザー実施結果の共有であり、Codexは実APIへ接続して再現していない。空結果や名称検索不一致だけから、東京メトロが公式に対象外とは断定しない。
- よって現時点でこのAPIを東京メトロの更新管理に採用しない。従来型ODPT JSON API・GTFS file APIとは別の会員ポータルmetadata APIとして扱う。
- `start_at`は適用開始日候補、`end_at`は公開終了日、`uploaded_at`は提供側アップロード日時。アプリ側の取得成功日時・ダイヤの適用終了日と混同しない。詳細な更新方式案はODPT-2F節。

調査日: 2026-10-22（JST）  
状態: 取得済みODPT JSON・GTFSをローカル解析済み。最新の検証結果は本書末尾の「Phase 3 実データ検証」を参照。

注: 以下のPhase 1・Phase 2当時の確認表と結論は、その時点の履歴として残している。後日ローカル実データで検証した内容はPhase 2実データ調査および末尾のPhase 3節を優先する。

## Phase 2準備状況（2026-10-22）

- `scripts/odpt_phase2_fetch.py` を追加。ユーザーのMacターミナルで実行する認証付き取得ツール。Railway / Station と、有楽町線・副都心線で絞った TrainTimetable / StationTimetable を合計6リクエストで取得し、`local_data/odpt/` に保存する。`.env.local` を読み、certifiでTLS検証。自動リトライなし。キー、URL、応答本文、例外全文は表示しない。
- `scripts/odpt_phase2_analyze.py` を追加。保存済みJSONの実キー・件数・対象駅レコードを調べ、配置済みGTFS ZIPがあれば実ファイル一覧・列・日付情報・対象駅を調べる。GTFSに必要列・対象駅IDが揃った場合のみ池袋→氷川台の直通と小竹向原経由の**時刻上の候補**を表示する。運行日適用と乗換可能性は断定しない。
- `.gitignore` に `local_data/odpt/` を追加。ODPT生データを誤ってコミットしない。
- GTFSは今回、CKAN実配布URLと認証条件を独立に確認していない。URLを推測した自動取得機能は設けていない。実際に取得できたZIPを `local_data/odpt/` に置けば解析対象となる。
- 現時点でAPI取得・GTFS取得・旅程解析は**未実施**。ODPT JSONの実フィールドに基づく旅程生成は未対応。実レコードを確認し、列・停車表現が特定できた後に実装する。

### Macターミナル実行手順

```sh
cd /Users/takamiyakoji/Documents/dotchi-ikebukuro
.venv/bin/python scripts/odpt_phase2_fetch.py
find local_data/odpt -maxdepth 1 -type f -print
.venv/bin/python scripts/odpt_phase2_analyze.py
```

解析結果はターミナル表示。JSON/ZIP本体はGit管理対象外の `local_data/odpt/` に保存する。取得が成功した表示だけでは解析済みを意味しない。

## 要約

東京メトロの列車時刻表・駅時刻表・駅情報・路線系統情報（JSON）、鉄道関連情報（GTFS/GTFS-JP）、鉄道関連リアルタイム情報（GTFS-RT/Protocol Buffers）、運行情報（JSON）がカタログに掲載されている。今回の実行環境では `ODPT_API_KEY`、`ODPT_CONSUMER_KEY`、`ODPT_CONSUMERKEY` が未設定だったため、認証付きJSONやGTFSファイルは取得していない。実レコード、実便、時刻、ID、ホーム、最低乗換時間について推測で補完しない。

仮推奨は、キーをサーバー側に保管し、GTFSをサーバー側で定期取得・内部正規化して静的時刻表検索の主データにする構成。JSON時刻表は便ID対応を確認後、照合・補完に使う。これは実ファイル検査前の設計案であり、フィード内容を確認してから確定する。

## 調査したURL・確認日時

すべて2026-10-22 JSTに確認。CKANカタログと公式文書を閲覧。認証API呼び出しは未実施。

| 対象 | URL | 確認結果 |
|---|---|---|
| 東京メトロ全データ | <https://ckan.odpt.org/dataset/?organization=tokyometro> | 10件。下記データセットと各形式の掲載を確認 |
| 列車時刻表 | <https://ckan.odpt.org/dataset/r_train_timetable-tokyometro> | JSONリソース、基本ライセンス表示 |
| 駅時刻表 | <https://ckan.odpt.org/dataset/r_station_timetable-tokyometro> | JSONリソース、基本ライセンス表示 |
| 鉄道関連情報 | <https://ckan.odpt.org/dataset/train-tokyometro> | GTFS/GTFS-JP、基本ライセンス表示 |
| 駅情報 | <https://ckan.odpt.org/dataset/r_station-tokyometro> | 一覧でJSON掲載確認。個別ページ本文は未確認 |
| 路線系統情報 | <https://ckan.odpt.org/dataset/r_route-tokyometro> | JSON、基本ライセンス表示 |
| 運行情報 | <https://ckan.odpt.org/dataset/r_train_status-tokyometro> | 一覧でJSON掲載確認。中身未取得 |
| 鉄道関連リアルタイム情報 | <https://ckan.odpt.org/dataset/r_train_gtfs_rt-odpt_train-tokyometro> | GTFS-RT Alert / Protocol Buffersのリソース、基本ライセンス表示を確認。中身未取得 |
| 開発者サイト | <https://developer.odpt.org/> | 登録後に発行されるAPIキーでアクセスする説明 |
| センター利用規則 | <https://developer.odpt.org/terms/center_use_rules.html> | API頻度・日時制限、キー管理等 |
| 基本ライセンス | <https://developer.odpt.org/terms/data_basic_license.html> | 商用利用、正確性、再配布制限等 |
| 開発者ガイドライン | <https://developer.odpt.org/terms/data_basic_use_guideline.html> | 動的データ等の実装指針 |

注: 駅情報・運行情報・GTFS-RTの個別ページも確認した。各リソースの内容・レコードは未取得。

## データセット比較

| データ | カタログ形式・粒度 | 用途候補 | 今回確認したこと／未確認点 |
|---|---|---|---|
| 列車時刻表 | JSON、列車単位 | 便の停車駅時刻から到着を計算 | JSON掲載を確認。実レコード・フィールド・運行日・便ID未確認 |
| 駅時刻表 | JSON、駅単位 | 池袋発候補抽出 | JSON掲載を確認。列車時刻表との対応、種別・行先未確認 |
| 鉄道関連情報 | GTFS/GTFS-JP | 駅・路線・便・停車時刻・運行日を表結合 | フィード掲載を確認。ZIP内ファイル、列、期間、直通表現未確認 |
| 駅情報 | JSON | 駅ID・名称・路線等の参照 | JSON掲載確認。ID、路線・ホーム情報未確認 |
| 路線系統情報 | JSON | 路線ID・名称の参照 | JSON掲載確認。実ID・接続等未確認 |
| 運行情報 | JSON | 遅延・運休等の注意表示 | JSON掲載確認。更新間隔、粒度、鮮度未確認 |
| 鉄道関連リアルタイム情報 | GTFS-RT / Protocol Buffers | 静的便の状態補足 | 掲載確認。実エンティティ、配信頻度、静的便ID照合未確認 |

## 実際に確認したレコード構造・主要フィールド

実レコードは**取得できていない**。APIキー未設定を環境変数名だけで確認し、値は表示していない。確認できたのはデータセット単位の形式までである。JSON時刻表の列名・JSON-LDプロパティ・ID・時刻表現、およびGTFS ZIP内のファイル・列・レコードは未確認。一般的なODPT/GTFS仕様から本データのフィールドを推定して記載しない。

## ODPT JSONとGTFSの比較

| 観点 | ODPT JSON | GTFS静的データ | 現時点の結論 |
|---|---|---|---|
| 列車ID・駅ID | ODPT IDの実際のキーとJSON間対応未確認 | 表間の便・停留所キーの本フィード実値未確認 | 実データ結合が必要 |
| 池袋発時刻 | 駅時刻表で取得可能か、便情報との照合未確認 | 池袋に該当する駅と便の時刻を抽出できるか未確認 | 発車便・時刻の実確認なし |
| 小竹向原・氷川台発着 | 列車時刻表に停車時刻があるか未確認 | 停車時刻表の収録・粒度未確認 | 到着・発車時刻未確認 |
| 種別・行き先 | JSONリソース内の有無未確認 | 路線・便等に相当値があるか未確認 | 表示可能性未確定 |
| 平日／土休日 | 運行日・適用カレンダー未確認 | 本フィードのカレンダー表収録・意味未確認 | 祝日・臨時日も要検証 |
| 深夜の日付跨ぎ | 24時超時刻か日付保持か未確認 | サービス日基準表現の実利用未確認 | 実値を見て処理決定 |
| 他社直通 | 東京メトロ外の停車が同列車に含まれるか未確認 | 他社区間・別事業者フィードの表現未確認 | メトロ単独で完結とは言えない |
| 更新方法 | REST API、キー認証 | カタログファイル取得。認証条件の実確認未了 | サーバー側定期取得と版・有効期間記録が候補 |

## 池袋→氷川台の旅程生成可否

実便の停車・時刻は一件も検証できていない。カタログ粒度からの必要条件は次の通り。

1. **有楽町線で直通:** 池袋発と氷川台停車を同一便IDで結び、両駅の時刻が必要。便の存在も時刻も未確認。
2. **副都心線で直通:** 池袋→小竹向原→氷川台の停車順を同一便として確認する必要がある。実便未確認。
3. **小竹向原で別列車へ乗換:** 先行便の到着、後続便の発車、運行日・行先の照合が必要。ホーム／経路と最低乗換時間の根拠が必要だが、提供有無は未確認。現状では接続可否を断定できない。
4. **将来の対象10駅:** 要町、千川、小竹向原、氷川台、平和台、地下鉄赤塚、地下鉄成増、和光市、新桜台、練馬を駅IDで照合し、停車列から候補を作る設計は可能性がある。ただし駅ID、停車、他社区間の収録は未確認。メトロ単独フィードで全区間が得られるとは仮定しない。

**ホーム情報・最低乗換時間:** カタログ説明では提供の記載を確認できず、実レコードも未取得。「含まれない」とは断定できない。データになければ現地・事業者根拠を別途得るまで「乗換候補・接続条件未確認」とし、接続可能と断定しない。

## 採用比較・推奨

仮案として、サーバー側バッチでGTFSを取得し、駅・便・停車時刻・運行日を内部共通形式へ正規化する。池袋発候補抽出と目的地到着計算を停車列から行う。ODPT JSONはGTFSとのID対応が実証できた範囲で照合・補完に使う。GTFSは一括データを正規化して更新・整合性を管理しやすいと見込むが、今回のフィードに必要な停車時刻や直通先があるか未検証。ODPT JSONは対象APIを絞れる可能性がある一方、複数リソースのID対応と更新整合性が課題。実データ確認後に方式を決める。

## 運用・ライセンス

- **認証:** 登録後に発行されるAPIキーを用いる。基本ライセンス規則はキーを第三者に開示しないよう求める。未設定環境では取得をスキップした。今後は発行済みキーをローカル秘密管理／サーバー環境変数 `ODPT_API_KEY` に設定し、サーバー側から `acl:consumerKey` として扱う。値をチャット・ソース・HTML/JS・ブラウザーに置かない。
- **利用制限:** センターがアクセス頻度・日時を制限できる規則を確認。具体的上限は未確認。
- **更新頻度:** 各JSON・GTFS・GTFS-RTの頻度は未確認。
- **保存・再配信:** 基本ライセンス上の範囲と制約は維持する。2026-10-26の事務局回答では、相談した想定利用方法でのserver-side保存/cacheと時刻表dataの加工・配信は問題ないとのこと。任意のdata/profileや元dataを復元できる形式まで許可されたとは解釈しない。詳細は文書末尾のT11記録。
- **広告付き無料利用:** 2026-10-26の事務局回答では、東京メトロの公共交通オープンデータ基本ライセンスとガイドラインに従う場合の広告・任意支援付き無料公開は問題ないとのこと。広告サービス側の審査やホスティング事業者規約は別途確認する。
- **クレジット:** 定型文・掲示場所は未確認。公開前に確認し、独自文言を確定扱いしない。
- **正式公開:** 取得失敗・期限切れ表示、有効期間・最終取得日時、データ更新時の反映、正確な表示と免責を設計する。提供データはAS IS。事務局回答で相談済み構成のserver-side保存/cacheは問題ないとの回答を得た。元データや大部分を復元できる配信の可否は未確定。

## 不明点・リスク

1. キー未設定により実レコード・実ダイヤを確認できていない。
2. JSON/GTFS間の便・駅ID、他社直通、運行カレンダー、祝日・臨時便、日付跨ぎ表現が不明。
3. 小竹向原のホーム・経路・最低乗換時間が不明。
4. 更新頻度、数値API上限、定型クレジットが未確認。保存/cacheは回答の想定利用方法では問題なしとの回答を受領したが、他用途への拡張可否は未確認。
5. GTFS-RTの静的便結合・遅延情報・更新間隔が不明。
6. 基本ライセンスの再配布制限があるため、公開物に生データまたは大部分が復元可能な派生データを含める運用は避ける。回答は相談した想定利用方法に限って適用し、公開payloadを別途reviewする。

## T11 ODPT事務局回答（2026-10-26）

2026-10-26にユーザーから共有されたODPT事務局の正式回答を、次のとおり記録する。これはユーザー提供の回答内容であり、回答原文や個別データセット条件を本調査で改めてAPI・アカウントから取得したものではない。

- 時刻表データの加工・配信: 問題なし。
- サーバー側でのデータ保存・キャッシュ: 想定利用方法なら問題なし。
- 広告・任意支援を伴う無料公開: 東京メトロの公共交通オープンデータ基本ライセンスとガイドラインに従えば問題なし。
- データ更新通知: 開発者サイト内の「ニュース」で各データの更新状況を適宜掲載する。

回答は今回相談した時刻表データと想定利用方法に関するものとして扱う。すべてのODPTデータ、無制限・長期の保存、元データや大部分を再構成できる形式の再配布、API keyの公開などへの包括的許可とは解釈しない。基本ライセンスとガイドライン、個別データ条件が引き続き適用される。基本ライセンスは条件を守った営利・非営利の公開deliverableを認める一方、元データや全体・大部分を復元できる再利用可能な形式の再配布等を制限する。開発者ガイドラインのstatic data取得日時表示、更新通知後1週間以内の更新、データ提供元・正確性免責・問い合わせ先表示も公開設計に反映する。

T11は完了。正式host設定、i-mobile申請、実ダイヤ一般公開は本回答だけでは実施していない。T12のhosting比較・推奨と公開前手順は [`hosting_research.md`](hosting_research.md) に分離した。

## ODPT-2F 更新・鮮度管理設計（2026-11-03、提案・未実装）

本節は運用設計の提案であり、取得・自動公開・鮮度閾値の承認ではない。実データ公開は引き続き未承認。既存のsynthetic公開経路は変更せず、release-managed契約を実データへ流用する場合は別途審査する。

### Phase 0確定契約（ODPT-2G、2026-11-03）

Phase 1A validatorで使う契約を次の通り確定した。Phase 0のレビュー対象はSource/Snapshot記録の構造と整合性であり、取得処理や公開資格を定義・承認するものではない。

固定sourceIdは `metro.railway`、`metro.station`、`metro.train-timetable.yurakucho`、`metro.train-timetable.fukutoshin`、`metro.station-timetable.yurakucho`、`metro.station-timetable.fukutoshin`、`metro.gtfs`。source記録とsnapshot記録を分離し、snapshotは7 sourceIdを各1回参照する。取得バッチsnapshotは参照source記録がすべてfetch mode・同一batchの成功記録であることを要求する。legacy snapshotは7件すべてlegacy-observationであることを要求する。

すべての日時はUTC RFC 3339（`Z`または`+00:00`）で記録し、JSTは表示時の変換とする。過去snapshotで取得成功日時が記録されていなければ `retrievedAt=null` のままにし、filesystem mtimeや観測時刻から補完しない。Source記録にはschema version、record/source/origin識別子、source種別、mode、batch/attempt/retry参照、観測・開始・終了・取得日時、outcome、許可項目に限定したHTTP結果、固定error code、artifactの保存path/hash/byte数、GTFSまたはODPTのsource metadata、unknownReasonsを含める。キー、認証付きURL、header、応答本文は含めない。

- `legacy-observation`: `observedAt`、artifact、`historical_acquisition_not_recorded` が必須。batch/attempt、取得開始・終了・成功日時、HTTP、errorはnull。outcomeは `observed`。Phase 1Aの初版実装では別の値 `legacy-observed` を受理していたが、Phase 1Bで確定契約に合わせてvalidatorと合成fixtureを修正した。
- `fetch/succeeded`: batchIdとattemptId、開始・終了・取得成功時刻、HTTP応答、artifactが必須。最終応答は2xx、errorはnull。
- `fetch/failed`: 取得成功日時とartifactはnull、終了時刻・error codeが必須。
- `fetch/interrupted`: 取得成功日時とartifactはnull、開始時刻とerror codeが必須。終了時刻はnull。

リトライは新attemptIdを使い、同じsource/batchの直前失敗または中断attemptを参照する。試行記録は消去・上書きしない。同じbytesの再取得も新recordIdを持ち、snapshot contentFingerprintはsourceId順のsourceId・SHA-256・byte数から計算し、試行日時を含めない。hash/bytes一致は保存representationの一致を示すだけで、時刻表の意味的同一性を証明しない。

JSON objectは未知key・重複key・不正型・非標準数値定数を拒否する。配列の順序を無視する意味比較は、対象フィールドを別途明示定義した比較profileだけで許可する。未定義の配列は順序差を保持する。改正境界で単一snapshotがservice dateの根拠を説明できない場合は初期公開候補を保留する。

applicationPeriodは期間根拠と公開承認が揃わない限りnull。運用停止期限は将来の独立項目とし、applicationPeriodの代替や公開資格として使わない。`end_at`は公開終了日であり、適用終了日へ読み替えない。期限切れ時はfail closed。rollbackでも期限・承認・source/hash・service date適合を再検証する。Phase 1では履歴の自動削除を実装せず、無期限保存も確定しない。

契約例・実装validatorの固定error codeとPhase 1A完了条件は [`scripts/odpt_source_contract.py`](../scripts/odpt_source_contract.py) と `tests/test_odpt_source_contract.py` にある。後者はvalidatorの合成テストであり、実sourceをfixture化しない。

### Phase 1B 保存済みsource inventory（2026-11-03）

[`scripts/odpt_source_inventory.py`](../scripts/odpt_source_inventory.py) は、既存QAで使う固定7ファイルを読み取り、Source recordをメモリ上で生成してPhase 1A validatorに渡すローカルCLIである。既定入力先は既存 `odpt_snapshot_qa.py` の `DEFAULT_SNAPSHOT` から参照するため、絶対パスを固定していない。出力はPASS、件数、sourceId、保存bytesのbyte数・SHA-256に限定し、recordやsource本文の永続化・表示はしない。

全recordは `mode=legacy-observation`、`outcome=observed`、UTCの今回の `observedAt` を持ち、取得成功日時・開始/終了日時・HTTP・batch/attempt参照はnullのまま。mtimeから取得日時は補わず、`unknownReasons` に `historical_acquisition_not_recorded` を記録する。artifactは `raw/<固定ファイル名>`、`representation=stored-file` とし、保存されていた元bytesそのものをhashする。今回のローカル観測日時は過去の取得日時を示さない。

ODPT JSONはrecord件数、`dc:date` / `dct:issued` の文字列値集合、各キーの欠損件数を取得する。未出現またはnullは欠損、文字列以外は解析失敗とする。GTFS ZIPからfeed versionとfeed期間を読む。ZIPは展開せず必須7メンバーを要求し、追加entryは安全なフラットな`.txt`名に限定する。重複名・階層/危険entry・暗号化・link/directory・上限超過・CRCを含む不正ZIPを拒否する。ファイルは通常ファイルか確認して前後のfilesystem identityとサイズを照合し、record作成後に全sourceを再読してinventory中のhash/byte数不変も確認する。読取上限はsource 128 MiB、ZIPメンバー64 MiB、展開合計256 MiB、圧縮率1000倍で、これは実装上の安全制限であり提供元仕様ではない。

合成fixtureのinventory・失敗系テストは [`tests/test_odpt_source_inventory.py`](../tests/test_odpt_source_inventory.py) にある。保存済み実sourceはfixtureに含めない。Phase 1B単体の範囲は読み取りとメモリ内record生成であり、次節のPhase 1Cがそのrecordを永続化する。差分エンジン・公開資格gateは未実装。

保存済みsourceのローカルQAでは7件すべてを検出し、Source validator通過。GTFSはfeed_version `20261008`、feed期間 `2026-09-19`〜`2027-03-12`。ODPT件数はRailway 10、Station 186、TrainTimetable有楽町843・副都心993、StationTimetable有楽町92・副都心60。時刻表4 sourceの `dc:date` は `2026-03-16T09:00:00+09:00`、`dct:issued` は `2026-03-14`。Railway/Stationの `dct:issued` は全件欠損（10/10、186/186）で、`dc:date` は欠損なし。全sourceについてCLI実行前後のSHA-256とbyte数が一致した。これらは保存ファイルの現状観測値であり、取得日時・最新版・適用期間・実データ公開可否を確定しない。

### Phase 1C Source/Snapshot記録の非公開保存（2026-11-03）

[`scripts/odpt_source_store.py`](../scripts/odpt_source_store.py) はPhase 1B recordからSnapshot recordを作り、明示指定された新規・絶対pathへmetadataだけを保存する。保存先はrepository、symlink経路、既知の公開風path、preview/QA出力先、既存destinationを拒否する。新規storeと `sources/` は0700、JSON recordは0600。store layoutは `sources/<sourceId>.json` 7件と `snapshot.json` 1件で、raw sourceは複製しない。

SnapshotはPhase 1Aの同じcanonicalization（sourceId・SHA-256・byte数をsourceId順にJSON canonical encodeしてSHA-256）を使う。追加状態は `completeness=complete`、`acquisitionStatus=historical-unknown`、`crossSourceConsistency=not-evaluated`。completeは固定7 sourceのrecord参照が揃った意味に限り、取得成功・同一ダイヤ・現行有効性・公開可能性を意味しない。Snapshot保存は公開承認ではない。

各JSONは一時fileに排他的作成し、0600でwrite・file fsync後にatomic renameし、directory fsyncする。全Source記録が確定した最後に `snapshot.json` をrenameし、これを完成storeのcommit markerとする。通常の失敗では今回新規作成したstoreだけを後片付けする。異常終了で残ったstoreにsnapshot markerがなければverifyは `store_incomplete_snapshot` で拒否し、既存pathへの再試行・上書きはしない。既存pathとの衝突時は別の新規pathを指定する。完全なrecord storeを再確認してからcleanupする。

CLIは既存 [`scripts/odpt_source_inventory.py`](../scripts/odpt_source_inventory.py) に `inspect`（既定・read-only）、`persist --store <absolute-new-path>`、`verify --store <path>` を追加した。verifyはrecord/Snapshot validator結果とsource bytes参照照合を別々に出す。参照dirがない場合は `unavailable`、source file欠落は `missing`、byte不一致・不正・変更中は `mismatch`。record検証の履歴はこれらと区別して保持される。

合成テストは [`tests/test_odpt_source_store.py`](../tests/test_odpt_source_store.py)。保存・再読込、別snapshot IDで同一fingerprint、元bytes照合、参照欠落/変更、record参照/fingerprint破損、JSON重複key/未知key、途中失敗・write失敗時のatomic性、既存path・symlink・traversal・不正権限を検証する（13件）。保存済みsourceでの実QAではユーザーLibrary配下の明示path `~/Library/Application Support/dotchi-ikebukuro-source-snapshot-20261103-phase1c` にrecord 8件だけを保存し、別CLIプロセスの再verifyでSnapshot validator PASS、source bytes 7/7 match。前後hash/byte数も7/7一致した。

### Phase 1D ODPT-0 Snapshot QA互換確認（2026-11-03）

[`scripts/odpt_source_compat.py`](../scripts/odpt_source_compat.py) とinventory CLIの `compare-legacy --store <absolute-path> [--source-dir ...]` を追加した。store/Source/SnapshotはPhase 1C/1A validatorで読み取り検証し、ODPT-0の既存 `odpt_snapshot_qa._inventory()` と `_fingerprint()` をそのまま呼んで独立再計算する。既存QAファイルやsource inventoryへの変換書込・上書きはしない。

照合は固定7 sourceIdと既存7 filenameの完全一致を要求し、各Source artifactのfilename対応・SHA-256・byte数をODPT-0 entriesと照合する。Sourceのpath mapping、重複/欠落/余剰、hash/byte数差は固定error codeで停止する。新Snapshot fingerprintはPhase 1A `content_fingerprint`、ODPT-0 fingerprintは既存のfilename順entry list canonical JSONという各既存定義で独立検証する。fingerprint文字列同士の一致は要求せず、対応ID/fileとhash/byte数で互換性を確認する。

metadata比較ではODPT recordCountと`dc:date`/`dct:issued`値集合、GTFS feedVersion/期間の共有値を比較する。ODPT-0はnon-null日付値をstring化し、新Source metadataはstring以外を解析拒否する。またODPT-0には日付欠損件数がなく、新metadataにはある。GTFSでは`requiredMemberCount`がODPT-0のみの派生field。これらは抽出項目/規則差として報告し、共有値不一致とは分ける。実source比較では共有値の不一致0件、schema/extraction差7件（GTFS legacy-only field 1、ODPT new-only missing count 6）。metadata statusは`compatible-with-extraction-differences`。

実source QAはPhase 1C store `~/Library/Application Support/dotchi-ikebukuro-source-snapshot-20261103-phase1c`を指定し、同じ保存済み7 sourceに対して実行。新Snapshot fingerprint `9392342c929297f98c1e8124a563e13dc35764c0f19df17454e11870d3196c6d`とODPT-0 fingerprint `6e578d7b55f669e58dd3597dc151d9d0db7a6cbf7651d96f84036538c4ea430e`は独立検証PASS、値は異なる（方式差）。ODPT-0値は過去devlog記録値と一致するが、既定・記録上のQA JSON reportが存在しないためreport fileとの直接比較はしていない。inventory一致PASS、現物bytes 7/7 match。取得状態は`historical-unknown`、source間整合は`not-evaluated`、公開statusはこの比較では未評価・承認付与なし。実行前後でsource 7件とstore JSON 8件のhash/byte数が一致。

合成fixtureは [`tests/test_odpt_source_compat.py`](../tests/test_odpt_source_compat.py)。一致/metadata射影差、inventory欠落/余剰/重複/誤mapping、hash/byte数不一致、Snapshot fingerprint不正、metadata型不正、source変更/欠落、symlink/traversal/不完全store、ODPT-0 fingerprint出力不正を検証する（8件）。互換確認はread-onlyで、ダイヤ最新版・同一ダイヤ・公開可能性の判定を行わない。

### Phase 2A Snapshot基本差分（2026-11-04）

[`scripts/odpt_source_diff.py`](../scripts/odpt_source_diff.py) とinventory CLIの `compare --baseline-store <absolute-path> --candidate-store <absolute-path>` を追加した。既存のPhase 1C `load_store_contract()`を両storeに適用し、Source/Snapshot validator、固定7件、record参照、schema version、canonical contentFingerprintを検証してから比較する。不正・欠落・symlink storeはsideを含む固定error codeで失敗し、差分なしとは扱わない。保存recordの検証と元source bytesの現物照合は分離し、比較に元source directoryを要求せず、現物bytesを読み取らない。

各sourceの結果にbaseline/candidate SHA-256・byte数、hash一致、byte数一致、`identical` / `different` / `unavailable`を記録する。hash一致かつbyte数一致で保存representationを同一とし、同じ長さでhashだけ異なる場合も`different`。異なるsnapshotIdや取得履歴はbytes判定へ影響しない。metadataはSource recordからGTFSのfeedVersion/validFrom/validThrough、ODPTのrecordCount/dcDates/issuedDates/欠損件数をfield単位で比較し、`same` / `different` / `both-unknown` / `one-unknown`を記録する。Phase 0契約どおり配列順序を保持する。構造不正はstore契約検証で拒否する。保存metadata不明が残れば総合状態は`unavailable`、既知のbytesまたはmetadata差があれば`changed`、全比較項目が既知で一致すれば`identical`。

結果はメモリ上だけで生成する。CLIは7 sourceの状態とmetadata変更field名のみを表示し、raw本文・metadata値を出さない。終了コード0は比較完了（identical/changed）、2は比較不能または引数不正。`FAIL error=<code>`と`PASS overall_basic_status=unavailable`を区別する。結果はPhase 2A専用でPhase 0分類、expected-change、公開承認に接続しない。

合成fixture testは [`tests/test_odpt_source_diff.py`](../tests/test_odpt_source_diff.py) に追加した。7件同一、snapshotId差、同byte数hash差、hash/byte数差、metadata-only差、GTFS3 field、ODPT日付/件数/欠損数、配列順序、unknown metadata、元source参照不能、欠落/破損・selectedRecords・fingerprint・record参照・metadata schema・未知schema・path/symlinkを検証する（13件）。Phase 1C実storeを同一path同士でread-only比較し、7 sourceとmetadataが一致して`identical`。この比較は元source bytes照合を行っていない。

本文のJSON/GTFS意味比較、旅程品質差分、総合公開資格判定、結果永続保存は未実装。hash一致は保存bytesの同一性を強く確認するが、取得日時・ダイヤ有効性・source間の同一版性を証明しない。

### Phase 2B-1採用契約・Phase 2B-2a TrainTimetable意味比較（2026-11-04）

比較profileは `dotchi.odpt-gtfs.semantic` / `1.0.0`。本節をPhase 2B-1レビューで採用した契約とし、初回実装は [`scripts/odpt_train_semantic_diff.py`](../scripts/odpt_train_semantic_diff.py) のTrainTimetable有楽町・副都心2 sourceだけに限定する。残るRailway、Station、StationTimetable 2件、GTFSは意味比較しない。世代別raw保管方式、GTFS table別キー・カレンダー比較、StationTimetableの動的boolean key等は後続工程で設計・確定し、今回実装しない。

### Phase 2B-2b Railway・Station・StationTimetable意味比較（2026-11-04）

Phase 2B-2aのprofile ID/version（`dotchi.odpt-gtfs.semantic` / `1.0.0`）を維持し、ODPT JSON 6 sourceを意味比較対象に拡張した。Railwayは`owl:sameAs`を主キー、`@id`を必須一意IDとして検証し、`stationOrder`の配列順・index・station ID・駅名を保持する。Stationは駅名、code、座標、路線・駅時刻表等の参照を比較し、connectingRailway / connectingStationの順序を保持する。StationTimetableは親recordと各eventの配列順を保持し、station・railway・railDirection・calendarを補助キーとして一意性検証に使う。親主キーの置換やtrain番号だけでの別世代列車同一視はしない。変更はfield path付きで分類し、差分詳細はsourceごと1,000件上限、打切りはindeterminateとなる。

StationTimetableイベント内で親record `owl:sameAs` のsuffixと一致する動的boolean keyは意味未解明のopaque extensionとしてraw key/valueを比較する。変更・追加・削除・型差を検出するが意味解釈済みとは扱わず、存在するsourceは常にcoverage partial / semanticStatus indeterminateとする。その他未知フィールドも記録し、未対応を無視しない。内部のRailway→Station、Station→Railway、StationTimetable→Station/Railway/Train参照を検証する。既知のTokyoMetro IDで未解決は内部参照失敗、外部事業者等の参照はexternalとして許容し、推測補完しない。これらは参照存在確認であって同一ダイヤ整合性の証明ではない。

`compare-semantic`はbaseline/candidate storeと原本directoryを明示し、両側固定7原本のhash・byte数をSource recordに照合する。実storeの同一Snapshot自己比較ではODPT 6件の処理が成立し、Railway、Station、TrainTimetable 2件の既知差分は0。StationTimetable 2件はopaque keyを理由にpartial、GTFSはnot-evaluated、全体indeterminate。参照確認は各側resolved 29,069、external 468、internal unresolved 0。15原本/storeファイルのSHA-256とbyte数は比較前後一致。これは自己比較であり世代間変更検出のQAではない。GTFS意味比較、source間の運行整合性証明、鮮度、公開資格、旅程品質差分は未実装・未評価。

**採用した基本規則**

- JSON objectのkey順・空白・escape表現を解析後の値で比較する。重複key、NaN/Infinity等の非標準定数、構造・型不正を拒否する。数値の解析はDecimalで精度を保持し、unknown値も型を保持して比較する。
- ODPT record主キーは `owl:sameAs`。`@id`も必須・一意とし変更を検出する。トップレベル配列は主キー存在・一意性の検査後だけ並び順を無視する。停車・発着イベント、起終点駅配列は順序を保持する。未定義配列のsort・重複除去はしない。
- missing、null、空文字、false、0を区別する。必須識別子・参照は空でない文字列、起終点駅は空でない文字列配列。metadataは文字列・null・missingを受理して区別する。イベント時刻はmissing/null/空文字を保存された欠損状態として保持し、false/0等の不正型を拒否する。欠損が同じことは時刻の妥当性を保証しない。
- 既知時刻はASCII `HH:MM` / `HH:MM:SS`（hourは2〜3桁、分秒0〜59）を秒へ変換し、秒省略は00秒とする。24時超を保持し、24時間剰余、丸め、日付補完をしない。文字列のtrim・大小文字・全半角・駅名統合も行わない。
- 識別子の世代間安定性を仮定しない。主キー変更は削除・追加を維持する。識別子4項目（owl:sameAs、@id、train、trainNumber）以外の全値が厳密一致し、unknownがなく、旧新の対応が双方向に一意な場合だけ `possible-identifier-change` を付記する。複数候補は `multiple-identifier-candidates`。いずれも同一列車と自動確定しない。
- 同じ主キーのtrain/trainNumber/railway/railDirection/calendar変更、または同じ@idが異なる主キー・異なる内容へ対応する場合は `suspected-identifier-reuse` 警告を残す。
- 未知fieldはrecord/eventのfield pathとsideを保持し、その値も比較する。unknownが不変でもcoverageはpartial。既知以外の@contextは警告・partial、未対応@typeやsourceとrailwayの不整合は入力不正とする。URIを外部へ解決しない。

**TrainTimetableの既知field**

| 分類 | field（`odpt:` prefixは対象語に適用） |
| --- | --- |
| 識別・schema | owl:sameAs、@id、@context、@type、train、trainNumber |
| 参照 | railway、railDirection、calendar、operator |
| 種別・起終点 | trainType、originStation、destinationStation |
| metadata | dc:date、dct:issued |
| ordered events | trainTimetableObject内のdepartureStation、arrivalStation、departureTime、arrivalTime |

イベントは駅参照を最低1つ必要とし、時刻があれば対応する発着駅参照を要求する。外部駅IDは文字列として保持し、Railway/Station等への意味的参照整合や同一ダイヤ版性の検証は未実施。既存matcherの番号表記候補化、駅名変換、時刻剰余化、停車列の重複除去は本profileへ流用しない。

**読み取り専用入力・結果**

baseline/candidateそれぞれのstoreと絶対pathの原本directoryを明示指定する。Phase 1C readerとPhase 2A比較を再利用し、両storeの契約・7件・record参照・fingerprintを検証する。両側7原本のSHA-256/byte数を対応recordへ照合し、対象2件だけstrict parse・意味比較する。他5件はbytes照合のみ。通常ファイル、symlink/traversal拒否、読取前後のdevice/inode/size/mtime/ctime、比較終了時の全原本再読とstore再検証を行う。元sourceがない場合や不一致・変更中に、その入力を意味比較の根拠にしない。実原本を過去Snapshotの代用品にせず、複製・移動・取得・persistしない。

結果contractは `odpt-semantic-diff` / schemaVersion 1。profile、両Snapshot ID/fingerprint、Phase 2AのbasicDiff、comparisonStatus、semanticStatus、固定7件のsourceResults、notEvaluated、inputErrorsをメモリ上だけに生成する。sourceResultsにはinputBytesStatus、coverage、comparisonStatus、semanticStatus、categories/categoryCounts、added/removed/modified/change件数、recordKeyとfieldPath付きchanges、unknownFields、ambiguities、warnings、errorCodes、truncatedを含む。本文や旧新record全体を結果へ複製しない。

比較対象2件のcoverageはcomplete/partial、状態はequivalent/changed/indeterminate。未知・曖昧・警告・打切りがあればpartial/indeterminate、入力不正ならfailed。未実装5件はcoverageとcomparisonStatusがnot-evaluated。したがって全体は常にsemanticStatus=indeterminate、comparisonStatusは通常partial、入力エラー時failed。確定したfield差分は残し、全体equivalentにはしない。

変更分類は `json-format-only`、`record-order-only`（JSON表現を除去した後のrecord順差）、metadata-changed、time-changed、stop-station-changed、stop-order-changed、event-structure-changed、train-type-changed、destination-changed、origin-changed、identifier-changed、reference-changed、schema-context-changed、record-added/removed、unknown-field-changed、ID変更候補/曖昧性。純粋なイベント並び替えはstop-orderとして記録し、移動した駅の時刻同士からdeltaを作らない。順序と内容の同時変更で位置対応が異なる時刻差はevent-position-changedとし、同じ発着駅contextで対応する既知時刻だけdeltaSecondsを付ける。

source入力上限128 MiB、record数20,000/source、event数500,000/source、JSON深さ32。changes/unknown/ambiguity/warningの保持は合計1,000件/sourceまで。field差分と変更recordの集計は走査完了時に全件分を保持し、詳細超過は `detail_limit_reached`、truncated=true、partialとして示す。入力構造上限は固定error codeでfailedとし、未走査を無差分としない。sourceId・record key・field key順で決定的に処理する。

CLI: `python3 -B scripts/odpt_source_inventory.py compare-semantic --baseline-store <absolute-store> --candidate-store <absolute-store> --baseline-source-dir <absolute-raw-dir> --candidate-source-dir <absolute-raw-dir>`。出力は固定sourceId、coverage、変更分類・件数、固定error/warning codeのみ。raw本文、recordKey、metadata値、field値を表示しない。終了コード0は対象2件を完全比較（変更自体は失敗でなく、5件の未実装による全体partialは許容）、2は入力不正・比較不能・未知・曖昧・上限到達。引数不正も2。expected-change、鮮度保証、公開資格、applicationPeriod/publicationApprovedに接続しない。

### 推奨する全体フロー

1. **更新確認:** ODPT開発者サイトNewsを更新通知の一次情報として確認する。News確認は更新の手掛かりであり、ファイル取得成功やsource内容の同一性を証明しない。通知後の静的データ更新条件は基本ライセンス/Developer Guidelineを確認する。
2. **取得:** News告知または運用上の定期確認で更新候補が見つかったら、GTFS ZIPとODPT JSON 6件を隔離したstaging領域へ取得する。7件全ての取得が成功してからsnapshotとして確定し、取得成功日時を個別に記録する。一部成功を現行snapshotに混ぜない。
3. **記録:** sourceごとにsource key、取得元dataset/endpoint、取得成功時刻（UTCと表示用JST）、HTTP結果、SHA-256、byte数、取得時に確認できたsource metadataを記録する。秘密キー、認証付きURL、レスポンス本文、生sourceはpublic artifact/Actions logに含めない。
4. **検証・差分:** 旧snapshotと新snapshotを比較し、構造・期間・日付・便・駅順・時刻・ODPT照合・v2候補品質を検証する。
5. **candidate:** 全gate成功時だけ非公開candidateを作り、candidate manifestにsource fingerprint、generator fingerprint、取得日時参照、差分要約、適用期間根拠を記録する。source本文やprivate metadata manifestを公開bundleに含めない。
6. **承認・公開:** 公開承認者が対象service date、期間根拠、差分、品質、ライセンス表示、release ID/hash/bytesを確認する。承認前は非公開。release-managed方式は世代整合とrollbackに再利用できるが、source適用期間・公開資格の検証を代替しない。

### 確認頻度の選択肢

| 方式 | 利点 | 制約 |
|---|---|---|
| ODPT Newsを手動で定期確認 | 固定費・実装が最小。現時点の一次通知先と合う | 見落とし・確認間隔に応じた遅延がある。未確認期間を鮮度保証にできない |
| News確認を担当者の運用タスク化し、更新時だけ取得 | 省運用を保ちつつ、変更のない回の取得を避けられる | 担当・頻度を決める必要がある。頻度の根拠は提供頻度や更新条件の確認後に定める |
| 定期的な公式ページ確認を自動化 | 見落としを減らし、通知の差分候補を作れる | Newsページの安定した機械可読形式・更新検知方法を未確認。通知がないことはsource不変の証明ではない |
| 定期的に7 sourceを全取得しhash比較 | upstream metadataがなくても実ファイル差分を検知 | API利用条件・取得頻度、認証、負荷、保管運用の確認が必要。現状の自動化には未接続 |

**初期推奨:** Newsを一次情報として担当者が確認し、更新通知後にまとめて7 sourceを取得・検証する。提供元の更新実態と運用負荷を計測するまで、数値の鮮度期限や確認間隔は決めない。定期ページ確認の自動化は、公式の安定した更新検知手段を確認後に追加判断する。

### 差分検証と判定段階

- **変更なし:** 7 sourceのhash不変。取得成功日時は今回の取得時刻として記録するが、sourceが最新・適用中と断定しない。sourceを再取得していない場合は取得時刻を更新しない。
- **想定内差分:** 版/期間の変更が説明可能で、calendarとservice dates、駅・時刻表構造、ODPT対応、品質gateがすべて通る。candidateは作成可能だが公開は人間承認後。
- **要確認差分:** 便数・時刻・停車・種別・行先・照合率・routeCoverageに説明のない差分、期間境界の変更、ODPTとGTFSの版不一致。candidateは隔離し承認保留。
- **検証失敗:** 必須source欠落、HTTP/parse/schema失敗、未知形式、service date欠落、曖昧・矛盾した対応の増加、validator/QA失敗。candidateを採用せず公開停止。

検査対象には、GTFS `feed_version`、`feed_start_date/end_date`、calendar/calendar_datesの差分、ODPT 6 JSONのレコード件数と識別子集合、便の発着・停車駅順・種別・行先、GTFS–ODPT一意照合率/未照合/曖昧/時刻不一致、8駅×service date候補件数・除外内訳・routeCoverageを含める。差分閾値は実更新サンプルを集めるまで定数化せず、重大な変化は原則要確認とする。

### ダイヤ改正・service date・release

- 改正前に次期sourceが正式配布された場合は、公式改正告知とsource内期間/calendarを照合して非公開candidateを作成する。GTFS期間や `date=next`相当の選択だけを改正日の証明にしない。
- 適用開始日は事業者の公式告知、対象datasetの明示metadataなど根拠を保存し、根拠URL/資料名・確認日時・対象路線・対象source・解釈をmanifestに記録する。
- 改正日当日は、新sourceの取得・7 source間整合・service date検証・candidate検証が成功し、承認済み開始時刻に達したことを確認して新releaseを有効化する。service dateは暦日と別フィールドで保持し、GTFS 24時超時刻や翌日暦時刻へ変換してもservice date identityを維持する。
- 現行v2 transfer探索は同じservice date内に限定され、次service dateへの接続探索は未対応。改正日の夜間service dateで境界を跨ぐ接続を網羅したと扱わず、必要なら候補停止または明示的な制限表示を行う。
- release-managed manifestは1世代をpinする既存方式を再利用し、駅間・asset間の新旧混在を防ぐ。旧世代の保持・rollbackでは、expired/未承認のデータを復活させない検証を追加する。

### applicationPeriodと期限切れ

- GTFS feed期間はfeedが記述するサービス日範囲。公開 `applicationPeriod` はアプリがそのreleaseを有効データとして扱う期間。別概念として保持する。
- ODPT JSONとGTFS双方が同一対象期間を記述する根拠を確認する。ODPTに明示期間がない場合は、公式告知等で補えるか確認し、根拠が不十分なら `applicationPeriod=null` を維持する。
- 根拠はcandidate private manifestにsource別に保存し、public manifestには承認済み期間と必要な根拠識別子/説明だけを反映する。`end_at`（公開終了日）を適用終了日として流用しない。
- `applicationPeriod`未設定、承認なし、現在時刻が期限外、source期間矛盾、期間根拠の参照切れがあれば公開・表示判定をfail closedにする。期限切れでは旧releaseをcurrentとして案内せず、データ利用不可/更新待ちを示す。
- rollback先releaseの適用期間が現在有効であること、source/hashと承認状態が依然有効であることを検証する。期限切れ・取消済み承認のreleaseはrollback候補から除外する。緊急時もデータを有効と誤表示するrollbackは行わない。

### 自動化・人間承認の境界

- **A 更新確認・差分検出:** 初期はNewsの確認記録を人が作成。安定した公式検知手段が確認できたら通知/差分候補だけ自動化。
- **B 取得・candidate生成・検証:** 認証情報を取得jobだけに与え、隔離staging、取得時刻/source hash、再現可能なgenerator/validator、失敗時のatomic discardを自動化候補にする。
- **C 公開承認:** 初期は毎回人間が対象期間根拠、差分・品質、表示義務、candidate/release hashを確認して承認。runtime/schema/validator、取得先、credentials、期間ポリシー変更はデータ承認と別のコードレビューが必要。
- **D 自動公開への移行:** 公式取得・通知仕様、適用期間根拠、複数回の差分実績、検証閾値、期限切れ表示、rollback制御、通知責任者、secret権限、staging証跡、停止手順が承認され、運用実績を確認した後に別途判断する。今回の提案では有効化しない。

既存 `.github/workflows/synthetic-public-ci.yml` はworkflow_dispatchのみのsynthetic専用であり、ODPT更新用途に転用しない。実データ更新workflowを追加する場合も既存synthetic経路から分離し、stagingでの承認付き検証を経る。Cloudflare Workers等は、静的candidate/build/deployで要件を満たす限り追加しない。

### 段階的な実装計画（提案）

| Phase | 目的・変更対象 | 完了条件 | テスト方法 | 外部アクセス・公開承認 |
|---|---|---|---|---|
| 0 設計契約 | source ID、manifest項目、差分分類、期間根拠、停止/期限切れ状態を仕様化。文書のみ | 7 sourceの責務・unknown時の扱い・承認境界をレビュー可能 | 例示manifestと状態遷移の机上レビュー | 外部アクセスなし。公開承認なし |
| 1 ローカル履歴 | 保存済みsourceをread-onlyでfingerprintし、非公開manifestへ取得時刻unknownを含め記録 | 既存sourceと出力先分離、欠損/mtime誤用を拒否 | fixture・保存済みsnapshotでhash/bytes/metadataと原本不変を検証 | 外部アクセスなし。公開承認なし |
| 2 差分エンジン | 旧版/新版fixtureのGTFS/ODPT差分と判定分類 | no-change/expected/review/fail各ケースを説明可能 | 合成fixture、source不整合・欠落・schema変更の異常系 | 外部アクセスなし。公開承認なし |
| 3 candidate gate | v2 generator/validatorへsource manifest、period evidence、候補・除外・routeCoverage比較を接続 | applicationPeriod根拠なし・矛盾時にcandidateを公開用へ昇格しない | 保存済みsourceと模擬更新で再現digest、fail closed、8駅×日付網羅 | 外部アクセスなし。公開承認なし |
| 4 read-only取得試行 | 取得コードを隔離stagingへ安全に実行し、sourceだけ更新候補化 | 7件全取得・取得日時/hash保存、部分取得を現行snapshot扱いしない | 無通信mock、HTTP失敗、TLS、redirect、空/異常schema、秘密出力検査 | ODPT/GTFS取得アクセスが必要。公開承認なし。別途明示許可が必要 |
| 5 CI candidate / private staging | 専用workflow、最小secret scope、artifact検証、private/stagingでcandidate QA | artifact一致、source/candidate分離、承認前公開不可、失敗時現行維持 | workflow静的検証、synthetic regression、staging QA | GitHub/Cloudflare操作を別途許可・承認。実データ一般公開なし |
| 6 公開運用審査 | 経験データ・適用期間・license表示・停止/rollback・通知手順を審査 | 運用責任・閾値・公開内容・復旧策を明示承認 | drill/期限切れ/rollback演習、レビュー記録 | 明示的な公開承認が必要。自動公開はさらに別承認 |

この計画は着手承認ではない。まずPhase 0の設計レビューと、提供元仕様の未確認点整理を行う。

## 次の実装ステップ案（未着手）

1. APIキーを秘密管理またはサーバー環境変数 `ODPT_API_KEY` に設定し、値をログに出さず認証テストする。
2. 池袋・小竹向原・氷川台に限定したJSON、駅・路線情報を取得し、取得日時・件数・フィールドを記録する。
3. GTFS ZIPを一時領域で調べ、実在するファイル・列・日付範囲・該当便を一覧化する。
4. 同一運行日の両形式を照合し、ID、停車順、到着・発車、種別、行先、日付跨ぎ、直通範囲を検証する。
5. 必要に応じ、数値API上限、具体的キャッシュ期間、公開payloadが元データの大部分を復元できるか、定型クレジット、今回の想定を超える広告/再配信の扱いをODPTへ確認する。今回受領した回答の範囲では広告付き無料公開・server-side保存/cacheは問題ないとのこと。
6. 確認結果から定期同期・内部正規化・データ失効処理を設計する。今回は動作コード・UIを変更していない。

## 公式参照先

- [ODPT開発者サイト](https://developer.odpt.org/)
- [センター利用規則](https://developer.odpt.org/terms/center_use_rules.html)
- [基本ライセンス](https://developer.odpt.org/terms/data_basic_license.html)
- [開発者ガイドライン](https://developer.odpt.org/terms/data_basic_use_guideline.html)

---

# ODPT実データ調査（Phase 2）

調査日: 2026-10-22（ローカル取得済みファイル）

対象: `local_data/odpt/` の指定6 JSONのみ。外部アクセスなし。

対象外: GTFS ZIPは入力になく調査していない。

## 1. 列車時刻表の構造

### ODPTプロパティの意味と観察結果

ODPT JSON-LDのプロパティ名は、`odpt:departureStation` / `odpt:departureTime` が発車駅・発車時刻、`odpt:arrivalStation` / `odpt:arrivalTime` が到着駅・到着時刻を表す。これはプロパティの意味であり、途中駅に到着時刻が必ず掲載されるという意味ではない。

実ファイルの列車時刻表は、有楽町線843件、副都心線993件。両方とも `odpt:trainTimetableObject` は駅順に並び、ほとんどの要素が発車駅と発車時刻を持つ。両路線の合計29,952要素中、発車駅・時刻の組は28,105、到着駅・時刻の組は1,835。発車欄がない845要素は到着駅欄を持ち、終端到着として現れる。到着時刻が欠けた到着駅要素は計8件。途中駅の到着は通常記録されず、池袋・小竹向原・氷川台も停車地では発車時刻のみで到着時刻はない。停車を通過する駅は要素に現れない。

したがって要素の順序は実際の走行順をたどるが、時刻は駅ごとの発車記録が中心。配列順を使って停車順は特定できても、直前駅との到着・停車時間を復元することはできない。発車時刻のない終端要素は前駅の発車と同じ時刻とみなせず、所要時間の推測にも使えない。

同一の列車運行レコードは、`odpt:train` と `odpt:calendar` の組で識別するのが適切。`odpt:train` と `odpt:trainNumber` は曜日違いで重複する（有楽町線はそれぞれ741種類、843レコードで102組重複）。同一番号だけをキーにすると平日・土休日の別便を混同する。`owl:sameAs` は全件一意で、例は `odpt.TrainTimetable:TokyoMetro.Fukutoshin.A1003K.SaturdayHoliday`。このほか `@id` もレコード識別子。

`odpt:calendar` の実値は両路線とも `odpt.Calendar:Weekday` と `odpt.Calendar:SaturdayHoliday` のみ（件数は下表）。「SaturdayHoliday」は土曜と祝日をまとめる区分としての値だが、個々の実運行日への適用はこの6ファイルに日付例外がないため判定できない。

時刻は `HH:MM`（駅時刻表）または `HH:MM`（列車時刻表の実値。秒なし）で、今回の6ファイルに24時超の値は見つからなかった。00時台の時刻は存在するが、翌日扱いを示す日付や運行日境界は格納されない。このため00時台が暦日上いつに属するかは、これらの値だけでは復元できない。

### ファイル件数と対象駅の列車時刻表件数

| 路線 | 列車時刻表総数 | Weekday | SaturdayHoliday | 池袋・小竹向原・氷川台の全停車順を含む北行記録（Weekday / 土休日） |
|---|---:|---:|---:|---:|
| 有楽町線 | 843 | 458 | 385 | 150 / 129 |
| 副都心線 | 993 | 518 | 475 | 137 / 111 |

北行記録数は列車オブジェクト順に池袋から氷川台へ進むものを数えた。これは直通の停車列の存在を示す。氷川台到着時刻が掲載された便数はどちらの路線・曜日区分も0。

## 2. 池袋→氷川台の直通列車

両路線とも池袋・氷川台を同じ列車番号で走る直通停車列を確認できる。池袋発時刻は同列車の池袋要素、氷川台停車時刻は氷川台要素の**発車時刻**であり、到着時刻ではない。よって要件の「氷川台到着時刻」はデータ上確認不能。到着を発車と同時刻とは扱わない。

実在サンプル（全候補の一部。列車番号・路線・時刻はレコード値）:

| 路線 | 区分 | 列車番号 | 池袋発 | 氷川台到着 | 氷川台発（参考） | 行き先 | 種別 |
|---|---|---|---|---|---|---|---|
| 有楽町線 | 平日 | B1005T | 11:04 | 記録なし | 11:15 | 川越市 | 各駅停車 |
| 有楽町線 | 土休日 | B1003T | 11:03 | 記録なし | 11:15 | 川越市 | 各駅停車 |
| 副都心線 | 平日 | B1004S | 11:41 | 記録なし | 11:50 | 和光市 | 各駅停車 |
| 副都心線 | 土休日 | B1002S | 12:02 | 記録なし | 12:10 | 和光市 | 各駅停車 |

行き先は `odpt:destinationStation` を `Station_all.json` の駅IDに対応付けて表示名にした。列車種別は `odpt:trainType` の実値を日本語に正規化（Local=各駅停車、CommuterExpress=通勤急行等）。駅時刻表の池袋発要素と列車時刻表は、`odpt:train` と同一 `odpt:calendar` の組で照合できた。なお全時刻表の列挙は成果物に転載せず、該当列車件数とサンプルのみを記録する。

副都心線は実レコード上、池袋→小竹向原→氷川台が同一列車に並ぶ一方、有楽町線も同様に対象3駅が同一列車内にある。この結果は時刻表データ上の直通列車の存在を確認するもの。特定日・臨時運転日を含む実際の運行保証ではない。

## 3. 小竹向原乗換候補

池袋→小竹向原列車の小竹向原到着時刻がなく、小竹向原→氷川台列車の小竹向原発時刻は得られるものの、到着時刻との差である待ち時間を算出できない。また乗換後列車の氷川台到着時刻もない。従って、本データから条件を満たす「同一運行日内の別列車乗換候補」を、時刻上の接続候補としても正確に抽出できない。小竹向原到着を同駅の発車時刻や直前駅発車時刻から補間しない。

駅情報ファイルは小竹向原を路線ごとの別駅IDで表現する（`odpt.Station:TokyoMetro.Yurakucho.KotakeMukaihara` と `odpt.Station:TokyoMetro.Fukutoshin.KotakeMukaihara`）。名称は同じだがIDは異なる。駅情報の `odpt:connectingStation` は駅間接続参照を提供するが、このJSONで物理的なホーム移動時間・乗換可能性までは示さない。また同一列車の直通は別路線の列車IDへの乗換として結合せず、各路線の列車時刻表で別々に表されている。

結論: 乗換時刻表の完全な候補生成には不足。仮に別データから到着・発車の時刻が揃って候補化できても、ホーム位置・徒歩時間・最低乗換時間を確認できない限り「時刻上の候補・接続未確認」と表示すべき。

## 4. 駅時刻表との対応・データ品質

- `StationTimetable_Yurakucho.json` は92件、`StationTimetable_Fukutoshin.json` は60件。両ファイルとも駅ID・方向・`odpt:calendar` 単位のレコードを含む。
- 池袋駅時刻表の出発要素を `odpt:train` + calendarで列車時刻表と照合したところ、調査した同方向レコードは全件一致（有楽町線191/191、副都心線212/212）。`trainNumber`だけでの結合は曜日違いの重複があるため不可。
- `StationTimetable` の各要素は `odpt:train`, `odpt:trainNumber`, `odpt:trainType`, `odpt:departureTime`, `odpt:destinationStation` を持つ。駅出発候補・種別・行先はここから得られる。列車時刻表側の池袋発時刻との同一列車照合も可能。
- 駅時刻表の列車番号・列車IDの同一日重複は池袋対象方向の該当レコードで見られず、列車時刻表では番号/列車IDが曜日間で重複する。これは曜日別レコードを意味し、重複便とは数えない。
- 列車時刻表の発車時刻欠損は終端到着オブジェクトに対応する形で存在。到着駅・到着時刻は多くの途中停車要素にない。到着駅欄を持つ要素5件のうち到着時刻も欠くものがあり、単純な必須値扱いはできない。
- 一つの列車レコードは運行路線ID配下に格納されるが、`originStation` / `destinationStation` や停車駅は東京メトロ外IDを含む。実際に副都心線列車の行先に東武・西武・みなとみらい線駅があり、メトロ路線境界外への直通を表現している。対象3駅がメトロ区間内にあればこの6ファイルで停車順は確認できるが、他社区間の詳細時刻表・運行日までは今回の対象データから網羅できない。
- 収録メタデータ `dc:date` は2026-03-16T09:00:00+09:00、`dct:issued` は2026-03-14。これはデータの発行・更新メタデータで、対象日カレンダーの例外や将来の改正日保証ではない。
- 実際の日付適用には祝日、臨時列車、運休・ダイヤ乱れ、改正適用日を別に確認する必要がある。`Weekday` / `SaturdayHoliday` の二分類だけでは祝日振替や特別ダイヤのすべてを確定できない。

## 5. ODPT JSON単独での評価

| 項目 | 評価 | 根拠 |
|---|---|---|
| A. 池袋発の直近列車一覧 | 条件付きで可能 | 池袋駅時刻表から区分・方向別に出発時刻、列車ID、番号、種別、行先を取得でき、列車時刻表と対応する。正しい当日区分・時刻表の有効期間・臨時運転反映が必要。 |
| B. 氷川台到着時刻の算出 | 現状不可 | 対象列車の氷川台要素は停車と発車時刻を示すが、到着時刻がない。到着を推測しない条件では算出不能。 |
| C. 小竹向原での乗換候補生成 | 現状不可 | 小竹向原到着時刻がなく待ち時間が計算できない。別データで補ってもホームと最低乗換時間は未確認。 |
| D. 平日・土休日の正しい切り替え | 条件付きで可能 | ファイルに `Weekday` / `SaturdayHoliday` の両方が実在し切替可能。ただし日付例外・臨時ダイヤ・祝日適用を持つカレンダー情報がこの6ファイルにはなく、任意の日付の正しさは保証できない。 |

## 実データ化に向けた残課題

1. 目的地到着時刻・小竹向原到着を得る別の信頼できる時刻データ（例: 当該便の完全な停車時刻を持つ静的GTFS等）を調査し、ODPT列車IDとの照合可否を検証する。
2. 運行日カレンダー、祝日・例外日、改正適用日を特定できるデータを取得し、画面で選ぶ日付から正しい区分を選択する。
3. 小竹向原のホーム・移動経路・最低乗換時間を裏付ける事業者情報を確認する。未確認なら接続可能と表示しない。
4. 東京メトロ外へ直通する区間も対象にするなら、相手事業者の時刻表・運行日とのID対応を別途検証する。
5. 元データは2026-03-16時点のメタデータである。アプリ採用前に、利用日に有効な改正ダイヤ・運行情報を取得する更新運用を設計する。

本Phase 2では調査文書のみ更新。アプリHTML/CSS/JavaScript、API取得、コミットは行っていない。

---

# ODPT Phase 3 — GTFS配布調査・解析準備（当時の記録）

調査日: 2026-10-22

段階: この節を記録した時点では、配布方法の調査とローカル解析ツールの準備までだった。実データ検証は本書末尾に追記済み。

## 配布元・取得方法

東京メトロの[CKANデータセット](https://ckan.odpt.org/dataset/train-tokyometro)は、GTFS/GTFS-JPの鉄道関連情報を掲載し、適用ライセンスとして公共交通オープンデータ基本ライセンスを示す。リソース詳細ページでは形式とライセンスは確認できるが、今回の閲覧ではダウンロードURL・認証方法・更新日を表示しなかった。

配布先を推測で組み立てず、独立したGTFSフィード目録がこのCKANフィードに結びつけている実ファイルURLを照合した。その記載URLは `https://api.odpt.org/api/v4/files/TokyoMetro/data/TokyoMetro-Train-GTFS.zip`、認証方式はクエリパラメーター `acl:consumerKey`。URLと認証メタデータは第三者のTransitlandフィード目録による確認であり、CKAN画面自体からは取得できなかった。利用時は[CKANデータセット](https://ckan.odpt.org/dataset/train-tokyometro)からリソースへ進み、ポータルの公式ダウンロード操作を優先する。取得できない場合は開発者ポータルの案内と照合する。ブラウザーでキーをURLへ貼り付けると履歴等に残る可能性があるため避ける。URLやキーをチャット、画面共有、コマンド履歴に記録しない。

配布物はZIP 1ファイルの静的GTFS/GTFS-JPフィードとして目録掲載。Transitlandが現在のフィード版として表示する情報は、version `20261008`、開始日2026-09-19、終了日2027-03-12。これはTransitland側で取得した最新版のフィード情報で、調査時点のCKANリソース更新日時そのものではない。CKAN側がファイル更新日時・有効期間をリソース画面上で示していないため、取得後はZIP内の `feed_info.txt`、`calendar.txt`、`calendar_dates.txt` を正とし、目録の日付は補助情報として扱う。

ライセンスはCKAN表示上、公共交通オープンデータ基本ライセンス。一般条件は営利・非営利Deliverableでの利用を認める一方、生データ、複製、元データの全体または大部分を復元可能な派生物の再配布・公衆送信を原則制限し、ガイドライン順守と提供元・正確性非保証等の表示を求める。CKANに表示される個別条件の有無を取得時にも確認する。出典: [基本ライセンス](https://developer.odpt.org/terms/data_basic_license.html)、[開発者ガイドライン](https://developer.odpt.org/terms/data_basic_use_guideline.html)。

### ユーザー側での取得手順

1. ブラウザーで[東京メトロ 鉄道関連情報](https://ckan.odpt.org/dataset/train-tokyometro)を開き、「鉄道関連情報 / Train information」リソースを選ぶ。
2. リソースの公式ダウンロード操作からGTFS ZIPを保存する。ログイン・認証が求められたら、開発者ポータルのアカウントで公式手順を使う。APIキーが必要な場合もキーを共有・記録せず、ブラウザーのURL欄に手入力する方式は避ける。
3. ZIPを展開・編集せず、プロジェクト内 `local_data/odpt/` に配置する。ファイル名は任意の `.zip` でよい。`local_data/odpt/` は `.gitignore` の対象。
4. 配置後に次のコマンドを実行して解析する。

```sh
cd /Users/takamiyakoji/Documents/dotchi-ikebukuro
.venv/bin/python scripts/odpt_phase3_gtfs_analyze.py
```

## ローカル解析スクリプト

既存 `scripts/odpt_phase2_analyze.py` はODPT JSONとGTFSの概況確認を担うため変更せず、GTFS照合の詳細を `scripts/odpt_phase3_gtfs_analyze.py` に分離した。ネットワーク通信はせず、`local_data/odpt/*.zip` とPhase 2で保存済みの列車時刻表JSONだけを読む。

ZIPごとに主要テーブルの行数・列、対象駅ID、対象路線・便、各対象停車の到着・発車時刻、`timepoint`、サービス日範囲・例外を報告する。副都心線の氷川台到着時刻欠損行はpickup/drop-off種別を含めて列挙し、ODPT照合は実データで確認したGTFS `trip_id` 中央部・路線・運行日区分を使う。

GTFS仕様上、`timepoint=1` は正確な時刻、`0` は概算または補間時刻。列が省略されている場合は仕様上、時刻を正確とみなす。`calendar_dates.txt` は `exception_type=1` で運行追加、`2` で運行削除をcalendarの曜日規則に適用し、`calendar.txt` がない場合は各運行日を列挙できる。スクリプトは値の補間・推測をせず、記録された値・分類をそのまま表示する。根拠: [GTFS Schedule Reference — stop_times / calendar_dates](https://gtfs.org/documentation/schedule/reference/)。

この準備段階では列車番号・池袋発時刻・曜日区分による照合を予定していた。実データでの検証結果と、GTFS `trip_id` の切り出し規則は本節より後の「Phase 3 実データ検証」を参照する。

## Phase 3 実データ検証（2026-10-22）

### 対象ファイルと再現方法

`local_data/odpt/TokyoMetro-Train-GTFS.zip` と同ディレクトリに保存済みのODPT JSONのみを使用。外部通信、`.env.local`、APIキーの読み取りは行っていない。ZIPの `feed_info.txt` は東京メトロ、version `20261008`、有効期間 `2026-09-19`〜`2027-03-12`。検証コマンドは次の通り。

```sh
.venv/bin/python scripts/odpt_phase3_gtfs_analyze.py
```

### 1. 副都心線の氷川台到着時刻欠損47件

副都心線 route_id `9` の池袋（stop_id `909`）から氷川台（stop_id `905`）へ進む295 tripを調査。248件は氷川台到着時刻があり、すべて `timepoint=1`。残る47件は全て氷川台のstop_timesレコード自体があり、`stop_sequence=12`、`arrival_time` と `departure_time` が空、`timepoint=0`、`pickup_type=1`、`drop_off_type=1` だった。

この47件は氷川台を経路上の時系列レコードとして持つが、乗降不可が指定され、時刻もない。GTFS上で実際に停車するのか通過するのかはこのデータだけでは判別できない。停車と推測して到着時刻を補わない。

該当trip_id（service_id別。全件共通の氷川台レコード値は上記の通り）:

- service_id `0`（13件）: `91B1085S00`, `91B1089S00`, `91B1119T00`, `91B1151K00`, `91B1247S00`, `91B1263K00`, `91B1303T00`, `91B1329S00`, `91B1485S00`, `91B1489S00`, `91B1519T00`, `91B1551K00`, `91B1663K00`
- service_id `1`（34件）: `93B0554K00`, `93B0689S00`, `93B0731S00`, `93B0733S00`, `93B0805T00`, `93B0839S00`, `93B0855S00`, `93B0911T00`, `93B0943S00`, `93B1023S00`, `93B1054K00`, `93B1161S00`, `93B1189S00`, `93B1233S00`, `93B1255S00`, `93B1311T00`, `93B1343S00`, `93B1413T00`, `93B1423S00`, `93B1561S00`, `93B1589S00`, `93B1633S00`, `93B1711T00`, `93B1743S00`, `93B1791S00`, `93B1813T00`, `93B1823S00`, `93B1849S00`, `93B1885S00`, `93B1943S00`, `93B1989S00`, `93B2149S00`, `93B2153K00`, `93B2243S00`

到着時刻収録率は「乗降可として記録された停車」を `pickup_type=0` かつ `drop_off_type=0` で数えると、有楽町線は279/279、副都心線は248/248。副都心線295件の残り47件は停車扱いにできず、状態不明として分母から分ける。便全体を分母にした記録率は248/295（84.1%）、両路線計では527/574（91.8%）。氷川台では到着時刻のある全件が `timepoint=1` だった。

### 2. GTFS便とODPT列車時刻表の照合

実値は次の通り。GTFSの全対象便で `trip_short_name` は空欄で、`service_id` は `0`（月〜金）と `1`（土日）。trip_idは便を参照する一意値として使われ、10文字の例は `60A1004M00`、`91B1085S00`。ODPTは `odpt:trainNumber` が `A1004M` / `B1085S`、`odpt:train` が `odpt.Train:TokyoMetro.Fukutoshin.B1085S` のようなURI、`odpt:calendar` が `odpt.Calendar:Weekday` または `odpt.Calendar:SaturdayHoliday`。ODPTの列車時刻表レコードは `owl:sameAs` / `@id` も持つ。

データ内で検証できた正規化候補は、GTFS trip_idの先頭2文字と末尾2文字を除いた中央部を列車番号とし（`60A1004M00` → `A1004M`）、その値をODPT `odpt:trainNumber` と比較する方法。対象trip_idは全て長さ10、末尾は `00` が9,705件・`20` が1件で、`trip_short_name` はこの値を格納していない。先頭2文字は `60`〜`63` / `90`〜`93` と複数値があり、末尾2文字も例外を含むが、フィード内に各符号を解読する対応表はないため意味を断定しない。このZIPの実データ上で一致した中央部抽出規則であり、他フィードや別版へ無条件適用しない。

対象は池袋から氷川台へ進む同方向便に限定し、service_idを曜日区分に対応させてから照合した。GTFS便を数えた結果:

| 路線 | GTFS池袋→氷川台便 | trainNumber中央部＋運行日区分で一意一致 | 複数候補 | 対応なし |
|---|---:|---:|---:|---:|
| 有楽町線 | 279 | 199 | 0 | 80 |
| 副都心線 | 295 | 168 | 0 | 127 |

IDと運行日区分で一意になった便は、池袋発時刻も全件一致した（有楽町線199/199、副都心線168/168）。時刻の比較ではGTFS `24:xx` をODPTの翌日表記 `00:xx` と突き合わせられるよう、GTFSサービス時刻を24時間で剰余化した。時刻はID候補を確認する追加検算として使った。池袋発時刻だけを使った同一便の主張はしていない。

未一致は両ファイル間に直接IDキーがないため直ちに非対応便と断定できないが、実データで確認した切り出し規則・路線・運行日だけでは対応が取れなかった便として数えた。`trip_short_name` の完全一致による照合件数が0なのは全件空欄だからである。`odpt:train` の末尾抽出や時刻だけの一致を、全件に通用する規則として追加する根拠は得られていない。異なる列車が同じ池袋発時刻になる可能性を排除できず、時刻一致単独は便IDの証拠にしない。

### 3. 小竹向原の時刻候補

小竹向原はGTFS内に同一名称・同一座標の別stop_id `606` と `906` があり、どちらも `location_type=0`、`parent_station` は空欄。stop_id `606` は有楽町線 route_id `6`、`906` は副都心線 route_id `9` で使われる。駅名・緯度経度は対応するが、GTFS内に両IDを結ぶparent stationや乗換経路の指定はない。

`stop_times` の小竹向原 arrival_time/departure_timeを使うと、有楽町線・副都心線それぞれで池袋から到着し、同じtrip_idのまま氷川台方向へ続く便がある。これらは同一便の継続乗車として扱い、乗換に数えない。異なる路線の別trip_idについて、同じservice_id（運行日区分）かつ小竹向原到着以降に出発する便を時刻上の候補として生成できた。例:

| 到着便（副都心線） | 小竹向原着 | 出発便（有楽町線） | 小竹向原発 | 時刻差 |
|---|---:|---|---:|---:|
| `91B0413K00` | 06:09 | `61B0567S00` | 06:14 | 5分 |
| `91B0509K00` | 06:34 | `61B0521S00` | 06:38 | 4分 |
| `91B0555K00` | 06:47 | `61B0671S00` | 06:49 | 2分 |

これは時刻上の候補であって接続可能判定ではない。stop_id間の構内移動経路、ホーム位置、最低乗換時間はフィードにない。発着が同時刻の候補もあり、乗換可能とは扱わない。

### 4. 運行日と日付跨ぎ

`calendar.txt` はservice_id `0`を2026-09-19〜2027-03-12の月〜金、`1`を同期間の土日とする。運行日の適用は曜日規則に `calendar_dates.txt` の追加（exception_type `1`）・削除（`2`）を重ねて計算する。例:

- 平日 2026-10-22（木）: service `0` 適用、`1` 非適用。
- 土曜 2026-10-24: service `1` 適用。
- 日曜 2026-10-25: service `1` 適用。
- 祝日 2026-11-03（火）: service `0` を削除し、service `1` を追加。
- 祝日 2026-09-21（月）も同じく `0` 削除・`1` 追加。

`feed_info` とcalendarの範囲外（例: 2026-09-18、2027-03-13）はこのフィードの有効サービス日として採用しない。今回の例外日はすべて範囲内。別日付の静的時刻表がないため、期間外に同じ規則が続くとは推測しない。

GTFS stop_timesには24時を超えるサービス時刻がある。例として副都心線 `91B2211K00`（service `0`）は池袋 `24:11`、小竹向原 `24:17`、氷川台 `24:19`。これは当日の暦時刻では翌日0時台だが、運行日判定の基準は前日のservice_idである。実装時には24時間超を保持し、サービス日と暦日を分けて表示・照合する。

### GTFS単独で実ダイヤ表示できる範囲

- **実現可能:** フィード有効期間内の池袋発列車、路線、方面（trip_headsign）、到着を含むstop_times、曜日・祝日例外、氷川台の到着時刻。氷川台到着は有楽町線279便全件、副都心線の時刻記録248便で確認できる。
- **限定付き:** 副都心線の残る47便はstop_timesに駅行があるが乗降不可・時刻なしのため、停車／通過を確定できない。候補から除外するか「時刻なし・状態不明」として扱う必要がある。フィード有効期間外の時刻表は出せない。
- **乗換:** 小竹向原で別便への時刻上の候補は作れるが、構内経路と最低乗換時間なしでは接続可否を保証できない。接続保証を伴う実ダイヤ表示には別根拠が必要。
- **運行実態:** 静的GTFSが示すのは予定時刻。遅延・運休・臨時変更は反映しない。
- **ODPTとの結合:** このフィードではtrip_id中央部から列車番号を得て一部を一意照合できるが、全便一致ではない。GTFS単独で池袋→氷川台の直接列車候補を表示する目的にはODPT結合は不要。全便の便名・運行詳細をODPTで補う用途には未一致分の追加根拠が要る。

したがってGTFS単独で池袋→氷川台の**予定ダイヤ**は実用的に表示可能。時刻収録が明確な便は駅到着まで提示できるが、副都心線47件の状態不明、フィード期間、静的データの鮮度、乗換保証は制約として残る。現行アプリへの実データ導入は未実施。

## Phase 3 — 小竹向原乗換・旅程生成の詳細検証（2026-10-22）

### 検証条件と番線情報

取得済み `TokyoMetro-Train-GTFS.zip` のみを使用し、日付はGTFS service dayとして評価。代表日は平日2026-10-22、土曜2026-10-24、例外日2026-11-03（火・祝日）。接続候補は次のアプリ側暫定条件で生成した。

1. 池袋から小竹向原へ向かう到着便と、小竹向原から氷川台へ向かう出発便を別trip_idで結ぶ。
2. 路線をまたぐ組だけを対象にし、arrival/departureの記録があり、降車・乗車が許可されたstop_timeを使う。
3. 両方の便が同じservice dayに運行することをcalendarとcalendar_datesから確認する。
4. `departure_time - arrival_time >= 60秒` を候補条件とする。これはユーザー指定のアプリ独自ルールで、事業者の接続保証・最低乗換時間ではない。

GTFS内の停留所行に `platform_code` 値は185行中0行。`stop_times.txt` に番線列はない。ZIP内には `transfers.txt`、`pathways.txt`、`levels.txt` 等、ホーム・構内経路を結ぶファイルもない。小竹向原 stop_id `606` / `906` は同じ駅名・座標だが、どちらも親駅なしの別stop。従って3・4番線の同一ホーム乗換は今回確認できたデータでは裏付けられず、旅程結果には「番線未確認／同一ホーム想定」のメタ情報を残す。個別列車が実際に3番線か4番線かは断定しない。

### 代表日の直通便・別列車候補数

「直通経路レコード」は同じtrip_idが池袋、小竹向原、氷川台の順にstop_times行を持つもの。「到着時刻あり」は氷川台arrival_timeがあり、降車可能な行数。副都心線の日別150便／145便のうち到着時刻なし13便／34便は状態不明で、列車が実際に氷川台へ停車すると確認した数ではない。物理停車を推測せずGTFS行と順序で集計した。

別列車接続は、同日運行・反対路線・時刻が存在する全ての到着trip × 後続出発tripを組み合わせた全組数。後の列車も全て別候補として数えるため、数万組の候補は実用画面にそのまま表示する数ではない。待ち時間はGTFSサービス時刻の差（秒）で判定。0分は差0秒、1分は60〜119秒、2分は120〜179秒、3分以上は180秒以上。今回の時刻は分単位なので1分・2分の各区分はそれぞれちょうど60秒・120秒。

| 対象日 | 適用service_id | 有楽町線直通（到着時刻あり） | 副都心線直通（到着時刻あり） | 別便接続の全組 | 0分 | 1分 | 2分 | 3分以上 | 1分以上 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-10-22（木） | `0` | 150/150 | 137/150 | 32,105 | 23 | 66 | 60 | 31,956 | 32,082 |
| 2026-10-24（土） | `1` | 129/129 | 111/145 | 24,696 | 14 | 80 | 29 | 24,573 | 24,682 |
| 2026-11-03（火・祝） | `1`（平日serviceを削除、土休日serviceを追加） | 129/129 | 111/145 | 24,696 | 14 | 80 | 29 | 24,573 | 24,682 |

1分ちょうどの候補数は平日66組、土曜80組、祝日80組。例:

| 運行日 | 到着便・小竹向原着 | 別列車・小竹向原発 | 氷川台着 | 時刻差 |
|---|---|---|---:|---:|
| 平日 2026-10-22 | 有楽町線 `61B0604M00` 06:43 | 副都心線 `91B0511K00` 06:44（方面: 和光市） | 06:46 | 1分 |
| 平日 2026-10-22 | 有楽町線 `61B0627S00` 07:08 | 副都心線 `91B0621T00` 07:09（方面: 和光市） | 07:11 | 1分 |
| 土曜 2026-10-24 | 副都心線 `93B0554K00` 06:32 | 有楽町線 `63B0547S00` 06:33（方面: 和光市） | 06:36 | 1分 |
| 土曜 2026-10-24 | 有楽町線 `63B0604M00` 07:33 | 副都心線 `93B0655K00` 07:34（方面: 志木） | 07:36 | 1分 |

0分境界の例は2026-10-22、有楽町線 `61B0551S00` が06:20に着き、副都心線 `91B0512K00` が06:20に発車する組。GTFS時刻上の差は0秒なので暫定基準では除外する。2分境界の例は同日、有楽町線 `61B0547S00` 06:32着→副都心線 `91B0509K00` 06:34発→氷川台06:37着で、候補に含む。

平日では到着便438本に1分以上の出発候補が1つ以上あり、そのうち434本には複数の後続出発候補が存在した。土曜・祝日は401本が候補を持ち、399本に複数候補がある。これは全日分の後続列車を候補として組み合わせた数であり、同じ池袋発便について全候補を画面カード化すると冗長になる。実装では池袋発列車を親にして直通・乗換をまとめ、乗換候補を氷川台到着時刻順で並べる。初期表示は各到着便につき最早到着の乗換候補を示し、同便からの他候補は展開表示にする案が扱いやすい。乗換候補の到着時刻は乗継後tripの氷川台arrival_timeそのものを使う。

### 同一列車、乗降不可、日付跨ぎ、期間外

- 代表日の直通pathでは、有楽町線は平日150本・土休日129本、副都心線は平日150本・土休日145本が同じtrip_idのまま小竹向原を越えて氷川台行レコードへ続く。これは乗換ではなく同一列車の継続乗車。乗換候補では必ず別trip_idを要求する。
- 副都心線の氷川台到着時刻なし47便は、平日13便・土休日34便。降車不可 (`drop_off_type=1`) かつarrival/departure時刻なしなので、到着駅候補や乗継後の行程に使わず、停車／通過も判定しない。氷川台で乗車不可でも降車可なら到着目的には使えるが、該当47件は降車も不可。
- 小竹向原のarrival/departureどちらかが空欄の組は待ち時間を計算せず除外。時刻を隣駅から補間しない。目的地の氷川台arrival_timeが空欄の副都心線便も乗継後候補から除く。
- 日付跨ぎはサービス時刻を24時間超の整数秒にして差を計算し、service dayのまま扱う。例: 平日 `61B2331S00` は小竹向原23:57着、別の副都心線 `91B2289S00` は24:00発、氷川台24:02着で、待ち3分の候補。23時台着→24時以降発の組は平日58組、土休日70組あり、そのうち待ち1〜10分の例示窓では平日2組、土休日3組だった。10分はこの境界例を抽出するための報告上の窓で、アプリの接続上限ではない。
- 2026-11-03は火曜だが、例外行がservice `0`を削除しservice `1`を追加するため、土曜と同じ日別便集合・候補数になった。運行日判定は曜日だけでは足りず、例外適用後の運行service集合を使う。
- feed有効期間外の2026-09-18は有効serviceなし。2027-03-13も対象外。期間外にカレンダーを延長して候補を作らない。

### 再現用スクリプト

`scripts/odpt_phase3_itinerary_analyze.py` はZIPを読むだけでネットワーク接続しない。既定では平日・土曜・祝日例外日を解析する。別の日付を明示する場合:

```sh
python3 scripts/odpt_phase3_itinerary_analyze.py 2026-10-22 2026-10-24 2026-11-03 2026-09-18
```

### Ver.0.5の内部データモデル案

1. **Feed:** `feed_version`, `feed_start_date`, `feed_end_date`, 取得・生成時刻。日付が有効期間外なら検索結果を作らない。
2. **ServiceDay:** `service_date`, `active_service_ids`。calendar曜日規則にcalendar_datesを適用して日単位で確定する。
3. **TripInstance:** `(service_date, trip_id)`をキーとし、`route_id`, 路線表示名, `trip_headsign`, `service_id` を保持する。trip_id単独では運行日を識別しない。
4. **StopEvent:** `stop_id`, 正規化した論理駅ID, `stop_sequence`, arrival/departureのサービス秒, pickup/drop-off, `timepoint` を保持する。24時超を24時間内へ剰余化せず、空欄はnullのままにする。
5. **StationAlias:** 池袋・小竹向原・氷川台の論理駅と路線別stop_idの対応を明示する。小竹向原606/906は共通座標・名称からの対応づけで、ホーム／番線対応とは分離する。
6. **Itinerary:** 種別（direct/transfer）、池袋発TripInstance、必要なら小竹向原の到着便・出発便、各駅時刻、待ち秒、氷川台着、`transfer_policy_seconds=60`、`platform_status=unknown`、`connection_guaranteed=false` を保持する。時刻候補と保証済接続を同一のbooleanで表さない。

### Ver.0.5の実装順序案

1. GTFS ZIPを読み込み、必須列・ID参照・時刻形式・フィード期間を検査するローカル前処理を作る。
2. calendar適用後のservice dayごとにTripInstanceとStopEventを構築。時刻欠損・乗降不可を捨てずに理由付きで保持する。
3. 直通旅程を同一trip_idの停車順と池袋departure／氷川台arrivalから生成する。
4. 乗換旅程を異なるtrip_id・反対route・同日service・小竹向原到着／発車の記録・氷川台到着記録から生成し、`wait_seconds >= 60` を適用する。60秒は設定値として記録し、事業者保証の表現を付けない。
5. 同一池袋発便の結果をまとめる。初期カードには直通と最早到着の乗換案を表示し、他の後続候補は到着順の展開リストへ置く。より遅く出て同じか遅く着く候補は初期表示から除くが、全行程データから削除しない。
6. その後にアプリのdata adapter / 画面連携を行い、欠損47件、0/1/2分、日付跨ぎ、祝日例外、期間外、複数候補をレビューする。今回の調査ではアプリ本体を変更していない。

## Phase 3 — 旅程候補の最適化と表示項目（2026-10-22）

### 比較方法

`scripts/odpt_phase3_itinerary_optimize.py` で取得済みZIPと保存済みODPT JSONをローカル解析した。各池袋発tripを親として、同一trip_idの氷川台到着（時刻あり・降車可）を直通候補として保持する。乗換は、別trip_id・反対路線・同じ運行日・小竹向原で降車／乗車可・到着／発車時刻あり・待ち60秒以上を満たす候補から氷川台到着が最も早いものを選ぶ。直通と乗換を比較し、同着は直通優先とした。60秒はアプリ側の暫定条件で、接続保証ではない。

待ち時間上限は5分・10分・15分・上限なしで比較。元接続組は条件に合う到着trip×出発tripのペア数、池袋発便集約は少なくとも一つの候補がある親trip数。したがって集約数が初期画面の候補カード数に相当し、元接続組は全件表示数ではない。表の直通最早数は乗換候補もある親のうち直通が最早（同着含む）、直通のみは有効な直通があり乗換候補がない便、乗換のみは有効な直通到着がなく乗換候補がある便。

| 日付・上限 | 元接続組 | 池袋発便に集約 | 直通最早 | 乗換最早 | 同着 | 直通のみ | 乗換のみ |
|---|---:|---:|---:|---:|---:|---:|---:|
| 平日 2026-10-22・5分 | 348 | 326 | 187 | 0 | 0 | 100 | 139 |
| 平日・10分 | 622 | 417 | 269 | 0 | 0 | 18 | 148 |
| 平日・15分 | 899 | 437 | 285 | 0 | 0 | 2 | 152 |
| 平日・上限なし | 32,082 | 438 | 286 | 0 | 0 | 1 | 152 |
| 土曜 2026-10-24・5分 | 278 | 267 | 129 | 0 | 0 | 111 | 138 |
| 土曜・10分 | 490 | 366 | 210 | 0 | 0 | 30 | 156 |
| 土曜・15分 | 689 | 396 | 234 | 0 | 0 | 6 | 162 |
| 土曜・上限なし | 24,682 | 401 | 239 | 0 | 0 | 1 | 162 |
| 祝日 2026-11-03・5分 | 278 | 267 | 129 | 0 | 0 | 111 | 138 |
| 祝日・10分 | 490 | 366 | 210 | 0 | 0 | 30 | 156 |
| 祝日・15分 | 689 | 396 | 234 | 0 | 0 | 6 | 162 |
| 祝日・上限なし | 24,682 | 401 | 239 | 0 | 0 | 1 | 162 |

乗換のみのうち、氷川台までの停車順行はあるが到着時刻欠損／降車不可の直通が、平日は13便、土曜・祝日は34便。残りの乗換のみはそれぞれ同じtrip_idに氷川台行がない139便／128便（5分上限時は126便／106便）。後者は必ずしもデータ欠損ではなく、同じ列車の停車列で目的地へ到達できない便を含む。

有効な直通と乗換を比較できた全件では、3日とも直通が最早で、同着はなかった。よって直通に対する乗換短縮は全日・全待ち上限で0件。短縮1・2・3・5分以上の各推奨条件も0件だった。比較可能な便では逆に直通が早く、平日の差は5分上限時2〜7分、10分時2〜10分、15分時2〜15分、上限なし2〜18分。土曜・祝日は順に2〜5分、2〜11分、2〜15分、2〜32分。上限なしの最大差は長時間待つ接続を選べることによる。これは今回の対象日とデータにおける予定時刻の結果で、将来の全ダイヤへの一般化ではない。

候補数は、例えば平日10分上限で622ペアから417池袋発便、土曜・祝日では490ペアから366便に縮約される。さらに親便ごとに最早到着乗換を一つ選ぶと、画面上の乗換案はそれぞれ417件／366件以下になる。5分上限は平日348→326、土曜・祝日278→267。上限なしは数万ペアを生むため初期表示には使わないのが妥当。初期仕様の上限値は固定せず、5/10/15分のどれを採るかは操作性と候補数を踏まえて決める。上限と「何分短縮なら乗換推奨」の閾値は別設定にする。今回の結果だけなら乗換を速達手段として推奨する閾値は有効性がなく、直通を既定で最上位にする根拠となる。乗換のみ便は候補として残し、直通比較なしと明示する。

1分待ち候補（前節の全接続組でちょうど60秒）は平日66組、土曜80組、祝日80組。これらを含むが、同一親便に複数組があるため、組数とユニーク池袋発便数は異なる。ちょうど1分の具体例は前節の表を参照。1分を含む全候補数は待ち上限5分の値に含まれる。

### 比較例と境界条件

最適化スクリプトは各シナリオで、直通が乗換より早い比較例と、直通到着がない乗換のみ例を最大2件ずつ出力する。全ての選択結果は日付・trip_idごとに再現できる。到着時刻の秒を比較し、表示はGTFS時刻文字列を維持する。GTFSが分単位のため、今回の日別データでは待ち1分は60秒差。

池袋発に出ていない候補・時刻欠損・pickup/drop-off不可のイベントは旅程に使わない。同じtrip_idは直通であり、乗換候補として再利用しない。到着が日付をまたぐGTFS 24時超の時刻はサービス秒に保つため、日付をまたいだ接続の差分も正しく比較できる。calendar_dates適用後の運行日が一致する便のみを組み合わせ、フィード有効期間外は候補0件。代表日では祝日2026-11-03がservice_id `1`となり、土曜と同じ候補集合になった。

### 表示情報の収録とODPT補完

GTFSは路線名（`routes.route_long_name`）、全tripの行先方面（`trips.trip_headsign`）、池袋発・氷川台着・小竹向原のarrival/departure、途中のstop_sequenceから得る停車駅順、service_idとカレンダーを提供する。行先はGTFS headsignとして表示できる。途中停車駅は今回の有効な直通例で要町・千川。GTFS `route_type=1` は鉄道の区分で、急行／各停のtrip種別ではない。対象843有楽町線trip、993副都心線tripの `trip_short_name` は全て空。

保存済みODPT JSONとの照合は、GTFS trip_idの先頭・末尾各2文字を除いた列車番号、路線、Weekday／SaturdayHoliday calendarの一致を候補条件にし、池袋発時刻も照合した。一意一致した便では池袋発分が全件一致したが、これは照合条件を補強する整合性確認であり、時刻一致単独を同一便の証拠にはしない。氷川台までの有効な直通便に限ると、平日有楽町線は106/150一致・44未照合、副都心線は91/137一致・46未照合。土曜・祝日は有楽町線93/129一致・36未照合、副都心線77/111一致・34未照合。未照合便の種別・ODPT行先は補完せず不明／非表示とする。

一意照合分の列車種別は、平日有楽町線106件がLocal、副都心線91件がLocal 77・CommuterExpress 14。土曜・祝日は有楽町線93件、副都心線77件がいずれもLocal。ODPT `destinationStation` も一意一致時に参照できるが、GTFS headsignと同じ概念と決めつけず、別項目として保持する。照合できない場合にGTFSの方面名から急行／各停を推測しない。

### Ver.0.5向け仕様案

- 一覧の親単位は `(service_date, origin_trip_id)`。各池袋発便に、GTFS時刻で最も早く氷川台へ着く旅程を `primary_itinerary` として一件割り当てる。比較可能なら直通・乗換双方を評価し、同着は直通を採る。
- 現UIに合わせ、カードには路線、種別（照合できたときだけ）、行先方面、池袋発時刻、氷川台着時刻、直通／小竹向原乗換ラベルを置く。乗換カードには小竹向原着・発と待ち分を追記する。
- 直通が有効なら `direct_alternative` として保持。初期表示では最早旅程を主表示し、別の直通／乗換案は詳細展開に置く。現データでは直通がある便は全て直通が早かったため、推奨表示は直通。ただし待ち上限は5/10/15分を引き続き比較し、仕様決定時に設定化する。
- 同じ出発便に複数の乗換後列車がある場合、主乗換案は最早着を一つ選び、同じ到着時刻なら待ちが短い便、なお同じならtrip_id順を安定タイブレークとする。全候補は到着順の代替リストに残す。乗換短縮の推奨閾値は未確定で、評価条件として1/2/3/5分を保持する。
- `platform_status=unknown` とし、同一ホーム・3/4番線を列車属性に付けない。画面で番線を出す場合は「未確認」。60秒以上というアプリ候補基準と「接続保証なし」をデータ状態として分ける。
- 到着時刻なし／降車不可、乗車不可、stop行なし、フィード期間外は個別の理由コードで保持し、時刻を補完しない。便の行先方面は出せても目的地着を計算できない場合は、到着表示を空欄にせず「到着時刻データなし」と説明するか、その候補を除外する。
- 運行日は日付から有効service_idを解決し、24時超時刻はservice secondsで保持。feed_versionと有効期間を検索結果のメタデータに含める。

内部モデルは先のTripInstance／StopEvent／Itinerary案を継続し、Itineraryに `primary`, `direct_alternative`, `transfer_wait_seconds`, `arrival_status`, `transfer_policy_seconds`, `platform_status` を加える。具体的な未決定事項は (1) 5/10/15分のどの待ち上限を採るか、(2) 乗換候補を初期カードに併記するか詳細展開にするか、(3) 種別／ODPT行先の不一致時の表示文言、(4) 欠損便を一覧に残すか除外するか、(5) GTFS更新・失効時のデータ更新運用。遅延・運休情報は今回の静的GTFS検証の対象外。

### 再現コマンド

```sh
python3 scripts/odpt_phase3_itinerary_optimize.py 2026-10-22 2026-10-24 2026-11-03
```

ローカルGTFS ZIPと取得済みODPT JSONのみを読み、APIキー・`.env.local`・ネットワークには触れない。アプリ本体は変更していない。

## Ver.0.5 Step 2B-2 改善 — 表示件数と列車種別照合（2026-10-22）

### 表示件数

ローカルpreviewではadapterが現在以降の候補を抽出し、直通のみfilterを適用した後にカード数を制限する。路線別は各路線の先頭3件、発車順は全路線を混ぜた先頭6件。最早着はこの表示対象だけで再計算する。同じ便が発車して候補から外れると毎秒の再描画で後続便が補充される。公開UI・adapter本体の表示件数仕様は変更しない。

### 種別照合の拡張調査

既存 `ItineraryGenerator` のODPT indexは、路線・運行日区分・GTFS trip_id中央部由来の `odpt:trainNumber` に加え、ODPT停車列に池袋と氷川台が順方向に存在することを要求していた。この条件は直通列車には合うが、小竹向原で別列車へ乗り換える場合の池袋発列車には不要な氷川台停車を要求する。そのため、乗換旅程の先行列車にもあるODPT `trainType` が「種別不明」になる。

追加のローカル解析 [odpt_phase3_train_type_match.py](../scripts/odpt_phase3_train_type_match.py) は、保存済みODPT全列車時刻表から、次の段階を分けて集計する。

1. `route_id` に対応したODPT路線、calendar区分、GTFS `trip_id[2:-2]` とODPT `trainNumber` が一意一致し、池袋発時刻の秒まで一致する照合。この一致はODPTのtrain IDで確認できる。
2. 上記で残る便に対し、route、calendar、池袋発時刻（ODPTの分精度）、ODPT `destinationStation` IDとGTFS `trip_headsign` の日付持ち越し検証で得た一貫した対応を使う候補照合。異なる日付のID一致便を学習側／検証側に分け、既知便で同じODPT `odpt:train` が一意に選ばれるかを確認する。

主表示対象（`primary_itinerary` あり）の結果:

| 日付・区分 | primary便 | 既存の氷川台経由ID照合 | 全ODPT便のID+路線+日区分+池袋時刻で確認 | さらに一意候補（ID未確認） | holdout既知便で同一train ID選択 |
|---|---:|---:|---:|---:|---:|
| 平日 2026-10-22 | 435 | 197 (45.3%) | 307 (70.6%) | 128 (29.4%) | 307/307 |
| 土曜 2026-10-24 | 396 | 170 (42.9%) | 286 (72.2%) | 107 (27.0%) | 286/286 |
| 祝日 2026-11-03 | 396 | 170 (42.9%) | 286 (72.2%) | 107 (27.0%) | 286/286 |

全ODPT便のID一致による追加分の内訳は、平日が有楽町線の乗換旅程50/68・副都心線60/80、土休日が46/60・70/96。氷川台までの直通便の一致数は既存照合から変わらず、平日197/287（68.6%）、土休日170/240（70.8%）。乗換の先行便は氷川台を通る必要がないため、ODPTの停車列を氷川台で絞る条件を外すことで正確なtrain ID付き種別が増えた。

未一致便に対する日区分・行先・発車分の候補規則では、平日128件、土曜・祝日107件が一意候補となった。既知ID便のholdout検査では平日307/307、土休日286/286で正しい `odpt:train` を選び、候補が作れた未知便も全件一意だった。ただし未知便自身には独立したODPT train IDの裏付けがないため、これらは「検証済みの正解」ではなく「検証済み規則による一意候補」として扱う。アプリへは補完実装せず、未照合のまま残す。時刻一致だけの代替照合も使わない。保存データ内で一致しないGTFS便の先頭／末尾符号の意味や、ID欠落理由は確定できなかった。

IDで確認できた種別の割合は平日70.6%、土曜・祝日72.2%。一意候補を仮に含めた候補網羅率は平日435/435、土曜・祝日393/396（99.2%）だが、後者は未知便の真値を直接確認した割合ではない。種別を正確に識別できた率として採用するのはID確認済み率までとする。

### Fライナーのデータ表現

取得済みODPT副都心線 `TrainTimetable` 993レコード中107レコードが `odpt:trainType` 値 `F-Liner`。GTFS `trips.txt` は `trip_short_name` が全件空で、列車種別やFライナー識別属性を持たない。取得済みODPT JSONではF-Linerは `odpt:trainType` に記録され、`serviceName` 等の独立したブランド／サービス属性は見つからない。これはローカル保存ファイルの調査範囲の結論で、他の公式データ製品の有無までは確認していない。

IDと池袋発時刻を一意確認できた乗換旅程の先行列車ではF-Linerが平日23件、土曜・祝日20件あった。直通到着便のF-Liner一致は今回の有効到着集合にはなかった。内部モデルでは、ODPTが返す原コードを `reportedTrainType` として保持し、`serviceBrand` は独立属性にする。ODPT側に別のブランド識別子がない状態では `serviceBrand` を推定せず、`F-Liner` を `Express` と同一視・変換しない。`F-Liner` の原値を種別コードとして維持する。

再現コマンド:

```sh
python3 -B scripts/odpt_phase3_train_type_match.py
```

取得済みローカルGTFS ZIPとODPT JSONのみを読み、ネットワーク・APIキー・`.env.local` は使わない。

### Ver.0.5 列車種別の確定照合実装（2026-10-22）

旅程生成器のODPT索引から「ODPT停車列に氷川台があること」という条件を削除した。小竹向原乗換の先行列車は氷川台へ行かなくても旅程に必要な列車であり、この条件が種別照合を不必要に落としていたためである。照合は次の全条件を満たす場合に限る。

1. GTFS `trip_id[2:-2]` と保存済みODPT `trainNumber` が完全一致（観測済み10文字形式のみ）
2. GTFS routeから得るODPT路線と `odpt:calendar` 区分が一致
3. 池袋のODPT `departureTime` がGTFS発車時刻と秒まで一致（24時超は時刻日の秒へ正規化）
4. 上記条件を満たすODPTレコードがちょうど1件

IDだけの一致、時刻・行先だけの候補一致、曖昧一致は補完に使わない。重複する列車番号があれば時刻条件まで適用して候補集合を作り、同条件のレコードが複数なら `ambiguous` とする。`odpt:trainType` は原コードのまま保持する。`serviceBrand` は独立項目で、保存済みODPT JSONに別の愛称フィールドがないため `null`。したがって `F-Liner` は原種別として「Fライナー」と表示し、「急行」へ置換しない。

| 代表日 | 主旅程 | 旧照合数 | 新しいID・路線・運行日・発車時刻の確定照合 | 新照合率 | 未照合 |
|---|---:|---:|---:|---:|---:|
| 平日 2026-10-22 | 435 | 197 | 307 | 70.6% | 128 |
| 土曜 2026-10-24 | 396 | 170 | 286 | 72.2% | 110 |
| 祝日 2026-11-03 | 396 | 170 | 286 | 72.2% | 110 |

旧照合からの増分は乗換旅程の池袋発先行便で、平日110件、土曜・祝日116件。直通便の照合数は従来どおり平日197/287、土休日170/240。照合確認便の種別コード数は平日 `Local 256 / CommuterExpress 14 / Express 11 / F-Liner 23 / SemiExpress 2 / Rapid 1`、土曜・祝日 `Local 242 / Express 20 / F-Liner 20 / SemiExpress 2 / Rapid 2`。未照合は引き続き「種別不明」。日本語表示は `Local=各駅停車`、`Express=急行`、`CommuterExpress=通勤急行`、`SemiExpress=準急`、`Rapid=快速`、`RapidExpress=快速急行`、`F-Liner=Fライナー`、`S-TRAIN=S-TRAIN`。

行先表示はODPT照合で裏付けられた値とGTFSの `trip_headsign` を混同しない。payloadの日本語行先は従来どおりGTFS headsignを使い、`destinationSource=gtfs_headsign` と記録する。確定一致便だけODPT `destinationStation` のID群を併記する。未照合便でもGTFS headsignは表示可能だが、ODPT由来の行先情報であるかのように扱わない。IDから日本語名への推測変換はしない。

F-Linerの確定照合例は平日23件・土曜20件で、いずれも副都心線から小竹向原乗換を始める便。2026-10-22の主旅程内では同一の23便に `reportedTrainType=F-Liner`、画面表示「Fライナー」、`serviceBrand=null` が出力される。平日全435件中128件、土休日396件中110件は種別を補完しない。

実装箇所は [odpt_itinerary.py](../scripts/odpt_itinerary.py)、[export_local_timetable_payload.py](../scripts/export_local_timetable_payload.py)、[timetable_adapter.mjs](../scripts/timetable_adapter.mjs)。payloadには `reportedTrainType` と `serviceBrand` を追加し、従来の `trainType` も互換項目として維持した。生ODPTレコードは出力しない。

### GTFS停車パターンによる種別識別の検証（2026-10-22）

指定された東京メトロ公式停車駅表を根拠に、[副都心線の駅・停車駅案内](https://www.tokyometro.jp/station/line_fukutoshin/index.html) と [有楽町線の駅案内](https://www.tokyometro.jp/station/line_yurakucho/index.html) を確認した。副都心線表は通勤急行・急行の停車駅を個別に示し、要町・千川は両種別とも通過、氷川台は通勤急行停車・急行通過、小竹向原は両方停車。各駅停車はこの表の全駅停車パターンとして扱える。F-Linerは急行と停車パターンが同じため、停車情報だけでは区別できない。公式表の駅ごとの印とページ本文を基準にし、他社線内の列車種別を東京メトロ線内の種別と同一視しない。

有楽町線の公式駅一覧には副都心線のような通勤急行／急行停車区分がない。GTFSの要町・千川・小竹向原・氷川台に有効な停車イベントがあるときだけ「メトロ線内全駅停車パターン」と数えた。この事実からODPT `Local` へ変換してはいない。ODPT `SemiExpress` / `Rapid` 等は他社直通区間の種別を含み得るため、同じ停車パターンから列車全体の種別名を決めない。

検証器 [odpt_phase3_stop_pattern_classifier.py](../scripts/odpt_phase3_stop_pattern_classifier.py) は、同じ運行日の `primary_itinerary` がある池袋発便を対象にした。駅の状態規則は厳格に次の通り。

- `stop`: arrival/departureの少なくとも一方に時刻があり、pickupまたはdrop-offの少なくとも一方が許可（空欄はGTFS既定の許可として扱う）。時刻のあるレコードでも乗降両方不可なら有効停車とは認めず判定不能。
- `pass`: 対象駅のレコードがあり、時刻が両方空欄、かつpickup/drop-offが両方禁止。物理的な通過を直接計測した値ではなく、GTFSに旅客停車イベントがないというパターン証拠としてのみ使う。
- レコードなし、時刻・乗降可否の組合せが上記以外、または分類に必要な駅状態が欠ける場合は `unknown`。駅レコードの不在を通過と推測しない。

#### 代表日ごとの結果

各セルの「判定」は副都心線の三種別パターン件数。有楽町線の判定欄は独立した公式種別表がないため、全駅停車パターン数／判定不能数。

| 日付・路線 | 主旅程便 | ODPT確定 | ODPT未照合 | パターン集計 | 未照合便のパターン内訳 |
|---|---:|---:|---:|---|---|
| 平日 2026-10-22 副都心線 | 217 | 151 | 66 | 各停107・通勤急行30・急行同型13・判定不能67 | 各停30・通勤急行16・急行同型0・判定不能20 |
| 平日 2026-10-22 有楽町線 | 218 | 156 | 62 | 全駅停車150・判定不能68 | 全駅停車パターン44・判定不能18 |
| 土曜 2026-10-24 副都心線 | 207 | 147 | 60 | 各停111・急行同型34・判定不能62 | 各停34・急行同型9・判定不能17 |
| 土曜 2026-10-24 有楽町線 | 189 | 139 | 50 | 全駅停車129・判定不能60 | 全駅停車パターン36・判定不能14 |
| 祝日 2026-11-03 副都心線 | 207 | 147 | 60 | 土曜と同一 | 土曜と同一 |
| 祝日 2026-11-03 有楽町線 | 189 | 139 | 50 | 土曜と同一 | 土曜と同一 |

「急行同型」は急行停車駅パターンを表し、急行という列車種別の確定ではない。F-Linerとの識別ができないため、同型9件（未照合土休日便）は種別名を確定しない。

#### ODPT確定便を正解にした比較

副都心線で、確定ODPT種別をメトロ線内停車種別と比較できる範囲の結果:

| 日付 | ODPT原種別 | パターン一致 | 必要駅状態不足で比較不能 | 不一致 |
|---|---|---:|---:|---:|
| 平日 | Local | 77/103 | 26 | 0 |
| 平日 | CommuterExpress | 14/14 | 0 | 0 |
| 平日 | Express | 急行同型 2/11 | 9 | 0 |
| 平日 | F-Liner | 急行同型 11/23 | 12 | 0 |
| 土曜・祝日 | Local | 77/107 | 30 | 0 |
| 土曜・祝日 | Express | 急行同型 14/20 | 6 | 0 |
| 土曜・祝日 | F-Liner | 急行同型 11/20 | 9 | 0 |

判定可能だったODPT確定便では不一致0件（平日104、土曜・祝日102）。これらはstop patternと矛盾しないが、母数は確定照合便全件ではない。平日の副都心線確定151件中47件、土休日147件中45件は必要駅状態が足りず比較不能。特に急行／F-Linerは要町・千川の通過パターンが同じで、氷川台が通過扱いの行であってもODPT名の識別はできない。未一致を不一致扱いにはしない。

有楽町線の確定便は平日156件中 `Local 153 / SemiExpress 2 / Rapid 1`、土休日139件中 `Local 135 / SemiExpress 2 / Rapid 2`。有効な全駅停車パターンが確定Localのうち平日106件・土休日93件で確認できた。残る確定便は氷川台レコード欠落などにより比較不能で、SemiExpress / Rapidも含めて公式有楽町線内の種別に対応づけられない。これは矛盾ではなく、ODPTの列車種別が直通先区間の種別を表す可能性を除外できないためである。

#### 未照合便の例と種別不明率の見込み

| 日付 | GTFS trip_id | 停車状態（要町／千川／小竹向原／氷川台） | 判定 |
|---|---|---|---|
| 平日 | `91B0501S00` | 停車／停車／停車／停車 | 副都心線各駅停車パターン |
| 平日 | `91B0559K00` | 通過証拠／通過証拠／停車／停車 | 通勤急行パターン |
| 土曜 | `93B0554K00` | 通過証拠／通過証拠／停車／通過証拠 | 急行・F-Liner同型、個別種別は判定不能 |
| 平日 | `91B0527K00` | 停車／停車／停車／駅行なし | 判定不能。氷川台行がないことを通過とみなさない |
| 土曜 | `93B0658K00` | 通過証拠／通過証拠／停車／駅行なし | 判定不能。通勤急行／急行同型を分ける氷川台状態がない |
| 平日 | `61B0553S00` | 有楽町線4駅すべて停車 | メトロ区間全駅停車パターン。種別名は不明のまま |

ODPT未照合便の現状は平日128/435（29.4%）、土曜・祝日110/396（27.8%）。未照合副都心線で、確定種別へ落とせるパターンは平日46件（各停30・通勤急行16）、土曜・祝日34件（各停34）。この判定規則を将来採用すれば、**正確な列車種別の不明率は平日82/435=18.9%、土曜・祝日76/396=19.2%まで下がる見込み**。この推定はODPT確定便とのパターン比較に矛盾がなかった範囲に限定し、F-Linerと急行同型の未照合便は種別不明に残す。

補助情報として「メトロ区間全駅停車パターン」を別属性で表示するなら、さらに平日44件、土休日36件の有楽町線未照合便を説明できる。これはODPT列車種別を確定しない。土休日の急行同型9件も「急行／F-Liner同型」としか言えず、列車種別は不明のまま。画面に停車パターン属性を追加してgenericな「種別不明」表記を減らす場合でも、正確な種別不明率は18.9%／19.2%である。

表示上「列車種別」ではなく停車プロファイルを示す選択肢まで含めると、現状の未照合便のうちパターン情報を付けられるのは平日90/128件（土休日79/110件）。その場合、単に汎用の「種別不明」と表示する便は38/435=8.7%、31/396=7.8%まで減らせる。ただし、平日44件／土休日36件は有楽町線の全駅停車パターン、土休日9件は急行／F-Liner同型を示すだけであり、この表示率を列車種別の判明率として報告してはいけない。正確な種別不明は引き続き82/435=18.9%、76/396=19.2%。

実装採用案は、ODPT確定値を常に優先し、矛盾時は上書きせず診断状態へ送る。ODPT未照合時に限り副都心線の `local` と `commuter_express` を停車パターン由来の暫定分類として別source付きで保持する。有楽町線の全駅停車、急行同型、未記録駅は `stopPattern` 等の独立属性とし、`trainType` には変換しない。ODPT確定便と矛盾する例は今回0件だったが、パターン分類できた確定サンプル平日104・土休日102件のみで、他の列車・フィードにも無条件に一般化しない。

#### ローカルpreviewへの表示反映（2026-10-22）

検証済みの共通判定を [`odpt_stop_patterns.py`](../scripts/odpt_stop_patterns.py) に切り出し、旅程生成器と既存調査スクリプトで共有した。ODPTが一意照合された便は原 `odpt:trainType` を優先する。副都心線ではODPT種別と必要停車パターンが比較できて矛盾した場合、種別表示を「種別不明」に保留し、`reportedTrainType`、`typeValidation=conflict`、`typeDiagnostic=odpt_stop_pattern_conflict` を出力する。必要イベントが欠ける場合も補完しない。ODPT照合が曖昧または利用できない便は、厳密に未照合便とは扱わず、停車パターン分類へフォールバックしない。

ODPT未照合便のみ次の表示分類を適用する:

- 副都心線の各駅停車パターン: `各駅停車` / `gtfs_stop_pattern`
- 副都心線の通勤急行パターン: `通勤急行` / `gtfs_stop_pattern`
- 副都心線の急行・Fライナー同型: `急行型` / `gtfs_stop_pattern`。種別コード・ブランドは空のまま
- 有楽町線の全駅停車パターン: `全駅停車` / `gtfs_stop_pattern`。正式な列車種別ではない
- その他・欠損・不確定: `種別不明` / `unknown`

種別表示率は到着時刻が利用可能な池袋発のprimary旅程を分母とする。平日2026-10-22は435便で、ODPTのみでは128便が未確定（29.4%）。更新後は分類表示された便が397、`種別不明` が38/435（8.7%）。この38件に加えて有楽町線44件は「全駅停車」、すなわち補助情報のみで正式種別は不明。従って正式種別が不明な便は82/435（18.9%）と数える。土曜2026-10-24と祝日2026-11-03は同じ運行区分で各396便。ODPTのみの未確定110/396（27.8%）に対し、更新後の `種別不明` は31/396（7.8%）。さらに有楽町線全駅停車36件、急行型9件は補助表示であり、正式種別不明は合計76/396（19.2%）。土曜・祝日のパターン由来の内訳は各駅停車34、急行型9、全駅停車36。

各日とも分類可能なODPT確定副都心線便との矛盾は0件（平日104件、土休日102件が比較可能）。確定パターンのない便や停車イベントが不十分な便を含むため、上記率はこのGTFS版・対象日・池袋発primary旅程に限る。Fライナーは確定ODPT原値がある便だけ `Fライナー` とし、急行型パターンからの推定はしない。

payload例の代表件数: 平日 `odpt_confirmed` 307、`gtfs_stop_pattern` 90、`unknown` 38（計435）; 土曜・祝日 `odpt_confirmed` 286、`gtfs_stop_pattern` 79、`unknown` 31（計396）。ODPTが確定しているにもかかわらず種別名称の対応表にない値も原値を保持し、画面ラベルは未知のままにする。

### 残存「種別不明」便 全件診断（2026-10-22）

再現用の [odpt_phase3_unknown_diagnostics.py](../scripts/odpt_phase3_unknown_diagnostics.py) を追加した。保存済みGTFS/ODPTだけから、対象便ごとのtrip ID、路線、発車時刻、行先、現行ODPT照合状態、ID候補、各停車イベントの時刻・pickup/drop-off、判定理由をderived JSONとして出力する。JSONには生レコードを含めず、出力先はリポジトリ外に指定する。

#### 原因分類

| 対象日 | 平日2026-10-22 | 土曜2026-10-24 | 祝日2026-11-03 | 合計 |
|---|---:|---:|---:|---:|
| 残存便 | 38 | 31 | 31 | 100 |
| tripが小竹向原で終端、氷川台を含まない | 38 | 31 | 31 | 100 |

100件すべてのprimary journeyは別tripへ乗り換える旅程で、池袋発の第一tripは小竹向原が最後の駅。したがって当該GTFS `trip_id` に氷川台イベントがなく、氷川台を「時刻なしで通過した」とは判定できない。これはtrip区間外であり、既存trip内の駅行欠損と区別される。必要駅イベント欠損、駅行はあるが時刻なし、乗降不可、複数種別への該当といった原因に分類される残存便は0件だった。

| 日付 | 路線 | 本数 | 要町・千川 | 小竹向原 | 氷川台 |
|---|---|---:|---|---|---|
| 平日 | 有楽町線 | 18 | 両駅とも時刻あり、pickup=0 / drop_off=0 | 到着・出発時刻あり、乗降可 | trip終端後でイベントなし |
| 平日 | 副都心線 | 17 | 両駅とも時刻あり、pickup=0 / drop_off=0 | 到着・出発時刻あり、乗降可 | trip終端後でイベントなし |
| 平日 | 副都心線 | 3 | 両駅とも時刻なし、pickup=1 / drop_off=1 | 到着・出発時刻あり、乗降可 | trip終端後でイベントなし |
| 土曜 | 有楽町線 | 14 | 両駅とも時刻あり、pickup=0 / drop_off=0 | 到着・出発時刻あり、乗降可 | trip終端後でイベントなし |
| 土曜 | 副都心線 | 11 | 両駅とも時刻あり、pickup=0 / drop_off=0 | 到着・出発時刻あり、乗降可 | trip終端後でイベントなし |
| 土曜 | 副都心線 | 6 | 両駅とも時刻なし、pickup=1 / drop_off=1 | 到着・出発時刻あり、乗降可 | trip終端後でイベントなし |
| 祝日 | 有楽町線 | 14 | 両駅とも時刻あり、pickup=0 / drop_off=0 | 到着・出発時刻あり、乗降可 | trip終端後でイベントなし |
| 祝日 | 副都心線 | 11 | 両駅とも時刻あり、pickup=0 / drop_off=0 | 到着・出発時刻あり、乗降可 | trip終端後でイベントなし |
| 祝日 | 副都心線 | 6 | 両駅とも時刻なし、pickup=1 / drop_off=1 | 到着・出発時刻あり、乗降可 | trip終端後でイベントなし |

「時刻なし・両方乗降不可」はGTFS上の通過根拠であり、要町・千川の15便では明示されている。一方、氷川台と平和台は該当tripの池袋発後のイベント列にないため、時刻・乗降可否は未指定である。停車・通過のどちらにも数えていない。各便の全駅イベント、arrival/departure、pickup/drop-off、候補列車番号は診断JSONに記録する。

#### ODPT ID表記と照合候補

対象100件はすべて現行ルールでは `unmatched`。運行日区分内に現行切り出し番号と一致するODPT便は100件中0件だが、池袋発の秒単位時刻が同一のODPT時刻表レコードは全100件に存在する。うち73件は同時刻候補1件、27件は2件で、時刻単独では同一便を確定しない。

GTFS `trip_id[2:-2]` だけでは、数字部分の先頭ゼロや末尾の運用記号を扱えない。診断用に候補文字列を作り、同一路線・運行日区分・池袋発秒の条件と合わせると、100件すべてでODPT列車番号の候補がちょうど1件となった。さらに、確定ID便から別日で学習したODPT destination ID→GTFS headsign対応を使うと、路線・発車分・行先に合う候補が全100件で一意となった。これは候補検証であり、このターンでは照合実装へ採用していない。

| 対象日 | 一意な番号変形＋秒一致候補 | 一意な発車分＋行先候補 | 候補種別 |
|---|---:|---:|---|
| 平日 | 38/38 | 38/38 | Local 29、Express 3、SemiExpress 4、RapidExpress 2 |
| 土曜 | 31/31 | 31/31 | Local 23、Express 3、F-Liner 3、SemiExpress 2 |
| 祝日 | 31/31 | 31/31 | Local 23、Express 3、F-Liner 3、SemiExpress 2 |

具体例:

- GTFS `61B0565S00`（有楽町線、06:00、小手指行）から現行切り出しした `B0565S` は不一致。時刻候補はODPT `B565S` で、先頭ゼロを除くと一意に一致し、ODPT destination は小手指。
- GTFS `91B0526K20`（副都心線、07:00、清瀬行）からの `B0526K` は不一致。1文字長い `B0526K2` を候補に残し、数字先頭ゼロを除くとODPT `B526K2` に一意一致。ODPT destination は清瀬。
- GTFS `91B0760K00`（副都心線、08:37、小手指行）は候補 `B760K` / ODPT `Express`。祝日側ではGTFS `93B0810M00`（09:09、小手指行）に候補 `B810M` / ODPT `F-Liner` が見つかった。要町・千川は通過根拠だが氷川台イベントがないため、stop pattern単独では両者を分けられない。

診断対象外の一意照合できた879 GTFS便日レコードを候補規則の対照にしたところ、同時刻に列車番号変形候補が一意だったものは879/879でODPTの既知 `odpt:train` と一致した。この対照は既知便での規則整合性を示すが、未照合100便の独立した実ID確認ではない。候補100件には十分な裏付けがある一方、採用時はこの複合条件を明示し、時刻一致だけで確定しないこと。

ODPTの別calendarにも正規化後番号が見つかる便は37/100。現行の切り出し番号そのものが別calendarにある例は0/100。土曜と祝日はサービス区分が同じで、残存31 `trip_id` は全件同一。このため同じ土休日ダイヤの再掲を別日の独立証拠として数えない。

#### 停車パターンだけで回復できる範囲と名称案

氷川台イベントを必要とする現行分類では100件すべて判定不能。一方、要町・千川の両駅に停車した副都心線tripは、検証済み公式停車表でローカルのみが両駅に停車する。該当する残存便は平日17、土曜11、祝日11の計39件である。同じく氷川台で終端するODPT確定対照は、両駅停車が Local 平日26・土休日各30、両駅通過が Express/F-Liner 平日21/12、土休日各6/9で、観測範囲では矛盾0。したがって、対象route 9・両駅の時刻と乗降可否が有効・小竹向原停車の条件を明示するなら、「各駅停車」パターン候補として39便を追加識別できる余地がある。ただしこれはODPT ID照合で得られる原種別を代替せず、既存分類の修正・表示実装は今回行わない。

残りのうち副都心線15便は要町・千川の両方に通過記録があるが、氷川台がtrip区間外で、通勤急行と急行/F-Linerを分ける駅情報がない。停車パターンのみで正確な種別を付けるのは困難。土休日の祝日を含むパターンは同一サービスtripの再掲であり、別運行日の停車記録を追加証拠として利用できない。有楽町線46便は記録された要町・千川・小竹向原が停車だが、氷川台を含む路線全区間の各駅停車証拠ではないため、正式種別名への変換はできない。

- 「急行型」→「急行」は不可。確定対照で同じ通過パターンがExpressだけでなくF-Linerにも該当（平日33件中12件、土休日各15件中9件がF-Liner）。「急行・Fライナー同型」等の補助表示を維持し、F-LinerはODPT確定時のみ愛称属性として付ける。
- 有楽町線の「全駅停車」→「各駅停車」は、現在の判定が4つの代表駅パターンであり、対象tripには小竹向原より先の駅がないため、正式種別名へ一括変更すると「全区間の各駅停車」と誤読される。全区間の駅イベントがそろい、ODPT確定Local以外に誤該当しないことを確認した場合に限り、正式種別でなくメトロ区間の運転形態の説明として「各駅停車」を検討する。

現実的な追加改善は、①trip IDの数字先頭ゼロ・可変末尾を候補化、②路線・service calendar・池袋発秒の一致、③独立したdestination/headsign対応、④候補一意性をすべて満たす場合だけODPT確定属性として採用、⑤確定データ対照と候補衝突診断を保持すること。今回の候補規則では100/100便を一意候補にできるため、理論上はこの3代表日の種別不明を0件にできる見込みだが、これは未照合便自身の第三の独立ID sourceで確認した結果ではない。実装は別作業で検証・承認してから行う。

再現コマンド:

```sh
python3 -B scripts/odpt_phase3_unknown_diagnostics.py \
  --output /private/tmp/dotchi-ikebukuro-unknown-diagnostics.json
```

再現コマンド:

```sh
python3 -B scripts/odpt_phase3_stop_pattern_classifier.py
```

取得済みGTFS ZIPとODPT JSONのみを読み、表示payload・preview・アプリコードへ分類値を書き込まない。公式停車駅表は [副都心線](https://www.tokyometro.jp/station/line_fukutoshin/index.html) と [有楽町線](https://www.tokyometro.jp/station/line_yurakucho/index.html)。

### 列車番号正規化とODPT照合エンジン（2026-10-22）

再利用可能な照合器 [`odpt_train_matcher.py`](../scripts/odpt_train_matcher.py) と再現用 [`validate_odpt_train_matching.py`](../scripts/validate_odpt_train_matching.py) を追加した。正規化は今回のローカルGTFSに観測された形式に限定する。対象1,836 trip_idは全件10文字で、路線番号 `6` / `9`、運行区分接頭部 `0` / `1` = Weekday、`2` / `3` = SaturdayHoliday、列車番号部 `[A-Z][0-9]{4}[A-Z]`、末尾 `00` または `20` で構成される。末尾 `00` はパディングとして外し、唯一の `20` 例外 `91B0526K20` は番号末尾の `2` を残す。数字部分の先頭ゼロだけを追加候補として除去する。`trip_short_name` は同じ列車番号を示す実値ではないため使わない。別フィードの形式や未観測末尾へ一般化しない。

候補一意と照合確定を分けた。確定には、(1) GTFS路線とODPT `odpt:railway`、(2) trip_id運行区分とODPT calendar、(3) 正規化番号、(4) 池袋発の秒単位時刻、(5) 既知照合便から作ったODPT destination ID→GTFS headsign対応、(6) GTFSで時刻・乗降イベントが有効な停車駅順とODPT停車駅順、を要求する。ODPTは通過駅の駅時刻を列挙しないため、GTFSの通過行（両時刻なし・pickup/drop-off=1）を除いた停車列を比較した。数字変形が別のアクティブGTFS tripとも衝突する場合、同時刻ODPT候補が複数の場合、行先・駅順が矛盾する場合、または行先対応が未確立の場合は確定しない。

| 対象 | 旧ID＋時刻照合 | 新照合で確定 | 未確定 |
|---|---:|---:|---:|
| 既知対照便 | 879/879 | 879/879 | 0 |
| 既存「種別不明」100便 | 0/100（旧番号切り出し） | 100/100 | 0 |
| それ以外のID未照合便 | 0/248（旧番号切り出し） | 242/248 | 6 |
| 3代表日のprimary旅程合計 | 879/1,227 = 71.6% | 1,221/1,227 = 99.5% | 6 |

残存「種別不明」便の内訳は、2026-10-22平日38/38、2026-10-24土曜31/31、2026-11-03祝日31/31が確定。これにより照合器を適用すればこの3日分のODPT照合起因の種別不明100件は解消できる見込み。ただし、照合器は現時点で独立したバッチ検証モジュールであり、`ItineraryGenerator`、exporter、UI payload、previewにはまだ接続していない。

追加で確定しなかった6件は土休日ダイヤ上の3 tripが土曜・祝日に重複するもの。GTFSの番号・路線・calendar・池袋発時刻・停車順からODPT候補は1件（`B554K` / `B689S` / `B733S`）だが、ODPT destinationの「小川町」をGTFS headsignへ結ぶ独立対応が保存済みデータから作れなかった。このため `candidate_unconfirmed: destination_has_no_independent_gtfs_crosswalk` とし、候補を確定便として使わない。行先別の追加根拠が得られない限り、現状のまま保留する。

新たに照合できた元種別の内訳（対象100便）は、有楽町線: `Local` 36、`SemiExpress` 8、`RapidExpress` 2、副都心線: `Local` 39、`Express` 9、`F-Liner` 6。既知879便のraw値は有楽町線 `Local` 423 / `SemiExpress` 6 / `Rapid` 5、副都心線 `Local` 317 / `Express` 51 / `CommuterExpress` 14 / `F-Liner` 63。保存JSONのtype URIは全て `odpt.TrainType:TokyoMetro.*` で、ODPT railwayも各東京メトロ路線だが、これだけではthrough-service列車の種別を池袋時点の線内運転種別と確定する適用区間情報にならない。種別モデルは原値・メトロ線内種別・他社線種別・サービス愛称を分離する。副都心線の `Local` / `Express` / `CommuterExpress` は同一路線のODPT時刻表と検証済み停車パターンを照合できる場合にメトロ線内種別として扱える。`F-Liner` は独立したサービス愛称であり、原値のみからメトロ線内の `Express` へ置換しない。今回の6件は愛称を確定できるが、氷川台がGTFS trip区間外のため `metro_line_type` は未設定のままにする。副都心線以外の `Local` / `SemiExpress` / `RapidExpress` / `Rapid` は、ODPT原値を他社線種別と断定する根拠も未確認のため `unscoped_through_service_type` に保持し、池袋でのメトロ種別ラベルには使わない。

自動テストは13件追加し、正規化、`20`末尾例外、路線・運行日区分、正規化衝突、同時刻複数候補、行先・停車順不一致、安全な保留、種別属性分離、既知879件、100件、全primary母集団の未確定6件を検証した。全Python suiteは28件成功。再現コマンド:

```sh
python3 -B scripts/validate_odpt_train_matching.py \
  --output /private/tmp/dotchi-ikebukuro-train-match-report.json
```

レポートは派生情報のみで `/private/tmp` に置き、GTFS ZIP・ODPT生JSON・payloadは出力・Git追加していない。画面への反映は可能だが、次の実装では新照合結果をODPT raw typeとして保持し、行先不明を保留し、路線別種別スコープを検証したうえで既存exporterへ接続する必要がある。今回アプリ・preview表示には変更を加えていない。

### 照合器の旅程生成・payload統合と種別表示（2026-10-22）

上記の未接続状態を今回の実装で更新した。`ItineraryGenerator` は運行日ごとに保存済みODPT JSONの候補索引を作り、`odpt_train_matcher.py` の確定条件を通った便だけから原種別URI・行先・照合方法をpayloadへ渡す。照合不能・行先crosswalk不足の6件（土休日3 tripが土曜/祝日に重複）は引き続き未確定。過去の既知879便は全件回帰一致、追加対象100件も確定し、残り6件以外の242件も候補の根拠を満たした。2026-10-22時点でvalidatorは `known_control:confirmed=879`, `residual_unknown:confirmed=100`, `pattern_classified_unmatched:confirmed=242`, `pattern_classified_unmatched:candidate_unconfirmed=6` を再現する。

種別はraw ODPT値、検証済みメトロ線内種別、他社線内種別候補、適用区間未確認値、Fライナー愛称を別属性で保持する。3代表日のprimary旅程のうち、平日435便ではODPT照合435・ODPT線内種別等を正式表示できるもの426・「種別不明」9。土曜/祝日は各396便中、照合393・ODPT確定の正式表示387・「種別不明」6、照合保留3は「急行型」補助表示を維持する。Fライナーは平日23、土休日24便で愛称として表示し、急行へ置換しない。副都心線の未照合3便の急行型パターンも正式「急行」へ昇格しない。有楽町線の through-service `SemiExpress` / `Rapid` / `RapidExpress` はメトロ線内種別として未確定のため「種別不明」のままとする。有楽町線 `Local` のうち小竹向原までの確認済みメトロ区間が全駅停車となる便は「各駅停車」と表示する。

### 切替レスポンス最適化（2026-10-22）

以前のローカルpreviewは1秒ごとに全payload（3日・1,317池袋発便）を `buildBoard` へ渡し、毎回payload検証、カード生成、日時formatter生成、候補sortを行ってからカードをDOM再生成していた。モード・直通filter切替でも同じ全件処理が走り、同じpayloadを再fetchする動作はなかった。測定済み旧adapter Nodeベンチマーク中央値はモード/filter組合せにより約352–618 ms（p95約513–729 ms）。

adapterに一度だけpayloadを検証してカードを事前生成する `prepareTimetablePayload` を追加し、Intl formatterも共有化。最早着の候補選択を二度目の全sortから一回のreduceへ変更した。previewでは切替時のみ候補・最大6カードを再生成し、毎秒は時計とカード上のカウントダウンだけを更新する。発車時、東京日付変更、payload有効性変更時は候補を再生成。Safariでconsoleから確認できる `window.__dotchiPreviewPerf` はfetch回数、候補走査、sort、adapter全体、selection、DOM更新、イベントからDOM/次frameまでの時間を直近50回保持する。

同じ1,317便payloadをNodeで15回測定（UIと同じonTiming有効）: unprepared payloadはadapter全体の中央値36.47 ms / 最大50.10 ms、候補走査26.89 / 39.52 ms、sort 0.05 / 0.34 ms。事前準備済みpayloadはadapter全体中央値0.88 / 最大4.47 ms、候補走査0.57 / 1.71 ms、sort 0.03 / 0.22 ms。ここで「最大」は15標本の最大値（p95相当の最近順位値）。この数値はSafariの実測ではない。ブラウザー上のイベントからDOM更新までのSafari数値は未取得で、previewは更新済み・サーバ停止の状態。Mac Safariでの再計測手順は `docs/devlog.md` の当日記録を参照。adapter Node test 15件、Python全28件が成功。ローカルpayloadとODPT派生レポートは `/private/tmp/dotchi-ikebukuro-preview/` のみ。

### 有楽町線内の各駅停車表示と種別表現（2026-10-23）

**公式根拠・適用範囲**

- 東京メトロの2010-03-06改正告知は、有楽町線の準急を各駅停車に変更し「有楽町線は全て各駅停車」と説明している（[東京メトロ 2010年ニュースリリース](https://www.tokyometro.jp/news/2010/2010-06.html)、確認日 2026-10-23）。2008年の準急導入告知は過去の運行形態を説明する資料であり、現在の規則として流用しない（[東京メトロ 2008年ニュースリリース](https://www.tokyometro.jp/news/2008/2008-17_2.html)）。
- 2026-03-14の改正資料は現行ダイヤ・S-TRAINの時刻を案内するが、今回の調査範囲では通常列車の全駅停車ルールを撤回する記載は確認できなかった（[東京メトロ改正資料](https://www.tokyometro.jp/info/files/20260314_daiyakaisei.pdf)）。有楽町線S-TRAINは停車駅が限定され、池袋で乗車できない（[東京メトロFAQ](https://ssl.tokyometro.jp/support/faq_answer?faqno=OpenFAQ-007736&lang=ja)）。今回の適用は池袋で乗車する通常営業列車の有楽町線区間に限定し、直通先区間の列車種別を意味しない。
- 公式時刻表の凡例も、東京メトロ線内の種別と直通他社線内の種別を別に扱う（[2023年有楽町線時刻表案内](https://www.tokyometro.jp/notice/20230318/yurakucho/index.html)、[池袋駅時刻表PDF](https://www.tokyometro.jp/notice/20230318/pdf/Y22.pdf)）。2010年の明示資料以降の包括的なルール再掲は確認できていないため、将来のダイヤ改正時に公式資料と対象区間を再確認する。

**実装条件・保留条件**

- `official_route_rule` はODPTのraw種別を上書きせず、別の根拠sourceとして `typeLabel=各駅停車` / 内部type `Local` を付ける。有楽町線GTFS route `6`、ODPT `unique_match`、ODPT線内type未確定かつraw through-service typeあり、池袋で有効に乗車可能、要町 `608`・千川 `607`・小竹向原 `606` の一意で有効な停車記録、順序・時刻整合、S-TRAIN/愛称なし、停車矛盾なしを要求する。
- さらにpreviewに有効な池袋→氷川台旅程がない便は表示対象外として補完しない。今回この条件で安全側に戻る1便を確認した。GTFSに氷川台stopがないこと自体は通過根拠としない。この表示上の追加ゲートは、旅程不能データに表示用種別だけを付けないための保守条件である。
- 照合失敗、ODPT元type欠損、必要停車データ欠損・重複・時刻逆転、S-TRAIN、service brand、その他の矛盾は従来どおり不明または既存表示とする。15対象tripのIDは実装条件にハードコードしていない。

**代表日結果と表示**

- 表示可能な旅程に限る種別不明は、平日9/435→0/435、土曜6/396→0/396、祝日6/396→0/396。補完sourceは各日9/6/6。S-TRAINや無効旅程は補完対象外。ODPT照合状態とraw ODPT type codeは維持する。
- 種別名と行先は別要素に分ける。各駅停車は通常色、急行・通勤急行は太字＋下線、Fライナーは愛称として別の太字破線下線、GTFS停車パターンの急行型/全駅停車は補助表示色と点線下線、種別不明は控えめな色で明示する。最早着の緑色とは別系統で、意味を色だけに依存させない。カード寸法・広告dock・safe-areaは変更していない。
- 公開モックのroot `index.html` / `styles.css` / `app.js` は変更していない。CSSの実機視認性、幅、縦寸法、広告dock、iOS safe areaはMac/iPhone Safariで最終確認する。

### T14 Phase 3.5: 小竹向原乗換候補を5駅へ共通化（2026-10-23）

#### 経路方針と候補条件

目的地カタログの `routePolicy` を使用する。要町・千川・小竹向原は `direct_only`。氷川台・平和台・地下鉄赤塚・地下鉄成増・和光市は `direct_and_kotake_transfer`。5駅の乗換候補は、池袋発のGTFS tripと反対路線の別GTFS tripを同じservice day内で組み合わせる。異なるtripを直通として結合せず、同一車両の継続も推定しない。

新4駅では池袋発tripの小竹向原までについて、stop順・時刻単調性・小竹向原の到着時刻・降車可を検証する。乗換先については小竹向原での出発時刻・乗車可、目的地が小竹向原より下流にあること、途中stop順・時刻単調性、目的地到着時刻・降車可を検証する。明示的通過は除外し、記録欠損・不明な乗降・順序や時刻の矛盾は推測で補わない。待ち時間60〜600秒、池袋発tripごとの最良乗換候補、直通優先と既存の最早着選定は変更していない。

#### 駅構造と接続保証の区別

2026-10-23に東京メトロの[小竹向原駅案内](https://www.tokyometro.jp/station/kotake-mukaihara/index.html)、[バリアフリー設備案内](https://www.tokyometro.jp/station/kotake-mukaihara/accessibility/index.html)、[駅構内図](https://www.tokyometro.jp/station/kotake-mukaihara/yardmap/index_print.html)を確認した。駅案内は有楽町線・副都心線と和光市方面を案内し、バリアフリー情報は1・2番線、3・4番線それぞれのホーム群への経路を示す。ユーザーからは和光市方面下りの3・4番線が同一島式ホームとの情報が提供された。

この駅構造は乗換時の移動を考える材料だが、個々の列車の番線や接続を保証する資料ではない。保存GTFSからは列車別platform、最低乗換時間、接続保証、block_idを確認できない。そのため番線は `unknown`、`connectionGuaranteed=false` を維持し、候補は「時刻表上の乗換候補」とする。60秒は候補抽出の下限であり、接続保証時間ではない。物理的な同一ホームの情報を理由に1〜2分候補を一律除外・保証する変更は行っていない。

#### 件数とデータ状態

`destinationStatus` には直通候補親trip数、乗換候補親trip数（各親tripの最良候補あり）、全有効乗換組数、乗換のみの親trip数、乗換側の明示通過・データ不足を個別記録する。route別にも同じ候補指標を持つ。直通側と乗換側の不足を分け、既存Phase 2の方針に従い候補がある日は有効な候補を利用可能にする。氷川台は既存payloadを保つため以前のstatus shapeのまま。

代表日（2026-10-22平日、2026-10-24土曜、2026-11-03祝日）の順に、平和台・地下鉄赤塚・地下鉄成増は各々:

| 日付 | 直通親trip | 乗換候補親trip | 有効乗換組 | 乗換のみ | primary候補 | 乗換先の明示通過 | 乗換データ不足 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-10-22 | 287 | 417 | 622 | 148 | 435 | 13 | 0 |
| 2026-10-24 | 240 | 366 | 490 | 156 | 396 | 34 | 3 |
| 2026-11-03 | 240 | 366 | 490 | 156 | 396 | 34 | 3 |

和光市:

| 日付 | 直通親trip | 乗換候補親trip | 有効乗換組 | 乗換のみ | primary候補 | 乗換先の明示通過 | 乗換データ不足 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-10-22 | 300 | 419 | 635 | 135 | 435 | 0 | 0 |
| 2026-10-24 | 274 | 378 | 525 | 123 | 397 | 0 | 3 |
| 2026-11-03 | 274 | 378 | 525 | 123 | 397 | 0 | 3 |

土曜・祝日の各3不足は小竹向原乗換に必要なGTFS時刻・乗降記録が利用できない乗換親trip。直通検証は独立して維持され、他の有効候補があるため状態は `normal`。新3駅の明示通過13/34/34は目的地の乗換先tripで確認した件数であり、直通側の通過除外は従来判定のまま。

追加4駅のprimary乗換待ち時間は、1分が平日247・土祝各294、2分が平日124・土祝各66。駅ごとの1分件数は平日、土祝でそれぞれ、平和台・地下鉄赤塚・地下鉄成増が各65/80、和光市52/54。2分は前3駅が各31/18、和光市31/12。乗換の方が直通より早い、または同着となるprimaryは全目的地・全代表日で0件。短時間の乗換候補はすべて乗換のみの池袋発便である。

#### 回帰・Phase 4への引継ぎ

- 旧generatorとの比較で、氷川台、要町、千川、小竹向原の全3代表日payloadは `generatedAt` 以外一致。氷川台の既存保存preview payloadも `generatedAt` 以外一致。
- 新4駅の直通候補射影はPhase 3旧出力と全代表日一致。直通発着、headsign、ODPT raw種別、typeSource、照合結果、駅IDを維持。
- 各乗換は別trip、反対路線、同一service day、60〜600秒、小竹向原の乗降、目的地の停車・到着・降車を検証する。乗換待ちだけから同一車両や現実の接続可能性を判断しない。
- Phase 4では1〜2分候補に対して、時刻表上の乗換候補であること、待ち時間、番線不明、接続保証なしをユーザーが短時間に認識できる説明を評価する。候補選定変更は別仕様として判断する。駅構造を踏まえても60秒一律除外は採用していない。


### Phase 2B-2c-1 GTFS入力基盤（2026-11-04）

`scripts/odpt_gtfs_loader.py` は profile `dotchi.odpt-gtfs.semantic` / `1.0.0` に接続する独立loader。旧新比較・公開判定・結果persistを行わない。根拠は[GTFS Schedule Reference](https://gtfs.org/documentation/schedule/reference/)（確認2026-11-04）。既存Phase 1B ZIP検査を `validate_gtfs_archive` として共有し、raw 128 MiB、member 64 MiB、非圧縮合計256 MiB、圧縮率1,000を維持。entry数128を追加上限とし、重複・flat .txt以外・暗号化・directory/symlink等特殊ファイル・CRC不整合を拒否する。ZIPを展開しない。flat .txt限定は本保存profileの制約であり、GTFS全形式の合法性を判定する規則ではない。

11テーブル（agency/feed_info/routes/stops/trips/stop_times/calendar/calendar_dates/fare_attributes/fare_rules/translations）をUTF-8-sig、strict CSVと引用符検査で解析する。BOM・quoted改行・LF/CRLF/CRを受理し、header重複・欠落、列数差、壊れた引用符、型不正、実在しない日付等を固定codeで拒否する。optional table/columnは一律必須にしない。calendar_datesのみのサービス、single agencyのagency_id省略、空時刻、blank transfersを受理する。missing columnはcellsのkey欠落、空欄は空文字、文字列nullは文字列のまま。`cell_state` はmissing-column/empty/null-equivalent/valueを返し、fare_attributes.transfers空欄のGTFS上のnull相当も識別する。valuesのNoneは解析値なしを示すだけで、cellsを失わない。

日付はISO date文字列、時刻はservice day基準秒（24時超保持）、sequenceは非負整数。整数の連番、文字列trim/大小文字/表記統合、補間、日付・timezone補完はしない。headerは名前順、rowsはtable key順（stop_timesはtrip_id+数値stop_sequence）に整列するが、全cellsと未知列を保持する。CSV物理行順を停車順とはしない。既知enumの未対応値は保持してpartial。未知テーブルは安全検査後のmember bytesをメモリに保持してpartial。追加の処理上限は100万rows/table、integer18桁、時刻hour6桁、CSV fieldはPython csv既定上限。これらは公式GTFS値域の主張ではない。

keyはagency_id、feed_info単一、route_id、stop_id、trip_id、trip_id+numeric stop_sequence、service_id、service_id+date、fare_id。agency_id省略はimplicit keyとしてpartial。既存Phase 2B-1採用文書にはfare_rules/translationsの具体的keyが未記録だったため、以下をloaderの検査候補として明記する。fare_rulesはfare_id+route_id+origin_id+destination_id+contains_id（公式は全fieldによるkey）、translationsはtable_name+field_name+language+record_id+record_sub_id+field_value。optional selectorの列欠落と空欄を保持する。fare_rules候補重複は上書き・除去せず全行保持、件数とpartialを返す。未知列を含むfare_rulesやoptional selector表現を、後続比較でどう同一視するかは未確定でありprofileを無言で変更しない。その他key重複は入力不正。IDの世代間安定性は主張しない。

trips→routes/service、stop_times→trips/stops、parent_station、routes/fare_attributes→agency、fare_rules→fare_attributes/routes/zones、translationsのfield_valueまたはrecord_id/record_sub_idを確認する。single agencyの暗黙参照、optional空参照、検証対象外参照を分離する。shape_id/block_id/level_id、flex、未対応translation target等は範囲外としてpartialを残す。本loaderは限定した構造・参照検証であり、GTFS仕様全条件・運行整合・同一ダイヤ・最新性の証明ではない。

結果contractはodpt-gtfs-input/schemaVersion 1。profile、input hash/bytes/sourceIdentity、members、tables（headers/rows/cells/values/keyFields/recordCount/keyUnique/duplicateKeyCount/unknownColumns/issues）、unsupportedTables、referenceChecks、coverage、固定errorCodesを返す。`load_gtfs(absolute_zip_path, source_record)` はSource契約・sourceId・hash/bytesを照合し、読取前後とparse終了後のbytes/identity変更を拒否する。ZIPのpath traversal/symlinkも拒否。bytesだけのparse_gtfsではsourceIdentity=not-checked。

独立CLI: `python3 -B scripts/odpt_gtfs_loader.py --zip <absolute-zip> --source-record <absolute-source-record-json>`。既存compare-semanticは変更せず、ODPT6件とGTFS not-evaluatedの結果契約も維持。CLIはsource同一性と構造検証、件数、一意性、参照集計、未知列数、固定codeのみを表示。終了0は構造検証完了（partialは明示して許容）、入力・同一性・構造不正と引数不正は2。本文・ID値・原本pathは出力しない。

実GTFS自己検証はhash/bytes一致、11テーブル検出、未知列0、候補key重複0、参照resolved474,507/optional-absent68,061。shape_id/block_idの補助参照未評価によりcoverage partial。約7.842秒、process peak RSS 480,075,776 bytes（約458 MiB、macOS resource計測、Python/結果全体を含む）。原本7件/store8 JSONのhash/byte数は前後一致。異世代GTFS比較は未実施。


### Phase 2B-2c-2 GTFS運行系6テーブル比較（2026-11-04）

`scripts/odpt_gtfs_semantic_diff.py` を追加し、profile `dotchi.odpt-gtfs.semantic` / `1.0.0` と既存semantic diff contract/schemaVersionを維持する。routes/stops/trips/stop_times/calendar/calendar_datesのみ比較し、agency/feed_info/fare_attributes/fare_rules/translationsは意味比較not-evaluated。feed_infoの期間は評価範囲指定だけに使う。既存ODPT6 source比較とcompare-semantic CLIは変更しない。新CLIはODPT比較結果を再利用して固定7 sourceResultsへGTFS結果を組み込み、確定した差分と未評価・曖昧性を保持する。GTFS coverageと全体coverageはpartial、全体semanticStatusは常にindeterminate。

入力は両storeと両原本directoryを明示する。既存store reader・Phase 2A基本差分・ODPT6 source比較の14原本検証を再利用し、全7 sourceのhash/bytesとidentityを確認してから旧新GTFS loaderを実行する。比較後も14原本と両storeを再検証し、欠落・不一致・読取/比較中変更は固定error codeで失敗する。旧原本を現行原本で代用しない。

各tableの既存loader keyで対応付け、header/columnの存在、record追加削除、全既知属性、未知列の値を比較する。stop_timesはtrip_id+数値stop_sequenceを使い、時刻はservice day秒として比較、両側が既知時刻ならdeltaSecondsを記録する。空セルとmissing columnを区別し、24時超、停車駅・sequence、停車順の意味を保持する。pickup/dropoff/timepoint等も比較する。未知列や未対応enumはpartialとしてunsupported-field-changeを記録する。raw値は結果に複製せず、recordKey・fieldPath・状態と分類だけを保持する。

Calendarは元record差分と有効運行日差分を別に保持する。両feed期間のunionRangesと共通期間を返し、片側期間外はnot-evaluated、共通期間がなければno-common-periodとする。共通期間内ではcalendarの曜日/rangeにcalendar_dates例外を優先適用し、service_id×serviceDateの追加・削除を記録する。片側に定義のないservice_idはその側に当該serviceがないという比較事実として扱い、別IDへ結合しない。feed期間欠損は推定せずpartial。最大3,660日かつ100万service-date組で、上限超過時は展開せずpartial/indeterminate。未対応曜日/例外値も未確定として保持する。

route_id/stop_id/trip_id変更は削除・追加が基本。他の全比較属性が厳密一致し、双方向一意かつ未知field/enumがない場合だけpossible-identifier-changeを付記する。service_id候補はcalendarとcalendar_datesを合わせた全recordパターン一致を要求する。一意でも同一対象と確定しない。複数候補・対応できないID/参照連鎖変更はambiguous-change。同じIDで路線/運行日/駅参照等が変わる場合はsuspected-identifier-reuseを別記する。

表現差は根拠を限定する。全member bytesのhashが同一ならZIPコンテナ差を記録できるが、全体意味同値とはしない。対象tableの全rawセルとheader集合が同一ならCSV表現差を分類する。headerと各rowの正確な引用符・改行を含むlexical multisetが同一ならcsv-record-order-only、解析後物理行順が同じならcsv-format-only、両方変化ならcsv-format-and-record-order。数値等の正規化でだけ一致するものはnormalized-value-representationとして区別する。差を説明できない場合は表現差のみと断定しない。残る5tableはmember bytes照合以外の意味比較をしない。

GTFS findings/ambiguitiesは合計1,000件まで保持し、全件のtable集計と分類件数、totalDetails/omittedDetailsを維持する。打切りは明示し、table detailComplete=false、coverage partial/semanticStatus indeterminateとする。並びと比較事実は決定的、時間/RSS計測値は再実行で変わる。結果persistなし。

CLI: `python3 -B scripts/odpt_gtfs_semantic_diff.py --baseline-store <absolute-store> --candidate-store <absolute-store> --baseline-source-dir <absolute-raw-dir> --candidate-source-dir <absolute-raw-dir>`。差分件数・coverage・未評価table・calendar状態・固定code・計測値のみ表示する。入力/構造/同一性不正、Calendar評価不能・上限、詳細打切りは終了2。対象範囲の比較完了は差分の有無によらず0（意図した5table未評価や保持された未知fieldによるpartialは明示して許容）。既存CLIの終了コードは変更しない。

実自己比較QAでは6tableがcomplete/equivalent、変更0、GTFS partial/全体indeterminate、未評価5table。共通期間2026-09-19〜2027-03-12、350 service-date組、運行有無差0。原本7件/store8 JSON計15ファイルのhash/bytesは前後一致。旧/新解析・compact化・表現検査各14.871秒、比較3.083秒、全体37.861秒、peak RSS584,773,632 bytes（macOS、約558 MiB）。findings/ambiguities/打切りはいずれも0。loaderのshape/block補助関係未評価も保持する。両世代を同時に保持する前にloaderのcellsと未評価5tableの解析recordを解放し、比較には対象6tableの正規化recordと表現証拠hashだけを残す。今後は表現検査とloaderの二重CSV走査の共有化が最適化候補だが、今回は大規模変更しない。これは自己比較であり実世代間QAではない。


### Phase 2B-2c-3 GTFS全11テーブルと7 source統合（2026-11-04）

profile `dotchi.odpt-gtfs.semantic` / `1.0.0`、semantic diff contract/schemaVersion 1を維持する。新 `scripts/odpt_semantic_compare.py` が既存比較を再利用し、ODPT6 sourceとGTFS11テーブルを統合する。従来のcompare-semantic（ODPT6件）とodpt_gtfs_semantic_diff.py既定CLI（GTFS主要6テーブル）は対象・終了コードを変えない。拡張は明示的なall_tables=True経路のみ。今回鮮度、公開資格、source間同一ダイヤ、結果persistを実装しない。

agencyはagency_id、feed_infoは単一record、fare_attributesはfare_idで対応付け、既知optional属性を含む全値を比較する。feed version/publisher/language/収録期間の変更は記録するがapplicationPeriodへ転記しない。欠落columnと空cell、未知列・enumを保持し、既知差分を消さずpartialとする。

fare_rulesとtranslationsのkey候補を[GTFS公式Reference](https://gtfs.org/documentation/schedule/reference/)の定義と照合した（2026-11-04）。fare_rulesは全fieldのkey（標準fieldはfare_id/route_id/origin_id/destination_id/contains_id）、translationsはtable_name/field_name/language/record_id/record_sub_id/field_value。異なるroute/zoneのfare行やrecord指定・field_value指定の翻訳ルール併存は正当に表現できる。完全に同じ公式keyの重複を正当と認定はしないが、拡張列やselectorによる曖昧性を調べるため新統合経路は全行保持の監査を許容する。loader既定のtranslations重複拒否は維持し、明示preserve_selector_duplicates=Trueのときだけtranslation_key_ambiguous/validity not-confirmedとして保持する。既存profileを黙って一意化・変更しない。

両tableの候補keyはoptional selectorの存在bitと空/値の状態を含む。行順はルールの識別順ではなく、多重集合として完全な正規化rowの一致分を個数付きで差し引く。候補keyが両側で一意ならfield差分を検出する。複数行groupは不変でもambiguous/partialとし、対応を確定せず残差の追加・削除を記録する。重複除去やlast-write上書きはしない。record_idとfield_value指定の優先関係は公式仕様に存在するが、今回その適用後の表示意味は解決せず、混在groupをtranslation_precedence_not_evaluatedとしてpartialにする。stop_timesの数値record_sub_id表記aliasも検出してpartial、推測統合しない。

GTFS tableResultsは11件。各tableにcoverage/semanticStatus、added/removed/modified/ambiguous等のcounts、categories/categoryCounts、checks、findings、ambiguities、unsupportedFields、detailCompleteを保持する。source coverageは全11件に加えloaderの未評価補助関係、Calendar範囲評価、曖昧性・打切りを集約して決める。shape_id/block_id関係は既知ID値を比較できても意味解決済みとはせず、tripsとGTFS全体をpartialとする。詳細はGTFS findings+ambiguities合計1,000件、ODPTは各既存上限を維持し、集計と打切り件数は失わない。

固定7 sourceを単一結果へ統合する。各sourceのcoverage/status/categories/counts/ambiguities/unsupportedFields/checks、topのconfirmedChanges/checks/errorCodesを返す。比較完了範囲ではcomplete/equivalentまたはchanged、未解明・未評価・曖昧・上限ならpartial/indeterminate、意味parse失敗ならfailed/indeterminate。入力bytes/契約が成立した後の一方の意味比較失敗でも他sourceの確定結果を残す。失敗sourceはcountsKnown=false/confirmedChanges=nullとし無差分としない。bytes不一致・store不正等は固定codeで比較失敗。crossSourceConsistencyはnot-evaluated。profile外の鮮度・旅程品質・公開資格はnotEvaluatedに明示し、比較完了をそれらの保証に読み替えない。

新CLI: `python3 -B scripts/odpt_semantic_compare.py --baseline-store <absolute-store> --candidate-store <absolute-store> --baseline-source-dir <absolute-raw-dir> --candidate-source-dir <absolute-raw-dir>`。7 source/11tableの状態・分類・件数・checks・固定理由codeと時間/RSSを表示し、raw値・record key/field値・秘密情報は出力しない。終了0は差分あり/なしを問わず、部分評価の理由を明示した比較結果の生成完了。入力異常・意味parse失敗・詳細上限・Calendar評価不能/上限は2。既存CLIは変更しない。

実自己比較で7 sourceとも既知差分0。Railway/Station/TrainTimetable2件はcomplete/equivalent、StationTimetable2件はopaque keyでpartial/indeterminate。GTFS11tableすべて比較成立、tripsだけ補助関係でpartial、他10件complete。GTFSと全体はpartial/indeterminate。原本7件/store8 JSONのhash/byte数前後一致。旧解析17.022秒、新16.262秒、比較4.283秒、全体44.614秒、peak RSS621,150,208 bytes（約592.4 MiB、macOS）。cellsを解放しながら正規化record/groupだけを保持し、原本・解析結果の余分な複製は避けた。大規模リファクタリングなし。実世代間の検証実績ではない。


### Phase 2C-1採用契約とPhase 2C-2a入力検証（2026-11-04）

品質比較はPhase 2B意味比較から独立し、(1) generator生成行、(2) v2射影・検証後の表示候補、(3) adapterの画面モデルの3段階を分ける。旧新は同じ凍結engine・同じcontextで再計算し、古いQA値はbaselineに流用しない。将来のmetricは駅日路線を基本単位とし、生成行G、候補C、除外E、primary直通/乗換、alternatives、接続組数を混同しない。G=C+E、C=primary直通+primary乗換を検査し、照合率は対象母集団の分子/分母付きとする。scheduledTripCountはactiveな路線全GTFS tripであり生成行と異なる。8目的地の重複を独立列車数として数えない。欠損・対象外はnull/理由付きで0件としない。照合のcandidate_unconfirmed集約前や第2legの品質計測は後続。

将来の品質差分はdotchi.odpt.itinerary-quality-diff/schemaVersion 1を予定し、Snapshot ID/fingerprint、evaluationContext、engine fingerprints、両metrics、metricDiffs、findings、checks、comparisonStatus、notEvaluatedを持たせる。条件不一致なら差分を作らず、部分評価でも既知差分は保持する。候補増減、特定駅路線消失、照合率低下、UNKNOWN/WARNING、coverage遷移、時刻/待ち時間矛盾、終電・始発/最早着の影響を区別し、根拠のない閾値や品質PASSによる鮮度・公開資格付与はしない。Phase 2Bのopaque key/GTFS補助関係等も解決扱いしない。今回このmetrics/差分契約の処理は実装しない。

実装は `scripts/odpt_quality_input.py`。context contract=odpt-quality-evaluation-context/schemaVersion 1、profile=dotchi.odpt.itinerary-quality/0.1.0-draft。初期serviceDatesは2026-10-28/29/30、auxiliaryServiceDates=[]、既存8 station ID、origin=Ikebukuro、routeIds=["6","9"]。direction=ikebukuro-outbound-order-v1、originStopIdsByRouteは6:[228,609]、9:[228,909]（IDは文字列）。既存コードのliteral定義をASTで読み、station mapping/route別originとの一致を検証する。推測した駅名変換やroute/方向の補完はしない。要町/千川/小竹向原はdirect-only、残り5駅はdirect-and-opposite-route-transfer、transferStationId=KotakeMukaihara、minimumWaitSeconds=60、maximumWaitSeconds=3600、crossServiceDateSearch=false。profileではminは60固定、maxは60〜3600の明示値を受け付け、600と3600を同じ条件としない。

primaryRule=arrival-direct-wait-second-trip-id-v1（到着最早、直通優先、待ち時間、second-leg trip ID順）。observationInstants/displayScenariosは必須の配列だが初期は空、displayEvaluation=not-evaluated。将来予約値は実在するUTC秒形式YYYY-MM-DDTHH:MM:SSZ、scenarioはid/mode/directOnly/horizonSeconds/lineLimit/departureLimitを検証する。mode=line/departure、horizon=86400、lineLimit=3、departureLimit=6。今回は表示を実行せず、観測日に必要な日付closureやfeed運行可用性も未評価とする。

contextは未知key/重複JSON key/NaN等、型差（boolとintを含む）、不正な日付・駅・路線・wait等を拒否する。serviceDates/auxiliaryServiceDates/stationIds/routeIds/observationInstantsとorigin stop ID配列は重複禁止の集合としてsort、displayScenariosは一意idでsortする。service/aux日付は重複不可。JSON object keyをsort、UTF-8・ensure_ascii=false・compact separators・NaN禁止でcanonical bytesを作り、contextFingerprint自身だけを除外してSHA-256。engineFingerprint参照も含む。時刻・mtime・観測時の実時計・run metadataは含めず、未知run fieldは拒否する。比較はidentical/different/insufficient/invalidを区別し、不足・差異はincomparable、改ざん・不正はinvalidとする。

engine rootsはitinerary/train matcher/stop-pattern/v2 projector+validator/QA分類/exporter/QA-state変換prepare/JS adapter/新入力validator。ASTで通常・関数内import、静的__import__を追い、JSのローカルimportも追跡する。既存QA fingerprintのmatcher漏れを補い、source reader等への間接依存を含めた現行集合は15ファイル: odpt_itinerary.py、odpt_train_matcher.py、odpt_stop_patterns.py、odpt_public_v2.py、odpt_snapshot_qa.py、export_local_timetable_payload.py、prepare_odpt_v2_qa.py、_local_preview/odpt_v2_qa_adapter.mjs、odpt_quality_input.py、odpt_source_contract.py、odpt_source_store.py、odpt_source_inventory.py、odpt_source_diff.py、odpt_source_compat.py、odpt_train_semantic_diff.py（Pythonはscripts/配下）。未知の動的importや解決不能依存はreadyにしない。HTML/CSS/DOM wrapperは画面モデルの依存範囲外で、browser visual QAは未評価。

engine manifestはcontract=odpt-quality-engine/schemaVersion 1。論理path順にsha256/sizeBytesを並べ、AST由来station mappingとそのfingerprint、environmentをcanonical JSONに含めてengineFingerprintを計算する。自身のfingerprintだけ除外。baseline/candidateのmanifest整合と現在の依存集合・bytes・mapping・environment一致を検証し、開始/終了にengineを再走査する。ファイルの欠落/読取不可はunavailable、既存凍結manifestとの内容差や実行中変更はincomparable、manifest改ざんはinvalid。既存公開用fingerprintの定義は変更しない。

environmentはCPython implementation/full version/cache tag/binary SHA、Node binary SHA・process.versions（Node/V8/ICU/CLDR/tz等）・platform/arch、en-GB/en-CA+Asia/TokyoのIntl resolvedOptions、OS release/machine/libc/byteorder、Python timezone DB内のAsia/Tokyoと取得可能なtzdata.ziのhash。非決定的なプロセスID・時計・絶対インストールpathは含めない。全recorded値の厳密一致を要求し、差の影響を推定して許可しない。Nodeまたはtimezone根拠が取得不能ならunavailable。これはNodeで将来adapterを評価する環境の根拠で、実ブラウザー環境の評価ではない。OS/標準library全binaryの完全な環境再現を証明するものでもない。

入力は両側storeと対応原本directoryを明示し、Phase 1C readerがSource/Snapshot契約、7件、record参照、contentFingerprintを検証する。固定sourceId↔filenameで14原本をSource artifactのSHA-256/bytesへ照合し、通常file性/symlink/traversal/読取identity（device/inode/size/mtime/ctime）を検査。終了時も全原本とstoreを再検証する。JSON/GTFS意味解析は行わず、品質用の原本代用・複製・生成をしない。

結果はodpt-quality-input-validation/schemaVersion 1。profile、両evaluationContext/contextFingerprint、両側+現在engineFingerprint、environment、両Snapshot ID/contentFingerprint、inputChecks、comparisonReadiness、固定reasonCodes、notEvaluatedをメモリに返す。readinessはready/incomparable/invalid/unavailable、不正>利用不能>条件不一致の優先順。readyはこの呼出しの入力・条件一致であり、後続実行中の凍結/再検証は2C-2b以降でも必要。metrics、feed/service可用性、表示、鮮度、公開資格等は生成・判定しない。

CLI: `python3 -B scripts/odpt_quality_input.py --baseline-store <absolute-store> --candidate-store <absolute-store> --baseline-source-dir <absolute-raw-dir> --candidate-source-dir <absolute-raw-dir>`。context/engine file無指定では現在のengineと明示した初期QA contextをメモリに構成する。--baseline-context/--candidate-context、--baseline-engine/--candidate-engineで既存のprivate JSONも明示できる。一方だけ指定した場合は他方を自動補完しない。出力はreadiness・設定/fingerprint/契約check要約・固定code・metrics未評価のみ。0=ready、2=incomparable（argparse引数不正も2）、3=invalid、4=unavailable。永続化なし。

実自己検証は既存Phase 1C store/原本でready、context identical、engine PASS、両側7原本/契約/fingerprint/終了時check PASS、reasonCodesなし。原本7件/store8 JSONのhash/bytes前後一致。Node24.15.0/ICU78.2/CPythonで約6.879秒（engine/env走査含む）。旅程生成・品質metrics・表示モデル実行なし。後続は2C-2bで単一Snapshot metrics、2C-2cで同一engine/contextの両側比較、2C-3で固定clock/filterのadapterモデルを実装する。既存gate・synthetic/public経路は維持する。

### Phase 2C-2b-1 単一Snapshotの基本metrics（2026-11-04）

独立read-only `scripts/odpt_quality_metrics.py` を追加。profileは `dotchi.odpt.itinerary-quality` / `0.1.0-draft`。`collect_metrics(store, source_dir, context=..., engine=...)` は単一SnapshotをPhase 2C-2a validatorの両側へ同じ入力として渡し、比較・差分は作らない。Source/Snapshot契約、原本7件のhash/bytes、context、現在engineと環境を開始・終了に検証する。さらに原本7件/store8件のSHA-256・byte数とdevice/inode/size/mtime/ctimeを開始前・終了後で照合し、JSON整形だけのstore変更も検出する。collector自身をengine rootsに追加し、現在の依存集合は16ファイル。既存公開用fingerprint/gateは変更しない。

既定contextは2026-10-28〜30、池袋発、既存8駅、出発routeId 6=有楽町線・9=副都心線（GTFS内部IDも同じ文字列）、wait60〜3600秒、crossServiceDateSearch=false。各駅で既存ItineraryGeneratorを使い、日別の返却行を出発路線別に分ける。生成を繰り返して乗換接続を再計算する独自ロジックは持たない。48セルを基本とし、配列順はserviceDate・stationId・routeId・metricId。

| metricId | 計測値と母集団 | unit |
|---|---|---|
| G | generator返却行すべて。到達不能・除外予定を含む | generated-rows |
| C | 既存v2 `_public_departure` で射影された候補行 | candidate-rows |
| E | 射影がNoneになった行を1行ずつ実測 | excluded-rows |
| primaryDirectCount / primaryTransferCount | Cのprimary.kind別件数 | candidate-rows |
| exclusionReasonCounts | 既存 `_exclusion_detail` の排他的な6理由別実測件数 | excluded-rows-by-reason |
| alternativeDirectRowCount | Gのdirect_alternativeが存在する行数。primary直通の行も含む | generated-rows |
| bestTransferRowCount | Gのbest_transfer_alternativeが存在する行数。primaryと独立 | generated-rows |
| validTransferPairCount | Gのtransfer_candidates_countの合計。最良1候補へ絞る前の有効接続組数 | transfer-pairs |

補助3指標はgeneratorの既存fieldから直接取得する。field欠落・接続組数の型/値不正はunavailable/nullと理由を記録し、推定や再探索はしない。空の評価可能セルはknown/0。各metricはmetricId/dimensions（snapshotId/serviceDate/stationId/routeId）/availability/value/unit/reasonCodes/evidenceRefsを持つ。availability語彙はknown/unavailable/out-of-range/not-applicable/failed（この工程ではnot-applicableを生成する対象なし）。不明値はnull。日付期間外はout-of-range、generator/射影例外はfailed。射影失敗でもGと取得できた補助指標、他セルの確定値を保持する。

セルごとにG=C+E、C=primaryDirect+primaryTransfer、E=除外理由の実測合計を検査する。不一致はfindingに残し補正しない。EをG-Cから求めない。v2既存のsignature/public ID helperを使って重複・衝突も検出する。既存公開gate、routeCoverage判定、matcher集計、UNKNOWN/WARNING分類別詳細、画面モデルは実行しない。除外理由に既存quality_warning等が含まれることと、診断詳細の品質評価は別である。

結果contractはodpt-itinerary-quality-collection/schemaVersion 1。profile、Snapshot ID/contentFingerprint、evaluationContext/contextFingerprint、engineFingerprint、metrics、checks、findings、notEvaluated、collectionStatusを返す。全体は常にpartialまたはfailedでcompleteを付けない。basicMetricsStatus=collectedはこの9指標の収集と算術検査だけが成立した意味。セル評価不能・指標欠損・算術不一致があればbasicMetricsStatus=partial。全体入力・engineの不一致/実行中変更ならfailedとし、当該Snapshotの確定値として扱えない全metricをfailed/nullにする。結果に時計・処理時間・RSSを混ぜず決定性を保ち、レポート/payload/旅程本文を永続化しない。

CLI: `python3 -B scripts/odpt_quality_metrics.py --store <absolute-store> --source-dir <absolute-source-dir>`。現在engineと初期contextをメモリに作り、対象日付・8駅・路線、knownなセルだけの各合計とknownセル数、全セル数/評価不能数、算術check件数、未評価項目、collectionStatus、入力前後不変、時間/RSSを表示する。合計は駅日路線の延べ行/接続組数であり、route6/9や8目的地を跨ぐ独立列車数ではない。全値不明なら合計もnullで0にしない。CLI終了0=基本metrics収集成立（全体partial）、2=部分収集/整合不一致/engine条件不一致/引数不正、3=入力不正・変更、4=入力/環境利用不能。raw source・旅程本文・列車IDは出力しない。

実source非公開QAは既存Phase 1C store（snapshotId `33af11c1-60f6-47fd-993a-94aa8b469cb1`、contentFingerprint `9392342c929297f98c1e8124a563e13dc35764c0f19df17454e11870d3196c6d`）と対応原本7件を利用。全48セル・432 metricsがknown、評価不能0、findings0。延べG=10,536、C=10,128、E=408、primary直通7,887/乗換2,241。補助指標はdirect alternative行7,887、best transfer行6,570、有効接続組50,772。除外理由はexplicit_pass_info=408、他5理由は各known/0（要町・千川の副都心線で各204、3日合計）。各日16セルのG=3,512/C=3,376/E=136、直通2,629/乗換747。出発route6の3日・8駅合計はG=5,256/C=5,256/E=0、route9はG=5,280/C=4,872/E=408。これらは延べ行であり独立列車数ではない。

G=C+E、C=直通+乗換、E=理由合計をそれぞれ48セル、合計144 checksでPASS。開始・終了のcontext identical、engine/env、Source/Snapshot契約・hash/bytesともPASS。collectionStatus=partial/basicMetricsStatus=collected、CLI終了0。レポートはメモリ内のみ。最終実行は46.558秒（独立した外側の前後inventory照合も含む）、process peak RSS363,638,784 bytes（約346.8 MiB、macOS）。原本7件/store8件の全15ファイルについて、collector内と独立照合の両方でSHA-256・byte数・identity前後一致。最終engineFingerprintは `ac072b0989e44e6ced288a0a05cbddaad9068b3e8f3108941fc7ba736e71d101`、contextFingerprintは `310f7ccd8e8ff892dbfffba5a03055fc5bd12cd5ace77bd8c5972ab3626c5735`。品質PASS・鮮度・公開資格の判定は行わない。

### Phase 2C-2b-2 単一Snapshotの詳細品質metrics（2026-11-04）

`odpt_quality_metrics.py` を拡張し、非公開 `odpt_quality_details.py` を追加。profile/contract/schemaVersionは前工程を維持し、generator生成行とv2射影候補の2段階だけを計測する。基本9指標・48セル・G/C/E実測と144算術checksは維持。各metricにnullable numerator/denominatorを追加する。追加98指標と基本9指標で107/cell、48セルなら5,136 entries。serviceDate・stationId・routeId・metricId順。全体はpartial/failedだけで、基本/詳細のcollectedは収集成立を表し品質PASSとはしない。Phase 2Bの意味比較状態とは独立。

**raw matcherと区間母集団:** collectorだけが使うObservingGeneratorは既存generatorの派生クラス。既存_enrichへ渡すmatcherをread-only proxyで包み、実matchを同じ引数で1回呼び、同じMatchResultを返してstatusだけを観測する。通常のItineraryGeneratorには観測処理を追加せず、判定・戻り値・公開DTO・payload・公開fingerprint/gateを変更しない。generator/matcher本体も未変更。matcherのnative statusはconfirmed/ambiguous/unmatched/unavailable/candidate_unconfirmed。profileのrawStatusCountsではnative confirmedだけをunique_matchという名称へ対応付け、nativeRawStatusCountsも別に保持する。candidate_unconfirmed→generator unmatchedの集約は既存_enrichの実結果から独立に記録する。matcherが呼ばれていない場合はraw unavailableと推測せず、raw指標自体をunavailable/null、理由raw_match_not_observedとする。実際に返ったunavailableはknownなraw状態である。

母集団はgenerated.firstLeg（G全行の出発trip）、primary.firstLeg/secondLeg（射影できたprimary）、bestTransferAlternative.firstLeg/secondLeg（Gに保持された最良乗換alternative）。primary第1区間は直通も含み、第2区間は乗換のみ。alternativeとprimaryを合算しない。全有効接続組の各leg品質は未評価で、前工程のvalidTransferPairCountをその代用にしない。照合を再実行して状態を推定しない。

各母集団にreferences/uniqueを設け、matcher.<population>.<counting>.<field>というmetricIdを使う。fieldはtargetCount、rawObservedTargetCount、rawStatusCounts、nativeRawStatusCounts、observedRawStatusCounts、aggregatedStatusCounts、rawMatchRate、aggregatedMatchRate。uniqueは同一Snapshot・セル内のserviceDate+routeId+GTFS tripIdで重複を除く。第2区間を複数親行が参照すればreferencesには各参照、uniqueには1対象を数える。tripIdの世代間安定性は仮定しない。異なるセルのunique件数の和はセル別一意数の延べ合計であり、Snapshot全体の独立列車数ではない。

照合率はunique_match対象数/全照合対象数で、ambiguous/unmatched/unavailable/candidate_unconfirmedも分母に含む。全raw根拠が揃わない率はunavailable/nullとし、rawObservedTargetCountとobservedRawStatusCountsに確認できた観測分を保持する。分母0はnumerator=0/denominator=0/value=null、reasonCodes=[zero_denominator]。評価可能な対象件数0や状態件数0はknown/0。leg根拠がない場合はunavailable/nullで推定しない。

**診断の別体系:** diagnostics.itinerary.INFO/WARNING、diagnostics.generatorMatchStates、diagnostics.v2Exclusions.INFO/WARNING/UNKNOWN、diagnostics.v2ValidatorRows/Cellを個別保持する。itineraryは既存_classify_diagnosticsの分類を使い、元data_qualityのcode出現を数える。繰り返しcodeのoccurrencesとcodeを持つ生成行数を区別し、1行の複数codeもaffectedGeneratedRowCountでは1行とする。各codeに発生数・影響行数・対象セル・availability/reasonCodesを記録する。v2除外は既存_exclusion_detailの排他的分類を使い、UNKNOWNとWARNINGを合算しない。generator照合状態をQA warningへ読み替えない。

既存validate_v2_payloadを、固定時刻のメモリ内診断envelope（実routeCoverage、射影行、既存public ID）で呼ぶ。公開bundle gateは呼ばない。Rowsは候補1行ごとのprobe、Cellはセル内候補全体のprobeで、validatorは各probeで最初のerrorを返す。両probe件数を合算せず、最初のerror以降は未評価と明記。位置indexだけを除いた安定codeを保持し、本文・IDを出力しない。Cell errorから影響生成行を特定できない場合はその行数をnull/unavailableとし、セル数やprobe数で代用しない。validator errorはfindingにも記録するが、既知のエラー収集を品質PASSや公開資格へ変換しない。

**routeCoverage:** 既存_route_stateのdataStateをそのままrouteCoverage.v2DataStateへ記録する。routeCoverageにはrouteId/dataState/実scheduledTripCount/originEvidence（originTripCount/dataInsufficientCount/transferDataInsufficientCount）/coverageClassificationを保持する。scheduledTripCountはactiveな路線全GTFS tripでGではない。元metadataが欠けた場合、v2内部の0 fallbackを実測scheduled=0として扱わず、routeCoverageはunavailable/null、v2状態はunknownのままにする。期間外はout-of-range。feed内で既存active_service_idsが空ならno-active-service、active serviceはあるが当該route scheduleが0ならno-scheduled-route-service、scheduled>0で対象方面の生成行なしならno-origin-direction-candidates。これらは保存calendar上の状態であり実運休保証ではない。data不足/行数不一致/QA warning/集約照合未解決を既存根拠から列挙し、data-insufficientへ分類する。根拠不足を正常運休へ補完しない。

**種別・行先:** 射影候補に対しtype_resolutionを再利用する。odpt_confirmed/official_route_ruleでMetro train_typeとラベルが確定した行をtrainTypeConfirmedCount、gtfs_stop_patternをtrainTypeAuxiliaryCount、それ以外の未確定をtrainTypeUnknownCountとして分ける。service brandだけのFライナー等はMetro種別不明へ含め、serviceBrandOnlyCountも別記。typeResolutionSourceCountsを保持する。行先は既存headsignが空/欠損ならdestinationMissingCount、nonblankかつunique_matchで既存ODPT destination根拠もあればdestinationConfirmedCount、それ以外のnonblankをdestinationUnknownCountとする。単に文字列があることを照合確定とはしない。出力ラベルは一切変えない。根拠field欠落は当該品質指標をunavailable/nullにする。

**整合・部分評価・CLI:** 基本checksと別に、種別/行先3分類の和=C、raw/native/集約状態数=対象数、観測数と状態数、一意数≤延べ数、率の分子分母を検査する（77 checks/cell）。不一致は補正せずfinding。局所的な指標欠損でも他の既知値を保持し、基本と詳細の収集statusを分離する。原本/store/engineの全体binding不正・変更時は全metricsをfailed/nullにし分子分母も確定しない。engine依存へdetailsを追加し現在17ファイル。CLI引数は--store/--source-dirを維持し、基本集計・詳細指標のknownセル数と評価不能数、加重分子/分母による率、各別体系、coverage/種別/行先、checksと状態を表示する。率の単純平均や駅別unique件数の全体一意化はしない。終了0は基本・詳細の計測成立、2は部分/不整合/条件不一致、3は入力不正/変更、4は利用不能。既知の品質問題があっても収集成立なら0となり得る。レポートはメモリのみで、raw source/旅程本文/秘密情報/IDを出力・保存しない。

実source非公開QA（既存Phase 1C storeと対応7原本、2026-10-28〜30/8駅/route6・9）では、基本G=10,536/C=10,128/E=408、primary直通7,887/乗換2,241を維持。Eはexplicit_pass_info408、他5理由はknown/0。以下の「一意」はセル内一意対象数の延べ合計であり、全駅を跨ぐ独立列車数ではない。全母集団でnative raw confirmed（profile raw unique_match）と集約unique_matchのみを観測し、ambiguous/unmatched/unavailable/candidate_unconfirmedは各known/0。raw/集約の照合率はいずれも表の対象数/同数=100%。

| 母集団 | 延べ参照の分子/分母 | セル内一意の分子/分母 |
|---|---:|---:|
| generated.firstLeg | 10,536/10,536 | 10,536/10,536 |
| primary.firstLeg | 10,128/10,128 | 10,128/10,128 |
| primary.secondLeg | 2,241/2,241 | 2,196/2,196 |
| bestTransferAlternative.firstLeg | 6,570/6,570 | 6,570/6,570 |
| bestTransferAlternative.secondLeg | 6,570/6,570 | 3,726/3,726 |

itinerary INFOは681 occurrences/564生成行。内訳はdestination_explicit_pass564、destination_alighting_prohibited39、destination_arrival_missing39、direct_arrival_unavailable39。itinerary WARNING0、v2除外INFO408/UNKNOWN0/WARNING0、Rows/Cell validator error各0で、別体系のまま保持した。routeCoverageはcomplete48/insufficient0/unknown0、分類complete48。種別は正式Metro種別確定9,696/補助0/未確定432。未確定432はすべて愛称だけのservice brand行で、表示ラベルの欠損432件を意味しない。type resolution sourceはodpt_confirmed9,888/official_route_rule240。行先は確定10,128/欠損0/不明0。

全5,136 metricsがknown、unavailable/部分評価metric0。基本144・詳細3,696 checksがPASS、finding0。分母0の率は既定どおりnullであり、0件の対象数・状態数と区別する。collectionStatus partial、basicMetricsStatus/detailedMetricsStatus collected。画面モデル、全有効接続組の各leg品質、セルを跨ぐ一意母集団、各validator probeの最初のerror以降、鮮度・公開資格は未評価。

最終の実source CLI終了0。collector自身の計測は55.337秒、process peak RSS402,907,136 bytes（約384.2 MiB、macOS、呼出側のメモリ内stdout捕捉も含む）。原本7件/store内8 JSONの15ファイルについて、SHA-256・byte数・identityをcollector内と独立した外側のinventoryで前後照合し全件一致。engine/environmentも外側の前後走査で一致した。hash/bytes inventory digestはa96510d56bc64e71a958d757219a39952c1fd376c624dbabb9042a0d45aa0d8a。最終engineFingerprintは37fdb3d42f8d1167d20358d946948bd8e98bedc3fd73402bc56327eacdc38448、contextFingerprintは520f19078d6be6449c9a0c7099048e0606c9a1fb9e7a65a9948216ebaadc01b8。計測レポート・candidate payloadは永続化せず、本節には検証要約だけを記録した。

### Phase 2C-2c-1 基本旅程品質metrics差分（2026-11-04）

独立 `scripts/odpt_quality_diff.py` の `compare_quality(baseline_store, candidate_store, baseline_source_dir, candidate_source_dir, ...)` が非公開のメモリ内比較を返す。quality profileはdotchi.odpt.itinerary-quality/0.1.0-draft、diff contractはdotchi.odpt.itinerary-quality-diff/schemaVersion 1。Phase 2Bの意味比較結果・公開資格とは独立する。既存collector・詳細metrics・単一Snapshot CLI・generator/matcher/v2射影/validator/gateは変更しない。比較モジュールを品質engine rootsに加え、現在18依存ファイル。

**入力と処理:** Phase 2C-2aのvalidate_inputsで両側のSource/Snapshot契約・固定7 source・hash/byte数・contentFingerprint・context・現在engineとruntimeを検証。さらに既存collectorのphysical inventoryを使い、両側の原本7件/store8 JSONをいずれの収集よりも前から最終検証後までbytes/identityで拘束する。同じ凍結engine/contextで既存collect_metricsをbaseline→candidateの順に実行し、各側の詳細観測は破棄して基本集計だけを保持する。metrics取得処理は再実装しない。APIでは共通context/engineに加え側別証拠を指定可能で、条件不一致の拒否を検証できる。入力不正=invalid、利用不能=unavailable、条件不一致=incomparableをinputReadinessで区別し、いずれも数値差分を生成しない。途中変更は確定差分として扱わない。

**差分の単位:** serviceDate×stationId×routeId。同じprofile/engineの基本9指標を比較し、除外理由辞書だけを固定6理由に分解するため14 numeric diffs/cell（初期48セルで672比較）。G/C/E、primary直通/乗換、alternative直通行、best transfer保有行、有効乗換接続組、各除外理由についてbaselineValue/candidateValue/delta/deltaDirection/comparisonAvailability/reasonCodesを保持する。deltaはcandidate−baseline。unit/numerator/denominatorが異なる値、片側欠損・重複・unavailable/null・不完全な理由集合は比較しない。known/0は比較し、欠損を0補完しない。両側の個別集計と、比較可能な同一セルだけを合計したmetricDiffTotalsを区別し、後者にもcomparedCellCount/notEvaluableCellCountを保持する。

**分類と整合性:** unchanged/candidate-increased/candidate-decreasedを基本とし、Cが正数→known/0の同一セルに限りcandidate-disappeared、primary減少にdirect-decreased/transfer-decreased、E/理由の増減にexclusion-increased/exclusion-decreasedを付与する。未評価はnot-evaluable、context差はcontext-mismatch。1 metric/reason/cellにつきfindingは最大1件とし、複数分類は同じfindingのtagsとして保持する。候補減少を品質悪化へ変換しない。両側のG=C+E、C=primaryDirect+primaryTransfer、E=実測理由合計を既存算術関数でそれぞれ再検査し、不一致は側別findingとして保持。両側が同じ異常値でdelta=0でも検査を省略せず、数値補正しない。

**結果と状態:** 指定のSnapshot ID/contentFingerprint、evaluationContext/contextFingerprint、engineFingerprints、baselineMetrics/candidateMetrics、metricDiffs/findings/checks/notEvaluated、comparisonStatus/qualityDiffStatusに加え、集計summary・omittedDetails・comparisonDigestを返す。条件差はincomparable、入力不正/利用不能はfailed、基本比較成立はpartial。詳細metrics差分と画面表示モデル比較は未実装なので、このPhaseで全体complete/unchangedは返さない。確定差分が1件でもあればqualityDiffStatus=changedとして、他の未評価指標・打切りがあっても保持する。基本差分0なら全体indeterminate、基本範囲だけはbasicQualityDiffStatus=unchanged（全基本指標・算術検査成立時）とする。局所未評価/不整合だけなら基本範囲もindeterminate。

**決定性と上限:** 日・駅・出発路線・metricId順、理由code昇順、baseline→candidate順。trip_id/public IDによる世代間結合はしない。既定詳細上限1,000件、許容0〜10,000件を、両側の基本metrics・metricDiffs・findings・整合checksの各リストへ適用する。打切り件数と全件集計を保持し、partial・detail_limit_reached・notEvaluatedへ明示する。digestはcanonicalな比較証拠から計算し、実行時計・性能値・物理stat時刻を含めない。CLIだけに処理時間とprocess peak RSSを表示し、raw source・旅程本文・列車ID・比較artifactを出力/保存しない。

CLI: `python3 -B scripts/odpt_quality_diff.py --baseline-store <absolute-store> --candidate-store <absolute-store> --baseline-source-dir <absolute-source-dir> --candidate-source-dir <absolute-source-dir>`。対象/changed/unchanged/indeterminateセル数、両側G/C/E/primary/理由等のknown集計、比較可能セルだけの差分合計、両側算術検査、状態・notEvaluated・入力前後不変・digestを表示する。終了コードは0=基本比較/整合検査成立（確定差分ありも0、全体partialを許容）、2=条件不一致/局所未評価/不整合/打切り/引数不正、3=入力不正/途中変更、4=入力または環境利用不能。

**検証:** 合成20テストを含む最終品質関連61件PASS（62.515秒）。既存関連224件を含む統合243件PASS（199.425秒、終了検証位置の最終調整前）；調整後は61件で算術計算中のstore変更も検出した。既存QA7件は6件PASS・sandboxのlocalhost bind制限1件となり、当該1件は権限付き単独再実行でPASS。既存v2 adapter/DOM Node12件PASS。Git管理するfixtureは合成のみ。実異世代の差分検出実績とはせず、異なる合成Snapshotと合成metricsで変化を確認した。

**非公開実source QA:** 既存Phase 1C storeと同じ原本7件を両側へ指定した自己比較。両側それぞれ48セル・基本432 entriesがknown、14数値指標×48=672比較成立。G10,536/C10,128/E408、primary直通7,887/乗換2,241、alternative直通行7,887、best transfer保有行6,570、有効接続組50,772。除外explicit_pass_info408、他5理由0。G/C/E・primary・alternative/接続組・全除外理由の差分はすべて0。確定差分0、changedセル0/unchangedセル48/indeterminateセル0、両側144×2=288算術checks PASS。inputReadiness ready、comparisonStatus partial、qualityDiffStatus indeterminate、basicQualityDiffStatus unchanged、新CLI終了0。詳細metrics差分と表示モデル等はnotEvaluatedで保持する。

最終実CLI134.040秒、process peak RSS423,194,624 bytes（約403.6 MiB、macOS、メモリ内stdout捕捉込み）。外側の独立した原本/store照合・engine/environment前後走査を含むQA全体136.608秒。原本7件/store8 JSONの全15ファイルでSHA-256・byte数・device/inode/size/mtime/ctimeが前後一致し、engine/environmentも一致した。比較digestは766db4d5fa4ee14754a301dcabc11a1ad233c65646bdf4f24e34c7f1c146acfa。比較結果・candidate payload・原本コピーは保存せず、要約だけ本節へ記録する。実データは非公開・公開未承認を維持する。

### Phase 2C-2c-2 詳細旅程品質metrics差分（2026-11-04）

既存odpt_quality_diff.pyを拡張し、型別比較をodpt_quality_detail_diff.pyへ追加。collector・generator・matcher・v2射影/validator/gateは未変更。同じ凍結engine/context/runtime、両側read-only bindingと最終不変検証、baseline→candidate順を維持する。比較helperは既存engine rootsからimportで追跡され、現在19依存ファイル。profile dotchi.odpt.itinerary-quality/0.1.0-draft、diff contract dotchi.odpt.itinerary-quality-diff/schemaVersion 1を維持する。

**互換性:** 既存baselineMetrics/candidateMetrics、metricDiffs、summary、basicQualityDiffStatusの基本9指標・理由別差分と算術は維持。追加field baselineDetailedMetrics/candidateDetailedMetrics、detailedMetricDiffs、detailedSummary、detailedQualityDiffStatus、confirmedFindingCount、checks.detailedConsistencyに詳細証拠を保持する。既存contract fieldの型/意味は変えず、98指標×48=4,704の詳細比較を加える。詳細のbaselineValue/candidateValue/deltaはscalarならscalar、辞書なら比較fieldのpath別値。componentDiffsで各fieldのavailability/reasonCodesを示し、親がpartialでも既知fieldの確定差分を保持する。コードpathのスラッシュ等はescapeし、affectedCellsのIDや旅程本文を比較しない。

**件数と率:** raw 5状態・native・generator集約状態を別metricとして比較し、native confirmed→profile unique_matchはcollectorの変換済み値を使う。第1/第2区間・primary/最良乗換alternative・延べ参照/セル内一意対象をmetric IDで区別する。世代間ID結合・セル横断一意化はしない。unitと母集団/分母定義を照合し、率は両側のnumerator/denominatorと算術整合を確認する。分母件数の変化は比較拒否せずdenominator-count-changedと件数差を明示する。分母0の率はnull/delta null、両側0はnot-applicable・zero_denominatorとして記録し、未評価対象へ列挙する。一方だけ0・根拠欠損・定義差ならnot-evaluable。照合件数変化と率低下は別finding。集計率は同じ比較可能セルの分子/分母を別々に合計して再計算し、率の単純平均・差の和は使わない。セル内一意数の延べ合計をSnapshot全体の一意列車数とはしない。

**診断・coverage・表示根拠:** itinerary INFO/WARNING、generator matcher状態、v2 exclusion INFO/WARNING/UNKNOWN、v2 validator Rows/Cellを別体系で比較。codeOccurrences・affectedRowCount・affectedGeneratedRowCountとcode別件数を保持し、体系間の総和を作らない。knownで完結した辞書内の未出現code/stateだけは実測0として扱う。metric自体や必須fieldの欠損/unavailable/nullを0にしない。Cell validatorの影響生成行数不明はfield単位で未評価のまま、既知のerror件数差を残す。routeCoverageのdataState/coverageClassification/reasonCodes、scheduledTripCount、origin/transfer不足根拠、状態別セル数・遷移・out-of-range等のavailability遷移を比較。complete→insufficient/unknownはcoverage-regressed候補であり、更新正当性や悪化の確定判定にしない。scheduledTripCountは路線の運行trip数で、池袋発候補数へ読み替えない。種別確定/補助/未確定・愛称のみ・種別根拠source、行先確定/欠損/不明も既存分類のまま比較する。

**findingと状態:** match-rate-decreased、ambiguous-increased、unmatched-increased、unknown-increased、warning-increased、validator-error-increased、coverage-regressed、train-type-unresolved-increased、destination-missing-increased、not-evaluable等を付与。metric/cell当たり最大1 findingへ複数分類を集約し、native/observed raw、generator診断、v2 stateは対応する主証拠が両側knownなら追加findingを抑える。主証拠が欠けても独立に既知の差分があれば保持する。両側の既存詳細算術checksも再利用し、異常を側別finding、全件状態数と異常明細へ保持する。全体complete/unchangedへは昇格しない。基本または詳細に確定差分があればchanged、差分がなくても全体indeterminate。詳細範囲は既知値一致・未定義率は別掲でunchanged、未取得/field不明/整合異常があればindeterminateとする。種別/行先不明増加も確認対象であり、不具合判定ではない。

**未収集の時刻検査:** collectorには時刻整合検査対象数・時刻矛盾件数・待ち時間検査対象数・待ち時間違反件数の独立metricsがない。この4項目をnotEvaluatedへ明示し、新しい検査・既存診断からの対象数推測・time-inconsistent/transfer-wait-invalidの断定は追加しない。既存validator/itinerary code件数を検査母数や違反総数の代用にしない。

**上限とCLI:** 4入力引数と終了コード0/2/3/4の意味を維持。既定各明細1,000件・API最大10,000件を維持し、詳細metric内のcomponentにも上限を適用。全件のmetric/field集計、状態遷移、確定finding件数、全省略件数は明細打切り前に計算する。変更・未評価・整合findingを優先して保持し、unchangedは全件数をsummaryへ集約して個別行を省略する。baseline/candidateの詳細metric明細もactionableな比較対象だけ保持する。unchanged集約だけではpartial/終了2にせず、確定変更/未評価/不整合明細が1,000件を超えた場合は省略数・detail_limit_reached・partialを明示して終了2。基本summary出力を維持し、detailed_summary/confirmed_finding_countへmatcher状態・区間別率/分子分母・診断・coverage・種別/行先・評価不能を出す。両側分母0の未定義率はnullのnot-applicableとして未評価項目へ残すが、正常な自己比較の異常理由や終了2にはしない。差分有無のみでは終了2にしない。実行時刻/時間/RSSはdigestへ含めず、結果・本文・candidateを保存しない。

**合成・回帰検証:** 新規16テスト（subTest含む）で全raw状態/native対応、raw/集約独立、分母変化・0・定義差・加重率、第2区間延べ/一意、code/行数/UNKNOWN/WARNING/validatorの分離、coverage遷移・scheduled数・availability、種別/行先、時刻未評価、片側欠損・既知差分保持、上限・順序/digest、既存CLI/gate独立を検証した。既存基本差分テストは数値assertを維持し、unchanged集約・actionable明細優先を追加検証。関連ODPT Python261件PASS（180.040秒）。別の既存QA7件は6件PASS、localhost bindのsandbox制限1件を権限付き単独再実行してPASS。Node adapter/DOM12件PASS。Git管理するfixtureは合成のみ。

**非公開実source QA:** 既存Phase 1C store/保存済み原本7件を両側へ指定し、2026-10-28〜30×8駅×2出発路線の48セルを自己比較。基本672比較は全差分0、G10,536/C10,128/E408、primary直通7,887/乗換2,241を維持した。詳細4,704 entriesの内訳はknown4,488、両側分母0による率not-applicable216（率/deltaともnull）、not-evaluable/partial0。比較可能な全詳細fieldの差分0、changed0/unchanged48、確定finding0。raw/native/集約状態差分0、定義されたraw/集約照合率100%・差分0。primary第1区間10,128/10,128、第2区間延べ2,241/2,241・セル内一意の延べ2,196/2,196。最良乗換alternative第1区間6,570/6,570、第2区間延べ6,570/6,570・セル内一意の延べ3,726/3,726。これらの軸を横断して独立列車数としない。

UNKNOWN/WARNING・validatorの差分0。routeCoverageの両側complete48、complete→complete48、分類/不足理由の変化なし。scheduledTripCountは目的地/日/路線の延べ合計23,424で差分0（池袋発候補数ではない）。種別確定/補助/未確定・愛称のみ・種別source、行先確定/欠損/不明も全差分0。両側基本144×2=288、詳細3,696×2=7,392、計7,680算術checks PASS。inputReadiness ready、comparisonStatus partial、qualityDiffStatus indeterminate、基本/詳細の既知範囲はunchanged。詳細metric明細はchanged/not-evaluable、不整合を優先し、unchanged件数は集計へ保持する。baseline/candidate詳細metricもactionableな対象だけ個別保持するため、unchangedの集約は省略件数・partial・終了コードへ影響しない。自己比較CLIは終了0。画面表示モデル未評価によるpartial/indeterminateは維持する。修正後QAは約101.8秒、peak RSS 430,297,088 bytes。原本7件とstore8 JSON（計15ファイル）のSHA-256/byte数/stat identity、engine 19依存ファイルの前後一致を確認した。

実CLI111.958秒、process peak RSS432,611,328 bytes（約412.6 MiB、macOS、メモリ内stdout捕捉込み）。独立inventory/engine前後走査を含むQA全体116.234秒。原本7件/store8 JSONのSHA-256・byte数・device/inode/size/mtime/ctimeが全15件で前後一致し、engine/runtimeも一致。比較digestは538a6b25f4cdd2d8c17a76a039b6c5f659c6edb38f1f36cc00a94685c6f3b082。結果・原本コピー・candidateは保存せず、実データ非公開/公開未承認を維持した。実異世代差分は合成fixtureでのみ確認。画面表示モデル・時刻/待ち時間4検査指標・各probeの最初のerror以降・全接続組の各leg品質・セル横断一意対象・鮮度/公開資格等は未評価のまま。


### Phase 2C-3a採用設計 / Phase 2C-3b-1 表示context・Node runner（2026-11-04）

Phase 2C-1の3段階のうち画面表示モデルへ進む入力基盤。既存旅程contextのdisplayEvaluation=not-evaluatedを維持し、独立contract `odpt-display-evaluation-context` / schemaVersion 1を追加した。qualityContextFingerprintで検証済み旅程contextを参照し、timezone=Asia/Tokyo、UTC秒精度のobservationInstants、4 displayScenarios、観測instant→必要3 serviceDateのrequiredServiceDatesを封印する。Python `odpt_display_context.py`が既存normalize_contextを再利用し、Node `odpt_display_contract.mjs`も参照・hash・条件を検証する。canonical JSONはUTF-8・key昇順・空白なし・非ASCIIをそのまま保持・有限safe integerのみ。fingerprintは自身を除いたSHA-256。instantsとscenario IDは昇順へ正規化、重複拒否、必要日配列はD-1/D/D+1固定順。必要日は旅程contextのserviceDates+auxiliaryServiceDatesに含まれることを要求する。実時計・実行日・暗黙の日付選択は使わない。

採用scenarioはdeparture-all/departure-direct/line-all/line-direct。modeとdirectOnlyのみを切り替え、horizonSeconds=86400、lineLimit=3、departureLimit=6は既存adapterの規則を記述する固定値。任意cardLimitやrouteSeparatedは追加しない。v2 QAは各候補の発車60分前ゲートを使い、候補全体のbestをカード制限前に選ぶ。従来previewのearliestVisibleを流用せず、bestがgroups外になる場合もそのまま観測する。

非公開 `node scripts/odpt_display_runner.mjs` はstdinに1 JSON request、stdoutに1 JSON response（本文を含む非公開IPC専用）を返す。request contract=`odpt-display-adapter-request` / schemaVersion 1、fields=qualityContext/displayContext/expectedNodeRuntime/payload/qaState/observationInstant/displayScenario。expectedNodeRuntimeは検証済みengine.environment.nodeをcallerが渡す。同じprobe形式でversions/platform/arch/Intlを完全比較する。8 MiB入力上限、UTF-8 strict、JSON重複key・深さ64超過を拒否。schema/context/runtime、payloadのちょうど必要3日・public ID、QA state、旅程contextの最大乗換待ち制限を検証してbuildV2QaBoardを呼ぶ。DOM本体はimportしない。成功0、失敗2。stderrは固定codeだけ、失敗応答にはboardを含めず、本文・例外メッセージをechoしない。

response contract=`odpt-display-adapter-response` / schemaVersion 1。boardのfield・card・group順/上限・best参照・route stateを検証し、key順だけを正規化する。items/groupsの順序と既存label/IDを保持し、candidateCount/cardCount/bestInGroups/displayedBestMarkCount/terminalKnownByRouteDate/unknownRouteStateCountを別掲する。itemContentKeysはID/sourceIdを除いた表示内容のhashで、独立列車・世代間同一性を保証しない。boardDigestはgeneratedAtを除き、実行時間も含めない。欠日boardの別形はnormalizeBoardでunavailable/missingFieldsとして保持し、best等の欠落fieldを補完しない。runnerではその前の3日envelope検証で欠日requestを拒否する。既知items=0はvalidatedとして区別する。

payload/QA stateはobject入力のため元candidate file bytesのhash照合は未評価（state内integrityは形だけ検証）。source/Snapshot binding・実engine artifact照合はcaller側の責任で次工程に残す。Node runtime一致だけで実sourceや公開適格性の確認とはしない。DOM文言・CSS・viewport/font・視覚品質・Python表示collector・旧新表示比較・公開資格は未評価。生成日時の固定envelope値は取得日時や適用期間の根拠ではない。

品質engineのschemaVersionとhash方式を維持し、display context/runner/そのimport closure、selection、DOM JS、HTMLを明示依存へ追加した。静的ファイル名の参照をimport探索だけに任せない。相対importはroot内の../を解決し、root外と未知external importを拒否。Node crypto/urlはruntimeのbinary/versions証拠で扱う。依存範囲拡張でengineFingerprintは変わるため旧証拠は再採取する。DOM/CSSそのものの評価は今回行わない。

実sourceのpayload生成・全駅収集は実施せず、原本/storeを読まない合成QAに限定。祝日・振替休日をrunnerが再判定しない。Python合成calendarで通常平日・例外切替・振替休日を模した固定例外を既存_active_servicesに適用し、実際の祝日feed・深夜境界の全駅QAは3b-2以降に残す。

検証: 新Node runner合成9件、既存Node adapter/DOM/selection/timetable関連54件PASS。Python ODPT統合265件PASS（184.046秒）、追加の依存閉包検査を含む表示context単独5件PASS。4 scenario、UTC/JST、3日不足、24/25時、60分ゲート、発車同時刻、直通alternative、同着、bestのgroups外、8 route状態、UNKNOWN抑止、0/unavailable、schema/runtime/context hash、重複JSON/depth上限、結果決定性を確認。engine依存25ファイル。実source QA・性能評価は今回実施していない。


### Phase 2C-3b-2 単一Snapshot非公開表示モデル収集（2026-11-04）

独立read-only CLI/API `scripts/odpt_display_metrics.py` を追加。contract=`odpt-display-model-collection` / schemaVersion 1。Snapshot ID/contentFingerprint、旅程/表示context fingerprintと実context、engine/environment、観測時刻/scenario、cells/aggregateMetrics/checks/findings/notEvaluated/collectionStatus/collectionDigestをメモリ上に保持する。既存context・Node request/responseの意味は維持。既存25 engine依存を引き続き検証し、collector自身を追加して26依存とする。engine/hashの方式やschemaは変更しない。

Phase 2C-2a validate_inputsを単一Snapshotの両側同一指定で再利用。生成前に原本7/store8 JSONのphysical inventory（SHA-256/bytes/identity）を凍結し、終了時はNode処理と集計まで含めて再検証する。engine/context/runtime/Source/Snapshot不一致や途中変更時は全cells・数値集計・生成証拠を無効化してfailed。局所的な日付不足/期間外・Node失敗では他セルの確認済み結果を保持する。DOMと視覚品質は未評価のため、正常収集時もcollectionStatus=partialであり全画面品質PASSではない。

観測時刻ごとのD-1/D/D+1のunionを駅ごとに一度ずつ生成し、generatorは駅単位で解放する。既存_build_station_payload（内部の_route_state/_public_departure/_exclusion_detail）、Python validator、_build_exclusion_audit/_validate_exclusion_audit、_qa_stateを再利用する。固定generatedAt=2000-01-01T00:00:00Zを検証用envelopeだけに使用し、評価時計はcontextのUTC instantのみ。3日payloadを組み立てる前に必要日を確認し、期間外はout-of-range、不正構造/利用不能はunavailable、metrics=null。欠日を空候補に補完しない。

除外監査は全reason/classification fieldとG=C+E、E=理由合計、分類集計・候補数・対象駅/日の完全性を既存validatorで検査してから_qa_stateへ渡す。_qa_stateの既存default 0を未取得情報の代用にしない。no_valid_arrivalとprimary_arrival_missing/unknownの集計、INFO、WARNING、coverageを保持し、payloadとQA stateの対応を検査する。candidate integrityは生成したメモリ内canonical UTF-8 bytesのSHA-256/byte数を計算・照合する。原本bytesのSource照合とは別の証拠であり、候補ファイルは保存しない。public run_pipeline/prepare/validate_bundleや公開資格gateを呼ばない。gate相当の問題がある候補も構造検証成立範囲だけを非公開観測し、構造不正はNodeへ渡さない。

Nodeはshellなし・stdin/stdout JSONで1セルずつ起動。request 8 MiB、response 32 MiB、stderr 4 KiB、既定20秒（上限120秒）を適用し、nonblocking pipesで上限超過/timeout時はkill/reapする。終了code・固定stderr・JSON/response schema・context/instant/scenario/runtime参照、board/group/card/best集計、UNKNOWNとterminalKnown、内容/digestを照合する。成功要求のrequest/response byte数と失敗理由数を保持。Node単体が未評価としているsource binding/candidate integrityはcollectorが別証拠で確認し、DOM等の未評価を全体reportに残す。

表示セルはSnapshot×observationInstant×station×scenario。itemsCount/groupsCardCount、路線別カード、serviceDate別候補、直通/乗換、bestの内容参照/表示内存在/マーク数、routeStates/terminalKnown、serviceState、UNKNOWN除外による抑止とcoverage等の不確実状態を区別して記録する。bestがgroups外でも選択を変更せず、枚数制限の既存挙動として件数に残す。public IDはSnapshot内参照だけに使う。集計は観測・駅・scenarioごとの延べ値で、独立列車数や旅程48セルの集計とは異なる。日別生成G/C/Eは別のgenerationSummaryで数え、シナリオ数で水増ししない。

cells/生成明細/findingsは既定1,000件、最大10,000件。評価不能・不整合セル/生成証拠を先に保持し、正常明細を残枠へ保持する。全集計・finding数・省略数は打切り前に計算し、省略時はpartial/detail_limit_reached/omitted-display-detailsを明示。時刻・駅・scenario順、生成は日・駅順、route/date mapはkey順。digestは実行時計・処理時間・RSS・物理stat時刻を含めない。比較機能は未実装なのでunchanged分類は行わない。

CLI: `python3 -B scripts/odpt_display_metrics.py --store <store> --source-dir <saved-source-dir>`。既定contextは旅程2026-10-28〜30、観測2026-10-29T03:00:00Z（JST正午）、4シナリオ、8駅=32表示セル。Snapshot ID・集計・状態・不変・digest・時間/RSSだけを表示し、原本/旅程/card本文を通常stdoutへ出さない。0=対象表示収集成立（DOM未評価のpartial許容）、2=局所未評価/条件差/明細省略/引数不正、3=入力不正/途中変更、4=入力・環境利用不能。APIは明示context/engine/上限/timeoutを受け取る。実時計で評価日を自動選択しない。


**合成・回帰:** 新collectorの合成16テストで、入力/原本不変、4 scenario、3日envelope・実合成feedの補助日期間外、QA state欠損/UNKNOWNのstart_unconfirmed・terminal_unconfirmed伝播、直通alternative、bestのgroups外・cardLimit、既知0とunavailable、異常JSON/終了code/stderr/timeout/出力上限、原本途中変更、engine途中変更時の全値無効化、構造不正payloadのNode非送信、上限/全集計/優先保持、同一入力の結果/digest、CLI非漏えい・公開gate独立を確認。Python ODPT統合278件PASS（374.968秒）、追加4件と更新対象の再検証もPASS。既存を含むNode63件PASS。fixtureは合成だけをGit管理し、実sourceは追加しない。

**実source非公開QA:** Phase 1C storeと対応原本7件をread-only使用。旅程context serviceDates=2026-10-28〜30、補助日=27・31を明示。必要日unionの27〜31を8駅それぞれ生成し、40駅日envelopeすべて構造検証成立。日別生成はG17,288/C16,604/E684（観測回数を掛けない）。事前確認で氷川台の10/29 route6は05:12〜24:13、route9は05:22〜24:11、任意昼候補はroute6 12:03を得てから観測リストを固定した。

実際の固定観測日時は次の21件（すべてJST、contextは対応UTC秒精度）:
- 10/28: 23:59:59。
- 10/29: 00:00:00、00:10:59、00:11:00、00:12:59、00:13:00、00:13:01。
- 10/29: 04:11:59、04:12:00、04:12:01、04:21:59、04:22:00。
- 10/29: 11:02:59、11:03:00、11:03:01、12:00:00、23:59:59。
- 10/30: 00:00:00、00:12:59、00:13:00、00:13:01。

21時刻×8駅×4シナリオ=672表示セル（旅程品質48セルとは別単位）がすべてknown、unavailable/out-of-range/部分未評価セル0、findings0、省略0、入力ready、collectionStatus partial、終了0。items3,288=直通2,864+乗換424、cards1,688（route6 1,036/route9 652）。候補serviceDate別延べ件数は10/28 428、10/29 2,860。best存在/表示内/表示マークは各512、非表示best0、best整合672/672、既知0候補160セル。昼間既定CLIは1時刻×8駅×4=32セル、items576/cards192、best表示32/32、findings0、終了0。

routeStatesは計4,032参照のうちrunning832/not_started2,016/ended1,056/data_insufficient128。terminalKnown=true3,904/false128。補助日10/31にcoverage insufficientがあり、補足の氷川台route9ではunique_match209/unmatched6・WARNINGあり3生成行を確認した（route6 complete、route9 insufficient）。収集処理はこの状態を補正せず、その路線の終電確定を抑制する。これは既知の表示状態の観測であり収集不能や全画面品質PASSではない。実sourceのUNKNOWN除外による抑止は0で、UNKNOWN始発/終電未確認は合成で確認した。実sourceでbestが表示上限外となるケースも今回0、合成で確認。

JST午前0時を跨ぐ前後で候補を維持し、24時超便は元serviceDateを保持。00:12:59の32候補が00:13:00に0となる際、過去serviceDateのroute stateはended、観測暦日のboard serviceStateはnot_startedとなる既存挙動をそのまま記録した。全駅・全路線・全filterの固有境界時刻を網羅したものではなく、上記代表時刻による共通評価である。

境界QAは独立inventory/engine走査込み629.257秒（回帰等と一部並行実行）、親process peak RSS426,160,128 bytes、Node子process最大RSS145,002,496 bytes（合計peakではない）。672成功requestの入力bytes合計425,470,096、応答4,759,700。各セルで既存runnerが3日payloadを再検証するため、反復コストが大きい。最終既定CLIは74.316秒、親peak RSS410,988,544 bytes。双方で原本7/store8 JSONのSHA-256/bytes/identity全15件、engine/runtime 26依存が前後一致。結果・candidate・原本コピーを保存しない。性能最適化、旧新比較、DOM/ブラウザー描画、鮮度/公開資格、serviceDate跨ぎ乗換探索は今回追加しない。


### Phase 2C-3c-1 表示モデル基本差分（2026-11-04）

独立contract `dotchi.odpt.display-model-diff` / schemaVersion 1、read-only `scripts/odpt_display_diff.py` を追加。両Snapshot ID/contentFingerprints、両旅程/表示evaluationContexts、同一engineFingerprint/environment、baselineSummary/candidateSummary、cellDiffs/findings/checks/notEvaluated、comparisonStatus/displayDiffStatus/basicDisplayDiffStatus、summary/omittedDetails/comparisonDigestをメモリ上に保持する。既存collector・generator・matcher・adapter・public gateと各schemaは変更しない。比較自身をengine seedへ追加し、27依存とする。

既存Phase 2C-2a検証で両store/原本7件・hash/bytes・Snapshot契約・contentFingerprint・context/engine/runtimeを検証。両側のphysical inventoryを収集前に凍結し、両collector・差分計算終了まで再検証する。表示contextもnormalize・参照・hash・同一性を確認。collectorは同一条件で順次実行し、baselineのraw boardを基本意味内容へcompactしてからcandidateを評価する。collection contract/digest、Snapshot/context/engine/environment、開始終了check、knownセルの内容・group参照/上限・bestと件数/集計の整合を検証する。global入力不正や途中変更時は数値差分を返さずfailed、条件差はincomparable。Node runtime不一致はincomparable、不正payload/responseはinvalid。局所unavailable/out-of-rangeでは他セルの確定差分を残す。

比較セルはobservationInstant×stationId×表示scenario（既存collectorのscenarioId）。items/cards/直通/乗換/可視bestマーク数、route別cards、serviceDate別items、best意味内容/表示内存在を両値・delta・availability/reasonCodes付きで保持する。欠損セルや未評価はnullで、0補完しない。完全に評価されたhistogram内の未出現だけを観測済み0として扱う。summaryの差分合計は両側knownな同一セルのみを分母とし、独立した両側収集summaryから単純減算しない。

itemsはdeparture/arrival epoch・route・serviceDate・選択journey種別・列車種別文字列・行先・乗換駅/待ち秒/乗継路線を正規化。ID/sourceId/public ID/trip_id、isBest/終電flagは項目同一性に使わない。選ばれなかったalternativeはitem内容に含めない。意味内容をcounterで数え、多重度を維持して追加/除去を計測する。変更項目を同じ列車と推定して対応付けない。多重集合が同じときは意味列の順序を直接比較し、内容が変わるときは共通かつ各側一意な内容の相対順序を比較する。挿入による位置移動と相対順序変更を区別。重複内容の個体対応はambiguousとして保持し、1対1に割り当てない。意味列そのものの同一性が確認できても個体対応の曖昧性は別に残す。

groupsはdeparture全体6枚/line各路線3枚を入力証拠として検査し、item比較とは別にgroup ID付きカード列・group存在・内容/順序/位置を比較。位置明細は列全体位置とgroup内addressを保持する。bestIdは各側model内で解決して意味内容とepochを比較し、同内容候補が複数ならbestの個体対応もambiguous。bestInGroups、visibleBestMarkerCount、実カードのマーク位置/内容/labelを別比較する。bestが表示上限外でも選択を変えず、両側の非表示件数を集計する。両側同じ非表示状態だけから変更findingを生成しない。

分類はunchanged、items/cards-increased/decreased、item/card-content-changed、item/card-order-changed、best-changed、best-not-visible、best-marker-changed、ambiguous、not-evaluable、context-mismatch。1セルのfindingへタグを集約し、減少やbest変化を品質悪化と断定しない。routeStates・terminalKnown・始発/終電・UNKNOWNの詳細差分分類は3c-2へ残す。side summaryの既存状態集計は説明情報であり今回の変化分類には使わない。DOM/CSS/視覚品質・公開資格/鮮度も未評価。

全体は比較できるセルがあればpartial、確定差分ありはdisplayDiffStatus changed、基本一致でも全体indeterminate。既知基本範囲の一致だけをbasicDisplayDiffStatus unchangedとする。曖昧/未評価があれば基本範囲もindeterminate。unchangedは件数中心で個別明細を保持しない。changed/ambiguous/not-evaluableセル・findings・contentChanges・positionChangesは各リストにつき既定1,000件（API最大10,000）、全件集計と省略数を保持する。必要明細省略はdetail_limit_reached/partial、unchanged件数だけでは打切り扱いにしない。collectorへは既存最大10,000セル保持を要求し、collector自身が省略したセルはmissing/not-evaluableとして明示する。collector上限を超えるcontextの全セル意味比較は未完了となるが、取得済みの確定差分は維持する。

CLI: `python3 -B scripts/odpt_display_diff.py --baseline-store <store> --candidate-store <store> --baseline-source-dir <source-dir> --candidate-source-dir <source-dir>`。既定はJST2026-10-29正午・8駅・4scenario。集計・状態・notEvaluated・digest・時間/RSSだけを表示し、原本/旅程/ラベル本文を出さない。0=対象基本比較成立（差分ありも0、全体partial許容）、2=条件差/局所未評価/曖昧/必要明細省略/引数不正、3=入力不正、4=入力・環境利用不能。時刻/駅/scenario、内容key順で決定的処理。timings/resourcesはcomparisonDigestから除外する。Node子最大RSSはRUSAGE_CHILDRENの最大値で親と合算せず、環境probeのNode起動数は今回未計測と明示する。


**実source自己比較QA:** 既存Phase 1C storeと対応する保存済み7原本を両側に指定。旅程日2026-10-28〜30、観測2026-10-29T03:00:00Z（JST12:00）、8駅×4scenarioの32セル。両側items576（直通480/乗換96）、cards192（route6/9各96）、best/表示マーク32。全基本値・内容/順序・best差分0、changed0/unchanged32、ambiguous/未評価/確定finding0。unchangedDetailsAggregatedCount32、個別cellDiffs/findings0、省略0、comparisonStatus partial/displayDiffStatus indeterminate/basicDisplayDiffStatus unchanged、CLI終了0。今回は実source境界時刻の追加比較は行わず、境界収集は3b-2 QAと合成テストを参照する。実異世代の検出は合成source/storeから既存v2生成・QA state・Node runnerを通す検証を含む合成fixtureで確認。

baseline収集81.935秒、candidate収集77.931秒、比較処理全体168.193秒、独立外側の前後照合込み171.269秒（回帰等と一部並行）。親peak RSS418,430,976 bytes、Node子最大144,384,000 bytes（合計peakではない）。各側generatorは8駅、駅日生成24回・runner成功起動32回。両側合計48駅日生成/64 runner起動で、同一Snapshotでも片側の結果を流用せず順次再評価する。各側内部の日別cacheにより同じ駅日をscenarioごとに再生成しない。環境probeのNode起動数は未計測。原本7/store8 JSON（同一path実体15ファイル）のSHA-256/bytes/identityとengine/runtime 27依存が、collector・外側比較・独立QAで前後一致。レポート/candidate/原本コピーの保存は行わない。

**合成・回帰検証:** 新規19テストを含むPython ODPT統合301件PASS（497.258秒）、既存Node関連63件PASS。自己比較、件数/意味内容/順序の分離、重複多重度・best曖昧性、IDのみ変更、欠損とknown/0、direct条件の分離、line/departureと上限、best非表示・mark、条件/engine/runtime差、入力/response不正、途中の原本/engine変更、1,024セルの全件集計と1,000件保持、unchanged大量時の終了0、順序/digest決定性、既存collector/gate独立を確認。実異世代検出は合成のみ。変更は新比較module/test、engine seed、指定3文書の6ファイル。git diff --check PASS、commit/push/merge/deployなし。


### Phase 2C-3c-2 運行状態・始発終電・UNKNOWN詳細表示差分（2026-11-04）

既存 `dotchi.odpt.display-model-diff` / schemaVersion 1と4引数CLIを維持し、`odpt_display_state_diff.py` を比較層のhelperとして追加した。既存collectorでbaseline→candidateを同じengine/context/runtime・固定観測時刻により順次収集する。helperは静的import経由でengineへ自動追加（28依存）。collector/generator/matcher/adapter/runner・公開v2 gateは変更しない。

基本 `summary` / `cellDiffs` / `basicDisplayDiffStatus` は従来のitems/groups/best比較の意味を維持。追加の `stateDiffs` はfeature・両値・availability・reasonCodesと観測時刻×駅×scenario（路線featureではserviceDate×routeIdも追加）を保持する。`stateSummary` は全featureのchanged/unchanged/not-evaluable件数、路線/terminalKnown/serviceStateの遷移件数、checks・不整合件数を集計する。`stateTransitions` は変化した既知遷移の明細、`stateChecks` は不整合明細、`stateFindings` はセル単位の状態finding。最上位 `findings` は基本/状態タグを同じセルへ統合し重複生成を抑える。`displaySummary` は基本/状態のセル集合を統合して件数を返す。changedとnot-evaluable/inconsistentの件数は独立で、同じセルが両方へ入ることがある。`stateDisplayDiffStatus` を追加し、確定状態差分があれば未評価や不整合が併存してもchangedを保持する。全体comparisonStatus partial、無差分時のdisplayDiffStatus indeterminateはDOM/描画等の未評価のため維持する。

routeStateは既存8状態をそのまま観測し、route候補数/有無とcoverage由来のcandidateEligible/scheduledTripCount/data_insufficientの影響を別featureにする。欠route/dateをno_candidatesへ補完しない。未知状態値が比較層へ到達した場合はraw値とunknown-route-state-valueを未評価明細へ保持し、既知状態へ変換しない。上流runner/collectorが契約違反として拒否した応答は、従来の不正response扱いを維持し未知値を正常化しない。terminalKnownは日×路線でtrue/false遷移を集計し、lost/gainedを確認対象とする。serviceStateはboard値を比較し、候補ありrunning／候補なし当日2路線集約との整合を独立checkする。data_insufficientを新しいserviceStateとして補完しない。

始発案内はnot_started/start_unconfirmed、終電案内はended/terminal_unconfirmedと、選択されたitems内のisLastDeparture/terminalBasis、意味内容、groups内存在を観測する。「終電」「直通終電」のlabel根拠を分離し、cardLimitで終電候補が非表示になる件数も保持する。ID/trip_idで終電を世代間対応付けず、選択されないalternativeやboard外の最終候補を推定しない。labelは既存rendererのbasis対応に基づくモデル観測であり、DOMの最終文言・ブラウザー描画は未評価。

UNKNOWNは日×路線にboardが保持するnoValidArrivalCount/otherUnknownCountを追跡し、UNKNOWNなし・あり・始発未確認・終電未確認・coverage由来の未確認・QA evidence欠損を分離する。駅×日で両路線へ同じUNKNOWN件数が伝播することと、当日のboard監査件数との整合を検査する。INFOはboardのauditEvidenceへ保持するがUNKNOWNへ昇格させない。WARNINGはQA state/boardに独立件数として露出しないため、その件数自体はnotEvaluatedに残し、既存converterがquality_warningをUNKNOWNへ加算しないことを合成テストで確認する。生routeCoverage.dataStateもboardにはないため推定しない。coverage不足とUNKNOWNを同一原因にしない。

日付境界featureは観測JST暦日、board serviceDate、必要/観測3日envelope、各表示候補の元serviceDate・routeId・departure epoch・発車JST日付の多重集合を比較する。時刻文字列は使わない。24時超便を翌serviceDateへ移動せず、同じ固定観測時刻で候補の出現消失を比較する。異なる観測時刻間を旧新比較セルとして対応付けない。

分類はroute-state-changed、terminal-certainty-lost/gained、service-state-changed、start-guidance-changed、terminal-guidance-changed、unknown-suppression-changed、coverage-state-changed、not-evaluableに加え、route-candidates-changed、date-boundary-changed、inconsistency。品質影響はnot-assessedであり、確定性喪失/改善候補はダイヤの正当性・公開資格の証明ではない。全件比較/件数集計の後、changed/not-evaluable/inconsistency明細を各リスト既定1,000件（API最大10,000）まで保持し、省略数・detail_limit_reached/partialを記録する。unchangedは集計のみで上限消費・終了2を起こさない。既存のcollector上限超過による欠セルは未評価を維持する。時刻/駅/scenario/日/route/feature順の決定性を保持し、timings/resourcesはdigestから除外する。

CLIは基本summaryにstate_summary/display_summary、遷移・certainty/始発終電/UNKNOWN/serviceState等のfeature件数とexit_codeを追加。原本・旅程・label本文は出力しない。0=比較成立（差分あり・全体partialも許容）、2=条件差/局所未評価/不整合/必要明細省略/引数不正、3=入力不正/途中変更、4=入力・環境利用不能。比較結果・candidate・原本コピーの永続化は行わない。

**既定実source自己比較:** 保存済みPhase 1C storeと対応原本7件を両側へ使用。2026-10-29 12:00 JST×8駅×4scenario=32セル、両側items576/cards192/best・表示mark32。基本差分0、routeState/terminalKnown/coverage/routeCandidates/始発/終電/UNKNOWN各192比較、serviceState/dateBoundary各32比較はすべてunchanged。routeState遷移はended→ended64、not_started→not_started64、running→running64、terminalKnown true→true192、serviceState running→running32。changed0/unchanged32、局所未評価/不整合/確定finding/省略0、両側計2,304 checks PASS。basic/stateの既知範囲unchanged、overall partial/indeterminate、CLI終了0。

baseline73.368秒、candidate83.507秒、比較全体164.729秒、独立照合込みQA全体167.675秒。親peak RSS422,023,168 bytes、Node子最大145,080,320 bytes（macOS、合算peakではなく、回帰と一部並行）。各側24駅日生成・32 runner成功起動、計48生成/64起動。環境probeのNode起動数は未計測。原本7/store8 JSONの全15実体についてSHA-256/byte数/device/inode/size/mtime/ctimeが前後一致し、engine/runtime28依存も独立走査で一致。比較digestはbd6a53f23c59510d7dc8c63ad085c9b494084817cc0f3693adf93e0fc061c16c。実異世代の変化検出は合成fixtureのみ。

**実source境界追加QA:** 既存21時刻の境界集合からJST 10/29 23:59:59、10/30 00:00:00・00:12:59・00:13:00の4時刻を固定。旅程日28〜30と補助日31により必要3日を用意し、4×8駅×4scenario=128セルを両側順次比較した。両側items/cards332（直通312/乗換20）、best・表示mark96、0候補32セル。候補はすべて元の10/29 serviceDateを維持。routeState/terminalKnown/始発/終電/UNKNOWN/coverage/候補数は各768比較、serviceState/dateBoundaryは各128比較がすべてunchanged。観測routeStateはdata_insufficient96/ended160/not_started352/running160、terminalKnown true672/false96、serviceState running96/not_started32で、補助日のcoverage不足も補正しない。changed/局所未評価/不整合/確定finding/省略0、9,216 checks PASS、全体partial/indeterminate、終了0。

境界QAはbaseline175.641秒/candidate187.940秒/比較全体369.693秒、独立照合込み372.256秒。親peak RSS426,311,680 bytes、Node子最大144,195,584 bytes（回帰等と一部並行）。各側32駅日生成/128 runner起動、合計64生成/256起動。原本7/store8 JSONの15実体のhash/bytes/stat identity、engine/runtime28依存が前後一致。digestは57e4709b81236d258d886efc52c2b718feeb9af40c487fa74f3ac3d973e9131e。全駅・全路線固有の境界を網羅したものではない。

**合成・回帰:** 状態helperの合成12テストを追加し、既存比較testへ局所未評価と確定状態差分の併存検証を追加（新規計13件）。既存adapterで全8状態・始発60分/発車ちょうど/最終候補前後・直通終電/上限外カード・UNKNOWN両路線伝播・INFO/WARNING非昇格・QA欠損/coverage不足/欠日・23:59→00:00と24時超・未知値保持・ID/フォーマット非依存・1,024セルの全件集計/1,000件上限・決定性/digestを検証。既存基本items/groups/best、条件/engine/runtime差、途中変更、CLI終了コード、公開gate独立も回帰した。ODPT Python313件一括PASS（571.732秒）、追加WARNINGテストを含む状態12件を再実行PASS（追加後ODPT対象314件）、追記した合成異世代Snapshot検証も再実行PASS。QA準備Python7件・関連Node83件PASS。QA準備のlocalhost bind検査はsandbox制限で失敗したため、許可されたsandbox外再実行で7件PASSを確認した。

変更は比較module/test、新helper/test、指定3文書の7ファイルのみ。実データ公開未承認を維持し、DOM/CSS/描画・性能最適化・Phase 2C-3d以降・鮮度/公開資格は対象外。API/新規取得、原本/store変更・複製・移動、applicationPeriod/publicationApproved変更、Actions/Cloudflare/Deploy、Commit/Push/Mergeは行っていない。


### Phase 2C-3d-2 固定時計DOM表示整合テスト（2026-11-05）

前回の未完了変更を維持して継続。開始main / 19ae54384fd2dde30ac5b5b987ce9b68d675c305（3c-2 commit済み）、未コミットはtests/odpt_v2_qa_dom.test.mjsだけ。失敗を再現し、期待03:01・実測05:00を確認した。テストのIntl.DateTimeFormat('en-CA').format()は「2026-10-29, 05:01:59」を返し、parseJstInputが要求するYYYY-MM-DDTHH:mm:ssと異なるためnullになり、仮想時計設定が拒否されていた。加えてdatetime-localの秒精度ではミリ秒観測を保持できない。adapter/DOMの不具合ではなくテスト入力経路の問題であり、公開規則は変更しない。

境界テストは実時間modeへ戻した上で固定Date.nowを観測epochへ変更し、手動intervalを1回呼ぶ。reference buildV2QaBoardも同じepochで評価する。発車TについてT-181秒とT-180秒-1msは03:01/redなし、T-180秒とT-180秒+1msは03:00/redあり、T-1msは00:01/redあり、TおよびT+1msはカード除去を確認。根拠はcountdownTextのceil、remaining<=180、およびadapterのdepartureAtMs<=nowMs除外。60分前ゲートは維持し、既存表示contextのUTC秒精度を拡張しない。JST秒入力、仮想時計進行・不正入力・実時間復帰は既存テストを維持する。

harnessはテストファイル内の小さいhelperへ整理。import前に時計・globalを設定し、非同期初期化完了（interval登録または検証error）を待つ。待機はsetImmediateと単調時計の資源timeoutを使い、観測時刻を実sleepで進めない。候補bytesは全8駅分の合成payloadから作り、公開IDとSHA-256/bytesを実際に検証する。fetch監査もstate内integrityと照合する。importごとの連番queryでentryの再初期化を保証し、finallyで元global property descriptor・Date.nowを復元、仮interval・全生成nodeのlistener/children・storage・fetch参照を破棄。import guard失敗・assert失敗にも復元を検証する。ESM module cacheそのものを削除する仕組みはなく、queryごとのmoduleはNodeテストprocess終了まで保持される。常駐runnerや実source再生機能は追加しない。

表示契約はboard.items全体ではなくgroupsごとのカード数・ID順序・section/見出しを基準とする。4シナリオのmode/checked/aria/class、直通alternativeによる同一IDの到着変更、直通のみで候補が減ること、種別/行先/発着時刻/元serviceDate、乗換駅・接続路線・待ち約分・接続保証なし、最早着/限定ラベル、終電/直通終電を確認。8 routeStateと空表示の文言、UNKNOWN両路線伝播とterminalKnown false、INFO非warning、coverage不足warningを確認する。HTMLはFake DOMが読み込まないため、別途標準html.parser.HTMLParserで必須IDの一意性・タグ・module/CSS参照・初期属性・dialog/label参照を検査する。HTML/CSS本体は変更しない。

現行挙動の固定と改善候補：bestはitems全体で選びgroups上限外ならマーク0件、終電も上限外ならバッジ0件となる。補助日の不足は全体warningへ反映するが個別ラベルは今日の2路線だけ。必要日欠落のunavailableでは通知data-stateがokになる場合がある。これらを修正せず回帰期待として記録する。表示改善の判断は別工程で行う。

検証は関連Node57件PASS（16.991秒、v2 DOM20件を含む）、Python20件PASS（10.717秒、HTML3/context5/状態差分12）。Nodeはodpt_v2_qa_dom・adapter・display_runner・preview_selection・terminal_ui・preview_runtime_dom_qaの6ファイル。Pythonはtest_odpt_v2_qa_html・test_odpt_display_context・test_odpt_display_state_diff。結果はdevlogにも記録する。テストPASSはブラウザー実描画・視覚品質の保証ではない。CSS cascade、フォント・折返し・safe-area、dialog focus/アクセシビリティ、HTTP/CSP/cache、実source接続QA、鮮度・公開資格は未評価。既存collector/比較の結果状態をcompleteへ昇格しない。generator/matcher/adapter/DOM、公開v2 gate、applicationPeriod/publicationApproved、原本/store、engine定義は未変更。API・新規取得・Deploy・Commit/Push/Mergeなし。


### Phase 2C-3d-3a 単一Snapshotの非公開DOM接続QA（2026-11-05）

独立read-only API/CLI `scripts/odpt_dom_metrics.py` を追加。contract=`dotchi.odpt.dom-qa` / schemaVersion 1。既定は2026-10-29T03:00:00Z（JST12:00）、千川・氷川台×departure-all/departure-direct/line-all/line-directの8セル。評価順はstation ID・scenario IDの固定順。表示contextは従来の全8駅/4scenario契約を変更せず、DOM評価対象の2駅を独立evaluationScopeへ明示する。1観測instantのみを受け付け、全駅・全境界DOM評価や旧新比較は追加しない。

入力は既存validate_inputs、原本7/store8 JSONのinventory、engine/context/runtime検証を再利用する。既存表示collectorの駅日v2生成・厳密監査部分を`_generate_day`へ抽出し、既存collectorとDOM collectorの両方が同じ処理を呼ぶ。必要D-1/D/D+1を全8駅で一度ずつ生成し（24駅日）、generatorは駅ごとに解放する。生成結果はメモリ内cacheのみ。`_envelope`の厳密なG=C+E・全除外理由/分類・候補integrity・QA counts bindingを8駅すべてに適用してから、実際の各駅stateと候補hash/bytesを合成する。1駅/必要1日でも作れなければ正常DOM評価へ進まない。欠損を0やcompleteに補完しない。

v2 payload・canonical UTF-8 bytes・SHA-256・ID・対象駅/日をメモリで共有する。Node reference boardへ渡すpayload objectとcandidateTextのparsed canonical内容一致、およびTextEncoder bytesとQA stateのhash/byte数一致を検査する。DOMは同じbytesをメモリ内fetchで受け取り、既存entry自身がbytes/hash/公開IDを再検証する。全8駅QA stateを要求する既存DOMに対応し、対象外6駅のstateを仮値で作らない。WARNINGとUNKNOWNは既存規則のままで、WARNINGをUNKNOWNへ昇格しない。除外理由/分類とcoverageは生成証拠に保持し、最小QA state自体には既存通りWARNING fieldを追加しない。

3d-2のFake DOM・固定時計・fetch・manual interval・後始末・board照合を`scripts/odpt_dom_harness.mjs`へ抽出し、旧テストと新runnerで共用する。合成bundle builderはtests側だけへ分離。runnerは`odpt-dom-request/odpt-dom-response` / schemaVersion 1の別protocolとし、既存`runRequest`のcontext/runtime/payload/ID/旅程policy/board/group/best検証を呼ぶ。nowMsはobservationInstantのepochと厳密一致させる。既存bounded subprocess transportをrunner名/response contractのprivate引数だけで共用し、従来runnerの既定I/Oは維持する。request上限8 MiB、response32 MiB、stderr4 KiB、既定20秒timeout（上限120秒）、kill/reapを維持。1セル1Node process。stderrは固定codeのみで、例外本文・原本・旅程をechoしない。

正規化したDOM観測はgroups/cardsの順序・同一board内ID、路線/種別/行先/発着/元serviceDate、直通/乗換/待ち約分/接続保証なし、best/終電、countdown/red、coverage/status/INFO/UNKNOWN、空案内、modeのaria/classとfilterを保持する。referenceは既存adapter。items全体ではなくgroupsとDOMカードを比較し、上限外best/終電を選び直さない。public IDは同一セル参照のみ。CSSや実ブラウザーを模倣した合格判定ではない。

結果はsnapshotId/contentFingerprint、品質/表示context fingerprint、engine/environment、evaluationScope、cells/checks/findings/notEvaluated、domQaStatus、resultDigestを持つ。completeは宣言したNode DOM意味評価8セルの成立だけ。正常0はknown/0、利用不能/不正はmetrics=null。局所未評価は他セルを残し、条件不一致・入力途中変更等の全体失敗では確認できないセル値/生成数値を無効化する。cells/generation/findingsに個別明細上限を適用し、全件集計と省略数を保持する。digestからtimings/resourcesを除く。既存comparisonStatus/displayDiffStatusと公開gateの意味は変更しない。

CLI: `python3 -B scripts/odpt_dom_metrics.py --store <saved-store> --source-dir <saved-source-dir>`。stdoutはSnapshot/評価scope・数値集計・固定finding code・状態・未評価・digest・時間/RSSのみ。payload/DOM/card本文はprivate IPCとメモリ内reportに限定し、候補・原本・reportをpersistしない。終了0=宣言範囲成立、2=部分/省略/条件差、3=入力不正・確定不整合、4=入力/環境利用不能。0でも実機描画・公開資格を意味しない。

engine依存へ新collector/runnerを明示seed追加し、harness/normalizationはimport closureで含める。DOM entry/HTML/selection等の既存依存も維持する。Node標準path/assertの既知依存だけをresolverへ追加し、外部依存は増やさない。DOM entryの動的importは既存の明示seedで封印する。engine値変更により旧engineの結果との同一条件比較は不可。CSS/viewport/font/browserはNode意味評価範囲外として扱う。

ブラウザー実描画、CSS cascade・font/折返し/safe-area、dialog focus/アクセシビリティ、HTTP/CSP/cache、鮮度/公開資格、全駅/全境界DOM評価・旧新DOM差分は未評価。実sourceで発生しないUNKNOWN・不足・空候補・上限外best/終電・境界等は合成テストで確認する。generator/matcher/v2射影・QA state・adapter/DOM/HTML/CSS/UI・公開v2 gateは変更しない。API・新規取得・原本/store変更/複製/移動・実source公開artifact生成・applicationPeriod/publicationApproved変更・Actions/Cloudflare/Deploy・Commit/Push/Mergeなし。


**3d-3a検証結果:** 新規Node接続10件、既存v2 DOM20件を含む関連Node67件PASS（最終21.853秒）。共有処理抽出後の既存表示collector/差分/context/HTMLのPython44件PASS（323.559秒）。最終の新collector15件・品質入力15件・表示context5件・HTML3件のPython38件PASS（131.461秒、先の44件とcontext/HTML8件が重複）。known/0・全8駅stateと1駅欠損・bytes/hash/object不一致、4scenario/直通alternative/上限/best/終電/始発/UNKNOWN/INFO/coverage/WARNING分類/24時超/countdown、DOM不一致、Node起動失敗・timeout・不正JSON/出力上限、後始末、繰返しdigest、store変更・実行後engine変化/runtime不一致、明細上限/確定失敗終了code保持、CLI本文非出力を確認。合成fixtureのみをGit管理する。

**最終実source smoke:** 保存済みPhase 1C store（Snapshot 33af11c1-60f6-47fd-993a-94aa8b469cb1、contentFingerprint 9392342c929297f98c1e8124a563e13dc35764c0f19df17454e11870d3196c6d）と対応原本7件を使用。JST10/29正午、必要日10/28〜30。各run24駅日生成・全8駅QA state PASS。G10,536=C10,128+E408、primary直通7,887/乗換2,241。8セルはすべてknown、items延べ140/groups12/groupsカード48/DOMカード48、best表示8/8、終電バッジ0、serviceState running8。routeStatesはended16/not_started16/running16、terminalKnown true48。Node意味整合check88 PASS、FAIL0、findings0、省略0、domQaStatus complete、終了0。正午に発生しない始発/終電/空候補/不足/UNKNOWN/上限外best等の条件は合成で確認し、実sourceでの当該条件の検証とは扱わない。

最終固定engineで2回実行し、resultDigestは両方 `b1e58a0e9c83cd49a6978f6ab603c2dbe31e84e60633dcbebbf8c7ece5a75e5a` で一致。qualityContextFingerprint `2583ffb6846cb491894c0a0b408abcc77178352a44e04a0f73195e6f155cdf7f`、displayContextFingerprint `74738b5c6562b573b061b43a02dad629f58eed887276d1d5afbbfea6b328976c`。原本7/store8 JSONのhash/bytes/identityは各runと2run全体で前後一致し、engine/runtimeも一致。

最終run時間75.090秒/69.496秒。親process peak RSS423,534,592/435,683,328 bytes、Node子最大RSS377,700,352/378,163,200 bytes（macOS、同一親processでの累積peakであり同時合計peakではない、回帰と一部並行）。セルrunnerは各8起動、反復計16起動。環境probe起動は未計測。最終前のCLI経路確認でも8セル正常・77.422秒/8起動を確認したが、途中engineの結果を最終digestと同一条件比較しない。実source確認のセルrunnerは初期CLIを含め計24起動。以前のboard専用runnerよりNode RSSが増える実測を記録し、性能最適化は追加していない。

3d-2時点のengineFingerprint `c5544d758801cfc0e1b7ee10c171a3f4d964524d15066315ac43f00b268c6f15`（28依存）から、最終 `8dd8a21a6d50ef30d280ac2e24bfe09f915f28093b25831f7a0842e8c8a09399`（31依存）へ変更。Node24.15.0/ICU78.2/CPython3.14.5で検証した。旧新engine結果を同じ条件の差分とは扱わない。git diff --check PASS、branch main・HEAD 2b942f1a31c33b3e7e3c086425f31cf18cac7309を維持。実データ公開未承認と既存gateを維持。

### Phase 2C-3d-3b 全8駅DOM QAとcoverage例外確認（2026-11-05）

既存`dotchi.odpt.dom-qa`/schemaVersion 1を維持し、collector APIの`station_ids`とCLIの明示flag `--all-stations`だけを追加した。引数なし既定は従来のHikawadai/Senkawa×4＝8セル。明示全駅は品質context内の固定駅順で8×4＝32セル。scenario集合と順序、固定時刻/Asia-Tokyo、DOM/adapter規則、終了codeは維持する。evaluationScopeはDOM対象駅・scenario・instant・requiredServiceDatesと全8 QA state駅を別々に記録する。全8駅DOM対象なら`all-station-dom-evaluation`をnotEvaluatedから除く。駅選択は既知の重複なし駅IDのみ許可。

**既定8セル実source確認:** Snapshot `33af11c1-60f6-47fd-993a-94aa8b469cb1` / contentFingerprint `9392342c929297f98c1e8124a563e13dc35764c0f19df17454e11870d3196c6d`。engine `1cf13c8139e04e2c74c93280fc7eb926a0035c2118457c954e14625be52e7dcb`、quality context `6aa60b19bf2806d256473975df5dd8c1dda1a27d8816d549d8c2852592352a43`、display context `5444f795e6ef652fe56ad61c0a895956ccc4f011c967cb00f7b833a495f8106f`。8/8 known、PASS 88、items140/groups12/cards48/DOM48/best8/terminal badge0、駅日生成24、Node 8起動、complete/終了0、65.973秒、親peak426,672,128 bytes/Node peak378,040,320 bytes。引数なしCLIの互換を確認。

**全駅32セル反復:** 固定2026-10-29 12:00 JST、serviceDate 10/28・29・30、上記同じengine/context/runtime。両runとも原本7/store8 JSONのhash/bytes/identityが前後不変。全8駅QA state PASS（24駅日）、8×4 known、PASS 352、finding/省略0、G10,536=C10,128+E408、primary direct7,887/transfer2,241、items延べ576、groups48、groups/DOM cards192、best mark32、terminal badge0。各run generation24回・Node32起動。resultDigest両方`68edbaffcc698f3c1f782013e24d66594a0b9f5a27e56d0ad93ba7c01f253703`、scope/checkCounts/findings一致。各run124.414/124.282秒、親peak424,685,568/433,422,336 bytes、Node child peak389,816,320 bytes。合計248.740秒/64 cell runner起動。現engineでの既定8セル65.973秒/8起動と比較し、4倍のDOMセルに対して所要時間は約1.89倍、駅日生成は24回のまま。

**10/31 coverage例外:** 保存済みGTFS feed periodは2026-09-19〜2027-03-12。固定観測2026-10-31 12:00 JSTの必要日10/30・31・11/1を元sourceから生成し、Hikawadai×4 scenarioで実source DOM QAを実行。全8駅QA state 24/24駅日PASS、対象4セルknown、PASS44、findings0、省略0、complete/終了0、4 runner起動、56.152秒、原本/store inventory不変。Hikawadai 10/31 generatorはG405=C402+E3、primary direct240/transfer162、excluded 3件すべてquality WARNING、routeCoverage route6 complete(385 scheduled trips)/route9 insufficient(475 scheduled trips)。既存3b-2の保存済みgenerator診断ではroute9 `unique_match=209`, `unmatched=6`。DOMでは副都心線`データ不足`警告、10/31と11/1 route9=`data_insufficient`・terminalKnown=false、10/30 route9=`ended`を4 scenarioすべてで確認。serviceStateはrunning、始発・終電の断定なし、terminal badge0。collectorの現在の公開観測項目にはraw matcher行明細を追加していないため、unmatched 6は既存の保存済み診断を根拠とし、このDOM結果から再推定した値ではない。

既存synthetic DOM suiteはrunning/not_started/ended/no_candidates/unknown/data_insufficient/start_unconfirmed/terminal_unconfirmed各表示、両routeへのUNKNOWN伝播、INFO-only正常、coverage警告、上限外best/terminal、24時超、既知0とunavailable等を含む。3bでfixture規則の重複追加は行わず、PythonのDOM collector 18件、関連Node runner/adapter/DOM 50件PASS。全source例外が実データで現れたという意味ではない。現engine fingerprintは前3d-3aの31依存engine `8dd8a21a...`から変更され、3b内のdefault/32/10-31 runsではNode24.15.0/ICU78.2/CPython3.14.5の同一runtimeと同engine/contextを使用した。旧fingerprintとの結果比較は同条件比較に使わない。ブラウザー実描画、CSS/フォント/safe-area、focus/アクセシビリティ、HTTP/CSP/cache、全駅×全境界、鮮度・公開資格は引き続き未評価。

### Phase 2C-3d-4 総合QAと評価範囲（2026-11-05）

開始時の`main`/HEAD `d2325dc67811463381f476e275a829a0c41cf5ed`、3d-3b commit済み・cleanを確認。3d-3bのengine fingerprint `1cf13c8139e04e2c74c93280fc7eb926a0035c2118457c954e14625be52e7dcb`（31依存）、quality context `6aa60b19bf2806d256473975df5dd8c1dda1a27d8816d549d8c2852592352a43`、display context `5444f795e6ef652fe56ad61c0a895956ccc4f011c967cb00f7b833a495f8106f`、Node24.15.0/ICU78.2/CPython3.14.5を軽量入力検証で再確認。Snapshot ID/content fingerprint、原本7件・store8件のSource hash/bytesとpost-validationはPASS。同一fingerprintの3b実source結果は再利用し、既定8/32と10/31 DOM全体生成は重複実行しない。

**既存3b実source健全性:** 引数なし既定8セルは8/8 known、88 checks PASS、groups/cards48、best mark8、terminal badge0、findings0、complete/exit0。32セルは32/32 known、352 PASS、groups/cards192、best mark32、terminal badge0、findings/省略0、complete/exit0。resultDigest両run一致、scope・checks・findings一致。known/0・missing・unavailableは各既存契約で別状態。CLIの8セル既定を維持し、32セルは`--all-stations`で明示する。`complete`はこのNode DOM意味評価範囲だけであり、基盤全体・実画面品質のcompleteではない。

**境界DOM実source:** 固定時刻、氷川台・千川の2駅×4scenario、各時刻で日付D−1/D/D+1を含む別の3日envelopeを使用。時刻はJST 10/29 23:59:59（UTC `2026-10-29T14:59:59Z`）、10/30 00:00:00（`2026-10-29T15:00:00Z`）、00:12:59（`2026-10-29T15:12:59Z`）、00:13:00（`2026-10-29T15:13:00Z`）。quality contextはauxiliary 10/31を加えた同一context fingerprint `4d0f5fa36318d51a9009092fd05bbe309594968e6af346d7c5c016ba5177fe56`。必要serviceDateは順に10/28–30、10/29–31、10/29–31、10/29–31。4点すべて8/8 known、88 PASS、findings0、complete/exit0、DOM groupsとcards一致、best mark8。00:12:59では合計8 cards/8 terminal badges、00:13:00では8セルすべてknown/0で0 card・0 terminal badge、serviceState not_started。JST日付変更前後の23:59:59/00:00でもitems38/cards38・best8・terminal badge16を維持し、元date envelope/route stateが変わることを確認した。各評価はNode8起動・24 station-days生成、generatorはscenarioごとには再生成しない。

各境界resultDigest（順に上記4時刻）は `8bb0ce1bb064161f41ba20a9d9b9d577d42692c52dc497a1672fa35013940f24`、`a4c2a74273106b8026c59e38f469e6700c598bb86f7220cc599c41651aa2d4cb`、`42c0e4c39ef1e8821151aa228a85c256c021ec16dc6b5fe0c94e3f8df81f4c53`、`8ddc014d31ef222f355508e57b7d56f586d30cd56579eff15d4db3c1a00616a4`。4時刻は異なるevaluation context/scopeなので、互いのdigest一致は期待せず、3b 32-cell repeatを同条件決定性証拠とする。

境界4 runの合計263.025秒、32 Node cell起動、96 station-day生成（各instant別に8駅×3日）。4runを行った単一親processのpeak RSSは434,241,536 bytes（約414 MiB）、Node child peakは393,064,448 bytes（約375 MiB）。いずれも入力のstart/end inventory不変、Node timeout/失敗/再試行0、engine/runtime不変。単一instantを個別呼出しする現契約のため、複数時刻でstation-day cacheを共有せず、各instantで24件生成する。これは最適化ではなく測定した実行境界であり、常駐runner等は追加しない。3bの既定8セル約66秒、32セル約124秒/Node子peak約372 MiBと同じ環境実測を比較基準にする。実行負荷とRSSは環境/並行処理で変動し、実測時間はdigestに含まれない。

**10/31 exceptionのsource層別根拠:** 既存の10/31 DOM評価はJST正午、必要日10/30・31・11/1、Hikawadai×4でcomplete/4 cells/44 checks PASS。今回DOM全体を再生成せず、10/31 Hikawadai generatorを1駅日だけ再実行してraw row数の関係を集計した（trip ID/本文は出力・保存しない）。generatorは全405 rows、route9は215 rowsで`unique_match=209`、`unmatched=6`。そのunmatched6のうち3 rowsはdiagnostic WARNINGかつprimaryなし（v2から除外）、残る3 rowsはWARNINGでなくprimary候補に残る。従ってG405=C402+E3、E3はすべて`quality_warning`/WARNING、C402にunmatched3が残る。unmatched6とWARNING3は重複3件であり独立件数として加算しない。

v2 routeCoverageはroute9 scheduledTripCount475、originTripCount215、dataInsufficientCount0、transferDataInsufficientCount0、directCandidateCount111、transferCandidateCount212だが`insufficient`。`_route_state`はrow WARNINGまたはmatched/unique_match以外をinsufficientにするため、対象215件中のWARNING3とunmatched6の両方がcoverage条件に関係する。各原因を除いた反実仮想や元データが不完全になった発生機序はこの調査で判定しない。候補payloadにroute9行が存在しても、adapterは`routeCoverage !== complete`のため10/31および11/1 route9を`candidateEligible=false`にしてitemsへ出さず、`terminalKnown=false`とする。10/30 route9はended。DOMは「副都心線：データ不足」、通知warningを表示し、終電バッジを付けない。これは既存の記録・コード伝播であり、品質不合格/公開承認判定を新設するものではない。補助日不足は必要serviceDateの欠落としてunavailable/validation failureに分け、候補0扱いしない。synthetic DOM testsで不足補助日warning/no extra route labelと必要日のfail-closedを確認。

**固定境界のsynthetic補完:** `odpt_v2_qa_dom.test.mjs`でcountdown T−181s/T−180s−1ms/T−180s/T−180s+1ms/T−1ms/T/T+1ms、秒切り上げ・180秒class、発車epochでのcard removalを検査。別harnessテストで60分gate境界、24/25時台、serviceDate保持、全8 routeState、UNKNOWN両路線伝播、INFO-only正常、coverage不足、上限外best/終電を確認する。実source固定境界は23:59:59、midnight、00:12:59/13:00のみ。始発境界の実source、時刻別全8駅、全境界時刻集合のDOM再生は未評価。既存3b-2/3c-2の全駅表示model・state境界結果をDOM実source結果へ読み替えない。

### 品質検証基盤の到達点と比較契約

| レイヤー | 判定できる範囲 | 実データで確認済み | 限界・公開資格との関係 |
|---|---|---|---|
| 2A input/source | Source/Snapshot契約、7原本hash/bytes、store8 JSON、fingerprint/context/runtime一致、途中変更 | 同一保存Snapshotのread-only再検証 | 取得時刻/鮮度、異世代Source差分はこの実行では未実証。readyは入力条件のみ |
| 2A/2B JSON・GTFS semantics | ODPT JSON/GTFS正規化と構造・意味差分、曖昧/opaque coverage | Phase 2Bの同一Snapshot比較と既存テスト | 同一Snapshot差分0は異世代同一性を示さない。opaque GTFS補助関係/StationTimetable keyはpartial |
| 2C generator/matcher | G、raw match status、primary/alternative、診断と理由分類、直接/乗換内訳 | 保存Snapshotの10/29–31集計、10/31 Hikawadai route9を単日再集計 | source correctnessや全運行日を証明しない。比較対象の異世代実Snapshotは未評価 |
| 2C v2 candidate/audit | G=C+E、strict exclusion reason/classification、candidate hash/bytes/ID、routeCoverage、QA state | 8駅32セル、10/31 exception | `insufficient`/UNKNOWN/WARNINGの由来と表示制御は観測するが、内容の正当性を確定しない。public validator条件とは別 |
| 3b adapter board/model | horizon/60分gate/direct filter/cardLimit/best/group/routeStates/terminalKnownとmodel diff/state diff | 既定/32セル・境界表示model自己比較、10/31不足 | model self-diffは別世代一致性/ユーザー利用品質/公開資格を保証しない |
| 3d DOM意味 | 同じ候補bytes/nowMsのboard.groups→DOM構造・順序・文言・class/countdown/状態 | 3b全8駅32セル、10/31 4セル、境界2駅×4点、合成例外 | Fake DOMでCSS/layout/browser/focus/networkは評価しない。`domQaStatus=complete`は宣言scope内のみ |

比較可能な結果には、同じsource Snapshot/同一の両side snapshot契約、同じevaluationContext（service dates、station/route、transfer wait、policy）、明示timezone/observation instant/scenario、同じengineFingerprintと依存bytes、runtime/Node/ICU/Python/tzdata、必要3日データが必要。source世代比較では異なるSnapshot自体を許すが、同じcollector/engine/context/runtimeと両側で可用な同じ評価セルが揃うことが条件であり、missing/unavailable/partialはzeroへ置換せずindeterminate/partialとして残す。resultDigestから実行時間/RSSを除外し、異なるengine fingerprintの結果は同条件の再現性証拠に混ぜない。

### 公開前に残る事項

- **データ来歴/鮮度:** 新しい異世代Snapshotの取得・比較、取得成功時刻と取得方法の証跡、ODPT News/GTFS版・有効開始日の根拠、実ダイヤ切替時点。
- **承認/ライセンス:** 実データ表示条件・クレジット/再構成リスク/配信条件の確認、承認者・承認範囲・期限を含む`publicationApproved`手順と、実データ用`applicationPeriod`根拠。現状未承認・未設定。
- **coverage/運行日:** insufficient/unknownをpublic bundleでどう拒否/限定するかの運用、祝日・振替休日・臨時改正・運休/例外日データの網羅性、D±1不足時の更新手順。
- **実画面/配信:** 対象端末の実ブラウザー画像、CSS cascade/viewport/font/折返し/safe-area、dialog focus/keyboard/accessibility、HTTP/CSP/cache/offline/失敗時表示を実測する。
- **運用復旧:** 取得→検証→隔離→人手承認→公開→期限切れの実更新runbook、異常通知と担当、誤った更新のrollback/旧版復帰と検証。

公開gate/承認workflowはこのPhaseで変更していない。source hash一致、意味差分0、display/DOM self-check completeのいずれも鮮度・正確性・public eligibilityを保証しない。公開v2 gateとpublication approvalを独立に通過するまでは実sourceは非公開のまま扱う。

## ODPT-2D-2 手動取得基盤実装状況（オフライン範囲）

`scripts/odpt_manual_fetch.py` に、合成response bytesを用いるcapture試験経路を追加した。固定7 sourceのraw bytesを新規private batchへ排他的に保存し、既存Phase 1B readerのODPT JSON/GTFS metadata検査を適用する。Source recordは既存strict schemaでvalidateし、別のhistory envelopeへ保存する。7 sourceが同一batchですべて成功した時だけ既存`validate_snapshot`に通るfetch Snapshotを作成する。`contentFingerprint`は既存のsourceId/hash/bytes定義を再利用し、`crossSourceConsistency=not-evaluated`とする。publication approval、provenance semantics、applicationPeriodは変更していない。

**未実装:** ライブHTTP transport、TLS/redirect検証、秘密管理からのkey読込、実endpoint/selector証拠の永続化、attemptを跨ぐretry追記、失敗時の完成history、Phase 2A/2B/2Cを一括評価する非公開CLI入口。従ってこのCLIは常にネットワークを拒否し、実データ取得には使用できない。公式仕様の確認、transport/履歴の実装とレビューを別作業で終えるまで、2D-2は未完了とする。capture test seamはprivate試験用であり、実source用のbatch作成APIではない。

合成テストは7件成功、1件欠落時のSnapshot非作成、既存batch/symlink拒否、不正JSON、サイズ上限、ライブ通信無効を確認する。hashは作成時に検証するが、Snapshot commit直前の保存ファイル再読照合は未実装。中断・手動retry・秘密漏えい・不正ZIP・hash mismatchの一連テストも未実装であり、現状の完了条件には含まれない。

## ODPT-2D-2A transport・履歴・証拠・raw再照合（2026-11-07）

上記2D-2の部分実装を拡張。`scripts/odpt_manual_fetch.py`の既存record生成とSnapshot契約を維持し、以下を実装した。前節の未実装記述は2D-2終了時の履歴であり、現在の残件は本節を参照。

- transportは交換関数を注入可能。実adapterは標準TLS証明書/host検証、接続15秒・read30秒、非圧縮body上限128 MiB、HTTP 200とsource別MIMEを要求する。未加工bodyを保存しJSON再整形を行わない。Content-Length不一致、未知encoding、サイズ超過、parse失敗は成功にしない。
- JSONのredirectは拒否。GTFSのみ最初の302からHTTPSの`dataodpt.blob.core.windows.net`/443へ1回許可し、userinfo・fragment・credential query/echo等を拒否。転送先の署名URLはメモリだけに保持し、API key/header/cookieを転送しない。このhostは既存GTFS取得scriptの制約に由来するもので、今回公式仕様を新規確認したものではない。`date=current/next/latest`は未使用・未確認のまま。
- secretはprovider経由で注入し、実値の登録/読込は未実施。環境変数providerを用意したがCLIは呼ばない。認証付きリクエストURLは通信に必要なメモリ内だけで使用。例外全文・生header・Locationは保存しない。記録するcontentTypeは許可MIMEだけ、errorは固定code。credentialをそのまま/URL encodeでechoするbodyは保存拒否。任意の符号化によるechoの完全検出を保証しない。
- 新規外部private batchに`batch.json`、`attempts/<attemptId>/started.json`・`result.json`・`evidence.json`、`raw/<固定名>`を保存する。開始前にinterrupted Source recordを耐久保存し、強制終了でresultが残らなければ中断とみなす。手動retryは前attemptを参照し、全履歴を残す。結果はraw/証拠の耐久保存後にだけ確定。途中の書込失敗は成功を返さず、孤立rawや壊れたhistoryは上書きせず停止する。自動retryなし。
- private path検証、symlink拒否、排他的作成、atomic link・fsync、directory flockで同一batchの操作を直列化する。0700/0600を使用する。POSIXローカルfilesystemを想定し、同一ユーザーの別processによる意図的な改変・ネットワークfilesystemのdurabilityは保証対象外。
- finalizeは全historyのstrict Source契約・retry関係・同一batch、固定7成功recordを検証し、全rawを二巡再読してhash/bytes、sourceIdから固定filename対応、JSON/GTFS形式・metadataを検証する。最後にのみstrict fetch Snapshotを排他的に確定する。JSONの業務的な路線/便対応や同一ダイヤ版性はここでは証明せず`crossSourceConsistency=not-evaluated`。既存provenance/public period/publication承認契約は変更せず、batch側で`applicationPeriod=null`/`publicationApproved=false`を保持する。Snapshot strict schemaへ承認fieldは追加しない。

CLIの実通信は常時終了2で、実adapterにも通信無効guardがある。テストのTLS adapter検証はHTTPSConnection全体をmockへ置換して行う。実API、実データ、既存raw/store、Cloudflareにはアクセスしない。実TLS/転送/公式endpoint・適用期間・版整合・公開資格は未評価。

2D-2Bでは、このbatch履歴と必要7原本を既存2A/2B/2Cへ安全に渡す入口を用意する。既存store readerは`sources/`7記録＋snapshotのみを受理し、retry親が欠けると契約検証で失敗するため、本batchを直接渡さない。Source/Snapshot schemaの意味を変えず全attempt契約を検証するadapterが必要。新規評価engine、実v2公開builder/runtime、公開承認は今回の対象外。

## ODPT-2D-2B 手動取得batchと既存評価の接続

`odpt_evaluation_input.load_input()`は従来strict storeを既存readerで読む。`batch.json`がある場合は専用read-only validatorへ進み、壊れたbatchをlegacy扱いへfallbackしない。完成Snapshotが必須で、全attemptの開始/結果・補助証拠とretry親関係を保持して`validate_snapshot(snapshot, all_attempts)`を実行する。sourceごとに単一root・非分岐chain・成功leaf一意・Snapshot選択一致を要求し、失敗/中断を成功に置換しない。固定7 rawとsourceId対応・hash/bytes・JSON/GTFS形式/metadataを二巡照合し、metadata bytesの前後hashも比較する。外部原本をコピーせず選択済み7 Source recordと全履歴をメモリ上で既存評価へ渡す。

2A source diff、2B train/GTFS semantic diff、2C quality inputのstore読込参照だけをadapterへ接続した。既存strict schema・store reader・比較アルゴリズム・generator/matcher/v2射影/board/DOM規則は維持する。2Cのphysical inventoryは旧storeの8 JSON固定から、batch/全attempt/evidence/Snapshotを列挙する方式へ拡張。件数表示も実数とし、同じmetadata bytes・identityの前後不変を検証する。新規adapter/取得処理等も自動import依存追跡でengine fingerprintへ入るため、旧engineの検証結果と同条件比較しない。

`odpt_fetch_evaluate.py`はstage別の非公開入口。2Aでは旧rawも明示照合して既存bytes/hash差分を呼び、2Bでは統合7 source意味差分を呼ぶ。2Cでは明示service dates・固定UTC観測1点・DOM対象駅を受け取り、同じ凍結engine/context/runtimeで品質差分、board/model/state差分、旧新それぞれのNode DOM意味QAを順に実行する。旅程生成/QA stateの対象は既存契約の全8駅、scenarioは固定4種。必要3日不足は補完しない。入力矛盾・readiness不成立・失敗・途中変更は停止し、未評価を0件や正常へ変換しない。partial/indeterminateは既存範囲の限界として保持する。これは異世代DOM専用diff engineではなく、両側が同じboard→DOM規則を満たすことを別々に検証するもの。

結果はメモリのみ、CLIは状態とscopeだけを出す。終了0も公開資格・鮮度・同一ダイヤ版性を意味しない。終了2は失敗・比較不能またはpartial。raw/旅程本文・field値・秘密・local pathをCLI結果へ出さない。batchのpublicationApproved=false/applicationPeriod=nullとSnapshotのcrossSourceConsistency=not-evaluatedを要求・維持する。生の評価APIの結果は非公開QA専用であり、公開物に含めない。

実APIアクセス、新規実取得、実異世代Snapshot、実ブラウザー/CSS/HTTP/CSP/cache、公開承認・適用期間・ダイヤ版根拠の審査は行わない。2D-3では公式取得先/認証/selector・切替時点を確認し、別途許可された隔離取得と鮮度/期間/版整合の根拠を揃える。ライブ通信は引き続き無効。

## ODPT-2D-3A ライブCLIの最小配線とオフライン検証

2D-3の調査結果を既存実装へ照合した。通常CLIが無条件停止する点、provenance/evidenceと評価adapterがoffline固定である点を、本節の範囲で修正する。外部通信による仕様照合や実取得は実施しない。

- `run_fetch()`は既存`new_batch/acquire/finalize`とHTTP transportを使い、固定7 sourceの新規batchを取得するdriver。各結果を確認して最初の失敗/中断で停止し、不完全なSnapshotを確定しない。正常時だけ既存二巡raw照合とstrict Snapshot検証を行う。raw再照合処理をhelperへ共通化した。
- `fetch`/`retry` CLIはdriverへ配線し、Pythonテスト引数のexchange/providerでmock検証できる。通常の実行はprovider読込・保存先作成より前に停止する。実adapterとtransportの入口には常に拒否する`_require_live_policy()`を置き、既存定数の変更や通常flagだけでは通信できない。任意のURLやtransportをCLIから指定できない。環境providerは未接続、実キーは未読取・未使用。
- `retry --source`は対象の失敗/中断を新attemptで再試行し、残る未試行sourceへ進む。過去の成功rawを再照合し、成功sourceを再取得しない。取得間にプロセスが止まると次sourceのattempt自体がないため、最初の未試行sourceを明示した続行も許可する。その最初のattemptに偽のretry親を付けない。他の失敗sourceが残る場合や対象が成功済みなら停止。保存失敗で孤立raw/壊れたhistoryが残る場合の自動修復は行わない。
- 補助batch/evidence v2は`offline-injected`と将来の`live-https`を区別。既存v1はofflineのみ受理する。`validate_batch`をhistory/adapterで共有し、schema version・exact fields・UUID・provenance・承認状態を検査。evidenceはbatchのversion/transportとの完全一致を要求する。実際のacquireは注入exchangeならofflineを要求し、labelを利用者optionでliveへ変更できない。新規v2のlive形式は将来のnative transport用であり、現在native transportはpolicy停止で到達不能。
- Source/Snapshot strict schemaは変更しない。snapshotId/contentFingerprintと来歴の意味を維持し、日時は従来どおりSourceのstarted/finished/retrievedAtに保持する。batchのretrievedAt=nullは従来の集約未設定であり、取得時刻を補完/捏造しない。publicationApproved=false/applicationPeriod=null/crossSourceConsistency=not-evaluatedを維持する。
- live形式はテスト内の合成履歴として構成し、全retry/strict契約・hash/bytes・2A/2B/2Cを実adapterで検証する。これはprovenanceの整合性検査であり、手編集された記録の外部真正性や実取得成功の証明ではない。署名基盤などは追加しない。

取得先は既存`endpoint()`の固定7 sourceだけ。operator/railway filter、GTFS file pathと認証queryは既存値を維持し、未確認のdate selectorやページングを追加しない。TLS/timeout/status/MIME/redirect/サイズ/秘密非出力の既存制約を再利用する。現行値を公式確認済みと扱わない。次工程では公式URL・認証・filter・date省略時の扱い・全件取得条件を照合し、対象/保存先/通信範囲の明示許可と、policy停止の別途レビュー付き変更を経る。旧取得script、既存実原本/store、公開経路は使用・変更しない。

<a id="phase-2d-3b"></a>

## ODPT-2D-3B 公式仕様との照合・初回実取得準備（2026-11-07）

**結論:** 指定されたPDF 2件とGTFS画像をローカルで直接確認し、根拠ページを追記した。API一般仕様・検索上限・date適用範囲・GTFS URL/認証/形式は確認できた。一方、API仕様はdatasetごとにendpointを確認するよう明記し、東京メトロの固定6 JSONごとの確定endpoint/filterと全件性の保証は資料だけでは確定できない。JSON各sourceの総合分類はC、GTFSのURL/認証/形式はAで、省略版等はC。`date`省略は取得後に版を審査する暫定案で、現行版の指定ではない。今回、資料は読取のみ。文書3件以外の変更、実装・テスト・実通信・既存原本/store・公開経路への操作はない。

### 根拠の所在と確認限界

公式資料の確認日は**2026-11-07**。U1/U2はリポジトリ内PDFの本文をPDFKitで読取、ページ番号を確認。U3は指定PNGを直接表示して読取。画像のページ番号は対象外。資料は参照場所から移動・変更・Git追加していない。

| ID | 資料名・版 | ページ・所在 | 今回使う根拠／限界 |
|---|---|---|---|
| U1 | ODPT API仕様 Version 4.16（2026-09-03）、`ODPT_開発者サイト_API仕様.pdf`（全103ページ） | pp. 7–10（API一般・endpoint/search/dump/filter/auth）、p. 9（GET例/status） | HTTPS REST API、`acl:consumerKey`をqueryに指定、query値はURI encoding、property filter、複数値・複数property filter、検索結果がシステム上限を超えた場合は上限以下へ絞った結果を返し必要データをquery filterで再検索、datasetごとのendpoint確認が必要。数値上限と本7 source固有のendpoint/filterは資料の一般説明だけでは確定しない |
| U2 | ODPT APIに関する補足、`ODPT_開発者サイト_APIに関する補足.pdf`（全6ページ） | p. 1（対象範囲）、p. 6（現行/次期/最新） | 記述の対象は会員ポータル経由で提供されるデータ。`current`=現在適用、`next`=明日以降最初に適用する次ダイヤ、`latest`=適用日が最も後のダイヤ。東京メトロ既存GTFS URLへの適用・date省略時の版は示していない |
| U3 | 東京メトロ 鉄道関連情報、ODPT公式カタログGTFSリソース画面（2026-11-07） | 画像、ページ番号対象外 | URL `https://api.odpt.org/api/v4/files/TokyoMetro/data/TokyoMetro-Train-GTFS.zip?acl:consumerKey=...`、認証query `acl:consumerKey`、形式GTFS/GTFS-JPを画面上で確認。実キーは表示されておらず、資料は改変していない |
| W1 | ODPT公開Webページ（Codex閲覧、2026-11-07） | 下記リンク先 | 補助確認としてカタログのJSON/GTFS形式を確認。URL・認証の直接根拠はU3画像。 |

W1の参照先は[GTFSリソース](https://ckan.odpt.org/dataset/train-tokyometro/resource/d4f11962-1c5a-4316-9a16-7fb229c227ea)（GTFS/GTFS-JP）、[列車時刻表リソース](https://ckan.odpt.org/dataset/r_train_timetable-tokyometro/resource/f030d032-c3ce-4f3f-ba25-f3b78fbd5848)（JSON）、[駅情報](https://ckan.odpt.org/dataset/r_station-tokyometro)・[路線系統情報](https://ckan.odpt.org/dataset/r_route-tokyometro)・[駅時刻表](https://ckan.odpt.org/dataset/r_station_timetable-tokyometro)（JSON掲載）。個別JSON endpointはPDF記載のdataset別確認事項に従い、ここで推定しない。U3画像のURLはGTFSファイル配布先であり、実API/GTFS URLへ通信していない。

### 固定7 sourceの照合

コード根拠は[`odpt_source_contract.py`](../scripts/odpt_source_contract.py)の`SOURCE_FILES`と、[`odpt_manual_fetch.py`](../scripts/odpt_manual_fetch.py)の`endpoint/transport/evidence_for/run_fetch`。分類は **A=公式資料と一致、B=公式資料との不一致あり、C=公式資料だけでは未確定**。PDFのpp. 8–10はAPI一般のendpoint形式・認証・filterを示すと同時に、実際のendpointはdatasetごとに確認するよう指示する。よってJSON 6件は形式上のAPI一般仕様との一致（A相当の部分）と、東京メトロ個別endpoint/filter/全件性の未確定（C）が併存し、source全体をCとする。既知の公式記載に反する設定は見つからず、B該当はない。GTFSはU3画像上のURL・認証・形式が現行初期設定と一致するため当該項目A、date省略時の版・転送先等はC。

現行baseは`https://api.odpt.org/api/v4/`。下表の`O`は`odpt:operator=odpt.Operator:TokyoMetro`、`Y`は`odpt:railway=odpt.Railway:TokyoMetro.Yurakucho`、`F`は`odpt:railway=odpt.Railway:TokyoMetro.Fukutoshin`。複数filterを同時に送るが、公式の組合せ動作も確認対象とする。

| source（保存名） | 公式endpointの根拠 | 現行endpoint（base以降）・filter | 必要な取得範囲（設計上の契約） | 項目別／source全体の判定 |
|---|---|---|---|---|
| `metro.railway` (`Railway_all.json`) | U1 pp. 7–10はAPI検索/dumpの一般endpointを説明。dataset個別の対応は未記載 | `/api/v4/odpt:Railway`（現行検索形）、O | 東京メトロの全路線系統。`all`は全事業者ではない | API HTTPS/auth/search形式=A相当(p. 8–9)、個別URL・Oの適用・全件性=C、全体C |
| `metro.station` (`Station_all.json`) | 同上 | `/api/v4/odpt:Station`（現行検索形）、O | 東京メトロの全駅レコード。行先名/路線駅対応・参照解決に使用 | API HTTPS/auth/search形式=A相当(p. 8–9)、個別URL・Oの適用・全件性=C、全体C |
| `metro.train-timetable.yurakucho` (`TrainTimetable_Yurakucho.json`) | U1 pp. 7–10はAPI一般仕様。列車時刻表の型はpp. 2–3 | `/api/v4/odpt:TrainTimetable`（現行検索形）、O+Y | 有楽町線の全列車時刻表。全方向・提供される全calendar、途中駅eventを保持 | API HTTPS/auth/search形式=A相当(pp. 8–9)、Metro個別URL・O/Yの適用・全件性=C、全体C |
| `metro.train-timetable.fukutoshin` (`TrainTimetable_Fukutoshin.json`) | U1 pp. 7–10はAPI一般仕様。列車時刻表の型はpp. 2–3 | `/api/v4/odpt:TrainTimetable`（現行検索形）、O+F | 副都心線の全列車時刻表。同上 | API HTTPS/auth/search形式=A相当(pp. 8–9)、Metro個別URL・O/Fの適用・全件性=C、全体C |
| `metro.station-timetable.yurakucho` (`StationTimetable_Yurakucho.json`) | U1 pp. 7–10はAPI一般仕様。駅時刻表の型はpp. 2–3 | `/api/v4/odpt:StationTimetable`（現行検索形）、O+Y | 有楽町線の全駅・全方向・提供される全calendarの駅時刻表 | API HTTPS/auth/search形式=A相当(pp. 8–9)、Metro個別URL・O/Yの適用・全件性=C、全体C |
| `metro.station-timetable.fukutoshin` (`StationTimetable_Fukutoshin.json`) | U1 pp. 7–10はAPI一般仕様。駅時刻表の型はpp. 2–3 | `/api/v4/odpt:StationTimetable`（現行検索形）、O+F | 副都心線の全駅時刻表。同上 | API HTTPS/auth/search形式=A相当(pp. 8–9)、Metro個別URL・O/Fの適用・全件性=C、全体C |
| `metro.gtfs` (`TokyoMetro-Train-GTFS.zip`) | U3画像に完全URLと認証query。U1 p. 8は一般query認証 | `/api/v4/files/TokyoMetro/data/TokyoMetro-Train-GTFS.zip`、operator/railway/dateのqueryなし | 東京メトロの配布ZIP全体。アプリの8目的地だけに切り出さない | URL・認証・形式=A(U3)、date省略時の版・MIME・転送先=C、総合A（取得版は別途要確認） |

全source共通の認証・URI・形式・CLI適合は次の通り。

| 項目 | 現行実装と照合結果 |
|---|---|
| 認証 | GET queryに`acl:consumerKey`を追加。U1 p. 8–9、U3画像と一致(A)。query parameterとして使用する。環境provider `env_credential()`は`ODPT_API_KEY`だけを読む設計だが、通常CLIへ未接続。今回は呼んでいない |
| URIエンコード | U1 p. 8はquery parameter値をURI encodeするよう指定。現行`urlencode(...)`はquery名/値をencodeしており一般仕様と一致(A)。TokyoMetro固有filter値・応答動作はC。secretは今回読取・使用していない |
| JSON 6件の形式 | W1はJSON掲載(A)。実装はHTTP 200、`application/json`または`application/ld+json`、UTF-8のobject配列を要求。HTTP MIME・配列形・個別fieldの公式照合はC。空配列も現行取得validatorを通る。`_parse_json()`はJSON key重複等を拒否するが、各rowの業務fieldをstrict Source契約で検証するわけではない |
| GTFSの形式 | GTFS/GTFS-JPはA(U3/W1)。実装はHTTP 200、ZIP/octet-streamを許可し、ZIP安全検査、必須7メンバー、feed_info 1行とversion/期間を要求。これらは既存入力契約で、GTFS一般仕様の全配布物が必ず通る保証ではない。実MIME/ZIP構成への適合はC |
| redirect | JSONは拒否。GTFSだけ初回302→`https://dataodpt.blob.core.windows.net:443`へ最大1回。既存実装の安全制約であり、U1〜U3による公式転送先の確認ではない(C)。転送先へAPI keyを付け直さない |
| CLI対応 | 各行のURL/filter・query encode・形式検査・7 source順次取得は実装済み。通常CLI/native adapterはpolicy拒否のため**現在は7件とも実取得不可**。設定を表現できることと、公式適合・全件性・実疎通の成立は別 |

現行filterには駅・方向・calendar・列車番号による追加制限がなく、意図する対象を狭めてはいない。ただし、指定プロパティ/値と複数filterの公式動作、提供される対象範囲、上限制限が未確認のため、必要範囲を取得できるという公式根拠にはまだならない。初回公開を理由に固定sourceの範囲や名称を縮小しない。

### 検索上限と全件性

現行6 JSONは`/api/v4/odpt:<種別>?<filter>`型の検索APIへ各1回requestする実装で、dump APIを呼んでいない。U1 p. 8は検索endpointと検索の上限動作、p. 10はdata dump API（`/api/v4/RDF_TYPE.json?`）を別endpoint形として説明する。dump APIが対象のTokyoMetro dataset・固定7 source範囲・権限で利用可能か、サイズ条件等はこの一般記述だけでは確定できず、次工程で選択・追加requestしない。`_all.json`という保存名もdump/全件取得を示さない。GTFS file配布経路へJSON検索上限を適用する根拠はない。

| JSON | 全件取得に必要な集合と条件 |
|---|---|
| Railway_all | Oに一致する全Railway。公式のoperator filter・提供範囲を確認し、その全集合が今回の応答に含まれる根拠が必要 |
| Station_all | Oに一致する全Station。同上。路線ごとの同名駅等を勝手に重複削除しない |
| TrainTimetable_Yurakucho | OかつYの全TrainTimetable。全calendar/方向/便・eventが揃うこと。filterの公式動作と上限による未返却の不存在が必要 |
| TrainTimetable_Fukutoshin | OかつFの全TrainTimetable。同上 |
| StationTimetable_Yurakucho | OかつYの全StationTimetable。全駅×実際に提供される方向/calendarの組と各eventが揃うこと。存在しない組を推測で要求しない |
| StationTimetable_Fukutoshin | OかつFの全StationTimetable。同上 |

U1 p. 8では検索結果がシステム上限を超えると上限以下に絞られ、必要データをquery filterで再取得する必要がある。**HTTP 200、parse成功、正常なContent-Lengthでも検索部分集合となり得る。**検索上限の数値はPDFに示されていない。128 MiB等はローカルの転送/parse安全上限で別物。上限Nだけ判明しても、公式文言上`<=N`の件数が返るので`取得件数<N`だけでは全件の証明にならない。dataset別endpoint/期待集合または網羅的な追加filter集合の根拠が必要。p. 10にdump APIも説明されるが、これを東京メトロの固定7 sourceに使える、検索上限を回避する、必要範囲だけを返すとは断定しない。

| 既存の検査・評価 | 検出できること | 検出できないこと／限界 |
|---|---|---|
| transport・inventory・Snapshot確定 | 転送長不一致、サイズ/形式/ZIP破損、保存hash/bytes/metadataの不一致、7 source不足、失敗/中断 | 正常配列として切り詰められた検索結果。取得時点で空配列/別種rowが混じっても現行のJSON構造検査だけでは停止しない。`complete`は固定7成功参照の充足だけ |
| Source metadata・Phase 2A | JSONの実recordCount、dc:date/dct:issuedと欠損数、旧新件数/hash/metadata差 | 公式の期待総件数がなく、増減の原因を「上限」と特定できない。同件数で別recordが欠ける場合は件数だけでは不明。旧保存値も全件性の正解ではない |
| Phase 2B | ID集合の追加/削除/変更、型/識別子/時刻/参照構造違反、残存recordからの内部参照未解決・曖昧さ（`odpt_train_semantic_diff.py`） | 正式改正による削除と取得欠落の自動識別、旧新共通の欠落、参照元/先が同時に消える欠落、既存集合にない新規record。外部事業者参照はinternal欠落と区別する |
| Phase 2C matcher/診断 | GTFSから生成された評価対象tripについてODPT候補の欠落/曖昧さ等をraw status、率の分子/分母、UNKNOWN/WARNINGで観測。primary/alternative・第1/第2legを区別 | 全ODPT recordを母集団にしない。評価日・8目的地・生成/候補/最良alternativeの外の便、GTFSとJSON双方にない便。照合率100%も全件性を証明しない |
| Phase 2C routeCoverage/表示/DOM | GTFSのactive路線trip数、池袋出発trip数、候補数/不足理由、候補消失や状態変化、画面内の意味整合 | scheduledTripCount等の分母は取得済みGTFSから作る。GTFS全体から便が消えると分母も縮む。小さな整合した集合でもcoverage/DOMが成立し得る。画面外の全列車・全駅・全日を保証しない |

全件性確認の最小手順（設計上の判断、今回は未実施）:

1. U1 pp. 8–10のsearch/dump/filter・上限記述に照らし、東京メトロ各datasetの公式endpointと正確なfilter条件、現行filterで対象全体をカバーする条件を確認する。上限値や部分結果の識別方法は公式資料に数値記載がない。必要なら人間による事務局照会で確認する（今回は問い合わせ送信なし）。
2. 公式非切捨て保証、当該集合の公式期待ID/件数、または利用可能な全件dumpを得た場合、その適用範囲を確認し取得後に実件数/一意ID/対象範囲を照合する。追加filterを使う場合は分割が網羅的かつ重複を安全に処理できる公式根拠が必要。既存Phase 1B件数は比較材料に限り、ハードコードした期待値/上限にしない。JSON相互参照とGTFS照合は補助根拠とする。
3. 根拠が得られなければ全件性は未確認のまま。明示許可した非公開の初回採取で応答を観測することと、「全件取得済み」と採用することを分ける。追加の分割照会が必要になれば、公式filter/分割の網羅性・結合/重複・証拠契約と追加通信範囲を別途レビュー・許可する。推測のpage/offset/limit、場当たり的な分割・ダンプへの自動切替は実装しない。

### GTFS `date`省略案と取得後の版確認

**暫定採用案:** 初回は現行`endpoint()`のとおり`date`を付けず、認証queryのみで配布ZIPを受け取る。U3のURLと一致するrequestであり、省略が必ずcurrentになるとの公式確認ではない。U2 p. 1/6の説明は会員ポータル経由で提供されたデータに適用される。東京メトロの既存GTFS file URLがその対象か、date省略時に返る版は資料から確定しない。JSON APIにdateを加える根拠もない。current/next/latestの詳細・next不在や切替時刻の解明は、初回にそのselectorを使わないため必須にしない。

- 省略時に確定できること: requestにdateを送らない、取得成功時にはそのrequestで返されたbytes/hash/実取得成功日時を記録できる、という事実。現時点で返る版・更新日時・適用日を確定することはできない。
- 確定できないこと: 現行/次期/最新のどれか、会員ポータル補足の適用、cache/版切替の時刻、JSONとの同一ダイヤ版性。取得成功日時はfeed版・適用開始日ではない。feed_versionが日付らしくても意味を補わない。
- 取得後のfeed_info: 保存ZIPをread-onlyで読み、既存Source metadataの`feedVersion/validFrom/validThrough`と`feed_version/feed_start_date/feed_end_date`を照合する。欠損・逆転・既存契約外は失敗/保留とし、旧版やmtimeから補完しない。期間に取得日が含まれても、それだけで最新版・現行ダイヤを証明しない。
- 適用日: `calendar.txt`のservice_id別期間/曜日に`calendar_dates.txt`の追加(1)/除外(2)を適用し、実際のactive service→trips→対象路線/駅eventを確認する。既存`ItineraryGenerator.active_service_ids()`を使える。feed期間全体に全便が毎日走ると解釈せず、平日・土曜・休日・改正境界/深夜の必要日を明示する。24時超は運行日内秒として保持する。
- 公式改正情報: 人間が東京メトロの公式改正告知・対象路線の公式時刻表・ODPT Newsの対象記事を選び、URL/確認日/改正日/対象路線/対象便・時刻を非公開審査記録へ残す。取得日前後の改正と、calendar/例外・実時刻の対応を確認する。今回新たな改正告知の探索・採用はしていない。version文字列や告知日だけから適用を推定しない。
- JSONとの整合: 各JSONのdc:date/dct:issuedの集合/欠損と、calendar・路線・方向・便番号・発着時刻・行先・停車列を比較する。既存matcherと2B/2Cを利用し、時刻表間のtrain+calendar参照も確認する。metadataの日付一致だけを同版の証明にせず、不一致だけで即別版とも決めない。既知の照合規則/crosswalkが新規版でも有効か確認する。公開に使う運行日と便の範囲に対する根拠が不足すれば保留。

この審査は取得Snapshotとは別の判断記録とし、raw・既存Source/Snapshot schemaを書き換えない。`applicationPeriod=null`、`publicationApproved=false`、`crossSourceConsistency=not-evaluated`を取得・評価CLIが自動変更しない。公開期間の設定・承認は後の公開工程で行う。

### 既存CLIの準備状態と次工程の変更分類

以下は2D-3B終了時の設計判断。2D-3Cで対応した実装状況は末尾の2D-3C節を参照する。

開始時はbranch `main`、HEAD `05508995ce1fd6d14dad3b90c55563828141320c`、status clean。HEADのPhase 2D-3A commit（manual fetch/評価adapter/testと4文書の計7ファイル）を確認した。既存2D-2A/2D-2B/2D-3Aの契約詳細・テスト実績は各節を正本とし、以下は初回実取得に関わる差分だけを列挙する。今回テストは変更・再実行していない。

| 分類 | ファイル・機能 | 次工程で必要な最小対応 |
|---|---|---|
| 必須 | `scripts/odpt_manual_fetch.py`: `_require_live_policy/_transport_mode/_https_exchange`とCLI fetch/retry | 公式照合と人間の取得許可後にだけ、コード上の無条件拒否をレビューして変更する。既定拒否を保ち、許可済みの固定経路に対する明示opt-inをfetch/retry両方で要求し、credential読取・batch作成より前に検査する。現在の`--enable-live-transport`は拒否専用でretryには存在しないため、既存flagの意味とretry入口の整合を直す。定数をTrueにするだけの解除やmock seam経由の実通信は不可 |
| 必須 | 同file: `main()`と`env_credential()` | policy通過後の通常CLIに環境providerを接続する。現状`credential_provider=None`のままなので、policy解除だけでもdriverは`credential_provider_required`で止まる。`.env.local`読込やCLI key引数は追加しない。fetch/retryとも同じ規則にする |
| 必須 | 同file: JSON受信から成功record作成まで | 取得契約の確認済み必須field/種別/operator/路線と0件を最低限検査し、明らかな別source・範囲外・想定外の空応答を成功にせず、そのsourceで停止する。現行はobject配列であれば業務field不足や0件でも7件成功→Snapshotへ進み得る。公式schema確認後に狭い検査を加え、補完・削除・再整形・自動filter修正はしない。全件性の証明や完全な意味評価はこの検査に担わせない |
| 必須 | `tests/test_odpt_manual_fetch.py`、必要な場合だけ`tests/test_odpt_fetch_evaluate.py` | 次工程の変更箇所について、既定拒否/許可前provider・socket未到達、固定7範囲、fetch/retry opt-in、別種/範囲外/空配列停止、秘密非出力、mock/live分離を合成・完全mockで検証する。実APIをテストに使わない。取得・provenanceが変わる範囲の既存回帰を実施する |
| 条件付き | `odpt_manual_fetch.py`: `endpoint/transport/evidence_for` | 個別公式仕様と実装の不一致が立証された場合に限りendpoint/filter/encode/MIME等を最小修正。GTFS転送先/statusが既存制約に合わなければ停止し、追加host/status許可は別レビュー・通信許可が必要。既存成功履歴に対する設定変更でevidenceの再計算内容が変わるため、途中batchを改造して続行しない |
| 条件付き | `odpt_manual_fetch.py`、`odpt_source_inventory.py`と対応test | 実応答のZIP構成/必須metadata等が既存契約と異なるときだけ仕様根拠を確認し、入力対応の要否を別判断する。GTFS一般仕様上の任意項目と現行readerの必須条件の差を自動緩和しない。件数制限回避が必要なら取得/証拠契約への影響も別設計。初回から追加実装しない |
| 不要 | `odpt_source_contract.py`、`odpt_source_store.py`、`odpt_evaluation_input.py` | strict Source/Snapshot、fingerprint、legacy reader、全retry/provenance検証の変更・原本コピー・新store形式の追加は不要。補助batch/evidence v2は既にlive-httpsを表現できる |
| 不要 | manual fetchのHTTP基盤、履歴、`run_fetch/acquire/finalize` | TLS/timeout・既存制約、排他的private保存、attempt/retry親、失敗/中断停止、成功raw二巡照合とSnapshot markerを再利用する。driver再実装、自動retry、孤立raw/historyの自動修復は不要 |
| 不要 | `odpt_fetch_evaluate.py`とPhase 2A〜2Cの既存評価engine | sealed fetch batchの読取専用adapterとstage別入口は存在する。比較/品質engineの新設、公開資格の自動付与は不要。新旧で同じ最終コード/context/runtimeを使い直す。異世代で比較可能日がなければ比較不能を残し、必要なcandidate単体QAは既存collectorで行う |
| 不要 | 全般 | date=current/next/latest、推測ページング、定期更新・監視・通知、汎用policy/credential基盤、Cloudflare/公開builder/runtime/承認gateの変更は初回取得に追加しない |

**次工程の最小実装範囲:** 原則`odpt_manual_fetch.py`の「既定拒否を保つ明示ライブ許可」「環境provider配線」「確認済みsource範囲の受信時停止検査」と、その必要な合成回帰だけ。endpoint等の変更は公式照合の結果が示した場合に限る。取得件数の上限値が不明という理由だけで取得方式を増築しない。inspectは現行では件数要約だけなので、retry理由は非公開のattempt/result/evidenceを人間が確認する。初回用の新しい履歴画面・レポート保存機能は不要。

### 解決事項の期限と安全な初回実行計画（未許可・未実施）

| 期限 | 必要な解決・判断 |
|---|---|
| 実取得開始前 | U1のJSON個別endpoint/filter/組合せ/応答schemaの照合とページ根拠。U3の初期URL・認証について共有記録の採用範囲を明示。保存先・実行環境・認証設定方法・通信host/path・GTFS redirectの許可範囲について人間の明示許可。上記必須実装・合成回帰・レビュー。全件性を確認する方法と未確認時の停止/採用保留を決める |
| 取得後、全件取得済みとして採用する前 | 6 JSONごとの全件性の根拠と実件数/ID・範囲照合。具体的上限の解明だけを一律必須とはせず、公式非切捨て保証や独立期待集合で代替できる。根拠不足なら非公開の観測結果にとどめる |
| 初回正式公開の承認前 | GTFS実版/運行日・公式改正情報・JSONとの版整合、必要な品質/表示QAと未評価の説明、適用期間と公開条件の審査。これらは実取得前に推測で埋めない |

1. **準備・許可境界を固定する。** 次工程開始時にもbranch/HEAD/status、既存原本7件/storeをread-onlyにする方針を確認する。人間が、実装変更の範囲と、実取得の対象7 source・保存先・通信を明示的に許可する。実装の許可とネットワーク実行の許可を混同しない。許可内容は秘密を含まない記録にする。
2. **通信範囲を限定する。** `api.odpt.org:443`の表にある4 JSON resource path（6 filter組）とGTFS file pathへのGETのみ。GTFSの既存302転送先を許可する場合は`dataodpt.blob.core.windows.net:443`へ1回という境界も明記する。承認しない場合は追従を無効にする変更が必要。追加のmetadata/照合API、HEAD疎通、別selector/追加filterの試行はこの7 source取得許可に含めない。通常は7 GET、許可したGTFS転送がある場合だけ追加1 GET。retryは別の明示操作とする。
3. **新規の非公開保存先を用意する。** repository・公開/preview/QA経路・既存原本/storeとは別の、同期/公開対象でないローカルPOSIX領域を人間が選ぶ。候補は`~/Library/Application Support/dotchi-ikebukuro-odpt-acquisition/<new-batch-id>`の絶対path（現時点では未作成・権限/非同期性未検証）。親を事前に用意し、symlink/既存destinationを拒否、dir 0700/file 0600を維持する。sandbox許可が必要な保存先は次工程で許可を得る。`/private/tmp`は合成検証用であり正式な保存先に自動採用しない。`init`はoffline batchを作るためlive fetchの前に実行しない。live fetch自身に新規batchを作らせる。
4. **認証を人間の実行環境に安全に設定する。** 認証providerは`ODPT_API_KEY`。人間がechoしない対話入力等で実行processの環境に設定する。キーをチャット、shell引数/履歴、repository、`.env.local`、ブラウザーURL、保存ログへ書かない。`env`/`printenv`等で検査表示しない。Codexが値を読み取る操作をこの文書で許可しない。実行後は当該環境から解除する。
5. **一度だけ順次取得する。** 必須修正・mock検証後の確定CLIを、人間が許可済みのライブopt-inで実行する。順序は表の7 source。現行CLIは未対応なので本節を今すぐ実行できるコマンドとは扱わない。各attemptは開始時刻/IDを先に耐久保存し、HTTP安全要約、固定path/filter、selector不使用、transport、結果、metadata件数/期間、rawのSHA-256/bytesと実取得成功日時を既存形式に残す。rawは応答bytesそのまま、キー付きURL・生header/Location・署名URLは証拠へ残さない。
6. **想定外なら停止する。** TLS/timeout/status/MIME/encoding/長さ/JSON/ZIP/範囲検査失敗・中断・保存失敗で後続sourceへ進まない。別のendpoint/filter/date/MIME/転送先への自動修正やfallbackはしない。取得後に判明した版/全件性/意味仕様の差も、その段階で評価・候補採用を停止/保留する。新規requestを重ねて解決しない。既存成功raw・開始/失敗証拠・孤立rawは消去/上書きしない。
7. **retryは人間が理由を確認して明示する。** sourceId、attemptId、outcome、固定errorCode、statusを非公開記録で確認する。通信一過性と判断できる失敗/中断または最初の未試行sourceだけを、同じ承認済み設定の`retry --source`で指定する。成功sourceは再取得せず、親attemptを残し、過去rawを再照合して未試行分へ続く。仕様差・設定変更・孤立raw・壊れたhistoryならretryせず停止する。変更が必要なら別レビュー/許可後、新規batchで採取し、旧不完全batchを保存する。
8. **Snapshotを確定する。** 7 sourceが同一batchで各1成功した時だけ、全retry/契約検査、raw全件二巡hash/bytes/形式/metadata照合、最後の完成markerである`snapshot.json`保存を既存`finalize()`で行う。現在のdriverは7件成功後に自動でこれを行うため、手動finalizeを重ねない。Snapshot完成は取得履歴の確定であり、全件性・同一版・公開承認の確定ではない。
9. **read-onlyで版/全件性とPhase 2A〜2Cを評価する。** `odpt_fetch_evaluate.py`へbaseline store/rawとcandidate batchを明示し、`--stage 2a`→`2b`→`2c`で既存入口を使用する。2Cは共通に有効なservice dates、固定UTC観測1点、DOM対象8駅を明示し、同じ凍結engine/context/runtimeで旧新を再計算する。観測JST日と前後1日の3日closureを含め、平日/土曜/休日と必要な深夜/改正境界の確認を計画する。必要なら別観測点の評価を明示的に追加する。共通期間がなければ比較不能を保持し、candidate単体評価を旧世代比較の代用としない。CLI終了0やpartial/indeterminateを公開PASSへ読み替えない。詳細結果は既存APIのメモリ上で非公開審査し、CLIの状態要約だけで品質を判断しない。
10. **公開承認を別工程にする。** 全件性、実feed/適用日、公式改正情報、JSONとの整合、評価で残った欠落・未知/未評価を秘密抜きの判断記録にまとめる。生データや詳細旅程をGit/公開経路へ複写しない。必要な公開QA/期間・条件の審査と人間の明示承認が揃うまで公開しない。今回もCommit/Push/Merge/Deploy、Cloudflare/公開経路の操作はない。

## ODPT-2D-3C 初回取得CLIの最小実装（2026-11-07）

2D-3Bの公式根拠・A/C分類・全件性/版の未確認事項を維持し、`odpt_manual_fetch.py`の実行経路を実装した。今回の実装承認は実取得の許可ではない。実ODPT通信・実データ取得・実キー読取/使用は行っていない。

- **事前確認と既定拒否:** `plan --batch <new-private-absolute-path>`は既存path validatorで新規保存先を検査し、固定7 source・URL/filter/filename・GTFS一回転送先・selector不使用・保存先を表示する。secretを読まず、保存先を作らず、通信しない。`plan --batch <unfinished-live-batch> --source <sourceId>`はretry対象と履歴fingerprintも確認値へ含める。fetch/retryは両方とも`--enable-live-transport`と`--confirm-plan <confirmation>`が必要で、現在のplanを再計算して一致を確認する。確認値は操作範囲の確認用で、秘密・署名・公式適合や人間の承認を証明するものではない。
- **native許可の寿命:** 一致確認・credential検査の後だけ呼出し内のContextVarへplanを置き、終了/例外時に解除する。transportとnative adapterはこの呼出しpermitを要求し、driver/acquireは保存先一致も要求する。旧bool定数は廃止。任意URL/transportをCLIへ追加せず、固定初期pathか既存の許可転送先だけをnative adapterでも検査する。mock exchangeとlive permit/flagの混在は拒否する。
- **credential:** 既存`env_credential()`を確認条件成立後にだけ通常CLIへ接続。`ODPT_API_KEY`の非空・ASCII可視文字を既存規則で検査し、未設定・空・空白/制御文字/非ASCII・非文字列ならbatch作成と通信の前に停止する。実キーの固有形式を推測した正規表現は加えない。CLI秘密引数、`.env.local` reader、URL/header/例外全文出力は追加しない。認証URLはメモリだけで使用し、GTFS転送先へキーを付け直さない。
- **応答:** 既存HTTP/status/MIME/encoding/サイズ/長さ、JSON duplicate-key/配列parser、ZIP/metadata validatorを再利用。JSON成功record作成前に非空・source種別に対応する`@type`、非空文字列の`@id/owl:sameAs`、全recordのTokyoMetro operatorと指定railwayの完全一致を追加確認する。空/別種/範囲外を除去・補完せず、固定error codeの失敗として停止する。finalize/retry前のraw検査でもscopeを再確認する。ローカルの期待source条件であり、公式の全件保証・便の正確性・同版保証ではない。
- **履歴と評価:** 既存`run_fetch/acquire/finalize`、固定7件の順序・最初の失敗/中断停止、成功raw上書き禁止、retry親・全attempt/provenance、二巡hash/bytes/metadata検証を維持。strict Source/Snapshotとv2補助envelopeを変えず、`publicationApproved=false/applicationPeriod=null/crossSourceConsistency=not-evaluated`を維持する。2A〜2C adapter/engineには変更なし。合成の取得fixtureを非空のscope-correct recordへ更新し、同じ評価入口で検証する。

ライブ許可contextを発動する試験はしていない。確認条件は副作用なし関数で検証し、条件成立後のCLI dispatchは`_live_session`とdriverをmock化、TLS/native adapterはguardとHTTPSConnection全体をmock化する。固定7件取得・失敗停止・retry・2A〜2Cの実評価はoffline-injectedまたは合成live形式のfixtureのみで行う。回帰時はsocket接続も拒否mockにする。

最終関連回帰は164件PASS（145.345秒）。manual fetch/取得評価、Source契約/inventory/store/2A、train意味比較/GTFS loader/GTFS意味比較/7 source統合/品質入力を実行した。2C接続は同じ凍結engine/contextの実generator→v2→board→Node DOMを合成fixtureで評価しており、実ダイヤ品質・実HTTP/TLS疎通の証明ではない。回帰前後の既存7原本＋store8ファイルはSHA-256/bytes/inode/mtime/ctime一致。原本/storeへ書込・コピーしない。

初回実取得前の残件は、JSON個別endpoint/filterと必要範囲/全件性の確認方法、GTFS転送先を含む通信範囲と保存先の人間による明示許可、この差分のレビュー。取得後はfeed/calendar・公式改正情報・JSONとの版整合と品質評価を実施し、公開承認は別工程。`date`指定・ページング・自動取得/監視・公開builder/runtimeは追加していない。新たな公式仕様との不一致は発見していない。

## route9旅客coverageとODPT照合品質の分離（2026-11-07）

判断根拠は本作業で利用者が確認済みとして提示した運行ルールと、取得済みrawである。提示された公式参照先は [西武鉄道S-TRAIN](https://www.seiburailway.jp/railway/reservedtrain/s-train/)、[東急S-TRAIN](https://www.tokyu.co.jp/railway/ticket/s-train/)、[東京メトロ副都心線](https://www.tokyometro.jp/station/line_fukutoshin/index.html)。外部通信禁止のため、この実装作業ではURLを再閲覧していない。先行調査で未確認だった土休日西武方面S-TRAINの池袋降車専用は、今回の利用者確認情報を根拠として採用する。平日有楽町線系統や逆方向への拡張はしない。

- **rawで確認:** 土休日3便のS-TRAINはGTFS池袋pickup/drop_offが0/0だが、ODPTには池袋arrivalのみがありdepartureがない。小竹向原はGTFS pickup/drop_off=1/1。GTFSだけでは池袋の降車専用を表現できていない。rawを修正せず、公式ルールと矛盾のない限定条件で乗車を禁止する。
- **設計判断:** route9・SaturdayHoliday・既存番号normalizerによる一意のODPT候補・S-TRAIN raw種別・和光市方向・全行先が西武・池袋到着一意/GTFS時刻一致/発時刻なし・小竹向原の乗降不可が全て成立した場合に限り、池袋乗車不可の根拠を内部結果に保持する。列車ID例外は使わない。対象行・ODPT未照合・kotake_alighting_prohibited WARNINGと公式ルール診断を残し、候補/乗換legへは使わない。乗車不可行は通過件数・乗換データ不足の集計対象ではなくなる。条件不成立時は従来の不足判定へ戻る。
- **coverage判断:** 上記乗車不可の証拠があり旅程なし、診断が想定した2コードだけの行は旅客coverageの判定対象外。それ以外のWARNINGは引き続き阻害する。ODPT未照合理由が独立destination/headsign crosswalkの欠落だけで、既存検証済み旅程または明示通過がある場合は、照合品質の未確定として保持し、旅客coverageを阻害しない。matcherが行先crosswalk検査で早期returnする場合も、enrichment層で既存のGTFS→ODPT停車順対応と完全一致を再検査し、未検証/矛盾は阻害理由に残す。他の未照合/衝突・目的駅欠損/時刻不明・件数不整合は阻害を維持する。matcher・種別表示・旅程validator・公開validatorは変更していない。
- **利用者影響:** B554K/B689S/B733Sは未照合のまま、小竹向原・和光市の直通および有効な乗換候補を維持。急行停車パターンを通勤急行へ置換せず、途中駅の通過も維持する。B771M/B1673M/B1975Mは乗車不可として除外し、他列車の表示まで止めない。未知の列車を利用可へ昇格する処理ではない。

QA結果は同日のdevlogを参照。coverage completeは、保存済み入力に対する旅客候補判定の状態であり、API全件性・鮮度・版整合・公開資格の承認ではない。publicationApproved=false/applicationPeriod=null/crossSourceConsistency=not-evaluatedは維持する。

## ODPT-0品質ゲートの解決区分（2026-11-07）

先行するroute9旅客coverageの根拠判定をODPT-0にも共有する。元のQA status、ODPT照合状態、WARNING/INFO診断と件数は変更しない。列車IDの例外リストは使わない。resolutionは、問題のある生成行をA（厳密な公式ルールで池袋乗車不可、旅程なし、想定2診断のみ）、B（独立した列車候補/運行日/池袋時刻/停車順検証済みで行先crosswalkだけ未確定、有効旅程または明示通過、他WARNINGなし）、C（不明/想定外）、D（衝突/曖昧/矛盾、明示的な種別と停車パターンのconflictを含む）に分類する。正常照合行は分類件数に含めない。

Bの停車順検証を通したことはgenerator内部のpassenger_match_verifiedで明示する。判定文字列だけで安全とは扱わない。Aは既存の公式乗降ルール証拠に加え、実際のODPT未照合理由、候補旅程なし、診断集合完全一致も要求する。追加警告、証拠欠損、C/Dは阻害する。原本・GTFS値とODPT confirmed条件は変えない。

各駅日のQA reportにresolutionとrouteCoverageを追加し、summaryに分類とunmatched/warningCodesのoriginal/resolved/unresolvedを合算する。QA status=WARNINGは保持する。候補生成ゲートは、scope/fingerprint/構造FAIL、24駅日の重複・欠落、全route complete、C/D=0、unresolved=0、原数=解決数+未解決数、駅日別と総計の一致を検証する。Aは1行2WARNING、BはWARNINGなしという原数の関係も検証する。単純にWARNINGを無視する許可フラグは設けない。

private manifestのodpt0には、元status/未照合数/診断集計と、全体および駅日別resolutionを記録する。既存bundle validatorはこの新しいmetadataがあるbundleで同じ算術・scope・総計とODPT照合数の一致を検証し、候補hash/bytes/schema/旅程/routeCoverage検証を維持する。旧private bundleの検証互換は維持するが、新しいpipelineは新しいQA根拠を必須とする。非公開候補生成の成功は公開承認ではなく、applicationPeriod=null/publicationApproved=falseを維持する。
