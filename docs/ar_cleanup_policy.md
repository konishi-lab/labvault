# Artifact Registry cleanup policy

`asia-northeast1 / klab-laser-process / labvault-pypi` (private PyPI 兼用の Python repo)
に積もる古い wheel / sdist をどう片付けるかの方針。本ドキュメントは **設計のみ**
で、実 apply (gcloud 一発) は別途運用判断で行う。

## 現状

- `.github/workflows/publish-pypi.yml` が `v*` タグ push で wheel + sdist を upload
- v0.1.0 以降のすべての version が AR repo に残存している
- 削除手段は手動 (gcloud / Console) のみ
- 利用者 (`pip install`) は `--extra-index-url` 経由で AR を引く

## なぜ片付けるのか

| 観点 | 程度 |
|---|---|
| **コスト** | AR Python repo は GB 単価。labvault wheel は数 MB / version、現状 < 100 MB。**当面は無料枠内**なので緊急ではない |
| **混乱** | 古い 0.0.x など bug 持ちが残ると、誤って install されて再現性が落ちる。`pip install "labvault>=0.2"` で防げるが、ガイドにそう書く運用が必要 |
| **監査** | 全 version が残ってる方が「いつ何を出したか」追えるので、消すなら snapshot や changelog で同等の情報を残すべき |

総合: 緊急ではないが、**早めに方針を固めて organic に育てる方が安い**。

## 候補オプション

### Option A — AR 組み込み cleanup policy (推奨)

AR には repo 単位で **削除ポリシー** が組み込まれている (`gcloud artifacts repositories set-cleanup-policies`)。dry-run で挙動を確認してから apply できる。

**メリット**
- 自前スクリプト不要
- AR 側で定期的に走るので CI / cron 不要
- dry-run flag で「次に消すもの」をプレビューできる (`--dry-run`)

**デメリット**
- ポリシーの記述力は限定的 (age / count / tag prefix の組み合わせ)。複雑な「直近の minor 3 つを保持」みたいなのは書けない (= 工夫が要る)

### Option B — 自前スクリプト (`scripts/ar_cleanup.py`) + GitHub Actions schedule

cleanup policy では書けない複雑な条件 (例: 「v0.x 系の最新だけ残す、v1.x 系は全保持」) を書ける。

**メリット**
- 任意のロジック
- code review に乗る

**デメリット**
- 実装・テストコストがかかる
- schedule workflow を維持しないといけない (CI 緑のままだと忘れがち)

### 推奨

**Option A を採用**。理由:
- 当面の運用ニーズは「古いものを機械的に消す」程度
- 複雑なルールが必要になったら Option B に乗り換える(本ドキュメントを更新)

## 推奨ポリシー (Option A)

3 つのポリシーを組み合わせる。

### ポリシー 1: `keep-recent-versions` (KEEP)

直近 **10 version** は無条件で保持。

```json
{
  "name": "keep-recent-versions",
  "action": { "type": "Keep" },
  "mostRecentVersions": {
    "packageNamePrefixes": ["labvault"],
    "keepCount": 10
  }
}
```

### ポリシー 2: `keep-minor-latest` (KEEP)

`minor` 単位の最新版は古くても保持 (`v0.1.7`, `v0.2.5` などの "x.y の最後" を残す)。

組み込みポリシーでは「semver minor の最後」を直接表現できないので、**tag prefix で擬似実現**:
- リリース時に `v0.1.7` 以外に `v0.1-latest` のような **moving tag** も打つ運用
- moving tag が指す version を保持

**この運用は手間なので、当面は採用しない**。Option B に移行した時に検討。

### ポリシー 3: `delete-old` (DELETE)

ポリシー 1 で保持されなかった version のうち、**作成から 365 日経過したもの** を削除。

```json
{
  "name": "delete-old",
  "action": { "type": "Delete" },
  "condition": {
    "olderThan": "31536000s",
    "packageNamePrefixes": ["labvault"]
  }
}
```

合算挙動: **「直近 10 version は何があっても保持、それ以外で 1 年経過したものを削除」**。

## 適用手順 (本番反映時の参考)

```bash
# 1. JSON ファイルを準備
cat > /tmp/ar_cleanup.json << 'EOF'
[
  {
    "name": "keep-recent-versions",
    "action": { "type": "Keep" },
    "mostRecentVersions": {
      "packageNamePrefixes": ["labvault"],
      "keepCount": 10
    }
  },
  {
    "name": "delete-old",
    "action": { "type": "Delete" },
    "condition": {
      "olderThan": "31536000s",
      "packageNamePrefixes": ["labvault"]
    }
  }
]
EOF

# 2. dry-run で挙動確認 (実際には消えない、消える対象がログに出る)
gcloud artifacts repositories set-cleanup-policies labvault-pypi \
  --project=klab-laser-process \
  --location=asia-northeast1 \
  --policy=/tmp/ar_cleanup.json \
  --dry-run

# 3. 1 週間ほど dry-run のまま放置してログを確認
#    (Cloud Logging で artifactregistry.googleapis.com の CleanupRun イベントを見る)

# 4. 問題なければ dry-run 解除
gcloud artifacts repositories set-cleanup-policies labvault-pypi \
  --project=klab-laser-process \
  --location=asia-northeast1 \
  --policy=/tmp/ar_cleanup.json \
  --no-dry-run
```

## セーフガード

- **apply 前に snapshot**: `gcloud artifacts versions list --repository=labvault-pypi --location=asia-northeast1 --package=labvault > ar_snapshot.txt` を git commit して残す
- **CHANGELOG.md** を同時に整備 (削除しても「何を出したか」の記録は残る)
- **README** に「サポート対象は直近 10 version」と明示
- 万一の rollback: AR の削除は **soft delete (30 日保持)** 扱い。慌てて undelete できる (`gcloud artifacts versions restore`)

## 将来の拡張 (Option B に乗り換えるトリガー)

次のいずれかが発生したら Option B (自前スクリプト) を検討:

- semver minor 単位の保持が必要になった (`v0.1.x` の最新を 1 年以上残したい)
- 利用者の install ログから「実際に install された version」を集めて、参照されてる version だけ残したい
- 削除前に Slack 通知などのワークフローを挟みたい

## 参考

- AR cleanup policy 公式: <https://cloud.google.com/artifact-registry/docs/repositories/cleanup-policy>
- gcloud reference: `gcloud artifacts repositories set-cleanup-policies --help`
- 既存運用: [`docs/multitenant_next_steps.md`](multitenant_next_steps.md), [`scripts/ar_backfill.py`](../scripts/ar_backfill.py)
