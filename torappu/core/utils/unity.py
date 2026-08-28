import lz4inv
from UnityPy.enums.BundleFile import CompressionFlags
from UnityPy.helpers.CompressionHelper import DECOMPRESSION_MAP


def install_unity_patches() -> None:
    """Teach UnityPy about the custom compression HG ships.

    Must run before any ``UnityPy.load()``; idempotent, so every entrypoint
    that touches asset bundles can call it.
    """
    # 2.5.04 25-04-03-14-16-11_4f0a01
    DECOMPRESSION_MAP[CompressionFlags.LZHAM] = lz4inv.decompress_buffer
