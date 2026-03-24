"""labvault 例外クラス。"""

from __future__ import annotations


class LabvaultError(Exception):
    """SDK基底例外。"""


class RecordNotFoundError(LabvaultError):
    """レコードが見つからない。"""

    def __init__(self, record_id: str) -> None:
        self.record_id = record_id
        super().__init__(f"Record not found: {record_id}")


class SyncError(LabvaultError):
    """同期失敗。"""


class BackendError(LabvaultError):
    """バックエンド操作失敗。"""


class ValidationError(LabvaultError):
    """バリデーションエラー。"""


class AuthError(LabvaultError):
    """認証・認可エラー。"""


class LabvaultPermissionError(LabvaultError):
    """権限不足エラー。ビルトイン PermissionError との衝突を避けてリネーム。"""
