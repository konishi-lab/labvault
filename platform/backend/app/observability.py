"""Cloud Logging 互換の構造化 (JSON) ログを 1 行で出すヘルパ。

backend の `records.py` / `metadata.py` / `bulk_upload.py` 等の主要経路は
これまで `logger` インスタンスが存在せず、slow query や push-down 失敗
が完全ブラックボックスだった (backend review C3 指摘)。本モジュールで:

1. `log_event(logger, event, **fields)` で「1 イベント = 1 JSON ログ行」
   を強制 (Cloud Logging が自動 parse して `jsonPayload.*` で検索可能に)
2. `EventTimer(logger, event, **fields)` context manager で duration_ms
   を自動付与 + slow 判定
3. main.py の lifespan で **1 度だけ** Cloud Logging 互換 JSON formatter
   を root logger に attach する (`setup_json_logging()`)

Cloud Run / Cloud Logging は stdout/stderr の各行が「JSON object かつ
`message` キーを含む」場合に自動的に structured payload として parse
する (`severity` が Python の `levelname` と対応)。本ヘルパが出す JSON
はその規約に揃えてある。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import AbstractContextManager
from typing import Any, Self

# Cloud Logging が期待する severity 名 (Python `levelname` と一致しない値あり)
# 参考: https://cloud.google.com/logging/docs/reference/v2/rest/v2/LogEntry#LogSeverity
_LEVEL_TO_SEVERITY = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}

# 「slow」と判定する閾値 (ms)。本番で問題発見の起点になるので、最初は
# 控えめ (1000ms = 1s) に置く。実運用で再調整する想定。
SLOW_THRESHOLD_MS = 1000


class _JsonFormatter(logging.Formatter):
    """1 LogRecord = 1 JSON object をシリアライズする formatter。

    Python の `extra={"event": ..., "fields": {...}}` で渡された
    additional fields を payload に flat に乗せる (`log_event` が使う形)。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": _LEVEL_TO_SEVERITY.get(record.levelno, record.levelname),
            "message": record.getMessage(),
            "logger": record.name,
        }
        # `log_event` が乗せた fields は record の attribute として
        # `_lv_fields` に格納してある (formatter で expand する)。
        lv = getattr(record, "_lv_fields", None)
        if isinstance(lv, dict):
            for k, v in lv.items():
                if k not in payload:
                    payload[k] = v
        # exception があれば traceback を文字列で格納
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_JSON_LOGGING_INSTALLED = False


def setup_json_logging() -> None:
    """root logger に JSON formatter 付き StreamHandler を 1 度だけ attach する。

    N5 (PR #83): Cloud Run + uvicorn 環境では起動時点で root に既存の
    StreamHandler (uvicorn 既定のプレーンテキスト出力) が居る。これを
    残したまま JSON handler を追加すると、**1 ログ行が 2 行 (plain + JSON)
    で重複出力** され、Cloud Logging のコスト/ノイズが 2 倍。

    対策: 既存の StreamHandler は **置換せず取り外す** (= root から detach)。
    JSON formatter 付きの 1 個だけが残るようにする。uvicorn のロガー自体
    (`uvicorn.error` 等の子ロガー) は別途自分の handler を持つことがあるが、
    そちらは触らず root だけ整える (子ロガーの伝播は別 effect)。

    test 環境では `LABVAULT_DISABLE_JSON_LOG=1` で抑止可能 (caplog の
    plain text 出力と衝突するため)。
    """
    global _JSON_LOGGING_INSTALLED
    if _JSON_LOGGING_INSTALLED:
        return
    if os.environ.get("LABVAULT_DISABLE_JSON_LOG") == "1":
        _JSON_LOGGING_INSTALLED = True
        return
    root = logging.getLogger()
    # 既に root に居る StreamHandler を全部外す (重複出力の元)。
    # ファイル handler / SysLog handler 等 stream 系以外は残す。
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(
            h, logging.FileHandler
        ):
            root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter())
    handler.set_name("labvault-json")
    root.addHandler(handler)
    # default は INFO (DEBUG にすると Firestore SDK が冗長すぎる)
    if root.level == logging.WARNING:
        root.setLevel(logging.INFO)
    _JSON_LOGGING_INSTALLED = True


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """1 イベントを構造化 JSON ログとして 1 行で出す。

    例:
        log_event(logger, "aggregate.done", key="power", record_count=500,
                  value_count=489, duration_ms=142, truncated=True)

    Cloud Logging では `jsonPayload.event="aggregate.done"` で検索可能。
    `duration_ms` を含むイベントはダッシュボードでも latency 分布が
    出せる。
    """
    extra = {"_lv_fields": {"event": event, **fields}}
    # message にも human-readable な要約を載せる (Cloud Logging 一覧で
    # JSON を expand せずに概要が読めるよう)
    summary_parts = [f"{k}={fields[k]!r}" for k in list(fields.keys())[:3]]
    summary = f"{event} ({', '.join(summary_parts)})" if summary_parts else event
    logger.log(level, summary, extra=extra)


# 「ログに乗せて安全」と見なす key 名の最大長。短い identifier 想定。
_SAFE_KEY_MAX_LEN = 40
_REDACTED = "<redacted>"


def safe_keys(keys: Any) -> list[str]:
    """log_event に渡す前に condition_keys 等の入力を sanitize する。

    N6 (PR #83): `records.list` / `records.aggregate` 等の event field に
    ユーザー入力由来の dict key (`condition_keys`) を乗せていた。template で
    宣言された key (`power` / `target` 等) は安全だが、**ユーザーがフリー
    フォームで入れた key** (`patient_name`、メアド、長文等) は PII リスク。

    ルール:
    - str でないか、空文字なら除外
    - `str.isidentifier()` (英数 + underscore + 先頭非数字) を満たし、
      長さ <= `_SAFE_KEY_MAX_LEN` のものはそのまま通す
    - それ以外は ``<redacted>`` に置換 (count を保ったまま、値は隠す)
    - 結果は **入力順を保つ** (元のソート順の意味を残す)
    """
    if not isinstance(keys, (list, tuple, set)):
        return []
    out: list[str] = []
    for k in keys:
        if not isinstance(k, str) or not k:
            continue
        # `str.isidentifier()` は Python の文法上の identifier 判定で、
        # 日本語などの Unicode identifier も True を返す。PII リスクを下げ
        # たいので、追加で **ASCII 限定** チェックを入れる。
        if (
            k.isidentifier()
            and k.isascii()
            and len(k) <= _SAFE_KEY_MAX_LEN
        ):
            out.append(k)
        else:
            out.append(_REDACTED)
    return out


class EventTimer(AbstractContextManager["EventTimer"]):
    """context manager で event の所要時間 (ms) を自動付与する。

    例:
        with EventTimer(logger, "aggregate") as t:
            ...
            t.add(record_count=500, value_count=489, truncated=True)

    終了時に 1 イベントだけ emit する。`duration_ms` が `SLOW_THRESHOLD_MS`
    を超えると level を WARNING に格上げ (Cloud Logging アラート対象)。
    """

    def __init__(
        self,
        logger: logging.Logger,
        event: str,
        **fields: Any,
    ) -> None:
        self._logger = logger
        self._event = event
        self._fields: dict[str, Any] = dict(fields)
        self._t0 = 0.0

    def __enter__(self) -> Self:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        duration_ms = round((time.perf_counter() - self._t0) * 1000, 1)
        level = (
            logging.ERROR
            if exc_type is not None
            else (logging.WARNING if duration_ms >= SLOW_THRESHOLD_MS else logging.INFO)
        )
        fields: dict[str, Any] = {"duration_ms": duration_ms, **self._fields}
        if exc_type is not None:
            fields["error_type"] = exc_type.__name__
        if duration_ms >= SLOW_THRESHOLD_MS:
            fields["slow"] = True
        log_event(self._logger, self._event, level=level, **fields)
        # 例外は再 raise させたいので suppress しない
        return None

    def add(self, **fields: Any) -> None:
        """追加の field を貯める (`__exit__` で emit される)。"""
        self._fields.update(fields)
