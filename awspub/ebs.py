import base64
import concurrent.futures
import hashlib
import logging
import os
import struct
import time
import zlib
from typing import Iterator, Optional, Sequence, Set, Tuple, Union

import boto3
from botocore.config import Config
from mypy_boto3_ebs.client import EBSClient
from mypy_boto3_ebs.type_defs import TagTypeDef

from awspub import exceptions
from awspub.context import Context

logger = logging.getLogger(__name__)

# EBS direct APIs work on fixed 512 KiB blocks (see PutSnapshotBlock)
BLOCK_SIZE = 512 * 1024

# a sparse vmdk starts with the magic "KDMV" (little endian representation of 0x564D4B00)
VMDK_MAGIC = b"KDMV"

_SECTOR_SIZE = 512
# vmdk sparse extent flags
_VMDK_FLAG_RGD = 1 << 1
_VMDK_FLAG_ZERO_GRAIN = 1 << 2
_VMDK_FLAG_COMPRESSED = 1 << 16
_VMDK_FLAG_MARKER = 1 << 17
# grain table entry that marks an explicit zeroed grain (only if _VMDK_FLAG_ZERO_GRAIN is set)
_VMDK_GTE_ZEROED = 0x1
# the u16 "compressAlgorithm" field of the sparse header uses this value for deflate
_VMDK_COMPRESSION_DEFLATE = 1
# sector offset of the u16 "compressAlgorithm" field within the 512 byte sparse extent header
_VMDK_COMPRESS_ALGORITHM_OFFSET = 77


def _is_vmdk(path: str) -> bool:
    """
    Check if the given file is a (sparse) vmdk by its magic.

    Descriptor-based vmdks are unsupported; other files are treated as raw disk images.

    :param path: the path to the source image
    :type path: str
    :return: True if the file is a vmdk, otherwise False
    :rtype: bool
    """
    with open(path, "rb") as f:
        header = f.read(_SECTOR_SIZE)
    if header.lstrip().startswith(b"# Disk DescriptorFile"):
        raise exceptions.InvalidSourceImageException(
            f"unsupported vmdk in '{path}': descriptor-based images are not supported"
        )
    return header.startswith(VMDK_MAGIC)


class RawBlockSource:
    """
    Streams the non-zero 512 KiB blocks of a raw disk image
    """

    def __init__(self, path: str):
        """
        :param path: the path to the raw disk image
        :type path: str
        """
        self._path = path
        size = os.path.getsize(path)
        if size == 0:
            raise exceptions.InvalidSourceImageException(f"source image '{path}' is empty")
        self.volume_size_gib: int = max(1, -(-size // (1024**3)))

    def blocks(self) -> Iterator[Tuple[int, bytes]]:
        """
        Yield (block_index, block_data) tuples for every non-zero 512 KiB block of the image.
        Blocks never yielded read back as zeros (which is what a snapshot does for blocks
        that are never written via PutSnapshotBlock). The last block of the image is padded
        with zeros to the full 512 KiB block size.

        :return: iterator of (block_index, block_data) tuples; block_data is always BLOCK_SIZE bytes
        :rtype: Iterator[Tuple[int, bytes]]
        """
        zeros = bytes(BLOCK_SIZE)
        block_index = 0
        with open(self._path, "rb") as f:
            while True:
                chunk = f.read(BLOCK_SIZE)
                if not chunk:
                    break
                # pad before checking so an all-zero partial block is skipped too
                chunk = chunk.ljust(BLOCK_SIZE, b"\x00")
                if chunk != zeros:
                    yield block_index, chunk
                block_index += 1


class VmdkBlockSource:
    """
    Streams the non-zero 512 KiB blocks of a sparse (monolithic-sparse or streamOptimized)
    vmdk image by parsing its grain directory / grain tables and inflating compressed grains
    on the fly. No external tooling is needed and the image is never fully materialized.
    """

    def __init__(self, path: str):
        """
        :param path: the path to the vmdk image
        :type path: str
        """
        self._path = path
        with open(path, "rb") as f:
            header = f.read(_SECTOR_SIZE)
        if len(header) < _SECTOR_SIZE:
            raise exceptions.InvalidSourceImageException(f"'{path}' is not a valid vmdk (truncated header)")
        if header[: len(VMDK_MAGIC)] != VMDK_MAGIC:
            raise exceptions.InvalidSourceImageException(f"'{path}' is not a valid vmdk (bad magic)")

        (
            _magic,
            version,
            flags,
            capacity_sectors,
            grain_size_sectors,
            descriptor_offset_sectors,
            descriptor_size_sectors,
            num_gtes_per_gt,
            rgd_offset_sectors,
            gd_offset_sectors,
            _overhead_sectors,
            _unclean,
        ) = struct.unpack_from("<IIIQQQQiQQQB", header, 0)

        if version > 3:
            raise exceptions.InvalidSourceImageException(f"unsupported vmdk version '{version}' in '{path}'")
        if capacity_sectors <= 0:
            raise exceptions.InvalidSourceImageException(f"invalid capacity in vmdk header of '{path}'")
        if grain_size_sectors <= 0:
            raise exceptions.InvalidSourceImageException(f"invalid grain size in vmdk header of '{path}'")

        # the u16 "compressAlgorithm" field decides whether grains are deflate compressed
        # (this mirrors how qemu interprets the header)
        (compress_algorithm,) = struct.unpack_from("<H", header, _VMDK_COMPRESS_ALGORITHM_OFFSET)
        self._compressed = compress_algorithm == _VMDK_COMPRESSION_DEFLATE
        self._has_marker = bool(flags & _VMDK_FLAG_MARKER)
        self._has_zero_grain = bool(flags & _VMDK_FLAG_ZERO_GRAIN)

        # only single extent vmdks (monolithicSparse/streamOptimized) are supported. A descriptor
        # with more than one extent entry ("RW ...") references additional extent files
        descriptor = b""
        if descriptor_offset_sectors and descriptor_size_sectors:
            with open(path, "rb") as f:
                f.seek(descriptor_offset_sectors * _SECTOR_SIZE)
                descriptor = f.read(int(descriptor_size_sectors) * _SECTOR_SIZE)
        rw_lines = [line for line in descriptor.decode("utf-8", "replace").splitlines() if line.startswith("RW ")]
        if len(rw_lines) != 1:
            raise exceptions.InvalidSourceImageException(
                f"unsupported vmdk in '{path}': expected exactly 1 extent in the descriptor, found {len(rw_lines)}"
            )
        if b"parentFileNameHint" in descriptor:
            raise exceptions.InvalidSourceImageException(
                f"unsupported vmdk in '{path}': linked clones (parent vmdk) are not supported"
            )

        # the primary grain directory is used; fall back to the redundant one (see _VMDK_FLAG_RGD)
        gd_offset_sectors = gd_offset_sectors or rgd_offset_sectors
        if not gd_offset_sectors:
            raise exceptions.InvalidSourceImageException(f"no grain directory found in vmdk '{path}'")

        self._capacity_sectors = capacity_sectors
        self._grain_size_sectors = grain_size_sectors
        self._num_gtes_per_gt = num_gtes_per_gt
        self._gd_offset_sectors = gd_offset_sectors

        self._grain_size_bytes = grain_size_sectors * _SECTOR_SIZE
        self._num_grains = -(-capacity_sectors // grain_size_sectors)
        self._num_gts = -(-self._num_grains // num_gtes_per_gt)
        self.volume_size_gib = max(1, -(-int(capacity_sectors * _SECTOR_SIZE) // (1024**3)))

    def _grains(self) -> Iterator[Optional[bytes]]:
        """
        Yield the content of every grain in the image in order (grain 0, 1, 2, ...).
        Grains that are not allocated (grain table entry 0 or the explicit zeroed marker) are
        yielded as None which means "all zeros".

        :return: iterator of grain content; None means an all-zero grain
        :rtype: Iterator[Optional[bytes]]
        """
        with open(self._path, "rb") as f:
            f.seek(self._gd_offset_sectors * _SECTOR_SIZE)
            gd_bytes = f.read(self._num_gts * 4)
            if len(gd_bytes) < self._num_gts * 4:
                raise exceptions.InvalidSourceImageException(f"truncated grain directory in vmdk '{self._path}'")
            gd = struct.unpack(f"<{self._num_gts}I", gd_bytes)
            gt_index = -1
            gt: Tuple[int, ...] = ()
            for grain_index in range(self._num_grains):
                current_gt_index = grain_index // self._num_gtes_per_gt
                if current_gt_index != gt_index:
                    gt_index = current_gt_index
                    gt_offset_sectors = gd[gt_index]
                    if not gt_offset_sectors:
                        # the whole grain table is unallocated: all its grains are zeros
                        gt = ()
                    else:
                        f.seek(gt_offset_sectors * _SECTOR_SIZE)
                        gt_bytes = f.read(self._num_gtes_per_gt * 4)
                        if len(gt_bytes) < self._num_gtes_per_gt * 4:
                            raise exceptions.InvalidSourceImageException(
                                f"truncated grain table in vmdk '{self._path}'"
                            )
                        gt = struct.unpack(f"<{self._num_gtes_per_gt}I", gt_bytes)

                if not gt:
                    yield None
                    continue
                gt_entry = gt[grain_index % self._num_gtes_per_gt]
                if gt_entry == 0 or (self._has_zero_grain and gt_entry == _VMDK_GTE_ZEROED):
                    # unallocated or explicitly zeroed grain
                    yield None
                    continue

                f.seek(gt_entry * _SECTOR_SIZE)
                expected_len = min(
                    self._grain_size_bytes, self._capacity_sectors * _SECTOR_SIZE - grain_index * self._grain_size_bytes
                )
                if self._compressed:
                    if self._has_marker:
                        # grain record: 8 byte lba + 4 byte compressed size + compressed data
                        # (see VmdkGrainMarker in qemu block/vmdk.c)
                        marker_bytes = f.read(12)
                        if len(marker_bytes) < 12:
                            raise exceptions.InvalidSourceImageException(
                                f"truncated grain marker in vmdk '{self._path}'"
                            )
                        _lba, compressed_size = struct.unpack("<QI", marker_bytes)
                    else:
                        compressed_size = self._grain_size_bytes
                    compressed_data = f.read(compressed_size)
                    if self._has_marker and len(compressed_data) != compressed_size:
                        raise exceptions.InvalidSourceImageException(
                            f"truncated compressed grain {grain_index} in vmdk '{self._path}'"
                        )
                    d = zlib.decompressobj()
                    try:
                        data = d.decompress(compressed_data, self._grain_size_bytes + 1)
                    except zlib.error as e:
                        raise exceptions.InvalidSourceImageException(
                            f"can not decompress grain {grain_index} in vmdk '{self._path}': {e}"
                        )
                    if len(data) > self._grain_size_bytes:
                        raise exceptions.InvalidSourceImageException(
                            f"grain {grain_index} in vmdk '{self._path}' exceeds the grain size"
                        )
                    if not d.eof:
                        raise exceptions.InvalidSourceImageException(
                            f"incomplete compressed grain {grain_index} in vmdk '{self._path}'"
                        )
                    if len(data) < expected_len:
                        raise exceptions.InvalidSourceImageException(
                            f"grain {grain_index} in vmdk '{self._path}' decompressed to {len(data)} bytes "
                            f"but expected {expected_len}"
                        )
                    yield data[:expected_len]
                else:
                    data = f.read(expected_len)
                    if len(data) < expected_len:
                        raise exceptions.InvalidSourceImageException(
                            f"grain {grain_index} in vmdk '{self._path}' is truncated"
                        )
                    yield data

    def blocks(self) -> Iterator[Tuple[int, bytes]]:
        """
        Yield (block_index, block_data) tuples for every non-zero 512 KiB block of the image.
        Grains are assembled in order into 512 KiB blocks; unwritten parts of a block are zeros.
        The last block of the image is padded with zeros to the full 512 KiB block size.

        :return: iterator of (block_index, block_data) tuples; block_data is always BLOCK_SIZE bytes
        :rtype: Iterator[Tuple[int, bytes]]
        """
        zeros = bytes(BLOCK_SIZE)
        buf = bytearray(BLOCK_SIZE)
        buf_used = 0
        block_index = 0
        for grain in self._grains():
            # a zero grain occupies grain_size_bytes zeros in the block stream
            grain_len = len(grain) if grain is not None else self._grain_size_bytes
            grain_offset = 0
            while grain_offset < grain_len:
                advance = min(BLOCK_SIZE - buf_used, grain_len - grain_offset)
                if grain is not None:
                    src_end = grain_offset + advance
                    dst_end = buf_used + advance
                    buf[buf_used:dst_end] = grain[grain_offset:src_end]
                grain_offset += advance
                buf_used += advance
                if buf_used == BLOCK_SIZE:
                    if buf != zeros:
                        yield block_index, bytes(buf)
                    buf = bytearray(BLOCK_SIZE)
                    buf_used = 0
                    block_index += 1
        if buf_used and buf[:buf_used] != zeros[:buf_used]:
            yield block_index, bytes(buf)


def get_block_source(path: str) -> Union[RawBlockSource, VmdkBlockSource]:
    """
    Get a block source for the given image path. Sparse vmdks are detected by their magic;
    descriptor-based vmdks are rejected, and other files are treated as raw disk images.

    :param path: the path to the source image (raw or vmdk)
    :type path: str
    :return: a block source for the image
    :rtype: Union[RawBlockSource, VmdkBlockSource]
    """
    if _is_vmdk(path):
        return VmdkBlockSource(path)
    return RawBlockSource(path)


class EBS:
    """
    Handle EBS direct API interaction (creating snapshots from a local image by
    streaming its non-zero blocks)
    """

    def __init__(self, context: Context, region: str):
        """
        :param context: the context
        :type context: awspub.context.Context
        :param region: the region to create the snapshot in
        :type region: str
        """
        self._ctx: Context = context
        concurrency = self._ctx.conf["snapshot"]["block_upload_concurrency"]
        self._ebsclient: EBSClient = boto3.client(
            "ebs",
            region_name=region,
            # AWS explicitly recommends retrying 5xx and (Request)Throttled exceptions
            # for the EBS direct APIs
            config=Config(retries={"max_attempts": 10, "mode": "standard"}, max_pool_connections=concurrency),
        )

    def start_snapshot(self, volume_size_gib: int, tags: Sequence[TagTypeDef], description: str) -> str:
        """
        Start a new (pending) snapshot via StartSnapshot

        :param volume_size_gib: the size of the snapshot volume in GiB
        :type volume_size_gib: int
        :param tags: the tags to apply to the snapshot
        :type tags: List[Dict[str, str]]
        :param description: the snapshot description
        :type description: str
        :return: the snapshot id
        :rtype: str
        """
        resp = self._ebsclient.start_snapshot(
            # auto-cancel the snapshot if no blocks are written for this many minutes
            # (a long timeout keeps a partially written snapshot reusable on retries)
            Timeout=720,
            VolumeSize=volume_size_gib,
            Tags=tags,
            Description=description,
        )
        if resp["Status"] == "error":
            raise exceptions.EBSSnapshotException(
                f"StartSnapshot returned status 'error' for volume size {volume_size_gib} GiB"
            )
        logger.info(f"started snapshot '{resp['SnapshotId']}' ({volume_size_gib} GiB) via the EBS direct APIs")
        return resp["SnapshotId"]

    def write_blocks(self, snapshot_id: str, source: Union[RawBlockSource, VmdkBlockSource]) -> int:
        """
        Write all non-zero blocks of the given block source to the (pending) snapshot.
        Unwritten blocks of a snapshot read back as zeros, so skipping zero blocks is safe.
        Blocks already written by a previous (interrupted) run are simply overwritten.

        :param snapshot_id: the snapshot id to write to
        :type snapshot_id: str
        :param source: the block source (raw or vmdk)
        :type source: Union[RawBlockSource, VmdkBlockSource]
        :return: the number of blocks written
        :rtype: int
        """
        concurrency = self._ctx.conf["snapshot"]["block_upload_concurrency"]
        # the total image size is only known for logging purposes; blocks are streamed
        # so the exact number of non-zero blocks is not known upfront
        total_bytes = source.volume_size_gib * (1024**3)
        started = time.monotonic()
        blocks_done = 0
        next_log_fraction = 0.05

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            pending_futures: Set[concurrent.futures.Future[None]] = set()

            def _drain(done_futures: Set[concurrent.futures.Future[None]]) -> None:
                nonlocal blocks_done, next_log_fraction
                for done_future in done_futures:
                    pending_futures.remove(done_future)
                    done_future.result()
                    blocks_done += 1
                    bytes_done = blocks_done * BLOCK_SIZE
                    if total_bytes and (bytes_done / total_bytes) >= next_log_fraction:
                        logger.info(
                            f"snapshot blocks written: {bytes_done // (1024**2)} MiB "
                            f"({round(bytes_done / total_bytes * 100)}%)"
                        )
                        next_log_fraction += 0.05

            for block_index, data in source.blocks():
                checksum = base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")
                future = executor.submit(self._put_block, snapshot_id, block_index, data, checksum)
                pending_futures.add(future)
                # bound memory usage/in-flight uploads
                if len(pending_futures) >= concurrency * 2:
                    done, _ = concurrent.futures.wait(pending_futures, return_when=concurrent.futures.FIRST_COMPLETED)
                    _drain(done)

            if pending_futures:
                done, _ = concurrent.futures.wait(pending_futures)
                _drain(done)

        logger.info(
            f"{blocks_done} blocks ({blocks_done * BLOCK_SIZE // (1024**2)} MiB) written to snapshot '{snapshot_id}' "
            f"in {round(time.monotonic() - started, 1)}s"
        )
        return blocks_done

    def _put_block(self, snapshot_id: str, block_index: int, data: bytes, checksum: str) -> None:
        """
        Write a single block to the given snapshot

        :param snapshot_id: the snapshot id to write to
        :type snapshot_id: str
        :param block_index: the block index (logical offset / 512 KiB)
        :type block_index: int
        :param data: the block data (always BLOCK_SIZE bytes)
        :type data: bytes
        :param checksum: the base64 encoded SHA256 checksum of the block data
        :type checksum: str
        """
        self._ebsclient.put_snapshot_block(
            SnapshotId=snapshot_id,
            BlockIndex=block_index,
            BlockData=data,
            DataLength=len(data),
            Checksum=checksum,
            ChecksumAlgorithm="SHA256",
        )

    def complete_snapshot(self, snapshot_id: str, changed_blocks_count: int) -> None:
        """
        Complete the given (pending) snapshot via CompleteSnapshot

        :param snapshot_id: the snapshot id to complete
        :type snapshot_id: str
        :param changed_blocks_count: the number of blocks written to the snapshot (required by
            the CompleteSnapshot API; for a snapshot without a parent snapshot every written
            block counts as changed)
        :type changed_blocks_count: int
        """
        resp = self._ebsclient.complete_snapshot(
            SnapshotId=snapshot_id,
            ChangedBlocksCount=changed_blocks_count,
        )
        status = resp.get("Status")
        if status not in ("completed", "pending"):
            raise exceptions.EBSSnapshotException(
                f"CompleteSnapshot for '{snapshot_id}' returned unexpected status '{status}'"
            )
