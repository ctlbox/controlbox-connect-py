import unittest

import sys
from hamcrest import assert_that, equal_to

from controlbox.conduit.process_conduit import ProcessConduit
from controlbox.config.config import configure_module

echo_command = None
more_command = None
# define these in consuit_test_<platform>.cfg


class ProcessConduitIntegrationTest(unittest.TestCase):

    def __init__(self, arg):
        super().__init__(arg)
        self.p = None

    def tearDown(self):
        if self.p is not None:
            self.p.close()

    @unittest.skipUnless(echo_command, "echo command not defined")
    def test_canCreateProcessConduitAndTerminate(self):
        self.p = ProcessConduit(echo_command)
        assert_that(self.p.open, equal_to(True))
        self.p.close()
        assert_that(self.p.open, equal_to(False))

    @unittest.skipUnless(echo_command, "echo command not defined")
    def test_canCreateProcessConduitAndReadOutputThenTerminate(self):
        p = ProcessConduit(echo_command, "123")
        lines = p.input.readline()
        self.assertEqual(lines, b"123\r\n")

    @unittest.skipUnless(more_command, "more command not defined")
    def test_canCreateProcessConduitAndSendInputOutputThenTerminate(self):
        # will read from stdin and pipe to stdout
        p = ProcessConduit(more_command)
        p.output.write(b"hello\r\n")
        p.output.flush()
        lines = p.input.readline()
        self.assertEqual(lines, b"hello\r\n")


configure_module(sys.modules[__name__], 'conduit_test')
