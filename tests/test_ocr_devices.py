"""Device routing tests run without requiring a Windows GPU on the host."""

import sys
from types import SimpleNamespace

import pytest

import screen_study_assistant.ocr as ocr
from screen_study_assistant.config import ConfigStore, Settings


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(ocr.sys, "platform", "win32")
    monkeypatch.setattr(ocr, "_ENGINES", {})
    monkeypatch.setattr(ocr, "_GPU_FAILURE", "")
    runtime = SimpleNamespace(
        get_available_providers=lambda: ["DmlExecutionProvider", "CPUExecutionProvider"]
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", runtime)
    return runtime


def test_gpu_priority_and_engine_reuse(runtime, monkeypatch):
    builds = []

    def build(provider):
        builds.append(provider)
        return lambda image: SimpleNamespace(txts=("GPU recognized text",))

    monkeypatch.setattr(ocr, "_new_engine", build)
    for _ in range(2):
        result = ocr.recognize_details(b"image")
        assert result.device == "GPU · DirectML"
        assert result.text == "GPU recognized text"
        assert not result.fallback
    assert builds == ["DmlExecutionProvider"]


@pytest.mark.parametrize("failure", ["unavailable", "initialize", "inference"])
def test_gpu_unavailable_or_failure_uses_cpu(runtime, monkeypatch, failure):
    if failure == "unavailable":
        runtime.get_available_providers = lambda: ["CPUExecutionProvider"]
    attempts = []

    def build(provider):
        attempts.append(provider)
        if provider == "DmlExecutionProvider" and failure == "initialize":
            raise RuntimeError("GPU unavailable")

        def run(image):
            if provider == "DmlExecutionProvider":
                raise RuntimeError("GPU run failure")
            return SimpleNamespace(txts=("CPU result",))

        return run

    monkeypatch.setattr(ocr, "_new_engine", build)
    result = ocr.recognize_details(b"image")
    assert result.text == "CPU result"
    assert result.device == "CPU"
    assert "CPU" in result.fallback
    ocr.recognize_details(b"image")
    assert attempts.count("CPUExecutionProvider") == 1
    assert attempts.count("DmlExecutionProvider") <= 1


def test_cpu_choice_never_attempts_gpu(runtime, monkeypatch):
    providers = []
    monkeypatch.setattr(
        ocr, "_new_engine", lambda p: providers.append(p) or (lambda _: SimpleNamespace(txts=()))
    )
    result = ocr.recognize_details(b"image", "cpu")
    assert providers == ["CPUExecutionProvider"]
    assert result.text == ""
    assert result.device == "CPU"
    assert not result.fallback


def test_ocr_preference_persists_without_model_config(tmp_path):
    store = ConfigStore(tmp_path)
    settings = Settings(ocr_device="cpu")
    store.save(settings)
    assert store.load().ocr_device == "cpu"
    with pytest.raises(ValueError, match="OCR"):
        Settings(ocr_device="invalid").validate()


def test_directml_session_options_and_silent_provider_fallback(tmp_path, monkeypatch):
    from contextlib import nullcontext

    models = tmp_path / "models"
    models.mkdir()
    for name in (
        "PP-OCRv6_det_small.onnx",
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "PP-OCRv6_rec_small.onnx",
    ):
        (models / name).write_bytes(b"test fixture")
    cfg = {stage: SimpleNamespace() for stage in ("Det", "Cls", "Rec")}
    engine = SimpleNamespace(
        cfg=cfg,
        _load_det_model=lambda: None,
        _load_cls_model=lambda: None,
        _load_rec_model=lambda: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "rapidocr",
        SimpleNamespace(__file__=str(tmp_path / "__init__.py"), RapidOCR=lambda params: engine),
    )
    monkeypatch.setitem(
        sys.modules, "omegaconf", SimpleNamespace(flag_override=lambda *_: nullcontext())
    )
    sessions = []
    available = ["DmlExecutionProvider", "CPUExecutionProvider"]

    def create(path, sess_options, providers):
        assert sess_options.enable_mem_pattern is False
        assert sess_options.execution_mode == "sequential"
        assert providers == ["DmlExecutionProvider", "CPUExecutionProvider"]
        sessions.append(path)
        return SimpleNamespace(get_providers=lambda: available, disable_fallback=lambda: None)

    runtime = SimpleNamespace(
        SessionOptions=SimpleNamespace,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
        InferenceSession=create,
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", runtime)
    assert ocr._new_engine("DmlExecutionProvider") is engine
    assert len(sessions) == 3
    assert all(hasattr(cfg[name], "session") for name in ("Det", "Cls", "Rec"))
    available = ["CPUExecutionProvider"]
    with pytest.raises(RuntimeError, match="GPU"):
        ocr._new_engine("DmlExecutionProvider")
