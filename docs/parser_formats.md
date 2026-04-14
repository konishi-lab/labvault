# パーサー対応フォーマット仕様

labvault が扱う顕微鏡データフォーマットの仕様と解析手法をまとめる。

## VK4 (Keyence レーザー顕微鏡)

### 概要

Keyence VK-X シリーズのレーザー顕微鏡が出力するバイナリファイル。
1つのファイルに光学画像、レーザー画像、高さデータが格納されている。

### バイナリ構造

ヘッダ先頭部にオフセットテーブルがあり、各データブロックの開始位置を示す。

| オフセット位置 | 内容 |
|---|---|
| bytes 16-20 | 光学画像 (color) オフセット |
| bytes 20-24 | レーザー+光学合成画像 (laser color) オフセット |
| bytes 24-28 | レーザー輝度画像 (laser intensity) オフセット |
| bytes 36-40 | 高さデータ (height) オフセット |
| bytes 252-256 | XY スケール (nm × 1000) |
| bytes 260-264 | Z スケール (nm × 1000) |

各データブロックの先頭 20-28 バイトにメタ情報がある:

| オフセット | 内容 |
|---|---|
| 0-4 | width (pixels) |
| 4-8 | height (pixels) |
| 8-12 | データバイト数/pixel × 8 |
| 16-20 | 総データ長 (bytes) |

### データ型

| データ種別 | 型 | 形状 | 備考 |
|---|---|---|---|
| 光学画像 | uint8 | (H, W, 3) | BGR → RGB 変換必要 |
| レーザー+光学合成画像 | uint8 | (H, W, 3) | BGR → RGB 変換必要 |
| レーザー輝度画像 | 可変バイト長整数 | (H, W) | LZW テーブル (768 bytes) あり |
| 高さデータ | 可変バイト長整数 | (H, W) | LZW テーブル (768 bytes) あり、単位: Z スケール × 値 = nm |

### スケール

- XY: `struct.unpack_from("<I", header, 252)[0] / 1e3` → nm
- Z: `struct.unpack_from("<I", header, 260)[0] / 1e3` → nm
- 高さデータの実寸 = `heightviewer() * Z_scale` (nm)

### 参照実装

- `klab-device-library/analysis/vk4_decoder.py` (GitHub: konishi-lab/klab-device-library)
  - `colorviewer()` — 光学画像
  - `lasercolorviewer()` — レーザー+光学合成画像
  - `laserviewer()` — レーザー輝度画像
  - `heightviewer()` — 高さデータ
  - `getscale()` — XY/Z スケール
  - `fix_tilt()` — 傾き補正 (平面フィット除去)
  - `extract_crater()` — クレーター検出 + クロップ
  - `extract_volume()` — 除去体積計算

## PLUX (Sensofar 干渉計)

### 概要

Sensofar S neox シリーズの干渉計 (CSI: Coherence Scanning Interferometry) が出力するファイル。
`.plux` ファイルは ZIP アーカイブで、高さマップ・光学画像・メタデータを含む。
MDG (Measurement Data Gateway) 経由で `measure3d_plux.zip` として配信される。
`measure3d_plux.zip` の中に `measure3d_before.plux` と `measure3d_after.plux` が入っている。

### ファイル構造 (.plux = ZIP)

| ファイル名 | 形式 | 内容 |
|---|---|---|
| `LAYER_0.raw` | float32, H×W | 高さマップ (単位: µm) |
| `LAYER_0.stack.raw` | uint8, H×W×3 | 光学画像 (RGB) |
| `z.thumbnail` | uint8, 280×280×3 | 高さマップサムネイル |
| `stack.thumbnail` | uint8, 280×280×3 | 光学画像サムネイル |
| `index.xml` | XML | メタデータ |
| `metrics.txt` | XML | 計測タイミング情報 |
| `recipe.txt` | XML | 測定条件詳細 |
| `preferences.txt` | XML | ソフトウェア設定 |
| `Analysis/recipe.txt` | XML | 解析設定 |

### index.xml の主要フィールド

```xml
<GENERAL>
    <FOV_X>0.138</FOV_X>         <!-- 視野 X (mm) -->
    <FOV_Y>0.138</FOV_Y>         <!-- 視野 Y (mm) -->
    <IMAGE_SIZE_X>2448</IMAGE_SIZE_X>
    <IMAGE_SIZE_Y>2048</IMAGE_SIZE_Y>
</GENERAL>
<Instrument>
    <Manufacturer>Sensofar</Manufacturer>
    <Model>S neox 090</Model>
</Instrument>
<ProbingSystem>
    <Id>Nikon - DI 50X|...|50.0000</Id>  <!-- 対物レンズ -->
</ProbingSystem>
<LAYER_0>
    <FILENAME_Z>LAYER_0.raw</FILENAME_Z>
    <FILENAME_STACK>LAYER_0.stack.raw</FILENAME_STACK>
</LAYER_0>
```

### スケール

- ピクセルサイズ: `FOV_X (mm) * 1000 / IMAGE_SIZE_X` → µm/pixel
- 例: 138 µm / 2448 px = 0.0564 µm/pixel = 56.4 nm/pixel
- Z 単位: µm (float32 値がそのまま µm)

### 確認済みの装置情報

- 装置: Sensofar S neox 090 (SN: 90-048-2019)
- 対物レンズ: Nikon DI 50X
- 測定方式: CSI (Coherence Scanning Interferometry)
- Z scan range: 60 µm

## 共通解析パイプライン

VK4 と PLUX は出力形式が異なるが、解析処理は共通化できる。

### データフロー

```
VK4 file  ──→ vk4.py  ──→ SurfaceData(height_map, optical_image, scale)
PLUX file ──→ plux.py ──→ SurfaceData(height_map, optical_image, scale)
                                │
                                ▼
                          _analysis.py
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              tilt_correct  detect_crater  compute_volume
                                │
                                ▼
                    CraterMetrics(diameter, depth, volume, ...)
```

### SurfaceData (共通データ構造)

```python
@dataclass
class SurfaceData:
    height_map: np.ndarray    # (H, W) float, 単位: µm
    optical_image: np.ndarray | None  # (H, W, 3) uint8, RGB
    pixel_size_um: float      # µm/pixel
    z_unit: str               # "um"
```

### 解析関数 (共通)

| 関数 | 入力 | 出力 | 説明 |
|---|---|---|---|
| `correct_tilt(height_map)` | 高さマップ | 補正済み高さマップ | 平面フィット除去 (最小二乗法) |
| `detect_crater(height_map, pixel_size_um, threshold)` | 高さマップ | CraterMetrics | クレーター検出、径・深さ計測 |
| `compute_volume(height_map, pixel_size_um)` | 高さマップ (クロップ済み) | float (µm³) | 除去体積 |

### CraterMetrics (計測結果)

```python
@dataclass
class CraterMetrics:
    diameter_um: float       # 等価円径 (µm)
    depth_um: float          # 最大深さ (µm)
    mean_depth_um: float     # 平均深さ (µm)
    volume_um3: float        # 除去体積 (µm³)
    center_x_um: float      # クレーター中心 X (µm)
    center_y_um: float      # クレーター中心 Y (µm)
    bbox_width_um: float    # バウンディングボックス幅 (µm)
    bbox_height_um: float   # バウンディングボックス高さ (µm)
    area_um2: float          # クレーター面積 (µm²)
```

### PLUX での before/after 差分解析

PLUX は照射前後のデータが別ファイルとして提供される。
差分 (after - before) を取ることで、レーザー加工による形状変化を抽出できる。

```python
diff = after.height_map - before.height_map
crater = detect_crater(diff, pixel_size_um, threshold=-0.05)
```

### クレーター検出アルゴリズム

1. 高さマップの中央値を基準レベルとする
2. 基準レベルから threshold (デフォルト: -0.05 µm) 以下の領域をマスク
3. `scipy.ndimage.label()` で連結領域をラベリング
4. 最大面積の連結領域をクレーターとして抽出
5. 等価円径、最大深さ、体積を計算

VK4 の `extract_crater()` では threshold=300 (nm 相当、Z スケール依存) を使用。
PLUX では µm 単位なので threshold=-0.05 (50 nm) 程度が適切。
