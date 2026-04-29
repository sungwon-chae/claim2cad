"""V13-B — scaffold registry.

Importing this package registers every Scaffold subclass via the
``@register_scaffold`` decorator. Look up a scaffold by id with
``get_scaffold(scaffold_id)`` or list available scaffolds with
``list_scaffolds()``.
"""
from claim2cad.scaffolds.base import (
    Scaffold,
    ScaffoldInput,
    ScaffoldResult,
    register_scaffold,
    get_scaffold,
    list_scaffolds,
)

# Import side-effect: registers each scaffold.
from claim2cad.scaffolds import (  # noqa: F401
    door_hinge,
    two_plate_hinge,
    bracket_mount,
    linkage,
    rotary_shaft,
    housing_panel,
    generic_exploded,
    fallback_layout,
)


__all__ = [
    "Scaffold",
    "ScaffoldInput",
    "ScaffoldResult",
    "register_scaffold",
    "get_scaffold",
    "list_scaffolds",
]
