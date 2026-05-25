#!/usr/bin/env bash
# Firestore 複合インデックスを gcloud で一括 apply するスクリプト。
#
# firebase deploy --only firestore:indexes:labvault が firebase-tools v14
# の bug (multi-database 配列形式で payload undefined) で落ちるため、
# 代替として gcloud で 1 個ずつ流す。各コマンドは非同期で submit され、
# 既存と等価な index がある場合は ALREADY_EXISTS で skip される (継続)。
#
# 新規 8 個 (PR #11 の idx_<key> 対応) のみ作成する。既存 index は触らない
# ので overwrite 事故は起きない。

set -u

PROJECT="${LABVAULT_GCP_PROJECT:-klab-laser-process}"
DATABASE="${LABVAULT_FIRESTORE_DATABASE:-labvault}"

create() {
  local label="$1"
  shift
  echo ""
  echo "==> $label"
  gcloud firestore indexes composite create \
    --project="$PROJECT" \
    --database="$DATABASE" \
    --collection-group=records \
    --query-scope=COLLECTION \
    --async \
    "$@" \
    || echo "   (skipped or failed — likely ALREADY_EXISTS)"
}

# 単一 idx_<key> (6 種)
create "deleted_at + idx_target + updated_at" \
  --field-config=field-path=deleted_at,order=ascending \
  --field-config=field-path=idx_target,order=ascending \
  --field-config=field-path=updated_at,order=descending

create "deleted_at + idx_method + updated_at" \
  --field-config=field-path=deleted_at,order=ascending \
  --field-config=field-path=idx_method,order=ascending \
  --field-config=field-path=updated_at,order=descending

create "deleted_at + idx_sample_name + updated_at" \
  --field-config=field-path=deleted_at,order=ascending \
  --field-config=field-path=idx_sample_name,order=ascending \
  --field-config=field-path=updated_at,order=descending

create "deleted_at + idx_measurement_mode + updated_at" \
  --field-config=field-path=deleted_at,order=ascending \
  --field-config=field-path=idx_measurement_mode,order=ascending \
  --field-config=field-path=updated_at,order=descending

create "deleted_at + idx_mode + updated_at" \
  --field-config=field-path=deleted_at,order=ascending \
  --field-config=field-path=idx_mode,order=ascending \
  --field-config=field-path=updated_at,order=descending

create "deleted_at + idx_laser_wavelength_nm + updated_at" \
  --field-config=field-path=deleted_at,order=ascending \
  --field-config=field-path=idx_laser_wavelength_nm,order=ascending \
  --field-config=field-path=updated_at,order=descending

# parent_id 併用 (2 種)
create "deleted_at + parent_id + idx_target + updated_at" \
  --field-config=field-path=deleted_at,order=ascending \
  --field-config=field-path=parent_id,order=ascending \
  --field-config=field-path=idx_target,order=ascending \
  --field-config=field-path=updated_at,order=descending

create "deleted_at + parent_id + idx_sample_name + updated_at" \
  --field-config=field-path=deleted_at,order=ascending \
  --field-config=field-path=parent_id,order=ascending \
  --field-config=field-path=idx_sample_name,order=ascending \
  --field-config=field-path=updated_at,order=descending

echo ""
echo "==> 全ての index を submit しました (async)。"
echo "状態確認:"
echo "  gcloud firestore indexes composite list --project=$PROJECT --database=$DATABASE"
echo "State: READY になるまで数分〜数十分かかります。"
