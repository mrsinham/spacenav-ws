"""Tests for controller logic."""

import asyncio
import struct

import numpy as np
import pytest

from spacenav_ws.controller import Controller
from spacenav_ws.spacenav import MotionEvent, ButtonEvent


class TestAffinePivotMatrices:
    def test_identity_model(self):
        """Symmetric extents around origin should produce zero-pivot matrices."""
        extents = [-1, -1, -1, 1, 1, 1]
        pivot_pos, pivot_neg = Controller.get_affine_pivot_matrices(extents)
        # pivot = (min+max)/2 = (0,0,0)
        assert np.allclose(pivot_pos, np.eye(4))
        assert np.allclose(pivot_neg, np.eye(4))

    def test_offset_model(self):
        """Extents from HAR capture: [-3, -0.75, 2.5, 0, 0.75, 5.5]"""
        extents = [-3, -0.75, 2.5, 0, 0.75, 5.5]
        pivot_pos, pivot_neg = Controller.get_affine_pivot_matrices(extents)
        expected_pivot = np.array([-1.5, 0.0, 4.0], dtype=np.float32)
        assert np.allclose(pivot_pos[3, :3], expected_pivot)
        assert np.allclose(pivot_neg[3, :3], -expected_pivot)

    def test_pos_neg_are_inverses(self):
        """pivot_pos @ pivot_neg should equal identity."""
        extents = [1, 2, 3, 5, 8, 13]
        pivot_pos, pivot_neg = Controller.get_affine_pivot_matrices(extents)
        result = pivot_pos @ pivot_neg
        assert np.allclose(result, np.eye(4), atol=1e-6)

    def test_matrices_are_4x4(self):
        extents = [0, 0, 0, 1, 1, 1]
        pivot_pos, pivot_neg = Controller.get_affine_pivot_matrices(extents)
        assert pivot_pos.shape == (4, 4)
        assert pivot_neg.shape == (4, 4)


def _make_motion_packet(x, y, z, pitch, yaw, roll, period=16):
    """Encode a motion event as a 32-byte spacenavd packet (type=0)."""
    return struct.pack("iiiiiiii", 0, x, z, y, pitch, yaw, roll, period)


def _make_button_packet(button_id, pressed):
    """Encode a button event as a 32-byte spacenavd packet."""
    return struct.pack("iiiiiiii", 1 if pressed else 2, button_id, 0, 0, 0, 0, 0, 0)


class TestDebounce:
    """Test that rapid motion events are accumulated and flushed as one."""

    @pytest.fixture
    def controller(self):
        """Build a Controller with a fake reader and a stub wamp session."""
        reader = asyncio.StreamReader()

        # Minimal stubs so Controller.__init__ doesn't touch a real websocket
        class StubWamp:
            subscribe_handlers = {}
            call_handlers = {}

        class StubSession:
            wamp = StubWamp()

            async def client_rpc(self, *args):
                return None

        ctrl = Controller.__new__(Controller)
        ctrl.id = "controller0"
        ctrl.client_metadata = {"name": "Onshape", "version": "0"}
        ctrl.reader = reader
        ctrl.wamp_state_handler = StubSession()
        ctrl.subscribed = True
        ctrl.focus = True
        ctrl._pending_motion = None
        ctrl._motion_ready = asyncio.Event()
        return ctrl, reader

    @pytest.mark.asyncio
    async def test_accumulates_motion_deltas(self, controller):
        """Feed three motion packets before the flush can run; they should be summed."""
        ctrl, reader = controller
        flushed_events: list[MotionEvent] = []
        original_update = ctrl.update_client

        async def capture_update(event):
            flushed_events.append(event)

        ctrl.update_client = capture_update

        # Queue three motion packets into the reader
        reader.feed_data(_make_motion_packet(100, 0, 0, 0, 0, 0))
        reader.feed_data(_make_motion_packet(100, 0, 0, 0, 0, 0))
        reader.feed_data(_make_motion_packet(100, 0, 0, 0, 0, 0))

        # Let the reader task consume all three
        read_task = asyncio.create_task(ctrl._read_spacenav_events())
        await asyncio.sleep(0.05)

        # Now flush once
        flush_task = asyncio.create_task(ctrl._flush_motion())
        await asyncio.sleep(0.05)

        read_task.cancel()
        flush_task.cancel()

        assert len(flushed_events) == 1
        assert flushed_events[0].x == 300

    @pytest.mark.asyncio
    async def test_button_not_debounced(self, controller):
        """Button events should be forwarded immediately, not accumulated."""
        ctrl, reader = controller
        button_events: list[ButtonEvent] = []

        async def capture_update(event):
            if isinstance(event, ButtonEvent):
                button_events.append(event)

        ctrl.update_client = capture_update

        reader.feed_data(_make_button_packet(0, True))
        reader.feed_data(_make_button_packet(0, False))

        read_task = asyncio.create_task(ctrl._read_spacenav_events())
        await asyncio.sleep(0.05)
        read_task.cancel()

        assert len(button_events) == 2
        assert button_events[0].pressed is True
        assert button_events[1].pressed is False
