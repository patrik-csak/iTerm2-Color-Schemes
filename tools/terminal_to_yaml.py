#!/usr/bin/env python3
# Convert macOS Terminal.app .terminal profiles in apple-terminal-profiles/
# to the project's YAML spec, written to yaml/.
#
# Modern Terminal.app writes colors with a custom sRGB color space — those go
# through pure Python. Legacy Calibrated/Device RGB profiles shell out to
# osascript so Apple's own ColorSync does the conversion (macOS-only path).

import plistlib
import subprocess
from pathlib import Path

REPO_PATH = Path(__file__).parent.parent
SOURCE_PATH = REPO_PATH / "apple-terminal-profiles"
TARGET_PATH = REPO_PATH / "yaml"

# Terminal.app's default cursor color (146/146/146 in sRGB) — used when a
# profile inherits the system default instead of overriding it.
DEFAULT_CURSOR = "#929292"

ANSI_COLORS = [
    ("color_01", "ANSIBlackColor"),
    ("color_02", "ANSIRedColor"),
    ("color_03", "ANSIGreenColor"),
    ("color_04", "ANSIYellowColor"),
    ("color_05", "ANSIBlueColor"),
    ("color_06", "ANSIMagentaColor"),
    ("color_07", "ANSICyanColor"),
    ("color_08", "ANSIWhiteColor"),
    ("color_09", "ANSIBrightBlackColor"),
    ("color_10", "ANSIBrightRedColor"),
    ("color_11", "ANSIBrightGreenColor"),
    ("color_12", "ANSIBrightYellowColor"),
    ("color_13", "ANSIBrightBlueColor"),
    ("color_14", "ANSIBrightMagentaColor"),
    ("color_15", "ANSIBrightCyanColor"),
    ("color_16", "ANSIBrightWhiteColor"),
]


def color_space_name(root):
    if "NSCustomColorSpace" in root:
        return "custom/sRGB"
    return {1: "calibrated RGB", 2: "device RGB"}.get(root.get("NSColorSpace"), "unknown")


def parse_numbers(value):
    text = value.decode("ascii").strip("\x00")
    return [float(component) for component in text.split()]


def convert_to_srgb(red, green, blue, space):
    if space == "custom/sRGB":
        return red, green, blue

    kind = "Calibrated" if space == "calibrated RGB" else "Device"
    script = (
        'ObjC.import("AppKit");'
        "function run(argv) {"
        f"const color = $.NSColor.colorWith{kind}RedGreenBlueAlpha(Number(argv[0]), Number(argv[1]), Number(argv[2]), 1);"
        "const srgb = color.colorUsingColorSpace($.NSColorSpace.sRGBColorSpace);"
        'return [srgb.redComponent, srgb.greenComponent, srgb.blueComponent].join(" ");'
        "}"
    )
    output = subprocess.check_output(
        ["osascript", "-l", "JavaScript", "-e", script, str(red), str(green), str(blue)],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return tuple(float(component) for component in output.split())


def hex_from_components(red, green, blue):
    return "#" + "".join(
        f"{round(max(0.0, min(1.0, component)) * 255):02X}"
        for component in (red, green, blue)
    )


def parse_color(data):
    archive = plistlib.loads(data)
    root = archive["$objects"][archive["$top"]["root"].data]
    if "NSRGB" in root:
        red, green, blue = parse_numbers(root["NSRGB"])[:3]
    elif "NSComponents" in root:
        # 4 values = R G B alpha; 2 values = gray alpha; 3 = R G B; 1 = gray.
        components = parse_numbers(root["NSComponents"])
        if len(components) >= 3:
            red, green, blue = components[:3]
        else:
            red = green = blue = components[0]
    else:
        return None
    return hex_from_components(*convert_to_srgb(red, green, blue, color_space_name(root)))


def parse_profile(path):
    profile = plistlib.loads(path.read_bytes())
    colors = {
        key: parse_color(value)
        for key, value in profile.items()
        if key.endswith("Color") and isinstance(value, bytes)
    }
    return profile["name"], colors


def render_yaml(name, colors, variant):
    def required(key):
        if key not in colors:
            raise ValueError(f"{name!r} is missing {key}")
        return colors[key]

    background = required("BackgroundColor")
    foreground = required("TextColor")
    lines = [f'name: "{name}"', f'variant: "{variant}"', ""]
    for index, (yaml_key, profile_key) in enumerate(ANSI_COLORS):
        if index == 8:
            lines.append("")
        lines.append(f'{yaml_key}: "{required(profile_key)}"')
    lines += [
        "",
        f'background: "{background}"',
        f'foreground: "{foreground}"',
        f'cursor: "{colors.get("CursorColor", DEFAULT_CURSOR)}"',
        f'link: "{required("ANSIBlueColor")}"',
        f'selection: "{required("SelectionColor")}"',
        f'bold: "{required("TextBoldColor")}"',
        "",
        f'cursor_text: "{foreground}"',
        f'cursor_guide: "{required("SelectionColor")}"',
        f'selection_text: "{foreground}"',
        "",
    ]
    return "\n".join(lines)


def main():
    sources = [
        {"file": "Clear Dark.terminal", "variant": "Dark"},
        {"file": "Clear Light.terminal", "variant": "Light"},
    ]
    for source in sources:
        path = SOURCE_PATH / source["file"]
        name, colors = parse_profile(path)
        output = TARGET_PATH / f"{path.stem}.yml"
        output.write_text(render_yaml(name, colors, source["variant"]), encoding="utf-8")
        print(f"Wrote {output.relative_to(REPO_PATH)}")


if __name__ == "__main__":
    main()
