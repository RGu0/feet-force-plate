import os
import unittest

from client.device.serial_transport import PortAvailability, SerialByteTransport, enumerate_ch340_ports
from client.device.transport import ByteTransport, TransportDisconnected


class FakePort:
    def __init__(self, device, *, vid=None, pid=None, description="", hwid=""):
        self.device = device
        self.vid = vid
        self.pid = pid
        self.description = description
        self.hwid = hwid


class FakeSerial:
    def __init__(self, reads=()):
        self.reads = list(reads)
        self.closed = False

    def read(self, size):
        value = self.reads.pop(0) if self.reads else b""
        if isinstance(value, BaseException):
            raise value
        return value[:size]

    def close(self):
        self.closed = True


class SerialDiscoveryTests(unittest.TestCase):
    _serial_options = {
        "baud_rate": 1_000_000,
        "data_bits": 8,
        "parity": "N",
        "stop_bits": 1,
    }

    def test_enumeration_filters_ch340_and_probes_availability(self) -> None:
        ports = [
            FakePort("/dev/cu.ch340-a", vid=0x1A86, pid=0x7523),
            FakePort("/dev/cu.other", vid=0x1234, description="Other USB"),
            FakePort("/dev/cu.ch341-b", description="USB-SERIAL CH341"),
        ]
        opened: list[tuple[str, dict]] = []

        def factory(*, port, **kwargs):
            opened.append((port, kwargs))
            if port.endswith("b"):
                raise OSError("resource busy")
            return FakeSerial()

        candidates = enumerate_ch340_ports(
            port_provider=lambda: ports,
            serial_factory=factory,
            probe_availability=True,
            **self._serial_options,
        )

        self.assertEqual(
            [item.device for item in candidates],
            ["/dev/cu.ch340-a", "/dev/cu.ch341-b"],
        )
        self.assertEqual(
            [item.availability for item in candidates],
            [PortAvailability.AVAILABLE, PortAvailability.BUSY_OR_UNAVAILABLE],
        )
        self.assertEqual(
            [port for port, _ in opened],
            ["/dev/cu.ch340-a", "/dev/cu.ch341-b"],
        )
        self.assertTrue(
            all(options["baudrate"] == 1_000_000 for _, options in opened)
        )
        if os.name == "posix":
            self.assertTrue(all(options["exclusive"] is True for _, options in opened))

    def test_enumeration_without_probe_does_not_claim_occupancy(self) -> None:
        candidates = enumerate_ch340_ports(
            port_provider=lambda: [FakePort("COM7", vid=0x1A86, description="CH340")],
            probe_availability=False,
            **self._serial_options,
        )

        self.assertEqual(candidates[0].availability, PortAvailability.UNKNOWN)

    def test_ch343_debug_port_is_never_probed_even_with_another_board(self) -> None:
        debug = FakePort("COM6", vid=0x1A86, pid=0x55D3, description="USB-Enhanced-SERIAL CH343")
        pressure = FakePort("COM7", vid=0x1A86, pid=0x7523)
        opened = []

        def factory(*, port, **_options):
            opened.append(port)
            return FakeSerial()

        for ports, expected in (([debug], []), ([debug, pressure], ["COM7"])):
            with self.subTest(ports=ports):
                opened.clear()
                candidates = enumerate_ch340_ports(
                    port_provider=lambda: ports,
                    serial_factory=factory,
                    **self._serial_options,
                )
                self.assertEqual([candidate.device for candidate in candidates], expected)
                self.assertEqual([candidate.availability for candidate in candidates],
                                 [PortAvailability.AVAILABLE] * len(expected))
                self.assertEqual(opened, expected)

    def test_ch341_is_detected_with_generic_driver_description(self) -> None:
        candidates = enumerate_ch340_ports(
            port_provider=lambda: [
                FakePort("COM8", vid=0x1A86, pid=0x5523, description="USB Serial"),
                FakePort("COM9", vid=0x1A86, pid=0x7522, description="USB Serial"),
            ],
            probe_availability=False,
            **self._serial_options,
        )
        self.assertEqual([candidate.device for candidate in candidates], ["COM8", "COM9"])


class SerialTransportTests(unittest.TestCase):
    def test_open_uses_one_megabaud_8n1_and_implements_byte_transport(self) -> None:
        calls = []
        serial = FakeSerial([b"abcdef"])

        def factory(**kwargs):
            calls.append(kwargs)
            return serial

        transport = SerialByteTransport.open(
            "/dev/cu.ch340-a",
            serial_factory=factory,
            timeout_seconds=0.25,
            baud_rate=1_000_000,
            data_bits=8,
            parity="N",
            stop_bits=1,
        )

        self.assertIsInstance(transport, ByteTransport)
        self.assertEqual(transport.read(3), b"abc")
        self.assertEqual(calls[0]["baudrate"], 1_000_000)
        self.assertEqual(calls[0]["bytesize"], 8)
        self.assertEqual(calls[0]["parity"], "N")
        self.assertEqual(calls[0]["stopbits"], 1)
        self.assertEqual(calls[0]["timeout"], 0.25)
        if os.name == "posix":
            self.assertTrue(calls[0]["exclusive"])
        transport.close()
        self.assertTrue(serial.closed)

    def test_read_failure_maps_to_transport_disconnect(self) -> None:
        transport = SerialByteTransport(FakeSerial([OSError("unplugged")]))

        with self.assertRaises(TransportDisconnected):
            transport.read(128)


if __name__ == "__main__":
    unittest.main()
