#
# Copyright (c) 2020 Manolis Stamatogiannakis <mstamat@gmail.com>.
#
# This file is part of pyvobsub
# (see https://github.com/m000/pyvobsub).
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
from pathlib import Path
from bitarray import bitarray

class MPEGDecodeError(Exception):
    pass

class MPEGPSDecodeError(MPEGDecodeError):
    pass

class PS:
    """A limited MPEG-PS parser for decoding VobSub subtitles.
       Reference:
           https://en.wikipedia.org/wiki/MPEG_program_stream
           https://en.wikipedia.org/wiki/Packetized_elementary_stream
           http://flavor.sourceforge.net/samples/mpeg2ps.htm
    """
    # bytes constants
    MARKER = b'\x00\x00\x01\xba'
    MARKER_SYS = b'\x00\x00\x01\xbb'
    MARKER_PRIVATE1 = b'\x00\x00\x01\xbd'
    MARKER_PADDING = b'\x00\x00\x01\xbe'
    MARKER_LENGTH = 4
    HEADER_LENGTH = 14  # 112bits
    CONTENT_LENGTH_LENGTH = 2

    # bits constants
    MPEG_MARKER_SLICE = slice(32, 32+2)
    HEADER_MARKERS = (37, 53, 69, 79, 102, 103)
    HEADER_STUFFING_SLICE = slice(109, 109+3)

    def __init__(self, packet, index=0, packetno=0):
        # Dump packet
        out = Path('subp_%02d.%04d.m2p' % (index, packetno))
        out.write_bytes(packet)

        if not packet.startswith(PS.MARKER):
            marker = packet[:PS.MARKER_LENGTH]
            err = "Bad packet marker {0:s}.".format(str(marker))
            raise MPEGPSDecodeError(err)

        # Note that this is bit endianess, not byte endianess!
        self.header = packet[:PS.HEADER_LENGTH]
        self.header01 = bitarray(endian='big')
        self.header01.frombytes(self.header)

        # Check MPEG version. According to the reference:
        #     header01[32:34] == 01 -> MPEG-2
        #     header01[32:34] == 10 -> MPEG-1
        mpeg_marker = self.header01[PS.MPEG_MARKER_SLICE].to01()
        if mpeg_marker == '01':
            self.mpeg_version = 2
        elif mpeg_marker == '10':
            self.mpeg_version = 1
        else:
            err = "Invalid MPEG version marker {0:s}.".format(mpeg_marker)
            raise MPEGPSDecodeError(err)

        # Check header markers.
        bad_markers = [m for m in PS.HEADER_MARKERS if not self.header01[m]]
        if bad_markers:
            err = "Header marker bits fail in positions {0:s}.".format(str(bad_markers))
            raise MPEGPSDecodeError(err)

        # Read stuffing length.
        # Byte order for doesn't matter here (converting 1 byte).
        length =  int.from_bytes(
                self.header01[PS.HEADER_STUFFING_SLICE].tobytes(),
                byteorder='big')

        # Keep the packet contents only. Contents are byte-oriented.
        # Integers use big-endian order (aka network byte order).
        self.contents = packet[PS.HEADER_LENGTH + length:]
        cidx = 0

        # Process contents.
        while cidx < len(self.contents):
            marker = self.contents[cidx:cidx+PS.MARKER_LENGTH]
            cidx += PS.MARKER_LENGTH

            if marker == PS.MARKER_SYS:
                err = 'MPEG-PS system header decoding not implemented.'
                raise MPEGPSDecodeError(err)
            elif marker == PS.MARKER_PRIVATE1:
                length = int.from_bytes(
                        self.contents[cidx:cidx+PS.CONTENT_LENGTH_LENGTH],
                        byteorder='big')
                cidx += PS.CONTENT_LENGTH_LENGTH
                cidx += length
                # Dump PES contents.
                out = Path('subc_%02d.%04d.m2p' % (index, packetno))
                out.write_bytes(self.contents[cidx-length:cidx])
            elif marker == PS.MARKER_PADDING:
                length = int.from_bytes(
                        self.contents[cidx:cidx+PS.CONTENT_LENGTH_LENGTH],
                        byteorder='big')
                cidx += PS.CONTENT_LENGTH_LENGTH
                cidx += length
            else:
                err = ( "Unsupported PES marker {0:s}.\n"
                        "Remaining packet: {1:s}"
                        ).format(str(marker), str(self.contents[cidx:]))
                raise MPEGPSDecodeError(err)

# vim: expandtab:ts=4:sts=4:sw=4:
