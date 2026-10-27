# 研究領域興隆可視化ダッシュボード (Research_Area_Viwer)

研究分野の「隆盛度」を、論文タイトルにおける対象語句の出現率の年次時系列で比較・判定する分析基盤。
データ源は [OpenAlex API](https://api.openalex.org)。

```
backend/     Python の分析基盤(API取得・集計・出力・検証・テスト)
frontend/    静的な PWA ビューア(iPhone のホーム画面から起動)
future/      将来拡張(状態空間モデル、LLM分類)。今回は TODO のみ
outputs/     バックエンドの出力。フロントとの唯一の接点(git管理外、Actionsが生成)
data/cache/  APIレスポンスのキャッシュ(git管理外)
```

バックエンドとフロントエンドは `outputs/`(`summary.json`・CSV・PNG)のファイルだけでつながる。
フロントはバックエンドのコードに依存しないため、将来 PC 版を作る場合も同じ出力を読めばよい。

## 使い方(iPhone だけで完結させる場合)

1. GitHub のリポジトリ設定 → Secrets and variables → Actions で `OPENALEX_API_KEY` を登録する(キーは https://openalex.org/settings/api で無料取得)。
2. Actions タブ → `analyze` → Run workflow。最初は `validate`(クエリ検証)を選ぶ。
3. `outputs` アーティファクトの `validation.json` で OR 条件が効いているか確認する。NG なら `backend/config.yaml` の `query_mode` を `union` に変える。
4. `run` を選んで実行すると、集計結果が GitHub Pages に公開される。公開された URL を Safari で開き、共有ボタン →「ホーム画面に追加」でアイコンから起動できる。
5. 精度確認は `sample` を実行し、`outputs/samples/precision_samples.csv` の `label` 列に「主題 / 非主題」を記入する。

注意: API キーはブラウザ側(フロント)には置かない。キーはバックエンド(Actions)だけが読む。
注意: 非公開リポジトリから GitHub Pages を公開できるかは、アカウントのプランに依存する(要確認)。公開できない場合は、アーティファクトの CSV・PNG を直接開く。

## 使い方(ローカル / PC)

Python 3.11 以上。

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENALEX_API_KEY=xxxx     # コードにも出力にも残らない

python -m openalex_trend validate --dry-run   # 推定リクエスト数だけ見る(通信しない)
python -m openalex_trend validate             # OR条件・フレーズ指定の検証 -> outputs/validation.json
python -m openalex_trend run                  # 集計 -> outputs/title_trend.csv, summary.json, title_trend_ratio.png
python -m openalex_trend sample               # 精度検証用サンプル -> outputs/samples/precision_samples.csv
python -m pytest -q                           # テスト(APIはモック)
```

ローカルでフロントを見る場合は、`outputs/` の結果を `frontend/data/` にコピーして配信する。

```bash
mkdir -p frontend/data && cp outputs/summary.json outputs/title_trend*.* frontend/data/
cd frontend && python -m http.server 8000     # http://localhost:8000
```

各コマンドは実行前に推定リクエスト数と推定費用を表示する(キャッシュ済みは除く)。
`union` 方式の `plan`・`run` は、ページ数の見積りのため語句ごとの件数取得(各1リクエスト)だけは先に通信する。

## 出力

- `title_trend.csv`: 縦持ち。列は `field, year, count, denominator, ratio, ratio_yoy, ratio_ma3`
  - `ratio_yoy` は比率の前年比成長率。前年の比率が 0 や欠損なら空欄
  - `ratio_ma3` は当該年を含む直近3年の単純平均(後ろ向き)。最新年を落とさないため中心化していない
- `title_trend_ratio.png`: 比率の折れ線(細線=年次、太線=3年移動平均)
- `summary.json`: フロント用。欠損は `null`
- `validation.json`, `samples/precision_samples.csv`: 検証用

## 設計判断とその理由

- **分野ラベリングはタイトル検索で行う。** OpenAlex Topics は粒度が粗く、SSM や階層ベイズ単体の Topic がないため。
- **タイトルに限定する。** アブストや全文には「前提として言及されただけの語句」が混入するため。全文での語句出現回数によるフィルタは、n-gram 機能が廃止されており使えない。
- **`search.title` を使う。** 旧形式の `title.search` フィルタは非推奨。同義語・表記揺れは OR 条件でまとめ、フレーズは二重引用符で囲む。
- **正規化する。** 比率 = 分子 / 分母。分子は分母と同じ母集団のうちタイトルが一致した論文数、分母は同一 subfield(既定は Statistics and Probability = `subfields/2613`)の年別論文数。OpenAlex の収録範囲の経年変化を相殺するため。
- **subfield は `primary_topic.subfield.id` で絞る。** 1論文に最大3つの Topic が付くため、`topics` 側で絞ると同じ論文が重複計上される。
- **`group_by=publication_year` で集計する。** `group_by` は1リクエストにつき1つまで。
- **OR が効かない場合の代替(`query_mode: union`)。** 語句ごとに cursor ページングで work ID を取得し、ID の和集合を取って年別に数える。
- **キャッシュ・リトライ・レート制御。** 応答は `data/cache/` に JSON で保存し、再実行で同じクエリを打たない。429/5xx は指数バックオフ(1, 2, 4…秒。`Retry-After` があれば尊重)。リクエスト間隔は毎秒30以内。リクエスト数が1日の予算(既定 $1 = 10,000 リクエスト)を超えそうなら通信前に中止する。
- **キーを残さない。** キーは環境変数からのみ読み、キャッシュ・例外メッセージ・出力に含めない(テストで確認済み)。

## 既知の限界

- OpenAlex は収録基準が緩く、論文以外の文書や質の低い記録も含まれる。
- Topic 分類は自動で、`primary_topic` の付与に誤りがある。分母(subfield)の定義はその影響を受ける。
- 主題なのにタイトルに語句がない論文は取りこぼす(再現率は低めになる)。逆に、語句がタイトルにあっても主題でない論文が混じる(適合率は `sample` の手ラベルで確認する)。
- 分野間の比率の大小は、語句の言い回しの幅(同義語の網羅度)に左右される。水準の比較より、各分野の時系列の形の比較に向く。
- 1日の予算チェックは1回の実行内の上限であり、複数回の実行をまたいだ合計は管理していない。

## 未検証の事項(要確認)

この開発環境では `api.openalex.org` に接続できなかったため、実 API では動かしていない。テストは API 応答のモックで通っている。次の点は実 API での確認が必要。

- `search.title` が OR・二重引用符のフレーズ指定を意図どおり解釈するか(`validate` で確認する。ここが最優先)
- `primary_topic.subfield.id:subfields/2613` の ID 形式が受理されるか
- 精度サンプラーが使う `sample` / `seed` パラメータ、`openalex:W1|W2` フィルタ(union 方式)の仕様
- 1リクエストあたりの費用(`config.yaml` の `cost_per_request_usd`。全文検索は単価が高いとされるが、`search.title` がどちらに当たるか)
- GitHub Actions ワークフローは一度も実行していない
