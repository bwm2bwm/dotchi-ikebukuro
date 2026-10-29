# どっちに池袋

池袋から氷川台へ向かう利用者が、有楽町線・副都心線の列車候補を比較するスマートフォン向けWebアプリです。現在の画面は架空ダイヤによる試作です。

> **注意:** 表示される列車・時刻・接続はすべて架空です。実際の乗車判断には使用しないでください。

## 起動方法

index.html をブラウザーで開きます。ビルド、フレームワーク、外部ライブラリは不要です。

## ODPTローカル検証

APIキーはリポジトリ内の `.env.local` に設定します。このファイルは Git 管理対象外です。キーをソースコード、チャット、ログ、スクリーンショットなどに貼り付けないでください。

1. ODPT開発者サイトで発行したキーを用意します。
2. リポジトリ直下に `.env.local` を作成し、次の形式でキーを設定します（`<発行済みキー>` は実際のキーに置き換えます）。

   ```text
   ODPT_API_KEY=<発行済みキー>
   ```

3. ターミナルから `python3 scripts/odpt_smoke.py` を実行します。

検証スクリプトは `.env.local` を読み、東京メトロの路線一覧を1回だけ取得します。設定ファイルまたはキーがない場合は通信せず終了します。出力は成否の概要のみで、キー、認証付きURL、HTTPリクエスト全文、応答本文は表示しません。`.env.local` は共有・コミットしないでください。

### Phase 2 データ取得・解析

`.venv` と `certifi` を準備済みの場合、リポジトリ直下で次を順番に実行します。認証付き取得はユーザーの通常ターミナルで実行してください。

```sh
.venv/bin/python scripts/odpt_phase2_fetch.py
find local_data/odpt -maxdepth 1 -type f -print
.venv/bin/python scripts/odpt_phase2_analyze.py
```

取得スクリプトは対象JSONを最大6リクエストでローカル保存します。`local_data/odpt/` はGit管理対象外です。GTFSのCKAN配布URL・認証条件は未確認のため自動ダウンロードしません。入手済みZIPを同フォルダに置くと解析対象になります。解析結果はターミナルに表示され、データ未配置時に実データ結果を作りません。

### ローカル実ダイヤpreview

previewのソースは [`_local_preview/`](_local_preview/) にあります。underscore始まりのディレクトリはGitHub PagesのJekyll出力対象外です。実行時のHTML/JSコピーとpayloadはリポジトリ外の `~/Library/Application Support/dotchi-ikebukuro-preview/site/` に置きます。公開モックの `styles.css` を再生成時にpreview出力へコピーし、preview固有の状態・metadata表示を重ねます。ODPT/GTFS生データ、payload、preview生成物をGit管理・公開しません。

保存済み `local_data/odpt/` から、JSTの前日・当日・翌日をpayloadにしてpreviewを再生成します。外部API・`.env.local` は使いません。出力はOS一時領域ではなく、`~/Library/Application Support/dotchi-ikebukuro-preview/site/` です。

```sh
python3 _local_preview/prepare_preview.py
python3 -m http.server 8765 --bind 127.0.0.1 --directory "$HOME/Library/Application Support/dotchi-ikebukuro-preview/site"
```

previewではルート枠から8駅の目的地選択を開けます。更新時に全payloadを生成・検証し、UIは選択駅の1ファイルだけ読み込みます。選択したstation IDだけをlocalStorageへ保存し、リロード時に復元します。storageが使えない場合は氷川台で開始し、選択操作は継続できます。payloadや列車データは端末へ保存しません。個別生成には `scripts/export_local_timetable_payload.py` の `--destination-station-id` と `--output` を指定できます。

更新スクリプトは必要な保存済みGTFS/ODPTファイルを確認し、一時ディレクトリ内で画面ファイルと8駅分の独立payload（氷川台は互換のため `timetable.json`、他駅は `timetable-{stationId}.json`）を生成します。全payloadをadapterで形式・metadata・現在必要な運行日について検証し、すべて成功した場合だけpreview一式を差し替えます。1駅でも生成・検証に失敗した場合は既存preview一式を維持します。入力ファイルが更新されない限り、payloadの生成日時だけが新しくなっても元データの鮮度は保証されません。24時間TTLはなく、適用期間と必要運行日の有無で表示可否を判定します。

Mac Safariで `http://127.0.0.1:8765/index.html` を開きます。終了時はHTTP serverを `Ctrl-C` で停止します。開発用計測はSafari Web Inspector Consoleの `window.__dotchiPreviewPerf.history`（adapter、selection、DOM描画）と `window.__dotchiPreviewPerf.loadHistory`（fetch、本文読込、JSON解析、adapter、cache hit）で直近50件を確認できます。`fetchCount` と `cachedDestinationIds` も参照できます。計測値は画面には表示しません。

### CI向けsynthetic public fixture

公開用builderの動作確認には、追跡済みのテスト用synthetic入力だけからfixtureを生成します。ODPT API、`local_data/`、local/QA preview生成物は読みません。`--output`には新しいパスを指定してください。既存ディレクトリは上書きせず、日付はJST基準です。

```sh
python3 scripts/generate_synthetic_public_fixtures.py \
  --service-date 2026-10-27 \
  --output /tmp/dotchi-public-fixtures
python3 scripts/build_public_site.py \
  --fixtures /tmp/dotchi-public-fixtures \
  --output /tmp/dotchi-public-site
python3 scripts/validate_public_artifact.py /tmp/dotchi-public-site
```

`--service-date`を省略するとJSTの当日を基準日として、前日・当日・翌日の3 serviceDateを生成します。同じ基準日ならファイル内容は同一です。GitHub Actions workflowはfixture生成、builder、独立validator、Environment承認後のdeployをこの順に実装しています。Cloudflareへの実deployとAccess動作検証はまだ行っていません。

### GitHub Actions synthetic CI

`.github/workflows/synthetic-public-ci.yml` は手動起動専用です。mainへworkflowを取り込んだ後、GitHubの **Actions → Synthetic public site CI → Run workflow** から `main` を選びます。main以外を選んだ実行はguard jobで失敗し、buildへ進みません。

workflow_dispatchの`publish_staging`は既定でfalseです。このまま起動するとsynthetic fixtureのrelease-managed buildと独立validationまで実行し、Environment secretsには触れず、deploy jobはskipされます。stagingへ進める場合だけ`publish_staging=true`を選びます。既存Productionがlegacy 17 filesのままである初回移行時だけ、別入力`allow_initial_legacy_migration=true`も明示します。release-managed manifestが欠落/不正ならlegacy扱いへfallbackせず失敗します。

任意の`service_date`にはstrictな`YYYY-MM-DD`実在日を指定できます。省略時は従来どおりbuild開始時点のJST当日を解決してfixture生成へ渡します。`expected_previous_release_id`は`r1-` + 小文字hex 64桁で指定します。release-managed publishでは必須で、build jobがBを生成した直後にB≠期待Aを確認します。B=A、日付不正、期待ID不正、期待A未指定の通常publishはfail closedです。初回legacy移行では期待Aを省略し、取得snapshotが実際にlegacy modeであることをEnvironment承認後に確認します。移行許可flagと期待Aを同時に指定した場合はrelease-managed運用として扱い、snapshotの期待A一致を要求します。

build jobはrunner一時領域で指定（または解決済みJST当日）基準日のsynthetic fixtureから18-file release-managed artifactを作り、期待Aとの比較後に3日間有効のArtifactとして保存します。別runnerのvalidate jobはArtifact IDで同じ成果物を取得し、release-managed independent validatorを実行します。service-date、期待A、B、A/B結果、validator結果をActions Summaryへ記録します。取得時のSHA-256 archive digest検証に加え、validation後の展開済みfile tree digestをEnvironment jobでも再計算して一致を確認します。

### Cloudflare Pages stagingへの承認付きdeploy

`main-branch-guard → build → validate → release-and-deploy`の順です。最後のjobは`publish_staging=true`の場合だけ有効になり、`pages-staging` GitHub EnvironmentのRequired Reviewer承認後に開始します。承認前はAccess/Cloudflare secretsがjobへ供給されず、Production aliasの取得もdeployも起きません。承認後、取得・独立検証したProduction snapshotのcurrent releaseIdが期待Aと一致しなければassembly前に停止します。Cloudflare Access tokenはsnapshot fetchとdeploy前fingerprint recheck stepだけ、Cloudflare API tokenはcredential/project確認とDirect Upload stepだけに渡します。Wrangler `4.152.0`を固定し、既存project `dotchi-ikebukuro-staging`の`main` branchへ、assembly済み成果物をDirect Uploadします。projectが見つからない場合は失敗し、workflowからprojectを作成しません。

`release-and-deploy`はAccess認証付きでProduction aliasのsnapshotを取得し、fetch前後のfingerprintを確認します。初回legacy許可を入力した場合、manifest HTTP 404またはHTTP 200/HTMLが取得したroot `index.html`とbyte単位で一致するときに限り、17-file strict validationへ進みます。HTTP 403、redirect、HTML不一致、その他のmanifest errorは停止します。D-1 assembly、完成artifactの独立validation、alias fingerprint再確認、Direct Uploadの順で、どれかが失敗すればupload stepに到達しません。同workflow内のstaging publishは固定concurrency groupで直列化します。GitHub Actions外のCloudflare Dashboard deployはこのlockに参加しないため、Actions実行中は手動Dashboard deployを避けてください。fingerprint確認からDirect Uploadまで完全排他されるわけではありません。

このPhaseではActions workflowを起動せず、Cloudflareへdeployしていません。既存stagingは引き続きlegacy 17-fileのままです。実際にstagingへ進める前に`publish_staging=true`を選び、初回ならlegacy migrationも別途明示し、Environment approvalを行ってください。Artifactは3日で期限切れになるため、承認待ちが長引いて期限切れになったrunは承認せずworkflowを再実行します。

初回deployはGitHub Actions run **#4** で成功しました。全guard/build/validate/approval/artifact検証/deploy処理が成功し、Wrangler project確認は`project_found`（Wrangler/diagnostic終了コードはいずれも0）でした。Cloudflare Pages `dotchi-ikebukuro-staging`の`main` branchへ、syntheticデータのみを含むdeployment（画面表示ID `13e10889`）を配信しています。既存GitHub Pages root mockは変更していません。

現在の `pages-staging` はRequired reviewerが `bwm2bwm`、管理者による承認回避は無効です。Prevent self-reviewは無効の設定なので、起動者とreviewerが同じ場合は本人承認を許します。別人による承認を必須にする運用なら、初回deploy前にGitHub EnvironmentでPrevent self-reviewを有効にしてください。

Artifactを取得するときはActions run summaryのArtifactsから `synthetic-public-site-<run id>-<attempt>` を選びます。失敗時はrunの **Jobs** から最初に失敗したjob/stepを確認します。build失敗、Artifact ID/digest欠落、Artifact download不在・digest不一致、独立validator失敗、deploy前tree digest不一致、main HEADの更新、project名不一致、token期限切れはfail closedでdeployされません。

Cloudflare project確認stepはsecretとAccount IDの空値だけを表示値なしで検査します。Wranglerのstdout/stderrは一時ファイルへ捕捉し、診断スクリプトは本文を出さず、`result`、許可済み`category`、`wrangler_exit_code`、`diagnostic_exit_code`、Cloudflare errorに含まれる数値codeだけを1行で出します。Wrangler 4.152.0のJSON行にある`Project Name`キーで対象projectを照合します。結果は`project_found`、`project_not_found`、`json_parse_failed`、`json_shape_invalid`、`wrangler_command_failed`等です。未知の構造や認証、権限、Account、rate limit、network、その他API errorを分類できない場合は`unknown`で停止します。値や生ログはActionsへ出さず、トークン値を確認するための`echo`・`set -x`・debug logは使わないでください。

次回失敗時はこの要約行の`result`、`category`、`wrangler_exit_code`、`diagnostic_exit_code`、`cloudflare_error_codes`を見てください。Wranglerが成功してもJSON shape検証に失敗した場合は`wrangler_exit_code: 0`、`diagnostic_exit_code: 1`となります。`project_not_found`ならCloudflare Dashboardで選択中Accountと既存Direct Upload project名を照合します。`wrangler_command_failed`なら表示された分類と数値codeをもとに、Environmentのsecret/variable登録名・空値、TokenのAccount scope/Pages権限、Cloudflare側のAPI状態をそれぞれ管理画面で確認します。要約が`unknown`の場合もdeployを停止し、診断分類を見直すまでは捕捉した生出力をログへ転記しないでください。捕捉ファイルはstep終了時に削除されます。Tokenの有効期限は **2027-01-25** です。期限前にCloudflareで必要最小権限のtokenへ交換し、GitHub Environment secretを更新します。

#### 初回deploy前のCloudflare Access確認

Cloudflare Dashboardで `dotchi-ikebukuro-staging` のAccess設定を開き、通常URL `dotchi-ikebukuro-staging.pages.dev` とPreview URLの両方をAccess application/policyが対象にしていることを確認します。Preview protection設定だけでは通常の `pages.dev` URLを保護しません。許可対象が意図した本人だけで、未認証利用者が許可されないこと、deployment固有URLのホストも保護範囲に入ること、Cache Rules等にAccessを迂回する設定がないことを確認してから初回deployを承認します。API tokenは対象AccountのCloudflare Pages Editだけに絞られていることも確認します。ワイルドカード設定だけに頼らず、実deploy後にDashboardに表示される実際のPreview/deployment URLを個別に試します。

deploy後、次の3種のURLを確認します。通常URL、Pagesが発行したPreview URL（`*.dotchi-ikebukuro-staging.pages.dev`）、そのrunのdeployment固有URLです。

初回deploy時のユーザー確認では、通常URL・deployment固有URL・未認証SafariからのJSON直アクセスでAccess認証画面が表示され、本人認証後の通常URLでアプリが表示されました。ChromeでJSON本文が直接表示されたケースもありましたが、直前の認証Cookieが残っていた可能性を含め原因は未確定です。cookieのない未認証状態を分離した再試験、Preview URL、cache経由の本文非漏えい確認は残っています。基本UI、氷川台の初期選択、目的地切替はiPhone Safariで確認済みです。Brotli、ETag/304、Mac Chromeの初回JSON取得約56ms、iPhoneでの目的地切替体感1秒以下も確認済みですが、列車カードの実機表示と全操作は固定時刻QA環境を使った確認が必要です。

1. シークレットウィンドウ等の未認証セッションでURLを開き、認証画面へ誘導されるか401/403となることを確認します。`curl -sS -D headers.txt -o body.txt --max-redirs 0 URL` でもredirectを追わずHTTP statusと応答を確認します。未認証応答からアプリのHTMLやJSON本文、架空駅・列車のpayload本文が取得できないことを確認してください。Access login画面の本文はアプリ本文と区別します。
2. 認証済みセッションでは同じURLを開き、画面とsyntheticデータが表示されることを確認します。
3. 認証状態を切った別のシークレットセッションから再確認し、`Cache-Control: no-cache`と一意なquery stringを付けた要求も試します。未認証応答が200でアプリ本文を返さないこと、可能な場合は `CF-Cache-Status` と `Age` を記録し、キャッシュHITでも内容が漏れないことを確認します。response bodyはローカルで調べ、公開ログやチャットへ貼らないでください。

確認対象やURLごとに結果・時刻・HTTP status・Access応答かどうかを記録します。未認証でアプリ本文が一つでも取得できたら、そのURLの配信を止め、Cloudflare Accessのhostname/policy/cache設定を修正してから再確認します。GitHub Pages root mockは現在どおり維持し、このworkflowからはdeployしません。今回の公開対象はsynthetic fixtureだけです。

#### deploy結果と復旧

成功時はActionsのdeploy job logとCloudflare Pagesの **Deployments** でdeployment status、commit SHA、branch `main`、project名を照合します。URLが出たら上記Access確認を行います。失敗時は最初の失敗stepを確認し、Artifact期限切れはrun再実行、main HEAD不一致は最新mainから再実行、Access問題は公開URLの利用を止めて設定修正後に再検証します。token期限切れ・権限不足は値を表示せず、期限とCloudflare Pages Edit権限を管理画面で確認します。

誤った内容をdeployした場合はCloudflare PagesのDeployments画面で直前の正常なdeploymentを選び、rollback/再deployの操作を行い、通常・Preview・deployment固有URLのAccess確認を繰り返します。rollback後に現在の通常URLとdeployment SHAが期待どおりか確認し、失敗runとdeployment IDを記録します。静的サイトに実ダイヤは含まれませんが、常にsyntheticであることを示す表示とmarkerを確認します。

#### 固定時刻synthetic列車カードQA（ローカル専用）

Cloudflare stagingの表示時刻に候補がない場合は、共有runtimeへQA専用時計を注入するローカルharnessで確認できます。既定の `cards` は従来どおり固定時刻で、目的地別カード差分は `destination-switch`、実時間に沿って時計とカウントダウンを進める場合は `clock-running` を使います。`destination-switch` は8駅分のsynthetic payloadを作り、発着時刻に駅順の差を付けます。実ダイヤ・本番向けfixtureには反映しません。

MacでWi‑FiのLAN IPv4を取得します。release-managed検証ではWeb CryptoのためChromeから `localhost` を使います。serverの必須LAN bindは維持し、必要に応じて同じQAファイルをloopback portにも追加配信できます。

```sh
ipconfig getifaddr en0
python3 -B scripts/serve_synthetic_public_qa.py --bind 192.168.1.23 --port 8765 --localhost-port 8766 --release-managed
```

2行目の例のIPは1行目で表示されたMacのLAN IPv4に置き換えます。`--release-managed`を付けない場合はlegacy形式、17ファイルのartifactで動作します。付けた場合はbaseline/evening/destination-switchを各18ファイルでbuildし、独立validatorに通します。QA操作パネル、scenario entrypoint、QA時計moduleはartifact外です。

Mac Chromeでは `http://localhost:8766/?scenario=destination-switch` を開き、氷川台・千川・小竹向原・地下鉄成増などへ切り替えて到着時刻の差を確認します。`?scenario=clock-running` を開き、画面の現在時刻と残り時間が進むことを確認します。固定scenarioは時間が進まず、同じ時点を繰り返し確認できます。scenario pickerからも切替できます。目的地、路線別／発車順、直通のみ、最早着、終電badgeは通常どおり確認できます。

iPhone Safariなど別端末では、`--release-managed`を付けずにserverを起動し、起動ログの `http://<MacのLAN IPv4>:8765/?scenario=destination-switch` を開きます。通常のlegacy QAでは利用できますが、release-managedのSHA-256検証に使うWeb CryptoはLAN HTTPで利用できないため、release-managedは `--release-managed --localhost-port 8766` を付けてMac Chromeのlocalhost URLで確認してください。

QA serverの主listenerは明示されたプライベートLAN IPv4だけにbindし、wildcard addressでは起動しません。任意のlocalhost listenerは `127.0.0.1` のみにbindします。HTTPのsynthetic専用harnessで、Cloudflare Accessは通りません。作業後は起動したTerminalで **Ctrl+C** を押すとserverが停止し、一時artifactとharnessが削除されます。起動コマンドはActions workflowから呼ばず、診断コードはCloudflare deploy artifactに含まれません。CIのDOMテストは `node --test tests/preview_runtime_dom_qa.test.mjs` で実行します。

## ファイル構成

- index.html: 画面の骨組み
- styles.css: レスポンシブ表示とカードのスタイル
- app.js: 時計、候補表示、並び替え、直通フィルター
- data.js: 架空の列車・接続データ
- docs/product_spec.md: 確定済み製品仕様の正本
- docs/ui_spec.md: 確定済みUI詳細仕様
- docs/project_state.md: 最新の開発状況、未解決課題、次のタスク
- docs/devlog.md: 過去の調査・実装・検証履歴

## ドキュメントの更新ルール

- 製品として合意・確定した要件は docs/product_spec.md に記載します。予定や未決定事項を確定仕様として書かず、状態を明記します。
- 合意・確定した画面構成、表示、操作、寸法、色などは docs/ui_spec.md に記載します。
- 現在の実装・データ・公開状況、未解決事項、次の作業は docs/project_state.md に記載します。履歴の詳細は重ねて書かず、必要に応じて docs/devlog.md を参照します。
- 調査、実装、仕様変更、検証を行ったら、結果が将来の判断に役立つ場合は日付付きで docs/devlog.md に追記します。現在の状況や未解決事項は履歴ではなく project_state.md を更新します。
- Codexはタスク完了時に、変更が確定仕様・UI仕様・現在状況・未解決事項・検証履歴のいずれかに影響するかを確認し、必要な文書だけを更新します。コード変更がなく、文書に影響しない作業では更新を増やしません。
- 仕様とコードの不一致を見つけた場合は、確定仕様を独断で変えず、不一致と未決定点を project_state.md に記録して判断を待ちます。

## 仕様・開発状況

まず docs/product_spec.md と docs/ui_spec.md を仕様の正本として参照し、実装・未解決事項は docs/project_state.md、経緯は docs/devlog.md を参照してください。
