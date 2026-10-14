"""Local OCR, cached engines and observable Windows GPU → CPU fallback."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter

_LOCK = Lock()  # DirectML sessions must not run concurrently.
_ENGINES = {}
_GPU_FAILURE = ""


@dataclass(frozen=True)
class OcrResult:
    text: str
    device: str
    seconds: float
    fallback: str = ""


def _apple_recognize(png: bytes) -> str:
    import objc
    import Quartz
    import Vision
    from Foundation import NSData, NSDictionary

    with objc.autorelease_pool():
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(["zh-Hans", "en-US"])
        request.setUsesLanguageCorrection_(True)
        # Apple chooses GPU / Neural Engine / CPU; never force CPU-only.
        request.setUsesCPUOnly_(False)
        image_data = NSData.dataWithBytes_length_(png, len(png))
        image_source = Quartz.CGImageSourceCreateWithData(image_data, None)
        if image_source is None:
            raise RuntimeError("选区图片无效，请重新框选。")
        image = Quartz.CGImageSourceCreateImageAtIndex(image_source, 0, None)
        if image is None:
            raise RuntimeError("选区图片无效，请重新框选。")
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            image, NSDictionary.dictionary()
        )
        success, _error = handler.performRequests_error_([request], None)
        if not success:
            raise RuntimeError("本地文字识别失败，请重新框选清晰的文字。")
        lines = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                lines.append(str(candidates[0].string()))
        return "\n".join(lines).strip()


def _new_engine(provider: str):
    import onnxruntime as ort
    import rapidocr
    from omegaconf import flag_override

    # Version-pinned package ships these models; no downloads during capture.
    models = Path(rapidocr.__file__).parent / "models"
    paths = {
        "Det": models / "PP-OCRv6_det_small.onnx",
        "Cls": models / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "Rec": models / "PP-OCRv6_rec_small.onnx",
    }
    params = {f"{name}.model_path": str(path) for name, path in paths.items()}
    params["Global.log_level"] = "critical"
    engine = rapidocr.RapidOCR(params=params)
    for name, path in paths.items():
        if not path.is_file():
            raise RuntimeError("本地 OCR 模型缺失，请重新安装或打包应用。")
        options = ort.SessionOptions()
        options.log_severity_level = 4
        options.intra_op_num_threads = min(4, os.cpu_count() or 1)
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.enable_mem_pattern = provider != "DmlExecutionProvider"
        providers = [provider]
        if provider != "CPUExecutionProvider":
            providers.append("CPUExecutionProvider")
        session = ort.InferenceSession(str(path), sess_options=options, providers=providers)
        if session.get_providers()[0] != provider:
            raise RuntimeError("GPU 会话未启用")
        session.disable_fallback()  # Handle failures explicitly and label CPU fallback.
        # RapidOCR supports supplied sessions; allow native objects in its config.
        with flag_override(engine.cfg, "allow_objects", True):
            engine.cfg[name].session = session
    # Load all stages now so initialization is cached with the engine.
    engine._load_det_model()
    engine._load_cls_model()
    engine._load_rec_model()
    return engine


def _engine(provider):
    if provider not in _ENGINES:
        _ENGINES[provider] = _new_engine(provider)
    return _ENGINES[provider]


def _onnx_recognize(png: bytes, device: str):
    global _GPU_FAILURE
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError("请安装本地 OCR：pip install -e '.[ocr]'。") from exc
    with _LOCK:
        fallback = ""
        provider = "CPUExecutionProvider"
        if sys.platform == "win32" and device != "cpu":
            if _GPU_FAILURE:
                fallback = _GPU_FAILURE
            elif "DmlExecutionProvider" not in ort.get_available_providers():
                fallback = "没有可用的 GPU 后端，已自动使用 CPU"
            else:
                provider = "DmlExecutionProvider"
        try:
            result = _engine(provider)(png)
        except Exception:
            if provider == "CPUExecutionProvider":
                raise RuntimeError("本地 OCR 运行失败，请检查安装或重新框选。") from None
            _GPU_FAILURE = "GPU 初始化或识别失败，已自动使用 CPU"
            fallback = _GPU_FAILURE
            _ENGINES.pop(provider, None)
            provider = "CPUExecutionProvider"
            try:
                result = _engine(provider)(png)
            except Exception:
                raise RuntimeError("GPU 与 CPU 识别均失败，请检查本地 OCR 安装。") from None
        text = "\n".join(result.txts or ()).strip()
        actual = "GPU · DirectML" if provider == "DmlExecutionProvider" else "CPU"
        return text, actual, fallback


def recognize_details(png: bytes, device="auto") -> OcrResult:
    started = perf_counter()
    if sys.platform == "darwin":
        text, actual, fallback = _apple_recognize(png), "Apple Vision · 系统自动加速", ""
    else:
        text, actual, fallback = _onnx_recognize(png, device)
    return OcrResult(text, actual, perf_counter() - started, fallback)


def recognize(png: bytes) -> str:
    return recognize_details(png).text
