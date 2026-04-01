"""Tests for spacenav event parsing."""

from spacenav_ws.spacenav import from_message, MotionEvent, ButtonEvent


class TestFromMessage:
    def test_motion_event(self):
        # type=0 means motion, followed by x,z,y,pitch,yaw,roll,period
        msg = [0, 100, 200, 300, 10, 20, 30, 16]
        event = from_message(msg)
        assert isinstance(event, MotionEvent)
        assert event.x == 100
        assert event.z == 200
        assert event.y == 300
        assert event.pitch == 10
        assert event.yaw == 20
        assert event.roll == 30
        assert event.period == 16
        assert event.type == "mtn"

    def test_motion_event_zeros(self):
        msg = [0, 0, 0, 0, 0, 0, 0, 0]
        event = from_message(msg)
        assert isinstance(event, MotionEvent)
        assert event.x == 0 and event.y == 0 and event.z == 0

    def test_motion_event_negative_values(self):
        msg = [0, -350, -200, -100, -5, -10, -15, 16]
        event = from_message(msg)
        assert isinstance(event, MotionEvent)
        assert event.x == -350
        assert event.z == -200
        assert event.y == -100

    def test_button_press(self):
        # type=1 means button press
        msg = [1, 0, 0, 0, 0, 0, 0, 0]
        event = from_message(msg)
        assert isinstance(event, ButtonEvent)
        assert event.button_id == 0
        assert event.pressed is True
        assert event.type == "btn"

    def test_button_release(self):
        # type=2 means button release
        msg = [2, 0, 0, 0, 0, 0, 0, 0]
        event = from_message(msg)
        assert isinstance(event, ButtonEvent)
        assert event.button_id == 0
        assert event.pressed is False

    def test_button_press_different_ids(self):
        for btn_id in [0, 1, 2, 5, 15]:
            msg = [1, btn_id, 0, 0, 0, 0, 0, 0]
            event = from_message(msg)
            assert event.button_id == btn_id
