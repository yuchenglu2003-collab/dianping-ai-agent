from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.tools._data_io import load_analysis_frame_from_ctx, resolve_tool_input_path
from src.tools.base import BaseTool, ToolResult


class RatingPredictTool(BaseTool):
    name = "rating_predict"
    description = "基于评论文本的评分预测：TF-IDF + NB/RF/HGB 对比"

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        try:
            from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics import accuracy_score, f1_score
            from sklearn.model_selection import train_test_split
            from sklearn.naive_bayes import MultinomialNB
            from sklearn.pipeline import Pipeline
        except ImportError as e:
            return ToolResult(success=False, error=f"缺少 scikit-learn: {e}")

        input_path = resolve_tool_input_path(ctx, kwargs)
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到数据: {input_path}")

        df = load_analysis_frame_from_ctx(ctx, input_path)
        if "content" not in df.columns or "score" not in df.columns:
            return ToolResult(success=False, error="评分预测需要 content 与 score 字段")

        threshold = float(ctx.params.get("positive_threshold", 4))
        work = df[["content", "score"]].copy()
        work["score"] = pd.to_numeric(work["score"], errors="coerce")
        work["content"] = work["content"].fillna("").astype(str).str.strip()
        work = work.dropna(subset=["score"])
        work = work[work["content"].str.len() >= 2]
        work["label"] = (work["score"] >= threshold).astype(int)

        # 控制云端内存/时间
        max_rows = int(kwargs.get("max_rows") or 20000)
        if len(work) > max_rows:
            work = work.sample(n=max_rows, random_state=int(ctx.config.get("project", {}).get("seed", 42)))

        if work["label"].nunique() < 2 or len(work) < 50:
            return ToolResult(success=False, error="有效样本不足或标签单一，无法训练")

        x_train, x_test, y_train, y_test = train_test_split(
            work["content"],
            work["label"],
            test_size=0.2,
            random_state=42,
            stratify=work["label"],
        )

        models = {
            "naive_bayes": Pipeline(
                [
                    ("tfidf", TfidfVectorizer(max_features=8000, ngram_range=(1, 2), min_df=2)),
                    ("clf", MultinomialNB()),
                ]
            ),
            "random_forest": Pipeline(
                [
                    ("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1, 2), min_df=2)),
                    ("clf", RandomForestClassifier(n_estimators=80, max_depth=18, n_jobs=-1, random_state=42)),
                ]
            ),
        }
        # HGB 需要 dense，单独路径
        from sklearn.decomposition import TruncatedSVD
        from sklearn.preprocessing import FunctionTransformer

        models["hist_gb"] = Pipeline(
            [
                ("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1, 2), min_df=2)),
                ("svd", TruncatedSVD(n_components=80, random_state=42)),
                ("clf", HistGradientBoostingClassifier(max_depth=6, max_iter=80, random_state=42)),
            ]
        )

        rows = []
        best_name = None
        best_f1 = -1.0
        best_pipe = None
        for name, pipe in models.items():
            pipe.fit(x_train, y_train)
            pred = pipe.predict(x_test)
            acc = float(accuracy_score(y_test, pred))
            f1 = float(f1_score(y_test, pred, average="weighted"))
            rows.append({"model": name, "accuracy": acc, "f1_weighted": f1})
            if f1 > best_f1:
                best_f1 = f1
                best_name = name
                best_pipe = pipe

        cmp_df = pd.DataFrame(rows).sort_values("f1_weighted", ascending=False)
        out_dir = Path(ctx.paths.get("features", ctx.project_root / "data" / "features"))
        out_dir.mkdir(parents=True, exist_ok=True)
        cmp_path = out_dir / f"{ctx.run_id}_model_compare.csv"
        cmp_df.to_csv(cmp_path, index=False)

        model_dir = Path(ctx.config["paths"].get("artifacts", ctx.project_root / "artifacts")) / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / f"{ctx.run_id}_best_rating_model.joblib"
        try:
            import joblib

            joblib.dump({"model": best_pipe, "threshold": threshold, "name": best_name}, model_path)
        except Exception:
            model_path = Path("")

        report = ctx.artifact_store.report_path("rating_model")
        lines = [
            "# 评分预测模型对比",
            "",
            f"- 正类定义: score >= {threshold}",
            f"- 样本数: {len(work)}",
            f"- 最佳模型: {best_name} (F1={best_f1:.4f})",
            "",
            "## 对比表",
            "",
            cmp_df.to_markdown(index=False) if hasattr(cmp_df, "to_markdown") else cmp_df.to_string(index=False),
        ]
        report.write_text("\n".join(lines), encoding="utf-8")

        metrics = {
            "rating_model_best": best_name or "",
            "rating_model_best_f1": best_f1,
            "rating_model_best_acc": float(cmp_df.iloc[0]["accuracy"]) if len(cmp_df) else 0.0,
            "rating_model_samples": int(len(work)),
        }
        for _, r in cmp_df.iterrows():
            metrics[f"model_acc_{r['model']}"] = float(r["accuracy"])
            metrics[f"model_f1_{r['model']}"] = float(r["f1_weighted"])

        outputs = {
            "model_compare": str(cmp_path),
            "rating_model_report": str(report),
        }
        if model_path and model_path.exists():
            outputs["rating_model"] = str(model_path)

        return ToolResult(success=True, outputs=outputs, metrics=metrics, message=f"模型对比完成，最佳={best_name}")
