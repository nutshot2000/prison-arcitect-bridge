import ctypes
import os
import unittest

from pa_agent.game.native import INPUT, Native


@unittest.skipUnless(os.name == "nt", "Windows native ABI")
class NativeTests(unittest.TestCase):
    def test_input_struct_size(self):
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_native_dpi_and_signatures(self):
        native = Native()
        self.assertGreater(native.user.GetSystemMetrics(78), 0)
        self.assertIsNotNone(native.user.SendInput.argtypes)
