# T12 正式配信方式・ホスティング設計調査

調査日: 2026-10-26 (JST)  
状態: 設計調査のみ。実装・デプロイ・ODPT APIアクセスは未実施。  
関連タスク: T11 利用条件確認は完了。T12の実装、T13、T15は未着手。

## 結論

推奨は **Cloudflare Pagesの静的配信のみ + GitHub Actionsでのデータ取得・生成・検証・デプロイ**。Workers / Pages Functionsは初期構成に含めない。現在のアプリは静的HTML/CSS/JavaScriptと、生成済み駅別JSONだけで動作し、リクエストごとのサーバー処理を必要としない。GitHub Actionsは既存コード・テストを使う更新処理の実行場所として利用し、Cloudflare Pages Direct Uploadへ検証済みの静的成果物を送る。

Cloudflare Pagesは静的asset requestがFree/有料プランとも無料・無制限で、Gzip/Brotli、ETag、再検証向けCache-Controlを公式に説明している。現行8駅payloadは合計22,115,799 bytes、最大1ファイル3,334,635 bytes。現状の容量でFreeの25 MiB/file上限内に入る。公開前には今後の増加も含め、生成bundleの実容量をCIで制限する。

GitHub Pages + Actionsは最も既存運用に近い案。ただし公式の利用制限は商取引や商用SaaS向け無料ホスティングを意図しないとしており、広告付き無料の交通案内サービスへの適用を明記していない。これを可否いずれとも決めつけず、GitHubの確認を取る必要がある。Cloudflare案も東京メトロの公開条件や広告事業者の審査を省略するものではない。

本調査によって現行GitHub Pagesのroot mockを実ダイヤへ置き換えない。公開mockは維持し、まず別の検証先を使う。

## 比較

| 観点 | A: GitHub Pages + GitHub Actions | B: Cloudflare Pages + Workers | C: GitHub Pages + 外部更新処理 |
|---|---|---|---|
| 1. 月額固定費・従量課金 | 公開リポジトリの標準GitHub-hosted Actionsは無料。公開Pages自体も追加固定費なし。独自domainは任意で別料金。 | 静的Pages配信はFreeで開始でき、静的asset requestsは無料・無制限。Workersを呼ぶ設計にすると別枠の無料上限・超過料金が発生。独自domainは任意。 | Pages費用はAと同じ。更新環境がVPS・外部CI等なら別料金になり得る。Mac常時稼働なら金銭費用を抑えられるが保守コストが残る。 |
| 2. 無料枠・制限 | Pages公開siteは最大1 GB、月100 GBのsoft bandwidth limit（custom Actions workflowでbuild/deployする場合はこのbandwidth limitの対象外）。10分deploy timeout、rate limitあり。Actionsはpublic repoで標準runner無料。 | Pages Freeは月500 builds、同時1 build、20,000 files、1 file 25 MiB、build timeout 20分。静的要求は無制限。Workers Freeを使う場合は100,000 requests/day、CPU 10 ms/invocation。 | GitHub Pages/ActionsはAと同じ。外部処理環境の上限・無料枠は選定サービス依存で、本調査では金額を確定できない。 |
| 3. iPhone Safari速度 | GitHub Pagesの公開静的配信は適合するが、今回確認した公式資料では圧縮方式・日本国内からの配信時間を保証する記述を確認できず、実機計測が必要。 | PagesはCloudflare global network上のstatic delivery、Gzip/Brotli対応を明記。payloadの圧縮効果を活かしやすいが、iPhone実機・国内回線で最終計測する。 | 配信面はAと同じ。更新環境は訪問者向け速度に直接影響しない。 |
| 4. 圧縮・HTTP cache | 静的assetを配信できる。調査したGitHub公式資料からは本件で設定できるCache-Control/圧縮動作を確定できなかった。デプロイ後に応答headerを測る。 | Pagesは200 responseにETagを付け、`public, max-age=0, must-revalidate`を返す場合を説明。可能な場合Gzip/Brotliで配信。既定cacheをまず使い、`_headers`は必要な場合だけ設ける。 | 配信面はAと同じ。外部処理でHTTP cache behaviorは変わらない。 |
| 5. 現在約22 MBの8駅payload | 22 MBはPagesのpublished site 1 GB上限内。最大駅payloadは3,334,635 bytes。Git履歴やsourceに毎回含めず、build artifactから配信する。 | 最大payloadは25 MiB/file未満、8駅・他静的fileも20,000 file上限から遠い。現在のsite規模で成立する。 | 配信容量はAと同じ。生成物をGitへcommitする場合は過去版が履歴に積み上がるため、artifact deploymentを優先する。 |
| 6. 静的siteの構築 | `index.html`等をPages artifactへ組み立てるActionsが必要。underscore directoryのJekyll除外だけに依存せず、deploy artifactのallowlistで公開対象を固定する。 | 静的fileを出力dirにまとめてDirect Uploadできる。GitHub ActionsからWranglerで送る形なら既存build/testsと連携可能。Direct Uploadを選ぶとGit integrationへ後から変更できず、プロジェクトを作り直す必要がある。 | 外部ジョブでbuildし、Pagesが受け取れる形で公開する設計が必要。生成物commit、Pages用branch更新、Pages artifact uploadのいずれかを管理する。 |
| 7. ODPT API key | GitHub Actions environment/repository secretへ置き、信頼したschedule/manual workflowだけに渡す。HTML/JS、artifact、logへ出さない。public PRのjobにsecretを渡さない。 | 推奨構成ではkeyはCloudflareへ置かず、GitHub Actions secretとして取得jobだけが使う。Pagesは生成後の静的fileだけを配信。Workerを導入する場合もブラウザーへkeyを渡さず、Worker secretに限定する。 | 外部実行環境のsecret storeに保管し、公開先更新に必要な別credentialも分離管理。サービス固有の権限設計が必要。 |
| 8. ダイヤ更新自動化 | schedule/manual workflowと親和性が高い。既存取得script・exporter・validatorの一部を再利用できるが、現在はAPI取得から公開まで未統合。 | Pages単体にはODPTの定期取得・payload生成がない。GitHub Actions等の外部builderが生成し、Pagesへアップロードする。Workers Cronを追加する必要はない。 | 更新環境を自由に選べる一方、scheduler、データ取得、認証、Pages公開連携、監視を新設・保守する。 |
| 9. 更新失敗時の既存公開版保護 | 全station/dateの検証後にだけPages deploy jobへ進める。失敗時はdeployしない。Actions上でbuild artifactを本番承認前に確認する構成が必要。 | 検証成功時のみDirect Uploadを実行し、失敗時は現行production deploymentに触れない。Pagesの新deploymentはdeployment単位で切り替える。 | generatorが公開処理から独立する利点はある。外部処理が部分fileを直接上書きしないよう、全量bundle生成・検証・一括deployを別途実装する。 |
| 10. deploy・rollback | PagesのActions deployment履歴を利用。ロールバックは前deployment/artifactの利用可能性を確認したうえで手順化する。 | Pagesには成功済みproduction deploymentへ即時戻す公式rollback機能がある。staging/productionで別projectまたは分離deploymentを設ける。 | Pages側rollbackはAと同じ。外部runnerの過去artifact保持とdeploy記録も管理する必要がある。 |
| 11. i-mobile広告・ads.txt | `ads.txt`の静的配信は可能。i-mobileはsiteごとに審査し、`i-mobile.co.jp, アカウントID, DIRECT/RESELLER`形式を案内。GitHubの商用site規定が広告付き無料アプリにどう適用されるかは未確認。 | root `ads.txt`と広告tagを静的配信できる。GitHub Pagesの商用用途判定を避けられるが、ODPT条件・i-mobileの登録審査は別途必要。 | 広告適合性はAと同じ。外部更新環境は広告tagやads.txtの公開元にならない。 |
| 12. 独自domain | 技術上は`github.io`を利用できる。project siteのsubpathより、ads.txtのroot配置やブランドでは独自domainが扱いやすい。費用はregistrarとTLD依存。 | `*.pages.dev`で開始でき、独自domainは後から追加可能。i-mobile申請に使うsite URLとads.txtの配置要件は申請前に確認。 | Aと同じ。 |
| 13. 運用・保守負荷 | 既存GitHub中心で最低。公開mockと本番実ダイヤを同じPages siteで切り替える場合の誤deploy防止が必要。 | 2サービス（GitHub/Cloudflare）とdeploy tokenを管理する分だけAより増えるが、配信・compression・rollbackが揃う。Workersを入れなければ実行基盤の監視は増えない。 | 3つ目の実行基盤と公開連携を保守するため最も高い。常時serverならOS更新・監視も追加。 |
| 14. 小規模app横展開 | 同一repo/workflows/test基盤を再利用しやすい。 | 独立Pages projectsへ横展開しやすいが、Direct Upload project・token・build outputsの運用を共有化する。 | データ更新基盤は複数app共有可能だが、個々のhostingへ適合させる層が増える。 |

### 費用の読み方（公式情報確認日: 2026-10-26）

- **GitHub:** GitHub FreeのActions allowanceはprivate repoで月2,000分、public repoの標準GitHub-hosted runnerは無料。超過時の金額はrunner/plan依存のため、現行アカウント・billing設定を見ずに確定しない。GitHub Pages自体に通常の月額固定料は示されていないが、利用制限と用途規定がある。
- **Cloudflare Pages:** Freeの静的asset requestsは無料・無制限。Freeのbuild上限は月500、20分、同時1件。Workersなしの静的配信ならWorkers request課金を発生させない。
- **Workers:** 本件で未使用を推奨。後日動的処理が必要なら、Freeは100,000 requests/day、10ms CPU/invocation。Paid Workersは月額minimum $5で、月10 million requestsと30 million CPU millisecondsを含む（超過別）。2026-10-02更新の料金表に基づくため導入時に再確認。
- **domain / 広告:** domainの年間価格、i-mobileの掲載収益はTLD・契約・審査により異なる。本調査で価格は確定していない。

## 現行リポジトリと再利用範囲

### 公開root mockとprivate preview

- 公開rootは `index.html` / `app.js` / `data.js` / `styles.css` の架空ダイヤmock。GitHub Pagesで試作公開中。実ダイヤpayloadや取得keyを含めない。
- `_local_preview/`はprivate previewのHTML/JS/CSS、validator、build script。GitHub Pagesはroot/Jekyll構成と記録され、underscore directoryはJekyll出力から除外される。`_local_preview/prepare_preview.py`の実行siteはApplication Support外部directoryに出力。
- local builderはJSTの前日・当日・翌日の運行日を8駅分生成し、各payloadをvalidatorへ通した後だけdirectoryを置換する。失敗時は既存出力を戻すatomic swapがある。これは更新失敗保護の有用な参考実装。
- `scripts/export_local_timetable_payload.py`は出力pathを受け取り、`scripts/odpt_itinerary.py`は保存済みfeedをoffline処理する。`_local_preview/validate_payload.mjs`とtest suiteもCIに移植可能。
- **そのまま公開しない:** exporterの出力は`dataScope: local-preview-only`。現在のbuilderは `local_data/odpt/` の保存済みファイルだけを前提にし、固定のApplication Support出力先をCLIから選べない。公開用の出力allowlist、必要項目へ絞るprofile、公開目的のschema/validator、CI向け一時出力dirを設け、preview専用表示情報やraw/復元可能な項目が紛れないことを検査する。

### データ取得・生成・検証・公開の分離

現在の処理責務は一部存在するが、一つの自動pipelineには接続されていない。

1. 取得: `scripts/odpt_phase2_fetch.py`はODPT JSONを `.env.local` からkeyを読むローカル取得script。`scripts/odpt_phase3_gtfs_fetch.py`にもGTFS取得処理がある。これらは本調査では実行していない。CI secret/envからの注入、安全なURL/query/log処理、取得後file検査は別途設計が要る。
2. 生成: exporterとoffline itinerary generatorは取得済みのGTFS/ODPTを使う。現行builderは取得済みローカル入力を照合し、外部取得を行わない。
3. 検証: schema、feed期間、serviceDate、駅ID、対象候補の妥当性と既存testsを再利用候補にする。全8駅・必要日を必須条件にし、どれか欠ければdeployを止める。
4. 公開: 現行builderのatomic directory swapはローカルpreviewのみ。CIでは `dist/`を一時作成し、成功時だけCloudflare Pages Direct Uploadへ1回deployする。API取得・生成・検証jobとproduction deploy permissionを分ける。

### cache適性

`scripts/local_preview_payload_loader.mjs`は駅別fileを `fetch(filename, { cache: 'no-store' })` で取得する。これはbrowser HTTP cacheを迂回するため、公開CDNのstatic JSONを再利用する本番設定には適さない。公開時はこの指定を本番設定から外し、PagesのETag/`max-age=0, must-revalidate`に再検証させる方式から測る。変更は実装段階で行い、private previewの計測要件とは分ける。将来immutable URLにする場合はpayload filenameまたはmanifestにfeed version/hashを持たせ、HTML/manifestも同じdeploymentで切り替える。

2026-10-26生成済みpayload 8件の合計は22,115,799 bytes、最大は3,334,635 bytes。ローカルJSONをzlib level 9でDEFLATE圧縮した概算は合計568,642 bytes、最大82,636 bytesだった。これは圧縮可能性の参考値で、Cloudflare実配信・Gzip/Brotli・iPhone転送時間の実測値ではない。CloudflareはGzip/Brotliを可能な場合に配信するとしている。

### GitHub設定・秘密管理の確認範囲

- workspaceに `.github/workflows/` と `package.json` はなく、Actionsによる現在のbuild/deploy workflowは見当たらない。`README.md`はroot/Jekyll公開を説明している。
- `.gitignore`は `.env.local`、`.venv/`、`local_data/odpt/`をignoreする。これはローカル入力・keyを誤って通常追加するのを防ぐが、公開artifactへのコピーを防ぐ仕組みではない。
- GitHub remote Settings（Pages publishing source、repo visibility、Actions権限、Environment secretsの有無/設定）をremote API/UIから照会していない。secret値にもアクセスしていない。project_state内の記録はroot/Jekyll公開である。公開前に管理画面上の実設定を人が確認する。
- build workflowはPRからsecretsへ到達させず、trusted default branchのschedule/manual runだけでdata updateを実行。workflow permissionを最小化し、API keyをsecret envとして取得jobにのみ渡す。公開前のreview jobにはkeyを渡さず、deploy credentialは別environment secretとする。

## 公開条件・広告

### ODPTの範囲

2026-10-26に共有されたODPT事務局の回答は [`odpt_research.md`](odpt_research.md) のT11記録に原意を保って記載した。加工・配信、想定利用方法でのserver-side保存/cache、基本ライセンス・ガイドラインに従う広告/任意支援付き無料公開は問題ないとの回答。更新通知は開発者サイトのNewsで各データの更新状況を適宜掲載するとのこと。

これは相談したデータと想定利用方法への回答として記録する。全データセット、全種類の再配布、再利用可能な元データ/大部分を復元できる形式、API key公開等への包括的許可とは解釈しない。基本ライセンスは別途遵守し、static dataの取得日時表示、正確な反映、更新通知後1週間以内の更新、データ提供元・正確性免責・問い合わせ先を公開deliverableへ整える。source dataや大半を復元できる再利用可能形式を成果物へ含めない形を候補とし、公開payload schemaは公開前reviewする。

### i-mobile

i-mobile公式FAQはmediaごとの審査を案内し、審査目安は2–3営業日。`ads.txt`に `i-mobile.co.jp, <account id>, DIRECT`（運用委託/再販関係に応じてRESELLER）を記載する。アカウントIDは管理画面の対象site広告tagで確認する情報であり、現時点では申請・ID取得をしていない。固定320x50 dockはmock placeholderであり、実広告tagは未導入。

`ads.txt`は配信hostのrootで提供する。技術上、`github.io`/`pages.dev`でも静的text fileを置けるが、project subpathの場合はroot URLにならないこと、i-mobileのsite審査・登録URL条件、独自domainの必要性を申請前に確認する。独自domainはapp稼働の技術要件ではないが、ブランド安定、移転時のURL維持、ads.txt root管理に有用。

## 段階的実装計画（未着手）

概算は経験的な実装規模であり、データ取得・審査待ち時間は含まない。

| 段階 | 内容 | 完了条件 | 概算 |
|---|---|---|---|
| 0. 公開条件確定 | ODPT回答の対象範囲、基本license表示、更新時刻/News通知、公開payloadでの再構成可能性を記録。i-mobileの審査、ads.txt/site URL、独自domain要否を確認。 | 公開物の許容範囲・必要表示・更新責任者を明記 | 0.5–1日 + 回答待ち |
| 1. 検証site分離 | Cloudflare Pages Direct Uploadのstaging projectを用意。初期はsynthetic/mock payloadで現在のGitHub Pages root mockと分離。実データを扱う場合はアクセス制限を先に確認。 | iPhone Safariでpreview/ads dock、URL、header、consoleを確認。実データの一般公開なし | 0.5–1日 |
| 2. 公開build profile | `_local_preview` generator/exportをCI向け `dist/` profileへ分離。payload allowlistと`public` scope、source timestamp、license metadata、必要service dayを検証。raw inputs/API keyをdistへ含めない。 | clean checkoutから全8駅を生成、validator/tests成功、異常時deployなし | 1–2日 |
| 3. Actions pipeline | trusted branch schedule/manual trigger、secret env、入力取得、生成、8駅/date検証、artifact、staging deploy。cache headers/no-store除去を実装してNetwork/Safari再計測。Actions logのsecret/URL漏えいをreview。 |失敗時は現production保持。正常artifactだけstagingへdeploy。 | 1–2日 |
| 4. QA・公開候補 | 目的地全8駅、日跨ぎ、更新差分、失敗・rollback、iPhone Safari、圧縮とHTTP再validation、ads.txt、ODPT表示文言を確認。 | 別stagingで責任者がチェックリストを承認。現在のGitHub Pages mockは継続公開。 | 1–2日 + 審査待ち |
| 5. Production | 独立production Pages project/domain、production Environment protection、同一artifact昇格、update News記載、監視・rollback runbook。 | 明示的な公開承認後だけ実ダイヤをproductionへdeploy | 0.5–1日 |

初回のCI・stagingまで約3–6人日を目安とする。i-mobile審査とドメイン購入・DNS待ち、feed変化での解析修正は別途。production公開は本調査の対象外。

## 残る確認事項・リスク

1. GitHub Pagesの公式用途規定が広告付き無料の交通案内appへどう適用されるか。案A/Cを選ぶ前にGitHubへ確認する。
2. ODPT事務局回答が具体的に想定したpayload内容・再構成可能性の境界。出力schema、 attribution、取得日時、更新期限を公開前にreviewする。
3. データ更新通知が「News掲載」でどの単位・タイミングを想定するか、公式guidelineの取得時刻/1週間以内更新とどう運用連携するか。
4. ODPT API数値上限、GTFS feed取得頻度、secretariat回答が全使用データに及ぶかは未確認。ここではAPIへアクセスしていない。
5. GitHub Actions現行repo visibility、Pages source、secret設定、environment protection、branch ruleはremote UI/API未確認。
6. i-mobileのWeb広告審査、独自domainまたは`pages.dev`の可否、実広告tag、広告収益は未確認。
7. 22 MBは今回のローカル生成物の値。GTFS改正でpayloadが増える。Cloudflareの25 MiB/file上限と、GitHub Pages案ではpublished site 1 GB上限を超えないCI gateを設ける。
8. GitHub PagesとCloudflare Pagesとも、公開後の訪問ログ/広告scriptのprivacy説明が必要。広告導入時は外部request・cookie・同意要件を別途確認する。

## 公式情報（確認日 2026-10-26 JST）

- [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) — 1 GB site、100 GB soft bandwidth、用途、build timeout/rate limit。
- [GitHub Pages publishing source / custom workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) — Actions artifact/deploy flow、production protection推奨。
- [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage), [GitHub plans](https://docs.github.com/en/get-started/learning-about-github/githubs-plans) — public repo標準runner無料、private repo quota。
- [GitHub Actions secrets](https://docs.github.com/en/actions/concepts/security/secrets), [deployment environments](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments) — secret scope、review、branch restriction。
- [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/) — Free builds/files/per-file cap。
- [Cloudflare Pages static/functions pricing](https://developers.cloudflare.com/pages/functions/pricing/), [Functions routing](https://developers.cloudflare.com/pages/functions/routing/) — static requests free/unlimited、Functions billing behavior。
- [Cloudflare Pages serving/caching](https://developers.cloudflare.com/pages/configuration/serving-pages/) — ETag、cache header、Gzip/Brotli、default cache guidance。
- [Cloudflare Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/), [limits](https://developers.cloudflare.com/workers/platform/limits/) — Free/Paid request・CPU枠。
- [Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/), [CI integration](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/), [rollback](https://developers.cloudflare.com/pages/configuration/rollbacks/) — CI upload・direct uploadの不可逆なproject方式・rollback。
- [ODPT Basic License](https://developer.odpt.org/terms/data_basic_license.html), [Developer Guideline](https://developer.odpt.org/terms/data_basic_use_guideline.html) — public deliverable、commercial/non-commercial、source/update/obtained-time/attribution obligations。
- [i-mobile media FAQ](https://www.i-mobile.co.jp/help_partner_sp.html) — site審査・ads.txtのdomain/id/account type。

