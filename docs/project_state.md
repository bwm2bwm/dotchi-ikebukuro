# プロジェクト状態

最終整理: 2026-11-03。仕様の正本は [product_spec.md](product_spec.md) と [ui_spec.md](ui_spec.md)、ODPT/GTFSの根拠と未解決事項は [odpt_research.md](odpt_research.md)、配信方式は [hosting_research.md](hosting_research.md)。詳細な作業履歴は [devlog.md](devlog.md)。

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
- ODPT更新通知の具体的運用、東京メトロGTFSへの `date=current/next/latest` 適用可否。
- 公開payloadの再構成リスク、表示・クレジット条件の実データ公開適用確認。
- release-managedのrollback実地確認、旧タブ・cache境界QA。
- 運行日境界を跨ぐ乗換探索は未実装。

ODPT事務局の2026-10-26回答で確認済みの範囲（説明した構成での加工済み時刻表配信、サーバー側保存/cache、広告・任意支援付き無料公開）は未解決に戻さない。回答の適用範囲を超える許可とは扱わない。詳細は [odpt_research.md](odpt_research.md)。

## 次の作業

1. ODPT/東京メトロの公式仕様・配布条件から取得日時、更新通知、適用期間の根拠を確定する。
2. source版整合・鮮度・差分ゲートの要件を決める。
3. 未解決のstaging QAを整理する。
4. 実データ公開の判断は、根拠と検証結果を揃えた後に別途行う。

この文書は状態の要約であり、履歴の数値や手順を重複管理しない。
