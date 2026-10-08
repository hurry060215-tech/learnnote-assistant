"""One privacy-preserving initializer for all optional local OCR entry points."""
import os


def create_ocr_engine():
    os.environ["ORT_DISABLE_TELEMETRY"] = "1"
    import onnxruntime
    # Disable native platform telemetry before importing/creating OCR sessions.
    onnxruntime.disable_telemetry_events()
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
