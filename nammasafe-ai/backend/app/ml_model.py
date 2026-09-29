"""Optional ML model registry for the risk engine.

ASSESSMENT_MODE controls behaviour:
  rule_based -> weighted-rule score only (the platform's default source of truth)
  hybrid     -> the rule score, with the model score attached when one is loaded
  ml         -> model score is primary; transparently falls back to the
                rule-based score whenever no model is configured so the platform
                never goes silent or fabricates an ML prediction

Model providers are optional dependencies:
  ONNXRuntimeProvider -> *.onnx model file at ML_MODEL_PATH
  SklearnProvider      -> joblib pickled sklearn model/dir at ML_MODEL_PATH

Without a package or configured path the registry reports model_status
"NOT_CONFIGURED" and the engine carries on with rules only.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from app import config


def model_status_summary(registry: "ModelRegistry") -> str:
    return registry.model_status


class BaseModelProvider:
    name: str = "base"

    def predict(self, features: Dict[str, Any]) -> float:
        raise NotImplementedError


class ONNXRuntimeProvider(BaseModelProvider):
    name = "ONNX Runtime"

    def __init__(self, model_path: str) -> None:
        self._path = model_path
        import onnxruntime as ort  # type: ignore

        self._session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._features = [inp.name for inp in self._session.get_inputs()]

    def predict(self, features: Dict[str, Any]) -> float:
        names = [name for name in self._features if name in features]
        inputs = {name: features.get(name) for name in names}
        if not inputs:
            raise ValueError("Model feature names do not match available inputs")
        output = self._session.run(None, inputs)[0]
        return float(max(0.0, min(100.0, float(output.reshape(-1)[0])) ))


class SklearnProvider(BaseModelProvider):
    name = "scikit-learn"

    def __init__(self, model_path: str) -> None:
        self._path = model_path
        import joblib  # type: ignore

        self._model = joblib.load(model_path)

    def predict(self, features: Dict[str, Any]) -> float:
        # Simple ordered-feature contract: the model is responsible for the
        # feature vector order (documented in ARCHITECTURE.md).
        ordered = [features.get(name, 0.0) for name in ("rainfall", "water", "elevation", "historical", "proximity", "field_damage")]
        value = float(self._model.predict([ordered])[0] if hasattr(self._model, "predict") else self._model.transform([ordered])[0])
        return max(0.0, min(100.0, value))


class ModelRegistry:
    def __init__(self, mode: Optional[str] = None, model_path: Optional[str] = None) -> None:
        self.mode = (mode or config.ASSESSMENT_MODE).lower()
        self._configured_path = (model_path if model_path is not None else config.ML_MODEL_PATH) or ""
        self._provider: Optional[BaseModelProvider] = None
        self._load_error: Optional[str] = None
        self._load_attempted = False

    def _load(self) -> None:
        if self._load_attempted:
            return
        self._load_attempted = True
        path = self._configured_path
        if not path or not os.path.exists(path):
            self._load_error = f"ML_MODEL_PATH not configured or missing ({path or '<empty>'})"
            return
        try:
            if path.lower().endswith(".onnx"):
                from onnxruntime import InferenceSession  # noqa: F401

                self._provider = ONNXRuntimeProvider(path)
            else:
                import joblib  # noqa: F401

                self._provider = SklearnProvider(path)
        except Exception as exc:  # pragma: no cover - optional deps
            self._load_error = f"Model could not be loaded: {exc}"

    @property
    def model_status(self) -> str:
        if self.mode == "rule_based":
            return "RULE_BASED"
        if self._provider is None:
            return "NOT_CONFIGURED"
        return "LOADED"

    @property
    def model_version(self) -> Optional[str]:
        if self._provider is None:
            return None
        return f"{self._provider.name}@{os.path.basename(self._configured_path)}"

    def predict(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Return {"risk_score", "model_status", "model_version",
        "prediction_timestamp", "input_data_timestamp"} or a NOT_CONFIGURED dict."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._load()
        if self._provider is None:
            return {
                "risk_score": None,
                "model_status": self.model_status,
                "model_version": None,
                "prediction_timestamp": now,
                "input_data_timestamp": features.get("_input_timestamp", now),
            }
        try:
            score = self._provider.predict(features)
        except Exception as exc:  # pragma: no cover - model runtime failures
            return {
                "risk_score": None,
                "model_status": f"ERROR: {exc}",
                "model_version": None,
                "prediction_timestamp": now,
                "input_data_timestamp": features.get("_input_timestamp", now),
            }
        return {
            "risk_score": round(score, 1),
            "model_status": self.model_status,
            "model_version": self.model_version,
            "prediction_timestamp": now,
            "input_data_timestamp": features.get("_input_timestamp", now),
        }


model_registry = ModelRegistry()