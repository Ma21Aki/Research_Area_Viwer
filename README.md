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

バックエンドとフロントエンドは `outputs/`(`dashboard.json`・CSV・PNG)のファイルだけでつながる。
フロントはバックエンドのコードに依存しないため、将来 PC 版を作る場合も同じ出力を読めばよい。

## 使い方(iPhone だけで完結させる場合)

1. GitHub のリポジトリ設定 → Secrets and variables → Actions で `OPENALEX_API_KEY` を登録する(キーは https://openalex.org/settings/api で無料取得)。
2. Actions タブ → `analyze` → Run workflow。最初は `validate`(クエリ検証)を選ぶ。
3. `results` ブランチの `latest/validation.json` で OR 条件・フレーズ指定が効いているか確認する。
4. `run` を選んで実行すると、集計結果が `outputs` アーティファクトと、`results` ブランチの `latest/` に出る(スマホでは GitHub アプリで `results` ブランチを開くと CSV・PNG を直接見られる)。`publish_pages` をオンにした場合だけ GitHub Pages に公開される(公開範囲を確認してから)。公開された URL を Safari で開き、共有ボタン →「ホーム画面に追加」でアイコンから起動できる。
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
python -m openalex_trend run                  # 集計 -> outputs/dashboard.json, title_trend.csv, topic_metrics.csv, title_trend_ratio.png
python -m openalex_trend diagnose             # 一致論文の subfield 分布 -> outputs/subfield_distribution.csv
python -m openalex_trend sample               # 精度検証用サンプル -> outputs/samples/precision_samples.csv
python -m pytest -q                           # テスト(APIはモック)
```

ローカルでフロントを見る場合は、`outputs/` の結果を `frontend/data/` にコピーして配信する。

```bash
mkdir -p frontend/data && cp outputs/dashboard.json frontend/data/
cd frontend && python -m http.server 8000     # http://localhost:8000
```

各コマンドは実行前に推定リクエスト数と推定費用を表示する(キャッシュ済みは除く)。
`plan`・`run` は、未取得の語句について件数取得(各1リクエスト)だけは先に通信してページ数を見積もる。

## ダッシュボード(インタラクティブ)

トピック(複数)の折れ線を、検索の再実行なしに画面で切り替えられる。

- **指標:** 出現率 / 論文数 / 被引用数(その年に受けた) / 被引用÷論文(出版年別の累計) / FWCI / 上位10%率。FWCI と上位10%率は、OpenAlex の応答に値がなければ選べなくなる
- **集計範囲(分母):** 全論文 / Mathematics(field) / Statistics and Probability(subfield)。出現率と論文数に効く
- **表示:** 年次 / 3年平均、トピックの表示・非表示、タップで年ごとの値を表示
- **検出語句:** トピックごとの語句(OR)と、語句別の件数

出現率・移動平均は画面側で計算する。バックエンドは、論文単位の取得結果から全指標を手元で集計して `dashboard.json` に出す。

## トピックの追加とキャッシュ

`backend/config.yaml` の `fields` に項目を足して `run` を実行するだけでよい。語句ごとの取得結果(各ページ)を `data/cache/` に残しており、既存トピックは再検索せず、新しい語句の分だけ取得する(既存トピックに語句を足したときも同様)。分母(3水準)は各1リクエストで、これもキャッシュされる。Actions では `actions/cache` で実行間にキャッシュを引き継ぐ。
語句の表記だけが違うもの(ハイフン・大小・空白)は同一視して1回だけ取得する。

## 出力

- `dashboard.json`: フロント用。素の件数と指標、分母の3水準。欠損は `null`
- `topic_metrics.csv`: トピック×年の全指標(件数3種・分母3種・出現率3種・被引用の指標)
- `title_trend.csv`: 既定の分母での縦持ち。列は `field, year, count, denominator, ratio, ratio_yoy, ratio_ma3`
  - `ratio_yoy` は比率の前年比成長率。前年の比率が 0 や欠損なら空欄
  - `ratio_ma3` は当該年を含む直近3年の単純平均(後ろ向き)。最新年を落とさないため中心化していない
- `title_trend_ratio.png`: 比率の折れ線(細線=年次、太線=3年移動平均)
- `validation.json`, `subfield_distribution.csv`, `samples/precision_samples.csv`: 検証用

被引用の指標の定義:
- 「その年に受けた被引用数」は、一致した論文の `counts_by_year`(引用された年別)を足したもの。年別の内訳が取れていない年は 0 ではなく欠損にする
- 「被引用÷論文」は出版年ごとの累計被引用の平均で、新しい論文ほど不利になる
- 今年(途中経過)の値は、画面で白抜きの点で示す

## 設計判断とその理由

- **母集団は全論文を既定にし、分母を切り替えられるようにする。** 診断(`diagnose`)で、タイトル一致論文のうち Statistics and Probability に主分類されるのは SSM で 8%、Gaussian process で 4%、Variational inference で 15% にすぎないと分かった(Hierarchical Bayes 28%、Causal inference 49%)。subfield に絞ると分野間の比較が歪むため、全論文・field・subfield を画面で切り替える。論文種別(`type:article`)でも絞る。
- **分野ラベリングはタイトル検索で行う。** OpenAlex Topics は粒度が粗く、SSM や階層ベイズ単体の Topic がないため。
- **タイトルに限定する。** アブストや全文には「前提として言及されただけの語句」が混入するため。全文での語句出現回数によるフィルタは、n-gram 機能が廃止されており使えない。
- **`search.title` を使う。** 旧形式の `title.search` フィルタは非推奨。同義語・表記揺れは OR 条件でまとめ、フレーズは二重引用符で囲む。
- **正規化する。** 比率 = 分子 / 分母。分子は分母と同じ母集団のうちタイトルが一致した論文数、分母はその母集団の年別論文数。OpenAlex の収録範囲の経年変化を相殺するため。
- **subfield は `primary_topic.subfield.id` で絞る。** 1論文に最大3つの Topic が付くため、`topics` 側で絞ると同じ論文が重複計上される。
- **`group_by=publication_year` で集計する。** `group_by` は1リクエストにつき1つまで。
- **語句ごとに取得して work ID で和集合を取る。** OR 条件の動作は検証済みだが、語句ごとのキャッシュ(トピックや語句の追加で再検索しない)と、被引用の指標を論文単位で集計するために、語句ごとに cursor ページングで取得して和集合を取る。
- **キャッシュ・リトライ・レート制御。** 応答は `data/cache/` に JSON で保存し、再実行で同じクエリを打たない。429/5xx は指数バックオフ(1, 2, 4…秒。`Retry-After` があれば尊重)。リクエスト間隔は毎秒30以内。リクエスト数が1日の予算(既定 $1 = 10,000 リクエスト)を超えそうなら通信前に中止する。
- **キーを残さない。** キーは環境変数からのみ読み、キャッシュ・例外メッセージ・出力に含めない(テストで確認済み)。

## 既知の限界

- OpenAlex は収録基準が緩く、論文以外の文書や質の低い記録も含まれる。
- Topic 分類は自動で、`primary_topic` の付与に誤りがある。分母(subfield)の定義はその影響を受ける。
- 主題なのにタイトルに語句がない論文は取りこぼす(再現率は低めになる)。逆に、語句がタイトルにあっても主題でない論文が混じる(適合率は `sample` の手ラベルで確認する)。
- 分野間の比率の大小は、語句の言い回しの幅(同義語の網羅度)に左右される。水準の比較より、各分野の時系列の形の比較に向く。
- 被引用の指標は、一致した論文を全件取得して集計する(件数が多い語句ほどリクエストが増える)。`counts_by_year` が遡れる年数は OpenAlex の仕様に依存する(要確認)。
- 1日の予算チェックは1回の実行内の上限であり、複数回の実行をまたいだ合計は管理していない。

## 未検証の事項(要確認)

この開発環境では `api.openalex.org` に接続できなかったため、実 API では動かしていない。テストは API 応答のモックで通っている。次の点は実 API での確認が必要。

- `search.title` が OR・二重引用符のフレーズ指定を意図どおり解釈するか(`validate` で確認する。ここが最優先)
- `primary_topic.subfield.id:subfields/2613` の ID 形式が受理されるか
- `type:article` フィルタ、`select` に指定する `counts_by_year` / `fwci` / `citation_normalized_percentile`(値が無い場合は欠損として扱う)
- 1リクエストあたりの費用(`config.yaml` の `cost_per_request_usd`。全文検索は単価が高いとされるが、`search.title` がどちらに当たるか)
- GitHub Actions ワークフローは一度も実行していない
