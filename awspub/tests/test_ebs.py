import base64
import hashlib
import pathlib
import struct
import zlib
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from awspub import context, ebs, exceptions

curdir = pathlib.Path(__file__).parent.resolve()
BLOCK_SIZE = ebs.BLOCK_SIZE
GRAIN_SIZE = 64 * 1024
GRAIN_SECTORS = GRAIN_SIZE // 512


def _make_raw(path: pathlib.Path, blocks: dict, num_blocks: int):
    """
    Write a raw image with the given non-zero blocks (dict block_index -> bytes, padded to BLOCK_SIZE)
    """
    with open(path, "wb") as f:
        for i in range(num_blocks):
            f.write(blocks.get(i, bytes(BLOCK_SIZE)).ljust(BLOCK_SIZE, b"\x00"))


def _make_vmdk(
    path: pathlib.Path,
    grains: list,
    grain_size: int = GRAIN_SIZE,
    compressed: bool = True,
    capacity_sectors: Optional[int] = None,
    descriptor_lines: Optional[List[str]] = None,
):
    """
    Build a synthetic single-extent sparse vmdk (like qemu-img produces for
    streamOptimized/monolithicSparse)

    :param grains: list of grain contents (bytes) or None for an unallocated grain
    :param grain_size: grain size in bytes
    :param compressed: if True, grains are deflate compressed with a grain marker
    :param capacity_sectors: optional capacity override (to test a partial last grain)
    :param descriptor_lines: optional override for the descriptor content
    """
    grain_sectors = grain_size // 512
    num_grains = len(grains)
    gtes_per_gt = 512
    num_gts = max(1, (num_grains + gtes_per_gt - 1) // gtes_per_gt)
    desc_offset = 1
    desc_size = 1
    gd_offset = desc_offset + desc_size
    gt_offset0 = gd_offset + num_gts  # each grain table needs 4 sectors (512 * 4 bytes)
    grain_offset = gt_offset0 + num_gts * 4

    if capacity_sectors is None:
        capacity_sectors = num_grains * grain_sectors

    if descriptor_lines is None:
        descriptor_lines = [f'RW {capacity_sectors} SPARSE "test.vmdk"']
    descriptor = ("\n".join(descriptor_lines) + "\n").encode("utf-8")

    # build grain records and the grain table entries
    gt_entries = []
    records = []  # (sector, payload)
    current_sector = grain_offset
    for grain_index, grain in enumerate(grains):
        if grain is None:
            gt_entries.append(0)
            continue
        if grain == "zeroed":
            # explicit zeroed grain table entry (requires the ZERO_GRAIN flag)
            gt_entries.append(1)
            continue
        if compressed:
            comp = zlib.compress(grain)
            payload = struct.pack("<QI", grain_index * grain_sectors, len(comp)) + comp
        else:
            payload = grain
        pad = (-len(payload)) % 512
        records.append((current_sector, payload + b"\x00" * pad))
        gt_entries.append(current_sector)
        current_sector += (len(payload) + pad) // 512

    with open(path, "wb") as f:
        # header
        header = bytearray(512)
        header[0:4] = b"KDMV"  # magic
        struct.pack_into(
            "<IIQQQQiQQQB",
            header,
            4,
            3,  # version
            (
                (ebs._VMDK_FLAG_COMPRESSED | ebs._VMDK_FLAG_MARKER | ebs._VMDK_FLAG_ZERO_GRAIN) if compressed else 0
            ),  # flags
            capacity_sectors,
            grain_sectors,
            desc_offset,
            desc_size,
            gtes_per_gt,
            0,  # rgd offset (unused)
            gd_offset,
            grain_offset,  # overhead
            0,  # unclean shutdown
        )
        header[73:77] = b"\x0a\x20\x0d\x0a"  # check bytes
        struct.pack_into("<H", header, ebs._VMDK_COMPRESS_ALGORITHM_OFFSET, 1 if compressed else 0)
        f.write(header)
        # descriptor
        f.write(descriptor.ljust(desc_size * 512, b"\x00"))
        # grain directory (padded to full sectors)
        gd_bytes = struct.pack(f"<{num_gts}I", *[gt_offset0 + gt_index * 4 for gt_index in range(num_gts)])
        f.write(gd_bytes.ljust(-(-len(gd_bytes) // 512) * 512, b"\x00"))
        # grain tables (padded to gtes_per_gt entries, each table 4 sectors)
        for gt_index in range(num_gts):
            slice_start = gt_index * gtes_per_gt
            slice_end = (gt_index + 1) * gtes_per_gt
            entries = gt_entries[slice_start:slice_end]
            entries = entries + [0] * (gtes_per_gt - len(entries))
            f.write(struct.pack(f"<{gtes_per_gt}I", *entries))
        # grain records
        for sector, payload in records:
            assert f.tell() == sector * 512
            f.write(payload)


def test_block_source_raw_nonzero_blocks_only(tmp_path):
    """
    RawBlockSource must only yield the non-zero blocks
    """
    raw_path = tmp_path / "test.raw"
    data0 = b"a" * BLOCK_SIZE
    data2 = b"b" * BLOCK_SIZE
    _make_raw(raw_path, {0: data0, 2: data2}, 3)
    source = ebs.RawBlockSource(str(raw_path))
    assert source.volume_size_gib == 1
    assert list(source.blocks()) == [(0, data0), (2, data2)]


def test_block_source_raw_partial_last_block_padded(tmp_path):
    """
    A partial last block must be padded with zeros to the full 512 KiB block size
    """
    raw_path = tmp_path / "test.raw"
    data = b"x" * (100 * 1024)
    with open(raw_path, "wb") as f:
        f.write(data)
    source = ebs.RawBlockSource(str(raw_path))
    blocks = list(source.blocks())
    assert blocks == [(0, data.ljust(BLOCK_SIZE, b"\x00"))]
    assert len(blocks[0][1]) == BLOCK_SIZE


def test_block_source_raw_zero_partial_block_skipped(tmp_path):
    raw_path = tmp_path / "zero.raw"
    raw_path.write_bytes(bytes(1024))
    assert list(ebs.RawBlockSource(str(raw_path)).blocks()) == []


def test_block_source_raw_empty_raises(tmp_path):
    """
    An empty raw image must raise
    """
    raw_path = tmp_path / "test.raw"
    raw_path.write_bytes(b"")
    with pytest.raises(exceptions.InvalidSourceImageException):
        ebs.RawBlockSource(str(raw_path))


def test_block_source_vmdk_compressed_with_markers(tmp_path):
    """
    Compressed grains (streamOptimized style) must be assembled into correct 512 KiB blocks;
    unallocated and explicitly zeroed grains are zeros
    """
    vmdk_path = tmp_path / "test.vmdk"
    grain0 = bytes(range(256)) * 256  # 64 KiB
    grain2 = bytes(reversed(bytes(range(256)))) * 256  # 64 KiB
    _make_vmdk(vmdk_path, [grain0, None, grain2, "zeroed"])
    source = ebs.VmdkBlockSource(str(vmdk_path))
    assert source.volume_size_gib == 1
    # 4 grains of 64 KiB = 256 KiB: one zero padded 512 KiB block consisting of
    # grain0 + unallocated grain1 + grain2 + explicitly zeroed grain3
    assert list(source.blocks()) == [
        (0, (grain0 + bytes(GRAIN_SIZE) + grain2 + bytes(GRAIN_SIZE)).ljust(BLOCK_SIZE, b"\x00")),
    ]


def test_block_source_vmdk_uncompressed(tmp_path):
    """
    Uncompressed grains (monolithicSparse style) must be assembled into correct blocks
    """
    vmdk_path = tmp_path / "test.vmdk"
    grain0 = b"a" * GRAIN_SIZE
    grain1 = b"b" * GRAIN_SIZE
    _make_vmdk(vmdk_path, [grain0, grain1], compressed=False)
    source = ebs.VmdkBlockSource(str(vmdk_path))
    # 2 grains = 128 KiB = one (zero padded) full block
    assert list(source.blocks()) == [(0, (grain0 + grain1).ljust(BLOCK_SIZE, b"\x00"))]


def test_block_source_vmdk_grain_larger_than_block(tmp_path):
    """
    Grains larger than the 512 KiB block size (eg. 1 MiB grains) must be split correctly
    """
    vmdk_path = tmp_path / "test.vmdk"
    grain_size = 1024 * 1024
    grain0 = b"a" * grain_size
    grain1 = b"b" * grain_size
    _make_vmdk(vmdk_path, [grain0, grain1], grain_size=grain_size, compressed=False)
    source = ebs.VmdkBlockSource(str(vmdk_path))
    assert source.volume_size_gib == 1
    assert list(source.blocks()) == [
        (0, b"a" * BLOCK_SIZE),
        (1, b"a" * BLOCK_SIZE),
        (2, b"b" * BLOCK_SIZE),
        (3, b"b" * BLOCK_SIZE),
    ]


def test_block_source_vmdk_partial_last_grain(tmp_path):
    """
    A capacity that is not grain aligned must shorten the last grain
    """
    vmdk_path = tmp_path / "test.vmdk"
    grain0 = b"a" * GRAIN_SIZE
    grain1 = b"b" * GRAIN_SIZE
    # capacity of 1.5 grains: grain1 is only half used
    _make_vmdk(vmdk_path, [grain0, grain1], compressed=False, capacity_sectors=GRAIN_SECTORS * 3 // 2)
    source = ebs.VmdkBlockSource(str(vmdk_path))
    assert list(source.blocks()) == [(0, (grain0 + grain1[: GRAIN_SIZE // 2]).ljust(BLOCK_SIZE, b"\x00"))]


def test_block_source_vmdk_multiple_extents_raises(tmp_path):
    """
    A vmdk with more than one extent in the descriptor must raise
    """
    vmdk_path = tmp_path / "test.vmdk"
    _make_vmdk(
        vmdk_path,
        [b"a" * GRAIN_SIZE],
        descriptor_lines=['RW 128 SPARSE "test.vmdk"', 'RW 128 SPARSE "test-s001.vmdk"'],
    )
    with pytest.raises(exceptions.InvalidSourceImageException):
        ebs.VmdkBlockSource(str(vmdk_path))


def test_block_source_vmdk_linked_clone_raises(tmp_path):
    """
    A vmdk with a parent (linked clone) must raise
    """
    vmdk_path = tmp_path / "test.vmdk"
    _make_vmdk(
        vmdk_path,
        [b"a" * GRAIN_SIZE],
        descriptor_lines=['RW 128 SPARSE "test.vmdk"', 'parentFileNameHint "parent.vmdk"'],
    )
    with pytest.raises(exceptions.InvalidSourceImageException):
        ebs.VmdkBlockSource(str(vmdk_path))


@pytest.mark.parametrize("damage", ["invalid-deflate", "truncated-record", "incomplete-stream", "oversized-grain"])
def test_block_source_vmdk_corrupt_compressed_grain_raises(tmp_path, damage):
    """
    A corrupted compressed grain must raise
    """
    vmdk_path = tmp_path / "test.vmdk"
    grain_size = GRAIN_SIZE + 1 if damage == "oversized-grain" else GRAIN_SIZE
    _make_vmdk(vmdk_path, [b"a" * grain_size])
    # locate the first grain record via its directory and table
    with open(vmdk_path, "rb") as f:
        header = f.read(512)
        _magic, _version, _flags, _cap, _grain, _doff, _dsize, num_gtes, _rgd, gd, _oh, _u = struct.unpack_from(
            "<IIIQQQQiQQQB", header, 0
        )
        f.seek(gd * 512)
        gt_offset = struct.unpack("<I", f.read(4))[0]
        f.seek(gt_offset * 512)
        grain_record_sector = struct.unpack("<I", f.read(4))[0]
        f.seek(grain_record_sector * 512)
        _lba, compressed_size = struct.unpack("<QI", f.read(12))
    with open(vmdk_path, "r+b") as f:
        if damage == "invalid-deflate":
            f.seek(grain_record_sector * 512 + 12)
            f.write(b"\x00" * compressed_size)
        elif damage in ("truncated-record", "incomplete-stream"):
            if damage == "incomplete-stream":
                # The record length is consistent, but the zlib trailer is missing.
                f.seek(grain_record_sector * 512 + 8)
                f.write(struct.pack("<I", compressed_size - 4))
            f.truncate(grain_record_sector * 512 + 12 + compressed_size - 4)
    with pytest.raises(exceptions.InvalidSourceImageException):
        list(ebs.VmdkBlockSource(str(vmdk_path)).blocks())


def test_get_block_source_dispatch(tmp_path):
    """
    get_block_source() must return a VmdkBlockSource for vmdks and a RawBlockSource otherwise
    """
    raw_path = tmp_path / "test.raw"
    raw_path.write_bytes(b"x" * BLOCK_SIZE)
    assert isinstance(ebs.get_block_source(str(raw_path)), ebs.RawBlockSource)

    vmdk_path = tmp_path / "test.vmdk"
    _make_vmdk(vmdk_path, [b"a" * GRAIN_SIZE])
    assert isinstance(ebs.get_block_source(str(vmdk_path)), ebs.VmdkBlockSource)


def test_get_block_source_rejects_vmdk_descriptor(tmp_path):
    vmdk_path = tmp_path / "split.vmdk"
    vmdk_path.write_text('# Disk DescriptorFile\nversion=1\nRW 2048 SPARSE "split-s001.vmdk"\n')
    with pytest.raises(exceptions.InvalidSourceImageException):
        ebs.get_block_source(str(vmdk_path))


@patch("boto3.client")
def test_ebs_write_blocks_puts_nonzero_blocks_only(bclient_mock, tmp_path):
    """
    write_blocks() must call put_snapshot_block for every non-zero block with the correct
    index, checksum and DataLength, then complete the snapshot
    """
    ctx = context.Context(curdir / "fixtures/config-direct.yaml", None)
    ebs_client = ebs.EBS(ctx, "region1")
    instance = bclient_mock.return_value

    raw_path = tmp_path / "test.raw"
    data0 = b"a" * BLOCK_SIZE
    data2 = b"b" * BLOCK_SIZE
    _make_raw(raw_path, {0: data0, 2: data2}, 3)
    source = ebs.RawBlockSource(str(raw_path))

    instance.start_snapshot = MagicMock(return_value={"SnapshotId": "snap-1", "Status": "pending"})
    instance.complete_snapshot = MagicMock(return_value={"Status": "completed"})
    snapshot_id = ebs_client.start_snapshot(1, [{"Key": "Name", "Value": "n"}], "description")
    assert snapshot_id == "snap-1"

    blocks_written = ebs_client.write_blocks("snap-1", source)
    assert blocks_written == 2
    ebs_client.complete_snapshot("snap-1", blocks_written)

    calls = instance.put_snapshot_block.call_args_list
    assert len(calls) == 2
    calls_by_index = {call.kwargs["BlockIndex"]: call for call in calls}
    assert calls_by_index.keys() == {0, 2}
    for index, data in ((0, data0), (2, data2)):
        call = calls_by_index[index]
        assert call.kwargs["SnapshotId"] == "snap-1"
        assert call.kwargs["BlockIndex"] == index
        assert call.kwargs["DataLength"] == BLOCK_SIZE
        assert call.kwargs["BlockData"] == data
        assert call.kwargs["ChecksumAlgorithm"] == "SHA256"
        assert call.kwargs["Checksum"] == base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")
    instance.complete_snapshot.assert_called_once_with(SnapshotId="snap-1", ChangedBlocksCount=2)


@patch("boto3.client")
def test_ebs_start_snapshot_error_raises(bclient_mock):
    """
    start_snapshot() must raise if StartSnapshot returns status 'error'
    """
    ctx = context.Context(curdir / "fixtures/config-direct.yaml", None)
    ebs_client = ebs.EBS(ctx, "region1")
    instance = bclient_mock.return_value
    instance.start_snapshot = MagicMock(return_value={"SnapshotId": "snap-1", "Status": "error"})
    with pytest.raises(exceptions.EBSSnapshotException):
        ebs_client.start_snapshot(1, [], "description")


@patch("boto3.client")
def test_ebs_complete_snapshot_unexpected_status_raises(bclient_mock):
    """
    complete_snapshot() must raise if CompleteSnapshot returns an unexpected status
    """
    ctx = context.Context(curdir / "fixtures/config-direct.yaml", None)
    ebs_client = ebs.EBS(ctx, "region1")
    instance = bclient_mock.return_value
    instance.complete_snapshot = MagicMock(return_value={"Status": "unexpected"})
    with pytest.raises(exceptions.EBSSnapshotException):
        ebs_client.complete_snapshot("snap-1", changed_blocks_count=0)
