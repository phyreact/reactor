# -*- coding: utf-8 -*-
"""MuJoCo scene + free-field acoustic propagation to the duck's 4-mic array.

What is simulated
  * The duck model (mechanical/mjcf/scene_walk.xml) posed at its STAND keyframe, optionally
    stepping physics (--dynamic) so the head really moves.
  * A ReSpeaker XVF3800 array in one of two poses:
      "hat"    : horizontal on top of the head, mics facing up, at the hat design position
                 (array centre x=+17.9 mm, z=270 mm in the model frame; mics at the true
                 (+-33.3, +-33.3) mm corners).  Azimuth 0 deg = duck forward (world -x),
                 90 deg = duck's left, counter-clockwise seen from above.  This is the
                 configuration the hardware project is building.
      "spider" : the array as it currently sits in robot_walk.xml (vertical, facing
                 forward, mics on the axes at r=33 mm).  Kept for comparison; note the
                 MJCF mic positions differ from the real board (corners vs axes).
  * Point sources (mocap bodies) with free-field propagation: 1/r spreading, exact
    fractional delay per mic, independent mic self-noise.  No reflections, no
    directivity, no head shadowing -- an anechoic room.
Output per 10 ms block: float32 (160, 4) mic signals (1.0 = full scale), plus ground
truth (source azimuth/elevation/distance in the array frame, speech-active flag).
"""
import math
import os

import mujoco
import numpy as np

from . import sources as srcmod
from .doa import MIC_XY, SR

C_SOUND = 343.0
BLOCK = SR // 100                       # 10 ms
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENE = os.path.join(REPO, "mechanical", "mjcf", "scene_walk.xml")
HEAD_BODY = "jaw_soft"                  # the head shell body (camera + speaker live here)
HAT_CENTER_MODEL = np.array([0.0179, 0.0, 0.270])   # array centre, model frame at STAND (m)


def _quat_from_mat(R):
    q = np.empty(4)
    mujoco.mju_mat2Quat(q, np.asarray(R, dtype=np.float64).reshape(9))
    return q


class AudioWorld:
    def __init__(self, scene=SCENE, array_pose="hat", dynamic=False, noise_dbfs=-75.0,
                 source_specs=None, seed=0):
        self.dynamic = dynamic
        self.noise_std = 10 ** (noise_dbfs / 20.0)
        self.rng = np.random.default_rng(seed)
        self.sources = [srcmod.make_source(s) for s in (source_specs or [])]
        self.array_pose = array_pose

        spec = mujoco.MjSpec.from_file(scene)
        # Base compile to read the head pose at the keyframe, so the hat can be placed
        # by world coordinates and attached in the head body's local frame.
        base = spec.compile()
        bd = mujoco.MjData(base)
        kf = mujoco.mj_name2id(base, mujoco.mjtObj.mjOBJ_KEY, "STAND")
        mujoco.mj_resetDataKeyframe(base, bd, kf)
        mujoco.mj_forward(base, bd)
        hid = base.body(HEAD_BODY).id
        p_head, R_head = bd.xpos[hid].copy(), bd.xmat[hid].reshape(3, 3).copy()

        if array_pose == "hat":
            # local x = world -x (forward), local y = world -y (left), local z = up
            R_w = np.array([[-1, 0, 0], [0, -1, 0], [0, 0, 1]], dtype=float).T
            pos_local = R_head.T @ (HAT_CENTER_MODEL - p_head)
            R_local = R_head.T @ R_w
            hat = spec.body(HEAD_BODY).add_body(name="hat_array", pos=pos_local, quat=_quat_from_mat(R_local))
            hat.add_geom(type=mujoco.mjtGeom.mjGEOM_CYLINDER, size=[0.05, 0.0015, 0], pos=[0, 0, -0.002],
                         rgba=[0.2, 0.5, 0.9, 0.35], contype=0, conaffinity=0, mass=0.0)
            for i, (x, y) in enumerate(MIC_XY):
                hat.add_site(name="sim_mic_%d" % i, pos=[x, y, 0.0], size=[0.003, 0, 0], rgba=[1, 1, 0, 1])
            self.array_body, self.site_names = "hat_array", ["sim_mic_%d" % i for i in range(4)]
        else:
            self.array_body, self.site_names = "respeaker", ["mic_%d" % i for i in range(4)]

        for s in self.sources:
            b = spec.worldbody.add_body(name="src_" + s.name, pos=list(s.pos), mocap=True)
            b.add_geom(type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.06, 0, 0], rgba=[1, 0.35, 0.2, 0.7],
                       contype=0, conaffinity=0, mass=0.0)

        self.model = spec.compile()
        self.data = mujoco.MjData(self.model)
        mujoco.mj_resetDataKeyframe(self.model, self.data, mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "STAND"))
        mujoco.mj_forward(self.model, self.data)
        self.site_ids = [self.model.site(n).id for n in self.site_names]
        self.array_id = self.model.body(self.array_body).id
        self.src_ids = [self.model.body("src_" + s.name).id for s in self.sources]
        self.t = 0.0                    # audio time [s]
        self.steps_per_block = max(1, int(round(BLOCK / SR / self.model.opt.timestep)))
        self.head_yaw_fn = None         # optional callable t -> ctrl for the head_yaw actuator
        self._yaw_act = self.model.actuator("head_yaw").id if dynamic else None

    # ---- geometry --------------------------------------------------------------
    def mic_positions(self):
        return np.array([self.data.site_xpos[i] for i in self.site_ids])   # (4,3) world

    def array_frame(self):
        """(centre, R) of the array: columns of R are the local x,y,z axes in world."""
        R = self.data.xmat[self.array_id].reshape(3, 3)
        return self.mic_positions().mean(axis=0), R

    def set_source_pos(self, name, pos):
        for s, bid in zip(self.sources, self.src_ids):
            if s.name == name:
                s.pos = tuple(pos)
                self.data.mocap_pos[self.model.body_mocapid[bid]] = pos

    def truth(self, src):
        """Ground truth for one source in the array frame: azimuth/elevation (deg), range (m)."""
        c, R = self.array_frame()
        v = R.T @ (np.asarray(src.pos) - c)
        r = float(np.linalg.norm(v))
        az = math.degrees(math.atan2(v[1], v[0])) % 360.0
        el = math.degrees(math.asin(v[2] / r)) if r > 0 else 0.0
        return {"az": az, "el": el, "range": r}

    def facing(self):
        """Duck forward direction (array local x for the hat pose) in world coordinates."""
        return self.array_frame()[1][:, 0]

    # ---- audio -----------------------------------------------------------------
    def step_block(self):
        """Advance one 10 ms block. Returns (mics float32 (BLOCK,4), truth dict)."""
        if self.dynamic:
            if self.head_yaw_fn is not None and self._yaw_act is not None:
                self.data.ctrl[self._yaw_act] = self.head_yaw_fn(self.t)
            for _ in range(self.steps_per_block):
                mujoco.mj_step(self.model, self.data)
        mics = self.mic_positions()
        t = self.t + np.arange(BLOCK) / SR
        out = self.rng.standard_normal((BLOCK, 4)).astype(np.float32) * self.noise_std
        active = False
        for s in self.sources:
            p = np.asarray(s.pos, dtype=float)
            active |= bool(s.active(self.t, self.t + BLOCK / SR))
            for i in range(4):
                r = float(np.linalg.norm(p - mics[i]))
                r = max(r, 0.2)
                out[:, i] += (s.signal(t - r / C_SOUND) / r).astype(np.float32)
        truth = {"t": self.t, "speech": active,
                 "sources": {s.name: self.truth(s) for s in self.sources}}
        self.t += BLOCK / SR
        return out, truth

    def beamform(self, block, az_deg):
        """Delay-and-sum toward az_deg (array frame), mono float32."""
        u = np.array([math.cos(math.radians(az_deg)), math.sin(math.radians(az_deg))])
        tau = (MIC_XY @ u) / C_SOUND                     # arrival advance per mic [s]
        n = np.arange(block.shape[0])
        acc = np.zeros(block.shape[0], dtype=np.float32)
        for i in range(4):
            d = tau[i] * SR                              # samples; positive = arrives earlier
            acc += np.interp(n + d, n, block[:, i], left=0.0, right=0.0).astype(np.float32)
        return acc / 4.0
