"""Animation name-to-path mapping for Pepper's ALAnimationPlayer."""

# Maps user-friendly names (case-insensitive lookup) to NAOqi animation paths.
# Standard animations use ALAnimationPlayer.run(path).
# Custom behaviors (prefixed with BEHAVIOR_PREFIX) use ALBehaviorManager.runBehavior(path).
ANIMATIONS = {
    "Yes": "animations/Stand/Gestures/Yes_1",
    "No1": "animations/Stand/Gestures/IDontKnow_2",
    "No2": "animations/Stand/Gestures/No_8",
    "Hey": "animations/Stand/Gestures/Hey_1",
    "Wave": "animations/Stand/Gestures/Hey_3",
    "Me": "animations/Stand/Gestures/Me_2",
    "You": "animations/Stand/Gestures/You_1",
    "Stop": "masterarbeit-pepper/behavior_stop",
    "ShowLeft": "masterarbeit-pepper/behavior_show_left",
    "ShowRight": "masterarbeit-pepper/behavior_show_right",
    "ShowFloor": "animations/Stand/Gestures/ShowFloor_1",
    "ShowTablet": "animations/Stand/Gestures/ShowTablet_2",
    "Far1": "animations/Stand/Gestures/Far_1",
    "Far2": "animations/Stand/Gestures/Far_3",
    "Explain1": "animations/Stand/Gestures/Explain_1",
    "Explain2": "animations/Stand/Gestures/Explain_11",
    "Nod": "animations/Stand/Emotions/Positive/Happy_4",
    "Unsure": "animations/Stand/Gestures/IDontKnow_1",
    "Bow": "animations/Stand/Gestures/BowShort_1",
    "Disappointed": "animations/Stand/Emotions/Negative/Bored_1",
    "CalmDown": "animations/Stand/Gestures/CalmDown_1",
    "Desperate": "animations/Stand/Gestures/Desperate_1",
    "Upset": "animations/Stand/Gestures/YouKnowWhat_1",
}

_ANIMATIONS_LOWER = {k.lower(): v for k, v in ANIMATIONS.items()}

BEHAVIOR_PREFIX = "masterarbeit-pepper"


def resolve_animation(name: str) -> str:
    """Resolve a friendly animation name to a NAOqi path.

    Accepts either a friendly name (e.g., "Yes", "wave") or a raw NAOqi path
    (e.g., "animations/Stand/Gestures/Yes_1"). Case-insensitive for friendly names.

    Raises:
        ValueError: If the name is not recognized and does not look like a raw path.
    """
    lower = name.lower()
    if lower in _ANIMATIONS_LOWER:
        return _ANIMATIONS_LOWER[lower]
    if name.startswith("animations/") or "/" in name:
        return name
    raise ValueError(
        f"Unknown animation '{name}'. "
        f"Valid names: {', '.join(ANIMATIONS.keys())}"
    )


def is_behavior(path: str) -> bool:
    """Check if an animation path is a custom behavior (not ALAnimationPlayer)."""
    return path.startswith(BEHAVIOR_PREFIX)
