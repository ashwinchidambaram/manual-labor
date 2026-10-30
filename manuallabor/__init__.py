from manuallabor.telemetry import disable_library_telemetry as _disable_library_telemetry

__version__ = "0.1.0"

# before any submodule can import onnxruntime (design 06 section 4)
_disable_library_telemetry()
