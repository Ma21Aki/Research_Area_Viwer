# 将来拡張(今回は未実装。TODO のみ)

- `state_space/`: 比率の時系列に状態空間モデルを当て、上昇中かを判定する
- `llm_classifier/`: 母集団の精度が不足した場合に、アブストを LLM で「主題 / 前提」に分類する

どちらも `outputs/`(CSV・JSON)を入力とし、`backend/openalex_trend` の内部には依存させない。
