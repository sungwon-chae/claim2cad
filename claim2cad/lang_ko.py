"""Korean (KO) deterministic parsing rules for patent claims.

Korean mechanical claims (KIPRIS / KIPO style) follow a different surface
form from US claims:

* Numbered with ``【청구항 N】`` or ``N.`` prefixes.
* The preamble appears at the *end* (``...를 포함하는 X.`` /
  ``...을 구비하는 X.``), not after a leading "comprising:".
* Element separators are ``;`` and the connective ``및`` (and).
* Dependent claims use ``제N항에 따른`` (according to claim N) /
  ``제N항의`` (of claim N).

The rules here are deliberately small — enough to support the
deterministic V1-7 baseline. The same pipeline still falls back to the
LLM path when configured (the LLM gets a language hint via the
``language`` field on :class:`claim2cad.claim_segmenter.ClaimSegments`).
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Claim splitting
# ---------------------------------------------------------------------------

# Match ``【청구항 N】`` (with optional whitespace) or ``N.`` at line start.
CLAIM_SPLIT_RE = re.compile(
    r"(?m)^(?:【\s*청구항\s*(\d+)\s*】|(\d+)\s*\.)\s*",
)

# Dependent claim header: ``제N항에 따른``, ``제N항의``, ``청구항 N항에 따른``.
DEPENDENT_RE = re.compile(
    r"(?:청구항\s*)?제?\s*(\d+)\s*항(?:\s*에\s*따른|\s*의|\s*에\s*있어서)",
)

# Trailing preamble: ``...를 포함하는 X``, ``...을 구비하는 X``,
# ``...로 이루어진 X``. Captures the noun phrase X *and* the connector verb.
# The noun phrase explicitly forbids further preamble verbs so we always
# pick the *last* verb before end-of-text (Korean claims typically have
# nested verbs inside elements, e.g. "구성된 ... 구비하는 매니퓰레이터").
_PREAMBLE_VERBS_GROUP = r"(포함하는|구비하는|이루어진|이루어지는|구성된|구성되는)"
PREAMBLE_TAIL_RE = re.compile(
    r"[를을]?\s*"
    + _PREAMBLE_VERBS_GROUP
    + r"\s+((?:(?!"
    + _PREAMBLE_VERBS_GROUP
    + r").)+?)\s*[.。]?\s*$",
    re.DOTALL,
)

# Element separator: ``;`` plus optional ``및`` ("and"). Korean writers also
# split on commas + 및, but inside this minimal baseline we require ``;`` so
# we don't accidentally split on commas inside a single element.
ELEMENT_SPLIT_RE = re.compile(r"\s*;\s*(?:및\s*)?")

# Korean relative-clause verbs that introduce the head noun at the *end* of
# an element. Korean grammar puts the modifier first, the head noun last:
# ``[상기 베이스에 회전 가능하게 결합된] [제1 링크]``. To find the head, we
# scan for the *last* relative-clause verb and take everything after it.
RELATIVE_CLAUSE_VERBS = re.compile(
    r"(?:"
    r"결합된|결합되는|결합되어|"
    r"연결된|연결되는|연결되어|"
    r"부착된|부착되는|"
    r"고정된|고정되는|"
    r"장착된|장착되는|"
    r"설치된|설치되는|"
    r"체결된|체결되는|"
    r"형성된|형성되는|"
    r"배치된|배치되는|"
    r"구성된|구성되는|"
    r"제공된|제공되는|"
    r"마련된|마련되는|"
    r"이루어진|이루어지는|"
    r"포함하는|포함하며|"
    r"구비하는|구비하며|"
    r"있는|"
    r"가지는|갖는"
    r")\s*"
)

# Particles that follow a non-head noun in Korean. After the first match
# (when there's no relative-clause verb), the leading noun has ended.
HEAD_NP_TERMINATORS = re.compile(
    r"(?:"
    r"에\s+|"           # locative particle
    r"의\s+|"           # possessive
    r"으로\s+|로\s+|"   # instrumental
    r"와\s+|과\s+|"     # conjunctive
    r"이\s+|가\s+|"     # nominative
    r"을\s+|를\s+|"     # accusative
    r"는\s+|은\s+|"     # topic
    r"회전\s+가능하게|"
    r"이동\s+가능하게|"
    r"슬라이딩\s+가능하게|"
    r"피벗\s+가능하게"
    r")"
)

# Strip Korean demonstratives from the head: ``상기`` (the aforementioned),
# ``일``, ``하나의`` (a / one).
LEADING_DEMONSTRATIVE = re.compile(
    r"^\s*(?:상기|일|하나의|소정의|적어도\s+하나의)\s+",
)

# Ordinal prefixes: ``제1``, ``제 1``, ``제1의``.
ORDINAL_PREFIX = re.compile(r"제\s*(\d+)\s*(?:의\s+)?")


# ---------------------------------------------------------------------------
# Head-noun translation for slug generation
# ---------------------------------------------------------------------------

# Component IDs must match ``^[a-z][a-z0-9_]*$``; Hangul cannot appear in IDs.
# This table romanises the most common mechanical terms found in Korean
# claims. Anything missing falls back to ``comp_<n>`` numbering in the
# parser.
HEAD_TRANSLATIONS: dict[str, str] = {
    "베이스": "base",
    "본체": "body",
    "프레임": "frame",
    "하우징": "housing",
    "케이스": "casing",
    "커버": "cover",
    "쉘": "shell",
    "링크": "link",
    "암": "arm",
    "로드": "rod",
    "샤프트": "shaft",
    "축": "shaft",
    "기둥": "column",
    "플레이트": "plate",
    "디스크": "disc",
    "조인트": "joint",
    "관절": "joint",
    "회전축": "rotational_axis",
    "회전관절": "revolute_joint",
    "회전 관절": "revolute_joint",
    "직동관절": "prismatic_joint",
    "직동 관절": "prismatic_joint",
    "구관절": "spherical_joint",
    "구 관절": "spherical_joint",
    "결합부": "joint",
    "연결부": "connector",
    "지지부": "support",
    "베어링": "bearing",
    "기어": "gear",
    "체결구": "fastener",
    "볼트": "bolt",
    "나사": "screw",
    "리벳": "rivet",
    "센서": "sensor",
    "엔코더": "encoder",
    "모터": "motor",
    "액추에이터": "actuator",
    "서보": "servo",
    "그리퍼": "gripper",
    "핑거": "finger",
    "엔드이펙터": "end_effector",
    "엔드 이펙터": "end_effector",
    "엔드 이팩터": "end_effector",
    "제어부": "controller",
    "제어기": "controller",
    "컨트롤러": "controller",
    "매니퓰레이터": "manipulator",
    "로봇": "robot",
    "로봇팔": "robot_arm",
    "로봇 팔": "robot_arm",
}

# Ordinal translations.
ORDINAL_TRANSLATIONS: dict[int, str] = {
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
    9: "ninth",
    10: "tenth",
}


# ---------------------------------------------------------------------------
# Kind classification heuristics — Korean
# ---------------------------------------------------------------------------

# Order matters: most specific first. Each pattern is matched against the
# *Korean* head noun phrase before romanisation.
KIND_HEURISTICS: list[tuple[str, str, str]] = [
    # Connections — specific joints first.
    (r"회전\s*관절|회전\s*조인트", "connection", "revolute_joint"),
    (r"직동\s*관절|직동\s*조인트|선형\s*관절", "connection", "prismatic_joint"),
    (r"구\s*관절|볼\s*조인트", "connection", "spherical_joint"),
    (r"관절|조인트|결합부|연결부", "connection", "fixed_joint"),
    (r"체결구|볼트|나사|리벳|핀", "connection", "fastener"),
    # Functional.
    (r"센서|엔코더", "functional", "sensor"),
    (r"모터|액추에이터|서보", "functional", "actuator"),
    (r"엔드\s*이펙터|엔드\s*이팩터|그리퍼", "functional", "end_effector"),
    (r"제어부|제어기|컨트롤러", "functional", "controller"),
    # Structural.
    (r"기어", "structural", "frame"),
    (r"축|샤프트", "structural", "rod"),
    (r"링크|암|로드", "structural", "rod"),
    (r"플레이트|디스크", "structural", "plate"),
    (r"하우징|케이스|본체", "structural", "housing"),
    (r"프레임|베이스|기저부", "structural", "frame"),
    (r"쉘|커버|덮개", "structural", "shell"),
]


# ---------------------------------------------------------------------------
# Embedded joints — Korean
# ---------------------------------------------------------------------------

# Captures phrases like ``회전 가능하게 결합된`` (rotatably coupled),
# implying a revolute joint between two components even when no explicit
# noun appears.
EMBEDDED_JOINT_HINTS: list[tuple[str, str]] = [
    (r"회전\s*가능하게\s*(?:결합|연결|장착|설치|부착|체결)", "revolute_joint"),
    (r"이동\s*가능하게\s*(?:결합|연결|장착|설치)", "prismatic_joint"),
    (r"슬라이딩\s*가능하게\s*(?:결합|연결|장착|설치)", "prismatic_joint"),
    (r"피벗\s*가능하게\s*(?:결합|연결)", "revolute_joint"),
]


__all__ = [
    "CLAIM_SPLIT_RE",
    "DEPENDENT_RE",
    "PREAMBLE_TAIL_RE",
    "ELEMENT_SPLIT_RE",
    "HEAD_NP_TERMINATORS",
    "RELATIVE_CLAUSE_VERBS",
    "LEADING_DEMONSTRATIVE",
    "ORDINAL_PREFIX",
    "HEAD_TRANSLATIONS",
    "ORDINAL_TRANSLATIONS",
    "KIND_HEURISTICS",
    "EMBEDDED_JOINT_HINTS",
]
