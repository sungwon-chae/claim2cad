"""Parameterized mechanical-component library for v1.1 figure-driven CAD.

Each component is a build123d-backed factory keyed by a string name in
:mod:`claim2cad.components.library`. The figure-to-CAD generator picks a
library entry per claim component, instantiates it with VLM-extracted
parameters, and tags the resulting solid so the GLB exporter preserves
component-id node names (the v1.0 contract).

Importing this package eagerly registers every shipped component so that
``library.lookup(...)`` works without callers having to remember to import
sub-modules.
"""
from __future__ import annotations

from claim2cad.components import library  # noqa: F401  — public API
from claim2cad.components.base import Component, ComponentBuildError  # noqa: F401

# Eagerly import every component module so its @register decorator runs.
from claim2cad.components.primitives import plate as _plate  # noqa: F401
from claim2cad.components.primitives import rod as _rod  # noqa: F401
from claim2cad.components.primitives import bracket as _bracket  # noqa: F401
from claim2cad.components.primitives import pin as _pin  # noqa: F401
from claim2cad.components.joints import hinge as _hinge  # noqa: F401
from claim2cad.components.joints import revolute as _revolute  # noqa: F401
from claim2cad.components.joints import prismatic as _prismatic  # noqa: F401
from claim2cad.components.joints import lift_off_hinge as _lift_off_hinge  # noqa: F401
from claim2cad.components.joints import hinge_primitives as _hinge_primitives  # noqa: F401
from claim2cad.components.transmission import gear as _gear  # noqa: F401
from claim2cad.components.transmission import bearing as _bearing  # noqa: F401
from claim2cad.components.fasteners import spring as _spring  # noqa: F401

__all__ = ["Component", "ComponentBuildError", "library"]
