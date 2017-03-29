import pytest
import sys
import struct
import math
from pypytools import IS_PYPY
from capnpy import ptr
from capnpy.printer import print_buffer
from capnpy.basesegment import BaseSegmentForTests as BaseSegment, SegmentBuilder

class TestBaseSegment(object):

    def test_None(self):
        pytest.raises(AssertionError, "BaseSegment(None)")

    def test_read_int64(self):
        buf = struct.pack('qqq', 42, 43, 44)
        s = BaseSegment(buf)
        assert s.read_int64(0) == 42
        assert s.read_int64(8) == 43
        assert s.read_int64(16) == 44

    def test_read_ints(self):
        buf = 'garbage0' + '\xff' * 8
        s = BaseSegment(buf)
        assert s.read_int8(8) == -1
        assert s.read_int16(8) == -1
        assert s.read_int32(8) == -1
        assert s.read_int64(8) == -1
        #
        assert s.read_uint8(8)  == (1 <<  8) - 1
        assert s.read_uint16(8) == (1 << 16) - 1
        assert s.read_uint32(8) == (1 << 32) - 1
        assert s.read_uint64(8) == (1 << 64) - 1

    def test_read_float(self):
        buf = struct.pack('ff', 0, math.pi)
        s = BaseSegment(buf)
        assert s.read_float(4) == struct.unpack('ff', buf)[1]

    def test_read_double(self):
        buf = struct.pack('dd', 0, math.pi)
        s = BaseSegment(buf)
        assert s.read_double(8) == struct.unpack('dd', buf)[1]

    def test_uint64(self):
        if sys.maxint != (1 << 63)-1:
            pytest.skip('64 bit only')
        if IS_PYPY and sys.pypy_version_info < (5, 6):
            pytest.skip('Broken on PyPy<5.6')
        #
        buf = struct.pack('QQ', sys.maxint, sys.maxint+1)
        s = BaseSegment(buf)
        #
        val = s.read_uint64_magic(0)
        assert val == sys.maxint == s.read_uint64(0)
        assert type(val) is int
        #
        val = s.read_primitive(0, ord('Q'))
        assert val == sys.maxint == s.read_uint64(0)
        assert type(val) is int
        #
        val = s.read_uint64_magic(8)
        assert val == sys.maxint+1 == s.read_uint64(8)
        assert type(val) is long

    def test_read_primitive(self):
        buf = struct.pack('Q', 0x1234567887654321)
        s = BaseSegment(buf)
        for fmt in 'qQiIhHbBdf':
            val = s.read_primitive(0, ord(fmt))
            val2 = struct.unpack_from(fmt, buf, 0)[0]
            assert val == val2

    def test_errors(self):
        buf = '\xff' * 8
        s = BaseSegment(buf)
        pytest.raises(IndexError, "s.read_int8(-1)")
        pytest.raises(IndexError, "s.read_int16(-1)")
        pytest.raises(IndexError, "s.read_int32(-1)")
        pytest.raises(IndexError, "s.read_int64(-1)")
        #
        pytest.raises(IndexError, "s.read_uint8(-1)")
        pytest.raises(IndexError, "s.read_uint16(-1)")
        pytest.raises(IndexError, "s.read_uint32(-1)")
        pytest.raises(IndexError, "s.read_uint64(-1)")
        #
        pytest.raises(IndexError, "s.read_float(-1)")
        pytest.raises(IndexError, "s.read_double(-1)")
        #
        pytest.raises(IndexError, "s.read_int64(8)")


@pytest.mark.skipif(getattr(SegmentBuilder, 'WIP', False), reason='WIP')
class TestSegmentBuilder(object):

    def test_allocate(self):
        buf = SegmentBuilder(16)
        assert buf.allocate(8) == 0
        s = buf.as_string()
        assert s == '\x00' * 8

    def test_write_int64(self):
        buf = SegmentBuilder(8)
        buf.allocate(8)
        buf.write_int64(0, 0x1234ABCD)
        s = buf.as_string()
        assert s == '\xCD\xAB\x34\x12\x00\x00\x00\x00'

    def test_alloc_struct(self):
        buf = SegmentBuilder(64)
        buf.allocate(16)
        a = buf.alloc_struct(0, data_size=3, ptrs_size=0)
        b = buf.alloc_struct(8, data_size=1, ptrs_size=0)
        buf.write_int64(a,    1)
        buf.write_int64(a+8,  2)
        buf.write_int64(a+16, 3)
        buf.write_int64(b,    4)
        s = buf.as_string()
        assert s == ('\x04\x00\x00\x00\x03\x00\x00\x00'   # ptr to a (3, 0)
                     '\x0c\x00\x00\x00\x01\x00\x00\x00'   # ptr to b (1, 0)
                     '\x01\x00\x00\x00\x00\x00\x00\x00'   # a: 1
                     '\x02\x00\x00\x00\x00\x00\x00\x00'   #    2
                     '\x03\x00\x00\x00\x00\x00\x00\x00'   #    3
                     '\x04\x00\x00\x00\x00\x00\x00\x00')  # b: 4

    def test_resize(self):
        buf = SegmentBuilder()
        buf.allocate(64)
        print
        buf.write_int64(0, 42)
        for i in range(63):
            buf.allocate(64)
        s = buf.as_string()
        assert len(s) == 64*64
        assert s[:8] == struct.pack('q', 42)
        assert s[8:] == '\x00' * (64*64-8)

    def test_resize_big_allocation(self):
        buf = SegmentBuilder(32)
        assert buf.length == 32
        assert buf.end == 0
        # make a big allocation, which is bigger than the normal exponential
        # growth of the buffer
        buf.allocate(4096)
        assert buf.length == 4096
        assert buf.end == 4096
