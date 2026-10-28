# T12 Phase 4-7 — 静的配信のrelease世代整合性 詳細設計

設計日: 2026-10-28（JST）  
対象: Cloudflare Pages Direct Upload staging。Phase 4-8で実装する前の設計。  
対象データ: まずsynthetic fixture。ODPT実データは後続の別ゲートで導入。

## 1. 採用方式

**root manifest + content-addressed releaseId + 世代別JSON + JSON SHA-256検証**を採用する。manifestはruntime起動時に一度取得し、そのruntimeの間は同じreleaseへpinする。manifestが示す各駅payloadとmanifestのreleaseId、bytes/hash、schema/期間、駅IDを照合し、1項目でも合わなければfail closedする。Cloudflare Pagesは引き続き静的assetをDirect Uploadし、Workers/KV/Functions/R2は導入しない。

同じCloudflare PagesのProduction aliasは「現在のdeploymentに含まれるファイル」へ解決される。新deploymentへ旧JSONを自動mergeする仕組みは現在のworkflowにない。よって、各deploy前にCIがProduction aliasの現行manifestと期限内generation pathを取得し、検証して新しいartifactへコピーする。旧Deployment固有URLやCDN cacheにファイルの永続性を期待しない。CloudflareのPages docsもasset cacheはdeploy間で継続保証されず、edge cacheは最長TTLがあってもいつでも消える可能性を記載している。`[Serving Pages](https://developers.cloudflare.com/pages/configuration/serving-pages/)`。

## 2. releaseId仕様

### 2.1 IDの意味と生成

`releaseId`はデータ更新時刻やActions run IDではなく、**公開runtime一式と全駅payloadからなるrelease bundleの内容・契約識別子**とする。方式は`r1-<64桁hex SHA-256>`。`r1`はID preimage規則のversionで、アルゴリズムやcanonicalizationの変更時は`r2`に上げる。

Buildは次の順で行う。descriptor serializationは[RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)に固定する。

1. 8駅すべてのvalidated public payloadを集め、共通schema/serviceDate/metadata条件を確認する。
2. ID計算前のcanonical release descriptorを作る。対象は `manifestSchemaVersion`, `jsonEnvelopeSchemaVersion`, `payloadSchemaVersion`, `runtimeContract`, `publicDataScope`, `builderContractVersion`、公開HTML/CSS/JS asset pathとSHA-256、8駅payloadのcanonical payload SHA-256。stationsはstation IDでsortし、assetsはUTF-8 path byte順にsortする。
3. descriptorをRFC 8785 JSON Canonicalization SchemeのUTF-8 bytesにし、SHA-256を計算。`r1-`を付けてreleaseIdとする。
4. 各payloadに同一の`releaseId`を入れてrelease envelopeを生成し、最終JSONのUTF-8 bytes、SHA-256、byte lengthを計算する。これらはmanifestへ記録する。
5. manifestを生成し、最終artifactの全tree digestをCIで計算する。manifest自身は自分のhashを持てないため、Actions Artifact digest/tree digestで検証し、manifest内では各JSONをhash検証する。

descriptor内payload hashはrelease envelope注入前、manifest内JSON hashはenvelope注入後の最終bytesを対象とする。自己参照を避けながら、実配信JSONの完全なhashを検査できる。`releaseId`はcurrent client assets + current 8-station data releaseを識別する。manifest内のretained historyや`publishedAt`が更新されるとProduction upload treeは変わるが、current release内容が同じならreleaseIdは同じでよい。deploy単位で全fileを識別する役目は現行CIのartifact digest/tree digestが担い、releaseIdと混同しない。hashは同一性・破損検知であり、署名ではない。CloudflareとCIの配信経路の外部者に対する真正性証明ではない。

### 2.2 再現性・変更時のID

- 同じ8駅payload、公開assets、contract/schema/builder contractで再生成すると、releaseId・8 JSON bytes・generation URLは同一になる。日時だけではIDを作らない。
- fixtureの基準serviceDateが変わり、payload bytes/期間が変わればIDも変わる。fixtureの再実行日時自体はIDに入れない。
- 公開JSON内容、station集合、HTML/JS/CSSの公開bytes、manifest/payload schema、runtime contractが変わればdescriptor hashが変わる。
- builderの実装を整理しても出力契約・生成bytesが同じならreleaseIdは同じ。出力意味や生成契約を変える場合は`builderContractVersion`を上げ、IDを変える。
- CI run ID、deployment ID、publish timestampはreleaseIdに含めない。同一bundleのretryで別IDを作らず、同じIDが既にProductionにあればその`publishedAt`を保持する。
- 新しいデータscopeがODPTになっても同じID方式を使える。ID descriptorへ入力データそのものは含めず、validated public payload bytesとその出力契約を含める。秘匿・内部ODPT raw bytesを公開manifestへ含めない。

### 2.3 関連日時とversionの役割

| 項目 | 用途 | releaseIdとの関係 |
|---|---|---|
| `releaseId` | 公開runtime/data bundleの内容識別・URL namespace | bundle hash由来。日時ではない |
| `generatedAt` | payload作成時刻。synthetic現行fixtureでは期間先頭日の00:00 JSTという決定値 | payload hashに含まれる。syntheticの意味は現状維持し、実時刻と誤読させない。ODPT出力では実際の生成時刻にする場合、仕様とfreshness判定を別途定義 |
| `serviceDateRange` | payloadに含む運行日範囲 | 駅間一致を検証。releaseの識別子ではない |
| `feed.validFrom/validThrough` | ソースfeedのデータ適用範囲 | manifestへ共通summaryとして記載。releaseIdの代用にしない |
| `feed.version` | 入力feedの版/識別。ODPT/GTFS等ソース仕様の値 | 内容metadata。異なるfeedでも同じbundle hashならreleaseIdはcontent/contract上で決まる |
| `publishedAt` | 最初にproduction aliasへpublishした時刻、retention時計 | deploy assembly metadata。ID preimageに含めない。同release retryで更新しない。ローカルbuildでは`null`、publish assemblyで実時刻を設定 |

## 3. manifestとJSON schema

### 3.1 root manifest例

```json
{
  "schemaVersion": 1,
  "releaseId": "r1-7d8f3d24cdded1227a859f7718f9e76fdb2c4e9b72f38a91d64f4fa0c07a9123",
  "releaseDescriptor": {
    "manifestSchemaVersion": 1,
    "jsonEnvelopeSchemaVersion": 1,
    "payloadSchemaVersion": 1,
    "runtimeContract": "dotchi-public-runtime-v2",
    "publicDataScope": "public-display-v1",
    "builderContractVersion": "dotchi-public-builder-v1",
    "assets": [
      { "path": "index.html", "sha256": "<64 lowercase hex>" },
      { "path": "local_preview_payload_loader.mjs", "sha256": "<64 lowercase hex>" },
      { "path": "preview.css", "sha256": "<64 lowercase hex>" },
      { "path": "preview_core.mjs", "sha256": "<64 lowercase hex>" },
      { "path": "preview_public.js", "sha256": "<64 lowercase hex>" },
      { "path": "selection.mjs", "sha256": "<64 lowercase hex>" },
      { "path": "styles.css", "sha256": "<64 lowercase hex>" },
      { "path": "terminal_ui.mjs", "sha256": "<64 lowercase hex>" },
      { "path": "timetable_adapter.mjs", "sha256": "<64 lowercase hex>" }
    ],
    "stations": [
      { "stationId": "ChikatetsuAkatsuka", "payloadSha256": "<64 lowercase hex>" },
      { "stationId": "ChikatetsuNarimasu", "payloadSha256": "<64 lowercase hex>" },
      { "stationId": "Heiwadai", "payloadSha256": "<64 lowercase hex>" },
      { "stationId": "Hikawadai", "payloadSha256": "<64 lowercase hex>" },
      { "stationId": "Kanamecho", "payloadSha256": "<64 lowercase hex>" },
      { "stationId": "KotakeMukaihara", "payloadSha256": "<64 lowercase hex>" },
      { "stationId": "Senkawa", "payloadSha256": "<64 lowercase hex>" },
      { "stationId": "Wakoshi", "payloadSha256": "<64 lowercase hex>" }
    ]
  },
  "runtimeContract": "dotchi-public-runtime-v2",
  "jsonEnvelopeSchemaVersion": 1,
  "payloadSchemaVersion": 1,
  "dataScope": "public-display-v1",
  "publishedAt": "2026-10-28T02:15:00Z",
  "generatedAt": "2026-10-27T00:00:00+09:00",
  "serviceDateRange": { "from": "2026-10-27", "through": "2026-10-29" },
  "feed": {
    "version": "synthetic-v1",
    "validFrom": "2026-10-27",
    "validThrough": "2026-10-29",
    "sourceUpdatedAt": null
  },
  "applicationPeriod": { "startsAt": "2026-10-27T00:00:00+09:00", "endsAt": "2026-10-30T00:00:00+09:00" },
  "stations": {
    "Kanamecho": { "url": "/releases/r1-7d8f3d24cdded1227a859f7718f9e76fdb2c4e9b72f38a91d64f4fa0c07a9123/timetable-Kanamecho.json", "sha256": "<64 lowercase hex>", "bytes": 123456 },
    "Senkawa": { "url": "/releases/r1-7d8f3d24cdded1227a859f7718f9e76fdb2c4e9b72f38a91d64f4fa0c07a9123/timetable-Senkawa.json", "sha256": "<64 lowercase hex>", "bytes": 123456 },
    "KotakeMukaihara": { "url": "/releases/r1-7d8f3d24cdded1227a859f7718f9e76fdb2c4e9b72f38a91d64f4fa0c07a9123/timetable-KotakeMukaihara.json", "sha256": "<64 lowercase hex>", "bytes": 123456 },
    "Hikawadai": { "url": "/releases/r1-7d8f3d24cdded1227a859f7718f9e76fdb2c4e9b72f38a91d64f4fa0c07a9123/timetable.json", "sha256": "<64 lowercase hex>", "bytes": 123456 },
    "Heiwadai": { "url": "/releases/r1-7d8f3d24cdded1227a859f7718f9e76fdb2c4e9b72f38a91d64f4fa0c07a9123/timetable-Heiwadai.json", "sha256": "<64 lowercase hex>", "bytes": 123456 },
    "ChikatetsuAkatsuka": { "url": "/releases/r1-7d8f3d24cdded1227a859f7718f9e76fdb2c4e9b72f38a91d64f4fa0c07a9123/timetable-ChikatetsuAkatsuka.json", "sha256": "<64 lowercase hex>", "bytes": 123456 },
    "ChikatetsuNarimasu": { "url": "/releases/r1-7d8f3d24cdded1227a859f7718f9e76fdb2c4e9b72f38a91d64f4fa0c07a9123/timetable-ChikatetsuNarimasu.json", "sha256": "<64 lowercase hex>", "bytes": 123456 },
    "Wakoshi": { "url": "/releases/r1-7d8f3d24cdded1227a859f7718f9e76fdb2c4e9b72f38a91d64f4fa0c07a9123/timetable-Wakoshi.json", "sha256": "<64 lowercase hex>", "bytes": 123456 }
  },
  "retainedReleases": [],
  "legacyCompatibilityV1": null
}
```

For compactness, the sample shows no retained release. Each actual `retainedReleases` entry has `releaseId`, `publishedAt`, `retiredAt`, `retainUntil`, `serviceDateRange`, and the same complete 8-station URL/hash/bytes map used above. Validator rejects partial sets. `retainedReleases` is operational carry-forward metadata and does not change current releaseId. `generatedAt`, `feed`, and `applicationPeriod` repeat common values from all 8 inner payloads and let the browser/retention job validate common metadata; validator requires exact equality. `legacyCompatibilityV1` is null except during the one-time v1-to-envelope migration; then it names root flat JSON files' hashes, source legacy digest, and expiry.

### 3.2 release JSON example

Generation path JSON uses a small release envelope around the existing public payload. This keeps the validated `public-display-v1` payload schema unchanged, while `releaseId` remains inside each JSON document as required. The current allowlist projector continues to build only the inner v1 payload; the release builder wraps it after projection. Migration-only root flat aliases remain byte-for-byte schemaVersion 1 for old runtimes.

```json
{
  "schemaVersion": 1,
  "releaseId": "r1-7d8f3d24cdded1227a859f7718f9e76fdb2c4e9b72f38a91d64f4fa0c07a9123",
  "stationId": "Hikawadai",
  "payloadSchemaVersion": 1,
  "dataScope": "public-display-v1",
  "payload": {
    "schemaVersion": 1,
    "dataScope": "public-display-v1",
    "generatedAt": "2026-10-27T00:00:00+09:00",
    "timezone": "Asia/Tokyo",
    "feed": { "version": "synthetic-v1", "validFrom": "2026-10-27", "validThrough": "2026-10-29", "sourceUpdatedAt": null },
    "serviceDays": []
  }
}
```

`serviceDays` is abbreviated. In full files, existing profile schema fields remain. Manifest and all station envelopes must agree on releaseId; all inner station payloads must also agree on feed metadata, application period, serviceDate list, timezone, schema, and data scope. The outer envelope version is independent of the existing public payload schemaVersion. Runtime verifies the envelope, then passes only `payload` into the unchanged timetable adapter contract.

## 4. URL layout、cacheとDeployment切替

```text
index.html
styles.css
preview.css
preview_public.js
preview_core.mjs
timetable_adapter.mjs
local_preview_payload_loader.mjs
selection.mjs
terminal_ui.mjs
manifest.json
releases/<releaseId>/timetable-Kanamecho.json
releases/<releaseId>/timetable-Senkawa.json
releases/<releaseId>/timetable-KotakeMukaihara.json
releases/<releaseId>/timetable.json
releases/<releaseId>/timetable-Heiwadai.json
releases/<releaseId>/timetable-ChikatetsuAkatsuka.json
releases/<releaseId>/timetable-ChikatetsuNarimasu.json
releases/<releaseId>/timetable-Wakoshi.json
# 旧v1タブ互換窓のみ:
timetable-Kanamecho.json ... timetable-Wakoshi.json
```

Pagesの現在のdefaultは200応答にETagを付け、再検証時に304を返し、圧縮を提供する。cacheable static assetは標準で`public, max-age=0, must-revalidate`。manifestは`fetch(..., {cache: 'no-cache'})`で毎回revalidateする。304ならブラウザーが持つ同じmanifest representationを使う。そのmanifestの参照generationがProduction aliasから引き継がれている限り、整合する。versioned JSONはimmutable pathのため長期cacheを許可できるが、初期実装はPages default revalidationを維持し、custom `_headers`/Cache Rulesを追加しない。性能検証後に長期cacheを導入する場合もgeneration pathだけに限定し、Pages asset cache自体を永続保存とみなさない。`[Serving Pages](https://developers.cloudflare.com/pages/configuration/serving-pages/)`, `[Pages headers](https://developers.cloudflare.com/pages/configuration/headers/)`。

ManifestとHTML/JSが異なるDeploymentから配信されても、`<html data-runtime-contract="dotchi-public-runtime-v2">`とJSの`RUNTIME_CONTRACT`を起動時照合し、manifestの同じcontractと比較する。互換contractなら古いtab/runtimeが新manifestを読み、そのreleaseを一貫して使える。contract mismatchはmanifest取得後の初期化拒否とreload案内。root manifestが古い304 representationに戻った場合も、そのmanifest IDをsession内固定し、列挙generation pathのhashを確認するため、無関係なcurrent flat JSONは使わない。もし古いJSが未知manifest形式を取得したらfail closed。

## 5. 旧世代の取得・保持・削除

### 5.1 保持ポリシー

全generationを無期限に残さず、次のdeadlineで期限内releaseを保持する。

```text
effectiveValidityEnd = min(
  applicationPeriod.endsAt,
  midnightAfter(feed.validThrough, Asia/Tokyo)
)
retainUntil = min(
  retiredAt + 14 days,
  max(retiredAt + 7 days, effectiveValidityEnd + 48 hours)
)
```

`effectiveValidityEnd`は現在のruntime gateである`applicationPeriod.endsAt`と、inclusiveな`feed.validThrough`の翌日00:00 JSTの早い方。`retiredAt`はreleaseがProduction aliasのcurrent positionから外れてretainedへ移る時刻であり、保持時計は初回`publishedAt`ではなくretirementから開始する。これで直前releaseを最低7日保持する。service validity終了後48時間の猶予も考慮し、上限14日で将来の適用期間が長いfeedによる無制限保存を防ぐ。期限はUTC ISO timestampでmanifestへ格納し、判定はUTC instantで行う。短時間の誤削除・clock skew対策として削除処理に追加24時間の安全marginを置くが、公開`retainUntil`そのものは変えない。Cloudflare rollbackで過去releaseがcurrentへ戻った場合は`retiredAt`を解除し、次にcurrentから外れる時点から期限を再計算する。古いtabを無期限保証しない。14日超過のsessionはreloadでlatest manifestへ移動し、失効済みgeneration URLが404ならデータを出さずreloadを案内する。

複数回更新時は現行manifestに列挙された**すべての`retainUntil`未到来release**を引き継ぐ。期限到来済みは除外する。新currentをdeployすると直前currentに`retiredAt=deployment publish instant`を付けて保持時計を開始する。retained releaseがrollbackでcurrentへ戻った場合は`retiredAt`を解除し、次回retired時点から期限を再開する。manifestの`legacyCompatibilityV1`が未期限ならそのflat root 8 JSONも同じhashで引き継ぐ。固定件数で直近N世代だけを残すことはせず、min 7d graceを保証する。削除単位はrelease directory全体（8 JSON）と、そのreleaseがcurrentでなくなった時点のretainedReleases entry。HTML/CSS/JSはversioned generation directoryに含めず、root shellのみ現行版を配信。

### 5.2 Production aliasからの引継ぎ

新しいWrangler Direct Uploadは全site treeを新Deployment内容として作るため、旧URLが残ることとProduction aliasから旧JSONが取れることを区別する。引継ぎはdeploy前に次の順で実施する。

1. GitHub Environment承認後のdeploy jobで、Access service tokenを使いProduction aliasの`manifest.json`をGETする。tokenは読取stepだけへ環境注入し、値・HTTP request headersをlogしない。Cloudflare Access service tokenはclient ID/secret headerで保護appへ自動認証できる。`[Service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)`。
2. manifest schema、releaseId/path対応、retainUntilを検証。期限内のcurrent/retained generationの8 JSON全てをProduction aliasから取得する。`legacyCompatibilityV1`が存在し未期限ならroot flat JSON 8個も取得する。
3. raw bytesのSHA-256/bytesを照合し、JSON内releaseId、schema、station ID、serviceDate/feed metadataも検証。期限内releaseの一部欠落、hash不一致、Access/HTTP失敗、manifest不正、retention size budget超過なら**deploy全体を中止**。欠けたreleaseを静かに落としてuploadしない。
4. new generationと未期限generation/legacy aliasesを新artifactへassemble。expiry済みgeneration/aliasesを除去し、新manifestを書き、完成artifactを再度independent validatorへ通してtree digestを記録してからWranglerへ渡す。
5. deploy直前にProduction aliasのcurrent releaseIdが取得時と同じか再確認できる場合は一致必須。別deploy/rollbackが入ったらabortし、次runで現manifestを読み直す。CI concurrencyに加え、手動Dashboard deployとの競合も扱う。

取得元は毎回のProduction alias内manifestとversioned files。3日で期限切れするGitHub Actions Artifactは同一run内build→validate→deployのhandoffにだけ利用し、世代データ永続保存にはしない。過去Artifact消失でdeploy不能にならない。Access service tokenをEnvironment secretsへ追加しない場合、現在のAccess保護を維持したまま自動取得できないため、継承stepをfail closedで停止する。

### 5.3 初回v1→manifest runtime v2移行

現在のProduction artifactはpublic payload schema v1でflat root JSONを持ち、manifest/generation pathがない。初回移行だけ、Production aliasの8 flat JSONを取得し、内容/共通serviceDateを検証して「legacy v1 compatibility」root JSONとして新deploymentに同じpath/bytesで複製する。旧tabからのstation switchは最大14日の移行窓で旧Deploymentと同じv1 payload bytesへ向かう。manifest/runtime contract v2の新clientはこれらのflat aliasを絶対に参照しない。`legacyCompatibilityV1.expiresAt`までaliasを引き継ぎ、その後除去する。

既にユーザーcacheにあるA payloadからB deployment内のflat JSONを取りに行く旧v1 runtimeは、A bytesのflat aliasを保持すればA/Aで一貫する。これだけは既存tabをreleaseId-awareに遡及変換できないための限定移行策。移行14日後に開いたままのv1 tabがflat URLを再取得した場合は404で停止し、旧コードに専用reload CTAがないためgeneric fetch failureとなる可能性がある。新規v2 runtime/manifest generationには混在しない。v1 aliasesを無期限保持すれば永続的に無releaseId pathを公開することになるため採用しない。

### 5.4 sizeとCloudflare制約

現在は9個の非JSON shell/runtime assetと8個のroot JSONで17 files。新構成は`9 shell + 1 root manifest + 8 × retainedGenerationCount`、移行compatibility期間はさらに8 flat legacy JSONで、**`18 + 8R` files**（Rはcurrent含む保持中generation数）。1世代だけなら26 files、日次更新を14日保持する最悪見込みは15 generations + compatibility 8で138 files。厳密なRは各`retainUntil`で決まる。validatorは実際のrecursive regular file countを計算し、`expected = 10 + 8R (+8 legacy)`と一致させる。directoryはfile数に含めず、symlink/extra pathを拒否。

Cloudflareの現行公式Pages limits（2026-10-28確認）はFreeで20,000 files/site、単一asset最大25 MiB。日次1回のdistinct releaseなら14日windowにcurrent含め最大15 generation、legacy期間は138 files想定だが、複数回/日更新ならRは15を超え得る。CIは実際のrecursive file countと全file size/tree total bytesを計測し、20,000 files、単一file 25 MiB、設定したサイトbudget超過、著しい前回比増をdeploy前に拒否する。全体budgetの具体値は現在artifactのサイズをPhase 4-8時に測り、通常generation合計の2〜3倍を起点に決める。Cloudflare docsに総site bytes上限の明記はこの設計確認時点で見つからなかったため、当面の実用budgetはrepository側で設ける。`[Pages limits](https://developers.cloudflare.com/pages/platform/limits/)`。

## 6. runtime状態遷移と表示

| 状態/イベント | 表示と候補 | cache・fetch | retry / update |
|---|---|---|---|
| 初回起動 | clock/controlsを表示し「時刻表を読み込んでいます…」。候補は空 | fetch manifest `no-cache`。payloadはまだfetchしない | errorは自動retryせず手動更新を案内 |
| manifest成功・contract/schema適合 | pinned release IDを内部状態へ保持 | release ID、manifest body、station mapをruntime lifetime固定 | 普通の目的地切替ではmanifestを再取得しない |
| manifest取得失敗・不正・client contract mismatch | fail closed。候補空、明確な「最新データを確認できません。再読み込みしてください。」 | 既存session storage/localStorage manifest fallbackなし。半端なmapで起動しない | 「再読み込み」ボタン。無限auto reloadなし |
| JSON成功 | 選択駅の通常status/候補を表示 | raw response bytesをSHA-256・bytes照合→JSON parse→releaseId/station/schema/metadata→adapter。検証後だけLRUへ | 通常通り切替 |
| JSON HTTP error/404/5xx/network | 該当駅の候補空。読み込みerror/status | 不正/失敗値はLRUに保存しない。別release aliasへfallbackしない | 自動retryせず手動更新を案内 |
| releaseId不一致 | fail closed、該当駅候補空 | cacheへ入れず、runtime全体をconsistency error状態へ。既存LRUの継続表示も停止 | reloadボタンのみ、繰返しfetchしない |
| hash/bytes不一致またはWeb Crypto不使用可能 | integrity error、候補空 | JSONをparse/useしない。HTTPS secure contextで`crypto.subtle.digest`必須。未対応ならfail closed | reloadで再取得。回避skipなし |
| feed/application期間外または必要serviceDate欠落 | 現行adapterどおり候補を空にし期限/データ不足warning | release/hashが正常ならLRUに保持可だが、期限切れデータを候補表示しない | 「最新データを確認」= full reload。latest manifestにも期間外なら停止表示継続 |
| Deployment更新中・old tab | runtimeがpin済みA manifestのまま。目的地切替はA pathのみ | Aの2駅LRU hitならmemory。missはProduction aliasの`/releases/A/...`。Aはretention期間中に同じaliasへ引継ぎ済み | A pathが失効/404なら候補空、reloadでBへ。A/B fallbackしない |
| A generation削除後にtabがswitch | 404をgeneration expired errorとして表示 | A JSONをcacheへ追加しない。Bのflat/current JSONへ勝手に切替えない | ユーザーがreloadしB manifestへ移る |
| User update/reload button | 一度statusを更新中にし`location.reload()` | 新runtimeでmanifestを`no-cache` revalidate、旧runtime memory LRUは破棄。destination/mode既存localStorageは再利用 | manifest/JSON読み込み通常開始。新release同一なら通常cache再利用可 |

目的地切替、direct-only、路線別/発車順、最早着、始発/終電ルールは、検証済みprepared payloadを渡す既存adapter/selectionへ維持する。変更点はその前段のmanifest pin/hash/release validationとerror gating。異世代/期限外payloadを表示入力にしない。release IDをLRU entryへ保持し、cache keyを`releaseId + stationId`とする。runtimeのpinを変更するのはfull reloadのみである。

## 7. builder・validator・CIの変更単位

| 対象 | Phase 4-8の変更設計 |
|---|---|
| `scripts/public_payload_profile.py` | 既存local→public v1 projection/schemaを維持。新しいrelease envelope validatorはbuilder/independent artifact validator側で別に行い、envelopeをpayload projectionに流さない |
| `scripts/synthetic_public_fixture_factory.py` / `generate_synthetic_public_fixtures.py` | 入力fixture生成は既存の合成データ専用動作を維持。generatedAtをbuild timeに偽装しない。serviceDate anchorとfixture決定性を維持 |
| `scripts/build_public_site.py` | 8 payloadをproject→descriptor/hash→releaseId→schema v1 payload envelope→versioned JSON→manifestの順に生成。versioned `releases/<id>/` treeを作り、retention assemblerが過去generationを引き継げる構成へ |
| `scripts/validate_public_artifact.py` | root固定17-file検査をrecursive allowlistへ変更。manifest schema/8 station exact map、path traversal/外部URL防止、releaseId path/body一致、final JSON SHA256/bytes、共通metadata/serviceDate、retainedRelease complete set/hash/deadline、legacy aliasesの期間・hash、symlink/non-regular/extra file、file count/sizeを確認 |
| `scripts/timetable_adapter.mjs` | envelopeを検証後に渡されるinner `public-display-v1` payloadの既存判定を維持。releaseId比較はloader/envelope boundaryで実施 |
| `scripts/local_preview_payload_loader.mjs` | 公開起動時manifest取得、station URL lookup、raw byte hash、bytes、release ID、station照合。local preview profile loader (`no-store`, local root payload)を壊さないようpublic/local pathを分離 |
| `_local_preview/preview_core.mjs` / `preview_public.js` / `public_index.html` | startup async manifest gate、runtimeContract一致、runtime単位pin、release-aware 2駅LRU、integrity error処理、statusにreload action。public entrypointだけmanifestを使い、local preview/virtual time QAは既存modeを保つ |
| `scripts/serve_synthetic_public_qa.py` | harness builderがmanifest+version pathを提供。scenario変更時に同一 releaseIdを維持できない場合はreloadで新manifestをロード。local HTTPでWeb Cryptoが使えないためQAはinjectable digest verifierでunit/component検証し、実機hashはHTTPS stagingで必ず確認。public production runtimeに検査skip optionを渡さない |
| `.github/workflows/synthetic-public-ci.yml` | build new release→upload run artifact→preliminary validate。approval付きdeploy job内でAccess tokenによりcurrent Production manifest/gensをfetch→期限分をcarry forward→assemble→final independent validate→tree digest→HEAD/project/source release再確認→Direct Upload。旧generation取得失敗はdeploy fail。Artifact 3日保持は同一run限定で継続 |
| tests | profile, builder, artifact validator, adapter, loader, runtime DOM QA, workflow static assertionsを追加。fixture/hash/integrity helpersは共有しない独立validator側で再計算 |

### ファイル数契約

従来はroot 17個（9 shell/runtime + 8 station JSON）を固定比較していた。新通常構成は9 shell/runtime + 1 manifest + 8R generation JSON、移行compatibility中は8 legacy JSONも加算する。Rはmanifest current + `retainUntil > buildTime`のretained releases。manifestに列挙された全generation file setとdisk上recursive file setが完全一致することをvalidatorが検査する。`.synthetic-public-display-v1` markerはfixture input側だけに残し、public siteへ含めない。

### Retention fetchとCI trust boundary

既存`build`/`validate` jobはCloudflare secretを持たない。retention fetchはEnvironment承認後のdeploy job内で行うため、current Production aliasからのremote bytesは承認後にしか取得しない。既存の「validate後に承認」順は維持し、新 generation-only artifactを先に独立validatorへ通す。assemble後のfinal treeもdeploy job内で独立validatorに通す。final tree digestはassemble後に計算・deploy直前に再照合する。これは旧generation入力を含むため必要な追加検証である。

Cloudflare Access service token (`CF-Access-Client-Id`, `CF-Access-Client-Secret`)をGitHub `pages-staging` Environment secretとして新設し、staging Pages Access applicationへそのtokenだけを許可するService Auth policyを追加してretention fetch stepだけに渡す。現在の人間向けAccess login/policyは維持する。Wrangler tokenは既存通りdeploy/API stepだけ。Access token未設定/expired/401/403はretention fetch failureとしてabort。HTTP response body/header/credentialsをraw logへ出さず、allowed status, release ID, file count, byte totalsのみ固定schema logにする。

## 8. rolloutとrollback

1. **4-8a offline schema/builder:** runtime/validator/builder unitを改修し、fixed synthetic serviceDateで決定性・新schema artifactをローカル検証。既存public productionはそのまま。
2. **4-8b synthetic CI artifact:** workflowにmanifest generation・retention assemblerを実装。ただしCloudflareへの自動deployなしでartifact fetch/mock current-site fixturesによるCIを確認。Access bootstrap用のstaging Environment設定を別途行う。
3. **4-8c staging migration:** 承認付きdeployで初回legacy aliasesを保存してmanifest schema v1/runtime contract v2をdeploy。旧Chrome tab/新tab双方、切替、14日retention・削除をsynthetic固定日付でstaging確認。実機ログに旧/新JS hash、manifest/release/hash、200/304/404、Cache-Controlを残す。
4. **4-8d soak:** 少なくとも複数回の連続staging deployでProduction aliasからretained generationsが実際に回収・再配置されること、Access token rotation/failureがfail closedであることを確認。いきなりODPT実データは使わない。
5. **Production eligibility review:** ODPT payload profile/許諾、更新周期、retentionと実データ有効期間、cache policy、運用責任、staging結果を別review。Phase 4-8自体はsynthetic only。

通常のロールバックはCloudflare Pages Deploymentsから成功済みProduction deploymentへrollbackする。Cloudflare docsでは成功済みProduction deploymentをrollback対象にでき、Production deploymentを切り替えると説明している。`[Pages Rollbacks](https://developers.cloudflare.com/pages/configuration/rollbacks/)`。rollback先artifactにはその時点のmanifestとgeneration filesが一緒に存在するため内部整合する。rollback後のcurrent aliasに存在しない新releaseへ既にpinしているtabは、新JSONを取れずfail closedしてreloadを案内する。Pages rollbackを旧世代pathの保持機能と混同しない。次回Direct Uploadでは改めて現在aliasのmanifestに列挙された期限内generationを全て取り込み、欠ける場合は中止。

既存workflowのGitHub Artifact 3日保存はrun中のvalidated artifact搬送にのみ使う。rollbackを3日経過後も再現するための元データとして依存しない。Pagesの成功deployment rollbackをUI regressionに使い、データreleaseだけ戻す運用は現在のmanifestを過去generationへ向ける別workflowの仕様化後に限る。

## 9. テスト計画

| Case | 自動化/実機 | 合格条件 |
|---|---|---|
| 同一releaseIdの正常build/load、同一入力の再build | 自動 (builder, loader) | ID, URL, payload bytes, hashes同一。8駅表示成功 |
| JSON releaseIdがmanifestと違う | 自動 | fail closed、LRUへ入らない、カード0件 |
| JSON raw-byte hash/byte count違い、JSON改ざん/UTF-8不正 | 自動 (Node/browser mock) | hash/parse error、payload利用なし |
| manifest内のstation欠損/duplicate/external URL/`..` path/wrong ID | 自動 (validator/runtime) | build/validator拒否またはruntime fail closed |
| 異なるserviceDate/feed/applicationPeriodのstation群 | 自動 | validator拒否 |
| 旧tab A manifest pinned後、deploy切替、未cache駅へ移動 | 自動2-root/deployment simulation + staging実機 | A pathへfetchするかexpired 404でfail。B flat root JSONへ誤fallbackしない |
| 2駅LRU内の世代混在 | 自動 | LRU entry releaseId一致必須。release change時は全entry clear。A cacheとB JSONを同一sessionへ入れない |
| deploy切替前後のmanifest 200/304/ETag | 自動mock + staging network実機 | 304はcache本文と同じmanifest hashとして扱い、B 200時は新runtimeでB pin。各stationはmanifest URL/hash一致 |
| old release retained + alias deployment succession | 自動retention assembler + staging複数回deploy | Production aliasからold files fetchし、新deployment pathに同じbytes/hashで存在 |
| retainUntil経過、old generation削除、stale tab switch | 自動 + staging | 404でfail closed、明示reloadでcurrent releaseへ復帰 |
| current manifest/Access fetch失敗、403、欠落old file、hash mismatch | 自動workflow fixtures + staging fault simulation | uploadを行わずfail closed。秘密・本文をlogに出さない |
| feed/application期間外、service day欠損 | 自動 adapter/runtime | 既存同等のwarning/empty board、始発/終電/最早着を判定しない |
| User reload action | 自動DOM test + staging | reloadが1回発火、古いcacheを使い回さずmanifest再検証、選択目的地は既存storageから復元 |
| iPhone Safari deployment切替/ETag/cache/目的地操作 | 実機必須 | 旧/新manifest behavior、A/B switch、直通filter、表示mode、最早着、始発/終電、reload復旧を確認 |

HTTP browser cacheの200/304交渉、iOS SafariのWeb Crypto/Cache API、実際のAccess/Pages cacheはfake fetchだけでは確証できないため、最後のstaging/iPhone確認を必須とする。

## 10. 未決事項・推奨判断

1. **Access service token:** Pages staging Accessが保護されているため、Production alias retention fetchにはservice tokenが要る。低運用案は`pages-staging` Environmentに専用tokenを置き、短いjob scope、期限/rotation calendarを設定する。Service tokenの発行・policy確認は別運用作業。未設定なら旧世代を安全に継承できずdeploy不可。
2. **Retention 7〜14日:** 推奨初期値。Pages上限よりbytes/再upload量/ODPT retention条件が支配的。基準artifact bytesの計測後、14dを維持可能か判断。長期放置tabの永続サポートはしない。
3. **runtime contract string:** `dotchi-public-runtime-v2`を固定する。HTML DOM contract、module API、manifest/payload compatibilityがbreaking change時に上げる。
4. **JSON envelope schema v1:** releaseIdはouter envelopeで追加し、inner `public-display-v1` schemaVersion 1は維持。legacy root aliasesも既存のflat schema v1を14日だけ保持する。
5. **`generatedAt`意味:** synthetic現行値は期間先頭日の決定timestampを維持。ODPT生成器は実際のgeneration timestampを持たせ、freshness thresholdをserviceDate/feed validityと別に設ける案を採用する。固定日時テストではgeneration instantを注入して決定性を保つ。
6. **正式導入対象:** staging syntheticでretention/Access/rollback検証後、ODPT実データを載せる変更は別Phase/approval。ODPT raw inputをID descriptor/public artifactへ誤投入しないsource boundary testを追加する。
7. **hash/runtime support:** production HTTPSではWeb Crypto `crypto.subtle`を必須。local QAがplain HTTP/private LANでdigestできない場合はtest-only injected verifierでunit testし、実データ検査はHTTPS stagingで行う。productionにskip flagは設けない。
8. **file budget:** Pages 20,000-file Free cap/25 MiB individual capを確認済み。日次以下の更新なら推定R≤15/138 files、より高頻度なら実数を毎回算出する。最大file・総artifact byte thresholdはPhase 4-8前にbaseline measureして固定し、budget超過はdeploy stop。

## 11. Phase 4-8の初期staging分割（§13で拡張）

以下はrelease整合性のsynthetic staging導入順を示した初期案。日次本番運用方針を反映した正式なPhase 4-8分割・作業順は§13を参照する。

- **4-8A — schema/hash contract:** release envelope (inner payload schema v1維持)、manifest schema、runtime contract、release descriptor/canonicalization、fixture updates、test vectorsを決める。
- **4-8B — deterministic builder/validator:** versioned tree、manifest、hashes、recursive allowlist、retention listを生成・検査。old site mock fixtureに対しcarry-forward toolを先行実装。
- **4-8C — runtime pin and UX:** startup manifest gate、compatibility check、SHA-256 verify、release-aware LRU、fail-closed/retry/reload CTA。local preview pathを隔離。
- **4-8D — CI retention assembly:** approved deploy jobでAccess service tokenによるcurrent Production alias fetch、expiry prune、hash verification、new release assembly、final independent validation/tree digest。欠損/unauthorized/oversizeはabort。
- **4-8E — synthetic staging migration:** first v1 compatibility copy、連続deployment retention、rollback/old-path expiry、ETag/304検証。ChromeとiPhone SafariのNetwork/画面確認。
- **Production eligibility review:** 実データ入力、更新周期・期限・利用条件、token/retention、監視/停止手順の確認後に別途着手。

## 12. 本番データ更新とアプリ公開の運用設計

### 12.1 workflowの責務

| 経路 | 目的・起動 | 入力と公開範囲 | 承認 |
|---|---|---|---|
| `Synthetic public site CI` | 現行どおり`workflow_dispatch`のみ。synthetic fixtureでstagingのbuilder・validator・承認付きdeployを検証 | ODPTを読まず、本番データを生成・公開しない | staging Environmentの既存承認を維持 |
| 将来の本番日次data workflow | 原則1日1回、ODPT確認・変換・比較・検証。手動dispatchを復旧用に残す | source取得、data artifact作成、既承認runtimeとの組み立て。UI/JS/CSS/契約をmainから無審査で取り込まない | 条件を満たすdata-only更新は自動公開を目標 |
| app release workflow | UI/JS/CSS、schema、builder/runtime契約、workflow/権限等の変更をテストし本番公開 | 承認済みコードと、currentまたは新規に検証された互換data releaseを一体化 | PR reviewとproduction Environmentの手動承認 |
| emergency workflow_dispatch | データ障害復旧または緊急app修正 | 選択releaseと対象を明示。通常の検証・整合性gate・直列化は省略しない | 実行者による明示起動。app/権限変更はproduction approvalを維持 |

本番data workflowが参照するbuilder/runtimeは、承認済みapp releaseのcommitまたは明示的に固定したtoolchainから供給する。data-only更新でsource branch先端の未承認HTML/JS/CSS/contractを混ぜない。Cloudflare credentialは最終deploy jobだけ、ODPT credentialは取得jobだけに限定する構成を推奨する。data artifactはjob境界でimmutable digestを渡し、deploy前後で同一性を検証する。

### 12.2 自動公開を許す条件と更新検出

毎日の確認自体はデプロイではない。`checkedAt`/`lastSuccessfulCheckAt`（運用状態）とsource側更新時刻/versionを記録し、次をすべて満たす時だけ公開候補を作る。

1. API response、認証、source schema、対象8駅、対象serviceDate、ライセンス/利用条件上の範囲が正常。
2. canonical public payload digestまたはsource-authoritative `feed.version` が現行と異なる、**または**有効期間延長が必要で、ODPT source metadataと承認済みextension ruleの双方が延長後範囲を裏付ける。
3. public profile、station/date/feed整合性、releaseId、manifest、最終JSON hash/bytes、保持世代の取得・検証、file/size budgetがすべて成功。
4. app asset/schema/runtime contractが現行の承認済みreleaseと一致し、data-only自動経路にコード差分がない。
5. Production aliasの最新releaseをdeploy直前に再取得し、組み立てたcurrent parentがまだ同一と確認できる。

payload/authoritative metadata/有効期間に変更がなく、公開データが引き続き有効ならno-opとし、manifestや`publishedAt`を更新しない。`releaseId`はbundle内容から決定的に計算し、日付やrun IDだけを理由に世代を増やさない。単に将来日付を足す、sourceが裏付けない期間を延長する、古い値を新鮮なデータとして再公開することは禁止する。更新期限が近くても有効な延長根拠が得られなければ公開を止め、運用通知とruntime期限表示へ移る。

ODPTの基本利用指針は静的データまたは静的データ由来コンテンツを定期更新し、個別条件がない場合も更新通知後1週間以内に更新するよう求める。日次確認はそれより短い検知間隔を目指す設計だが、対象データの個別条件・API仕様・更新通知経路は本番前に確認する。実行JST時刻は更新タイミングを確認して決定し、毎時ちょうどを避ける。GitHub scheduleはUTC基準を既定とし、高負荷で遅延・欠落し得るため、時刻ぴったりの実行保証とは扱わない。scheduleがdefault branch上で動くこと、公開repositoryの60日活動なしで自動無効化され得ること、通知先がschedule定義を最後に編集した人に依存する点も監視手順に含める。

### 12.3 失敗、再試行、期限警告、通知

| 事象 | 推奨動作 | 公開状態 |
|---|---|---|
| timeout/network/429/5xx等の一時障害 | 同一run内で最大3回程度、指数backoff+jitter。`Retry-After`があれば尊重。上限後に終了し、可能なら30〜60分後の単一再試行を運用する | deploy jobへ進めない。現Productionを保持 |
| auth/secret/不正schema/駅欠損/期間矛盾/hash失敗/旧世代欠損/size超過 | 原因修正まで自動再試行しない。固定schemaのsummaryに分類・release・run URLを記録し通知 | deploy jobへ進めない。既存正常deploymentを保持 |
| production Direct Upload失敗 | deployment結果を確認し、自動で別内容を重ねて再deployしない。現行aliasとdeploymentを確認してから再実行 | Pagesが維持する直近正常Productionを使用。成功を確認できない場合は停止扱い |
| scheduled run未起動/Actions停止 | 後述のheartbeat期限超過を警告。手動dispatchの復旧手順を維持 | 既存公開物を保持するが、有効期限を過ぎたダイヤはruntimeで表示しない |

推奨警告閾値は、effective validity endまで72時間でwarning、24時間でcritical、期限到達でexpired/high。日次処理の遅延や一度の失敗を吸収する候補値であり、ODPT更新頻度と許容停止時間を確認して本番前に確定する。ここでeffective validity endは設計書§5の`applicationPeriod.endsAt`と`feed.validThrough`翌日00:00 JSTの早い方。運用側は最終成功確認時刻と期限までの残り時間を評価し、通常・warning・critical・expiredの通知を出す。runtimeも公開metadataから残り時間を算出し、推奨初期案として72時間以内に更新確認が成功していない場合は控えめな「データ更新を確認中」表示、期限切れ後は候補を出さず「最新の時刻表を確認できません」とする。期限切れpayloadを正常候補として案内しない。

低固定費の初期通知はGitHub Actionsのfailed workflow email/web notificationとrun summaryを使う。ただしユーザー通知設定に依存し、通知はworkflow run完了を起点とするため、schedule自体が起動しない事象は通知されない。成功runではheartbeatを更新し、次回runが前回成功から36時間超過を検知した場合にwarning/failureを発生させる案を推奨する。これもActions全体停止中は動かない。独立監視SaaS/外部通知は無償・運用条件を確認してから追加判断し、当初は導入しない案を推奨する。Actions通知の受信者、通知先設定、heartbeatの保存先と書込み権限は本番前の未決事項。

GitHub scheduleは遅延・欠落する場合があるため、1回の実行失敗に対して同一run内の有限retry後は一回だけ遅延retryを推奨し、無限retryをしない。schedule trigger自体の欠落は36時間heartbeatと期限アラートで発見する。手動dispatchは復旧策であり、自動公開の安全gateや期限検査を回避できない。

### 12.4 自動・手動publishの競合回避

Productionを変更する全workflowで共有の同一concurrency groupを使い、`cancel-in-progress: false`とする。GitHub Actions concurrencyの既定では同一groupのpendingは1件で、新しいrunがpending runを置換して取消すため、データ更新と手動app更新を別々の競合workflowにするだけではlossless queueにならない。対応するGitHub plan/runtimeで`queue: max`を利用できるか確認し、利用可能なら少数のpendingを順序待ちさせる。利用できない場合は、唯一のproduction publish coordinatorへ要求を集約し、待ちrunの置換を許容する代わりに、各runが最新Productionを読み直して不足したdata/app変更を再計算する。いずれもdeploy直前にcurrent manifest/release/deploymentを再取得・比較し、親世代が変わっていたらassemble結果を破棄して最新世代から再組立する。

推奨は同一Production Environmentと共通lockを使う単一publish coordinator。data check/build jobと手動承認付きapp requestは独立させつつ、実deployをcoordinatorへ集約する。run id順だけに正しさを依存せず、deploy直前のcompare-and-abortが必須。敗北した/取消されたdata runは成功扱いにせず、次の日次checkまたは手動dispatchで再評価する。workflowのconcurrency queue機能はアカウント/利用可能機能を確認後に決定する。

### 12.5 旧世代保持と日次更新

§5の保持式をそのまま適用し、日々のno-opはgenerationを作らずretention時計を進めない。変更・有効期間延長で実際に新releaseがcurrentになる都度、旧releaseをcurrent Production aliasから取得し、新Direct Upload treeへ再配置する。旧Deployment固有URLが残ることをProduction aliasでの旧path取得の代替としない。対象はmanifest列挙済みで`retainUntil > buildTime`のgenerationだけ。期限切れgenerationと14日移行期間終了後のlegacy flat aliasesは次のartifactから削除可能。

旧世代の取得元はdeploy直前のProduction alias。GitHub run artifactは同一run内の受け渡しに限り、3日保存artifactを将来のretention sourceにしない。Deploy jobはmanifest・各file hash/bytes・release metadata・期限・全file setを検証してからcarry forwardする。1つでも欠ける/読めない/壊れている、Access認証不可、最終treeがbudget超過なら新uploadを行わない。Pages Direct Uploadが旧treeを自動で引き継ぐとは仮定しない。

### 12.6 自動承認・手動承認境界

**data-only自動公開を許す範囲:** source取得と既承認変換契約に沿ったpayload更新、manifest/release envelope生成、hash/期間/駅/保持検証、Production data-only publish。成功条件は§12.2を全て満たすこと。人手確認なしを目標とするが、権限・署名・環境保護ルールの最終形は本番前に確認する。

**production手動承認を維持する変更:** UI/HTML/JS/CSS、public schema/envelope/manifest契約、builder/validator semantics、runtime判定・キャッシュ・期限ルール、GitHub Action実装/major version/pin/permissions、Cloudflare Access/Pages設定、secret/Environment policy、retention/budget/通知方針。PR test/reviewの後、app releaseとしてproduction Environment承認を要求する。自動data runが同じタイミングでこれらの差分を検出した場合はdata-only pathを中止し、承認済みapp releaseと互換dataで手動公開する。

コードとデータが同時に変わる場合は、app承認済みbundleを基準に新しいdataを再生成/再検証し、一つのreleaseId/manifestで同じDeploymentに公開する。データだけを先行公開して新clientとの互換を賭けない。緊急手動dispatchもrelease/hash/retention/expiry gateを必須とする。

### 12.7 固定費・利用条件の本番前checklist

- GitHub repository visibility/plan、Actions minutes/storage実績、Artifact保持量、schedule利用可否、queue/concurrency対応、Environment reviewer数と通知受信先。
- Cloudflare Pagesの現在のfile count/単体・upload上限、Direct Upload所要時間・総bytes、Production aliasからの旧世代回収、Access service-token権限/rotationとrollback。
- ODPT対象datasetの利用条件、API request/attribution/freshness要件、更新通知経路、rate limit/maintenance、対象service期間と有効期限の意味。
- 利用状況を計測して上限を確定し、超過時はpublish stopにする。特定planのquotaを現時点で固定値として設計に埋め込まない。追加の有料SaaSを必須依存にしない。

日次workflowはraw ODPT dataを外部artifact/logへ保存しない。必要な入力保存期間・再実行性を別途判断する。Actions scheduleの遅延、miss、60日inactive disable、およびfailure notification仕様は[GitHub schedule events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)、[workflow troubleshooting](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)、[Actions notifications](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs)、[concurrency control](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)を確認した。GitHub料金とquotaはrepository plan/visibilityで異なるため、[included usage](https://docs.github.com/en/billing/reference/product-usage-included)を本番アカウントで確認する。ODPTの静的データ更新に関する根拠は[基本利用指針](https://developer.odpt.org/terms/data_basic_use_guideline.html)。資料確認日: 2026-10-28。

## 13. Phase 4-8実装分割への反映

- **4-8A — contract (implemented):** `scripts/release_contract.py` / `.mjs` でJCS、release descriptor/ID、manifest、envelope、raw bytes/hash契約を実装し、Python/Node専用testを追加済み。旧世代retain/legacy migrationの組立・CI運用は4-8B以降。
- **4-8B — builder/validator:** generation tree、manifest、hash、保持世代検証。daily no-opと内容変更/authoritative validity extensionのfixtureを用意。
- **4-8C — runtime:** session pin、generation-aware 2駅LRU、fail closed、期限前/期限後UI、更新操作。
- **4-8D — synthetic staging:** 現workflowは手動synthetic専用として維持。複数回Direct Upload、旧世代carry-forward、ETag/304、切替、Safari実機を検証。
- **4-8E — production data workflow in shadow mode:** ODPT API/利用条件審査後、schedule/手動起動でfetch・diff・validationを実施するがdeployせず、no-op/更新判定・retry・heartbeat・通知・size budgetを確認。実ODPT接続の許可は別途必要。
- **4-8F — production publishing coordinator:** 共通lock、current deployment再読込、data/app要求の競合、data-only権限分離、Environment gate、旧世代保持をsynthetic/mockで検証。app code変更は承認必須。
- **4-8G — controlled production activation:** GitHub/Cloudflare/ODPT plan/terms・schedule時刻・通知・期限SLA・staging evidenceをreviewし、明示承認後にdata-only自動公開を有効化。段階的に監視期間を置き、即時停止とPages deployment rollbackを手順化。

Phase 4-8の着手前に決めるのは、ODPT source/freshness詳細、実行時刻、72h/24h警告値、36h heartbeat、retry回数/間隔、Actions concurrency queue可否、通知責任者/受信先、GitHub/Pages利用枠、data workflowのtoken scopeである。これらは推奨初期値を示しただけで、未承認の本番設定を確定したものではない。

## 14. Phase 4-8A 契約module実装メモ（2026-10-28）

今回の実装対象は純粋な契約APIであり、existing builder/independent validator/runtime/fixture/workflowには接続しない。既存17-file public artifact、inner `public-display-v1` payload、staging workflowを維持したまま、次段builderが使うAPIを先行実装した。

### APIと生成順

| API | 用途 |
|---|---|
| Python `canonicalize_jcs(value) -> bytes`; JS `canonicalizeJcs(value) -> Buffer` | RFC 8785 canonical UTF-8 JSON bytes |
| `build_release_descriptor(runtime_contract, builder_contract_version, payloads, assets)` / JS object-form equivalent | schema/compatibility IDs、asset path+raw-byte SHA-256、8駅inner payload canonical SHA-256をまとめる。assetsはHTML/CSS/JSを含める |
| `calculate_release_id(descriptor)` / `calculateReleaseId(descriptor)` | canonical descriptorから`r1-<64 lowercase hex>`生成 |
| `create_envelope(...)`, `encode_envelope(...)` / `createEnvelope`, `encodeEnvelope` | existing payload validatorを通したinner payloadをenvelopeへ包み、canonical bytesを出す |
| `create_manifest(...)` / `createManifest(...)` | 最終envelope bytesからstation URL/hash/byte数を作成し、strict validation後に返す |
| `validate_manifest(value)` / `validateManifest(value)` | manifest fields、compatibility、station集合、URL、hash、length、date/feed/period、retained release、legacy compatibilityを検査 |
| `verify_envelope_bytes(raw, ...)` / `verifyEnvelopeBytes` | 生bytesの長さ→SHA-256→UTF-8/重複keyを含むJSON構造→envelope/payload検証。安定error `code`を付ける |
| `verify_station_bytes(raw, manifest, station_id)` / `verifyStationBytes` | manifest記載hash/bytesとの照合に加え、release/station/common metadata/serviceDate範囲を確認 |

生成順: (1) 8 payloadを現行public validatorで検証、(2) HTML/CSS/JS raw bytesを集める、(3) inner payload JCS hashとasset SHA-256でdescriptorを組む、(4) `releaseId`を計算、(5) envelopeを作成しcanonical UTF-8 bytes/hash/lengthを得る、(6) 最終envelope bytesからmanifestを作る、(7) independent artifact validatorがtree全体を検査する。envelope注入後のJSON hashをdescriptorへ入れないためreleaseId自己参照を作らない。`publishedAt`/Actions run IDもdescriptorに含めない。

JCS implementationは両言語で依存packageを追加せず実装。JavaScriptはECMAScript number renderingとUTF-16 key sort、Pythonはfloat shortest representationをJCSのdecimal/exponent thresholdsへ整形し、keyをUTF-16BE code unit順にsortする。非finite数、lone surrogate、JSON外型、Python integerのsafe IEEE-754範囲外は拒否する。配列順はJSON意味の一部として保持し、descriptorのassets/stationsは生成APIでID/path順に整列する。契約errorには`code`を持たせる。

manifest/envelope unknown fieldはfail closed。manifest URLは`/releases/<releaseId>/<所定駅filename>`だけを許し、外部origin、query/fragment、percent encoding、backslash、dot segment、重複URLを拒否する。station envelopeは`schemaVersion`, `releaseId`, `stationId`, `payloadSchemaVersion`, `dataScope`, `payload`を固定しinner schema v1は変更しない。legacy flat aliasesは明示的な`legacyCompatibilityV1` schemaとして期限・source digest・8 root URL/hash/bytesを検証する。

JavaScript moduleは現在Node.js `node:crypto`を使う契約/test helperで、browser runtimeから直接importする実装ではない。Phase 4-8Cで使う場合は同じbytes/order semanticsを保ちつつWeb Crypto async SHA-256へ接続する。Python/JS JCS・descriptor/releaseId parityはtestで照合済み。payload validatorの意味差（Python profile validatorはallowlist projection比較、JS adapter validatorはruntime向け検証）を独立artifact validatorで再照合する作業は4-8Bで残る。

4-8B完了時点ではruntime/2駅LRU・Web Crypto接続・pinning/UXは未実装だった。Phase 4-8Cでbrowser runtimeとlocal synthetic QAを追加済み。manifest retained listのProduction aliasからの取得・carry-forward/prune、旧世代bytes引継ぎ、staging deployment切替は未実装で、後続Phaseに残る。legacy builder既定とvalidator mode、fixture contract、GitHub workflowは維持する。

## 15. Phase 4-8B builder・独立validator統合（2026-10-28）

### 15.1 opt-in builderとファイル形式

既定の`build_public_site.py`呼出はこれまでどおりflat v1 payloadの17-file artifactを作る。新形式は明示的な`--release-managed`のみで有効にする。

```sh
python3 scripts/generate_synthetic_public_fixtures.py --service-date 2026-10-27 --output /private/tmp/t12-fixtures
python3 scripts/build_public_site.py --fixtures /private/tmp/t12-fixtures --output /private/tmp/t12-release-site --release-managed
python3 scripts/validate_public_artifact.py --release-managed /private/tmp/t12-release-site
```

新artifactは9 static shell/runtime asset + root `manifest.json` + `releases/<releaseId>/`下の8 envelope JSON = **18 files**。root flat station JSONは置かず、retained release/legacy aliasもローカルbuilderでは作らない。`manifest.publishedAt`は未公開を表す`null`で固定し、production publish assemblyが初回publish timestampを入れる想定。日時はreleaseId preimageに含まれず、same inputsからのlocal treeはbyte-identical。

Static asset bytesを確定後、既存public profile validatorを通した8 payloadと全static asset path/hashからdescriptorを作る。`releaseId`を計算してJCS envelope bytesを出し、hash/byte countをManifestへ入れる。manifestには`releaseDescriptor`も保存する。これによりindependent validatorはactual static asset hashes・inner payload canonical hashes・schema/contract fieldsからcurrent `releaseId`を再計算できる。descriptorはreleaseIdを入れず、envelope final JSON bytes hashも含めないので循環参照はない。manifest自身のdigestは含めない。

### 15.2 independent validationと既存payload境界

`validate_public_artifact.py`の従来CLI `python3 scripts/validate_public_artifact.py ARTIFACT_DIR`は従来のflat 17-file exact allowlistと検査を維持する。新形式だけ`--release-managed`を追加する。新modeはbuilderをimport/callせず、artifactのrecursive path set、symlink/nonregular entry、static assets、root manifest、current/retained generation dirs、optional legacy aliasesを読取専用で検証する。未知file/path、欠損、URL traversal/external origin、hash・bytes・JSON・station/release不一致は拒否。

Current manifest descriptorからreleaseIdを再計算し、全static asset SHA-256と8 inner payload canonical SHA-256を再照合する。JSONは重複key・UTF-8・構造を確認し、raw bytes length/hash→envelope contract→Python strict public allowlist/schema→既存JavaScript adapter validationをそれぞれ実施する。全駅でserviceDate list、feed、generatedAt、applicationPeriod、station ownershipを照合する。これによりPhase 4-8Aで見えたvalidator差を、Pythonのallowlist検証を弱めず、JS adapter検証も併用する境界にした。inner `public-display-v1` schema v1は変更しない。

manifest schemaへ`releaseDescriptor`を追加したのは、artifact上で可能な限りreleaseIdを独立再計算するための4-8B設計判断。既存stagingはmanifestを配信しておらず、builder defaultと旧artifactはこのmodeに入らない。releaseDescriptorなしの4-8A単体manifestは契約module testで引き続き許すが、新mode validatorはdescriptor必須。descriptorのschema fieldは既存v1/contractへ固定する。

### 15.3 再現性、retention範囲、runtime引継ぎ

固定synthetic dates・fixture・static bytes・builder contractではmanifestに`publishedAt: null`を含め、releaseId、manifest bytes、8 envelope bytes、全18-file treeが再生成で一致する。payload 1駅、asset bytes、builder contractの変更でreleaseIdが変わる。current releaseのIDはartifactにdescriptorがあるため再計算可能。Phase 4-8D-1でretained release entryにも元の`releaseDescriptor`を持たせ、独立validatorはID preimageと旧payload canonical hashを再検証する。旧世代のshared HTML/CSS/JS bytes自体は保持対象に含まれないため、descriptorに記録された過去asset hashを旧asset fileと照合できない。旧currentをretireするときは入力artifactの独立validatorでasset hashを確認してからdescriptorをretained化する。

このartifactはbuilderの`--release-managed` opt-inでのみrelease runtimeを起動し、既定の17-file buildはflat modeを維持する。Phase 4-8Cでmanifest pinning、raw-byte Web Crypto検証、release-aware 2駅LRU、fail-closedと手動更新UXを実装した。4-8D-1はローカルassemblyを追加するが、Production alias取得と実デプロイは行わない。

### 15.4 Phase 4-8C browser runtime

Public shellは`<meta name="dotchi-data-mode">`を持つ。sourceとdefault buildは`legacy`、release-managed builderはdescriptor hash確定前に値を`release-managed`へ変更する。`preview_public.js`はmeta未設定時legacyを維持し、`legacy`/`release-managed`以外を拒否する。query parameterでruntime modeは切り替えない。release mode起動失敗時にflat JSONへfallbackしない。

Browser-safe release loaderは既存public assetの`scripts/local_preview_payload_loader.mjs`内に実装し、Node専用`release_contract.mjs`/`node:crypto`をimportしない。起動時に`/manifest.json`を`cache: "no-cache"`で一度取得し、厳密なfield set、schema/runtime/data scope、descriptor形状とJCS SHA-256からのreleaseId再計算、8駅、固定URL、SHA-256/bytes、serviceDate/feed/application periodを検証する。各駅切替ではmanifestを再取得せず、pin済みstation URLからraw `ArrayBuffer`を受け取る。Web Crypto SHA-256とbyte lengthをJSON decode/parseより先に照合し、strict UTF-8、envelope schema・releaseId・stationId、payload metadataを確かめた後、既存`prepareTimetablePayload(..., PUBLIC_DATA_SCOPE)`へinner payloadだけを渡す。Web Cryptoがない、HTTP error/404、破損、互換性不一致等はfail closed。

`preview_core.mjs`は既存2件上限LRUを使い、内部cache keyをpin済み`releaseId + stationId`にする。同駅への同時fetchはsession内single-flight promiseを共有する。既存latest-request sequenceで古い目的地の遅着結果を破棄する。loader/integrityエラーはboardを空にして既存の「列車なし」「終電終了」と異なるerror statusへ出し、原因codeをconsoleとoptional hookへ記録する。release-managed error時だけ手動「更新する」buttonを追加し、押下でsessionStorageへ一回の更新試行を記録してfull reloadする。そのreload後も失敗した場合はbuttonを再表示せず「時間をおいて再度アクセス」と案内する。自動retryやreload loopは作らない。成功したstation payload取得時に更新試行markerを消す。適合期間外は既存adapter validity判定により列車を表示しない。

Manifestは`no-cache`再検証を指定する。通常のFetch cacheは304再検証済み本文を200相当representationとして返す場合があり、raw 304/non-successを本文なしで受けた場合はfail closed。generation URLはpin済み世代を指し、normal cacheを利用しつつ毎回hash/bytesを検証する。Cloudflare Pagesの実ETag/304/cache header挙動は実deployment未実施のため未検証。releaseId/hashは配信内容の誤り・混在・破損検出であり、署名や配信元の真正性証明ではない。

Synthetic local QA: `python3 -B scripts/serve_synthetic_public_qa.py --prepare-only --release-managed --output /private/tmp/dotchi-release-qa`。2世代の18-file artifactsを別々にbuild/validateし、QA shell、scenario picker、fixed clockはartifact外に置く。legacy QAは引き続き17 files。追加Node/DOMテストはpinした旧sessionと新session、manifest/JSON 404、Web Crypto不在、byte/hash/station mismatch、LRU eviction、fail-closed board/error/reload CTAを検査する。Chrome実機のdeployment切替・Network/ETag・実機画面、およびiPhone Safariは未確認。

4-8DではChrome/iPhone Safariでlegacyとrelease-managed双方の目的地・直通filter・表示順・最早着・始発/終電・countdown・縦画面を回帰確認し、更新button、old tab、HTTP cache/304を実測する。4-8Eの連続staging deployment/retention/rollback確認が完了するまでProduction切替しない。staging workflowは変更しておらずlegacyを既定に保つ。

## 17. Phase 4-8C QAシナリオ改善（2026-10-28）

`scripts/serve_synthetic_public_qa.py` は既存 `cards` 固定時刻scenarioを維持し、目的地差分を見分ける `destination-switch` と実時間で進む `clock-running` を追加した。前者は8駅のQA専用payloadを生成し、駅順に2分ずつ到着時刻を遅らせる。発車時刻・駅ID・station ownership・service dateは維持し、到着は発車後になる。payloadはrelease-managed builder/validatorを通過するが、本番fixture generatorやCI入力は変更しない。運行上の正確性を表すものではなく、UIの切替検出用synthetic値である。

時計providerは `scripts/synthetic_public_qa_clock.mjs` に分離し、QA shell生成時にharness直下へコピーする。`fixed` は開始時刻を返し続け、`advancing` は `performance.now()` の単調経過時間を開始時刻へ加算する。moduleとscenario UIは検証済みartifactの外にあり、production runtime/APIにQA専用分岐を加えていない。

DOM QAはrelease-managed 18-file artifactsに対してmanifestを1回取得すること、目的地ごとにmanifestの世代別URLと一致するstation JSONをfetchすること、station identityとカード到着時刻が目的地に応じて変わることを検証する。2駅LRU hit/eviction、遅れて到着した旧station responseの破棄、固定時計での不進行・進行時計でのclock/countdown更新、legacy modeも追加確認する。LAN IPv4 bindは従来どおり必須。任意 `--localhost-port` は追加の `127.0.0.1` listenerだけを開き、Mac Chromeでrelease-mode Web Cryptoを利用するためのもの。iPhoneなどLAN HTTPでのWeb Crypto検証は対象外。

## 18. Phase 4-8C QA改善での検証範囲

DOM QAはNode内のDOM harnessとsynthetic release artifactsを使用する。対象DOM QA 9件、Node全体129件、Python全体108件が成功した。Mac Chrome実機での目視は別途README手順に従う。destination-switch到着差は表示切替の識別標識であり、路線の実旅行時間として解釈しない。公開17-file legacy artifact、新形式18-file contract、runtime、workflowは本変更対象外。

## 19. Phase 4-8D-1 ローカルretention assembly

### 19.1 入力・出力と実行

`scripts/assemble_public_release.py` はbuilderから独立したローカル工程。`--previous` は独立validatorを通るrelease-managed full artifact、または既存17-file legacy artifactを受け取る。`--new-release` は既存opt-in builderが作るcleanな18-file generation-only artifact（retained/legacyなし）を受け取る。明示的timezone付きJST/UTC instantを`--as-of`で指定し、既存でない`--output`へatomic assemblyする。

```sh
python3 -B scripts/generate_synthetic_public_fixtures.py --service-date 2026-10-28 --output /private/tmp/t12-new-fixtures
python3 -B scripts/build_public_site.py --fixtures /private/tmp/t12-new-fixtures --output /private/tmp/t12-new-release --release-managed
python3 -B scripts/assemble_public_release.py --previous /private/tmp/t12-old-production-artifact --new-release /private/tmp/t12-new-release --as-of 2026-10-28T12:00:00+09:00 --output /private/tmp/t12-assembled
python3 -B scripts/validate_public_artifact.py --release-managed /private/tmp/t12-assembled
```

旧current/retained generationの8 filesだけを同じbytesで引き継ぎ、旧runtime aliasが有効な間はflat root JSONも元bytesで複製する。新static shell/assetsはnew release artifactから採る。出力は`18 + 8R + 8L` files（R=current以外のretained count、L=legacy alias groupが有効なら1）で、directory自体はcountしない。default budgetは20,000 files、single file 25 MiB、whole tree 256 MiB。上限はCLIでさらに下げられる。サイズ/countは完成tree上で計測し、超過ならstage全体を削除して出力先を作らない。

入力はcopy前に旧/newそれぞれのindependent validatorで完全検証する。出力先は既存pathを拒否し、親dirは事前存在・symlinkなしを要求する。stageは同一parentのtemporary directoryへ作成し、manifest/file set/independent validator/budgetが成功した後にdirectory renameする。JSON bytesを再serializeしない。JSON欠損、unexpected file、symlink/non-regular path、path traversal、station/hash/byte mismatch、descriptor不一致、失敗途中の出力はfail closed。

ローカルsynthetic A→Bの実測は26 files、292,178 total bytes、largest file 45,180 bytes。A/B→Cはtestで34 files。どちらもdefault 20,000-file / 25-MiB-single-file / 256-MiB-tree ceilings内。legacy初回移行も26 files（current 18 + flat alias 8）で、8 aliasはsource bytes一致。

### 19.2 保持期限、同一release、legacy初回移行

instantはUTCへ正規化して比較する。releaseの`effectiveValidityEnd`は`applicationPeriod.endsAt`と、feedのinclusive `validThrough`翌日00:00 JSTの早い方。`retiredAt`はcurrentからretainedへ移るassembly時刻。要求期限を`max(retiredAt + 7 days, effectiveValidityEnd + 48 hours)`とし、要求期限が`retiredAt + 14 days`を超えたらassemblyを中止する。超えない場合、その要求期限を`retainUntil`へ記録する。これで有効データ+48時間を14日以内に保持できない場合に削除しない。retained fileは`asOf < retainUntil + 24 hours`なら引き継ぐ。これは削除操作だけに適用する安全marginで、manifest上のretainUntilを変更しない。

同じreleaseIdを再投入するとcurrentの`publishedAt`を維持し、同IDをretainedへ重複追加しない。旧retained releaseへrollbackすると、そのIDをcurrentから外し、直前currentへ新しい`retiredAt`を開始する。local builder由来でprevious currentの`publishedAt`がnullならlocal modelの初回観測時刻として`asOf`を入れる。本番sourceのpublishedAt/null扱いはD-2接続前にreject-or-normalize policyを確定する。

初回legacy migrationでは17-file validatorを通したflat v1 JSON 8 filesをbyte-for-byte複製し、canonical station SHA-256/byte metadataから`sourceLegacyDigest`を構成する。`legacyCompatibilityV1.expiresAt = asOf + 14 days`で、削除には同じ24時間marginを適用する。release-managed runtimeはこれらのaliasesへfallbackしない。期限後の次assemblyで8 aliasesとmetadataをまとめて削除する。legacy validatorはpublic schema、駅所有権、共通feed/serviceDate、file setを確認し、release validatorはaliasのhash/bytesとsourceLegacyDigestも再照合する。

### 19.3 retained descriptorの契約拡張

retained entryへ`releaseDescriptor`を追加する。manifest schemaVersionは1のままで、現行/legacy codeが読むstation map・current manifest fields・envelope・payload schemaは変えない。Python/Node contractとbrowser loaderはdescriptorがあるentryを検証し、descriptor hashからretained releaseIdを再計算する。Independent artifact validatorはdescriptor必須とし、8 retained envelopeのSHA/bytes/schema/station/common metadataと各inner payloadのcanonical hashをdescriptorへ照合する。旧currentをretireする段階では、source artifactの全asset bytesもcurrent descriptorに照合済み。

過去retained generationごとにversioned shell assetsを保存しない既存設計のため、すでにretainedだった世代はasset fileそのものを再照合できない。descriptorがreleaseIdにhash結合され、payload hashを現存8 JSONで照合できることが検証可能範囲。将来shell asset自体を世代別に配信しない限り、この限界は残る。既存descriptorless retained entryは4-8D-1 artifact validatorとassemblerが拒否する。4-8D-1より前にretained deploymentを作っていた場合は、その期間に対応する当時のassetを回収してdescriptorを復元・検証するか、新しい安全なretention baselineを作り直す必要がある。現状のstagingはlegacy flat 17 filesでretained manifestを配っていないため、このmigrationは未発生。

browser loaderの変更はretained entryの追加descriptor field受け入れとJCS/releaseId照合に限る。station selection/fetch, current manifest pinning, current payload verification/rendering/error/UXは変更しない。この加算的metadata acceptanceは新manifestをPhase 4-8C runtimeが読めるために必要で、runtime contract IDは維持する。古いrelease-managed runtimeが未知fieldを拒否するため、descriptor付きretention manifestを生成する前に新しいruntime shellをcurrentにdeployする必要がある。旧flat runtimeはmanifestを読まない。

### 19.4 Phase 4-8D-2 Production接続への受け渡し

- 取得対象: root `manifest.json`; retain期限内のcurrent + retained releaseごとの8 JSON (`/releases/<id>/<filename>`); 有効な`legacyCompatibilityV1`があればroot flat 8 JSON。shell assetsは新release artifactから使い、old generation assetsは取得・carryしない。
- Access:専用Cloudflare Access Service TokenのClient ID / Client SecretをGitHub Environment secretsに置き、`CF-Access-Client-Id` / `CF-Access-Client-Secret` headerとしてretention download stepだけへ注入。Wrangler tokenと権限/Environmentを分離する。値・headers・response bodyをshell trace/logへ出さない。
- HTTP:unconditional GET、redirect禁止、各JSONは200のみを通常成功とする。`manifest.json`/JSONは`application/json` Content-Typeを確認し、Content-Lengthがあれば実raw bytesと比較したうえでmanifestのbytes/SHA-256を照合する。304はconditional requestを使わない限りエラー。将来conditional GETを使う場合は同一run内の以前に検証済みraw bodyがあるときだけ304を復元可能にする。
- timeout/retry:提案初期値はconnect 5s、file 30s、1 deploy fetch全体5分。408/429/5xx/network timeoutだけ最大2回のbounded backoffを許し、401/403/404、redirect、不正MIME、途中切断、hash/bytes不一致は即abort。再試行後も失敗なら公開しない。値はD-2実測で調整する。
- Race control:GitHub deploy jobをPages project単位のnon-canceling concurrency groupへ入れる。download後manifest raw SHA-256とcurrent releaseIdを保存し、assembly・final validation後、Direct Upload直前にProduction aliasのmanifestをno-cacheで再GETし、raw hash/releaseIdが同じことを要求する。差があればartifactを捨てて新しいcurrentを取得し直す。GitHub concurrency外のDashboard/manual deployはCASで封じられないため、D-2では手動uploadをfreezeする運用窓を設けるか、Cloudflare側の唯一writer化を判断する。
- Rollback:aliasが以前のretained IDへ戻った場合、そのmanifestを新しいsource of truthとして再取得する。そのIDをcurrentから除き、過去のretiredAtを解除し、今回currentから退くgenerationだけをnowでretireする。rollback deploymentが保持manifestを欠く/old bytes欠損なら次のassemblyはfail closed。rollback自体のPages操作後にmanifest/file setを再検証する。

Phase 4-8D-1はCLI local inputだけを扱い、当時はHTTP取得、Access credential、workflow、Cloudflare Direct Uploadを実装しなかった。次のD-2B前に、production upload concurrency外writer対策、actual payload/tree byte budgetとallowance、Cloudflare Access MIME/redirect behavior、unpublished manifestの扱いを確定する。現在のlocalhost専用HTTP取得実装の境界とD-2B提案は次節に記録する。

## 20. Phase 4-8D-2A Production alias取得・fingerprint CLI

### 20.1 CLIと責務

`scripts/fetch_production_artifact.py` はalias HTTP取得だけを担当する。既存builderは呼ばず、取得完了後に`validate_public_artifact.py`の独立validator（Python API）を呼び、結果をD-1 `assemble_public_release.py --previous`へ渡せるdirectoryにする。Cloudflare API、Wrangler、Actions workflow、secret設定、deploy操作は含まない。許可先はCLIで固定したroot originであり、manifest内の相対URLは既存release contractとruntime asset allowlistでさらに制限される。

```sh
# HTTPS Production alias。Service Tokenはsecret storeから環境へ注入し、CLI引数には書かない。
export CF_ACCESS_CLIENT_ID="$PAGES_READ_CLIENT_ID"
export CF_ACCESS_CLIENT_SECRET="$PAGES_READ_CLIENT_SECRET"
python3 -B scripts/fetch_production_artifact.py fetch \
  --base-url https://dotchi-ikebukuro-staging.pages.dev \
  --output /private/tmp/t12-production-snapshot

# 取得したartifactをD-1へ渡す場合
python3 -B scripts/assemble_public_release.py \
  --previous /private/tmp/t12-production-snapshot \
  --new-release /private/tmp/t12-next-release \
  --as-of 2026-10-28T12:00:00+09:00 \
  --output /private/tmp/t12-next-assembled

# 初回移行専用。manifestがHTTP 404の場合にだけlegacy取得を許可する。
python3 -B scripts/fetch_production_artifact.py fetch \
  --base-url http://127.0.0.1:8765 --allow-insecure-localhost \
  --allow-initial-legacy-migration --output /private/tmp/t12-legacy-snapshot
```

上記の環境変数例は値を格納する場所の説明であり、実credentialをrepositoryやshell historyへ置かない。CLIにはAccess値を受け取る引数がなく、`CF-Access-Client-Id` / `CF-Access-Client-Secret` headerとしてだけ送る。片方だけ設定された場合は停止する。exception/log/resultはheader、response body、完全URLを含めない。HTTPは`--allow-insecure-localhost`とloopback IP/`localhost`の組み合わせだけ許可し、通常はHTTPS必須。出力先は存在しないdirectory、親は存在しsymlinkを含まない必要がある。一時stageは出力と同じ親に作り、失敗時は削除する。default budgetは20,000 files、単体25 MiB、全体256 MiB。有限retryは初回+指定回数で、timeout、途中切断、408/425/429/5xx/network errorだけを対象とし、認証・404・redirect・MIME・構造・hash errorはretry対象外。

### 20.2 取得選択・検証・legacy境界

- Release-managed: root manifestを一度取得し、strict JSON/manifest validation、current descriptorからのreleaseId再計算、descriptor asset setと現行9 static assetsの一致を確認。manifestから現在releaseの8 JSON、保持期限内のcurrent/retained JSON、未期限のlegacy flat aliases、およびvalidatorが必要とするstatic assetsだけをallowlistで取得する。originに追加ファイルがあってもlistingせず取得しない。
- retained entryは有効期間の残り+48時間を含む保持期限が未到来である場合に限り、D-1同様にdescriptor必須とする。期限と24h削除marginを過ぎたentryはlocal snapshot manifestから除き、expired fileも取得しない。raw source manifest bytesはfingerprint用に保持するが、normalized snapshotでは期限切れのretention/legacy metadataだけを削除する。現行runtime assetはD-1 validatorがcurrent descriptorと実bytesを照合する。
- 取得したJSONはmanifest記載のraw byte count/hashをindependent validatorが照合し、envelope/release/station、inner payload、駅間metadata、descriptorも検査する。最後にsource manifestを再取得し、raw SHA-256が開始時と同一であることを確認してからsnapshotを公開する。
- Legacy: manifest endpointのHTTP 404だけを「manifestなし」と扱う。404以外、HTML login 200、malformed/invalid manifest、timeout、401/403はlegacyへfallbackしない。legacyは`--allow-initial-legacy-migration`の明示時だけ、現在の17 allowlisted filesを全取得し、既存strict validatorで検証する。開始/終了で17ファイルの固定順hash+bytes fingerprintを比較し、途中でmanifestが出現していないことも再確認する。
- 同一alias取得中のraceは、release-managedならraw manifest SHA、legacyなら固定17-file fingerprintの前後差でfail-closedにする。これは瞬間的にA→B→Aへ変わるABAや、取得終了後からdeployまでの競合を暗号学的にロックするものではない。後者はD-2B deploy直前のfingerprint再確認とGitHub concurrencyで窓を縮める。Dashboard等の別writerとのCAS保証はなく、手動deploy凍結または唯一writer化が別途必要。

Static assetsの全量取得は省略できない。current descriptorは9 assetのhashをreleaseId preimageに含み、独立validatorが実bytesと照合するためである。manifestが参照する必要ファイルのみ取得するので、directory listingや未参照ファイルの全downloadはしない。過去retained generationのshell assets自体はD-1契約で保持されず、retained descriptor内の過去asset hashは過去bytesとの再照合対象ではない。

### 20.3 fingerprint APIとD-2B直前確認

```sh
python3 -B scripts/fetch_production_artifact.py fingerprint \
  --base-url https://dotchi-ikebukuro-staging.pages.dev --mode release-managed
# 出力のfingerprintを同一deploy run内の安全なstep output/artifactへ保存し、Direct Upload直前:
python3 -B scripts/fetch_production_artifact.py fingerprint \
  --base-url https://dotchi-ikebukuro-staging.pages.dev --mode release-managed \
  --expected-sha256 "$CAPTURED_PRODUCTION_FINGERPRINT"
```

release-managed fingerprintはroot `manifest.json`の**raw response bytesのSHA-256**。legacy modeはstrict validator通過後に、固定17 pathのpath→`{sha256,bytes}` mapをJCS canonicalizeしSHA-256する。`--expected-sha256` mismatch時はnonzero終了。release-managed `fingerprint`コマンドは1回のmanifest snapshotを返し、legacyは17ファイルを2回読み直す。deploy workflowではdownload時のfingerprintとreleaseIdをrun内に固定し、assembly/final validation後・Direct Upload直前に同コマンドを再実行する。差があれば既に作ったassemblyを捨て、最新aliasを再取得して先頭からやり直す。値はCIログへ平文出力せず、step output等へ限定する。Cloudflare Dashboard deployはGitHub concurrency groupに参加しないため、この手順だけでは同時publishを防げない。

### 20.4 D-2B Cloudflare/GitHub接続への推奨

- Cloudflare Accessは専用Service TokenとService Auth policyをretention runner用に作る。human email OTPの既存Allow policyはそのまま残し、machine token policyは対象Pages hostnameに限定する。共有・広域tokenを避け、stagingとproductionでtokenを分離し、ローテーション・失効手順を用意する。Access policyのpath/HTTP method制限可否は実装前にCloudflare設定で確認する。Pages aliasが同一Access app配下にあり必要scopeへ絞れない場合、別hostname/policyへ分離する判断を先に行う。
- GitHub Environmentには例として`PAGES_PRODUCTION_READ_CLIENT_ID`、`PAGES_PRODUCTION_READ_CLIENT_SECRET`を環境別に置き、download/recheck jobだけへ渡す。CLIは現状`CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET`を読むため、workflow側でstep-local mappingする。secretをartifact、command argument、debug trace、exception、HTTP bodyへコピーしない。GitHub Environment/secretはこのPhaseでは作成していない。
- 現CLIはHTTP status 200、JSON `application/json`、HTML/CSS/JSの対応MIME、実bytesと上限を確認する。unconditional requestなので304、redirect、401/403、404（manifest 404の明示legacy判定を除く）、HTML login、途中切断は公開失敗にする。
- GitHub Pages-project単位の`cancel-in-progress: false` concurrencyをdata publishとapp publish共通で使う。GitHub job外Dashboard deployを残すならdeploy直前fingerprint後からupload完了まで手動writerを止めるrunbookを用意する。DashboardとActions双方から同時uploadする場合はCAS相当の外部調整がない限り安全保証できない。
- 初回legacy migrationは明示flag付きdownloadで17-file strict validationし、D-1 assemblyでflat JSONを14日保持するmanifest/eight aliasesを生成してrelease-managed新shellと一括deployする。壊れた/欠損legacyは取り込まない。実stagingのlegacy 17ファイルやAccess認証は今回取得していない。
- rollback後はalias上の現在manifest/fingerprintを新source of truthとして再取得し、現在artifactを独立検証してからassemblyする。以前のlocal snapshot/ArtifactだけをProductionの現状とみなさない。rollback後もmanifestが欠落・不正、必要generationが404ならfail closedしdeployしない。

### 20.5 ローカルテスト・限界

`tests/test_fetch_production_artifact.py` はfixtureから生成したlegacy 17-fileとrelease-managed 18-fileを127.0.0.1のテストHTTP serverで配信し、normalizationなしの独立validationとD-1入力形を確認する。current-only、retained付き（26 files）、初回legacy-alias付き（26 files）release snapshotを取得する。HTTP/Access header present/missing/401/403/secret非漏えい、malformed/absent manifestとfallback拒否、JSON 404/hash改変、HTML login/MIME、別origin redirect未到達、不正path、有限timeout/中断retry、上限、既存出力/symlink、legacy/releaseの取得途中変更、fingerprint mismatch、未知remote file非取得を自動化する。テスト専用loopback HTTP以外へ通信しない。legacy 17-file snapshotとrelease-managed current snapshotを実際にD-1 `assemble_public_artifact()`へ渡し、完成artifactのindependent validator通過まで確認する。Cloudflare Access policy、実Pages headers/ETag/cache、Service Token、実Cloudflare redirect挙動、GitHub Actions/OIDC/secret masking、Dashboard raceは未検証。

このPhaseのコードはローカル専用CLIとtestだけで、既存17-file builder/default validator/runtime/18-file contract/synthetic fixtures/workflow/stagingは変更しない。実接続、Access設定、GitHub secret、CI自動化、Cloudflare deployment、ODPT API、commit/push/mergeは行わない。D-2Bでは先にCloudflare/GitHub利用枠、Access policy共存、unique writer/concurrency、D-1の実データbyte budget、manual rollback運用を確定し、workflow変更を別作業としてレビューする。

## 16. 根拠・作業境界

設計根拠として`docs/t12_phase4_6b_release_consistency.md`、`docs/project_state.md`、`docs/devlog.md`、`scripts/build_public_site.py`、`scripts/validate_public_artifact.py`、`scripts/public_payload_profile.py`、`scripts/synthetic_public_fixture_factory.py`、`scripts/local_preview_payload_loader.mjs`、`_local_preview/preview_core.mjs`、`scripts/timetable_adapter.mjs`、`.github/workflows/synthetic-public-ci.yml`と関連testsを読んだ。

Phase 4-7はドキュメントのみ、4-8Aは契約module、4-8Bはbuilder/independent validator、4-8Cはexplicit runtime modeとlocal QAを追加した。builder defaultの17-file出力、legacy validator/runtime behavior、synthetic fixture contract、GitHub Actions workflow、existing staging/public deploymentは維持。Cloudflare deploy・Actions実行・ODPT API接続・old Production alias fetch・commit/push/mergeなし。
