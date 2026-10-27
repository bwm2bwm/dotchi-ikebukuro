# T12 Phase 4-6B — 新旧Deployment切替とrelease世代整合性

調査日: 2026-10-28（JST）  
対象: Cloudflare Pages staging `dotchi-ikebukuro-staging`、GitHub Actions `Synthetic public site CI`  
データ: syntheticのみ。ODPT実データは対象外。

## 1. 実機確認結果

以下はユーザー提供のstaging実機記録であり、本調査ではCloudflare/GitHubへ接続して再確認していない。

| 項目 | 世代A | 世代B |
|---|---|---|
| Deployment ID | `13e10889` | `f3be074d` |
| `generatedAt` | `2026-10-26T00:00:00+09:00` | `2026-10-27T00:00:00+09:00` |
| `feed.validFrom` | `2026-10-26` | `2026-10-27` |
| `feed.validThrough` | `2026-10-28` | `2026-10-29` |

10月28日朝にActions #5がBを生成・deploy。前日から開いていたChromeタブで手動reloadせず小竹向原へ切替えた際、`timetable-KotakeMukaihara.json`がHTTP 200で取得され、本文の`generatedAt`は10月27日だった。世代固有URL A/B、通常Production URLの応答も報告どおりだった。表示不具合の報告はない。

この操作状況は、古いタブからdeployment切替後のJSONをfetchする経路を実測している。一方でJavaScriptファイルのhash・内容は採取されておらず、「旧JavaScriptが保持されていた」は操作状況に基づく推定。タブ内で旧JSONと新JSONを同時に保持して表示した事実、混在時の画面差は未確認。

## 2. `generatedAt`が1日ずれて見える理由

コード上の因果は次の通り。

1. `.github/workflows/synthetic-public-ci.yml` のfixture生成stepは`--service-date`を指定しない。
2. `scripts/generate_synthetic_public_fixtures.py` は引数省略時に`jst_today()`を使う。
3. `scripts/synthetic_public_fixture_factory.py` の`jst_today()`は`datetime.now(ZoneInfo("Asia/Tokyo")).date()`を返す。runnerのOS timezoneをそのまま使わず、UTC instantを明示的にJSTへ変換する。
4. `generate_fixture_directory()`は基準日の前日・当日・翌日の3日をserviceDateにする。
5. `make_public_fixture()`は最初のserviceDateのJST 00:00を`generatedAt`と`feed.validFrom`にし、最後のserviceDateを`feed.validThrough`にする。

従って10月28日（JST）を基準日に生成すると、serviceDateは10/27・10/28・10/29、`generatedAt`は`2026-10-27T00:00:00+09:00`、validityは10/27〜10/29となる。報告されたBの値は現在のコードどおりで、JST/UTC境界バグではない。

`--service-date YYYY-MM-DD`は`date.fromisoformat()`で解析する暦日アンカーであり、時刻やtimezoneを持たない。指定時はそれを基準日として同じ前日・当日・翌日を作る。省略時の基準はJST暦日。GitHub-hosted `ubuntu-latest` が通常UTC設定でも、この関数はzone-awareなJST時刻を使用するためdate選択へ影響しない。実runのrunner clock/log timezoneは本調査では取得していない。

意味上の注意: 現在のsynthetic factoryにおける`generatedAt`は実際の生成・build時刻ではなく、fixtureカバー期間の先頭日00:00 JSTを指す決定値である。したがって「10月28日に生成したのにgeneratedAtが10月27日」という観測は仕様どおりだが、名前を通常のbuild timestampの意味で読むと紛らわしい。実データpipelineへ移る際は、生成時刻と対象データ期間の意味を分ける設計が必要。

## 3. Deployment切替時のasset・payload挙動

### コードで確認できたこと

- public HTMLは`preview_public.js`を通常のmodule scriptとして読み込む。public bootstrapは`PUBLIC_DATA_SCOPE`とHTTP `cache: default`を固定し、runtimeを起動する。
- `DESTINATION_PAYLOADS`は`./timetable-KotakeMukaihara.json`等の固定相対URLを使う。release ID/pathは付いていない。
- 目的地を切り替えたとき、prepared payload LRUに対象駅があればそれを使い、なければ相対URLへfetchする。LRUは駅IDをkeyにした2件で、reloadで新runtimeが起動すれば消える。
- LRU内payloadは既にparse/adapter準備済みの値。毎秒の`buildBoard`は再実行され、serviceDate・feed期間・applicationPeriod・現在時刻を判定するが、payload間のrelease比較はしない。
- loaderはrequested destinationとJSON内の全service dayのdestination IDを照合し、profile/schema等をadapterで検証する。異なる駅向けpayloadは拒否する。
- validatorはpublic profileと個々のpayload schema、駅名・origin、各駅間serviceDate一覧一致、asset allowlistを検証する。payloadの生成世代IDは現行schemaに存在しない。駅JSON間の`generatedAt`やfeed metadata一致は比較しない。
- `validFrom`/`validThrough`は適用serviceDateの範囲として使われる。runtimeは必要日付がfeed内か、serviceDaysが足りるか、有効期間内かを判定するが、deployment世代の同一性を証明しない。

### 切替時に起こりうること

1. **同一tab内のA/B混在:** A稼働中に取得済みの駅がLRUに残り、deploy後にまだLRUにない別駅を選ぶと、同じruntimeのAキャッシュとB fetch結果を同時に持つ可能性がある。LRU上限2のため全駅分ではないが、少なくとも旧payload 1件と新payload 1件の共存は可能。
2. **表示・判定への影響:** 現状のA/Bは異なるserviceDate窓とvalidityを持つ。通常時刻が両payloadの有効期間内なら、双方がそれぞれvalidとして表示内容を出しうる。Bで追加された日付・変更された便がAのキャッシュ側には反映されないため、目的地によって候補の鮮度や終電/始発判定が異なる可能性がある。期間外になれば古い方は期限切れ/必要service day不足として空状態になることがある。今回、見た目や判定への不具合は報告されなかったが、同一タブでのpayload共存は計測されていない。
3. **HTML/JS/CSS:** Pages deploy後にURLが新世代を返すことは実測JSON経路から確認できるが、当該tabがどのHTML/JS/CSS byteを実行中だったかは未採取。既に評価済みのES moduleはそのtab内で実行を続ける。別ファイルURLのcache/revalidationが同じreleaseへ揃う保証は現コードにない。

### ETag/304と日付有効期間

ユーザーはstagingでBrotliとETag/304の応答を以前確認している。ただし今回の各assetのCache-Control、ETag値、304対象・deployment間のETag挙動は記録されていない。

HTTP ETagは通常、個別URLのrepresentationを再検証する仕組みであり、HTML・module・駅別JSONを一括で同一releaseへtransactionalに揃える識別子ではない。304はそのURLについてcache本文を再利用する応答なので、そのURLのキャッシュ本文がどのdeployment由来かが重要になる。異なるURLが別々にfresh/revalidatedされる状況では、ETagだけで複数resourceの世代整合は保証されない。実際にCloudflare Pagesが今回どのURLへ304を返したかは未検証。

日付有効性だけでは不十分。異なるreleaseでも同じ有効期間を使い得るし、古い/新しいJSON双方が期間内なら共に受理される。逆に期限チェックは世代一致とは別の安全弁として引き続き必要。

## 4. 現行validatorが検出する範囲と限界

検出する: 期待ファイル集合・JS import graph・schema/profile、JSONの各payload検証、station filenameとdestination対応、駅間serviceDate一覧差、必須フィールドや不正値。

検出しない: HTML/JS/JSON共通release ID、8駅payload間のgeneratedAt/feed/application metadata差、deploy先実体が同じartifactかどうかをPages側で照合、ブラウザーに既にあるprepared payloadと新fetch結果の世代混在。CI workflowはArtifact ID/digest/tree digestをbuild→validate→deploy間で固定するが、これはdeployされた単一artifactの同一性を保証するもので、deploy後のブラウザーcache/runtimeを世代pinする仕組みではない。

## 5. releaseId方式の比較

| 方式 | 整合性保証 | 実装範囲 | cache / Pages | 検証容易性 | 既存機能への影響 | 実データ更新への適性 |
|---|---|---|---|---|---|---|
| **A. HTML/JSとJSONへ共通releaseIdを埋め込む** | JSの期待IDとJSON IDが違えば検出可能。旧JS+新JSONの誤受理を防ぐ。旧LRU payloadはその旧JSのIDで判定済みなので、同一runtime内の旧/新混在は新payload不一致時に拒否できる。検出中心で、更新資産への自動切替や旧版維持はしない。 | schema/profile、builder、validator、loader/bootstrap、testsを変更。public artifactの新フィールドは仕様変更を伴う。 | 固定URLのままでも動く。通常のcache revalidationは維持。ただしキャッシュが古いJSONを返しJSも古いままなら全て旧世代で整合し続ける。 | 非常に容易。HTML/JS constantと全JSON ID一致をvalidatorで検査。 | 最小。reload誘導UIを追加。エラー時に対象駅のみretryするか全体reloadを選ぶ。 | 手軽な第一段階。更新毎にIDを一意生成し、build metadataを明示する必要。 |
| **B. releaseId付き世代別JSON URL** | runtimeが選んだID付きpathから全stationを取得すれば、URL上で同世代へpinできる。ファイルを固定名へ上書きしてquery paramだけ変える方式は、CDNがqueryをcache keyへ含めるか/contentをID検証する必要があり弱い。immutable path＋ID照合が強い。 | builderで世代ディレクトリ生成、manifest/JSがID pathを選択、validatorのallowlist/構造変更、旧世代保持方針。 | Static Pagesと相性良い。immutable URLはcacheしやすい。旧タブが参照する限り旧世代JSONを保持する必要がある。Pagesの各deployment固有URLだけに依存すると通常URLから長期参照できない。 | 中〜容易。IDとpath/data一致、各station揃いを検証。 | URL mapping/API loader変更。通常JSON URL直アクセス/QA toolingにも影響。旧版資産の保持・容量管理が必要。 | 世代ごとのODPT生成物の再現性・rollbackに適する。削除期限と保存期間の方針が必要。 |
| **C. manifestによる世代管理** | runtimeがmanifestを一度読みrelease IDとstation URL集合を固定すれば、駅ごとの固定名参照より全station pinしやすい。manifestだけでは不十分で、immutable URLとpayload内ID/hash検証を組み合わせると強い。HTML/JS client互換条件もmanifestで確認すべき。 | manifest schema/generator、最初のmanifest fetch/cache policy、runtime pin、builder/validator、failure/retry、旧世代path管理。 | 小さなmanifestは再検証し、世代JSONはimmutable長期cacheにできる。Cloudflare Pages静的配信に適する。Deployは単一静的artifactに含め、公開前validatorで参照先全てを検証する。 | 強い。manifest参照閉包、ID、hash、8駅全ファイルをCI validatorで検査できる。 | 最も大きい。初期ロードでmanifest requestが1回増える。loaderと失敗UXを変更する。 | 最適。更新ごとにmanifestを切替え、immutableデータを保持でき、更新・rollbackを分離できる。 |

### 推奨

中期の推奨は**C + Bを組み合わせる**方式: `manifest.json`が`releaseId`と8駅のimmutable世代別JSON URL（可能ならSHA-256も）を記載し、runtime起動時にmanifestを一度取得・固定、payload内release IDも照合する。manifestのclient compatibility/schema情報も用意する。manifestを`no-cache`/短い再検証、世代別データをimmutable cacheにする。1tabのruntimeはmanifestを取り直さない限り同じ世代URLだけを使う。旧タブは取得済みの旧manifestを使い、旧generation filesを保持期間内利用できる。新deployment上に旧世代filesを残す保存方式が必要で、Pages deployment URL単体を永続保存場所とは見なさない。

低運用の初回実装としてAを先に実装する段階案も有効。Aは現状の混在を安全に**検出して拒否**し、C+Bは一貫した世代を**選択・配信**する。Aのみで防止できるのは、JSONが期待releaseと異なる場合の受理であり、古いcacheが同じrelease内で返るケースではreloadまでは更新されない。production実データ投入前にC+Bまで採用するか、generation retentionを明文化したうえでAを十分とするかは実装review時に決める。

## 6. mismatch時のUXとretry

- JSON release ID不一致、manifest破損・未対応client、manifest参照先のID/hash不一致はfail closed。該当payloadの候補を表示せず、既存LRUを別releaseとして黙って使わない。
- status欄に「時刻表データを更新しています。ページを再読み込みしてください。」を表示し、`location.reload()`ボタンを提供。自動reloadはtabがreload loopに入る恐れがあるためしない。
- reload後も不一致が出たら手動再試行ボタンを提示。手動retryは一度だけmanifestを再取得し、同じ失敗なら再試行を止めて「時間をおいて再読み込み」を案内する。1回目のnetwork失敗（offline/5xx）は短いdelay付き1回retry可。validator/schema mismatchをnetwork retry扱いにしない。
- 既存候補を継続表示するfallbackは、鮮度が異なるreleaseの混在を隠すため採用しない。駅切替時の操作を妨げず、エラー駅名と再読込actionをstatusで伝える。モバイルで頻繁なreloadを強制しないようloop検出・一回上限を置く。

## 7. 次の実装Phase案

**Phase 4-7（設計を確定する実装前準備）**

1. manifest schemaを定義: `releaseId`, `clientCompatibility`またはschema version、8 stationごとのimmutable URL、hash/byte length optional、作成時刻と対象期間の意味。
2. release IDの生成規則を決める。CI run IDを人が読めるIDに使い、artifact tree digestまたはpayload集合digestを内容同一性の裏付けにする。実生成時刻とservice periodは別フィールドとして扱う。
3. Cloudflare Pages上で旧世代JSONをどう保持するか決定。更新artifactに直近N世代を含める/別のstatic object pathを使う等を比較し、旧タブ最大寿命と容量・ODPT利用条件を定める。
4. UI文言、mismatch/missing/hash mismatch/offline/5xx/unsupported client状態、retry一回上限、reload loop防止を仕様化。
5. migration時の固定URLと新manifest URLの互換期間、QA/Access/preview URL・validator allowlist変更を設計レビュー。

**Phase 4-8（実装・検証。別途開始後）**

- builder/CIが世代ID・manifest・immutable station payload群を生成し、validatorがmanifestから参照される8ファイル全てとID/hashを検査する。
- runtimeがmanifestを一度pinし、2駅LRU keyにreleaseIdを含める（またはruntime単位に固定）、payload ID mismatchを拒否し、status/retry/reload UXを実装。
- testsでA→B deployment相当を模擬し、同一runtimeのLRU miss fetch、同駅LRU hit、複数station switch、manifest/JSON 304、古いmanifest、欠損generation path、offline/5xx、hash mismatch、retry loop防止を確認。
- static artifactのCI validationを通してから、承認付きstaging deploy後に新旧tab・通常URL・deployment URL・ETag/304・Cache-Controlを実機で再検証。旧JSのcontent hash、各JSON body release ID、Network response statusを保存し、A/B混在有無を確証する。
- production/ODPT API、実データ配信への移行は別承認・別Phase。現Phaseでは行わない。

## 8. 未解決・未検証

- Actions #5 runner上のUTC/JST clockとstep log時刻、実際のworkflow input値は未取得（コードからdate算出は特定済み）。
- Chrome tab内の旧JS/CSS/HTML byte/hash、今回の各URLのCache-Control/ETag、実際の304発生有無は未記録。
- A/B payloadが同じruntime LRUに共存した証拠、混在した際に選択駅間で候補・終電判定差が出るかは未確認。
- Cloudflare Access認証Cookieのない状態での通常/deployment/Preview URLとJSON本文cache leak確認も残件。
- `generatedAt`をbuild timestampとして扱うのか、対象期間先頭を示すsynthetic metadataとして維持するのか、ODPT実データpipelineに入る前に意味を確定する。

## 9. 作業境界

この調査で編集したのは`docs/project_state.md`、`docs/devlog.md`、本設計メモのみ。アプリ、builder、validator、fixture、workflow、public artifact、Cloudflare、GitHub Actions、ODPT APIは変更・実行していない。テストも実行していない。
