"""LearnNote Assistant backend."""

import os

# Native ONNX telemetry starts at library initialization; API opt-out alone is
# too late on non-Windows. Set the process-lifetime opt-out before model imports.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

APP_VERSION = "0.2.14"
API_VERSION = 1
UX_PROTOCOL_VERSION = 1
TASK_SCHEMA_VERSION = 1
