import gzip
import lzma
import struct

import brotli
import lz4.block

GZIP_MAGIC: bytes = b"\x1f\x8b"
BROTLI_MAGIC: bytes = b"brotli"


# LZMA
def decompress_lzma(data: bytes, read_decompressed_size: bool = False) -> bytes:
    """decompresses lzma-compressed data

    :param data: compressed data
    :type data: bytes
    :raises _lzma.LZMAError: Compressed data ended before the end-of-stream marker was reached
    :return: uncompressed data
    :rtype: bytes
    """
    props, dict_size = struct.unpack("<BI", data[:5])
    lc = props % 9
    remainder = props // 9
    pb = remainder // 5
    lp = remainder % 5
    dec = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW,
        filters=[
            {
                "id": lzma.FILTER_LZMA1,
                "dict_size": dict_size,
                "lc": lc,
                "lp": lp,
                "pb": pb,
            }
        ],
    )
    data_offset = 13 if read_decompressed_size else 5
    return dec.decompress(data[data_offset:])


def compress_lzma(data: bytes, write_decompressed_size: bool = False) -> bytes:
    """compresses data via lzma (unity specific)
    The current static settings may not be the best solution,
    but they are the most commonly used values and should therefore be enough for the time being.

    :param data: uncompressed data
    :type data: bytes
    :return: compressed data
    :rtype: bytes
    """
    dict_size = 0x800000  # 1 << 23
    compressor = lzma.LZMACompressor(
        format=lzma.FORMAT_RAW,
        filters=[
            {
                "id": lzma.FILTER_LZMA1,
                "dict_size": dict_size,
                "lc": 3,
                "lp": 0,
                "pb": 2,
                "mode": lzma.MODE_NORMAL,
                "mf": lzma.MF_BT4,
                "nice_len": 123,
            }
        ],
    )

    compressed_data = compressor.compress(data) + compressor.flush()
    cdl = len(compressed_data)
    if write_decompressed_size:
        return struct.pack(f"<BIQ{cdl}s", 0x5D, dict_size, len(data), compressed_data)
    else:
        return struct.pack(f"<BI{cdl}s", 0x5D, dict_size, compressed_data)


# LZ4
def decompress_lz4(data: bytes, uncompressed_size: int) -> bytes:  # LZ4M/LZ4HC
    """decompresses lz4-compressed data

    :param data: compressed data
    :type data: bytes
    :param uncompressed_size: size of the uncompressed data
    :type uncompressed_size: int
    :raises _block.LZ4BlockError: Decompression failed: corrupt input or insufficient space in destination buffer.
    :return: uncompressed data
    :rtype: bytes
    """
    return lz4.block.decompress(data, uncompressed_size)

class LZ4:
    @classmethod
    def decompress(cls, cmp: bytes, decompressed_size: int) -> bytes:
        dec = bytearray(decompressed_size)
        cmpPos = 0
        decPos = 0

        while cmpPos < len(cmp) and decPos < decompressed_size:
            encCount, litCount, cmpPos = cls.get_literal_token(cmp, cmpPos)

            litCount, cmpPos = cls.get_length(litCount, cmp, cmpPos)

            # Copy literal chunk
            dec[decPos:decPos + litCount] = cmp[cmpPos:cmpPos + litCount]
            cmpPos += litCount
            decPos += litCount

            if cmpPos >= len(cmp):
                break

            # Get back-offset from compressed chunk
            back, cmpPos = cls.get_chunk_end(cmp, cmpPos)
            encCount, cmpPos = cls.get_length(encCount, cmp, cmpPos)
            encCount += 4

            encPos = decPos - back
            if encCount <= back:
                # Optimized block copy (if buffers don't overlap badly)
                dec[decPos:decPos + encCount] = dec[encPos:encPos + encCount]
                decPos += encCount
            else:
                # Copy byte by byte
                for _ in range(encCount):
                    dec[decPos] = dec[encPos]
                    decPos += 1
                    encPos += 1

        return bytes(dec[:decPos])

    @staticmethod
    def get_literal_token(cmp: bytes, cmpPos: int) -> tuple[int, int, int]:
        token = cmp[cmpPos]
        cmpPos += 1
        # In base LZ4, lower nibble is encoded length and higher nibble is literal length.
        encCount = token & 0x0F
        litCount = (token >> 4) & 0x0F
        return encCount, litCount, cmpPos

    @staticmethod
    def get_chunk_end(cmp: bytes, cmpPos: int) -> tuple[int, int]:
        # In base LZ4, first byte is low, second is high.
        low = cmp[cmpPos]
        high = cmp[cmpPos + 1]
        cmpPos += 2
        return (low | (high << 8)), cmpPos

    @staticmethod
    def get_length(length: int, cmp: bytes, cmpPos: int) -> tuple[int, int]:
        if length == 0xF:
            while True:
                extra = cmp[cmpPos]
                cmpPos += 1
                length += extra
                if extra != 0xFF:
                    break
        return length, cmpPos


class LZ4Inv(LZ4):
    @staticmethod
    def get_literal_token(cmp: bytes, cmpPos: int) -> tuple[int, int, int]:
        token = cmp[cmpPos]
        cmpPos += 1
        # For LZ4Inv, the nibble order is swapped:
        # higher nibble is encoded length, lower nibble is literal length.
        encCount = (token >> 4) & 0x0F
        litCount = token & 0x0F
        return encCount, litCount, cmpPos

    @staticmethod
    def get_chunk_end(cmp: bytes, cmpPos: int) -> tuple[int, int]:
        # For LZ4Inv, the order is reversed: first byte is high, second is low.
        high = cmp[cmpPos]
        low = cmp[cmpPos + 1]
        cmpPos += 2
        return ((high << 8) | low), cmpPos


# LZHAM
def decompress_lzham(data: bytes, uncompressed_size: int) -> bytes:
    return LZ4Inv.decompress(data, uncompressed_size)


def compress_lz4(data: bytes) -> bytes:  # LZ4M/LZ4HC
    """compresses data via lz4.block

    :param data: uncompressed data
    :type data: bytes
    :return: compressed data
    :rtype: bytes
    """
    return lz4.block.compress(
        data, mode="high_compression", compression=9, store_size=False
    )


# Brotli
def decompress_brotli(data: bytes) -> bytes:
    """decompresses brotli-compressed data

    :param data: compressed data
    :type data: bytes
    :raises brotli.error: BrotliDecompress failed
    :return: uncompressed data
    :rtype: bytes
    """
    return brotli.decompress(data)


def compress_brotli(data: bytes) -> bytes:
    """compresses data via brotli

    :param data: uncompressed data
    :type data: bytes
    :return: compressed data
    :rtype: bytes
    """
    return brotli.compress(data)


# GZIP
def decompress_gzip(data: bytes) -> bytes:
    """decompresses gzip-compressed data

    :param data: compressed data
    :type data: bytes
    :raises OSError: Not a gzipped file
    :return: uncompressed data
    :rtype: bytes
    """
    return gzip.decompress(data)


def compress_gzip(data: bytes) -> bytes:
    """compresses data via gzip
    The current static settings may not be the best solution,
    but they are the most commonly used values and should therefore be enough for the time being.

    :param data: uncompressed data
    :type data: bytes
    :return: compressed data
    :rtype: bytes
    """
    return gzip.compress(data)


def chunk_based_compress(data: bytes, block_info_flag: int) -> (bytes, list):
    """compresses AssetBundle data based on the block_info_flag
    LZ4/LZ4HC will be chunk-based compression

    :param data: uncompressed data
    :type data: bytes
    :param block_info_flag: block info flag
    :type block_info_flag: int
    :return: compressed data and block info
    :rtype: tuple
    """
    switch = block_info_flag & 0x3F
    if switch == 0:  # NONE
        return data, [(len(data), len(data), block_info_flag)]
    elif switch == 1:  # LZMA
        chunk_size = 0xFFFFFFFF
        compress_func = compress_lzma
    elif switch in [2, 3]:  # LZ4
        chunk_size = 0x00020000
        compress_func = compress_lz4
    elif switch == 4:  # LZHAM
        raise NotImplementedError
    block_info = []
    uncompressed_data_size = len(data)
    compressed_file_data = bytearray()
    p = 0
    while uncompressed_data_size > chunk_size:
        compressed_data = compress_func(data[p: p + chunk_size])
        if len(compressed_data) > chunk_size:
            compressed_file_data.extend(data[p: p + chunk_size])
            block_info.append(
                (
                    chunk_size,
                    chunk_size,
                    block_info_flag ^ switch,
                )
            )
        else:
            compressed_file_data.extend(compressed_data)
            block_info.append(
                (
                    chunk_size,
                    len(compressed_data),
                    block_info_flag,
                )
            )
        p += chunk_size
        uncompressed_data_size -= chunk_size
    if uncompressed_data_size > 0:
        compressed_data = compress_func(data[p:])
        if len(compressed_data) > uncompressed_data_size:
            compressed_file_data.extend(data[p:])
            block_info.append(
                (
                    uncompressed_data_size,
                    uncompressed_data_size,
                    block_info_flag ^ switch,
                )
            )
        else:
            compressed_file_data.extend(compressed_data)
            block_info.append(
                (
                    uncompressed_data_size,
                    len(compressed_data),
                    block_info_flag,
                )
            )
    return bytes(compressed_file_data), block_info
