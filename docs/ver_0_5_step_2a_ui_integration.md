# Ver.0.5 Step 2A — Web UI接続設計

更新日: 2026-10-22

この文書はStep 1のPython旅程生成結果を現行Web UIへ渡す設計案。今回はHTML/CSS/JavaScriptの表示・動作を変更せず、実データを公開リポジトリへ配置しない。製品要件は `product_spec.md`、現行画面は `ui_spec.md` を優先する。

## 1. 現行UIとStep 1のデータ差

現行 `data.js` の `DOTCHI_EXAMPLES` は `id`, `line`, `color`, `departSec`, `travelMin`, `destination`, `kind`, `transfer` を持つ。`departSec` はページ起動からの相対秒、到着は `departSec + travelMin` の架空計算。`app.js` は `boot` に相対秒を足して時計・カウントダウンを作り、同じ候補の `transfer` の有無で直通フィルターを行う。

Step 1 `ItineraryGenerator.generate(service_date)` は `(service_date, origin_trip_id)` 単位の便と旅程を返す。時刻はGTFSサービス日の秒で、24時を超える値がある。直通時刻・最早乗換旅程・ODPT照合状態・欠損状態が別項目で、`primary_itinerary` がない便もある。そこで、現在のmock項目を無理に使い回さず、サービス日を含む絶対時刻を持つview modelへ変換する。

| 表示項目 | 生成器／データ源 | UI adapter案 |
|---|---|---|
| 路線名 | `route_name` / `route_id` | GTFS路線名を表示。路線ID `6` は有楽町線、`9` は副都心線。 |
| 路線色 | UIの表示定義 | データ側に色を持たせず、route_idから現行色 `#c1a026` / `#9C5E31` を選ぶ。未知routeはデータ異常として扱う。 |
| 列車種別 | 一意ODPT照合時のみ `odpt.train_type` | `Local` 等の既知値を日本語ラベルへ対応。未照合・未知コードは「種別不明」。推測しない。 |
| 行き先 | GTFS `headsign` と一意照合時ODPT destination | 既存表示向けの日本語headsignを優先。必要ならODPT駅IDを駅名辞書で変換し、解決できないIDをそのまま画面に出さない。 |
| 池袋発時刻 | `departure_seconds`, `service_date`, `departure_text` | サービス日午前0時（Asia/Tokyo）にサービス秒を加えてepoch msを作る。 |
| カウントダウン | 表示時の `Date.now()` と発車epoch ms | 毎秒再計算。現在時刻以降だけ表示。過去便は候補から除外。 |
| 氷川台到着 | primary journeyの `arrival_seconds` | 同様にepoch ms化。`travelMin`から逆算しない。nullなら到着情報なし。 |
| 直通／乗換 | `primary_itinerary.kind` | `direct` は「直通・乗換なし」、`transfer` は小竹向原乗換と表示。 |
| 乗換待ち | `transfer_wait_seconds` | 分表示は切り上げない。GTFS精度に合わせた「約N分」または秒差を分に変換した整数分を表示し、接続保証ではない注記を維持。 |
| 最早着マーク | 表示対象候補の `arrivalAtMs` | 現在時刻以降かつ現在のフィルターを適用した候補間で最早到着を算出。複数同着時は全てマークするか、決定規則をStep 2Bで固定する。マークは推奨を意味しない。 |
| 直通のみ | `direct_alternative` | 直通旅程が有効な便だけ残し、表示旅程は `direct_alternative` に切り替える。primaryが乗換でも直通代替があれば直通で表示する。 |

現UIは `destination` に列車の行き先を、氷川台着欄には到着時刻を表示している。adapterでもこの意味を分け、目的地「氷川台」と列車行き先（例: 和光市）を混同しない。

### データ不足

- `primary_itinerary == null` は到着時刻を補完せず、通常の時刻比較候補から除外する。UIで非表示にする場合でも、データ診断では除外件数を残す。将来、行き先のみ表示する運用を採るなら「到着時刻データなし」を明示し、最早着マークを付けない。
- 種別・ODPT行先未照合は `unknown` とし、headsignのみ表示する。ODPT駅IDが駅名に変換できない場合はそのコードを表示しない。
- フィード有効期間外はデータ更新エラー相当を出し、古い便や架空の到着時刻へフォールバックしない。
- 番線は `unknown` のまま。60秒以上の候補条件は「乗換目安」であり、接続保証・同一ホーム保証は示さない。

## 2. JavaScript受け渡しpayload案

Step 2BではPython内部dataclassをブラウザーへ直接渡さず、必要な表示情報のみの versioned JSONへ変換する。追加した `scripts/export_local_timetable_payload.py` は次の形をリポジトリ外へ出力する。`--output` がリポジトリ内へ解決される場合は拒否する。

```json
{
  "schemaVersion": 1,
  "dataScope": "local-preview-only",
  "generatedAt": "2026-10-22T00:00:00+00:00",
  "timezone": "Asia/Tokyo",
  "feed": {"version": "20261008", "validFrom": "2026-09-19", "validThrough": "2027-03-12"},
  "connectionPolicy": {"minimumWaitSeconds": 60, "maximumWaitSeconds": 600,
    "platformStatus": "unknown", "connectionGuaranteed": false},
  "serviceDays": [{
    "serviceDate": "2026-10-22",
    "originStationId": "Ikebukuro", "destinationStationId": "Hikawadai",
    "departures": [{
      "id": "2026-10-22:61B0001S00", "originTripId": "61B0001S00",
      "routeId": "6", "routeName": "有楽町線", "headsign": "和光市",
      "trainType": "Local", "destination": "和光市", "odptDestinationIds": ["Wakoshi"],
      "departureServiceSeconds": 21600,
      "primary": {"kind": "direct", "departureServiceSeconds": 21600,
        "arrivalServiceSeconds": 22200, "departureText": "06:00:00",
        "arrivalText": "06:10:00", "arrivalStationId": "Hikawadai", "transfer": null,
        "platformStatus": "unknown", "connectionGuaranteed": false},
      "directAlternative": {"kind": "direct", "departureServiceSeconds": 21600,
        "arrivalServiceSeconds": 22200, "departureText": "06:00:00",
        "arrivalText": "06:10:00", "arrivalStationId": "Hikawadai", "transfer": null,
        "platformStatus": "unknown", "connectionGuaranteed": false},
      "bestTransferAlternative": null,
      "transferCandidateCount": 0, "status": "ok", "dataQuality": []
    }]
  }],
  "excludedServiceDates": []
}
```

これはschema例であり、列車ID・時刻等は実在便を示すものではない。実payloadでは、`directAlternative`／旅程がない項目はnull。時間フィールドはサービス秒と表示用文字列を保持し、カード向けepoch値はブラウザー側で算出する。`generatedAt`, `feed`, `connectionPolicy` は運用・診断用の内部metadataとし、通常の列車カードには表示しない。目的地を増やす際は `originStationId`, `destinationStationId` とjourneyの駅IDを利用し、駅別stop_id対応表をadapterまたはPythonモデルに渡す。

payloadに含めないもの: GTFS生行、stop_times全停車列、ODPT JSON生レコード、APIキー・環境変数、未使用のGTFS列。`scripts/export_local_timetable_payload.py` は `primary`, `directAlternative`, `bestTransferAlternative` とカードに必要な項目だけを含める。

## 3. ローカルデータ受け渡し方式

| 方式 | 評価 |
|---|---|
| 実ダイヤ値を `data.js` に直書き | 簡単だが誤コミット・公開混入の危険が高く、採らない。 |
| `public`/リポジトリ内JSONへ出力し `.gitignore` で隠す | `git add -f` や設定漏れで公開し得るため採らない。 |
| リポジトリ外の一時ディレクトリにpayload、別の一時previewディレクトリにHTML/CSS/JSの作業コピーを置いてHTTP配信 | 推奨。元UI・配信ファイルを変えず、ローカル限定のadapterとJSONを同じstaging rootから配信できる。 |
| file:// からJSONを直接読む | ブラウザーのfetch制約、CORS、相対パス差で再現性が低いため使わない。 |

payload exporterの既定出力はOS一時ディレクトリの `dotchi-ikebukuro-local/timetable.json`。有効期間外のservice dateはJSONの `excludedServiceDates` に記録してskipする。Step 2Bのpreview起動補助はUIファイルを一時領域へコピーし、local loader/adapterを追加してその領域だけをHTTP serverで配信する。`.gitignore`だけに依存せず、出力パスがrepository外であることをツールで検証する。公開版の `index.html` がlocal payloadを参照しないことをdiffで確認してから終了する。今回そのpreview用UIやHTTP serverは作らず、既存画面は未変更。

## 4. 日付・現在時刻

1. JavaScriptの時計・日付表示は `Asia/Tokyo` を明示し、ホスト端末のtimezone設定に依存させない。epoch millisecondは標準Dateで更新、表示文字列は `Intl.DateTimeFormat` のtimeZone指定で整える。
2. 運行日と暦日は別概念。ブラウザーで現在の東京日付を `today` とし、GTFS生成対象日は `yesterday`, `today`, `tomorrow` の最大3つを使う。昨日のservice dayに含まれる24時超便が本日の0時台に走るためである。フィード有効期間外の対象日はskipし、残る有効日もなければ期間外状態にする。
3. 実時刻は `serviceDate` 東京午前0時のepochに `serviceSeconds × 1000` を加えて算出する。たとえばservice day 2026-10-22の24:02は暦日2026-10-23の00:02を表す。秒数を86400で剰余化してservice dateを失わない。
4. 表示対象は `departureAtMs > nowMs` を満たす候補。翌暦日を含む候補期間を決め、推奨初期値は「現在から24時間以内」。乗車候補が途切れないよう、翌日のservice dayまで生成して時刻窓で絞る。
5. カウントダウンと現在時刻は既存同様1秒ごとに更新。出発epochと到着epochは毎秒再計算せず、候補抽出のみ現在時刻に合わせて再評価する。画面を日付跨ぎで開いたままにしても昨日・今日・翌日の3日payloadを使い続けられるが、データのgeneratedAtを過ぎた場合は再生成／再読込を案内する。
6. 連続運用時の古いpayloadを検知し、feed有効日外・生成日からの過剰経過・空データを区別する。期限外に架空データへ切り替えない。

## 5. 候補選択と現UIモード

- 一意表示keyは `(serviceDate, originTripId)`。ひとつの池袋発tripを一枚のカードにし、直通と乗換をそれぞれ別カード化しない。
- `primary` が有効で、発車時刻が現在以降の便だけを通常リスト候補にする。`primary` はStep 1で最早着・同着直通優先により一件へ確定済み。
- 最早着マークは現在時刻以降の表示対象の `primary.arrivalAtMs` 最小値に付ける。路線別／発車順のモードで同じ全体候補を比較し、モード切替で最早着そのものを変えない。直通フィルターを入れた後も表示対象の最早着に再計算するか、全候補のままにするかはStep 2Bで製品仕様に合わせて固定する。推奨はフィルター後に再計算し、画面上の「最早着」が表示候補群を意味するようにする。
- 路線別は有楽町線→副都心線、各路線内を `departureAtMs` 順。発車順は全路線を同じ値で昇順。秒まで同じ場合はroute_id、serviceDate、originTripIdで安定sortする。
- 直通のみは `directAlternative != null` を条件にし、採用時は表示旅程をdirectに置き換える。直通が有効でもprimaryが乗換の便を消さない。現代表日ではそのケースはないが一般規則を明示する。
- transfer primaryは「小竹向原乗換・待ち約N分」を表示。接続非保証・番線未確認は共通説明か注記で示し、3/4番線・同一ホームの断定はしない。
- `primary == null` は到着比較できないので通常候補に混ぜない。初期はdebug/diagnostics集計に残す。画面から完全に消すか「到着時刻不明」として補助行を出すかはStep 2Bでユーザー向け表示を決める。どちらでも架空到着の生成、最早着マーク、直通扱いはしない。
- 路線色はroute_idによるUI定数。GTFS/ODPTに頼らない。行き先の表示名がない便は「行き先不明」とし、空文字をそのまま「行」に連結しない。

## 6. Step 2B 実装順序

1. このJSON schemaを固定し、payload exporterの出力を `to_dict()` とのキー／欠損値単位で検査する。export先repository外チェック、空payload、期間外を検証する。
2. JS adapterでroute_id、ODPT trainType、station ID、service secondsをUI用view modelへ変換する。GTFS行き先headsignとODPT行先IDを混同しない。
3. UIカードにepoch時刻を渡し、相対 `boot + departSec`・仮 `travelMin` の計算に依存しないデータ経路をローカルpreviewで検証する。
4. current time、previous/current/next service date、0時台・24時超、今日の日付変更、有効期間外、到着なし、ODPT未照合をローカルで確認する。
5. 路線別／発車順、最早着、直通のみ、同一trip重複防止、候補なしの回帰確認。公開用HTML/APIデータへの実payload参照がないことを確認する。
6. ローカルpreviewを閉じ、生成payload/stagingを削除またはOS一時領域に留める。公開・配信変更は別作業とする。

## 7. Step 2B-1 adapter実装（2026-10-22）

`scripts/timetable_adapter.mjs` はDOMや既存 `app.js` に依存しないES module。`validateTimetablePayload(payload)` でversion、scope、Asia/Tokyo、feed期間、serviceDays、便・旅程、接続条件を検証し、`buildBoard(payload, options)` が表示候補を返す。オプションは `nowMs`, `horizonMs`（既定24時間）, `directOnly`, `mode`（`line` / `departure`）。

返却 `items` はカード用view model。既存表示に合わせた `line`, `color`, `kind`, `destination`, `transfer.station`, `transfer.wait` に、実時刻用の `departureAtMs`, `arrivalAtMs`, `departureText`, `arrivalText` を加える。serviceDate、origin/destination/arrival station ID、GTFS trip ID、ODPT照合状態、platform unknown、connection guarantee falseも保持する。カウントダウンは `max(0, ceil((departureAtMs-nowMs)/1000))` で画面側から算出できる。発車／到着表示時刻は絶対時刻からAsia/Tokyoで生成する。`departSec` と `travelMin` は返さず、従来の相対・仮所要モデルへ誤接続できないようにする。

- 表示対象は `nowMs < departureAtMs <= nowMs + horizonMs`。serviceDateがfeed有効期間に含まれない便は除外理由 `outside_feed_validity` を返し、東京時間の前日・当日・翌日以外のservice dayは `outside_service_date_window` で除外する。service dateの午前0時JSTにservice secondsを足すので、前日24:xxと当日00:xxを正しい暦時刻へ変換する。
- 同一実列車の重複判定keyは `routeId + originTripId + absolute departureAtMs`。同一tripが別service dateから同一epochへ現れたら一件にする。GTFS trip_idが異なるものは、時刻一致だけで同一列車とみなさない。
- directOnlyは `directAlternative` がある便を選び、表示旅程を直通へ切り替える。なければ `direct_unavailable` として除外する。通常表示は `primary` を使う。
- 路線別は有楽町線→副都心線、発車時刻順は全路線混在。最早着は現在時刻・24時間窓・直通フィルターを適用した後に、モード共通の全候補から一件選ぶ。同着なら発車時刻が早い便、なお同値ならroute/serviceDate/trip ID順。`bestId` / `isBest` は常に一件のみ。
- `primary` なし、arrival seconds null、直通なし等は通常候補にせず、`excluded` に理由とdataQualityを残す。種別は `Local`→「各駅停車」、`CommuterExpress`→「通勤急行」の既知値だけ変換し、それ以外は「種別不明」。行先はpayloadのGTFS headsign由来文字列のみを表示し、欠落時は「行き先不明」。ODPT destination IDから推測しない。
- 不正構造、サービス秒、路線、日付、旅程整合、接続条件違反は `PayloadValidationError`。欠損到着そのものは旅程を除外し、推測値を作らない。

テストはNode標準 `node:test` を用い、npm依存を追加しない。

```sh
node --test tests/timetable_adapter.test.mjs
TZ=UTC node --test tests/timetable_adapter.test.mjs
```

いずれも12件通過。これはadapter単体検証であり、既存UIへの接続・画面表示確認ではない。Step 2B-2ではlocal preview専用stagingへこのmoduleをコピーし、既存mockと並行するadapter data sourceからカードview modelをUIへ渡す。`index.html` / `app.js` / `data.js` / `styles.css` は今回変更していない。

## 未解決事項

1. primaryなし4便（平日）／9便（土曜・祝日）を画面で「到着時刻不明」と表示するか、通常候補から除外して件数だけ通知するか。
2. GTFS `trip_headsign` を第一行先表示にしてよいか。ODPT行先IDを日本語駅名へ変換するstation辞書の維持元。
3. Step 2B-2 local previewで現行mock data sourceと実ダイヤdata sourceをどう切り替えるか。公開版へlocal payloadを参照させない構成。
4. payloadを毎回起動時に生成するか、日付単位で作り置きするか。preview起動時再生成を推奨し、生成時刻の鮮度上限を決める。

## 再現用ローカル検証

payloadは実行時に指定したOS一時ディレクトリへ出力する。例:

```sh
python3 scripts/export_local_timetable_payload.py \
  --service-date 2026-10-21 --service-date 2026-10-22 --service-date 2026-10-23
```

出力先を変える場合もrepository外のパスを指定する。生成物を `local_data/`, `public/`, repository内の `data.js` / JSONへ保存しない。
