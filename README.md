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

`--service-date`を省略するとJSTの当日を基準日として、前日・当日・翌日の3 serviceDateを生成します。同じ基準日ならファイル内容は同一です。CIではfixture生成、builder、独立validator、承認後のdeployの順に接続する想定です。workflowとCloudflare設定はまだありません。

### GitHub Actions synthetic CI

`.github/workflows/synthetic-public-ci.yml` は手動起動専用です。mainへworkflowを取り込んだ後、GitHubの **Actions → Synthetic public site CI → Run workflow** から `main` を選んで起動します。main以外を選んだ実行はguard jobで失敗し、buildへ進みません。

workflowはrunner一時領域でJST当日基準のfixtureを生成し、public siteをbuildして17ファイルをartifactに保存します。別jobがartifactをダウンロードし、独立validatorを実行します。artifactは3日で期限切れになります。取得する場合はActionsのrun summaryにあるArtifactsから `synthetic-public-site-<run id>-<attempt>` を選びます。Artifactがない場合はdownload stepが失敗します。失敗時はrunのJobsから失敗job/stepを開き、build log、download結果、validatorの理由を確認してください。

検証成功時も外部公開は行いません。Phase 4-4でCloudflare deployを接続する場合は独立したdeploy jobを追加し、少なくとも `needs: validate` を必須にします。そのjobだけにCloudflare credentialを渡し、build/validation jobへCloudflareやODPTのsecretsを渡さない構成とします。

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
