
import functools
import os
import re

from SublimePyuv import pyuv

from StreamingLinter.lib import ui


LINESEP = os.linesep.encode()


class LineReaderPipe(pyuv.Pipe):

    def __init__(self, *args, **kwargs):
        super(LineReaderPipe, self).__init__(*args, **kwargs)
        self.callback = None
        self.buffer = b''

    def _line_generator(self, data):
        for line in data.splitlines(True):
            if not line[-len(LINESEP):] == LINESEP:
                self.buffer += line
                break

            line = line.strip()
            if self.buffer:
                line = self.buffer + line
                self.buffer = b''

            yield line

    def on_pipe_read(self, pipe, data, error):
        if error:
            pipe.close()
            return

        self.callback(self._line_generator(data))

    def start_read(self, callback):
        self.callback = callback
        super(LineReaderPipe, self).start_read(self.on_pipe_read)


class Linter(object):
    pattern = None
    command = None

    @classmethod
    def run(cls, view):
        ui.clear(view)
        cls.run_command(view.file_name(), view)

    @classmethod
    def run_command(cls, file_name, view):
        loop = pyuv.Loop.default_loop()
        pipe = LineReaderPipe(loop)
        proc = pyuv.Process(loop)

        ios = [pyuv.StdIO(),  # stdin - ignore
               pyuv.StdIO(pipe, flags=pyuv.UV_CREATE_PIPE |
                          pyuv.UV_WRITABLE_PIPE)]  # stdout - create pipe
        exit_cb = functools.partial(cls.command_finished, view)
        proc.spawn(cls.command, exit_cb, (file_name,), stdio=ios,
                   flags=pyuv.UV_PROCESS_WINDOWS_HIDE)
        line_cb = functools.partial(cls.process_lines, view)
        pipe.start_read(line_cb)

    @classmethod
    def process_lines(cls, view, lines):
        regions = list()
        for line in lines:
            line = line.decode('utf-8')
            match = cls.pattern.match(line)
            if match:
                line = int(match.group('line_number')) - 1

                region = view.full_line(view.text_point(line, 0))
                regions.append(region)

                messages = ui.get_messages(view)
                msg = '%(code)s %(reason)s' % {'code': match.group('code'),
                                               'reason': match.group('reason')}
                messages[line].append(msg)
        ui.add_regions(view, regions)

    @classmethod
    def command_finished(cls, view, proc, exit_status, term_signal):
        proc.close()

        cur_line = ui.get_selected_lineno(view)
        ui.update_status_message(view, cur_line)
        ui.linting_views.discard(view.buffer_id())


class Flake8(Linter):
    ''' Requires 2.0 '''
    pattern = re.compile(r'^(?P<file_name>.+):(?P<line_number>\d+):'
                         '(?P<position>\d+):\s+(?P<code>\w{4,4})\s+'
                         '(?P<reason>.*)$')
    command = 'flake8'


def lint(view, ioloop):
    if ui.get_syntax(view) != 'Python':
        return
    if view.buffer_id() in ui.linting_views:
        return

    ui.linting_views.add(view.buffer_id())
    ioloop.add_callback(Flake8.run, view)
