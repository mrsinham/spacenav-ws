import asyncio
import logging
import struct
from typing import Any

import numpy as np
from scipy.spatial import transform

from spacenav_ws.spacenav import MotionEvent, ButtonEvent, from_message
from spacenav_ws.wamp import WampSession, Prefix, Call, Subscribe, CallResult


class Mouse3d:
    """This bad boy doesn't do a damn thing right now!"""

    def __init__(self):
        self.id = "mouse0"


class Controller:
    """Manage shared state and event streaming between a local 3D mouse and a remote client.

    This class subscribes clients over WAMP, tracks focus/subscription state,
    reads raw 3D mouse data from an asyncio.StreamReader, and forwards
    MotionEvent/ButtonEvent updates back to the client via RPC. It also
    provides utility methods for affine‐pivot calculations and generic
    remote_read/write operations.

    Args:
        reader (asyncio.StreamReader):
            Asynchronous stream reader for receiving raw 3D mouse packets.
        _ (Mouse3d):
            Doesn't do anything.. things should be restructured so that it does probably.
        wamp_state_handler (WampSession):
            WAMP session handler that manages subscriptions and RPC calls.
        client_metadata (dict):
            Metadata about the connected client (e.g. its name and capabilities).

    Attributes:
        id (str):
            Unique identifier for this controller instance (defaults to "controller0").
        client_metadata (dict):
            Same as the constructor arg: information about the client.
        reader (asyncio.StreamReader):
            Stream reader for incoming mouse event bytes.
        wamp_state_handler (WampSession):
            WAMP session object for subscribing and remote RPC.
        subscribed (bool):
            True once the client has subscribed to this controller’s URI.
        focus (bool):
            True when this controller is in focus and should send events.
    """

    # Base scaling factors (before user sensitivity multiplier)
    BASE_ROTATION_SCALE = 0.02
    BASE_TRANSLATION_SCALE = 0.0005
    BASE_ZOOM_SCALE = 0.001

    def __init__(self, reader: asyncio.StreamReader, _: Mouse3d, wamp_state_handler: WampSession, client_metadata: dict, sensitivity: float = 1.0, rotation_sensitivity: float = 1.0):
        self.id = "controller0"
        self.client_metadata = client_metadata
        self.reader = reader
        self.wamp_state_handler = wamp_state_handler
        self.sensitivity = sensitivity
        self.rotation_sensitivity = rotation_sensitivity

        self.wamp_state_handler.wamp.subscribe_handlers[self.controller_uri] = self.subscribe
        self.wamp_state_handler.wamp.call_handlers["wss://127.51.68.120/3dconnexion#update"] = self.client_update

        self.subscribed = False
        self.focus = False

    async def subscribe(self, msg: Subscribe):
        """When a subscription request for self.controller_uri comes in we start broadcasting!"""
        logging.info("handling subscribe %s", msg)
        self.subscribed = True
        self.focus = True

    async def client_update(self, controller_id: str, args: dict[str, Any]):
        # TODO Maybe use some more of this data that the client sends our way?
        logging.debug("Got update for '%s': %s, THESE ARE DROPPED FOR NOW!", controller_id, args)
        if (focus := args.get("focus")) is not None:
            self.focus = focus

    @property
    def controller_uri(self) -> str:
        return f"wss://127.51.68.120/3dconnexion3dcontroller/{self.id}"

    async def remote_write(self, *args):
        return await self.wamp_state_handler.client_rpc(self.controller_uri, "self:update", *args)

    async def remote_read(self, *args):
        return await self.wamp_state_handler.client_rpc(self.controller_uri, "self:read", *args)

    async def start_mouse_event_stream(self):
        """Read spacenav events and forward them to the browser client.

        Motion events are accumulated (deltas summed) and flushed only as
        fast as the browser RPC round-trips allow.  Button events are
        forwarded immediately.
        """
        logging.info("Starting the mouse stream")
        self._pending_motion: MotionEvent | None = None
        self._motion_ready = asyncio.Event()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._read_spacenav_events())
            tg.create_task(self._flush_motion())

    async def _read_spacenav_events(self):
        while True:
            raw = await self.reader.read(32)
            if not (self.focus and self.subscribed):
                continue
            nums = struct.unpack("iiiiiiii", raw)
            event = from_message(list(nums))

            if isinstance(event, ButtonEvent):
                if self.client_metadata["name"] in ["Onshape", "WebThreeJS Sample"]:
                    await self.update_client(event)
                else:
                    logging.warning("Unknown client! Cannot send mouse events, client_metadata:%s", self.client_metadata)
            elif isinstance(event, MotionEvent):
                pending = self._pending_motion
                if pending is None:
                    self._pending_motion = event
                else:
                    self._pending_motion = MotionEvent(
                        x=pending.x + event.x,
                        y=pending.y + event.y,
                        z=pending.z + event.z,
                        pitch=pending.pitch + event.pitch,
                        yaw=pending.yaw + event.yaw,
                        roll=pending.roll + event.roll,
                        period=event.period,
                    )
                self._motion_ready.set()

    async def _flush_motion(self):
        while True:
            await self._motion_ready.wait()
            self._motion_ready.clear()
            event = self._pending_motion
            self._pending_motion = None
            if event is not None and self.client_metadata["name"] in ["Onshape", "WebThreeJS Sample"]:
                await self.update_client(event)

    @staticmethod
    def get_affine_pivot_matrices(model_extents):
        min_pt = np.array(model_extents[0:3], dtype=np.float32)
        max_pt = np.array(model_extents[3:6], dtype=np.float32)
        pivot = (min_pt + max_pt) * 0.5

        pivot_pos = np.eye(4, dtype=np.float32)
        pivot_pos[3, :3] = pivot
        pivot_neg = np.eye(4, dtype=np.float32)
        pivot_neg[3, :3] = -pivot
        return pivot_pos, pivot_neg

    async def update_client(self, event: MotionEvent | ButtonEvent):
        """
        This send mouse events over to the client. Currently just a few properties are used but more are avaialable:
        view.target, view.constructionPlane, view.extents, view.affine, view.perspective, model.extents, selection.empty, selection.extents, hit.lookat, views.front

        """
        model_extents = await self.remote_read("model.extents")

        if isinstance(event, ButtonEvent):
            # Reset rotation to front view, but keep the current camera distance
            curr_affine = np.asarray(await self.remote_read("view.affine"), dtype=np.float32).reshape(4, 4)
            front = np.eye(4, dtype=np.float32)
            front[3, :] = curr_affine[3, :]  # preserve camera position and w
            await self.remote_write("view.affine", front.reshape(-1).tolist())
            return

        # 1) pull down the current extents and model matrix
        perspective = await self.remote_read("view.perspective")
        curr_affine = np.asarray(await self.remote_read("view.affine"), dtype=np.float32).reshape(4, 4)

        # Extract camera-to-world rotation from the view matrix (transpose of
        # the top-left 3x3). Re-orthogonalize via SVD to counter float32 drift
        # that accumulates over many incremental read-modify-write cycles.
        R_cam = curr_affine[:3, :3].T
        U, _, Vt = np.linalg.svd(R_cam)
        R_cam = U @ Vt

        # 2) Separately calculate rotation and translation matrices
        angles = np.array([event.pitch, event.yaw, -event.roll]) * self.BASE_ROTATION_SCALE * self.rotation_sensitivity
        R_delta_cam = transform.Rotation.from_euler("xyz", angles, degrees=True).as_matrix()
        R_world = R_cam @ R_delta_cam @ R_cam.T

        rot_delta = np.eye(4, dtype=np.float32)
        rot_delta[:3, :3] = R_world
        trans_delta = np.eye(4, dtype=np.float32)
        zoom_factor = self.BASE_ZOOM_SCALE / self.BASE_TRANSLATION_SCALE  # zoom scales faster than pan
        trans_delta[3, :3] = np.array([-event.x, -event.y, -event.z * zoom_factor], dtype=np.float32) * self.BASE_TRANSLATION_SCALE * self.sensitivity

        # 3) Apply changes to the ModelViewProjection matrix
        pivot_pos, pivot_neg = self.get_affine_pivot_matrices(model_extents)
        new_affine = trans_delta @ curr_affine @ (pivot_neg @ rot_delta @ pivot_pos)

        # Write back changes and optionally update extents if the projection is orthographic!
        if not perspective:
            extents = await self.remote_read("view.extents")
            zoom_delta = -event.z * self.BASE_ZOOM_SCALE * self.sensitivity
            scale = 1.0 + zoom_delta
            new_extents = [c * scale for c in extents]
            await self.remote_write("motion", True)
            await self.remote_write("view.extents", new_extents)
        else:
            await self.remote_write("motion", True)
        await self.remote_write("view.affine", new_affine.reshape(-1).tolist())


async def create_mouse_controller(wamp_state_handler: WampSession, spacenav_reader: asyncio.StreamReader, sensitivity: float = 1.0, rotation_sensitivity: float = 1.0) -> Controller:
    """
    This takes in an active websocket wrapped in a wampsession, it consumes the first couple of messages that form a sort of pseudo handshake..
    When all is said is done it returns an active controller!
    """
    await wamp_state_handler.wamp.begin()
    # The first three messages are typically prefix setters!
    msg = await wamp_state_handler.wamp.next_message()
    while isinstance(msg, Prefix):
        await wamp_state_handler.wamp.run_message_handler(msg)
        msg = await wamp_state_handler.wamp.next_message()

    # The first call after the prefixes must be 'create mouse'
    assert isinstance(msg, Call)
    assert msg.proc_uri == "3dx_rpc:create" and msg.args[0] == "3dconnexion:3dmouse"
    mouse = Mouse3d()  # There is really no point to this lol
    logging.info(f'Created 3d mouse "{mouse.id}" for version {msg.args[1]}')
    await wamp_state_handler.wamp.send_message(CallResult(msg.call_id, {"connexion": mouse.id}))

    # And the second call after the prefixes must be 'create controller'
    msg = await wamp_state_handler.wamp.next_message()
    assert isinstance(msg, Call)
    assert msg.proc_uri == "3dx_rpc:create" and msg.args[0] == "3dconnexion:3dcontroller" and msg.args[1] == mouse.id
    metadata = msg.args[2]
    controller = Controller(spacenav_reader, mouse, wamp_state_handler, metadata, sensitivity, rotation_sensitivity)
    logging.info(f'Created controller "{controller.id}" for mouse "{mouse.id}", for client "{metadata["name"]}", version "{metadata["version"]}"')

    await wamp_state_handler.wamp.send_message(CallResult(msg.call_id, {"instance": controller.id}))
    return controller
