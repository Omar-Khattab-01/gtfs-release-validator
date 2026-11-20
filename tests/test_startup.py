import errno
import io
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from gtfs_validator import __version__
from gtfs_validator.web import ValidatorHandler, serve


class StartupTests(unittest.TestCase):
    def test_browser_launch_uses_free_port_when_old_copy_is_running(self):
        with ThreadingHTTPServer(('127.0.0.1', 0), ValidatorHandler) as old:
            ports = []
            output = io.StringIO()
            with patch.object(ThreadingHTTPServer, 'serve_forever',
                              lambda server: ports.append(server.server_port)), \
                    patch('gtfs_validator.web.threading.Timer') as timer, \
                    redirect_stdout(output):
                serve(port=old.server_port, open_browser=True)
            self.assertNotEqual(old.server_port, ports[0])
            self.assertIn(f'http://127.0.0.1:{ports[0]}', timer.call_args.kwargs['args'])
            self.assertIn(f'GTFS Validator {__version__}', output.getvalue())
            self.assertIn('Application folder:', output.getvalue())
            self.assertEqual(old.server_port, old.socket.getsockname()[1])

    def test_explicit_server_port_without_browser_stays_strict(self):
        with ThreadingHTTPServer(('127.0.0.1', 0), ValidatorHandler) as old:
            with self.assertRaises(OSError):
                serve(port=old.server_port)

    def test_permission_errors_are_not_treated_as_busy_ports(self):
        with patch('gtfs_validator.web.ThreadingHTTPServer',
                   side_effect=PermissionError(errno.EACCES, 'Permission denied')) as factory:
            with self.assertRaises(PermissionError):
                serve(open_browser=True)
            self.assertEqual(1, factory.call_count)

    def test_automatic_port_opens_the_actual_bound_address(self):
        ports = []
        with patch.object(ThreadingHTTPServer, 'serve_forever',
                          lambda server: ports.append(server.server_port)), \
                patch('gtfs_validator.web.threading.Timer') as timer, \
                redirect_stdout(io.StringIO()):
            serve(port=0, open_browser=True)
        self.assertGreater(ports[0], 0)
        self.assertEqual((f'http://127.0.0.1:{ports[0]}',), timer.call_args.kwargs['args'])


if __name__ == '__main__':
    unittest.main()
