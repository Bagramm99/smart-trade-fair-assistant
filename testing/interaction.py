import sys
from iso_fair_assistant.pypepper import PepperRobot
from pytemi import TemiRobot


ROBOT_IP = "172.30.36.41"
LOCAL_IP = "0.0.0.0"

robot_pepper = PepperRobot(ROBOT_IP, local_ip=LOCAL_IP)
robot_temi = TemiRobot("172.30.36.31")

def interaction_user():
    robot_pepper.say("Hello i'm Pepper your Assistant")
    robot_pepper.say("How can i help you?")
    robot_temi.say("hello i can help you to find a place or any direction.")
def main():
    interaction_user()

if _name__== "__main__":
    main()