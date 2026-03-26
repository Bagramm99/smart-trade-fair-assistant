"""
PyPepper Interactive Test Runner

Walk through all robot features one step at a time.
At each prompt:
  Enter   → run the action
  s       → skip this action
  S       → skip the rest of this section
  q       → quit the test
"""

import sys
from pypepper import PepperRobot

ROBOT_IP = "172.30.36.41"
LOCAL_IP = "172.30.36.227"

# ─────────────────────────────────────────────────────────────────────────────
# Terminal helpers
# ─────────────────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"

def header(title):
    width = 60
    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}")

def info(msg):
    print(f"  {DIM}{msg}{RESET}")

def ok(msg):
    print(f"  {GREEN}✓ {msg}{RESET}")

def warn(msg):
    print(f"  {YELLOW}! {msg}{RESET}")

def err(msg):
    print(f"  {RED}✗ {msg}{RESET}")

def yn(question):
    """Ask a yes/no question. Returns True for yes."""
    while True:
        answer = input(f"\n  {BOLD}{question} [y/n]: {RESET}").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False

# ─────────────────────────────────────────────────────────────────────────────
# Step runner
# ─────────────────────────────────────────────────────────────────────────────

_skip_section = False

def step(description, action):
    """
    Print description, wait for user input, then run action.

    Returns True if the action ran, False if it was skipped.
    Raises SystemExit if the user quits.
    """
    global _skip_section

    if _skip_section:
        return False

    print(f"\n  {BOLD}▶ {description}{RESET}")
    print(f"  {DIM}Enter=run  s=skip  S=skip section  q=quit{RESET}", end="  ")
    try:
        raw = input().strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    choice = raw.lower()

    if choice == "q":
        print(f"\n{YELLOW}Quit requested.{RESET}")
        sys.exit(0)
    if raw == "S":
        warn("Skipping rest of section.")
        _skip_section = True
        return False
    if choice == "s":
        warn("Skipped.")
        return False

    try:
        result = action()
        if result is not None:
            ok(str(result))
        else:
            ok("Done.")
        return True
    except TimeoutError as e:
        warn(f"Timeout: {e}")
        return False
    except Exception as e:
        err(f"Error: {e}")
        return False

def section(title):
    """Start a new section — resets the skip flag."""
    global _skip_section
    _skip_section = False
    header(title)
    print(f"  {DIM}Press Enter on each step to run it.{RESET}")

# ─────────────────────────────────────────────────────────────────────────────
# Test sections
# ─────────────────────────────────────────────────────────────────────────────

def run_speech(robot):
    section("SPEECH")

    step('say("Hello, I am Pepper")',
         lambda: robot.say("Hello, I am Pepper"))

    step('say("Hallo, ich bin Pepper") in German with animation',
         lambda: robot.say("Hallo, ich bin Pepper", language="German", animated=True))

    step("set_volume(0.8)  →  TTS volume to 80%",
         lambda: robot.set_volume(0.8))

    step("get_volume()  →  read system volume",
         lambda: f"System volume: {robot.get_volume()}")

    step("set_system_volume(70)  →  system volume to 70",
         lambda: robot.set_system_volume(70))


def run_motion(robot):
    section("MOTION & POSTURE")

    step("wakeup()  →  motors on, stand up",
         lambda: robot.wakeup())

    step("go_to_posture('Stand')  →  upright stance",
         lambda: robot.go_to_posture("Stand"))

    step("head_yaw(30)  →  turn head 30° left",
         lambda: robot.head_yaw(30))

    step("head_yaw(-30)  →  turn head 30° right",
         lambda: robot.head_yaw(-30))

    step("head_yaw(0)  →  head back to center",
         lambda: robot.head_yaw(0))

    step("head_pitch(-10)  →  tilt head up 10°",
         lambda: robot.head_pitch(-10))

    step("head_pitch(0)  →  head level again",
         lambda: robot.head_pitch(0))

    step("hand_open('Both')  →  open both hands",
         lambda: robot.hand_open("Both"))

    step("hand_close('Both')  →  close both hands",
         lambda: robot.hand_close("Both"))

    step("rest()  →  relax motors",
         lambda: robot.rest())


def run_navigation(robot):
    section("NAVIGATION")
    warn("Make sure there is at least 1.5 m of clear space in front of Pepper.")

    step("wakeup()  →  motors on before navigation",
         lambda: robot.wakeup())

    step("go_to_posture('Stand')",
         lambda: robot.go_to_posture("Stand"))

    step("move_to(0.5, 0.0)  →  move forward 0.5 m",
         lambda: robot.move_to(0.5, 0.0))

    step("move_to(-0.5, 0.0)  →  move back 0.5 m",
         lambda: robot.move_to(-0.5, 0.0))

    step("move_along(0.2, 0, 0, duration=2)  →  drive forward 2 s then stop",
         lambda: robot.move_along(0.2, 0.0, 0.0, 2.0))


def run_animations(robot):
    section("ANIMATIONS")

    step("get_available_animations()  →  list all names",
         lambda: ", ".join(robot.get_available_animations()))

    step("play_animation('Wave')  →  wave gesture",
         lambda: robot.play_animation("Wave"))

    step("play_animation('Bow')  →  bow",
         lambda: robot.play_animation("Bow"))

    step("play_animation('Yes')  →  nod yes",
         lambda: robot.play_animation("Yes"))

    step("play_animation('No2')  →  shake head",
         lambda: robot.play_animation("No2"))

    step("play_animation('Explain1')  →  explain gesture",
         lambda: robot.play_animation("Explain1"))


def run_leds(robot):
    section("LED CONTROL")

    step("led_fade('FaceLeds', 'red', 1.0)  →  face LEDs turn red",
         lambda: robot.led_fade("FaceLeds", "red", 1.0))

    step("led_fade('FaceLeds', 'blue', 1.0)  →  face LEDs turn blue",
         lambda: robot.led_fade("FaceLeds", "blue", 1.0))

    step("led_fade('ChestLeds', 'green', 0.5)  →  chest LEDs turn green",
         lambda: robot.led_fade("ChestLeds", "green", 0.5))

    step("led_fade('AllLeds', 'yellow', 1.0)  →  all LEDs turn yellow",
         lambda: robot.led_fade("AllLeds", "yellow", 1.0))

    step("led_reset()  →  all LEDs back to white",
         lambda: robot.led_reset())

    step("led_off('AllLeds')  →  all LEDs off",
         lambda: robot.led_off("AllLeds"))

    step("led_on('AllLeds')  →  all LEDs on (white)",
         lambda: robot.led_on("AllLeds"))


def run_tablet(robot):
    section("TABLET DISPLAY")

    step("show_text('Hello from PyPepper!')  →  text on tablet",
         lambda: robot.show_text("Hello from PyPepper!"))

    step("show_text with multiline  →  multiline text on tablet",
         lambda: robot.show_text("PyPepper Test\nLine 2\nLine 3"))

    step("clear_tablet()  →  blank screen",
         lambda: robot.clear_tablet())

    step("show_image from URL  →  image on tablet",
         lambda: robot.show_image("https://image.shutterstock.com/image-photo/royalty-high-quality-free-stock-260nw-1582825999.jpg"))

    step("clear_tablet()  →  blank screen",
         lambda: robot.clear_tablet())


def run_system_info(robot):
    section("SYSTEM INFORMATION")

    step("get_battery_level()  →  battery %",
         lambda: f"Battery: {robot.get_battery_level()}%")

    step("get_robot_name()  →  robot name",
         lambda: f"Name: {robot.get_robot_name()}")

    step("get_system_version()  →  NAOqi version",
         lambda: f"Version: {robot.get_system_version()}")

    step("get_temperature('KneePitch')  →  joint temp in °C",
         lambda: f"KneePitch: {robot.get_temperature('KneePitch'):.1f} °C")


def run_awareness(robot):
    section("AWARENESS & AUTONOMOUS BEHAVIORS")

    step("configure_awareness(background_movement=False, speaking_movement=True)",
         lambda: robot.configure_awareness(
             background_movement=False,
             speaking_movement=True,
         ))

    step("set_tracking_mode('Head')  →  only head follows people",
         lambda: robot.set_tracking_mode("Head"))

    step("wait(3)  →  observe head-only tracking for 3 s",
         lambda: robot.wait(3))

    step("set_tracking_mode('WholeBody')  →  restore full-body tracking",
         lambda: robot.set_tracking_mode("WholeBody"))

    step("configure_awareness(background_movement=True)  →  restore movement",
         lambda: robot.configure_awareness(background_movement=True))


def run_touch_blocking(robot):
    section("TOUCH / BUTTONS  (blocking)")
    warn("Pepper will speak and wait up to 10 s for a physical touch.")

    step("wait_for_touch(['Head'], timeout=10)  →  touch Pepper's head",
         lambda: _touch_test(robot, ["Head"]))

    step("wait_for_touch(all buttons, timeout=10)  →  touch any sensor",
         lambda: _touch_test(robot, None))


def _touch_test(robot, buttons):
    robot.say("Touch me now" if buttons is None else "Touch my head")
    sensor = robot.wait_for_touch(buttons=buttons, timeout=10)
    robot.say(f"Touched {sensor}")
    return f"Sensor: {sensor}"


def run_touch_callback(robot):
    section("TOUCH / BUTTONS  (callback)")
    warn("Pepper will listen for touches for 10 seconds. Touch any sensor.")

    touched = []

    def on_touch(sensor):
        ok(f"  [callback] Touched: {sensor}")
        touched.append(sensor)

    def _run():
        robot.say("Touch me anywhere for 10 seconds")
        robot.on_touch(on_touch)
        robot.wait(10)
        robot.stop_touch_detection()
        return f"Total touches detected: {len(touched)}"

    step("on_touch callback  →  register, wait 10 s, stop", _run)


def run_speech_recognition(robot):
    section("SPEECH RECOGNITION  (blocking)")
    warn("Pepper will listen for keywords. Speak clearly near the robot's microphone.")

    step('wait_for_keyword(["yes","no"], timeout=10)  →  say "yes" or "no"',
         lambda: _speech_test(robot, ["yes", "no"]))

    step('wait_for_keyword(["left","right","stop"], timeout=10)  →  say a direction',
         lambda: _speech_test(robot, ["left", "right", "stop"]))


def _speech_test(robot, keywords):
    robot.say(f"Say one of: {', '.join(keywords)}")
    word = robot.wait_for_keyword(keywords, timeout=10)
    robot.say(f"You said {word}")
    return f"Heard: '{word}'"


def run_face_detection(robot):
    section("FACE DETECTION  (blocking)")
    warn("Stand in front of Pepper. The robot's head camera will scan for faces.")

    step("wait_for_face(timeout=10)  →  stand in front of Pepper",
         lambda: _face_test(robot))


def _face_test(robot):
    robot.say("I am looking for a face")
    count = robot.wait_for_face(timeout=10)
    robot.say(f"I see {count} face" + ("s" if count != 1 else ""))
    return f"Detected {count} face(s)"


def run_qr_detection(robot):
    section("QR CODE DETECTION  (blocking)")
    warn("Hold a QR code in front of Pepper's head camera.")

    step("wait_for_qr(timeout=15)  →  show a QR code",
         lambda: _qr_test(robot))


def _qr_test(robot):
    robot.say("Show me a QR code")
    data = robot.wait_for_qr(timeout=15)
    robot.say(f"QR code says: {data}")
    return f"Scanned: {data}"


def run_camera(robot):
    section("CAMERA")
    warn("Requires numpy and opencv-python: pip install numpy opencv-python")
    warn("Camera windows appear on your development machine (not the robot tablet).")

    step("save_image('test_top.jpg')  →  snapshot from top camera",
         lambda: _camera_save(robot, "test_top.jpg", camera=0))

    step("save_image('test_bottom.jpg', camera=1)  →  snapshot from bottom camera",
         lambda: _camera_save(robot, "test_bottom.jpg", camera=1))

    step("save_image('test_depth.png', camera=2)  →  depth map snapshot",
         lambda: _camera_save(robot, "test_depth.png", camera=2))

    step("show_camera()  →  live stream from top camera (press 'q' to stop)",
         lambda: robot.show_camera(camera=0))

    step("show_camera(camera=2)  →  live depth stream (press 'q' to stop)",
         lambda: robot.show_camera(camera=2))


def _camera_save(robot, path, camera):
    robot.save_image(path, camera=camera)
    camera_names = {0: "top", 1: "bottom", 2: "depth"}
    return f"Saved {camera_names.get(camera, camera)} camera image to {path}"


# ─────────────────────────────────────────────────────────────────────────────
# Main menu
# ─────────────────────────────────────────────────────────────────────────────

SECTIONS = [
    ("Speech",                  run_speech),
    ("Motion & Posture",        run_motion),
    ("Navigation",              run_navigation),
    ("Animations",              run_animations),
    ("LEDs",                    run_leds),
    ("Tablet Display",          run_tablet),
    ("System Information",      run_system_info),
    ("Awareness",               run_awareness),
    ("Touch (blocking)",        run_touch_blocking),
    ("Touch (callback)",        run_touch_callback),
    ("Speech Recognition",      run_speech_recognition),
    ("Face Detection",          run_face_detection),
    ("QR Code Detection",       run_qr_detection),
    ("Camera",                   run_camera),
]

def print_menu():
    print(f"\n  {BOLD}Available test sections:{RESET}")
    for i, (name, _) in enumerate(SECTIONS, 1):
        print(f"    {DIM}{i:2}.{RESET} {name}")
    print(f"\n    {DIM} a.{RESET} Run all sections in order")
    print(f"    {DIM} q.{RESET} Quit")

def choose_sections():
    print_menu()
    while True:
        choice = input(f"\n  {BOLD}Select section(s) to run (e.g. 1 3 5  or  a): {RESET}").strip().lower()
        if choice == "q":
            sys.exit(0)
        if choice == "a":
            return SECTIONS
        parts = choice.split()
        selected = []
        valid = True
        for p in parts:
            if p.isdigit() and 1 <= int(p) <= len(SECTIONS):
                selected.append(SECTIONS[int(p) - 1])
            else:
                err(f"Invalid choice: '{p}'")
                valid = False
                break
        if valid and selected:
            return selected
        warn("Enter numbers from the list, 'a' for all, or 'q' to quit.")


if __name__ == "__main__":
    width = 60
    print(f"\n{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"{BOLD}{CYAN}  PyPepper Interactive Test Runner{RESET}")
    print(f"{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"\n  Robot IP : {BOLD}{ROBOT_IP}{RESET}")
    print(f"  Local IP : {BOLD}{LOCAL_IP or '(not set)'}{RESET}")

    print(f"\n  {DIM}Connecting to Pepper...{RESET}", end=" ", flush=True)
    try:
        robot = PepperRobot(ROBOT_IP, local_ip=LOCAL_IP)
        print(f"{GREEN}Connected!{RESET}")
    except ConnectionError as e:
        print(f"{RED}Failed{RESET}")
        err(str(e))
        sys.exit(1)

    selected = choose_sections()

    try:
        for name, fn in selected:
            fn(robot)

        header("ALL DONE")
        step("say('All tests completed')",
             lambda: robot.say("All tests completed"))

    except SystemExit:
        pass
    except Exception as e:
        err(f"Unexpected error: {e}")
    finally:
        print(f"\n  {DIM}Closing connection...{RESET}", end=" ", flush=True)
        robot.close()
        print(f"{GREEN}Done.{RESET}\n")
