# Backend Agent Rules

- このバックエンドは labvault SDK (`src/labvault/`) のラッパーです。ビジネスロジックは SDK 側にあります
- 新しいエンドポイントを追加する際は、対応する SDK メソッドが `Lab` または `Record` クラスに存在することを確認してください
- `schemas.py` のレスポンスモデルは SDK の `Record._to_dict()` と整合性を保ってください
- FastAPI の `Depends(get_lab)` で Lab インスタンスを注入します。直接 `Lab()` を呼ばないでください
