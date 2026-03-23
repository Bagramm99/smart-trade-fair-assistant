# simple_pepper.py — Beginner-friendly Pepper example

# ── EVENTS ──
# These are messages Pepper reacts to
EVT_VISITOR_DETECTED = "visitor_detected"
EVT_VISITOR_INTERESTED = "visitor_interested"
EVT_VISITOR_LEFT = "visitor_left"
EVT_RESET = "reset"

# ── STATES ──
# What Pepper is doing now
STATE_IDLE = "idle"
STATE_GREETING = "greeting"
STATE_PRESENTING = "presenting"
STATE_FAREWELL = "farewell"

# Start in idle state
current_state = STATE_IDLE

# ── HANDLERS ──
def greet():
    print("Pepper: Hello! Welcome!")

def present():
    print("Pepper: Let me tell you about our products.")

def farewell():
    print("Pepper: Goodbye! Thank you for visiting!")

# ── SIMPLE FSM ──
def handle_event(event):
    global current_state
    if current_state == STATE_IDLE and event == EVT_VISITOR_DETECTED:
        current_state = STATE_GREETING
        greet()
    elif current_state == STATE_GREETING and event == EVT_VISITOR_INTERESTED:
        current_state = STATE_PRESENTING
        present()
    elif current_state in [STATE_GREETING, STATE_PRESENTING] and event == EVT_VISITOR_LEFT:
        current_state = STATE_FAREWELL
        farewell()
    elif current_state == STATE_FAREWELL and event == EVT_RESET:
        current_state = STATE_IDLE
        print("Pepper is now idle.")
    else:
        print(f"Pepper: I don't know how to handle '{event}' from state '{current_state}'.")

# ── DEMO ──
print(f"Initial state: {current_state}")

# Simulate events
handle_event(EVT_VISITOR_DETECTED)
handle_event(EVT_VISITOR_INTERESTED)
handle_event(EVT_VISITOR_LEFT)
handle_event(EVT_RESET)

print(f"Final state: {current_state}")