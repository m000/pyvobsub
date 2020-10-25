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
import logging
import re
import shlex
from datetime import timedelta
from pathlib import Path
from PIL import ImageColor
from . import MPEGDecode

class IdxError(Exception):
    def __init__(self, vobsub, line, linenum, reason='Unspecified error'):
        message_fmt = '{reason:s} on {filename:s}:{linenum:d}.'
        message = message_fmt.format(reason=reason, linenum=linenum,
                filename=vobsub.idxfileq)
        super().__init__(message)

class IdxParseError(IdxError):
    def __init__(self, vobsub, line, linenum):
        super().__init__(vobsub, line, linenum, reason='Malformed line')

class VobSubError(Exception):
    pass

class VobSub:
    def __init__(self, filename, minframes=0):
        self.subfile = Path(filename)
        self.idxfile = Path(filename).with_suffix('.idx')
        self.minframes = minframes
        self.subtitles = {}
        self.meta = {}
        self._subfileh = None

        # parse idx file
        with self.idxfile.open() as f:
            logging.info("Parsing idx file %s.", self.idxfileq)
            context = {'id': None, 'index': None, 'lastpos': -1}
            for linenum, line in enumerate(f, 1):
                line = line.strip()
                if line.startswith('#'):
                    continue
                if len(line) == 0:
                    continue

                prefix, value = line.split(':', 1)
                parser = getattr(self, '_parse_{}'.format(prefix), None)
                if callable(parser):
                    # we have a parser for the prefix
                    parser(line, linenum, context)
                else:
                    # no parser - ignore
                    logging.debug("%s:%d: Ignoring prefix '%s'.",
                            self.idxfileq, linenum, prefix)
                    continue

        # remove subtitles that don't have enough frames - also account for dummy frame
        ignored = [i for i, s in self.subtitles.items() if len(s['frames']) - 1 < self.minframes]
        for i in ignored:
            logging.info("Ignoring subtitle %s (<%d frames).", self.subname(i), self.minframes)
            del self.subtitles[i]

        # show what's left
        logging.info("Subtitles found in {0:s}: {1:s}".format(self.idxfileq,
            ", ".join([self.subname(s, True) for s in self.subtitles])))

    def __del__(self):
        self.subfile_handle_close()

    def decode_frame(self, index, frameno):
        """Decode a singe subtitles frame.
           https://en.wikipedia.org/wiki/MPEG_program_stream
           Implementation ported from VLC DemuxVobSub():
            https://github.com/videolan/vlc/blob/master/modules/demux/vobsub.c
            https://github.com/videolan/vlc/blob/master/modules/demux/mpeg/ps.h
        """
        if index not in self.subtitles:
            raise VobSubError("Unknown subtitles index {0:d}.".format(index))

        frames = self.subtitles[index]['frames']
        h = self.subfile_handle()

        #t, o = frames[0]
        #for tn, on in frames[1:]:
            #print(on-o)
            #t, o = tn, on
        t, o = frames[frameno]
        tn, on = frames[frameno + 1]

        # read and parse bytes
        packet = h.read(on-o)
        mpegps = MPEGDecode.PS(packet)
        #magic = b[0:4]

        # check for errors
        #if not packet.startswith( != b'\x00\x00\x01\xba':
            #err = "Invalid PES magic {3:s} in {0:s}:{1:d}:{2:d}.".format(
                    #self.subfileq, index, frameno, str(magic))
            #raise VobSubError(err)

        # dump to file
        #with open('foo.mp4', 'wb') as bmp:
            #h.seek(o)
            #bmp.write(b)

    def _parse_id(self, line, linenum, context):
        """Parses an id line from an idx file.
        """
        id_regex = r'id:\s*([a-z]*)\s*,\s*index:\s*(\d*)'
        if (_m := re.match(id_regex, line, re.IGNORECASE)) is None:
            raise IdxParseError(self, line, linenum)

        lang, index =  (_m.group(1), int(_m.group(2)))
        if index in self.subtitles:
            err = "Repeated subtitle index {0:d}".format(index)
            raise IdxError(self, line, linenum, reason=err)

        self.subtitles[index] = {'lang': lang, 'frames': []}
        context['index'] = index

    def _parse_timestamp(self, line, linenum, context):
        """Parses a timetamp line from an idx file.
        """
        timestamp_regex = r'timestamp:\s*(\d{2}):(\d{2}):(\d{2}):(\d{3})\s*,\s*filepos:\s*([\da-f]+)'
        if (_m := re.match(timestamp_regex, line, re.IGNORECASE)) is None:
            raise IdxParseError(self, line, linenum)

        (h, m, s, ms) = map(int, _m.groups()[:4])
        timestamp = timedelta(hours=h, minutes=m, seconds=s, milliseconds=ms)
        filepos = int(_m.group(5), 16)

        # Offsets should increase monotonically.
        if not filepos > context['lastpos']:
            err = "Non-increasing file offset {0:x}".format(filepos)
            raise IdxError(self, line, linenum, reason=err)

        context['lastpos'] = filepos
        self.subtitles[context['index']]['frames'].append((timestamp, filepos))

    def _parse_palette(self, line, linenum, context):
        """Parses a pallette line from an idx file.
        """
        palette_regex = r'palette:\s*((?:[\da-f]{6}\s*,\s*)+[\da-f]{6})'
        if (_m := re.match(palette_regex, line, re.IGNORECASE)) is None:
            raise IdxParseError(self, line, linenum)

        # currently we don't handle changing the palette
        if 'palette' in self.meta:
            err = "Attempt to reset the palette"
            raise IdxError(self, line, linenum, reason=err)

        makecolor = lambda s: ImageColor.getrgb('#' + s.strip())
        self.meta['palette'] = [makecolor(c) for c in _m.group(1).split(',')]
        logging.debug("%s:%d: Setting the palette to %s.",
                self.idxfileq, linenum, self.meta['palette'])

    def subname(self, index, verbose=False):
        """Returns a string representing the subtitle of the specified index.
        """
        if index not in self.subtitles:
            return None
        s = self.subtitles[index]
        c = {'index': index, 'lang': s['lang'], 'nframes': len(s['frames']),}
        if verbose:
            return '{index:d}:{lang:s} ({nframes:d} frames)'.format(**c)
        else:
            return '{index:d}:{lang:s}'.format(**c)

    def subfile_handle(self):
        """Wrapper for transparently creating a handle for the subs file.
        """
        if self._subfileh is None or self._subfileh.closed:
            self._sbfileh = self.subfile.open('rb')
        return self._sbfileh

    def subfile_handle_close(self):
        """Force close the handle for the subs file.
        """
        if self._subfileh is not None and not self._subfileh.closed:
            self._subfileh.close()
        self._subfileh = None

    @property
    def idxfileq(self):
        return shlex.quote(str(self.idxfile))

    @property
    def subfileq(self):
        return shlex.quote(str(self.subfile))

# vim: expandtab:ts=4:sts=4:sw=4:
