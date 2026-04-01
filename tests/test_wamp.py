"""Tests for WAMP protocol message handling."""

import pytest

from spacenav_ws.wamp import (
    WAMP_MSG_TYPE,
    WampMessage,
    Welcome,
    Prefix,
    Call,
    CallResult,
    CallError,
    Subscribe,
    Unsubscribe,
    Publish,
    Event,
    WampProtocol,
)


class TestWampMessageSerialization:
    def test_welcome_serialize(self):
        msg = Welcome("session123", 1, "server v1")
        assert msg.serialize_with_msg_id() == [0, "session123", 1, "server v1"]

    def test_prefix_serialize(self):
        msg = Prefix("3dx_rpc", "wss://127.51.68.120/3dconnexion#")
        assert msg.serialize_with_msg_id() == [1, "3dx_rpc", "wss://127.51.68.120/3dconnexion#"]

    def test_call_serialize(self):
        msg = Call("call123", "3dx_rpc:create", "3dconnexion:3dmouse", "0.3.11")
        serialized = msg.serialize_with_msg_id()
        assert serialized[0] == 2
        assert serialized[1] == "call123"
        assert serialized[2] == "3dx_rpc:create"
        assert serialized[3] == "3dconnexion:3dmouse"
        assert serialized[4] == "0.3.11"

    def test_call_create_generates_id(self):
        msg = Call.create("3dx_rpc:create", "arg1")
        assert len(msg.call_id) == 18
        assert msg.proc_uri == "3dx_rpc:create"
        assert msg.args == ["arg1"]

    def test_call_result_serialize(self):
        msg = CallResult("call123", {"connexion": "mouse0"})
        assert msg.serialize_with_msg_id() == [3, "call123", {"connexion": "mouse0"}]

    def test_call_error_serialize(self):
        msg = CallError("call123", "wamp.error.not_found", "not found")
        serialized = msg.serialize_with_msg_id()
        assert serialized[0] == 4
        assert serialized[1] == "call123"
        assert serialized[3] == "not found"

    def test_subscribe_serialize(self):
        msg = Subscribe("some:topic")
        assert msg.serialize_with_msg_id() == [5, "some:topic"]

    def test_event_serialize(self):
        msg = Event("topic", {"data": 42})
        assert msg.serialize_with_msg_id() == [8, "topic", {"data": 42}]


class TestWampMessageRegistry:
    def test_all_types_registered(self):
        expected = {
            WAMP_MSG_TYPE.WELCOME,
            WAMP_MSG_TYPE.PREFIX,
            WAMP_MSG_TYPE.CALL,
            WAMP_MSG_TYPE.CALLRESULT,
            WAMP_MSG_TYPE.CALLERROR,
            WAMP_MSG_TYPE.SUBSCRIBE,
            WAMP_MSG_TYPE.UNSUBSCRIBE,
            WAMP_MSG_TYPE.PUBLISH,
            WAMP_MSG_TYPE.EVENT,
        }
        assert set(WampMessage.REGISTRY.keys()) == expected

    def test_registry_roundtrip_prefix(self):
        """Deserialize from raw JSON list like a real client would send."""
        raw = [1, "3dx_rpc", "wss://127.51.68.120/3dconnexion#"]
        msg_type = WAMP_MSG_TYPE(raw[0])
        msg = WampMessage.REGISTRY[msg_type](*raw[1:])
        assert isinstance(msg, Prefix)
        assert msg.prefix == "3dx_rpc"

    def test_registry_roundtrip_call(self):
        raw = [2, "0.3uy1h4l77rf", "3dx_rpc:create", "3dconnexion:3dmouse", "0.3.11"]
        msg_type = WAMP_MSG_TYPE(raw[0])
        msg = WampMessage.REGISTRY[msg_type](*raw[1:])
        assert isinstance(msg, Call)
        assert msg.call_id == "0.3uy1h4l77rf"
        assert msg.proc_uri == "3dx_rpc:create"

    def test_registry_roundtrip_subscribe(self):
        raw = [5, "3dconnexion:3dcontroller/controller0"]
        msg_type = WAMP_MSG_TYPE(raw[0])
        msg = WampMessage.REGISTRY[msg_type](*raw[1:])
        assert isinstance(msg, Subscribe)


class TestWampProtocolResolve:
    """Test prefix resolution without needing a websocket."""

    def test_resolve_with_prefix(self):
        proto = WampProtocol.__new__(WampProtocol)
        proto.prefixes = {"3dx_rpc": "wss://127.51.68.120/3dconnexion#"}
        assert proto.resolve("3dx_rpc:create") == "wss://127.51.68.120/3dconnexion#create"

    def test_resolve_without_matching_prefix(self):
        proto = WampProtocol.__new__(WampProtocol)
        proto.prefixes = {}
        assert proto.resolve("unknown:thing") == "thing"
