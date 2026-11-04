#!/usr/bin/env python3
"""Correct swapped Alt/Win keys only in Lan Mouse's virtual keyboard output.

Lan Mouse supplies a keymap that Hyprland treats as authoritative. Keep the
packaged application and its certificate unchanged; relay its Wayland traffic,
rewriting only virtual-keyboard keycodes and matching modifier masks.
No key events are recorded. This does not intercept physical input devices.

Protocol reference:
https://github.com/hyprwm/Hyprland/blob/v0.56.2/protocols/virtual-keyboard-unstable-v1.xml
"""

import array
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import threading


HEADER = struct.Struct("=II")
UINT = struct.Struct("=I")
KEY_SWAP = {56: 125, 125: 56, 100: 126, 126: 100}


def swap_modifiers(mask):
    return (mask & ~0x48) | ((mask & 0x08) << 3) | ((mask & 0x40) >> 3)


def message(object_id, opcode, payload=b""):
    return HEADER.pack(object_id, ((8 + len(payload)) << 16) | opcode) + payload


class KeyFilter:
    def __init__(self):
        self.registries = set()
        self.managers = set()
        self.keyboards = set()
        self.buffers = {"client": bytearray(), "server": bytearray()}
        self.lock = threading.Lock()

    def forget(self, object_id):
        self.registries.discard(object_id)
        self.managers.discard(object_id)
        self.keyboards.discard(object_id)

    def feed(self, direction, data):
        with self.lock:
            pending = self.buffers[direction]
            pending.extend(data)
            output = bytearray()
            offset = 0
            while len(pending) - offset >= 8:
                object_id, word = HEADER.unpack_from(pending, offset)
                size, opcode = word >> 16, word & 0xFFFF
                if size < 8 or size % 4:
                    raise ValueError("Invalid Wayland message length")
                if len(pending) - offset < size:
                    break
                frame = bytes(pending[offset:offset + size])
                if direction == "client":
                    frame = self.client_frame(object_id, opcode, frame)
                elif object_id == 1 and opcode == 1 and size == 12:
                    # wl_display.delete_id: IDs can later be reused.
                    self.forget(UINT.unpack_from(frame, 8)[0])
                output.extend(frame)
                offset += size
            if offset:
                del pending[:offset]
            return bytes(output)

    def client_frame(self, object_id, opcode, frame):
        if object_id == 1 and opcode == 1 and len(frame) == 12:
            self.registries.add(UINT.unpack_from(frame, 8)[0])
        elif object_id in self.registries and opcode == 0:
            # wl_registry.bind(name, interface string, version, new_id).
            if len(frame) < 24:
                raise ValueError("Truncated registry bind")
            string_size = UINT.unpack_from(frame, 12)[0]
            string_end = 16 + string_size
            tail = 16 + ((string_size + 3) & ~3)
            if not string_size or string_end > len(frame) or tail + 8 != len(frame):
                raise ValueError("Invalid registry bind")
            interface = frame[16:string_end].rstrip(b"\0")
            new_id = UINT.unpack_from(frame, tail + 4)[0]
            self.forget(new_id)
            if interface == b"zwp_virtual_keyboard_manager_v1":
                self.managers.add(new_id)
        elif object_id in self.registries and opcode == 1:
            self.forget(object_id)
        elif object_id in self.managers and opcode == 0 and len(frame) == 16:
            # create_virtual_keyboard(seat, new_id).
            new_id = UINT.unpack_from(frame, 12)[0]
            self.forget(new_id)
            self.keyboards.add(new_id)
        elif object_id in self.keyboards:
            if opcode == 1 and len(frame) == 20:
                frame = bytearray(frame)
                key = UINT.unpack_from(frame, 12)[0]
                UINT.pack_into(frame, 12, KEY_SWAP.get(key, key))
                return bytes(frame)
            if opcode == 2 and len(frame) == 24:
                frame = bytearray(frame)
                for offset in (8, 12, 16):
                    UINT.pack_into(frame, offset, swap_modifiers(UINT.unpack_from(frame, offset)[0]))
                return bytes(frame)
            if opcode == 3:
                self.forget(object_id)
        return frame


def send_with_fds(destination, data, fds):
    ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))] if fds else []
    sent = destination.sendmsg([data], ancillary)
    if sent <= 0:
        raise ConnectionError("Wayland connection closed during send")
    if sent < len(data):
        destination.sendall(data[sent:])


def close_fds(fds):
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass
    fds.clear()


def relay_pair(client, compositor, stopped, finished):
    key_filter = KeyFilter()
    close_lock = threading.Lock()
    closed = False

    def close_pair():
        nonlocal closed
        with close_lock:
            if closed:
                return
            closed = True
            for endpoint in (client, compositor):
                try:
                    endpoint.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                endpoint.close()
            finished(close_pair)

    def relay(source, destination, direction):
        fds = []
        try:
            while not stopped.is_set():
                data, ancillary, flags, _ = source.recvmsg(
                    65536, socket.CMSG_SPACE(256 * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC)
                for level, kind, contents in ancillary:
                    if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                        received = array.array("i")
                        received.frombytes(contents[:len(contents) - len(contents) % received.itemsize])
                        fds.extend(received)
                if flags & socket.MSG_CTRUNC:
                    raise ValueError("Truncated Wayland descriptor transfer")
                if not data:
                    break
                output = key_filter.feed(direction, data)
                if output:
                    # Wayland queues descriptors in stream order, independently
                    # of packet boundaries. Preserve that order across frames.
                    send_with_fds(destination, output, fds)
                    close_fds(fds)
        except (OSError, ValueError) as error:
            if not stopped.is_set() and not closed:
                print(f"Lan Mouse keyboard correction: {error}", file=sys.stderr)
        finally:
            close_fds(fds)
            close_pair()

    threads = [threading.Thread(target=relay, args=(client, compositor, "client"), daemon=True),
               threading.Thread(target=relay, args=(compositor, client, "server"), daemon=True)]
    return close_pair, threads


def run():
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
    real_socket = Path(display) if os.path.isabs(display) else runtime / display
    local_socket = runtime / f"lan-mouse-keys-{os.getpid()}.sock"
    stopped = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    child = None
    connections = set()
    connections_lock = threading.Lock()
    bound = False

    def finished(closer):
        with connections_lock:
            connections.discard(closer)

    try:
        listener.bind(str(local_socket))
        bound = True
        os.chmod(local_socket, 0o600)
        listener.listen(8)
        listener.settimeout(0.25)
        environment = os.environ.copy()
        environment["WAYLAND_DISPLAY"] = str(local_socket)
        environment.pop("WAYLAND_SOCKET", None)
        child = subprocess.Popen(["/usr/bin/lan-mouse", "daemon"], env=environment)
        print("Alt/Windows correction enabled for Lan Mouse virtual keyboard output.", flush=True)
        while not stopped.is_set() and child.poll() is None:
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            compositor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                compositor.connect(str(real_socket))
            except OSError:
                client.close()
                compositor.close()
                raise
            closer, threads = relay_pair(client, compositor, stopped, finished)
            with connections_lock:
                connections.add(closer)
            for thread in threads:
                thread.start()
        return 0 if stopped.is_set() else child.returncode
    finally:
        stopped.set()
        listener.close()
        with connections_lock:
            closers = list(connections)
        for closer in closers:
            closer()
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if bound:
            local_socket.unlink(missing_ok=True)


def transport_test():
    """Exercise the relay with synthetic traffic, never the real compositor.

    This test runs in the user's desktop terminal before enabling the fix.
    It tests both stream directions and keymap file-descriptor transfer.
    """
    client, client_relay = socket.socketpair()
    server_relay, server = socket.socketpair()
    for endpoint in (client, server):
        endpoint.settimeout(3)
    stopped = threading.Event()
    closer, threads = relay_pair(client_relay, server_relay, stopped, lambda _: None)
    for thread in threads:
        thread.start()
    original_fd = os.memfd_create("lan-mouse-keyboard-transport-test", os.MFD_CLOEXEC)
    received_fds = []

    def receive(endpoint, size):
        result = bytearray()
        while len(result) < size:
            data, ancillary, flags, _ = endpoint.recvmsg(
                65536, socket.CMSG_SPACE(256 * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC)
            if not data or flags & socket.MSG_CTRUNC:
                raise RuntimeError("Incomplete transport test")
            result.extend(data)
            for level, kind, contents in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    fds = array.array("i")
                    fds.frombytes(contents[:len(contents) - len(contents) % fds.itemsize])
                    received_fds.extend(fds)
        return bytes(result)

    try:
        marker = b"Synthetic keymap descriptor test.\0"
        os.write(original_fd, marker)
        interface = b"zwp_virtual_keyboard_manager_v1\0"
        padded = interface + b"\0" * (-len(interface) % 4)
        prefix = (message(1, 1, UINT.pack(2)) +
                  message(2, 0, struct.pack("=II", 1, len(interface)) + padded + struct.pack("=II", 1, 3)) +
                  message(3, 0, struct.pack("=II", 4, 5)))
        keymap = message(5, 0, struct.pack("=II", 1, len(marker)))
        source = prefix + keymap + message(5, 1, struct.pack("=III", 10, 56, 1))
        expected = prefix + keymap + message(5, 1, struct.pack("=III", 10, 125, 1))
        # Deliberately split a header, while transferring its descriptor early.
        send_with_fds(client, source[:3], [original_fd])
        client.sendall(source[3:])
        if receive(server, len(expected)) != expected or len(received_fds) != 1:
            raise RuntimeError("Client-to-compositor transfer failed")
        if os.pread(received_fds[0], len(marker), 0) != marker:
            raise RuntimeError("Keymap descriptor contents changed")
        response = message(8, 0, struct.pack("=II", 1, len(marker)))
        send_with_fds(server, response, [original_fd])
        if receive(client, len(response)) != response or len(received_fds) != 2:
            raise RuntimeError("Compositor-to-client transfer failed")
        if os.pread(received_fds[1], len(marker), 0) != marker:
            raise RuntimeError("Returned descriptor contents changed")
        print("Wayland relay transport test passed (both directions and file descriptors).")
        return 0
    finally:
        stopped.set()
        closer()
        client.close()
        server.close()
        close_fds(received_fds)
        os.close(original_fd)
        for thread in threads:
            thread.join(timeout=1)


def self_test():
    import unittest

    def uints(*values):
        return struct.pack("=" + "I" * len(values), *values)

    def startup():
        interface = b"zwp_virtual_keyboard_manager_v1\0"
        padded = interface + b"\0" * (-len(interface) % 4)
        return (message(1, 1, uints(2)) +
                message(2, 0, uints(1, len(interface)) + padded + uints(1, 3)) +
                message(3, 0, uints(4, 5)))

    class ProtocolTests(unittest.TestCase):
        def ready(self):
            parser = KeyFilter()
            self.assertEqual(parser.feed("client", startup()), startup())
            return parser

        def test_corrects_each_modifier_key_press_and_release(self):
            for original, corrected in ((56, 125), (125, 56), (100, 126), (126, 100)):
                for state in (0, 1):
                    with self.subTest(key=original, state=state):
                        source = message(5, 1, uints(123, original, state))
                        expected = message(5, 1, uints(123, corrected, state))
                        self.assertEqual(self.ready().feed("client", source), expected)

        def test_preserves_other_keys(self):
            parser = self.ready()
            for key in (29, 42, 58, 97, 30, 133, 312):
                frame = message(5, 1, uints(1, key, 1))
                self.assertEqual(parser.feed("client", frame), frame)

        def test_preserves_pointer_and_other_objects(self):
            frame = message(99, 1, uints(123, 56, 1))
            self.assertEqual(self.ready().feed("client", frame), frame)

        def test_preserves_incoming_physical_keyboard_events(self):
            frame = message(5, 1, uints(123, 56, 1))
            self.assertEqual(self.ready().feed("server", frame), frame)

        def test_keeps_key_and_modifier_states_consistent(self):
            frame = message(5, 2, uints(8 | 4, 64, 64 | 16, 3))
            expected = message(5, 2, uints(64 | 4, 8, 8 | 16, 3))
            self.assertEqual(self.ready().feed("client", frame), expected)

        def test_preserves_other_modifiers_and_both_keys_together(self):
            for mask in (0, 1, 2, 4, 16, 32, 128, 8 | 64, 0xFFFF):
                self.assertEqual(swap_modifiers(swap_modifiers(mask)), mask)
            frame = message(5, 2, uints(8 | 64 | 4 | 1, 0, 16 | 2, 0))
            self.assertEqual(self.ready().feed("client", frame), frame)

        def test_survives_arbitrary_stream_fragmentation(self):
            wire = startup() + message(5, 1, uints(1, 56, 1)) + message(5, 2, uints(8, 0, 0, 0))
            expected = startup() + message(5, 1, uints(1, 125, 1)) + message(5, 2, uints(64, 0, 0, 0))
            for chunk in (1, 2, 3, 7, 8, 13, 64, 65536):
                parser = KeyFilter()
                result = b"".join(parser.feed("client", wire[i:i + chunk]) for i in range(0, len(wire), chunk))
                self.assertEqual(result, expected)

        def test_does_not_rewrite_the_keymap_or_its_descriptor(self):
            frame = message(5, 0, uints(1, 4096))
            self.assertEqual(self.ready().feed("client", frame), frame)

        def test_forgets_destroyed_keyboard(self):
            parser = self.ready()
            parser.feed("client", message(5, 3))
            frame = message(5, 1, uints(1, 56, 1))
            self.assertEqual(parser.feed("client", frame), frame)

        def test_forgets_server_released_object_ids(self):
            parser = self.ready()
            released = message(1, 1, uints(5))
            self.assertEqual(parser.feed("server", released), released)
            frame = message(5, 1, uints(1, 56, 1))
            self.assertEqual(parser.feed("client", frame), frame)

        def test_rejects_invalid_framing(self):
            with self.assertRaises(ValueError):
                KeyFilter().feed("client", HEADER.pack(1, (7 << 16) | 1))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProtocolTests)
    return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        raise SystemExit(self_test())
    if sys.argv[1:] == ["--transport-test"]:
        try:
            raise SystemExit(transport_test())
        except PermissionError:
            raise SystemExit("The transport test needs socket permissions. Run it in your normal Omarchy terminal.")
    if sys.argv[1:]:
        raise SystemExit("Usage: lan-mouse-keyboard-fix.py [--self-test|--transport-test]")
    raise SystemExit(run())
