"""Small blocky Pal for utility screens. Coordinates are relative to a 30 x 28 box."""

WIDTH = 30
HEIGHT = 28


def draw(canvas, x, y, pose, phase=0):
    """Draw a contextual crab using rectangles only; phase alternates two quiet frames."""
    step = phase % 2
    def block(bx, by, width, height, color=1):
        canvas.fill_rect(x + bx, y + by, width, height, color)

    # The same broad square shell, detached claws, short feet and cut-out eyes as the large Pal.
    block(4, 4, 22, 15)
    block(0, 10 - (2 if pose in ("alert", "done") else 0), 4, 7)
    block(26, 10 - (2 if pose in ("music", "done") and step else 0), 4, 7)
    for foot in (6, 12, 18, 24):
        block(foot, 19, 3, 5)
    block(8, 9, 4, 4, 0)
    block(19, 9, 4, 4 if pose != "focus" else 2, 0)
    block(13, 15, 4, 2, 0)

    if pose == "limits":
        block(7, 26, 4, 2)
        block(13, 25, 4, 3)
        block(19, 24, 4, 4)
    elif pose == "today":
        block(24, 0, 4, 3)
        block(26, 3, 2, 2)
    elif pose == "focus":
        block(13, 0, 4, 3)
        block(17, 1, 2, 2)
    elif pose == "music":
        block(22, 0 if step else 1, 2, 6)
        block(18, 4 if step else 5, 4, 2)
    elif pose == "flights":
        block(12, 0, 7, 2)
        block(15, 2, 2, 2)
    elif pose == "tracking":
        block(23, 0, 2, 4)
        block(21, 2, 6, 2)
    elif pose == "alert":
        block(14, 0, 3, 3)
        block(15, 26, 2, 2)
    elif pose == "done":
        block(10, 25, 4, 2)
        block(14, 26, 4, 2)
        block(18, 24, 5, 2)
    else:
        raise ValueError("unknown Pal pose: " + str(pose))
